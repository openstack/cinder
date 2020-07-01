# Copyright (c) 2019 ShenZhen SandStone Data Technologies Co., Ltd.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
"""Volume Drivers for SandStone distributed storage."""

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import units

from cinder import exception
from cinder.i18n import _
from cinder import interface
from cinder.volume import driver
from cinder.volume.drivers.san import san
from cinder.volume.drivers.sandstone.sds_client import RestCmd

LOG = logging.getLogger(__name__)

sds_opts = [
    cfg.ListOpt("default_sandstone_target_ips",
                default=[],
                help="SandStone default target ip."),
    cfg.StrOpt("sandstone_pool",
               default="",
               help="SandStone storage pool resource name."),
    cfg.DictOpt("initiator_assign_sandstone_target_ip",
                default={},
                help="Support initiator assign target with assign ip.")
]

CONF = cfg.CONF
CONF.register_opts(sds_opts)


class SdsBaseDriver(driver.VolumeDriver):
    """ISCSIDriver base class."""

    # ThirdPartySytems wiki page
    VERSION = '1.0'
    CI_WIKI_NAME = "SandStone_Storage_CI"

    def __init__(self, *args, **kwargs):
        """Init configuration."""
        super(SdsBaseDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(sds_opts)
        self.configuration.append_config_values(san.san_opts)

    def do_setup(self, context):
        """Instantiate common class and login storage system."""
        if not self.configuration:
            msg = _('Configuration is not found.')
            raise exception.InvalidConfigurationValue(msg)
        self.address = self.configuration.san_ip
        self.user = self.configuration.san_login
        self.password = self.configuration.san_password
        self.pool = self.configuration.sandstone_pool
        self.iscsi_info = (self.configuration.
                           initiator_assign_sandstone_target_ip)
        self.default_target_ips = (self.configuration.
                                   default_sandstone_target_ips)
        self.chap_username = self.configuration.chap_username
        self.chap_password = self.configuration.chap_password
        self.suppress_requests_ssl_warnings = (self.configuration.
                                               suppress_requests_ssl_warnings)
        self.client = RestCmd(self.address, self.user, self.password,
                              self.suppress_requests_ssl_warnings)
        LOG.debug("Run sandstone driver setup.")

    def check_for_setup_error(self):
        """Check pool status and exist or not."""
        self.client.login()
        self.poolname_map_poolid = self.client.get_poolid_from_poolname()
        all_pools = self.client.query_pool_info()
        all_pools_name = [p['pool_name'] for p in all_pools
                          if p.get('pool_name')]

        if self.pool not in all_pools_name:
            msg = _('Storage pool %(pool)s does not exist '
                    'in the cluster.') % {'pool': self.pool}
            LOG.error(msg)
            raise exception.InvalidInput(reason=msg)
        pool_status = [p['status'] for p in all_pools
                       if p.get('pool_name') == self.pool]
        if pool_status:
            if ("health" not in pool_status[0].get('state') and
                    pool_status[0].get("progress", 0) != 100):
                LOG.warning('Storage pool: %(poolName)s not healthy.',
                            {"poolName": self.pool})
        if not self.poolname_map_poolid:
            err_msg = _('poolname_map_poolid info is empty.')
            self._raise_exception(err_msg)
        self.poolid = self.poolname_map_poolid.get(self.pool)
        if not self.poolid:
            err_msg = _('poolid is None.')
            self._raise_exception(err_msg)

    def _update_volume_stats(self, pool_name):
        """Get cluster capability and capacity."""
        data, pool = {}, {}
        data['pools'] = []

        cluster_capacity = self.client.query_capacity_info()
        total_capacity_gb = (float(cluster_capacity.get("capacity_bytes", 0))
                             / units.Gi)
        free_capacity_gb = (float(cluster_capacity.get("free_bytes", 0))
                            / units.Gi)

        self._stats = pool.update(dict(
            pool_name = pool_name,
            vendor_name = 'SandStone USP',
            driver_version = self.VERSION,
            total_capacity_gb = total_capacity_gb,
            free_capacity_gb = free_capacity_gb,
            QoS_support=True,
            thin_provisioning_support=True,
            multiattach=False,
        ))
        data['pools'].append(pool)
        return data

    def _raise_exception(self, msg):
        LOG.error(msg)
        raise exception.VolumeBackendAPIException(data=msg)

    def create_volume(self, volume):
        """Create a volume."""
        capacity_bytes = int(volume.size) * units.Gi
        self.client.create_lun(capacity_bytes, self.poolid, volume.name)

    def delete_volume(self, volume):
        """Delete a volume."""
        LOG.debug("Delete volume %(volumeName)s from pool %(poolId)s",
                  {"volumeName": volume.name,
                   "poolId": self.poolid})
        self.client.delete_lun(self.poolid, volume.name)

    def migrate_volume(self, ctxt, volume, host, new_type=None):
        """Migrate a volume within the same array."""
        return (False, None)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Create a volume from a snapshot.

        We use LUNcopy to copy a new volume from snapshot.
        The time needed increases as volume size does.
        """
        if snapshot.volume:
            source_vol_name = snapshot.volume.name
            source_vol_size = snapshot.volume.size * units.Gi
            destination_vol_name = volume.name
            destination_vol_size = volume.size * units.Gi
            snapshot_name = snapshot.name

            self.client.create_lun_from_snapshot(snapshot_name,
                                                 source_vol_name,
                                                 self.poolid,
                                                 destination_vol_name)
            if destination_vol_size > source_vol_size:
                self.client.extend_lun(destination_vol_size,
                                       self.poolid, volume.name)
        else:
            err_msg = _('No such snapshot volume.')
            self._raise_exception(err_msg)

    def create_cloned_volume(self, dst_volume, src_volume):
        """Clone a new volume from an existing volume."""
        if not self._check_volume_exist(src_volume.name):
            msg = (_('Source volume: %(volume_name)s does not exist.')
                   % {'volume_name': src_volume.name})
            self._raise_exception(msg)
        self.client.create_lun_from_lun(dst_volume.name, self.poolid,
                                        src_volume.name)
        dst_vol_size = dst_volume.size * units.Gi
        src_vol_size = src_volume.size * units.Gi
        if dst_vol_size > src_vol_size:
            self.client.extend_lun(dst_vol_size, self.poolid, dst_volume.name)

    def _check_volume_exist(self, volume):
        return self.client.query_lun_by_name(volume, self.poolid)

    def extend_volume(self, volume, new_size):
        """Extend a volume."""
        old_volume = self._check_volume_exist(volume.name)
        if not old_volume:
            msg = (_('Not exist volume: %(volumeName)s')
                   % {"volumeName": volume.name})
            self._raise_exception(msg)

        old_size = old_volume.get("capacity_bytes")
        new_size = new_size * units.Gi
        if new_size == old_size:
            LOG.info("New size is equal to the real size from backend "
                     "storage, no need to extend. "
                     "realsize: %(oldsize)s, newsize: %(newsize)s.",
                     {"oldsize": old_size,
                      "newsize": new_size})
            return

        if new_size < old_size:
            msg = (_("New size should be bigger than the real size from "
                     "backend storage. "
                     "realsize: %(oldsize)s, newsize: %(newsize)s.")
                   % {"oldsize": old_size,
                      "newsize": new_size})
            self._raise_exception(msg)

        LOG.info(
            'Extend volume: %(volumename)s, '
            'oldsize: %(oldsize)s, newsize: %(newsize)s.',
            {"volumename": volume.name,
             "oldsize": old_size,
             "newsize": new_size})
        self.client.extend_lun(new_size, self.poolid, volume.name)

    def create_snapshot(self, snapshot):
        """Create snapshot from volume."""
        volume = snapshot.volume

        if not volume:
            msg = (_("Can't get volume id from snapshot, snapshot: %(id)s.")
                   % {"id": snapshot.id})
            self._raise_exception(msg)

        LOG.debug(
            "create snapshot from volumeName: %(volume)s, "
            "snap name: %(snapshot)s.",
            {"snapshot": snapshot.name,
             "volume": volume.name},)
        self.client.create_snapshot(self.poolid,
                                    volume.name,
                                    snapshot.name)

    def _check_snapshot_exist(self, snapshot):
        return self.client.query_snapshot_by_name(snapshot.volume.name,
                                                  self.poolid,
                                                  snapshot.name)

    def delete_snapshot(self, snapshot):
        """Delete volume's snapshot."""
        snapshot_name = snapshot.name
        volume_name = snapshot.volume.name

        if not self._check_snapshot_exist(snapshot):
            LOG.debug("not exist snapshot: %(snapshotName)s",
                      {"snapshotName": snapshot.name})

        LOG.info(
            'stop_snapshot: snapshot name: %(snapshot)s, '
            'volume name: %(volume)s.',
            {"snapshot": snapshot_name,
             "volume": volume_name},)

        self.client.delete_snapshot(self.poolid,
                                    volume_name,
                                    snapshot_name)

    def retype(self, ctxt, volume, new_type, diff, host):
        """Convert the volume to be of the new type."""
        LOG.debug("Enter retype: id=%(id)s, new_type=%(new_type)s, "
                  "diff=%(diff)s, host=%(host)s.", {'id': volume.id,
                                                    'new_type': new_type,
                                                    'diff': diff,
                                                    'host': host})

    def create_export(self, context, volume, connector):
        """Export a volume."""
        pass

    def ensure_export(self, context, volume):
        """Synchronously recreate an export for a volume."""
        pass

    def remove_export(self, context, volume):
        """Remove an export for a volume."""
        pass

    def create_export_snapshot(self, context, snapshot, connector):
        """Export a snapshot."""
        pass

    def remove_export_snapshot(self, context, snapshot):
        """Remove an export for a snapshot."""
        pass

    def backup_use_temp_snapshot(self):
        """The config option has a default to be False, So just return it."""
        pass

    def unmanage(self, volume):
        """Export SandStone volume from Cinder."""
        LOG.debug("Unmanage volume: %s.", volume.id)

    def unmanage_snapshot(self, snapshot):
        """Unmanage the specified snapshot from Cinder management."""
        LOG.debug("Unmanage snapshot: %s.", snapshot.id)


@interface.volumedriver
class SdsISCSIDriver(SdsBaseDriver, driver.ISCSIDriver):
    """ISCSI driver for SandStone storage arrays.

    Version history:

    .. code-block:: none

        1.0.0 - Initial driver
                Provide SandStone storage
                create volume support
                delete volume support
                create snapshot support
                delete snapshot support
                extend volume support
                create volume from snap support
                create cloned volume support
                nova volume-attach support
                nova volume-detach support
    """

    VERSION = "1.0.0"

    def get_volume_stats(self, refresh):
        """Get volume status and capality."""
        data = SdsBaseDriver.get_volume_stats(self, refresh)
        backend_name = self.configuration.safe_get('volume_backend_name')
        data['volume_backend_name'] = backend_name or self.__class__.__name__
        data['storage_protocol'] = 'iSCSI'
        data['driver_version'] = self.VERSION
        data['vendor_name'] = 'SandStone USP'
        return data

    def _check_target_exist(self, target_name):
        """Check target name exist or not."""
        return self.client.query_target_by_name(target_name)

    def _check_initiator_exist(self, initiator_name):
        """Check initiator name exist or not."""
        return self.client.query_initiator_by_name(initiator_name)

    def _check_target_added_initiator(self, target_name, initiator_name):
        return self.client.query_target_initiatoracl(target_name,
                                                     initiator_name)

    def _check_target_added_lun(self, target_name, poolid, volume_name):
        return self.client.query_target_lunacl(target_name, poolid,
                                               volume_name)

    def _check_target_added_chap(self, target_name, username):
        return self.client.query_chapinfo_by_target(target_name, username)

    def _get_target_ip(self, initiator):
        ini = self.iscsi_info.get(initiator)
        if ini:
            target_ips = [ip.strip() for ip in ini.split(',')
                          if ip.strip()]
        else:
            target_ips = []

        # If not specify target IP for some initiators, use default IP.
        if not target_ips:
            if self.default_target_ips:
                target_ips = self.default_target_ips
            else:
                msg = (_(
                    'get_iscsi_params: Failed to get target IP '
                    'for initiator %(ini)s, please check config file.')
                    % {'ini': initiator})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

        return target_ips

    def initialize_connection(self, volume, connector):
        """Map a volume to a host and return target iSCSI information."""
        initiator_name = connector['initiator']
        LOG.info(
            "initiator name: %(initiator_name)s, "
            "LUN ID: %(lun_id)s.",
            {"initiator_name": initiator_name,
             "lun_id": volume.name})

        # Create target
        iqn_end = initiator_name.split(':')[-1]
        target_head = 'iqn.2014-10.com.szsandstone:storage:'
        target_name = target_head + iqn_end
        target_ips = self._get_target_ip(initiator_name)
        if not self._check_target_exist(iqn_end):
            targetip_to_hostid = (self.client.
                                  query_node_by_targetips(target_ips))
            self.client.create_target(iqn_end, targetip_to_hostid)
        else:
            # Target is exist, get target_name and nodes
            LOG.info("target is exist, don't repeat to create, "
                     "iscsi_iqn: %(iscsi_iqn)s.",
                     {"iscsi_iqn": target_name})

        LOG.info("initialize_connection, iscsi_iqn: %(iscsi_iqn)s, "
                 'target_ips: %(target_ips)s.',
                 {'iscsi_iqn': target_name,
                  'target_ips': target_ips})
        # Check initiator isn't exist
        if not self._check_initiator_exist(initiator_name):
            # Create initiator and add in storage
            self.client.create_initiator(initiator_name)
        else:
            LOG.info("initiator is exist, don't repeat to create "
                     "initiator: %(initiator_name)s.",
                     {"initiator_name": initiator_name})

        # Check target added initiator or not
        if not self._check_target_added_initiator(iqn_end,
                                                  initiator_name):
            # Add initiator to target
            self.client.add_initiator_to_target(iqn_end,
                                                initiator_name)
        else:
            LOG.info("initiator is added to target, no action needed, "
                     "target: %(target_name)s, "
                     "initiator: %(initiator_name)s.",
                     {"initiator_name": initiator_name,
                      "target_name": target_name})

        lun_id = self._check_target_added_lun(iqn_end,
                                              self.poolid, volume.name)
        if not lun_id:
            # Mapping lun to target
            self.client.mapping_lun(iqn_end, self.poolid,
                                    volume.name, self.pool)
            lun_id = self._check_target_added_lun(iqn_end,
                                                  self.poolid, volume.name)
        else:
            LOG.info("lun is added to target, don't repeat to add "
                     "volume: %(volume_name)s, target: %(target_name)s.",
                     {"volume_name": volume.name,
                      "target_name": target_name})

        # Mapping lungroup and hostgroup to view.
        LOG.info("initialize_connection, host lun id is: %(lun_id)d.",
                 {"lun_id": lun_id})

        # Return iSCSI properties.
        properties = {}
        properties['target_discovered'] = True
        properties['volume_id'] = volume.id
        multipath = connector.get('multipath', False)
        hostlun_id = lun_id
        if not multipath:
            properties['target_portal'] = ("%s:3260" % target_ips[0])
            properties['target_iqn'] = target_name
            properties['target_lun'] = hostlun_id
        else:
            properties['target_iqns'] = [target_name for i in
                                         range(len(target_ips))]
            properties['target_portals'] = [
                "%s:3260" % ip for ip in target_ips]
            properties['target_luns'] = [hostlun_id] * len(target_ips)

        # If use CHAP, return CHAP info.
        if self.chap_username and self.chap_password:
            if not self._check_target_added_chap(iqn_end, self.chap_username):
                self.client.add_chap_by_target(iqn_end, self.chap_username,
                                               self.chap_password)
            else:
                LOG.info("chap username: %(chap_username)s exist, don't "
                         "repeat to create, iscsi_iqn: %(iscsi_iqn)s.",
                         {"iscsi_iqn": target_name,
                          "chap_username": self.chap_username})

            properties['auth_method'] = 'CHAP'
            properties['auth_username'] = self.chap_username
            properties['auth_password'] = self.chap_password

        LOG.info("initialize_connection success. Return data: %(properties)s.",
                 {"properties": properties})
        return {'driver_volume_type': 'iscsi', 'data': properties}

    def terminate_connection(self, volume, connector, **kwargs):
        """Delete map between a volume and a host."""
        if not connector:
            target_name = self.client.query_target_by_lun(volume.name,
                                                          self.poolid)
            self.client.unmap_lun(target_name, self.poolid,
                                  volume.name, self.pool)
            return
        initiator_name = connector['initiator']
        # Remove lun from target force.
        iqn_end = initiator_name.split(':')[-1]
        target_head = 'iqn.2014-10.com.szsandstone:storage:'
        target_name = target_head + iqn_end
        self.client.unmap_lun(iqn_end, self.poolid, volume.name, self.pool)
        LOG.info(
            "terminate_connection: initiator name: %(ini)s, "
            "LUN ID: %(lunid)s, "
            "Target Name: %(target_name)s.",
            {"ini": initiator_name,
             "lunid": volume.name,
             "target_name": target_name})
