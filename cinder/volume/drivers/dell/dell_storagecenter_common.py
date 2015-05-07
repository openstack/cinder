#    Copyright 2015 Dell Inc.
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

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils

from cinder import exception
from cinder.i18n import _, _LE, _LW
from cinder.volume.drivers.dell import dell_storagecenter_api
from cinder.volume.drivers.san import san


common_opts = [
    cfg.IntOpt('dell_sc_ssn',
               default=64702,
               help='Storage Center System Serial Number'),
    cfg.IntOpt('dell_sc_api_port',
               default=3033,
               help='Dell API port'),
    cfg.StrOpt('dell_sc_server_folder',
               default='openstack',
               help='Name of the server folder to use on the Storage Center'),
    cfg.StrOpt('dell_sc_volume_folder',
               default='openstack',
               help='Name of the volume folder to use on the Storage Center')
]

LOG = logging.getLogger(__name__)

CONF = cfg.CONF
CONF.register_opts(common_opts)


class DellCommonDriver(san.SanDriver):

    def __init__(self, *args, **kwargs):
        super(DellCommonDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(common_opts)
        self.backend_name =\
            self.configuration.safe_get('volume_backend_name') or 'Dell'

    def _bytes_to_gb(self, spacestring):
        '''Space is returned in a string like ...
        7.38197504E8 Bytes
        Need to split that apart and convert to GB.

        returns gbs in int form
        '''
        try:
            n = spacestring.split(' ', 1)
            fgbs = float(n[0]) / 1073741824.0
            igbs = int(fgbs)
            return igbs
        except Exception:
            # If any of that blew up it isn't in the format we
            # thought so eat our error and return None
            return None

    def do_setup(self, context):
        '''One time driver setup.

        Called once by the manager after the driver is loaded.
        Sets up clients, check licenses, sets up protocol
        specific helpers.
        '''
        self._client = dell_storagecenter_api.StorageCenterApiHelper(
            self.configuration)

    def check_for_setup_error(self):
        '''Validates the configuration information.'''
        with self._client.open_connection() as api:
            ssn = self.configuration.safe_get('dell_sc_ssn')
            api.find_sc(ssn)

    def create_volume(self, volume):
        '''Create a volume.'''
        volume_name = volume.get('id')
        volume_size = volume.get('size')
        LOG.debug('Creating volume %(name)s of size %(size)s',
                  {'name': volume_name, 'size': volume_size})
        scvolume = None
        with self._client.open_connection() as api:
            try:
                # we use id as our name as it s unique
                volume_folder = self.configuration.dell_sc_volume_folder
                ssn = api.find_sc(self.configuration.dell_sc_ssn)
                LOG.debug('create_volume: %(name)s on %(ssn)s in %(vf)s',
                          {'name': volume_name,
                           'ssn': ssn,
                           'vf': volume_folder})
                if ssn is not None:
                    scvolume = api.create_volume(volume_name,
                                                 volume_size,
                                                 ssn,
                                                 volume_folder)
            except Exception:
                with excutils.save_and_reraise_exception():
                    LOG.error(_LE('Failed to create volume %s'),
                              volume['name'])
        if scvolume is None:
            raise exception.VolumeBackendAPIException(
                _('Unable to create volume'))

    def delete_volume(self, volume):
        deleted = False
        # we use id as our name as it s unique
        volume_name = volume.get('id')
        LOG.debug('Deleting volume %s', volume_name)
        with self._client.open_connection() as api:
            try:
                ssn = api.find_sc(self.configuration.dell_sc_ssn)
                if ssn is not None:
                    deleted = api.delete_volume(ssn,
                                                volume_name)
            except Exception:
                with excutils.save_and_reraise_exception():
                    LOG.error(_LE('Failed to delete volume %s'),
                              volume_name)

        # if there was an error we will have raised an
        # exception.  If it failed to delete it is because
        # the conditions to delete a volume were not met.
        if deleted is False:
            raise exception.VolumeIsBusy(volume_name=volume_name)

    def create_snapshot(self, snapshot):
        '''Create snapshot'''
        # our volume name is the volume id
        volume_name = snapshot.get('volume_id')
        snapshot_id = snapshot.get('id')
        LOG.debug('Creating snapshot %(snap)s on volume %(vol)s',
                  {'snap': snapshot_id, 'vol': volume_name})
        with self._client.open_connection() as api:
            ssn = api.find_sc(self.configuration.dell_sc_ssn)
            if ssn is not None:
                scvolume = api.find_volume(ssn,
                                           volume_name)
                if scvolume is not None:
                    if api.create_replay(scvolume,
                                         snapshot_id,
                                         0) is not None:
                        snapshot['status'] = 'available'
                        return
                else:
                    LOG.warning(_LW('Unable to locate volume:%s'),
                                volume_name)

        snapshot['status'] = 'error_creating'
        raise exception.VolumeBackendAPIException(
            _('Failed to create snapshot %s') %
            snapshot_id)

    def create_volume_from_snapshot(self, volume, snapshot):
        '''Create new volume from other volume's snapshot on appliance.'''
        scvolume = None
        src_volume_name = snapshot.get('volume_id')
        snapshot_id = snapshot.get('id')
        volume_name = volume.get('id')
        LOG.debug(
            'Creating new volume %(vol)s from snapshot %(snap)s '
            'from vol %(src)s',
            {'vol': volume_name,
             'snap': snapshot_id,
             'src': src_volume_name})
        with self._client.open_connection() as api:
            try:
                volume_folder = self.configuration.dell_sc_volume_folder
                ssn = api.find_sc(self.configuration.dell_sc_ssn)
                srcvol = api.find_volume(ssn,
                                         src_volume_name)
                if srcvol is not None:
                    replay = api.find_replay(srcvol,
                                             snapshot_id)
                    if replay is not None:
                        volume_name = volume.get('id')
                        scvolume = api.create_view_volume(volume_name,
                                                          volume_folder,
                                                          replay)
            except Exception:
                with excutils.save_and_reraise_exception():
                    LOG.error(_LE('Failed to create volume %s'),
                              volume_name)
        if scvolume is not None:
            LOG.debug('Volume %(n)s created from %(s)s',
                      {'n': volume_name,
                       's': snapshot_id})
        else:
            raise exception.VolumeBackendAPIException(
                _('Failed to create volume %s') % volume_name)

    def create_cloned_volume(self, volume, src_vref):
        '''Creates a clone of the specified volume.'''
        scvolume = None
        src_volume_name = src_vref.get('id')
        volume_name = volume.get('id')
        LOG.debug('Creating cloned volume %(clone)s from volume %(vol)s',
                  {'clone': volume_name,
                   'vol': src_volume_name})
        with self._client.open_connection() as api:
            try:
                volume_folder = self.configuration.dell_sc_volume_folder
                ssn = api.find_sc(self.configuration.dell_sc_ssn)
                srcvol = api.find_volume(ssn,
                                         src_volume_name)
                if srcvol is not None:
                    scvolume = api.create_cloned_volume(volume_name,
                                                        volume_folder,
                                                        srcvol)
            except Exception:
                with excutils.save_and_reraise_exception():
                    LOG.error(_LE('Failed to create volume %s'),
                              volume_name)
        if scvolume is not None:
            LOG.debug('Volume %(n)s cloned from %(s)s',
                      {'n': volume_name,
                       's': src_volume_name})
        else:
            raise exception.VolumeBackendAPIException(
                _('Failed to create volume %s') % volume_name)

    def delete_snapshot(self, snapshot):
        '''delete_snapshot'''
        volume_name = snapshot.get('volume_id')
        snapshot_id = snapshot.get('id')
        LOG.debug('Deleting snapshot %(snap)s from volume %(vol)s',
                  {'snap': snapshot_id,
                   'vol': volume_name})
        with self._client.open_connection() as api:
            ssn = api.find_sc(self.configuration.dell_sc_ssn)
            if ssn is not None:
                scvolume = api.find_volume(ssn,
                                           volume_name)
                if scvolume is not None:
                    if api.delete_replay(scvolume,
                                         snapshot_id):
                        return
        # if we are here things went poorly.
        snapshot['status'] = 'error_deleting'
        raise exception.VolumeBackendAPIException(
            _('Failed to delete snapshot %s') % snapshot_id)

    def create_export(self, context, volume):
        '''Create an export of a volume.

        The volume exists on creation and will be visible on
        initialize connection.  So nothing to do here.
        '''
        pass

    def ensure_export(self, context, volume):
        '''Ensure an export of a volume.

        Per the eqlx driver we just make sure that the volume actually
        exists where we think it does.
        '''
        scvolume = None
        volume_name = volume.get('id')
        LOG.debug('Checking existence of volume %s', volume_name)
        with self._client.open_connection() as api:
            try:
                ssn = api.find_sc(self.configuration.dell_sc_ssn)
                if ssn is not None:
                    scvolume = api.find_volume(ssn,
                                               volume_name)
            except Exception:
                with excutils.save_and_reraise_exception():
                    LOG.error(_LE('Failed to ensure export of volume %s'),
                              volume_name)
        if scvolume is None:
            raise exception.VolumeBackendAPIException(
                _('unable to find volume %s') % volume_name)

    def remove_export(self, context, volume):
        '''Remove an export of a volume.

        We do nothing here to match the nothing we do in create export.  Again
        we do everything in initialize and terminate connection.
        '''
        pass

    def extend_volume(self, volume, new_size):
        '''Extend the size of the volume.'''
        volume_name = volume.get('id')
        LOG.debug('Extending volume %(vol)s to %(size)s',
                  {'vol': volume_name, 'size': new_size})
        if volume is not None:
            with self._client.open_connection() as api:
                ssn = api.find_sc(self.configuration.dell_sc_ssn)
                if ssn is not None:
                    scvolume = api.find_volume(ssn,
                                               volume_name)
                    if api.expand_volume(scvolume, new_size) is not None:
                        return
        # If we are here nothing good happened.
        raise exception.VolumeBackendAPIException(
            _('Unable to extend volume %s') % volume_name)

    def get_volume_stats(self, refresh=False):
        '''Get volume status.

        If 'refresh' is True, run update the stats first.
        '''
        if refresh:
            self._update_volume_stats()

        return self._stats

    def _update_volume_stats(self):
        '''Retrieve stats info from volume group.'''
        with self._client.open_connection() as api:
            ssn = api.find_sc(self.configuration.dell_sc_ssn)
            storageusage = api.get_storage_usage(ssn)

            # all of this is basically static for now
            data = {}
            data['volume_backend_name'] = self.backend_name
            data['vendor_name'] = 'Dell'
            data['driver_version'] = self.VERSION
            data['storage_protocol'] = 'iSCSI'
            data['reserved_percentage'] = 0
            # In theory if storageusage is None then we should have
            # blown up getting it.  If not just report unavailable.
            if storageusage is not None:
                totalcapacity = storageusage.get('availableSpace')
                totalcapacitygb = self._bytes_to_gb(totalcapacity)
                data['total_capacity_gb'] = totalcapacitygb
                freespace = storageusage.get('freeSpace')
                freespacegb = self._bytes_to_gb(freespace)
                data['free_capacity_gb'] = freespacegb
            if data.get('total_capacity_gb') is None:
                data['total_capacity_gb'] = 'unavailable'
            if data.get('free_capacity_gb') is None:
                data['free_capacity_gb'] = 'unavailable'
            data['QoS_support'] = False
            self._stats = data
            LOG.debug('Total cap %(t)s Free cap %(f)s',
                      {'t': totalcapacitygb,
                       'f': freespacegb})

    def update_migrated_volume(self, ctxt, volume, new_volume):
        """Return model update for migrated volume.

        :param volume: The original volume that was migrated to this backend
        :param new_volume: The migration volume object that was created on
                           this backend as part of the migration process
        :return model_update to update DB with any needed changes
        """
        # We use id as our volume name so we need to rename the backend
        # volume to the original volume name.
        original_volume_name = volume.get('id')
        current_name = new_volume.get('id')
        LOG.debug('update_migrated_volume: %(c)s to %(o)s',
                  {'c': current_name,
                   'o': original_volume_name})
        if original_volume_name:
            with self._client.open_connection() as api:
                ssn = api.find_sc(self.configuration.dell_sc_ssn)
                if ssn is not None:
                    scvolume = api.find_volume(ssn,
                                               current_name)
                    if scvolume:
                        if api.rename_volume(scvolume, original_volume_name):
                            model_update = {'_name_id': None}
                            return model_update
        # The world was horrible to us so we should error and leave.
        LOG.error(_LE('Unabled to rename the logical volume for volume: %s'),
                  original_volume_name)
        return None
