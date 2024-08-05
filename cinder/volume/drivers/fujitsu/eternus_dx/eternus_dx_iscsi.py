# Copyright (c) 2015 FUJITSU LIMITED
# Copyright (c) 2012 EMC Corporation.
# Copyright (c) 2012 OpenStack Foundation
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
#

"""iSCSI Cinder Volume driver for Fujitsu ETERNUS DX S3 series."""
from oslo_log import log as logging

from cinder.common import constants
from cinder import exception
from cinder.i18n import _
from cinder import interface
from cinder.volume import driver
from cinder.volume.drivers.fujitsu.eternus_dx import eternus_dx_common

LOG = logging.getLogger(__name__)


@interface.volumedriver
class FJDXISCSIDriver(driver.ISCSIDriver):
    """iSCSI Cinder Volume Driver for Fujitsu ETERNUS DX S3 series."""

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = "Fujitsu_ETERNUS_CI"
    VERSION = eternus_dx_common.FJDXCommon.VERSION

    def __init__(self, *args, **kwargs):

        super(FJDXISCSIDriver, self).__init__(*args, **kwargs)
        self.common = eternus_dx_common.FJDXCommon(
            'iSCSI',
            configuration=self.configuration)
        self.VERSION = self.common.VERSION

    @staticmethod
    def get_driver_options():
        return eternus_dx_common.FJDXCommon.get_driver_options()

    def check_for_setup_error(self):
        if not self.common.pywbemAvailable:
            msg = _('pywbem could not be imported! '
                    'pywbem is necessary for this volume driver.')
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

    def create_volume(self, volume):
        """Create volume."""
        model_update = self.common.create_volume(volume)

        return model_update

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot."""
        element_path, metadata = (
            self.common.create_volume_from_snapshot(volume, snapshot))

        v_metadata = volume.get('volume_metadata')
        if v_metadata:
            for data in v_metadata:
                metadata[data['key']] = data['value']
        else:
            v_metadata = volume.get('metadata', {})
            metadata.update(v_metadata)

        return {'provider_location': str(element_path), 'metadata': metadata}

    def create_cloned_volume(self, volume, src_vref):
        """Create cloned volume."""
        element_path, metadata = (
            self.common.create_cloned_volume(volume, src_vref))

        v_metadata = volume.get('volume_metadata')
        if v_metadata:
            for data in v_metadata:
                metadata[data['key']] = data['value']
        else:
            v_metadata = volume.get('metadata', {})
            metadata.update(v_metadata)

        return {'provider_location': str(element_path), 'metadata': metadata}

    def delete_volume(self, volume):
        """Delete volume on ETERNUS."""
        LOG.debug('delete_volume, '
                  'volume id: %s, Enter method.', volume['id'])

        self.common.delete_volume(volume)

        LOG.debug('delete_volume, '
                  'volume id: %s, delete succeed.', volume['id'])

    def create_snapshot(self, snapshot):
        """Creates a snapshot."""
        LOG.debug('create_snapshot, '
                  'snap id: %(sid)s, volume id: %(vid)s, Enter method.',
                  {'sid': snapshot['id'], 'vid': snapshot['volume_id']})

        model_update = self.common.create_snapshot(snapshot)

        LOG.debug('create_snapshot, info: %s, Exit method.',
                  model_update['metadata'])
        return model_update

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""
        self.common.delete_snapshot(snapshot)

    def ensure_export(self, context, volume):
        """Driver entry point to get the export info for an existing volume."""
        return

    def create_export(self, context, volume, connector):
        """Driver entry point to get the export info for a new volume."""
        return

    def remove_export(self, context, volume):
        """Driver entry point to remove an export for a volume."""
        return

    def initialize_connection(self, volume, connector):
        """Allow connection to connector and return connection info."""
        info = self.common.initialize_connection(volume, connector)

        return info

    def terminate_connection(self, volume, connector, **kwargs):
        """Disallow connection from connector."""
        self.common.terminate_connection(volume, connector)

    def get_volume_stats(self, refresh=False):
        """Get volume stats."""
        LOG.debug('get_volume_stats, refresh: %s, Enter method.', refresh)

        pool_name = None
        if refresh:
            data, pool_name = self.common.update_volume_stats()
            backend_name = self.configuration.safe_get('volume_backend_name')
            data['volume_backend_name'] = backend_name or 'FJDXISCSIDriver'
            data['storage_protocol'] = constants.ISCSI
            self._stats = data

        LOG.debug('get_volume_stats, '
                  'pool name: %s, Exit method.', pool_name)
        return self._stats

    def extend_volume(self, volume, new_size):
        """Extend volume."""
        LOG.debug('extend_volume, '
                  'volume id: %s, Enter method.', volume['id'])

        used_pool_name = self.common.extend_volume(volume, new_size)

        LOG.debug('extend_volume, '
                  'used pool name: %s, Exit method.', used_pool_name)

    def update_migrated_volume(self, ctxt, volume, new_volume,
                               original_volume_status):
        """Update migrated volume."""
        LOG.debug('update_migrated_volume, '
                  'source volume id: %(s_id)s, '
                  'target volume id: %(t_id)s, Enter method.',
                  {'s_id': volume['id'], 't_id': new_volume['id']})

        model_update = self.common.update_migrated_volume(
            ctxt, volume, new_volume)

        LOG.debug('update_migrated_volume, '
                  'target volume meta: %s, Exit method.', model_update)

        return model_update

    def revert_to_snapshot(self, context, volume, snapshot):
        """Revert volume to snapshot."""
        return self.common.revert_to_snapshot(volume, snapshot)
