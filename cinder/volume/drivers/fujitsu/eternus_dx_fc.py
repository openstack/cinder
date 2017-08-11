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
FibreChannel Cinder Volume driver for Fujitsu ETERNUS DX S3 series.
"""
from oslo_log import log as logging
import six

from cinder import interface
from cinder.volume import driver
from cinder.volume.drivers.fujitsu import eternus_dx_common
from cinder.zonemanager import utils as fczm_utils

LOG = logging.getLogger(__name__)


@interface.volumedriver
class FJDXFCDriver(driver.FibreChannelDriver):
    """FC Cinder Volume Driver for Fujitsu ETERNUS DX S3 series."""

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = "Fujitsu_ETERNUS_CI"
    VERSION = eternus_dx_common.FJDXCommon.VERSION

    def __init__(self, *args, **kwargs):

        super(FJDXFCDriver, self).__init__(*args, **kwargs)
        self.common = eternus_dx_common.FJDXCommon(
            'fc',
            configuration=self.configuration)
        self.VERSION = self.common.VERSION

    def check_for_setup_error(self):
        if not self.common.pywbemAvailable:
            LOG.error('pywbem could not be imported! '
                      'pywbem is necessary for this volume driver.')

        pass

    def create_volume(self, volume):
        """Create volume."""
        LOG.debug('create_volume, '
                  'volume id: %s, enter method.', volume['id'])

        location, metadata = self.common.create_volume(volume)

        v_metadata = self._get_metadata(volume)
        metadata.update(v_metadata)

        LOG.debug('create_volume, info: %s, exit method.', metadata)
        return {'provider_location': six.text_type(location),
                'metadata': metadata}

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot."""
        LOG.debug('create_volume_from_snapshot, '
                  'volume id: %(vid)s, snap id: %(sid)s, enter method.',
                  {'vid': volume['id'], 'sid': snapshot['id']})

        location, metadata = (
            self.common.create_volume_from_snapshot(volume, snapshot))

        v_metadata = self._get_metadata(volume)
        metadata.update(v_metadata)

        LOG.debug('create_volume_from_snapshot, '
                  'info: %s, exit method.', metadata)
        return {'provider_location': six.text_type(location),
                'metadata': metadata}

    def create_cloned_volume(self, volume, src_vref):
        """Create cloned volume."""
        LOG.debug('create_cloned_volume, '
                  'target volume id: %(tid)s, '
                  'source volume id: %(sid)s, enter method.',
                  {'tid': volume['id'], 'sid': src_vref['id']})

        location, metadata = (
            self.common.create_cloned_volume(volume, src_vref))

        v_metadata = self._get_metadata(volume)
        metadata.update(v_metadata)

        LOG.debug('create_cloned_volume, '
                  'info: %s, exit method.', metadata)
        return {'provider_location': six.text_type(location),
                'metadata': metadata}

    def delete_volume(self, volume):
        """Delete volume on ETERNUS."""
        LOG.debug('delete_volume, '
                  'volume id: %s, enter method.', volume['id'])

        vol_exist = self.common.delete_volume(volume)

        LOG.debug('delete_volume, '
                  'delete: %s, exit method.', vol_exist)

    def create_snapshot(self, snapshot):
        """Creates a snapshot."""
        LOG.debug('create_snapshot, '
                  'snap id: %(sid)s, volume id: %(vid)s, enter method.',
                  {'sid': snapshot['id'], 'vid': snapshot['volume_id']})

        location, metadata = self.common.create_snapshot(snapshot)

        LOG.debug('create_snapshot, info: %s, exit method.', metadata)
        return {'provider_location': six.text_type(location)}

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""
        LOG.debug('delete_snapshot, '
                  'snap id: %(sid)s, volume id: %(vid)s, enter method.',
                  {'sid': snapshot['id'], 'vid': snapshot['volume_id']})

        vol_exist = self.common.delete_snapshot(snapshot)

        LOG.debug('delete_snapshot, '
                  'delete: %s, exit method.', vol_exist)

    def ensure_export(self, context, volume):
        """Driver entry point to get the export info for an existing volume."""
        return

    def create_export(self, context, volume, connector):
        """Driver entry point to get the export info for a new volume."""
        return

    def remove_export(self, context, volume):
        """Driver entry point to remove an export for a volume."""
        return

    @fczm_utils.add_fc_zone
    def initialize_connection(self, volume, connector):
        """Allow connection to connector and return connection info."""
        LOG.debug('initialize_connection, volume id: %(vid)s, '
                  'wwpns: %(wwpns)s, enter method.',
                  {'vid': volume['id'], 'wwpns': connector['wwpns']})

        info = self.common.initialize_connection(volume, connector)

        data = info['data']
        init_tgt_map = (
            self.common.build_fc_init_tgt_map(connector, data['target_wwn']))
        data['initiator_target_map'] = init_tgt_map

        info['data'] = data
        LOG.debug('initialize_connection, '
                  'info: %s, exit method.', info)
        return info

    @fczm_utils.remove_fc_zone
    def terminate_connection(self, volume, connector, **kwargs):
        """Disallow connection from connector."""
        wwpns = connector.get('wwpns') if connector else None

        LOG.debug('terminate_connection, volume id: %(vid)s, '
                  'wwpns: %(wwpns)s, enter method.',
                  {'vid': volume['id'], 'wwpns': wwpns})

        map_exist = self.common.terminate_connection(volume, connector)

        info = {'driver_volume_type': 'fibre_channel',
                'data': {}}

        if connector:
            attached = self.common.check_attached_volume_in_zone(connector)
            if not attached:
                # No more volumes attached to the host
                init_tgt_map = self.common.build_fc_init_tgt_map(connector)
                info['data'] = {'initiator_target_map': init_tgt_map}

        LOG.debug('terminate_connection, unmap: %(unmap)s, '
                  'connection info: %(info)s, exit method',
                  {'unmap': map_exist, 'info': info})
        return info

    def get_volume_stats(self, refresh=False):
        """Get volume stats."""
        LOG.debug('get_volume_stats, refresh: %s, enter method.', refresh)

        pool_name = None
        if refresh is True:
            data, pool_name = self.common.update_volume_stats()
            backend_name = self.configuration.safe_get('volume_backend_name')
            data['volume_backend_name'] = backend_name or 'FJDXFCDriver'
            data['storage_protocol'] = 'FC'
            self._stats = data

        LOG.debug('get_volume_stats, '
                  'pool name: %s, exit method.', pool_name)
        return self._stats

    def extend_volume(self, volume, new_size):
        """Extend volume."""
        LOG.debug('extend_volume, '
                  'volume id: %s, enter method.', volume['id'])

        used_pool_name = self.common.extend_volume(volume, new_size)

        LOG.debug('extend_volume, '
                  'used pool name: %s, exit method.', used_pool_name)

    def _get_metadata(self, volume):
        v_metadata = volume.get('volume_metadata')
        if v_metadata:
            ret = {data['key']: data['value'] for data in v_metadata}
        else:
            ret = volume.get('metadata', {})

        return ret
