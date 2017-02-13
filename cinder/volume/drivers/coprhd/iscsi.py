# Copyright (c) 2016 EMC Corporation
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.


"""Driver for EMC CoprHD iSCSI volumes."""

from oslo_log import log as logging

from cinder import interface
from cinder.volume import driver
from cinder.volume.drivers.coprhd import common as coprhd_common


LOG = logging.getLogger(__name__)


@interface.volumedriver
class EMCCoprHDISCSIDriver(driver.ISCSIDriver):
    """CoprHD iSCSI Driver."""
    VERSION = "3.0.0.0"

    # ThirdPartySystems wiki page name
    CI_WIKI_NAME = "EMC_CoprHD_CI"

    def __init__(self, *args, **kwargs):
        super(EMCCoprHDISCSIDriver, self).__init__(*args, **kwargs)
        self.common = self._get_common_driver()

    def _get_common_driver(self):
        return coprhd_common.EMCCoprHDDriverCommon(
            protocol='iSCSI',
            default_backend_name=self.__class__.__name__,
            configuration=self.configuration)

    def check_for_setup_error(self):
        self.common.check_for_setup_error()

    def create_volume(self, volume):
        """Creates a Volume."""
        self.common.create_volume(volume, self)
        self.common.set_volume_tags(volume, ['_obj_volume_type'])

    def create_cloned_volume(self, volume, src_vref):
        """Creates a cloned Volume."""
        self.common.create_cloned_volume(volume, src_vref)
        self.common.set_volume_tags(volume, ['_obj_volume_type'])

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot."""
        self.common.create_volume_from_snapshot(snapshot, volume)
        self.common.set_volume_tags(volume, ['_obj_volume_type'])

    def extend_volume(self, volume, new_size):
        """expands the size of the volume."""
        self.common.expand_volume(volume, new_size)

    def delete_volume(self, volume):
        """Deletes an volume."""
        self.common.delete_volume(volume)

    def create_snapshot(self, snapshot):
        """Creates a snapshot."""
        self.common.create_snapshot(snapshot)

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""
        self.common.delete_snapshot(snapshot)

    def ensure_export(self, context, volume):
        """Driver entry point to get the export info for an existing volume."""
        pass

    def create_export(self, context, volume, connector=None):
        """Driver entry point to get the export info for a new volume."""
        pass

    def remove_export(self, context, volume):
        """Driver entry point to remove an export for a volume."""
        pass

    def create_consistencygroup(self, context, group):
        """Creates a consistencygroup."""
        return self.common.create_consistencygroup(context, group)

    def delete_consistencygroup(self, context, group, volumes):
        """Deletes a consistency group."""
        return self.common.delete_consistencygroup(context, group, volumes)

    def update_consistencygroup(self, context, group,
                                add_volumes=None, remove_volumes=None):
        """Updates volumes in consistency group."""
        return self.common.update_consistencygroup(group, add_volumes,
                                                   remove_volumes)

    def create_cgsnapshot(self, context, cgsnapshot, snapshots):
        """Creates a cgsnapshot."""
        return self.common.create_cgsnapshot(cgsnapshot, snapshots)

    def delete_cgsnapshot(self, context, cgsnapshot, snapshots):
        """Deletes a cgsnapshot."""
        return self.common.delete_cgsnapshot(cgsnapshot, snapshots)

    def check_for_export(self, context, volume_id):
        """Make sure volume is exported."""
        pass

    def initialize_connection(self, volume, connector):
        """Initializes the connection and returns connection info."""

        initiator_ports = []
        initiator_ports.append(connector['initiator'])
        itls = self.common.initialize_connection(volume,
                                                 'iSCSI',
                                                 initiator_ports,
                                                 connector['host'])
        properties = {}
        properties['target_discovered'] = False
        properties['volume_id'] = volume['id']
        if itls:
            properties['target_iqn'] = itls[0]['target']['port']
            properties['target_portal'] = '%s:%s' % (
                itls[0]['target']['ip_address'],
                itls[0]['target']['tcp_port'])
            properties['target_lun'] = itls[0]['hlu']
        auth = volume['provider_auth']
        if auth:
            (auth_method, auth_username, auth_secret) = auth.split()
            properties['auth_method'] = auth_method
            properties['auth_username'] = auth_username
            properties['auth_password'] = auth_secret

        LOG.debug("ISCSI properties: %s", properties)
        return {
            'driver_volume_type': 'iscsi',
            'data': properties,
        }

    def terminate_connection(self, volume, connector, **kwargs):
        """Disallow connection from connector."""

        init_ports = []
        init_ports.append(connector['initiator'])
        self.common.terminate_connection(volume,
                                         'iSCSI',
                                         init_ports,
                                         connector['host'])

    def get_volume_stats(self, refresh=False):
        """Get volume status.

        If 'refresh' is True, run update the stats first.
        """
        if refresh:
            self.update_volume_stats()

        return self._stats

    def update_volume_stats(self):
        """Retrieve stats info from virtual pool/virtual array."""
        LOG.debug("Updating volume stats")
        self._stats = self.common.update_volume_stats()

    def retype(self, ctxt, volume, new_type, diff, host):
        """Change the volume type."""
        return self.common.retype(ctxt, volume, new_type, diff, host)
