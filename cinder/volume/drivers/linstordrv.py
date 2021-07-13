#  Copyright (c) 2014-2019 LINBIT HA Solutions GmbH
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

See https://docs.linbit.com/docs/users-guide-9.0/#ch-openstack-linstor
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
from cinder.volume import volume_utils

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
                    'specifies the block size.'),

    cfg.IntOpt('linstor_autoplace_count',
               default=0,
               help='Autoplace replication count on volume deployment. '
                    '0 = Full cluster replication without autoplace, '
                    '1 = Single node deployment without replication, '
                    '2 or greater = Replicated deployment with autoplace.'),

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
DISKLESS = 'DISKLESS'
LVM = 'LVM'
LVM_THIN = 'LVM_THIN'
ZFS = 'ZFS'
ZFS_THIN = 'ZFS_THIN'


class LinstorBaseDriver(driver.VolumeDriver):
    """Cinder driver that uses LINSTOR for storage.

    Version history:

    .. code-block:: none

        1.0.0 - Initial driver
        1.0.1 - Added support for LINSTOR 0.9.12
    """

    VERSION = '1.0.1'

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
        self.ap_count = self.configuration.safe_get(
            'linstor_autoplace_count')
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
            api_reply = lin.resource_list()[0].__dict__['_rest_data']
            return api_reply

    def _get_api_resource_dfn_list(self):
        with lin_drv(self.default_uri) as lin:
            if not lin.connected:
                lin.connect()
            api_reply = lin.resource_dfn_list()[0].__dict__['_rest_data']
            return api_reply

    def _get_api_node_list(self):
        with lin_drv(self.default_uri) as lin:
            if not lin.connected:
                lin.connect()
            api_reply = lin.node_list()[0].__dict__['_rest_data']
            return api_reply

    def _get_api_storage_pool_dfn_list(self):
        with lin_drv(self.default_uri) as lin:
            if not lin.connected:
                lin.connect()
            api_reply = lin.storage_pool_dfn_list()[0].__dict__['_rest_data']
            return api_reply

    def _get_api_storage_pool_list(self):
        with lin_drv(self.default_uri) as lin:
            if not lin.connected:
                lin.connect()
            api_reply = lin.storage_pool_list()[0].__dict__['_rest_data']
            return api_reply

    def _get_api_volume_extend(self, rsc_target_name, new_size):
        with lin_drv(self.default_uri) as lin:
            if not lin.connected:
                lin.connect()

            vol_reply = lin.volume_dfn_modify(
                rsc_name=rsc_target_name,
                volume_nr=0,
                size=self._vol_size_to_linstor(new_size))
            return vol_reply

    def _api_snapshot_create(self, drbd_rsc_name, snapshot_name):
        lin = linstor.Resource(drbd_rsc_name, uri=self.default_uri)
        snap_reply = lin.snapshot_create(snapshot_name)
        return snap_reply

    def _api_snapshot_delete(self, drbd_rsc_name, snapshot_name):
        lin = linstor.Resource(drbd_rsc_name, uri=self.default_uri)
        snap_reply = lin.snapshot_delete(snapshot_name)
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

    def _api_rsc_autoplace(self, rsc_name):
        with lin_drv(self.default_uri) as lin:
            if not lin.connected:
                lin.connect()

            new_rsc = linstor.Resource(name=rsc_name, uri=self.default_uri)
            new_rsc.placement.redundancy = self.ap_count
            new_rsc.placement.storage_pool = self.default_pool
            rsc_reply = new_rsc.autoplace()

            return rsc_reply

    def _api_rsc_delete(self, rsc_name, node_name):
        with lin_drv(self.default_uri) as lin:
            if not lin.connected:
                lin.connect()

            rsc_reply = lin.resource_delete(node_name=node_name,
                                            rsc_name=rsc_name)
            return rsc_reply

    def _api_rsc_auto_delete(self, rsc_name):
        with lin_drv(self.default_uri) as lin:
            if not lin.connected:
                lin.connect()

            rsc = linstor.Resource(str(rsc_name), self.default_uri)
            return rsc.delete()

    def _api_rsc_is_diskless(self, rsc_name):
        with lin_drv(self.default_uri) as lin:
            if not lin.connected:
                lin.connect()

            rsc = linstor.Resource(str(rsc_name))
            return rsc.is_diskless(self.host_name)

    def _api_rsc_size(self, rsc_name):
        with lin_drv(self.default_uri) as lin:
            if not lin.connected:
                lin.connect()

            rsc = linstor.Resource(str(rsc_name))
            if len(rsc.volumes):
                if "size" in rsc.volumes:
                    return rsc.volumes[0].size
                else:
                    return 0
            else:
                return 0

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
                                       src_rsc_name,
                                       src_snap_name,
                                       new_vol_name):

        lin = linstor.Resource(src_rsc_name, uri=self.default_uri)
        new_rsc = lin.restore_from_snapshot(src_snap_name, new_vol_name)

        # Adds an aux/property KV for synchronous return from snapshot restore
        with lin_drv(self.default_uri) as lin:
            if not lin.connected:
                lin.connect()

            aux_prop = {}
            aux_prop["Aux/restore"] = "done"
            lin.volume_dfn_modify(
                rsc_name=new_vol_name,
                volume_nr=0,
                set_properties=aux_prop)

        if new_rsc.name == new_vol_name:
            return True
        return False

    def _get_rsc_path(self, rsc_name):
        rsc_list_reply = self._get_api_resource_list()

        if rsc_list_reply:
            for rsc in rsc_list_reply:
                if (rsc["name"] == rsc_name and
                        rsc["node_name"] == self.host_name):
                    for volume in rsc["volumes"]:
                        if volume["volume_number"] == 0:
                            return volume["device_path"]

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

        if spd_list_reply:
            for spd in spd_list_reply:
                spd_list.append(spd["storage_pool_name"])

        return spd_list

    def _get_storage_pool(self):
        # Fetch Storage Pool List
        sp_list_reply = self._get_api_storage_pool_list()

        # Separate the diskless nodes
        sp_diskless_list = []
        sp_list = []
        node_count = 0

        if sp_list_reply:
            for node in sp_list_reply:
                if node["storage_pool_name"] == self.default_pool:
                    sp_node = {}
                    sp_node["node_name"] = node["node_name"]
                    sp_node["sp_uuid"] = node["uuid"]
                    sp_node["sp_name"] = node["storage_pool_name"]

                    if node["provider_kind"] == DISKLESS:
                        diskless = True
                        sp_node["sp_free"] = -1.0
                        sp_node["sp_cap"] = -1.0
                        sp_node["sp_allocated"] = 0.0
                    else:
                        diskless = False
                        if "free_capacity" in node:
                            temp = float(node["free_capacity"]) / units.Mi
                            sp_node["sp_free"] = round(temp)
                            temp = float(node["total_capacity"]) / units.Mi
                            sp_node["sp_cap"] = round(temp)

                    drivers = [LVM, LVM_THIN, ZFS, ZFS_THIN, DISKLESS]

                    # Driver selection
                    if node["provider_kind"] in drivers:
                        sp_node['driver_name'] = node["provider_kind"]
                    else:
                        sp_node['driver_name'] = str(node["provider_kind"])

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
        data["vendor_name"] = "LINBIT"
        data["driver_version"] = self.VERSION
        data["pools"] = []

        sp_data = self._get_storage_pool()
        rd_list = self._get_resource_definitions()

        # Total volumes and capacity
        num_vols = 0
        for rd in rd_list:
            num_vols += 1

        # allocated_sizes_gb = []
        free_gb = []
        total_gb = []
        thin_enabled = False

        # Total & Free capacity for Local Node
        single_pool = {}
        for sp in sp_data:
            if "Diskless" not in sp["driver_name"]:
                thin_backends = [LVM_THIN, ZFS_THIN]
                if sp["driver_name"] in thin_backends:
                    thin_enabled = True
                if "sp_cap" in sp:
                    if sp["sp_cap"] >= 0.0:
                        total_gb.append(sp["sp_cap"])
                if "sp_free" in sp:
                    if sp["sp_free"] >= 0.0:
                        free_gb.append(sp["sp_free"])

        # Allocated capacity
        sp_allocated_size_gb = 0.0
        local_resources = []

        reply = self._get_api_resource_list()

        if reply:
            for rsc in reply:
                if rsc["node_name"] == self.host_name:
                    local_resources.append(rsc["name"])

            for rsc_name in local_resources:
                if not self._api_rsc_is_diskless(rsc_name):
                    rsc_size = self._api_rsc_size(rsc_name)
                    sp_allocated_size_gb += round(
                        int(rsc_size) / units.Gi, 2)

        single_pool["pool_name"] = data["volume_backend_name"]
        single_pool["free_capacity_gb"] = min(free_gb) if free_gb else 0
        single_pool["total_capacity_gb"] = min(total_gb) if total_gb else 0
        single_pool["provisioned_capacity_gb"] = sp_allocated_size_gb
        single_pool["reserved_percentage"] = (
            self.configuration.reserved_percentage)
        single_pool["thin_provisioning_support"] = thin_enabled
        single_pool["thick_provisioning_support"] = not thin_enabled
        single_pool["max_over_subscription_ratio"] = (
            self.configuration.max_over_subscription_ratio)
        single_pool["location_info"] = self.default_uri
        single_pool["total_volumes"] = num_vols
        single_pool["filter_function"] = self.get_filter_function()
        single_pool["goodness_function"] = self.get_goodness_function()
        single_pool["QoS_support"] = False
        single_pool["multiattach"] = False
        single_pool["backend_state"] = "up"

        data["pools"].append(single_pool)

        return data

    def _get_resource_definitions(self):

        rd_list_reply = self._get_api_resource_dfn_list()
        rd_list = []

        if rd_list_reply:
            for node in rd_list_reply:
                # Count only Cinder volumes
                if DM_VN_PREFIX in node['name']:
                    rd_node = {}
                    rd_node["rd_uuid"] = node['uuid']
                    rd_node["rd_name"] = node['name']
                    rd_list.append(rd_node)

        return rd_list

    def _get_snapshot_nodes(self, resource):
        """Returns all available resource nodes for snapshot.

        However, it excludes diskless nodes.
        """
        rsc_list_reply = self._get_api_resource_list()
        snap_list = []

        if rsc_list_reply:
            for rsc in rsc_list_reply:
                if rsc["name"] != resource:
                    continue

                # Diskless nodes are not available for snapshots
                diskless = False
                if "flags" in rsc:
                    if 'DISKLESS' in rsc["flags"]:
                        diskless = True
                if not diskless:
                    snap_list.append(rsc["node_name"])

        return snap_list

    def _get_diskless_nodes(self, resource):
        # Returns diskless nodes given a resource
        rsc_list_reply = self._get_api_resource_list()
        diskless_list = []

        if rsc_list_reply:
            for rsc in rsc_list_reply:
                if rsc["name"] != resource:
                    continue

                if "flags" in rsc:
                    if DISKLESS in rsc["flags"]:
                        diskless_list.append(rsc["node_name"])

        return diskless_list

    def _get_linstor_nodes(self):
        # Returns all available LINSTOR nodes
        node_list_reply = self._get_api_node_list()
        node_list = []

        if node_list_reply:
            for node in node_list_reply:
                node_list.append(node["name"])

        return node_list

    def _get_nodes(self):
        # Returns all LINSTOR nodes in a dict list
        node_list_reply = self._get_api_node_list()
        node_list = []

        if node_list_reply:
            for node in node_list_reply:
                node_item = {}
                node_item["node_name"] = node["name"]
                node_item["node_address"] = (
                    node["net_interfaces"][0]["address"])
                node_list.append(node_item)

        return node_list

    def _check_api_reply(self, api_response, noerror_only=False):
        if noerror_only:
            # Checks if none of the replies has an error
            return lin_drv.all_api_responses_no_error(api_response)
        else:
            # Check if all replies are success
            return lin_drv.all_api_responses_success(api_response)

    def _copy_vol_to_image(self, context, image_service, image_meta, rsc_path,
                           volume):

        return volume_utils.upload_volume(context,
                                          image_service,
                                          image_meta,
                                          rsc_path,
                                          volume)

    #
    # Snapshot
    #
    def create_snapshot(self, snapshot):
        snap_name = self._snapshot_name_from_cinder_snapshot(snapshot)
        rsc_name = self._drbd_resource_name_from_cinder_snapshot(snapshot)

        snap_reply = self._api_snapshot_create(drbd_rsc_name=rsc_name,
                                               snapshot_name=snap_name)

        if not snap_reply:
            msg = 'ERROR creating a LINSTOR snapshot {}'.format(snap_name)
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(msg)

    def delete_snapshot(self, snapshot):
        snapshot_name = self._snapshot_name_from_cinder_snapshot(snapshot)
        rsc_name = self._drbd_resource_name_from_cinder_snapshot(snapshot)

        snap_reply = self._api_snapshot_delete(rsc_name, snapshot_name)

        if not snap_reply:
            msg = 'ERROR deleting a LINSTOR snapshot {}'.format(snapshot_name)
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(msg)

        # Delete RD if no other RSC are found
        if not self._get_snapshot_nodes(rsc_name):
            self._api_rsc_dfn_delete(rsc_name)

    def create_volume_from_snapshot(self, volume, snapshot):
        src_rsc_name = self._drbd_resource_name_from_cinder_snapshot(snapshot)
        src_snap_name = self._snapshot_name_from_cinder_snapshot(snapshot)
        new_vol_name = self._drbd_resource_name_from_cinder_volume(volume)

        # If no autoplace, manually build a cluster list
        if self.ap_count == 0:
            diskless_nodes = []
            nodes = []
            for node in self._get_storage_pool():

                if DISKLESS in node['driver_name']:
                    diskless_nodes.append(node['node_name'])
                    continue

                # Filter out controller node if it is diskless
                if self.diskless and node['node_name'] == self.host_name:
                    continue
                else:
                    nodes.append(node['node_name'])

        reply = self._api_snapshot_resource_restore(src_rsc_name,
                                                    src_snap_name,
                                                    new_vol_name)
        if not reply:
            msg = _('Error on restoring a LINSTOR volume')
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        # Manually add the controller node as a resource if diskless
        if self.diskless:
            reply = self._api_rsc_create(rsc_name=new_vol_name,
                                         node_name=self.host_name,
                                         diskless=self.diskless)

        # Add any other diskless nodes only if not autoplaced
        if self.ap_count == 0 and diskless_nodes:
            for node in diskless_nodes:
                self._api_rsc_create(rsc_name=new_vol_name,
                                     node_name=node,
                                     diskless=True)

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
                failed_volume = {}
                failed_volume['id'] = volume['id']
                self.delete_volume(failed_volume)

                msg = _('Error on extending LINSTOR resource size')
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

    def create_volume(self, volume):

        # Check for Storage Pool List
        sp_data = self._get_storage_pool()
        rsc_size = volume['size']

        # No existing Storage Pools found
        if not sp_data:

            # Check for Nodes
            node_list = self._get_nodes()

            if not node_list:
                msg = _('No LINSTOR resource nodes available / configured')
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

            # Create Storage Pool
            spd_list = self._get_spd()

            if spd_list:
                spd_name = spd_list[0]

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

                if not self._check_api_reply(sp_reply, noerror_only=True):
                    msg = _('Could not create a LINSTOR storage pool')
                    LOG.error(msg)
                    raise exception.VolumeBackendAPIException(data=msg)

        # Check for RD
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

        if not self._check_api_reply(rsc_dfn_reply, noerror_only=True):
            msg = _("Error creating a LINSTOR resource definition")
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        # Create a New VD
        vd_size = self._vol_size_to_linstor(rsc_size)
        vd_reply = self._api_volume_dfn_create(rsc_name=rsc_name,
                                               size=int(vd_size))

        if not self._check_api_reply(vd_reply, noerror_only=True):
            msg = _("Error creating a LINSTOR volume definition")
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        # Create LINSTOR Resources
        ctrl_in_sp = False
        for node in sp_data:
            # Check if controller is in the pool
            if node['node_name'] == self.host_name:
                ctrl_in_sp = True

        # Use autoplace to deploy if set
        if self.ap_count:
            try:
                self._api_rsc_autoplace(rsc_name=rsc_name)

            except Exception:
                msg = _("Error creating autoplaces LINSTOR resource(s)")
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

        # Otherwise deploy across the entire cluster
        else:
            for node in sp_data:
                # Deploy resource on each node
                if DISKLESS in node['driver_name']:
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
                msg = _("Error creating a LINSTOR controller resource")
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

        return {}

    def delete_volume(self, volume):
        drbd_rsc_name = self._drbd_resource_name_from_cinder_volume(volume)
        rsc_list_reply = self._get_api_resource_list()
        diskful_nodes = self._get_snapshot_nodes(drbd_rsc_name)
        diskless_nodes = self._get_diskless_nodes(drbd_rsc_name)

        # If autoplace was used, use Resource class
        if self.ap_count:

            rsc_reply = self._api_rsc_auto_delete(drbd_rsc_name)
            if not rsc_reply:
                msg = _("Error deleting an autoplaced LINSTOR resource")
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

        # Delete all resources in a cluster manually if not autoplaced
        else:
            if rsc_list_reply:
                # Remove diskless nodes first
                if diskless_nodes:
                    for node in diskless_nodes:
                        rsc_reply = self._api_rsc_delete(
                            node_name=node,
                            rsc_name=drbd_rsc_name)
                        if not self._check_api_reply(rsc_reply,
                                                     noerror_only=True):
                            msg = _("Error deleting a diskless LINSTOR rsc")
                            LOG.error(msg)
                            raise exception.VolumeBackendAPIException(data=msg)

                # Remove diskful nodes
                if diskful_nodes:
                    for node in diskful_nodes:
                        rsc_reply = self._api_rsc_delete(
                            node_name=node,
                            rsc_name=drbd_rsc_name)
                        if not self._check_api_reply(rsc_reply,
                                                     noerror_only=True):
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
            msg = _("ERROR extending a LINSTOR volume")
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
        # self.create_volume(volume) already called by Cinder, and works
        full_rsc_name = self._drbd_resource_name_from_cinder_volume(volume)

        # This creates a LINSTOR volume from the source image
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
                                rsc_path,
                                volume)
        return {}

    # Not supported currently
    def migrate_volume(self, ctxt, volume, host, thin=False, mirror_count=0):
        return (False, None)

    def check_for_setup_error(self):
        msg = None
        if linstor is None:
            msg = _('Linstor python package not found')

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
    """Cinder iSCSI driver that uses LINSTOR for storage."""

    def __init__(self, *args, **kwargs):
        super(LinstorIscsiDriver, self).__init__(*args, **kwargs)

        # iSCSI target_helper
        if 'h_name' in kwargs:
            self.helper_name = kwargs.get('h_name')
            self.helper_driver = self.helper_name
            self.target_driver = None
        else:
            self.helper_name = self.configuration.safe_get('iscsi_helper')
            self.helper_driver = self.target_mapping[self.helper_name]
            self.target_driver = importutils.import_object(
                self.helper_driver,
                configuration=self.configuration,
                executor=self._execute)

        LOG.info('START: LINSTOR DRBD driver %s', self.helper_name)

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
    """Cinder DRBD driver that uses LINSTOR for storage."""

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
