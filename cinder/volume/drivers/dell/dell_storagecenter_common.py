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
    cfg.PortOpt('dell_sc_api_port',
                default=3033,
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
                       driver.ExtendVD, driver.ReplicaV2VD,
                       driver.SnapshotVD, driver.BaseVD):

    def __init__(self, *args, **kwargs):
        super(DellCommonDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(common_opts)
        self.configuration.append_config_values(san_opts)
        self.backend_name =\
            self.configuration.safe_get('volume_backend_name') or 'Dell'
        self.backends = self.configuration.safe_get('replication_device')
        self.replication_enabled = True if self.backends else False
        self.is_direct_connect = False

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
            self.is_direct_connect = api.is_direct_connect
            if self.is_direct_connect and self.replication_enabled:
                msg = _('Dell Cinder driver configuration error replication '
                        'not supported with direct connect.')
                raise exception.InvalidHost(reason=msg)

            if self.replication_enabled:
                # Check that our replication destinations are available.
                # TODO(tswanson): Check if we need a diskfolder.  (Or not.)
                # TODO(tswanson): Can we check that the backend specifies
                # TODO(tswanson): the same ssn as target_device_id.
                for backend in self.backends:
                    replssn = backend['target_device_id']
                    try:
                        # Just do a find_sc on it.  If it raises we catch
                        # that and raise with a correct exception.
                        api.find_sc(int(replssn))
                    except exception.VolumeBackendAPIException:
                        msg = _('Dell Cinder driver configuration error '
                                'replication_device %s not found') % replssn
                        raise exception.InvalidHost(reason=msg)

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
        :returns: Nothing.
        """
        if scvolume and volume.get('consistencygroup_id'):
            profile = api.find_replay_profile(
                volume.get('consistencygroup_id'))
            if profile:
                api.update_cg_volumes(profile, [volume])

    def _do_repl(self, api, volume):
        """Checks if we can do replication.

        Need the extra spec set and we have to be talking to EM.

        :param api: Dell REST API object.
        :param volume: Cinder Volume object.
        :return: Boolean (True if replication enabled), Boolean (True if
                 replication type is sync.
        """
        do_repl = False
        sync = False
        if not self.is_direct_connect:
            specs = self._get_volume_extra_specs(volume)
            do_repl = specs.get('replication_enabled') == '<is> True'
            sync = specs.get('replication_type') == '<in> sync'
        return do_repl, sync

    def _create_replications(self, api, volume, scvolume):
        """Creates any appropriate replications for a given volume.

        :param api: Dell REST API object.
        :param volume: Cinder volume object.
        :param scvolume: Dell Storage Center Volume object.
        :return: model_update
        """
        # Replication V2
        # for now we assume we have an array named backends.
        replication_driver_data = None
        # Replicate if we are supposed to.
        do_repl, sync = self._do_repl(api, volume)
        if do_repl:
            for backend in self.backends:
                # Check if we are to replicate the active replay or not.
                specs = self._get_volume_extra_specs(volume)
                replact = specs.get('replication:activereplay') == '<is> True'
                if not api.create_replication(scvolume,
                                              backend['target_device_id'],
                                              backend.get('qosnode',
                                                          'cinderqos'),
                                              sync,
                                              backend.get('diskfolder', None),
                                              replact):
                    # Create replication will have printed a better error.
                    msg = _('Replication %(name)s to %(ssn)s failed.') % {
                        'name': volume['id'],
                        'ssn': backend['target_device_id']}
                    raise exception.VolumeBackendAPIException(data=msg)
                if not replication_driver_data:
                    replication_driver_data = backend['target_device_id']
                else:
                    replication_driver_data += ','
                    replication_driver_data += backend['target_device_id']
        # If we did something return model update.
        model_update = {}
        if replication_driver_data:
            model_update = {'replication_status': 'enabled',
                            'replication_driver_data': replication_driver_data}
        return model_update

    @staticmethod
    def _cleanup_failed_create_volume(api, volumename):
        try:
            api.delete_volume(volumename)
        except exception.VolumeBackendAPIException as ex:
            LOG.info(_LI('Non fatal cleanup error: %s.'), ex.msg)

    def create_volume(self, volume):
        """Create a volume."""
        model_update = {}

        # We use id as our name as it is unique.
        volume_name = volume.get('id')
        # Look for our volume
        volume_size = volume.get('size')

        # See if we have any extra specs.
        specs = self._get_volume_extra_specs(volume)
        storage_profile = specs.get('storagetype:storageprofile')
        replay_profile_string = specs.get('storagetype:replayprofiles')

        LOG.debug('Creating volume %(name)s of size %(size)s',
                  {'name': volume_name,
                   'size': volume_size})
        scvolume = None
        with self._client.open_connection() as api:
            try:
                if api.find_sc():
                    scvolume = api.create_volume(volume_name,
                                                 volume_size,
                                                 storage_profile,
                                                 replay_profile_string)
                    if scvolume is None:
                        raise exception.VolumeBackendAPIException(
                            message=_('Unable to create volume %s') %
                            volume_name)

                # Update Consistency Group
                self._add_volume_to_consistency_group(api, scvolume, volume)

                # Create replications. (Or not. It checks.)
                model_update = self._create_replications(api, volume, scvolume)

            except Exception:
                # if we actually created a volume but failed elsewhere
                # clean up the volume now.
                self._cleanup_failed_create_volume(api, volume_name)
                with excutils.save_and_reraise_exception():
                    LOG.error(_LE('Failed to create volume %s'),
                              volume_name)
        if scvolume is None:
            raise exception.VolumeBackendAPIException(
                data=_('Unable to create volume. Backend down.'))

        return model_update

    def _split(self, replication_driver_data):
        ssnstrings = []
        if replication_driver_data:
            for str in replication_driver_data.split(','):
                ssnstring = str.strip()
                if ssnstring:
                    ssnstrings.append(ssnstring)
        return ssnstrings

    def _delete_replications(self, api, volume):
        """Delete replications associated with a given volume.

        We should be able to roll through the replication_driver_data list
        of SSNs and delete replication objects between them and the source
        volume.

        :param api: Dell REST API object.
        :param volume: Cinder Volume object
        :return:
        """
        do_repl, sync = self._do_repl(api, volume)
        if do_repl:
            volume_name = volume.get('id')
            scvol = api.find_volume(volume_name)
            replication_driver_data = volume.get('replication_driver_data')
            # This is just a string of ssns separated by commas.
            ssnstrings = self._split(replication_driver_data)
            # Trundle through these and delete them all.
            for ssnstring in ssnstrings:
                ssn = int(ssnstring)
                if not api.delete_replication(scvol, ssn):
                    LOG.warning(_LW('Unable to delete replication of '
                                    'Volume %(vname)s to Storage Center '
                                    '%(sc)s.'),
                                {'vname': volume_name,
                                 'sc': ssnstring})
        # If none of that worked or there was nothing to do doesn't matter.
        # Just move on.

    def delete_volume(self, volume):
        deleted = False
        # We use id as our name as it is unique.
        volume_name = volume.get('id')
        LOG.debug('Deleting volume %s', volume_name)
        with self._client.open_connection() as api:
            try:
                if api.find_sc():
                    self._delete_replications(api, volume)
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
        msg = _('Failed to create snapshot %s') % snapshot_id
        raise exception.VolumeBackendAPIException(data=msg)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Create new volume from other volume's snapshot on appliance."""
        model_update = {}
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
                            # See if we have any extra specs.
                            specs = self._get_volume_extra_specs(volume)
                            replay_profile_string = specs.get(
                                'storagetype:replayprofiles')
                            scvolume = api.create_view_volume(
                                volume_name, replay, replay_profile_string)
                            if scvolume is None:
                                raise exception.VolumeBackendAPIException(
                                    message=_('Unable to create volume '
                                              '%(name)s from %(snap)s.') %
                                    {'name': volume_name,
                                     'snap': snapshot_id})

                            # Update Consistency Group
                            self._add_volume_to_consistency_group(api,
                                                                  scvolume,
                                                                  volume)
                            # Replicate if we are supposed to.
                            model_update = self._create_replications(api,
                                                                     volume,
                                                                     scvolume)

            except Exception:
                # Clean up after ourselves.
                self._cleanup_failed_create_volume(api, volume_name)
                with excutils.save_and_reraise_exception():
                    LOG.error(_LE('Failed to create volume %s'),
                              volume_name)
        if scvolume is not None:
            LOG.debug('Volume %(vol)s created from %(snap)s',
                      {'vol': volume_name,
                       'snap': snapshot_id})
        else:
            msg = _('Failed to create volume %s') % volume_name
            raise exception.VolumeBackendAPIException(data=msg)

        return model_update

    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume."""
        model_update = {}
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
                        # See if we have any extra specs.
                        specs = self._get_volume_extra_specs(volume)
                        replay_profile_string = specs.get(
                            'storagetype:replayprofiles')
                        # Create our volume
                        scvolume = api.create_cloned_volume(
                            volume_name, srcvol, replay_profile_string)
                        if scvolume is None:
                            raise exception.VolumeBackendAPIException(
                                message=_('Unable to create volume '
                                          '%(name)s from %(vol)s.') %
                                {'name': volume_name,
                                 'vol': src_volume_name})

                        # Update Consistency Group
                        self._add_volume_to_consistency_group(api,
                                                              scvolume,
                                                              volume)
                        # Replicate if we are supposed to.
                        model_update = self._create_replications(api,
                                                                 volume,
                                                                 scvolume)
            except Exception:
                # Clean up after ourselves.
                self._cleanup_failed_create_volume(api, volume_name)
                with excutils.save_and_reraise_exception():
                    LOG.error(_LE('Failed to create volume %s'),
                              volume_name)
        if scvolume is not None:
            LOG.debug('Volume %(vol)s cloned from %(src)s',
                      {'vol': volume_name,
                       'src': src_volume_name})
        else:
            msg = _('Failed to create volume %s') % volume_name
            raise exception.VolumeBackendAPIException(data=msg)
        return model_update

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
        msg = _('Failed to delete snapshot %s') % snapshot_id
        raise exception.VolumeBackendAPIException(data=msg)

    def create_export(self, context, volume, connector):
        """Create an export of a volume.

        The volume exists on creation and will be visible on
        initialize connection.  So nothing to do here.
        """
        # TODO(tswanson): Move mapping code here.
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
            msg = _('Unable to find volume %s') % volume_name
            raise exception.VolumeBackendAPIException(data=msg)

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
        msg = _('Unable to extend volume %s') % volume_name
        raise exception.VolumeBackendAPIException(data=msg)

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
            data['replication_enabled'] = self.replication_enabled
            if self.replication_enabled:
                data['replication_type'] = ['async', 'sync']
                data['replication_count'] = len(self.backends)

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
        :returns: model_update to update DB with any needed changes
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
                        # Replicate if we are supposed to.
                        model_update = self._create_replications(api,
                                                                 new_volume,
                                                                 scvolume)
                        model_update['_name_id'] = None

                        return model_update
        # The world was horrible to us so we should error and leave.
        LOG.error(_LE('Unable to rename the logical volume for volume: %s'),
                  original_volume_name)

        return {'_name_id': new_volume['_name_id'] or new_volume['id']}

    def create_consistencygroup(self, context, group):
        """This creates a replay profile on the storage backend.

        :param context: the context of the caller.
        :param group: the dictionary of the consistency group to be created.
        :returns: Nothing on success.
        :raises: VolumeBackendAPIException
        """
        gid = group['id']
        with self._client.open_connection() as api:
            cgroup = api.create_replay_profile(gid)
            if cgroup:
                LOG.info(_LI('Created Consistency Group %s'), gid)
                return
        msg = _('Unable to create consistency group %s') % gid
        raise exception.VolumeBackendAPIException(data=msg)

    def delete_consistencygroup(self, context, group, volumes):
        """Delete the Dell SC profile associated with this consistency group.

        :param context: the context of the caller.
        :param group: the dictionary of the consistency group to be created.
        :returns: Updated model_update, volumes.
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
        :returns: model_update, add_volumes_update, remove_volumes_update

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
        msg = _('Unable to update consistency group %s') % gid
        raise exception.VolumeBackendAPIException(data=msg)

    def create_cgsnapshot(self, context, cgsnapshot, snapshots):
        """Takes a snapshot of the consistency group.

        :param context: the context of the caller.
        :param cgsnapshot: Information about the snapshot to take.
        :returns: Updated model_update, snapshots.
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

        msg = _('Unable to snap Consistency Group %s') % cgid
        raise exception.VolumeBackendAPIException(data=msg)

    def delete_cgsnapshot(self, context, cgsnapshot, snapshots):
        """Deletes a cgsnapshot.

        If profile isn't found return success.  If failed to delete the
        replay (the snapshot) then raise an exception.

        :param context: the context of the caller.
        :param cgsnapshot: Information about the snapshot to delete.
        :returns: Updated model_update, snapshots.
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
                    msg = (_('Unable to delete Consistency Group snapshot %s')
                           % snapshotid)
                    raise exception.VolumeBackendAPIException(data=msg)

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
                # Replicate if we are supposed to.
                scvolume = api.find_volume(volume['id'])
                model_update = self._create_replications(api, volume, scvolume)
                if model_update:
                    return model_update
        else:
            msg = _('Must specify source-name or source-id.')
            raise exception.ManageExistingInvalidReference(
                existing_ref=existing_ref, reason=msg)
        # Only return a model_update if we have replication info to add.
        return None

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
            msg = _('Must specify source-name or source-id.')
            raise exception.ManageExistingInvalidReference(
                existing_ref=existing_ref, reason=msg)

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

    def _get_retype_spec(self, diff, volume_name, specname, spectype):
        """Helper function to get current and requested spec.

        :param diff: A difference dictionary.
        :param volume_name: The volume name we are working with.
        :param specname: The pretty name of the parameter.
        :param spectype: The actual spec string.
        :return: current, requested spec.
        :raises: VolumeBackendAPIException
        """
        spec = (diff['extra_specs'].get(spectype))
        if spec:
            if len(spec) != 2:
                msg = _('Unable to retype %(specname)s, expected to receive '
                        'current and requested %(spectype)s values. Value '
                        'received: %(spec)s') % {'specname': specname,
                                                 'spectype': spectype,
                                                 'spec': spec}
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

            current = spec[0]
            requested = spec[1]

            if current != requested:
                LOG.debug('Retyping volume %(vol)s to use %(specname)s '
                          '%(spec)s.',
                          {'vol': volume_name,
                           'specname': specname,
                           'spec': requested})
                return current, requested
            else:
                LOG.info(_LI('Retype was to same Storage Profile.'))
        return None, None

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
        model_update = None
        # Any spec changes?
        if diff['extra_specs']:
            volume_name = volume.get('id')
            with self._client.open_connection() as api:
                try:
                    # Get our volume
                    scvolume = api.find_volume(volume_name)
                    if scvolume is None:
                        LOG.error(_LE('Retype unable to find volume %s.'),
                                  volume_name)
                        return False
                    # Check our specs.
                    # Storage profiles.
                    current, requested = (
                        self._get_retype_spec(diff, volume_name,
                                              'Storage Profile',
                                              'storagetype:storageprofile'))
                    # if there is a change and it didn't work fast fail.
                    if (current != requested and not
                       api.update_storage_profile(scvolume, requested)):
                        LOG.error(_LE('Failed to update storage profile'))
                        return False

                    # Replay profiles.
                    current, requested = (
                        self._get_retype_spec(diff, volume_name,
                                              'Replay Profiles',
                                              'storagetype:replayprofiles'))
                    # if there is a change and it didn't work fast fail.
                    if requested and not api.update_replay_profiles(scvolume,
                                                                    requested):
                        LOG.error(_LE('Failed to update replay profiles'))
                        return False

                    # Replication_enabled.
                    current, requested = (
                        self._get_retype_spec(diff,
                                              volume_name,
                                              'replication_enabled',
                                              'replication_enabled'))
                    # if there is a change and it didn't work fast fail.
                    if current != requested:
                        if requested:
                            model_update = self._create_replications(api,
                                                                     volume,
                                                                     scvolume)
                        else:
                            self._delete_replications(api, volume)
                            model_update = {'replication_status': 'disabled',
                                            'replication_driver_data': ''}

                    # Active Replay
                    current, requested = (
                        self._get_retype_spec(diff, volume_name,
                                              'Replicate Active Replay',
                                              'replication:activereplay'))
                    if current != requested and not (
                            api.update_replicate_active_replay(
                                scvolume, requested == '<is> True')):
                        LOG.error(_LE('Failed to apply '
                                      'replication:activereplay setting'))
                        return False

                    # TODO(tswanson): replaytype once it actually works.

                except exception.VolumeBackendAPIException:
                    # We do nothing with this. We simply return failure.
                    return False
        # If we have something to send down...
        if model_update:
            return model_update
        return True

    def replication_enable(self, context, vref):
        """Re-enable replication on vref.

        :param context: NA
        :param vref: Cinder volume reference.
        :return: model_update.
        """
        volumename = vref.get('id')
        LOG.info(_LI('Enabling replication on %s'), volumename)
        model_update = {}
        with self._client.open_connection() as api:
            replication_driver_data = vref.get('replication_driver_data')
            destssns = self._split(replication_driver_data)
            do_repl, sync = self._do_repl(api, vref)
            if destssns and do_repl:
                scvolume = api.find_volume(volumename)
                if scvolume:
                    for destssn in destssns:
                        if not api.resume_replication(scvolume, int(destssn)):
                            LOG.error(_LE('Unable to resume replication on '
                                          'volume %(vol)s to SC %(ssn)s'),
                                      {'vol': volumename,
                                       'ssn': destssn})
                            model_update['replication_status'] = 'error'
                            break
                else:
                    LOG.error(_LE('Volume %s not found'), volumename)
            else:
                LOG.error(_LE('Replication not enabled or no replication '
                              'destinations found.  %s'),
                          volumename)
        return model_update

    def replication_disable(self, context, vref):
        """Disable replication on vref.

        :param context: NA
        :param vref: Cinder volume reference.
        :return: model_update.
        """
        volumename = vref.get('id')
        LOG.info(_LI('Disabling replication on %s'), volumename)
        model_update = {}
        with self._client.open_connection() as api:
            replication_driver_data = vref.get('replication_driver_data')
            destssns = self._split(replication_driver_data)
            do_repl, sync = self._do_repl(api, vref)
            if destssns and do_repl:
                scvolume = api.find_volume(volumename)
                if scvolume:
                    for destssn in destssns:
                        if not api.pause_replication(scvolume, int(destssn)):
                            LOG.error(_LE('Unable to pause replication on '
                                          'volume %(vol)s to SC %(ssn)s'),
                                      {'vol': volumename,
                                       'ssn': destssn})
                            model_update['replication_status'] = 'error'
                            break
                else:
                    LOG.error(_LE('Volume %s not found'), volumename)
            else:
                LOG.error(_LE('Replication not enabled or no replication '
                              'destinations found.  %s'),
                          volumename)
        return model_update

    def _find_host(self, ssnstring):
        """Find the backend associated with this ssnstring.

        :param ssnstring: The ssn of the storage center we are looking for.
        :return: The managed_backend_name associated with said storage center.
        """
        for backend in self.backends:
            if ssnstring == backend['target_device_id']:
                return backend['managed_backend_name']
        return None

    def _parse_secondary(self, api, vref, secondary):
        """Find the replication destination associated with secondary.

        :param api: Dell StorageCenterApi
        :param vref: Cinder Volume
        :param secondary: String indicating the secondary to failover to.
        :return: Destination SSN and the host string for the given secondary.
        """
        LOG.debug('_parse_secondary. Looking for %s.', secondary)
        replication_driver_data = vref['replication_driver_data']
        destssn = None
        host = None
        ssnstrings = self._split(replication_driver_data)
        # Trundle through these and delete them all.
        for ssnstring in ssnstrings:
            # If they list a secondary it has to match.
            # If they do not list a secondary we return the first
            # replication on a working system.
            if not secondary or secondary == ssnstring:
                # Is a string.  Need an int.
                ssn = int(ssnstring)
                # Without the source being up we have no good
                # way to pick a destination to failover to. So just
                # look for one that is just up.
                try:
                    # If the SC ssn exists check if we are configured to
                    # use it.
                    if api.find_sc(ssn):
                        host = self._find_host(ssnstring)
                        # If host then we are configured.
                        if host:
                            # Save our ssn and get out of here.
                            destssn = ssn
                            break
                except exception.VolumeBackendAPIException:
                    LOG.warning(_LW('SSN %s appears to be down.'), ssn)
        LOG.info(_LI('replication failover secondary is %(ssn)s %(host)s'),
                 {'ssn': destssn,
                  'host': host})
        return destssn, host

    def replication_failover(self, context, vref, secondary):
        """Failover to secondary.

        The flow is as follows.
            1.The user explicitly requests a failover of a replicated volume.
            2.Driver breaks replication.
                a. Neatly by deleting the SCReplication object if the
                   primary is still up.
                b. Brutally by unmapping the replication volume if it isn't.
            3.We rename the volume to "Cinder failover <Volume GUID>"
            4.Change Cinder DB entry for which backend controls the volume
              to the backend listed in the replication_device.
            5.That's it.

        Completion of the failover is done on first use on the new backend.
        We do this by modifying the find_volume function.

        Find volume searches the following places in order:
            1. "<Volume GUID>" in the backend's volume folder.
            2. "<Volume GUID>" outside of the volume folder.
            3. "Cinder failover <Volume GUID>" anywhere on the system.

        If "Cinder failover <Volume GUID>" was found:
            1.Volume is renamed to "<Volume GUID>".
            2.Volume is moved to the new backend's volume folder.
            3.The volume is now available on the secondary backend.

        :param context;
        :param vref: Cinder volume reference.
        :param secondary:  SSN of the destination Storage Center
        :return: model_update on failover.
        """
        LOG.info(_LI('Failing replication %(vol)s to %(sec)s'),
                 {'vol': vref.get('id'),
                  'sec': secondary})
        # If we fall through this is our error.
        msg = _('Unable to failover replication.')
        with self._client.open_connection() as api:
            # Basic check.  We should never get here.
            do_repl, sync = self._do_repl(api, vref)
            if not do_repl:
                # If we did get here then there is a disconnect.  Set our
                # message and raise (below).
                msg = _('Unable to failover unreplicated volume.')
            else:
                # Look for the specified secondary.
                destssn, host = self._parse_secondary(api, vref, secondary)
                if destssn and host:
                    volumename = vref.get('id')
                    # This will break the replication on the SC side.  At the
                    # conclusion of this the destination volume will be
                    # renamed to indicate failover is in progress.  We will
                    # pick the volume up on the destination backend later.
                    if api.break_replication(volumename, destssn):
                        model_update = {}
                        model_update['host'] = host
                        model_update['replication_driver_data'] = None
                        return model_update
                    # We are here.  Nothing went well.
                    LOG.error(_LE('Unable to break replication from '
                                  '%(from)s to %(to)d.'),
                              {'from': volumename,
                               'to': destssn})
                else:
                    LOG.error(_LE('Unable to find valid destination.'))

        # We raise to indicate something bad happened.
        raise exception.ReplicationError(volume_id=vref.get('id'),
                                         reason=msg)

    def list_replication_targets(self, context, vref):
        """Lists replication targets for the given vref.

        We return targets the volume has been setup to replicate to and that
        are configured on this backend.

        :param context: NA
        :param vref: Cinder volume object.
        :return: A dict of the form {'volume_id': id,
                                     'targets': [ {'type': xxx,
                                                   'target_device_id': xxx,
                                                   'backend_name': xxx}]}
        """
        LOG.debug('list_replication_targets for volume %s', vref.get('id'))
        targets = []
        with self._client.open_connection() as api:
            do_repl, sync = self._do_repl(api, vref)
            # If we have no replication_driver_data then we have no replication
            # targets
            replication_driver_data = vref.get('replication_driver_data')
            ssnstrings = self._split(replication_driver_data)
            # If we have data.
            if ssnstrings:
                # Trundle through our backends.
                for backend in self.backends:
                    # If we find a backend then we report it.
                    if ssnstrings.count(backend['target_device_id']):
                        target = {}
                        target['type'] = 'managed'
                        target['target_device_id'] = (
                            backend['target_device_id'])
                        target['backend_name'] = (
                            backend['managed_backend_name'])
                        targets.append(target)
                    else:
                        # We note if the source is not replicated to a
                        # configured destination for the backend.
                        LOG.info(_LI('Volume %(guid)s not replicated to '
                                     'backend %(name)s'),
                                 {'guid': vref['id'],
                                  'name': backend['managed_backend_name']})
            # At this point we note that what we found and what we
            # expected to find were two different things.
            if len(ssnstrings) != len(targets):
                LOG.warning(_LW('Expected replication count %(rdd)d does '
                                'match configured replication count '
                                '%(tgt)d.'),
                            {'rdd': len(ssnstrings),
                             'tgt': len(targets)})
        # Format response.
        replication_targets = {'volume_id': vref.get('id'), 'targets': targets}
        LOG.info(_LI('list_replication_targets: %s'), replication_targets)
        return replication_targets

    def get_replication_updates(self, context):
        # No idea what to do with this.
        return []
