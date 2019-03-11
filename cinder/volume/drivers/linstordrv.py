#  Copyright (c) 2014-2018 LINBIT HA Solutions GmbH
#  All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License"); you may
#  not use this file except in compliance with the License. You may obtain
#  a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#  WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#  License for the specific language governing permissions and limitations
#  under the License.

"""This driver connects Cinder to an installed LINSTOR instance.

See https://docs.linbit.com/docs/users-guide-9.0/#ch-openstack
for more details.
"""

import socket
import uuid

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import importutils
from oslo_utils import units

from cinder import exception
from cinder.i18n import _
from cinder.image import image_utils
from cinder import interface
from cinder.volume import configuration
from cinder.volume import driver

try:
    import google.protobuf.json_format as proto
except ImportError:
    proto = None

try:
    import linstor
    lin_drv = linstor.Linstor
except ImportError:
    linstor = None
    lin_drv = None

# To override these values, update cinder.conf in /etc/cinder/
linstor_opts = [
    cfg.StrOpt('linstor_default_volume_group_name',
               default='drbd-vg',
               help='Default Volume Group name for LINSTOR. '
                    'Not Cinder Volume.'),

    cfg.StrOpt('linstor_default_uri',
               default='linstor://localhost',
               help='Default storage URI for LINSTOR.'),

    cfg.StrOpt('linstor_default_storage_pool_name',
               default='DfltStorPool',
               help='Default Storage Pool name for LINSTOR.'),

    cfg.FloatOpt('linstor_volume_downsize_factor',
                 default=4096,
                 help='Default volume downscale size in KiB = 4 MiB.'),

    cfg.IntOpt('linstor_default_blocksize',
               default=4096,
               help='Default Block size for Image restoration. '
                    'When using iSCSI transport, this option '
                    'specifies the block size'),

    cfg.BoolOpt('linstor_controller_diskless',
                default=True,
                help='True means Cinder node is a diskless LINSTOR node.')
]

LOG = logging.getLogger(__name__)

CONF = cfg.CONF
CONF.register_opts(linstor_opts, group=configuration.SHARED_CONF_GROUP)

CINDER_UNKNOWN = 'unknown'
DM_VN_PREFIX = 'CV_'
DM_SN_PREFIX = 'SN_'
LVM = 'Lvm'
LVMTHIN = 'LvmThin'


