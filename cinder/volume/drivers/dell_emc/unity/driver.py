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

from cinder import interface
from cinder.volume import configuration
from cinder.volume import driver
from cinder.volume.drivers.dell_emc.unity import adapter
from cinder.volume.drivers.san.san import san_opts
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
    """

    VERSION = '05.00.00'
    VENDOR = 'Dell EMC'
    # ThirdPartySystems wiki page
    CI_WIKI_NAME = "EMC_UNITY_CI"

    def __init__(self, *args, **kwargs):
        super(UnityDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(UNITY_OPTS)
        self.configuration.append_config_values(san_opts)
        protocol = self.configuration.storage_protocol
        if protocol.lower() == adapter.PROTOCOL_FC.lower():
            self.protocol = adapter.PROTOCOL_FC
            self.adapter = adapter.FCAdapter(self.VERSION)
        else:
            self.protocol = adapter.PROTOCOL_ISCSI
            self.adapter = adapter.ISCSIAdapter(self.VERSION)

    @staticmethod
    def get_driver_options():
        return UNITY_OPTS

    def do_setup(self, context):
        self.adapter.do_setup(self, self.configuration)

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
