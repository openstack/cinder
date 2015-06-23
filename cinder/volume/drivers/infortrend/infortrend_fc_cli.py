# Copyright (c) 2015 Infortrend Technology, Inc.
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
Fibre Channel Driver for Infortrend Eonstor based on CLI.
"""


from oslo_log import log as logging

from cinder.volume import driver
from cinder.volume.drivers.infortrend.eonstor_ds_cli import common_cli
from cinder.zonemanager import utils as fczm_utils

LOG = logging.getLogger(__name__)


class InfortrendCLIFCDriver(driver.FibreChannelDriver):

    """Infortrend Fibre Channel Driver for Eonstor DS using CLI.

    Version history:
        1.0.0 - Initial driver
        1.0.1 - Support DS4000
    """

    def __init__(self, *args, **kwargs):
        super(InfortrendCLIFCDriver, self).__init__(*args, **kwargs)
        self.common = common_cli.InfortrendCommon(
            'FC', configuration=self.configuration)
        self.VERSION = self.common.VERSION

    def check_for_setup_error(self):
        LOG.debug('check_for_setup_error start')
        self.common.check_for_setup_error()

    def create_volume(self, volume):
        """Creates a volume.

        Can optionally return a Dictionary of changes
        to the volume object to be persisted.
        """
        LOG.debug('create_volume volume id=%(volume_id)s', {
            'volume_id': volume['id']})
        return self.common.create_volume(volume)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot."""
        LOG.debug(
            'create_volume_from_snapshot volume id=%(volume_id)s '
            'snapshot id=%(snapshot_id)s', {
                'volume_id': volume['id'], 'snapshot_id': snapshot['id']})
        return self.common.create_volume_from_snapshot(volume, snapshot)

    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume."""
        LOG.debug(
            'create_cloned_volume volume id=%(volume_id)s '
            'src_vref provider_location=%(provider_location)s', {
                'volume_id': volume['id'],
                'provider_location': src_vref['provider_location']})
        return self.common.create_cloned_volume(volume, src_vref)

    def extend_volume(self, volume, new_size):
        """Extend a volume."""
        LOG.debug(
            'extend_volume volume id=%(volume_id)s new size=%(size)s', {
                'volume_id': volume['id'], 'size': new_size})
        self.common.extend_volume(volume, new_size)

    def delete_volume(self, volume):
        """Deletes a volume."""
        LOG.debug('delete_volume volume id=%(volume_id)s', {
            'volume_id': volume['id']})
        return self.common.delete_volume(volume)

    def migrate_volume(self, ctxt, volume, host):
        """Migrate the volume to the specified host.

        Returns a boolean indicating whether the migration occurred, as well as
        model_update.

        :param ctxt: Context
        :param volume: A dictionary describing the volume to migrate
        :param host: A dictionary describing the host to migrate to, where
                     host['host'] is its name, and host['capabilities'] is a
                     dictionary of its reported capabilities.
        """
        LOG.debug('migrate_volume volume id=%(volume_id)s host=%(host)s', {
            'volume_id': volume['id'], 'host': host['host']})
        return self.common.migrate_volume(volume, host)

    def create_snapshot(self, snapshot):
        """Creates a snapshot."""
        LOG.debug(
            'create_snapshot snapshot id=%(snapshot_id)s '
            'volume id=%(volume_id)s', {
                'snapshot_id': snapshot['id'],
                'volume_id': snapshot['volume_id']})
        return self.common.create_snapshot(snapshot)

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""
        LOG.debug(
            'delete_snapshot snapshot id=%(snapshot_id)s '
            'volume id=%(volume_id)s', {
                'snapshot_id': snapshot['id'],
                'volume_id': snapshot['volume_id']})
        self.common.delete_snapshot(snapshot)

    def ensure_export(self, context, volume):
        """Synchronously recreates an export for a volume."""
        pass

    def create_export(self, context, volume):
        """Exports the volume.

        Can optionally return a Dictionary of changes
        to the volume object to be persisted.
        """
        LOG.debug(
            'create_export volume provider_location=%(provider_location)s', {
                'provider_location': volume['provider_location']})
        return self.common.create_export(context, volume)

    def remove_export(self, context, volume):
        """Removes an export for a volume."""
        pass

    @fczm_utils.AddFCZone
    def initialize_connection(self, volume, connector):
        """Initializes the connection and returns connection information.

        Assign any created volume to a compute node/host so that it can be
        used from that host.

        The  driver returns a driver_volume_type of 'fibre_channel'.
        The target_wwn can be a single entry or a list of wwns that
        correspond to the list of remote wwn(s) that will export the volume.
        The initiator_target_map is a map that represents the remote wwn(s)
        and a list of wwns which are visible to the remote wwn(s).
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
        LOG.debug(
            'initialize_connection volume id=%(volume_id)s '
            'connector initiator=%(initiator)s', {
                'volume_id': volume['id'],
                'initiator': connector['initiator']})
        return self.common.initialize_connection(volume, connector)

    @fczm_utils.RemoveFCZone
    def terminate_connection(self, volume, connector, **kwargs):
        """Disallow connection from connector."""
        LOG.debug('terminate_connection volume id=%(volume_id)s', {
            'volume_id': volume['id']})
        return self.common.terminate_connection(volume, connector)

    def get_volume_stats(self, refresh=False):
        """Get volume stats.

        If 'refresh' is True, run update the stats first.
        """
        LOG.debug('get_volume_stats refresh=%(refresh)s', {
            'refresh': refresh})
        return self.common.get_volume_stats(refresh)

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
        LOG.debug(
            'manage_existing volume id=%(volume_id)s '
            'existing_ref source id=%(source_id)s', {
                'volume_id': volume['id'],
                'source_id': existing_ref['source-id']})
        return self.common.manage_existing(volume, existing_ref)

    def unmanage(self, volume):
        """Removes the specified volume from Cinder management.

        Does not delete the underlying backend storage object.

        :param volume: Cinder volume to unmanage
        """
        LOG.debug('unmanage volume id=%(volume_id)s', {
            'volume_id': volume['id']})
        self.common.unmanage(volume)

    def manage_existing_get_size(self, volume, existing_ref):
        """Return size of volume to be managed by manage_existing.

        When calculating the size, round up to the next GB.
        """
        LOG.debug(
            'manage_existing_get_size volume id=%(volume_id)s '
            'existing_ref source id=%(source_id)s', {
                'volume_id': volume['id'],
                'source_id': existing_ref['source-id']})
        return self.common.manage_existing_get_size(volume, existing_ref)

    def retype(self, ctxt, volume, new_type, diff, host):
        """Convert the volume to be of the new type.

        :param ctxt: Context
        :param volume: A dictionary describing the volume to migrate
        :param new_type: A dictionary describing the volume type to convert to
        :param diff: A dictionary with the difference between the two types
        :param host: A dictionary describing the host to migrate to, where
                     host['host'] is its name, and host['capabilities'] is a
                     dictionary of its reported capabilities.
        """
        LOG.debug(
            'retype volume id=%(volume_id)s new_type id=%(type_id)s', {
                'volume_id': volume['id'], 'type_id': new_type['id']})
        return self.common.retype(ctxt, volume, new_type, diff, host)

    def update_migrated_volume(self, ctxt, volume, new_volume):
        """Return model update for migrated volume.

        :param volume: The original volume that was migrated to this backend
        :param new_volume: The migration volume object that was created on
                           this backend as part of the migration process
        :return model_update to update DB with any needed changes
        """
        LOG.debug(
            'update migrated volume original volume id= %(volume_id)s '
            'new volume id=%(new_volume_id)s', {
                'volume_id': volume['id'], 'new_volume_id': new_volume['id']})
        return self.common.update_migrated_volume(ctxt, volume, new_volume)
