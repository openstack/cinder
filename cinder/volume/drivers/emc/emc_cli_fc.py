# Copyright (c) 2012 - 2014 EMC Corporation, Inc.
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
"""
Fibre Channel Driver for EMC VNX array based on CLI.

"""

from cinder.openstack.common import log as logging
from cinder.volume import driver
from cinder.volume.drivers.emc import emc_vnx_cli
from cinder.zonemanager.utils import AddFCZone
from cinder.zonemanager.utils import RemoveFCZone


LOG = logging.getLogger(__name__)


class EMCCLIFCDriver(driver.FibreChannelDriver):
    """EMC FC Driver for VNX using CLI.

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
    """

    def __init__(self, *args, **kwargs):

        super(EMCCLIFCDriver, self).__init__(*args, **kwargs)
        self.cli = emc_vnx_cli.getEMCVnxCli(
            'FC',
            configuration=self.configuration)
        self.VERSION = self.cli.VERSION

    def check_for_setup_error(self):
        pass

    def create_volume(self, volume):
        """Creates a volume."""
        return self.cli.create_volume(volume)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot."""
        return self.cli.create_volume_from_snapshot(volume, snapshot)

    def create_cloned_volume(self, volume, src_vref):
        """Creates a cloned volume."""
        return self.cli.create_cloned_volume(volume, src_vref)

    def extend_volume(self, volume, new_size):
        """Extend a volume."""
        self.cli.extend_volume(volume, new_size)

    def delete_volume(self, volume):
        """Deletes a volume."""
        self.cli.delete_volume(volume)

    def migrate_volume(self, ctxt, volume, host):
        """Migrate volume via EMC migration functionality."""
        return self.cli.migrate_volume(ctxt, volume, host)

    def retype(self, ctxt, volume, new_type, diff, host):
        """Convert the volume to be of the new type."""
        return self.cli.retype(ctxt, volume, new_type, diff, host)

    def create_snapshot(self, snapshot):
        """Creates a snapshot."""
        self.cli.create_snapshot(snapshot)

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""
        self.cli.delete_snapshot(snapshot)

    def ensure_export(self, context, volume):
        """Driver entry point to get the export info for an existing volume."""
        pass

    def create_export(self, context, volume):
        """Driver entry point to get the export info for a new volume."""
        pass

    def remove_export(self, context, volume):
        """Driver entry point to remove an export for a volume."""
        pass

    def check_for_export(self, context, volume_id):
        """Make sure volume is exported."""
        pass

    @AddFCZone
    def initialize_connection(self, volume, connector):
        """Initializes the connection and returns connection info.

        Assign any created volume to a compute node/host so that it can be
        used from that host.

        The  driver returns a driver_volume_type of 'fibre_channel'.
        The target_wwn can be a single entry or a list of wwns that
        correspond to the list of remote wwn(s) that will export the volume.
        The initiator_target_map is a map that represents the remote wwn(s)
        and a list of wwns which are visiable to the remote wwn(s).
        Example return values:

            {
                'driver_volume_type': 'fibre_channel'
                'data': {
                    'target_discovered': True,
                    'target_lun': 1,
                    'target_wwn': '1234567890123',
                    'access_mode': 'rw'
                    'initiator_target_map': {
                        '1122334455667788': ['1234567890123']
                    }
                }
            }

            or

             {
                'driver_volume_type': 'fibre_channel'
                'data': {
                    'target_discovered': True,
                    'target_lun': 1,
                    'target_wwn': ['1234567890123', '0987654321321'],
                    'access_mode': 'rw'
                    'initiator_target_map': {
                        '1122334455667788': ['1234567890123',
                                             '0987654321321']
                    }
                }
            }

        """
        conn_info = self.cli.initialize_connection(volume,
                                                   connector)
        conn_info = self.cli.adjust_fc_conn_info(conn_info, connector)
        LOG.debug("Exit initialize_connection"
                  " - Returning FC connection info: %(conn_info)s."
                  % {'conn_info': conn_info})

        return conn_info

    @RemoveFCZone
    def terminate_connection(self, volume, connector, **kwargs):
        """Disallow connection from connector."""
        remove_zone = self.cli.terminate_connection(volume, connector)
        conn_info = {'driver_volume_type': 'fibre_channel',
                     'data': {}}
        conn_info = self.cli.adjust_fc_conn_info(conn_info, connector,
                                                 remove_zone)
        LOG.debug("Exit terminate_connection"
                  " - Returning FC connection info: %(conn_info)s."
                  % {'conn_info': conn_info})

        return conn_info

    def get_volume_stats(self, refresh=False):
        """Get volume stats.

        If 'refresh' is True, run update the stats first.
        """
        if refresh:
            self.update_volume_stats()

        return self._stats

    def update_volume_stats(self):
        """Retrieve stats info from volume group."""
        LOG.debug("Updating volume stats.")
        data = self.cli.update_volume_stats()
        backend_name = self.configuration.safe_get('volume_backend_name')
        data['volume_backend_name'] = backend_name or 'EMCCLIFCDriver'
        data['storage_protocol'] = 'FC'
        self._stats = data

    def manage_existing(self, volume, existing_ref):
        """Manage an existing lun in the array.

        The lun should be in a manageable pool backend, otherwise
        error would return.
        Rename the backend storage object so that it matches the,
        volume['name'] which is how drivers traditionally map between a
        cinder volume and the associated backend storage object.

        existing_ref:{
            'id':lun_id
        }
        """
        LOG.debug("Reference lun id %s." % existing_ref['id'])
        self.cli.manage_existing(volume, existing_ref)

    def manage_existing_get_size(self, volume, existing_ref):
        """Return size of volume to be managed by manage_existing.
        """
        return self.cli.manage_existing_get_size(volume, existing_ref)

    def create_consistencygroup(self, context, group):
        """Creates a consistencygroup."""
        return self.cli.create_consistencygroup(context, group)

    def delete_consistencygroup(self, context, group):
        """Deletes a consistency group."""
        return self.cli.delete_consistencygroup(
            self, context, group)

    def create_cgsnapshot(self, context, cgsnapshot):
        """Creates a cgsnapshot."""
        return self.cli.create_cgsnapshot(
            self, context, cgsnapshot)

    def delete_cgsnapshot(self, context, cgsnapshot):
        """Deletes a cgsnapshot."""
        return self.cli.delete_cgsnapshot(self, context, cgsnapshot)