class LinstorBaseDriver(driver.VolumeDriver):
    """Cinder driver that uses Linstor for storage."""

    VERSION = '1.0.0'

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = 'LINBIT_LINSTOR_CI'

    def __init__(self, *args, **kwargs):
        super(LinstorBaseDriver, self).__init__(*args, **kwargs)
        LOG.debug('START: Base Init Linstor')

        self.configuration.append_config_values(linstor_opts)
        self.default_pool = self.configuration.safe_get(
            'linstor_default_storage_pool_name')
        self.default_uri = self.configuration.safe_get(
            'linstor_default_uri')
        self.default_downsize_factor = self.configuration.safe_get(
            'linstor_volume_downsize_factor')
        self.default_vg_name = self.configuration.safe_get(
            'linstor_default_volume_group_name')
        self.default_blocksize = self.configuration.safe_get(
            'linstor_default_blocksize')
        self.diskless = self.configuration.safe_get(
            'linstor_controller_diskless')
        self.default_backend_name = self.configuration.safe_get(
            'volume_backend_name')
        self.host_name = socket.gethostname()

    @staticmethod
    def get_driver_options():
        return linstor_opts

    def _ping(self):
        with lin_drv(self.default_uri) as lin:
            return lin.ping()

    def _clean_uuid(self):
        """Returns a UUID string, WITHOUT braces."""
        # Some uuid library versions put braces around the result.
        # We don't want them, just a plain [0-9a-f-]+ string.
        uuid_str = str(uuid.uuid4())
        uuid_str = uuid_str.replace("{", "")
        uuid_str = uuid_str.replace("}", "")
        return uuid_str

    # LINSTOR works in kiB units; Cinder uses GiB.
    def _vol_size_to_linstor(self, size):
        return int(size * units.Mi - self.default_downsize_factor)

    def _vol_size_to_cinder(self, size):
        return int(size / units.Mi)

    def _is_clean_volume_name(self, name, prefix):
        try:
            if (name.startswith(CONF.volume_name_template % "") and
                    uuid.UUID(name[7:]) is not None):
                return prefix + name[7:]
        except ValueError:
            return None

        try:
            if uuid.UUID(name) is not None:
                return prefix + name
        except ValueError:
            return None

    def _snapshot_name_from_cinder_snapshot(self, snapshot):
        sn_name = self._is_clean_volume_name(snapshot['id'], DM_SN_PREFIX)
        return sn_name

    def _cinder_volume_name_from_drbd_resource(self, rsc_name):
        cinder_volume_name = rsc_name.split(DM_VN_PREFIX)[1]
        return cinder_volume_name

    def _drbd_resource_name_from_cinder_snapshot(self, snapshot):
        drbd_resource_name = '{}{}'.format(DM_VN_PREFIX,
                                           snapshot['volume_id'])
        return drbd_resource_name

    def _drbd_resource_name_from_cinder_volume(self, volume):
        drbd_resource_name = '{}{}'.format(DM_VN_PREFIX, volume['id'])
        return drbd_resource_name

    def _get_api_resource_list(self):
        with lin_drv(self.default_uri) as lin:
            if not lin.connected:
                lin.connect()

            response = proto.MessageToDict(lin.resource_list()[0].proto_msg)
        return response

    def _get_api_resource_dfn_list(self):
        with lin_drv(self.default_uri) as lin:
            if not lin.connected:
                lin.connect()

            response = proto.MessageToDict(
                lin.resource_dfn_list()[0].proto_msg)
            return response

    def _get_api_nodes_list(self):
        with lin_drv(self.default_uri) as lin:
            if not lin.connected:
                lin.connect()

            response = proto.MessageToDict(lin.node_list()[0].proto_msg)
            return response

    def _get_api_storage_pool_dfn_list(self):
        with lin_drv(self.default_uri) as lin:
            if not lin.connected:
                lin.connect()

            response = proto.MessageToDict(
                lin.storage_pool_dfn_list()[0].proto_msg)
            return response

    def _get_api_storage_pool_list(self):
        with lin_drv(self.default_uri) as lin:
            if not lin.connected:
                lin.connect()

            response = proto.MessageToDict(
                lin.storage_pool_list()[0].proto_msg)
            return response

    def _get_api_volume_extend(self, rsc_target_name, new_size):
        with lin_drv(self.default_uri) as lin:
            if not lin.connected:
                lin.connect()

            vol_reply = lin.volume_dfn_modify(
                rsc_name=rsc_target_name,
                volume_nr=0,
                size=self._vol_size_to_linstor(new_size))
            return vol_reply

    def _api_snapshot_create(self, node_names, rsc_name, snapshot_name):
        with lin_drv(self.default_uri) as lin:
            if not lin.connected:
                lin.connect()

            snap_reply = lin.snapshot_create(node_names=node_names,
                                             rsc_name=rsc_name,
                                             snapshot_name=snapshot_name,
                                             async_msg=False)
            return snap_reply

    def _api_snapshot_delete(self, drbd_rsc_name, snap_name):
        with lin_drv(self.default_uri) as lin:
            if not lin.connected:
                lin.connect()

            snap_reply = lin.snapshot_delete(rsc_name=drbd_rsc_name,
                                             snapshot_name=snap_name)
            return snap_reply

    def _api_rsc_dfn_delete(self, drbd_rsc_name):
        with lin_drv(self.default_uri) as lin:
            if not lin.connected:
                lin.connect()

            snap_reply = lin.resource_dfn_delete(drbd_rsc_name)
            return snap_reply

    def _api_storage_pool_create(self,
                                 node_name,
                                 storage_pool_name,
                                 storage_driver,
                                 driver_pool_name):
        with lin_drv(self.default_uri) as lin:
            if not lin.connected:
                lin.connect()

            sp_reply = lin.storage_pool_create(
                node_name=node_name,
                storage_pool_name=storage_pool_name,
                storage_driver=storage_driver,
                driver_pool_name=driver_pool_name)
            return sp_reply

    def _api_rsc_dfn_create(self, rsc_name):
        with lin_drv(self.default_uri) as lin:
            if not lin.connected:
                lin.connect()

            rsc_dfn_reply = lin.resource_dfn_create(rsc_name)
            return rsc_dfn_reply

    def _api_volume_dfn_create(self, rsc_name, size):
        with lin_drv(self.default_uri) as lin:
            if not lin.connected:
                lin.connect()

            vol_dfn_reply = lin.volume_dfn_create(
                rsc_name=rsc_name,
                storage_pool=self.default_pool,
                size=size)
            return vol_dfn_reply

    def _api_volume_dfn_set_sp(self, rsc_target_name):
        with lin_drv(self.default_uri) as lin:
            if not lin.connected:
                lin.connect()

            snap_reply = lin.volume_dfn_modify(
                rsc_name=rsc_target_name,
                volume_nr=0,
                set_properties={
                    'StorPoolName': self.default_pool
                })
            return snap_reply

    def _api_rsc_create(self, rsc_name, node_name, diskless=False):
        with lin_drv(self.default_uri) as lin:
            if not lin.connected:
                lin.connect()

            if diskless:
                storage_pool = None
            else:
                storage_pool = self.default_pool

            new_rsc = linstor.ResourceData(rsc_name=rsc_name,
                                           node_name=node_name,
                                           storage_pool=storage_pool,
                                           diskless=diskless)

            rsc_reply = lin.resource_create([new_rsc], async_msg=False)
            return rsc_reply

    def _api_rsc_delete(self, rsc_name, node_name):
        with lin_drv(self.default_uri) as lin:
            if not lin.connected:
                lin.connect()

            rsc_reply = lin.resource_delete(node_name=node_name,
                                            rsc_name=rsc_name)
            return rsc_reply

    def _api_volume_dfn_delete(self, rsc_name, volume_nr):
        with lin_drv(self.default_uri) as lin:
            if not lin.connected:
                lin.connect()

            rsc_reply = lin.volume_dfn_delete(rsc_name=rsc_name,
                                              volume_nr=volume_nr)
            return rsc_reply

    def _api_snapshot_volume_dfn_restore(self,
                                         src_rsc_name,
                                         src_snap_name,
                                         new_vol_name):
        with lin_drv(self.default_uri) as lin:
            if not lin.connected:
                lin.connect()

            vol_reply = lin.snapshot_volume_definition_restore(
                from_resource=src_rsc_name,
                from_snapshot=src_snap_name,
                to_resource=new_vol_name)
            return vol_reply

    def _api_snapshot_resource_restore(self,
                                       nodes,
                                       src_rsc_name,
                                       src_snap_name,
                                       new_vol_name):
        with lin_drv(self.default_uri) as lin:
            if not lin.connected:
                lin.connect()

            rsc_reply = lin.snapshot_resource_restore(
                node_names=nodes,
                from_resource=src_rsc_name,
                from_snapshot=src_snap_name,
                to_resource=new_vol_name)
            return rsc_reply

    def _get_rsc_path(self, rsc_name):
        rsc_list_reply = self._get_api_resource_list()

        for rsc in rsc_list_reply['resources']:
            if rsc['name'] == rsc_name and rsc['nodeName'] == self.host_name:
                for volume in rsc['vlms']:
                    if volume['vlmNr'] == 0:
                        return volume['devicePath']

    def _get_local_path(self, volume):
        try:
            full_rsc_name = (
                self._drbd_resource_name_from_cinder_volume(volume))

            return self._get_rsc_path(full_rsc_name)

        except Exception:
            message = _('Local Volume not found.')
            raise exception.VolumeBackendAPIException(data=message)

    def _get_spd(self):
        # Storage Pool Definition List
        spd_list_reply = self._get_api_storage_pool_dfn_list()

        spd_list = []
        for node in spd_list_reply['storPoolDfns']:
            spd_item = {}
            spd_item['spd_uuid'] = node['uuid']
            spd_item['spd_name'] = node['storPoolName']
            spd_list.append(spd_item)

        return spd_list

    def _get_storage_pool(self):
        # Fetch Storage Pool List
        sp_list_reply = self._get_api_storage_pool_list()

        # Fetch Resource Definition List
        sp_list = []

        # Separate the diskless nodes
        sp_diskless_list = []
        node_count = 0

        if sp_list_reply:
            for node in sp_list_reply['storPools']:
                if node['storPoolName'] == self.default_pool:
                    sp_node = {}
                    sp_node['node_uuid'] = node['nodeUuid']
                    sp_node['node_name'] = node['nodeName']
                    sp_node['sp_uuid'] = node['storPoolUuid']
                    sp_node['sp_name'] = node['storPoolName']
                    sp_node['sp_vlms_uuid'] = []
                    if 'vlms' in node:
                        for vlm in node['vlms']:
                            sp_node['sp_vlms_uuid'].append(vlm['vlmDfnUuid'])

                    if 'Diskless' in node['driver']:
                        diskless = True
                        sp_node['sp_free'] = -1.0
                        sp_node['sp_cap'] = 0.0
                    else:
                        diskless = False
                        if 'freeSpace' in node:
                            sp_node['sp_free'] = round(
                                int(node['freeSpace']['freeCapacity']) /
                                units.Mi,
                                2)
                            sp_node['sp_cap'] = round(
                                int(node['freeSpace']['totalCapacity']) /
                                units.Mi,
                                2)

                            # Driver
                    if node['driver'] == "LvmDriver":
                        sp_node['driver_name'] = LVM
                    elif node['driver'] == "LvmThinDriver":
                        sp_node['driver_name'] = LVMTHIN
                    else:
                        sp_node['driver_name'] = node['driver']

                    if diskless:
                        sp_diskless_list.append(sp_node)
                    else:
                        sp_list.append(sp_node)
                    node_count += 1

        # Add the diskless nodes to the end of the list
        if sp_diskless_list:
            sp_list.extend(sp_diskless_list)

        return sp_list

    def _get_volume_stats(self):

        data = {}
        data["volume_backend_name"] = self.default_backend_name
        data["vendor_name"] = 'LINBIT'
        data["driver_version"] = self.VERSION
        data["pools"] = []

        sp_data = self._get_storage_pool()
        rd_list = self._get_resource_definitions()

        # Total volumes and capacity
        num_vols = 0
        for rd in rd_list:
            num_vols += 1

        allocated_sizes_gb = []
        free_capacity_gb = []
        total_capacity_gb = []
        thin_enabled = False

        # Free capacity for Local Node
        single_pool = {}
        for sp in sp_data:
            if 'Diskless' not in sp['driver_name']:
                if 'LvmThin' in sp['driver_name']:
                    thin_enabled = True
                if 'sp_cap' in sp:
                    if sp['sp_cap'] >= 0.0:
                        total_capacity_gb.append(sp['sp_cap'])
                if 'sp_free' in sp:
                    if sp['sp_free'] >= 0.0:
                        free_capacity_gb.append(sp['sp_free'])
                sp_allocated_size_gb = 0
                for vlm_uuid in sp['sp_vlms_uuid']:
                    for rd in rd_list:
                        if 'vlm_dfn_uuid' in rd:
                            if rd['vlm_dfn_uuid'] == vlm_uuid:
                                sp_allocated_size_gb += rd['rd_size']
                allocated_sizes_gb.append(sp_allocated_size_gb)

        single_pool["pool_name"] = data["volume_backend_name"]
        single_pool["free_capacity_gb"] = min(free_capacity_gb)
        single_pool["total_capacity_gb"] = min(total_capacity_gb)
        single_pool['provisioned_capacity_gb'] = max(allocated_sizes_gb)
        single_pool["reserved_percentage"] = (
            self.configuration.reserved_percentage)
        single_pool['thin_provisioning_support'] = thin_enabled
        single_pool['thick_provisioning_support'] = not thin_enabled
        single_pool['max_over_subscription_ratio'] = (
            self.configuration.max_over_subscription_ratio)
        single_pool["location_info"] = self.default_uri
        single_pool["total_volumes"] = num_vols
        single_pool["filter_function"] = self.get_filter_function()
        single_pool["goodness_function"] = self.get_goodness_function()
        single_pool["QoS_support"] = False
        single_pool["multiattach"] = False
        single_pool["backend_state"] = 'up'

        data["pools"].append(single_pool)

        return data

    def _get_resource_definitions(self):

        rd_list = []

        rd_list_reply = self._get_api_resource_dfn_list()

        # Only if resource definition present
        if 'rscDfns' in rd_list_reply:
            for node in rd_list_reply['rscDfns']:

                # Count only Cinder volumes
                if DM_VN_PREFIX in node['rscName']:
                    rd_node = {}
                    rd_node['rd_uuid'] = node['rscDfnUuid']
                    rd_node['rd_name'] = node['rscName']
                    rd_node['rd_port'] = node['rscDfnPort']

                    if 'vlmDfns' in node:
                        for vol in node['vlmDfns']:
                            if vol['vlmNr'] == 0:
                                rd_node['vlm_dfn_uuid'] = vol['vlmDfnUuid']
                                rd_node['rd_size'] = round(
                                    float(vol['vlmSize']) / units.Mi, 2)
                                break

                    rd_list.append(rd_node)

        return rd_list

    def _get_snapshot_nodes(self, resource):
        """Returns all available resource nodes for snapshot.

        However, it excludes diskless nodes.
        """

        rsc_list_reply = self._get_api_resource_list()  # reply in dict

        snap_list = []
        for rsc in rsc_list_reply['resources']:
            if rsc['name'] != resource:
                continue

            # Diskless nodes are not available for snapshots
            diskless = False
            if 'rscFlags' in rsc:
                if 'DISKLESS' in rsc['rscFlags']:
                    diskless = True
            if not diskless:
                snap_list.append(rsc['nodeName'])

        return snap_list

    def _get_linstor_nodes(self):
        # Returns all available DRBD nodes
        node_list_reply = self._get_api_nodes_list()

        node_list = []
        for node in node_list_reply['nodes']:
            node_list.append(node['name'])

        return node_list

    def _get_nodes(self):
        # Get Node List
        node_list_reply = self._get_api_nodes_list()

        node_list = []
        if node_list_reply:
            for node in node_list_reply['nodes']:
                node_item = {}
                node_item['node_name'] = node['name']
                node_item['node_uuid'] = node['uuid']
                node_item['node_address'] = (
                    node['netInterfaces'][0]['address'])
                node_list.append(node_item)

        return node_list

    def _check_api_reply(self, api_response, noerror_only=False):
        if noerror_only:
            # Checks if none of the replies has an error
            return lin_drv.all_api_responses_no_error(api_response)
        else:
            # Check if all replies are success
            return lin_drv.all_api_responses_success(api_response)

    def _copy_vol_to_image(self, context, image_service, image_meta, rsc_path):

        return image_utils.upload_volume(context,
                                         image_service,
                                         image_meta,
                                         rsc_path)

    #
    # Snapshot
    #
    def create_snapshot(self, snapshot):
        snap_name = self._snapshot_name_from_cinder_snapshot(snapshot)
        drbd_rsc_name = self._drbd_resource_name_from_cinder_snapshot(snapshot)
        node_names = self._get_snapshot_nodes(drbd_rsc_name)

        snap_reply = self._api_snapshot_create(node_names=node_names,
                                               rsc_name=drbd_rsc_name,
                                               snapshot_name=snap_name)

        if not self._check_api_reply(snap_reply, noerror_only=True):
            msg = 'ERROR creating a LINSTOR snapshot {}'.format(snap_name)
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(msg)

    def delete_snapshot(self, snapshot):
        snap_name = self._snapshot_name_from_cinder_snapshot(snapshot)
        drbd_rsc_name = self._drbd_resource_name_from_cinder_snapshot(snapshot)

        snap_reply = self._api_snapshot_delete(drbd_rsc_name, snap_name)

        if not self._check_api_reply(snap_reply, noerror_only=True):
            msg = 'ERROR deleting a LINSTOR snapshot {}'.format(snap_name)
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(msg)

        # Delete RD if no other RSC are found
        if not self._get_snapshot_nodes(drbd_rsc_name):
            self._api_rsc_dfn_delete(drbd_rsc_name)

    def create_volume_from_snapshot(self, volume, snapshot):
        src_rsc_name = self._drbd_resource_name_from_cinder_snapshot(snapshot)
        src_snap_name = self._snapshot_name_from_cinder_snapshot(snapshot)
        new_vol_name = self._drbd_resource_name_from_cinder_volume(volume)

        # New RD
        rsc_reply = self._api_rsc_dfn_create(new_vol_name)

        if not self._check_api_reply(rsc_reply):
            msg = _('Error on creating LINSTOR Resource Definition')
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        # New VD from Snap
        reply = self._api_snapshot_volume_dfn_restore(src_rsc_name,
                                                      src_snap_name,
                                                      new_vol_name)
        if not self._check_api_reply(reply, noerror_only=True):
            msg = _('Error on restoring LINSTOR Volume Definition')
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        # Set StorPoolName property on VD
        reply = self._api_volume_dfn_set_sp(new_vol_name)
        if not self._check_api_reply(reply):
            msg = _('Error on restoring LINSTOR Volume StorPoolName property')
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        # New RSC from Snap
        # Assumes restoring to all the nodes containing the storage pool
        # unless diskless
        nodes = []
        for node in self._get_storage_pool():

            if 'Diskless' in node['driver_name']:
                continue

            # Filter out controller node if LINSTOR is diskless
            if self.diskless and node['node_name'] == self.host_name:
                continue
            else:
                nodes.append(node['node_name'])

        reply = self._api_snapshot_resource_restore(nodes,
                                                    src_rsc_name,
                                                    src_snap_name,
                                                    new_vol_name)
        if not self._check_api_reply(reply, noerror_only=True):
            msg = _('Error on restoring LINSTOR resources')
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        # Manually add the controller node as a resource if diskless
        if self.diskless:
            reply = self._api_rsc_create(rsc_name=new_vol_name,
                                         node_name=self.host_name,
                                         diskless=self.diskless)

        # Upsize if larger volume than original snapshot
        src_rsc_size = int(snapshot['volume_size'])
        new_vol_size = int(volume['size'])

        if new_vol_size > src_rsc_size:

            upsize_target_name = self._is_clean_volume_name(volume['id'],
                                                            DM_VN_PREFIX)
            reply = self._get_api_volume_extend(
                rsc_target_name=upsize_target_name,
                new_size=new_vol_size)

            if not self._check_api_reply(reply, noerror_only=True):
                # Delete failed volume
                failed_volume = []
                failed_volume['id'] = volume['id']
                self.delete_volume(failed_volume)

                msg = _('Error on extending LINSTOR resource size')
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

    def create_volume(self, volume):
        # Check for Storage Pool List
        sp_data = self._get_storage_pool()
        rsc_size = 1
        rsc_size = volume['size']

        # No existing Storage Pools found
        if not sp_data:

            # Check for Nodes
            node_list = self._get_nodes()

            if not node_list:
                msg = _('No LINSTOR resource nodes available / configured')
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

            # Create Storage Pool (definition is implicit)
            spd_list = self._get_spd()

            if spd_list:
                spd_name = spd_list[0]['spd_name']

            for node in node_list:

                node_driver = None
                for sp in sp_data:
                    if sp['node_name'] == node['node_name']:
                        node_driver = sp['driver_name']

                sp_reply = self._api_storage_pool_create(
                    node_name=node['node_name'],
                    storage_pool_name=spd_name,
                    storage_driver=node_driver,
                    driver_pool_name=self.default_vg_name)

                if not self._check_api_reply(sp_reply):
                    msg = _('Could not create a LINSTOR storage pool')
                    LOG.error(msg)
                    raise exception.VolumeBackendAPIException(data=msg)

        # # Check for RD
        # If Retyping from another volume, use parent/origin uuid
        # as a name source
        if (volume['migration_status'] is not None and
                str(volume['migration_status']).find('success') == -1):
            src_name = str(volume['migration_status']).split(':')[1]
            rsc_name = self._is_clean_volume_name(str(src_name),
                                                  DM_VN_PREFIX)
        else:
            rsc_name = self._is_clean_volume_name(volume['id'],
                                                  DM_VN_PREFIX)

        # Create a New RD
        rsc_dfn_reply = self._api_rsc_dfn_create(rsc_name)
        if not self._check_api_reply(rsc_dfn_reply,
                                     noerror_only=True):
            msg = _("Error creating a LINSTOR resource definition")
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        # Create a New VD
        vd_size = self._vol_size_to_linstor(rsc_size)
        vd_reply = self._api_volume_dfn_create(rsc_name=rsc_name,
                                               size=int(vd_size))
        if not self._check_api_reply(vd_reply,
                                     noerror_only=True):
            msg = _("Error creating a LINSTOR volume definition")
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        # Create LINSTOR Resources
        ctrl_in_sp = False
        for node in sp_data:

            # Check if controller is in the pool
            if node['node_name'] == self.host_name:
                ctrl_in_sp = True

            # Create resources and,
            # Check only errors when creating diskless resources
            if 'Diskless' in node['driver_name']:
                diskless = True
            else:
                diskless = False
            rsc_reply = self._api_rsc_create(rsc_name=rsc_name,
                                             node_name=node['node_name'],
                                             diskless=diskless)

            if not self._check_api_reply(rsc_reply, noerror_only=True):
                msg = _("Error creating a LINSTOR resource")
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

        # If the controller is diskless and not in the pool, create a diskless
        # resource on it
        if not ctrl_in_sp and self.diskless:
            rsc_reply = self._api_rsc_create(rsc_name=rsc_name,
                                             node_name=self.host_name,
                                             diskless=True)

            if not self._check_api_reply(rsc_reply, noerror_only=True):
                msg = _("Error creating a LINSTOR resource")
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

        return {}

    def delete_volume(self, volume):
        drbd_rsc_name = self._drbd_resource_name_from_cinder_volume(volume)
        rsc_list_reply = self._get_api_resource_list()

        if rsc_list_reply:
            # Delete Resources
            for rsc in rsc_list_reply['resources']:
                if rsc['name'] != drbd_rsc_name:
                    continue

                rsc_reply = self._api_rsc_delete(
                    node_name=rsc['nodeName'],
                    rsc_name=drbd_rsc_name)
                if not self._check_api_reply(rsc_reply, noerror_only=True):
                    msg = _("Error deleting a LINSTOR resource")
                    LOG.error(msg)
                    raise exception.VolumeBackendAPIException(data=msg)

            # Delete VD
            vd_reply = self._api_volume_dfn_delete(drbd_rsc_name, 0)
            if not vd_reply:
                if not self._check_api_reply(vd_reply):
                    msg = _("Error deleting a LINSTOR volume definition")
                    LOG.error(msg)
                    raise exception.VolumeBackendAPIException(data=msg)

            # Delete RD
            # Will fail if snapshot exists but expected
            self._api_rsc_dfn_delete(drbd_rsc_name)

        return True

    def extend_volume(self, volume, new_size):
        rsc_target_name = self._is_clean_volume_name(volume['id'],
                                                     DM_VN_PREFIX)

        extend_reply = self._get_api_volume_extend(rsc_target_name, new_size)

        if not self._check_api_reply(extend_reply, noerror_only=True):
            msg = _("ERROR Linstor Volume Extend")
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

    def create_cloned_volume(self, volume, src_vref):
        temp_id = self._clean_uuid()
        snapshot = {}
        snapshot['id'] = temp_id
        snapshot['volume_id'] = src_vref['id']
        snapshot['volume_size'] = src_vref['size']

        self.create_snapshot(snapshot)

        self.create_volume_from_snapshot(volume, snapshot)

        self.delete_snapshot(snapshot)

    def copy_image_to_volume(self, context, volume, image_service, image_id):
        # self.create_volume(volume) already called by Cinder, and works.
        # Need to check return values
        full_rsc_name = self._drbd_resource_name_from_cinder_volume(volume)

        # This creates a LINSTOR volume at the original size.
        image_utils.fetch_to_raw(context,
                                 image_service,
                                 image_id,
                                 str(self._get_rsc_path(full_rsc_name)),
                                 self.default_blocksize,
                                 size=volume['size'])
        return {}

    def copy_volume_to_image(self, context, volume, image_service, image_meta):
        full_rsc_name = self._drbd_resource_name_from_cinder_volume(volume)
        rsc_path = str(self._get_rsc_path(full_rsc_name))

        self._copy_vol_to_image(context,
                                image_service,
                                image_meta,
                                rsc_path)
        return {}

    # Not supported currently
    def migrate_volume(self, ctxt, volume, host, thin=False, mirror_count=0):
        return (False, None)

    def check_for_setup_error(self):

        msg = None
        if linstor is None:
            msg = _('Linstor python package not found')

        if proto is None:
            msg = _('Protobuf python package not found')

        if msg is not None:
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

    def create_export(self, context, volume, connector):
        pass

    def ensure_export(self, context, volume):
        pass

    def initialize_connection(self, volume, connector, **kwargs):
        pass

    def remove_export(self, context, volume):
        pass

    def terminate_connection(self, volume, connector, **kwargs):
        pass


