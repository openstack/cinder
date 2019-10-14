# Copyright (c) 2016 EMC Corporation.
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
"""Cinder Driver for EMC VNX based on CLI."""

from oslo_log import log as logging

from cinder import interface
from cinder.volume import driver
from cinder.volume.drivers.dell_emc.vnx import adapter
from cinder.volume.drivers.dell_emc.vnx import common
from cinder.volume.drivers.dell_emc.vnx import utils
from cinder.zonemanager import utils as zm_utils


LOG = logging.getLogger(__name__)


@interface.volumedriver
class VNXDriver(driver.ManageableVD,
                driver.ManageableSnapshotsVD,
                driver.MigrateVD,
                driver.BaseVD):
    """Dell EMC Cinder Driver for VNX using CLI.

    .. code-block:: default

      Version history:
          1.0.0 - Initial driver
          2.0.0 - Thick/thin provisioning, robust enhancement
          3.0.0 - Array-based Backend Support, FC Basic Support,
                  Target Port Selection for MPIO,
                  Initiator Auto Registration,
                  Storage Group Auto Deletion,
                  Multiple Authentication Type Support,
                  Storage-Assisted Volume Migration,
                  SP Toggle for HA
          3.0.1 - Security File Support
          4.0.0 - Advance LUN Features (Compression Support,
                  Deduplication Support, FAST VP Support,
                  FAST Cache Support), Storage-assisted Retype,
                  External Volume Management, Read-only Volume,
                  FC Auto Zoning
          4.1.0 - Consistency group support
          5.0.0 - Performance enhancement, LUN Number Threshold Support,
                  Initiator Auto Deregistration,
                  Force Deleting LUN in Storage Groups,
                  robust enhancement
          5.1.0 - iSCSI multipath enhancement
          5.2.0 - Pool-aware scheduler support
          5.3.0 - Consistency group modification support
          6.0.0 - Over subscription support
                  Create consistency group from cgsnapshot support
                  Multiple pools support enhancement
                  Manage/unmanage volume revise
                  White list target ports support
                  Snap copy support
                  Support efficient non-disruptive backup
          7.0.0 - Clone consistency group support
                  Replication v2 support(managed)
                  Configurable migration rate support
          8.0.0 - New VNX Cinder driver
          9.0.0 - Use asynchronous migration for cloning
          10.0.0 - Extend SMP size before async migration when cloning from an
                   image cache volume
          10.1.0 - Add QoS support
          10.2.0 - Add replication group support
          11.0.0 - Fix failure of migration during cloning
          12.0.0 - Add `volume revert to snapshot` support
          12.1.0 - Adjust max_luns_per_storage_group and
                   check_max_pool_luns_threshold
          12.1.1 - Fix perf issue when create/delete volume
          13.0.0 - Fix bug https://bugs.launchpad.net/cinder/+bug/1817385 to
                   make sure sg can be created again after it was destroyed
                   under `destroy_empty_stroage_group` setting to `True`
          13.0.1 - Fix bug 1794646: failed to delete LUNs from backend due to
                   the temporary snapshots on them wasn't deleted.
    """

    VERSION = '13.00.01'
    VENDOR = 'Dell EMC'
    # ThirdPartySystems wiki page
    CI_WIKI_NAME = "EMC_VNX_CI"

    def __init__(self, *args, **kwargs):
        super(VNXDriver, self).__init__(*args, **kwargs)
        utils.init_ops(self.configuration)
        self.protocol = self.configuration.storage_protocol.lower()
        self.active_backend_id = kwargs.get('active_backend_id', None)
        self.adapter = None
        self._stats = {}

    @staticmethod
    def get_driver_options():
        return common.VNX_OPTS

    def do_setup(self, context):
        if self.protocol == common.PROTOCOL_FC:
            self.adapter = adapter.FCAdapter(self.configuration,
                                             self.active_backend_id)
        else:
            self.adapter = adapter.ISCSIAdapter(self.configuration,
                                                self.active_backend_id)
        self.adapter.VERSION = self.VERSION
        self.adapter.do_setup()

    def check_for_setup_error(self):
        pass

    def create_volume(self, volume):
        """Creates a volume."""
        return self.adapter.create_volume(volume)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot."""
        return self.adapter.create_volume_from_snapshot(volume, snapshot)

    def create_cloned_volume(self, volume, src_vref):
        """Creates a cloned volume."""
        return self.adapter.create_cloned_volume(volume, src_vref)

    def extend_volume(self, volume, new_size):
        """Extend a volume."""
        self.adapter.extend_volume(volume, new_size)

    def delete_volume(self, volume):
        """Deletes a volume."""
        self.adapter.delete_volume(volume)

    def migrate_volume(self, ctxt, volume, host):
        """Migrate volume via EMC migration functionality."""
        return self.adapter.migrate_volume(ctxt, volume, host)

    def retype(self, ctxt, volume, new_type, diff, host):
        """Convert the volume to be of the new type."""
        return self.adapter.retype(ctxt, volume, new_type, diff, host)

    def create_snapshot(self, snapshot):
        """Creates a snapshot."""
        self.adapter.create_snapshot(snapshot)

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""
        self.adapter.delete_snapshot(snapshot)

    def revert_to_snapshot(self, context, volume, snapshot):
        """Reverts a volume to a snapshot"""
        self.adapter.restore_snapshot(volume, snapshot)

    def ensure_export(self, context, volume):
        """Driver entry point to get the export info for an existing volume."""
        pass

    def create_export(self, context, volume, connector):
        """Driver entry point to get the export info for a new volume."""
        pass

    def remove_export(self, context, volume):
        """Driver entry point to remove an export for a volume."""
        pass

    def check_for_export(self, context, volume_id):
        """Make sure volume is exported."""
        pass

    def initialize_connection(self, volume, connector):
        """Initializes the connection and returns connection info.

        Assign any created volume to a compute node/host so that it can be
        used from that host.

        The  driver returns a driver_volume_type of 'fibre_channel'.
        The target_wwn can be a single entry or a list of wwns that
        correspond to the list of remote wwn(s) that will export the volume.
        The initiator_target_map is a map that represents the remote wwn(s)
        and a list of wwns which are visible to the remote wwn(s).
        Example return values:
        FC:

        .. code-block:: json

            {
                'driver_volume_type': 'fibre_channel'
                'data': {
                    'target_discovered': True,
                    'target_lun': 1,
                    'target_wwn': ['1234567890123', '0987654321321'],
                    'initiator_target_map': {
                        '1122334455667788': ['1234567890123',
                                             '0987654321321']
                    }
                }
            }

        iSCSI:

        .. code-block:: json

            {
                'driver_volume_type': 'iscsi'
                'data': {
                    'target_discovered': True,
                    'target_iqns': ['iqn.2010-10.org.openstack:volume-00001',
                                    'iqn.2010-10.org.openstack:volume-00002'],
                    'target_portals': ['127.0.0.1:3260', '127.0.1.1:3260'],
                    'target_luns': [1, 1],
                }
            }

        """
        LOG.debug("Entering initialize_connection"
                  " - connector: %(connector)s.",
                  {'connector': connector})
        conn_info = self.adapter.initialize_connection(volume,
                                                       connector)
        LOG.debug("Exit initialize_connection"
                  " - Returning connection info: %(conn_info)s.",
                  {'conn_info': conn_info})
        zm_utils.add_fc_zone(conn_info)
        return conn_info

    def terminate_connection(self, volume, connector, **kwargs):
        """Disallow connection from connector."""
        LOG.debug("Entering terminate_connection"
                  " - connector: %(connector)s.",
                  {'connector': connector})
        conn_info = self.adapter.terminate_connection(volume, connector)
        LOG.debug("Exit terminate_connection"
                  " - Returning connection info: %(conn_info)s.",
                  {'conn_info': conn_info})
        zm_utils.remove_fc_zone(conn_info)
        return conn_info

    def get_volume_stats(self, refresh=False):
        """Get volume stats.

        :param refresh: True to get updated data
        """
        if refresh:
            self.update_volume_stats()

        return self._stats

    def update_volume_stats(self):
        """Retrieve stats info from volume group."""
        LOG.debug("Updating volume stats.")
        self._stats = self.adapter.update_volume_stats()
        self._stats['driver_version'] = self.VERSION
        self._stats['vendor_name'] = self.VENDOR

    def manage_existing(self, volume, existing_ref):
        """Manage an existing lun in the array.

        The lun should be in a manageable pool backend, otherwise
        error would return.
        Rename the backend storage object so that it matches the,
        volume['name'] which is how drivers traditionally map between a
        cinder volume and the associated backend storage object.

        .. code-block:: python

          manage_existing_ref:{
              'source-id':<lun id in VNX>
          }

        or

        .. code-block:: python

          manage_existing_ref:{
              'source-name':<lun name in VNX>
          }

        """
        return self.adapter.manage_existing(volume, existing_ref)

    def manage_existing_get_size(self, volume, existing_ref):
        """Return size of volume to be managed by manage_existing."""
        return self.adapter.manage_existing_get_size(volume, existing_ref)

    def get_pool(self, volume):
        """Returns the pool name of a volume."""
        return self.adapter.get_pool_name(volume)

    def unmanage(self, volume):
        """Unmanages a volume."""
        return self.adapter.unmanage(volume)

    def update_migrated_volume(self, context, volume, new_volume,
                               original_volume_status=None):
        """Returns model update for migrated volume."""
        return self.adapter.update_migrated_volume(context, volume, new_volume,
                                                   original_volume_status)

    def create_export_snapshot(self, context, snapshot, connector):
        """Creates a snapshot mount point for snapshot."""
        return self.adapter.create_export_snapshot(
            context, snapshot, connector)

    def remove_export_snapshot(self, context, snapshot):
        """Removes snapshot mount point for snapshot."""
        return self.adapter.remove_export_snapshot(context, snapshot)

    def initialize_connection_snapshot(self, snapshot, connector, **kwargs):
        """Allows connection to snapshot."""
        return self.adapter.initialize_connection_snapshot(snapshot,
                                                           connector,
                                                           **kwargs)

    def terminate_connection_snapshot(self, snapshot, connector, **kwargs):
        """Disallows connection to snapshot."""
        return self.adapter.terminate_connection_snapshot(snapshot,
                                                          connector,
                                                          **kwargs)

    def backup_use_temp_snapshot(self):
        return True

    def failover_host(self, context, volumes, secondary_id=None, groups=None):
        """Fail-overs volumes from primary device to secondary."""
        return self.adapter.failover_host(context, volumes, secondary_id,
                                          groups)

    @utils.require_consistent_group_snapshot_enabled
    def create_group(self, context, group):
        """Creates a group."""
        return self.adapter.create_group(context, group)

    @utils.require_consistent_group_snapshot_enabled
    def delete_group(self, context, group, volumes):
        """Deletes a group."""
        return self.adapter.delete_group(
            context, group, volumes)

    @utils.require_consistent_group_snapshot_enabled
    def update_group(self, context, group,
                     add_volumes=None, remove_volumes=None):
        """Updates a group."""
        return self.adapter.update_group(context, group,
                                         add_volumes,
                                         remove_volumes)

    @utils.require_consistent_group_snapshot_enabled
    def create_group_from_src(self, context, group, volumes,
                              group_snapshot=None, snapshots=None,
                              source_group=None, source_vols=None):
        """Creates a group from source."""
        if group_snapshot:
            return self.adapter.create_group_from_group_snapshot(
                context, group, volumes, group_snapshot, snapshots)
        elif source_group:
            return self.adapter.create_cloned_group(
                context, group, volumes, source_group, source_vols)

    @utils.require_consistent_group_snapshot_enabled
    def create_group_snapshot(self, context, group_snapshot, snapshots):
        """Creates a group_snapshot."""
        return self.adapter.create_group_snapshot(
            context, group_snapshot, snapshots)

    @utils.require_consistent_group_snapshot_enabled
    def delete_group_snapshot(self, context, group_snapshot, snapshots):
        """Deletes a group_snapshot."""
        return self.adapter.delete_group_snapshot(
            context, group_snapshot, snapshots)

    def is_consistent_group_snapshot_enabled(self):
        return self._stats.get('consistent_group_snapshot_enabled')

    def enable_replication(self, context, group, volumes):
        return self.adapter.enable_replication(context, group, volumes)

    def disable_replication(self, context, group, volumes):
        return self.adapter.disable_replication(context, group, volumes)

    def failover_replication(self, context, group, volumes,
                             secondary_backend_id):
        return self.adapter.failover_replication(
            context, group, volumes, secondary_backend_id)

    def get_replication_error_status(self, context, groups):
        return self.adapter.get_replication_error_status(context, groups)
