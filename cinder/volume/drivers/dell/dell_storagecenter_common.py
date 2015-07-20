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
from cinder import objects
from cinder.i18n import _, _LE, _LI, _LW
from cinder.volume import driver
from cinder.volume.drivers.dell import dell_storagecenter_api
from cinder.volume.drivers.san.san import san_opts
from cinder.volume import volume_types


common_opts = [
    cfg.IntOpt('dell_sc_ssn',
               default=64702,
               help='Storage Center System Serial Number'),
    cfg.IntOpt('dell_sc_api_port',
               default=3033,
               min=1, max=65535,
               help='Dell API port'),
    cfg.StrOpt('dell_sc_server_folder',
               default='openstack',
               help='Name of the server folder to use on the Storage Center'),
    cfg.StrOpt('dell_sc_volume_folder',
               default='openstack',
               help='Name of the volume folder to use on the Storage Center'),
    cfg.BoolOpt('dell_sc_verify_cert',
                default=False,
                help='Enable HTTPS SC certificate verification.')
]

LOG = logging.getLogger(__name__)

CONF = cfg.CONF
CONF.register_opts(common_opts)


class DellCommonDriver(driver.ConsistencyGroupVD, driver.ManageableVD,
                       driver.ExtendVD, driver.SnapshotVD, driver.BaseVD):

    def __init__(self, *args, **kwargs):
        super(DellCommonDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(common_opts)
        self.configuration.append_config_values(san_opts)
        self.backend_name =\
            self.configuration.safe_get('volume_backend_name') or 'Dell'

    def _bytes_to_gb(self, spacestring):
        """Space is returned in a string like ...

        7.38197504E8 Bytes
        Need to split that apart and convert to GB.

        :returns: gbs in int form
        """
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
        """One time driver setup.

        Called once by the manager after the driver is loaded.
        Sets up clients, check licenses, sets up protocol
        specific helpers.
        """
        self._client = dell_storagecenter_api.StorageCenterApiHelper(
            self.configuration)

    def check_for_setup_error(self):
        """Validates the configuration information."""
        with self._client.open_connection() as api:
            api.find_sc()

    def _get_volume_extra_specs(self, volume):
        """Gets extra specs for the given volume."""
        type_id = volume.get('volume_type_id')
        if type_id:
            return volume_types.get_volume_type_extra_specs(type_id)

        return {}

    def _add_volume_to_consistency_group(self, api, scvolume, volume):
        """Just a helper to add a volume to a consistency group.

        :param api: Dell SC API opbject.
        :param scvolume: Dell SC Volume object.
        :param volume: Cinder Volume object.
        :return: Nothing.
        """
        if scvolume and volume.get('consistencygroup_id'):
            profile = api.find_replay_profile(
                volume.get('consistencygroup_id'))
            if profile:
                api.update_cg_volumes(profile, [volume])

    def create_volume(self, volume):
        """Create a volume."""

        # We use id as our name as it is unique.
        volume_name = volume.get('id')
        volume_size = volume.get('size')

        # See if we have any extra specs.
        specs = self._get_volume_extra_specs(volume)
        storage_profile = specs.get('storagetype:storageprofile')

        LOG.debug('Creating volume %(name)s of size %(size)s',
                  {'name': volume_name,
                   'size': volume_size})
        scvolume = None
        with self._client.open_connection() as api:
            try:
                if api.find_sc():
                    scvolume = api.create_volume(volume_name,
                                                 volume_size,
                                                 storage_profile)
                # Update Consistency Group
                self._add_volume_to_consistency_group(api, scvolume, volume)
            except Exception:
                with excutils.save_and_reraise_exception():
                    LOG.error(_LE('Failed to create volume %s'),
                              volume['name'])
        if scvolume is None:
            raise exception.VolumeBackendAPIException(
                _('Unable to create volume'))

    def delete_volume(self, volume):
        deleted = False
        # We use id as our name as it is unique.
        volume_name = volume.get('id')
        LOG.debug('Deleting volume %s', volume_name)
        with self._client.open_connection() as api:
            try:
                if api.find_sc():
                    deleted = api.delete_volume(volume_name)
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
        """Create snapshot"""
        # our volume name is the volume id
        volume_name = snapshot.get('volume_id')
        snapshot_id = snapshot.get('id')
        LOG.debug('Creating snapshot %(snap)s on volume %(vol)s',
                  {'snap': snapshot_id,
                   'vol': volume_name})
        with self._client.open_connection() as api:
            if api.find_sc():
                scvolume = api.find_volume(volume_name)
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
        """Create new volume from other volume's snapshot on appliance."""
        scvolume = None
        src_volume_name = snapshot.get('volume_id')
        # This snapshot could have been created on its own or as part of a
        # cgsnapshot.  If it was a cgsnapshot it will be identified on the Dell
        # backend under cgsnapshot_id.  Given the volume ID and the
        # cgsnapshot_id we can find the appropriate snapshot.
        # So first we look for cgsnapshot_id.  If that is blank then it must
        # have been a normal snapshot which will be found under snapshot_id.
        snapshot_id = snapshot.get('cgsnapshot_id')
        if not snapshot_id:
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
                if api.find_sc():
                    srcvol = api.find_volume(src_volume_name)
                    if srcvol is not None:
                        replay = api.find_replay(srcvol,
                                                 snapshot_id)
                        if replay is not None:
                            volume_name = volume.get('id')
                            scvolume = api.create_view_volume(volume_name,
                                                              replay)
                            # Update Consistency Group
                            self._add_volume_to_consistency_group(api,
                                                                  scvolume,
                                                                  volume)
            except Exception:
                with excutils.save_and_reraise_exception():
                    LOG.error(_LE('Failed to create volume %s'),
                              volume_name)
        if scvolume is not None:
            LOG.debug('Volume %(vol)s created from %(snap)s',
                      {'vol': volume_name,
                       'snap': snapshot_id})
        else:
            raise exception.VolumeBackendAPIException(
                _('Failed to create volume %s') % volume_name)

    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume."""
        scvolume = None
        src_volume_name = src_vref.get('id')
        volume_name = volume.get('id')
        LOG.debug('Creating cloned volume %(clone)s from volume %(vol)s',
                  {'clone': volume_name,
                   'vol': src_volume_name})
        with self._client.open_connection() as api:
            try:
                if api.find_sc():
                    srcvol = api.find_volume(src_volume_name)
                    if srcvol is not None:
                        scvolume = api.create_cloned_volume(volume_name,
                                                            srcvol)
                        # Update Consistency Group
                        self._add_volume_to_consistency_group(api,
                                                              scvolume,
                                                              volume)
            except Exception:
                with excutils.save_and_reraise_exception():
                    LOG.error(_LE('Failed to create volume %s'),
                              volume_name)
        if scvolume is not None:
            LOG.debug('Volume %(vol)s cloned from %(src)s',
                      {'vol': volume_name,
                       'src': src_volume_name})
        else:
            raise exception.VolumeBackendAPIException(
                _('Failed to create volume %s') % volume_name)

    def delete_snapshot(self, snapshot):
        """delete_snapshot"""
        volume_name = snapshot.get('volume_id')
        snapshot_id = snapshot.get('id')
        LOG.debug('Deleting snapshot %(snap)s from volume %(vol)s',
                  {'snap': snapshot_id,
                   'vol': volume_name})
        with self._client.open_connection() as api:
            if api.find_sc():
                scvolume = api.find_volume(volume_name)
                if scvolume is not None:
                    if api.delete_replay(scvolume,
                                         snapshot_id):
                        return
        # if we are here things went poorly.
        snapshot['status'] = 'error_deleting'
        raise exception.VolumeBackendAPIException(
            _('Failed to delete snapshot %s') % snapshot_id)

    def create_export(self, context, volume, connector):
        """Create an export of a volume.

        The volume exists on creation and will be visible on
        initialize connection.  So nothing to do here.
        """
        pass

    def ensure_export(self, context, volume):
        """Ensure an export of a volume.

        Per the eqlx driver we just make sure that the volume actually
        exists where we think it does.
        """
        scvolume = None
        volume_name = volume.get('id')
        LOG.debug('Checking existence of volume %s', volume_name)
        with self._client.open_connection() as api:
            try:
                if api.find_sc():
                    scvolume = api.find_volume(volume_name)
            except Exception:
                with excutils.save_and_reraise_exception():
                    LOG.error(_LE('Failed to ensure export of volume %s'),
                              volume_name)
        if scvolume is None:
            raise exception.VolumeBackendAPIException(
                _('Unable to find volume %s') % volume_name)

    def remove_export(self, context, volume):
        """Remove an export of a volume.

        We do nothing here to match the nothing we do in create export.  Again
        we do everything in initialize and terminate connection.
        """
        pass

    def extend_volume(self, volume, new_size):
        """Extend the size of the volume."""
        volume_name = volume.get('id')
        LOG.debug('Extending volume %(vol)s to %(size)s',
                  {'vol': volume_name,
                   'size': new_size})
        if volume is not None:
            with self._client.open_connection() as api:
                if api.find_sc():
                    scvolume = api.find_volume(volume_name)
                    if api.expand_volume(scvolume, new_size) is not None:
                        return
        # If we are here nothing good happened.
        raise exception.VolumeBackendAPIException(
            _('Unable to extend volume %s') % volume_name)

    def get_volume_stats(self, refresh=False):
        """Get volume status.

        If 'refresh' is True, run update the stats first.
        """
        if refresh:
            self._update_volume_stats()

        return self._stats

    def _update_volume_stats(self):
        """Retrieve stats info from volume group."""
        with self._client.open_connection() as api:
            storageusage = api.get_storage_usage() if api.find_sc() else None

            # all of this is basically static for now
            data = {}
            data['volume_backend_name'] = self.backend_name
            data['vendor_name'] = 'Dell'
            data['driver_version'] = self.VERSION
            data['storage_protocol'] = 'iSCSI'
            data['reserved_percentage'] = 0
            data['free_capacity_gb'] = 'unavailable'
            data['total_capacity_gb'] = 'unavailable'
            data['consistencygroup_support'] = True
            # In theory if storageusage is None then we should have
            # blown up getting it.  If not just report unavailable.
            if storageusage is not None:
                totalcapacity = storageusage.get('availableSpace')
                totalcapacitygb = self._bytes_to_gb(totalcapacity)
                data['total_capacity_gb'] = totalcapacitygb
                freespace = storageusage.get('freeSpace')
                freespacegb = self._bytes_to_gb(freespace)
                data['free_capacity_gb'] = freespacegb
            data['QoS_support'] = False
            self._stats = data
            LOG.debug('Total cap %(total)s Free cap %(free)s',
                      {'total': data['total_capacity_gb'],
                       'free': data['free_capacity_gb']})

    def update_migrated_volume(self, ctxt, volume, new_volume,
                               original_volume_status):
        """Return model update for migrated volume.

        :param volume: The original volume that was migrated to this backend
        :param new_volume: The migration volume object that was created on
                           this backend as part of the migration process
        :param original_volume_status: The status of the original volume
        :return model_update to update DB with any needed changes
        """
        # We use id as our volume name so we need to rename the backend
        # volume to the original volume name.
        original_volume_name = volume.get('id')
        current_name = new_volume.get('id')
        LOG.debug('update_migrated_volume: %(current)s to %(original)s',
                  {'current': current_name,
                   'original': original_volume_name})
        if original_volume_name:
            with self._client.open_connection() as api:
                if api.find_sc():
                    scvolume = api.find_volume(current_name)
                    if (scvolume and
                       api.rename_volume(scvolume, original_volume_name)):
                        model_update = {'_name_id': None}
                        return model_update
        # The world was horrible to us so we should error and leave.
        LOG.error(_LE('Unable to rename the logical volume for volume: %s'),
                  original_volume_name)

        return {'_name_id': new_volume['_name_id'] or new_volume['id']}

    def create_consistencygroup(self, context, group):
        """This creates a replay profile on the storage backend.

        :param context: the context of the caller.
        :param group: the dictionary of the consistency group to be created.
        :return: Nothing on success.
        :raises: VolumeBackendAPIException
        """
        gid = group['id']
        with self._client.open_connection() as api:
            cgroup = api.create_replay_profile(gid)
            if cgroup:
                LOG.info(_LI('Created Consistency Group %s'), gid)
                return
        raise exception.VolumeBackendAPIException(
            _('Unable to create consistency group %s') % gid)

    def delete_consistencygroup(self, context, group):
        """Delete the Dell SC profile associated with this consistency group.

        :param context: the context of the caller.
        :param group: the dictionary of the consistency group to be created.
        :return: Updated model_update, volumes.
        """
        gid = group['id']
        with self._client.open_connection() as api:
            profile = api.find_replay_profile(gid)
            if profile:
                api.delete_replay_profile(profile)
        # If we are here because we found no profile that should be fine
        # as we are trying to delete it anyway.

        # Now whack the volumes.  So get our list.
        volumes = self.db.volume_get_all_by_group(context, gid)
        # Trundle through the list deleting the volumes.
        for volume in volumes:
            self.delete_volume(volume)
            volume['status'] = 'deleted'

        model_update = {'status': group['status']}

        return model_update, volumes

    def update_consistencygroup(self, context, group,
                                add_volumes=None, remove_volumes=None):
        """Updates a consistency group.

        :param context: the context of the caller.
        :param group: the dictionary of the consistency group to be updated.
        :param add_volumes: a list of volume dictionaries to be added.
        :param remove_volumes: a list of volume dictionaries to be removed.
        :return model_update, add_volumes_update, remove_volumes_update

        model_update is a dictionary that the driver wants the manager
        to update upon a successful return. If None is returned, the manager
        will set the status to 'available'.

        add_volumes_update and remove_volumes_update are lists of dictionaries
        that the driver wants the manager to update upon a successful return.
        Note that each entry requires a {'id': xxx} so that the correct
        volume entry can be updated. If None is returned, the volume will
        remain its original status. Also note that you cannot directly
        assign add_volumes to add_volumes_update as add_volumes is a list of
        cinder.db.sqlalchemy.models.Volume objects and cannot be used for
        db update directly. Same with remove_volumes.

        If the driver throws an exception, the status of the group as well as
        those of the volumes to be added/removed will be set to 'error'.
        """
        gid = group['id']
        with self._client.open_connection() as api:
            profile = api.find_replay_profile(gid)
            if not profile:
                LOG.error(_LE('Cannot find Consistency Group %s'), gid)
            elif api.update_cg_volumes(profile,
                                       add_volumes,
                                       remove_volumes):
                LOG.info(_LI('Updated Consistency Group %s'), gid)
                # we need nothing updated above us so just return None.
                return None, None, None
        # Things did not go well so throw.
        raise exception.VolumeBackendAPIException(
            _('Unable to update consistency group %s') % gid)

    def create_cgsnapshot(self, context, cgsnapshot):
        """Takes a snapshot of the consistency group.

        :param context: the context of the caller.
        :param cgsnapshot: Information about the snapshot to take.
        :return: Updated model_update, snapshots.
        :raises: VolumeBackendAPIException.
        """
        cgid = cgsnapshot['consistencygroup_id']
        snapshotid = cgsnapshot['id']

        with self._client.open_connection() as api:
            profile = api.find_replay_profile(cgid)
            if profile:
                LOG.debug('profile %s replayid %s', profile, snapshotid)
                if api.snap_cg_replay(profile, snapshotid, 0):
                    snapshots = objects.SnapshotList().get_all_for_cgsnapshot(
                        context, snapshotid)
                    for snapshot in snapshots:
                        snapshot.status = 'available'

                    model_update = {'status': 'available'}

                    return model_update, snapshots

                # That didn't go well.  Tell them why.  Then bomb out.
                LOG.error(_LE('Failed to snap Consistency Group %s'), cgid)
            else:
                LOG.error(_LE('Cannot find Consistency Group %s'), cgid)

        raise exception.VolumeBackendAPIException(
            _('Unable to snap Consistency Group %s') % cgid)

    def delete_cgsnapshot(self, context, cgsnapshot):
        """Deletes a cgsnapshot.

        If profile isn't found return success.  If failed to delete the
        replay (the snapshot) then raise an exception.

        :param context: the context of the caller.
        :param cgsnapshot: Information about the snapshot to delete.
        :return: Updated model_update, snapshots.
        :raises: VolumeBackendAPIException.
        """
        cgid = cgsnapshot['consistencygroup_id']
        snapshotid = cgsnapshot['id']

        with self._client.open_connection() as api:
            profile = api.find_replay_profile(cgid)
            if profile:
                LOG.info(_LI('Deleting snapshot %(ss)s from %(pro)s'),
                         {'ss': snapshotid,
                          'pro': profile})
                if not api.delete_cg_replay(profile, snapshotid):
                    raise exception.VolumeBackendAPIException(
                        _('Unable to delete Consistency Group snapshot %s') %
                        snapshotid)

            snapshots = objects.SnapshotList().get_all_for_cgsnapshot(
                context, snapshotid)
            for snapshot in snapshots:
                snapshot.status = 'deleted'

            model_update = {'status': 'deleted'}

            return model_update, snapshots

    def manage_existing(self, volume, existing_ref):
        """Brings an existing backend storage object under Cinder management.

        existing_ref is passed straight through from the API request's
        manage_existing_ref value, and it is up to the driver how this should
        be interpreted.  It should be sufficient to identify a storage object
        that the driver should somehow associate with the newly-created cinder
        volume structure.

        There are two ways to do this:

        1. Rename the backend storage object so that it matches the,
           volume['name'] which is how drivers traditionally map between a
           cinder volume and the associated backend storage object.

        2. Place some metadata on the volume, or somewhere in the backend, that
           allows other driver requests (e.g. delete, clone, attach, detach...)
           to locate the backend storage object when required.

        If the existing_ref doesn't make sense, or doesn't refer to an existing
        backend storage object, raise a ManageExistingInvalidReference
        exception.

        The volume may have a volume_type, and the driver can inspect that and
        compare against the properties of the referenced backend storage
        object.  If they are incompatible, raise a
        ManageExistingVolumeTypeMismatch, specifying a reason for the failure.

        :param volume:       Cinder volume to manage
        :param existing_ref: Driver-specific information used to identify a
        volume
        """
        if existing_ref.get('source-name') or existing_ref.get('source-id'):
            with self._client.open_connection() as api:
                api.manage_existing(volume['id'], existing_ref)
        else:
            raise exception.ManageExistingInvalidReference(
                _('Must specify source-name or source-id. (%s)') %
                existing_ref)

    def manage_existing_get_size(self, volume, existing_ref):
        """Return size of volume to be managed by manage_existing.

        When calculating the size, round up to the next GB.

        :param volume:       Cinder volume to manage
        :param existing_ref: Driver-specific information used to identify a
        volume
        """
        if existing_ref.get('source-name') or existing_ref.get('source-id'):
            with self._client.open_connection() as api:
                return api.get_unmanaged_volume_size(existing_ref)
        else:
            raise exception.ManageExistingInvalidReference(
                _('Must specify source-name or source-id. (%s)') %
                existing_ref)

    def unmanage(self, volume):
        """Removes the specified volume from Cinder management.

        Does not delete the underlying backend storage object.

        For most drivers, this will not need to do anything.  However, some
        drivers might use this call as an opportunity to clean up any
        Cinder-specific configuration that they have associated with the
        backend storage object.

        :param volume: Cinder volume to unmanage
        """
        with self._client.open_connection() as api:
            scvolume = api.find_volume(volume['id'])
            if scvolume:
                api.unmanage(scvolume)

    def retype(self, ctxt, volume, new_type, diff, host):
        """Convert the volume to be of the new type.

        Returns a boolean indicating whether the retype occurred.

        :param ctxt: Context
        :param volume: A dictionary describing the volume to migrate
        :param new_type: A dictionary describing the volume type to convert to
        :param diff: A dictionary with the difference between the two types
        :param host: A dictionary describing the host to migrate to, where
                     host['host'] is its name, and host['capabilities'] is a
                     dictionary of its reported capabilities (Not Used).
        """
        # We currently only support retyping for the Storage Profile extra spec
        if diff['extra_specs']:
            storage_profiles = diff['extra_specs'].get(
                'storagetype:storageprofile')
            if storage_profiles:
                if len(storage_profiles) != 2:
                    LOG.warning(_LW('Unable to retype Storage Profile, '
                                    'expected to receive current and '
                                    'requested storagetype:storageprofile '
                                    'values. Value received: %s'),
                                storage_profiles)
                    return False

                current = storage_profiles[0]
                requested = storage_profiles[1]

                if current != requested:
                    volume_name = volume.get('id')
                    LOG.debug('Retyping volume %(vol)s to use storage '
                              'profile %(profile)s.',
                              {'vol': volume_name,
                               'profile': requested})
                    with self._client.open_connection() as api:
                        if api.find_sc():
                            scvolume = api.find_volume(volume_name)
                            return api.update_storage_profile(
                                scvolume, requested)
                else:
                    # We only support retype of Storage Profile and they are
                    # the same, so just return True to avoid unnecessary data
                    # migration.
                    LOG.info(_LI('Retype was to same Storage Profile.'))
                    return True

        return False
