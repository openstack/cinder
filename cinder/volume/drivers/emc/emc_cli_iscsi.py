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
iSCSI Drivers for EMC VNX array based on CLI.

"""

from cinder.openstack.common import log as logging
from cinder.volume import driver
from cinder.volume.drivers.emc import emc_vnx_cli

LOG = logging.getLogger(__name__)


class EMCCLIISCSIDriver(driver.ISCSIDriver):
    """EMC ISCSI Drivers for VNX using CLI.

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

        super(EMCCLIISCSIDriver, self).__init__(*args, **kwargs)
        self.cli = emc_vnx_cli.getEMCVnxCli(
            'iSCSI',
            configuration=self.configuration)
        self.VERSION = self.cli.VERSION

    def check_for_setup_error(self):
        pass

    def create_volume(self, volume):
        """Creates a VNX volume."""
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
        """Deletes a VNX volume."""
        self.cli.delete_volume(volume)

    def migrate_volume(self, ctxt, volume, host):
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
        self.cli.create_export(context, volume)

    def remove_export(self, context, volume):
        """Driver entry point to remove an export for a volume."""
        pass

    def check_for_export(self, context, volume_id):
        """Make sure volume is exported."""
        pass

    def initialize_connection(self, volume, connector):
        """Initializes the connection and returns connection info.

        The iscsi driver returns a driver_volume_type of 'iscsi'.
        the format of the driver data is defined in vnx_get_iscsi_properties.
        Example return value::

            {
                'driver_volume_type': 'iscsi'
                'data': {
                    'target_discovered': True,
                    'target_iqn': 'iqn.2010-10.org.openstack:volume-00000001',
                    'target_portal': '127.0.0.0.1:3260',
                    'target_lun': 1,
                    'access_mode': 'rw'
                }
            }

        """
        return self.cli.initialize_connection(volume, connector)

    def terminate_connection(self, volume, connector, **kwargs):
        """Disallow connection from connector."""
        self.cli.terminate_connection(volume, connector)

    def get_volume_stats(self, refresh=False):
        """Get volume status.

        If 'refresh' is True, run update the stats first.
        """
        if refresh:
            self.update_volume_stats()

        return self._stats

    def update_volume_stats(self):
        """Retrieve status info from volume group."""
        LOG.debug("Updating volume status.")
        # retrieving the volume update from the VNX
        data = self.cli.update_volume_stats()

        backend_name = self.configuration.safe_get('volume_backend_name')
        data['volume_backend_name'] = backend_name or 'EMCCLIISCSIDriver'
        data['storage_protocol'] = 'iSCSI'

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