# Class with iSCSI interface methods
@interface.volumedriver
class LinstorIscsiDriver(LinstorBaseDriver):
    """Cinder iSCSI driver that uses Linstor for storage."""

    def __init__(self, *args, **kwargs):
        super(LinstorIscsiDriver, self).__init__(*args, **kwargs)

        # iSCSI target_helper
        if 'h_name' in kwargs:
            self.helper_name = kwargs.get('h_name')
            self.helper_driver = self.helper_name
            self.target_driver = None
        else:
            self.helper_name = self.configuration.safe_get('target_helper')
            self.helper_driver = self.target_mapping[self.helper_name]
            self.target_driver = importutils.import_object(
                self.helper_driver,
                configuration=self.configuration,
                db=self.db,
                executor=self._execute)

        LOG.info('START: LINSTOR DRBD driver {}'.format(self.helper_name))

    def get_volume_stats(self, refresh=False):
        data = self._get_volume_stats()
        data["storage_protocol"] = 'iSCSI'
        data["pools"][0]["location_info"] = (
            'LinstorIscsiDriver:' + data["pools"][0]["location_info"])

        return data

    def ensure_export(self, context, volume):
        volume_path = self._get_local_path(volume)

        return self.target_driver.ensure_export(
            context,
            volume,
            volume_path)

    def create_export(self, context, volume, connector):
        volume_path = self._get_local_path(volume)

        export_info = self.target_driver.create_export(
            context,
            volume,
            volume_path)

        return {'provider_location': export_info['location'],
                'provider_auth': export_info['auth'], }

    def remove_export(self, context, volume):

        return self.target_driver.remove_export(context, volume)

    def initialize_connection(self, volume, connector, **kwargs):

        return self.target_driver.initialize_connection(volume, connector)

    def validate_connector(self, connector):

        return self.target_driver.validate_connector(connector)

    def terminate_connection(self, volume, connector, **kwargs):

        return self.target_driver.terminate_connection(volume,
                                                       connector,
                                                       **kwargs)


