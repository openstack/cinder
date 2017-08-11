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

"""
iSCSI Cinder Volume driver for Fujitsu ETERNUS DX S3 series.
"""
import six

from cinder import interface
from cinder.volume import driver
from cinder.volume.drivers.fujitsu import eternus_dx_common
from oslo_log import log as logging

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

    def check_for_setup_error(self):
        if not self.common.pywbemAvailable:
            LOG.error('pywbem could not be imported! '
                      'pywbem is necessary for this volume driver.')

        return

    def create_volume(self, volume):
        """Create volume."""
        LOG.info('create_volume, volume id: %s, Enter method.', volume['id'])

        element_path, metadata = self.common.create_volume(volume)

        v_metadata = volume.get('volume_metadata')
        if v_metadata:
            for data in v_metadata:
                metadata[data['key']] = data['value']
        else:
            v_metadata = volume.get('metadata', {})
            metadata.update(v_metadata)

        LOG.info('create_volume, info: %s, Exit method.', metadata)
        return {'provider_location': six.text_type(element_path),
                'metadata': metadata}

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot."""
        LOG.info('create_volume_from_snapshot, '
                 'volume id: %(vid)s, snap id: %(sid)s, Enter method.',
                 {'vid': volume['id'], 'sid': snapshot['id']})

        element_path, metadata = (
            self.common.create_volume_from_snapshot(volume, snapshot))

        v_metadata = volume.get('volume_metadata')
        if v_metadata:
            for data in v_metadata:
                metadata[data['key']] = data['value']
        else:
            v_metadata = volume.get('metadata', {})
            metadata.update(v_metadata)

        LOG.info('create_volume_from_snapshot, '
                 'info: %s, Exit method.', metadata)
        return {'provider_location': six.text_type(element_path),
                'metadata': metadata}

    def create_cloned_volume(self, volume, src_vref):
        """Create cloned volume."""
        LOG.info('create_cloned_volume, '
                 'target volume id: %(tid)s, '
                 'source volume id: %(sid)s, Enter method.',
                 {'tid': volume['id'], 'sid': src_vref['id']})

        element_path, metadata = (
            self.common.create_cloned_volume(volume, src_vref))

        v_metadata = volume.get('volume_metadata')
        if v_metadata:
            for data in v_metadata:
                metadata[data['key']] = data['value']
        else:
            v_metadata = volume.get('metadata', {})
            metadata.update(v_metadata)

        LOG.info('create_cloned_volume, info: %s, Exit method.', metadata)
        return {'provider_location': six.text_type(element_path),
                'metadata': metadata}

    def delete_volume(self, volume):
        """Delete volume on ETERNUS."""
        LOG.info('delete_volume, volume id: %s, Enter method.', volume['id'])

        vol_exist = self.common.delete_volume(volume)

        LOG.info('delete_volume, delete: %s, Exit method.', vol_exist)
        return

    def create_snapshot(self, snapshot):
        """Creates a snapshot."""
        LOG.info('create_snapshot, snap id: %(sid)s, volume id: %(vid)s, '
                 'Enter method.',
                 {'sid': snapshot['id'], 'vid': snapshot['volume_id']})

        element_path, metadata = self.common.create_snapshot(snapshot)

        LOG.info('create_snapshot, info: %s, Exit method.', metadata)
        return {'provider_location': six.text_type(element_path)}

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""
        LOG.info('delete_snapshot, snap id: %(sid)s, volume id: %(vid)s, '
                 'Enter method.',
                 {'sid': snapshot['id'], 'vid': snapshot['volume_id']})

        vol_exist = self.common.delete_snapshot(snapshot)

        LOG.info('delete_snapshot, delete: %s, Exit method.', vol_exist)
        return

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
        LOG.info('initialize_connection, volume id: %(vid)s, '
                 'initiator: %(initiator)s, Enter method.',
                 {'vid': volume['id'], 'initiator': connector['initiator']})

        info = self.common.initialize_connection(volume, connector)

        LOG.info('initialize_connection, info: %s, Exit method.', info)
        return info

    def terminate_connection(self, volume, connector, **kwargs):
        """Disallow connection from connector."""
        initiator = connector.get('initiator') if connector else None

        LOG.info('terminate_connection, volume id: %(vid)s, '
                 'initiator: %(initiator)s, Enter method.',
                 {'vid': volume['id'], 'initiator': initiator})

        map_exist = self.common.terminate_connection(volume, connector)

        LOG.info('terminate_connection, unmap: %s, Exit method.', map_exist)
        return

    def get_volume_stats(self, refresh=False):
        """Get volume stats."""
        LOG.debug('get_volume_stats, refresh: %s, Enter method.', refresh)

        pool_name = None
        if refresh is True:
            data, pool_name = self.common.update_volume_stats()
            backend_name = self.configuration.safe_get('volume_backend_name')
            data['volume_backend_name'] = backend_name or 'FJDXISCSIDriver'
            data['storage_protocol'] = 'iSCSI'
            self._stats = data

        LOG.debug('get_volume_stats, '
                  'pool name: %s, Exit method.', pool_name)
        return self._stats

    def extend_volume(self, volume, new_size):
        """Extend volume."""
        LOG.info('extend_volume, volume id: %s, Enter method.', volume['id'])

        used_pool_name = self.common.extend_volume(volume, new_size)

        LOG.info('extend_volume, used pool name: %s, Exit method.',
                 used_pool_name)
