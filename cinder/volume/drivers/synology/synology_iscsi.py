# Copyright (c) 2016 Synology Inc. All rights reserved.
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

from oslo_log import log as logging
from oslo_utils import excutils

from cinder import exception
from cinder import interface
from cinder.volume import driver
from cinder.volume.drivers.synology import synology_common as common

LOG = logging.getLogger(__name__)


@interface.volumedriver
class SynoISCSIDriver(driver.ISCSIDriver):
    """OpenStack Cinder drivers for Synology storage.

    .. code-block:: none

     Version history:
        1.0.0 - Initial driver. Provide Cinder minimum features
    """
    # ThirdPartySystems wiki page
    CI_WIKI_NAME = 'Synology_DSM_CI'
    VERSION = '1.0.0'

    def __init__(self, *args, **kwargs):
        super(SynoISCSIDriver, self).__init__(*args, **kwargs)

        self.common = None
        self.configuration.append_config_values(common.cinder_opts)
        self.stats = {}

    @staticmethod
    def get_driver_options():
        return common.cinder_opts

    def do_setup(self, context):
        self.common = common.SynoCommon(self.configuration, 'iscsi')

    def check_for_setup_error(self):
        self.common.check_for_setup_error()

    def create_volume(self, volume):
        """Creates a logical volume."""

        self.common.create_volume(volume)

    def delete_volume(self, volume):
        """Deletes a logical volume."""

        self.common.delete_volume(volume)

    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume."""

        self.common.create_cloned_volume(volume, src_vref)

    def extend_volume(self, volume, new_size):
        """Extend an existing volume's size."""

        if volume['size'] >= new_size:
            LOG.error('New size is smaller than original size. '
                      'New: [%(new)d] Old: [%(old)d]',
                      {'new': new_size,
                       'old': volume['size']})
            return

        self.common.extend_volume(volume, new_size)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot."""

        self.common.create_volume_from_snapshot(volume, snapshot)

    def update_migrated_volume(self, ctxt, volume, new_volume, status):
        """Return model update for migrated volume."""

        return self.common.update_migrated_volume(volume, new_volume)

    def create_snapshot(self, snapshot):
        """Creates a snapshot."""

        return self.common.create_snapshot(snapshot)

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""

        self.common.delete_snapshot(snapshot)

    def get_volume_stats(self, refresh=False):
        """Get volume status.

        If 'refresh' is True, run update the stats first.
        """

        try:
            if refresh or not self.stats:
                self.stats = self.common.update_volume_stats()
                self.stats['driver_version'] = self.VERSION
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception('Failed to get_volume_stats.')

        return self.stats

    def ensure_export(self, context, volume):
        pass

    def create_export(self, context, volume, connector):
        model_update = {}

        try:
            if self.common.is_lun_mapped(volume['name']):
                return model_update
            iqn, trg_id, provider_auth = (self.common.create_iscsi_export
                                          (volume['name'], volume['id']))
        except Exception as e:
            LOG.exception('Failed to remove_export.')
            raise exception.ExportFailure(reason=e)

        model_update['provider_location'] = (self.common.get_provider_location
                                             (iqn, trg_id))
        model_update['provider_auth'] = provider_auth

        return model_update

    def remove_export(self, context, volume):
        try:
            if not self.common.is_lun_mapped(volume['name']):
                return
        except exception.SynoLUNNotExist:
            LOG.warning("Volume not exist")
            return

        try:
            _, trg_id = (self.common.get_iqn_and_trgid
                         (volume['provider_location']))
            self.common.remove_iscsi_export(volume['name'], trg_id)
        except Exception as e:
            LOG.exception('Failed to remove_export.')
            raise exception.RemoveExportException(volume=volume,
                                                  reason=e.msg)

    def initialize_connection(self, volume, connector):
        LOG.debug('iSCSI initiator: %s', connector['initiator'])

        try:
            iscsi_properties = self.common.get_iscsi_properties(volume)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception('Failed to initialize_connection.')

        volume_type = self.configuration.safe_get('target_protocol') or 'iscsi'

        return {
            'driver_volume_type': volume_type,
            'data': iscsi_properties
        }

    def terminate_connection(self, volume, connector, **kwargs):
        pass
