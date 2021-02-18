# Copyright (c) 2016 Dell Inc. or its subsidiaries.
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""Cinder Driver for Unity"""

from oslo_config import cfg
from oslo_log import log as logging
import six

from cinder import interface
from cinder.volume import configuration
from cinder.volume import driver
from cinder.volume.drivers.dell_emc.unity import adapter
from cinder.volume.drivers.dell_emc.unity import replication
from cinder.volume.drivers.san.san import san_opts
from cinder.volume import volume_utils
from cinder.zonemanager import utils as zm_utils

LOG = logging.getLogger(__name__)

CONF = cfg.CONF

UNITY_OPTS = [
    cfg.ListOpt('unity_storage_pool_names',
                default=[],
                help='A comma-separated list of storage pool names to be '
                     'used.'),
    cfg.ListOpt('unity_io_ports',
                default=[],
                help='A comma-separated list of iSCSI or FC ports to be used. '
                     'Each port can be Unix-style glob expressions.'),
    cfg.BoolOpt('remove_empty_host',
                default=False,
                help='To remove the host from Unity when the last LUN is '
                     'detached from it. By default, it is False.')]

CONF.register_opts(UNITY_OPTS, group=configuration.SHARED_CONF_GROUP)


def skip_if_not_cg(func):
    @six.wraps(func)
    def inner(self, *args, **kwargs):
        # Only used to decorating the second argument is `group`
        if volume_utils.is_group_a_cg_snapshot_type(args[1]):
            return func(self, *args, **kwargs)

        LOG.debug('Group is not a consistency group. Unity driver does '
                  'nothing.')
        # This exception will let cinder handle it as a generic group
        raise NotImplementedError()
    return inner


@interface.volumedriver
class UnityDriver(driver.ManageableVD,
                  driver.ManageableSnapshotsVD,
                  driver.BaseVD):
    """Unity Driver.

    .. code-block:: none

      Version history:
        1.0.0 - Initial version
        2.0.0 - Add thin clone support
        3.0.0 - Add IPv6 support
        3.1.0 - Support revert to snapshot API
        4.0.0 - Support remove empty host
        4.2.0 - Support compressed volume
        5.0.0 - Support storage assisted volume migration
        6.0.0 - Support generic group and consistent group
        6.1.0 - Support volume replication
        7.0.0 - Support tiering policy
        7.1.0 - Support consistency group replication
        7.2.0 - Support retype volume
    """

    VERSION = '07.02.00'
    VENDOR = 'Dell EMC'
    # ThirdPartySystems wiki page
    CI_WIKI_NAME = "DellEMC_Unity_CI"

    def __init__(self, *args, **kwargs):
        super(UnityDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(UNITY_OPTS)
        self.configuration.append_config_values(san_opts)

        # active_backend_id is not None if the service is failed over.
        self.active_backend_id = kwargs.get('active_backend_id')
        self.replication_manager = replication.ReplicationManager()
        protocol = self.configuration.storage_protocol
        if protocol.lower() == adapter.PROTOCOL_FC.lower():
            self.protocol = adapter.PROTOCOL_FC
        else:
            self.protocol = adapter.PROTOCOL_ISCSI

    @staticmethod
    def get_driver_options():
        return UNITY_OPTS

    def do_setup(self, context):
        self.replication_manager.do_setup(self)

    @property
    def adapter(self):
        return self.replication_manager.active_adapter

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

    def migrate_volume(self, context, volume, host):
        """Migrates a volume."""
        return self.adapter.migrate_volume(volume, host)

    def retype(self, ctxt, volume, new_type, diff, host):
        """Convert the volume to be of the new type."""
        return self.adapter.retype(ctxt, volume, new_type, diff, host)

    def create_snapshot(self, snapshot):
        """Creates a snapshot."""
        self.adapter.create_snapshot(snapshot)

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""
        self.adapter.delete_snapshot(snapshot)

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
        conn_info = self.adapter.initialize_connection(volume, connector)
        zm_utils.add_fc_zone(conn_info)
        return conn_info

    def terminate_connection(self, volume, connector, **kwargs):
        """Disallow connection from connector."""
        conn_info = self.adapter.terminate_connection(volume, connector)
        zm_utils.remove_fc_zone(conn_info)
        return conn_info

    def _update_volume_stats(self):
        """Retrieve stats info from volume group."""
        LOG.debug("Updating volume stats.")
        stats = self.adapter.update_volume_stats()
        stats['driver_version'] = self.VERSION
        stats['vendor_name'] = self.VENDOR
        self._stats = stats

    def manage_existing(self, volume, existing_ref):
        """Manages an existing LUN in the array.

        :param volume: the mapping cinder volume of the Unity LUN.
        :param existing_ref: the Unity LUN info.
        """
        return self.adapter.manage_existing(volume, existing_ref)

    def manage_existing_get_size(self, volume, existing_ref):
        """Returns size of volume to be managed by manage_existing."""
        return self.adapter.manage_existing_get_size(volume, existing_ref)

    def get_pool(self, volume):
        """Returns the pool name of a volume."""
        return self.adapter.get_pool_name(volume)

    def unmanage(self, volume):
        """Unmanages a volume."""
        pass

    def backup_use_temp_snapshot(self):
        return True

    def create_export_snapshot(self, context, snapshot, connector):
        """Creates the mount point of the snapshot for backup.

        Not necessary to create on Unity.
        """
        pass

    def remove_export_snapshot(self, context, snapshot):
        """Deletes the mount point the snapshot for backup.

        Not necessary to create on Unity.
        """
        pass

    def initialize_connection_snapshot(self, snapshot, connector, **kwargs):
        return self.adapter.initialize_connection_snapshot(snapshot, connector)

    def terminate_connection_snapshot(self, snapshot, connector, **kwargs):
        return self.adapter.terminate_connection_snapshot(snapshot, connector)

    def revert_to_snapshot(self, context, volume, snapshot):
        """Reverts a volume to a snapshot."""
        return self.adapter.restore_snapshot(volume, snapshot)

    @skip_if_not_cg
    def create_group(self, context, group):
        """Creates a consistency group."""
        return self.adapter.create_group(group)

    @skip_if_not_cg
    def delete_group(self, context, group, volumes):
        """Deletes a consistency group."""
        return self.adapter.delete_group(group)

    @skip_if_not_cg
    def update_group(self, context, group, add_volumes=None,
                     remove_volumes=None):
        """Updates a consistency group, i.e. add/remove luns to/from it."""
        # TODO(Ryan L) update other information (like description) of group
        return self.adapter.update_group(group, add_volumes, remove_volumes)

    @skip_if_not_cg
    def create_group_from_src(self, context, group, volumes,
                              group_snapshot=None, snapshots=None,
                              source_group=None, source_vols=None):
        """Creates a consistency group from another group or group snapshot."""
        if group_snapshot:
            return self.adapter.create_group_from_snap(group, volumes,
                                                       group_snapshot,
                                                       snapshots)
        elif source_group:
            return self.adapter.create_cloned_group(group, volumes,
                                                    source_group, source_vols)

    @skip_if_not_cg
    def create_group_snapshot(self, context, group_snapshot, snapshots):
        """Creates a snapshot of consistency group."""
        return self.adapter.create_group_snapshot(group_snapshot, snapshots)

    @skip_if_not_cg
    def delete_group_snapshot(self, context, group_snapshot, snapshots):
        """Deletes a snapshot of consistency group."""
        return self.adapter.delete_group_snapshot(group_snapshot)

    def failover_host(self, context, volumes, secondary_id=None, groups=None):
        """Failovers volumes to secondary backend."""
        return self.adapter.failover(volumes,
                                     secondary_id=secondary_id, groups=groups)

    def enable_replication(self, context, group, volumes):
        return self.adapter.enable_replication(context, group, volumes)

    def disable_replication(self, context, group, volumes):
        return self.adapter.disable_replication(context, group, volumes)

    def failover_replication(self, context, group, volumes,
                             secondary_backend_id=None):
        return self.adapter.failover_replication(
            context, group, volumes, secondary_backend_id)

    def get_replication_error_status(self, context, groups):
        return self.adapter.get_replication_error_status(context, groups)