# Class with DRBD transport mode
@interface.volumedriver
class LinstorDrbdDriver(LinstorBaseDriver):
    """Cinder DRBD driver that uses Linstor for storage."""

    def __init__(self, *args, **kwargs):
        super(LinstorDrbdDriver, self).__init__(*args, **kwargs)

    def _return_drbd_config(self, volume):
        full_rsc_name = self._drbd_resource_name_from_cinder_volume(volume)
        rsc_path = self._get_rsc_path(full_rsc_name)
        return {
            'driver_volume_type': 'local',
            'data': {
                "device_path": str(rsc_path)
            }
        }

    def _node_in_sp(self, node_name):
        for pool in self._get_storage_pool():
            if pool['node_name'] == node_name:
                return True
        return False

    def get_volume_stats(self, refresh=False):
        data = self._get_volume_stats()
        data["storage_protocol"] = 'DRBD'
        data["pools"][0]["location_info"] = 'LinstorDrbdDriver:{}'.format(
            data["pools"][0]["location_info"])

        return data

    def initialize_connection(self, volume, connector, **kwargs):
        node_name = connector['host']
        if not self._node_in_sp(connector['host']):

            full_rsc_name = self._drbd_resource_name_from_cinder_volume(volume)
            rsc_reply = self._api_rsc_create(rsc_name=full_rsc_name,
                                             node_name=node_name,
                                             diskless=True)
            if not self._check_api_reply(rsc_reply, noerror_only=True):
                msg = _('Error on creating LINSTOR Resource')
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

        return self._return_drbd_config(volume)

    def terminate_connection(self, volume, connector, **kwargs):
        if connector:
            node_name = connector['host']
            if not self._node_in_sp(connector['host']):
                rsc_name = self._drbd_resource_name_from_cinder_volume(volume)
                rsc_reply = self._api_rsc_delete(rsc_name=rsc_name,
                                                 node_name=node_name)
                if not self._check_api_reply(rsc_reply, noerror_only=True):
                    msg = _('Error on deleting LINSTOR Resource')
                    LOG.error(msg)
                    raise exception.VolumeBackendAPIException(data=msg)

    def create_export(self, context, volume, connector):

        return self._return_drbd_config(volume)

    def ensure_export(self, context, volume):

        return self._return_drbd_config(volume)

    def remove_export(self, context, volume):
        pass
