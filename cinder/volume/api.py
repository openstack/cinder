# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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
Handles all requests relating to volumes.
"""


import collections
import functools

from oslo.config import cfg

from cinder import context
from cinder.db import base
from cinder import exception
from cinder.image import glance
from cinder import keymgr
from cinder.openstack.common import excutils
from cinder.openstack.common import log as logging
from cinder.openstack.common import timeutils
import cinder.policy
from cinder import quota
from cinder.scheduler import rpcapi as scheduler_rpcapi
from cinder import units
from cinder import utils
from cinder.volume.flows import create_volume
from cinder.volume import rpcapi as volume_rpcapi
from cinder.volume import volume_types

from cinder.taskflow import states


volume_host_opt = cfg.BoolOpt('snapshot_same_host',
                              default=True,
                              help='Create volume from snapshot at the host '
                                   'where snapshot resides')
volume_same_az_opt = cfg.BoolOpt('cloned_volume_same_az',
                                 default=True,
                                 help='Ensure that the new volumes are the '
                                      'same AZ as snapshot or source volume')

CONF = cfg.CONF
CONF.register_opt(volume_host_opt)
CONF.register_opt(volume_same_az_opt)
CONF.import_opt('storage_availability_zone', 'cinder.volume.manager')

LOG = logging.getLogger(__name__)
QUOTAS = quota.QUOTAS


def wrap_check_policy(func):
    """Check policy corresponding to the wrapped methods prior to execution

    This decorator requires the first 3 args of the wrapped function
    to be (self, context, volume)
    """
    @functools.wraps(func)
    def wrapped(self, context, target_obj, *args, **kwargs):
        check_policy(context, func.__name__, target_obj)
        return func(self, context, target_obj, *args, **kwargs)

    return wrapped


def check_policy(context, action, target_obj=None):
    target = {
        'project_id': context.project_id,
        'user_id': context.user_id,
    }
    target.update(target_obj or {})
    _action = 'volume:%s' % action
    cinder.policy.enforce(context, _action, target)


class API(base.Base):
    """API for interacting with the volume manager."""

    def __init__(self, db_driver=None, image_service=None):
        self.image_service = (image_service or
                              glance.get_default_image_service())
        self.scheduler_rpcapi = scheduler_rpcapi.SchedulerAPI()
        self.volume_rpcapi = volume_rpcapi.VolumeAPI()
        self.availability_zone_names = ()
        self.key_manager = keymgr.API()
        super(API, self).__init__(db_driver)

    def _valid_availability_zone(self, availability_zone):
        #NOTE(bcwaldon): This approach to caching fails to handle the case
        # that an availability zone is disabled/removed.
        if availability_zone in self.availability_zone_names:
            return True
        if CONF.storage_availability_zone == availability_zone:
            return True

        azs = self.list_availability_zones()
        self.availability_zone_names = [az['name'] for az in azs]
        return availability_zone in self.availability_zone_names

    def list_availability_zones(self):
        """Describe the known availability zones

        :retval list of dicts, each with a 'name' and 'available' key
        """
        topic = CONF.volume_topic
        ctxt = context.get_admin_context()
        services = self.db.service_get_all_by_topic(ctxt, topic)
        az_data = [(s['availability_zone'], s['disabled']) for s in services]

        disabled_map = {}
        for (az_name, disabled) in az_data:
            tracked_disabled = disabled_map.get(az_name, True)
            disabled_map[az_name] = tracked_disabled and disabled

        azs = [{'name': name, 'available': not disabled}
               for (name, disabled) in disabled_map.items()]

        return tuple(azs)

    def create(self, context, size, name, description, snapshot=None,
               image_id=None, volume_type=None, metadata=None,
               availability_zone=None, source_volume=None,
               scheduler_hints=None, backup_source_volume=None):

        def check_volume_az_zone(availability_zone):
            try:
                return self._valid_availability_zone(availability_zone)
            except exception.CinderException:
                LOG.exception(_("Unable to query if %s is in the "
                                "availability zone set"), availability_zone)
                return False

        create_what = {
            'size': size,
            'name': name,
            'description': description,
            'snapshot': snapshot,
            'image_id': image_id,
            'volume_type': volume_type,
            'metadata': metadata,
            'availability_zone': availability_zone,
            'source_volume': source_volume,
            'scheduler_hints': scheduler_hints,
            'key_manager': self.key_manager,
            'backup_source_volume': backup_source_volume,
        }
        (flow, uuid) = create_volume.get_api_flow(self.scheduler_rpcapi,
                                                  self.volume_rpcapi,
                                                  self.db,
                                                  self.image_service,
                                                  check_volume_az_zone,
                                                  create_what)

        assert flow, _('Create volume flow not retrieved')
        flow.run(context)
        if flow.state != states.SUCCESS:
            raise exception.CinderException(_("Failed to successfully complete"
                                              " create volume workflow"))

        # Extract the volume information from the task uuid that was specified
        # to produce said information.
        volume = None
        try:
            volume = flow.results[uuid]['volume']
        except KeyError:
            pass

        # Raise an error, nobody provided it??
        assert volume, _('Expected volume result not found')
        return volume

    @wrap_check_policy
    def delete(self, context, volume, force=False):
        if context.is_admin and context.project_id != volume['project_id']:
            project_id = volume['project_id']
        else:
            project_id = context.project_id

        volume_id = volume['id']
        if not volume['host']:
            # NOTE(vish): scheduling failed, so delete it
            # Note(zhiteng): update volume quota reservation
            try:
                reserve_opts = {'volumes': -1, 'gigabytes': -volume['size']}
                QUOTAS.add_volume_type_opts(context,
                                            reserve_opts,
                                            volume['volume_type_id'])
                reservations = QUOTAS.reserve(context,
                                              project_id=project_id,
                                              **reserve_opts)
            except Exception:
                reservations = None
                LOG.exception(_("Failed to update quota for deleting volume"))
            self.db.volume_destroy(context.elevated(), volume_id)

            if reservations:
                QUOTAS.commit(context, reservations, project_id=project_id)
            return
        if not force and volume['status'] not in ["available", "error",
                                                  "error_restoring",
                                                  "error_extending"]:
            msg = _("Volume status must be available or error, "
                    "but current status is: %s") % volume['status']
            raise exception.InvalidVolume(reason=msg)

        if volume['attach_status'] == "attached":
            # Volume is still attached, need to detach first
            raise exception.VolumeAttached(volume_id=volume_id)

        if volume['migration_status'] != None:
            # Volume is migrating, wait until done
            msg = _("Volume cannot be deleted while migrating")
            raise exception.InvalidVolume(reason=msg)

        snapshots = self.db.snapshot_get_all_for_volume(context, volume_id)
        if len(snapshots):
            msg = _("Volume still has %d dependent snapshots") % len(snapshots)
            raise exception.InvalidVolume(reason=msg)

        # If the volume is encrypted, delete its encryption key from the key
        # manager. This operation makes volume deletion an irreversible process
        # because the volume cannot be decrypted without its key.
        encryption_key_id = volume.get('encryption_key_id', None)
        if encryption_key_id is not None:
            self.key_manager.delete_key(context, encryption_key_id)

        now = timeutils.utcnow()
        self.db.volume_update(context, volume_id, {'status': 'deleting',
                                                   'terminated_at': now})

        self.volume_rpcapi.delete_volume(context, volume)

    @wrap_check_policy
    def update(self, context, volume, fields):
        self.db.volume_update(context, volume['id'], fields)

    def get(self, context, volume_id):
        rv = self.db.volume_get(context, volume_id)
        volume = dict(rv.iteritems())
        check_policy(context, 'get', volume)
        return volume

    def get_all(self, context, marker=None, limit=None, sort_key='created_at',
                sort_dir='desc', filters={}):
        check_policy(context, 'get_all')

        try:
            if limit is not None:
                limit = int(limit)
                if limit < 0:
                    msg = _('limit param must be positive')
                    raise exception.InvalidInput(reason=msg)
        except ValueError:
            msg = _('limit param must be an integer')
            raise exception.InvalidInput(reason=msg)

        if (context.is_admin and 'all_tenants' in filters):
            # Need to remove all_tenants to pass the filtering below.
            del filters['all_tenants']
            volumes = self.db.volume_get_all(context, marker, limit, sort_key,
                                             sort_dir)
        else:
            volumes = self.db.volume_get_all_by_project(context,
                                                        context.project_id,
                                                        marker, limit,
                                                        sort_key, sort_dir)

        # Non-admin shouldn't see temporary target of a volume migration
        if not context.is_admin:
            filters['no_migration_targets'] = True

        if filters:
            LOG.debug(_("Searching by: %s") % str(filters))

            def _check_metadata_match(volume, searchdict):
                volume_metadata = {}
                for i in volume.get('volume_metadata'):
                    volume_metadata[i['key']] = i['value']

                for k, v in searchdict.iteritems():
                    if (k not in volume_metadata.keys() or
                            volume_metadata[k] != v):
                        return False
                return True

            def _check_migration_target(volume, searchdict):
                status = volume['migration_status']
                if status and status.startswith('target:'):
                    return False
                return True

            # search_option to filter_name mapping.
            filter_mapping = {'metadata': _check_metadata_match,
                              'no_migration_targets': _check_migration_target}

            result = []
            not_found = object()
            for volume in volumes:
                # go over all filters in the list
                for opt, values in filters.iteritems():
                    try:
                        filter_func = filter_mapping[opt]
                    except KeyError:
                        def filter_func(volume, value):
                            return volume.get(opt, not_found) == value
                    if not filter_func(volume, values):
                        break  # volume doesn't match this filter
                else:  # did not break out loop
                    result.append(volume)  # volume matches all filters
            volumes = result

        return volumes

    def get_snapshot(self, context, snapshot_id):
        check_policy(context, 'get_snapshot')
        rv = self.db.snapshot_get(context, snapshot_id)
        return dict(rv.iteritems())

    def get_volume(self, context, volume_id):
        check_policy(context, 'get_volume')
        rv = self.db.volume_get(context, volume_id)
        return dict(rv.iteritems())

    def get_all_snapshots(self, context, search_opts=None):
        check_policy(context, 'get_all_snapshots')

        search_opts = search_opts or {}

        if (context.is_admin and 'all_tenants' in search_opts):
            # Need to remove all_tenants to pass the filtering below.
            del search_opts['all_tenants']
            snapshots = self.db.snapshot_get_all(context)
        else:
            snapshots = self.db.snapshot_get_all_by_project(
                context, context.project_id)

        if search_opts:
            LOG.debug(_("Searching by: %s") % str(search_opts))

            results = []
            not_found = object()
            for snapshot in snapshots:
                for opt, value in search_opts.iteritems():
                    if snapshot.get(opt, not_found) != value:
                        break
                else:
                    results.append(snapshot)
            snapshots = results
        return snapshots

    @wrap_check_policy
    def check_attach(self, context, volume):
        # TODO(vish): abstract status checking?
        if volume['status'] != "available":
            msg = _("status must be available")
            raise exception.InvalidVolume(reason=msg)
        if volume['attach_status'] == "attached":
            msg = _("already attached")
            raise exception.InvalidVolume(reason=msg)

    @wrap_check_policy
    def check_detach(self, context, volume):
        # TODO(vish): abstract status checking?
        if volume['status'] != "in-use":
            msg = _("status must be in-use to detach")
            raise exception.InvalidVolume(reason=msg)

    @wrap_check_policy
    def reserve_volume(self, context, volume):
        #NOTE(jdg): check for Race condition bug 1096983
        #explicitly get updated ref and check
        volume = self.db.volume_get(context, volume['id'])
        if volume['status'] == 'available':
            self.update(context, volume, {"status": "attaching"})
        else:
            msg = _("Volume status must be available to reserve")
            LOG.error(msg)
            raise exception.InvalidVolume(reason=msg)

    @wrap_check_policy
    def unreserve_volume(self, context, volume):
        if volume['status'] == "attaching":
            self.update(context, volume, {"status": "available"})

    @wrap_check_policy
    def begin_detaching(self, context, volume):
        # If we are in the middle of a volume migration, we don't want the user
        # to see that the volume is 'detaching'. Having 'migration_status' set
        # will have the same effect internally.
        if not volume['migration_status']:
            self.update(context, volume, {"status": "detaching"})

    @wrap_check_policy
    def roll_detaching(self, context, volume):
        if volume['status'] == "detaching":
            self.update(context, volume, {"status": "in-use"})

    @wrap_check_policy
    def attach(self, context, volume, instance_uuid, host_name,
               mountpoint, mode):
        volume_metadata = self.get_volume_admin_metadata(context.elevated(),
                                                         volume)
        if 'readonly' not in volume_metadata:
            # NOTE(zhiyan): set a default value for read-only flag to metadata.
            self.update_volume_admin_metadata(context.elevated(), volume,
                                              {'readonly': 'False'})
            volume_metadata['readonly'] = 'False'

        if volume_metadata['readonly'] == 'True' and mode != 'ro':
            raise exception.InvalidVolumeAttachMode(mode=mode,
                                                    volume_id=volume['id'])

        return self.volume_rpcapi.attach_volume(context,
                                                volume,
                                                instance_uuid,
                                                host_name,
                                                mountpoint,
                                                mode)

    @wrap_check_policy
    def detach(self, context, volume):
        return self.volume_rpcapi.detach_volume(context, volume)

    @wrap_check_policy
    def initialize_connection(self, context, volume, connector):
        return self.volume_rpcapi.initialize_connection(context,
                                                        volume,
                                                        connector)

    @wrap_check_policy
    def terminate_connection(self, context, volume, connector, force=False):
        self.unreserve_volume(context, volume)
        return self.volume_rpcapi.terminate_connection(context,
                                                       volume,
                                                       connector,
                                                       force)

    @wrap_check_policy
    def accept_transfer(self, context, volume, new_user, new_project):
        return self.volume_rpcapi.accept_transfer(context,
                                                  volume,
                                                  new_user,
                                                  new_project)

    def _create_snapshot(self, context,
                         volume, name, description,
                         force=False, metadata=None):
        check_policy(context, 'create_snapshot', volume)

        if volume['migration_status'] != None:
            # Volume is migrating, wait until done
            msg = _("Snapshot cannot be created while volume is migrating")
            raise exception.InvalidVolume(reason=msg)

        if ((not force) and (volume['status'] != "available")):
            msg = _("must be available")
            raise exception.InvalidVolume(reason=msg)

        try:
            if CONF.no_snapshot_gb_quota:
                reserve_opts = {'snapshots': 1}
            else:
                reserve_opts = {'snapshots': 1, 'gigabytes': volume['size']}
            QUOTAS.add_volume_type_opts(context,
                                        reserve_opts,
                                        volume.get('volume_type_id'))
            reservations = QUOTAS.reserve(context, **reserve_opts)
        except exception.OverQuota as e:
            overs = e.kwargs['overs']
            usages = e.kwargs['usages']
            quotas = e.kwargs['quotas']

            def _consumed(name):
                return (usages[name]['reserved'] + usages[name]['in_use'])

            for over in overs:
                if 'gigabytes' in over:
                    msg = _("Quota exceeded for %(s_pid)s, tried to create "
                            "%(s_size)sG snapshot (%(d_consumed)dG of "
                            "%(d_quota)dG already consumed)")
                    LOG.warn(msg % {'s_pid': context.project_id,
                                    's_size': volume['size'],
                                    'd_consumed': _consumed(over),
                                    'd_quota': quotas[over]})
                    raise exception.VolumeSizeExceedsAvailableQuota(
                        requested=volume['size'],
                        consumed=_consumed('gigabytes'),
                        quota=quotas['gigabytes'])
                elif 'snapshots' in over:
                    msg = _("Quota exceeded for %(s_pid)s, tried to create "
                            "snapshot (%(d_consumed)d snapshots "
                            "already consumed)")

                    LOG.warn(msg % {'s_pid': context.project_id,
                                    'd_consumed': _consumed(over)})
                    raise exception.SnapshotLimitExceeded(
                        allowed=quotas[over])

        self._check_metadata_properties(context, metadata)
        options = {'volume_id': volume['id'],
                   'user_id': context.user_id,
                   'project_id': context.project_id,
                   'status': "creating",
                   'progress': '0%',
                   'volume_size': volume['size'],
                   'display_name': name,
                   'display_description': description,
                   'volume_type_id': volume['volume_type_id'],
                   'encryption_key_id': volume['encryption_key_id'],
                   'metadata': metadata}

        try:
            snapshot = self.db.snapshot_create(context, options)
            QUOTAS.commit(context, reservations)
        except Exception:
            with excutils.save_and_reraise_exception():
                try:
                    self.db.snapshot_destroy(context, volume['id'])
                finally:
                    QUOTAS.rollback(context, reservations)

        self.volume_rpcapi.create_snapshot(context, volume, snapshot)

        return snapshot

    def create_snapshot(self, context,
                        volume, name,
                        description, metadata=None):
        return self._create_snapshot(context, volume, name, description,
                                     False, metadata)

    def create_snapshot_force(self, context,
                              volume, name,
                              description, metadata=None):
        return self._create_snapshot(context, volume, name, description,
                                     True, metadata)

    @wrap_check_policy
    def delete_snapshot(self, context, snapshot, force=False):
        if not force and snapshot['status'] not in ["available", "error"]:
            msg = _("Volume Snapshot status must be available or error")
            raise exception.InvalidSnapshot(reason=msg)
        self.db.snapshot_update(context, snapshot['id'],
                                {'status': 'deleting'})
        volume = self.db.volume_get(context, snapshot['volume_id'])
        self.volume_rpcapi.delete_snapshot(context, snapshot, volume['host'])

    @wrap_check_policy
    def update_snapshot(self, context, snapshot, fields):
        self.db.snapshot_update(context, snapshot['id'], fields)

    @wrap_check_policy
    def get_volume_metadata(self, context, volume):
        """Get all metadata associated with a volume."""
        rv = self.db.volume_metadata_get(context, volume['id'])
        return dict(rv.iteritems())

    @wrap_check_policy
    def delete_volume_metadata(self, context, volume, key):
        """Delete the given metadata item from a volume."""
        self.db.volume_metadata_delete(context, volume['id'], key)

    def _check_metadata_properties(self, context, metadata=None):
        if not metadata:
            metadata = {}

        for k, v in metadata.iteritems():
            if len(k) == 0:
                msg = _("Metadata property key blank")
                LOG.warn(msg)
                raise exception.InvalidVolumeMetadata(reason=msg)
            if len(k) > 255:
                msg = _("Metadata property key greater than 255 characters")
                LOG.warn(msg)
                raise exception.InvalidVolumeMetadataSize(reason=msg)
            if len(v) > 255:
                msg = _("Metadata property value greater than 255 characters")
                LOG.warn(msg)
                raise exception.InvalidVolumeMetadataSize(reason=msg)

    @wrap_check_policy
    def update_volume_metadata(self, context, volume, metadata, delete=False):
        """Updates or creates volume metadata.

        If delete is True, metadata items that are not specified in the
        `metadata` argument will be deleted.

        """
        if delete:
            _metadata = metadata
        else:
            orig_meta = self.get_volume_metadata(context, volume)
            _metadata = orig_meta.copy()
            _metadata.update(metadata)

        self._check_metadata_properties(context, _metadata)

        self.db.volume_metadata_update(context, volume['id'],
                                       _metadata, delete)

        # TODO(jdg): Implement an RPC call for drivers that may use this info

        return _metadata

    def get_volume_metadata_value(self, volume, key):
        """Get value of particular metadata key."""
        metadata = volume.get('volume_metadata')
        if metadata:
            for i in volume['volume_metadata']:
                if i['key'] == key:
                    return i['value']
        return None

    @wrap_check_policy
    def get_volume_admin_metadata(self, context, volume):
        """Get all administration metadata associated with a volume."""
        rv = self.db.volume_admin_metadata_get(context, volume['id'])
        return dict(rv.iteritems())

    @wrap_check_policy
    def delete_volume_admin_metadata(self, context, volume, key):
        """Delete the given administration metadata item from a volume."""
        self.db.volume_admin_metadata_delete(context, volume['id'], key)

    @wrap_check_policy
    def update_volume_admin_metadata(self, context, volume, metadata,
                                     delete=False):
        """Updates or creates volume administration metadata.

        If delete is True, metadata items that are not specified in the
        `metadata` argument will be deleted.

        """
        if delete:
            _metadata = metadata
        else:
            orig_meta = self.get_volume_admin_metadata(context, volume)
            _metadata = orig_meta.copy()
            _metadata.update(metadata)

        self._check_metadata_properties(context, _metadata)

        self.db.volume_admin_metadata_update(context, volume['id'],
                                             _metadata, delete)

        # TODO(jdg): Implement an RPC call for drivers that may use this info

        return _metadata

    def get_snapshot_metadata(self, context, snapshot):
        """Get all metadata associated with a snapshot."""
        rv = self.db.snapshot_metadata_get(context, snapshot['id'])
        return dict(rv.iteritems())

    def delete_snapshot_metadata(self, context, snapshot, key):
        """Delete the given metadata item from a snapshot."""
        self.db.snapshot_metadata_delete(context, snapshot['id'], key)

    def update_snapshot_metadata(self, context,
                                 snapshot, metadata,
                                 delete=False):
        """Updates or creates snapshot metadata.

        If delete is True, metadata items that are not specified in the
        `metadata` argument will be deleted.

        """
        if delete:
            _metadata = metadata
        else:
            orig_meta = self.get_snapshot_metadata(context, snapshot)
            _metadata = orig_meta.copy()
            _metadata.update(metadata)

        self._check_metadata_properties(context, _metadata)

        self.db.snapshot_metadata_update(context,
                                         snapshot['id'],
                                         _metadata,
                                         True)

        # TODO(jdg): Implement an RPC call for drivers that may use this info

        return _metadata

    def get_snapshot_metadata_value(self, snapshot, key):
        pass

    def get_volumes_image_metadata(self, context):
        check_policy(context, 'get_volumes_image_metadata')
        db_data = self.db.volume_glance_metadata_get_all(context)
        results = collections.defaultdict(dict)
        for meta_entry in db_data:
            results[meta_entry['volume_id']].update({meta_entry['key']:
                                                     meta_entry['value']})
        return results

    @wrap_check_policy
    def get_volume_image_metadata(self, context, volume):
        db_data = self.db.volume_glance_metadata_get(context, volume['id'])
        return dict(
            (meta_entry.key, meta_entry.value) for meta_entry in db_data
        )

    def _check_volume_availability(self, context, volume, force):
        """Check if the volume can be used."""
        if volume['status'] not in ['available', 'in-use']:
            msg = _('Volume status must be available/in-use.')
            raise exception.InvalidVolume(reason=msg)
        if not force and 'in-use' == volume['status']:
            msg = _('Volume status is in-use.')
            raise exception.InvalidVolume(reason=msg)

    @wrap_check_policy
    def copy_volume_to_image(self, context, volume, metadata, force):
        """Create a new image from the specified volume."""
        self._check_volume_availability(context, volume, force)

        recv_metadata = self.image_service.create(context, metadata)
        self.update(context, volume, {'status': 'uploading'})
        self.volume_rpcapi.copy_volume_to_image(context,
                                                volume,
                                                recv_metadata)

        response = {"id": volume['id'],
                    "updated_at": volume['updated_at'],
                    "status": 'uploading',
                    "display_description": volume['display_description'],
                    "size": volume['size'],
                    "volume_type": volume['volume_type'],
                    "image_id": recv_metadata['id'],
                    "container_format": recv_metadata['container_format'],
                    "disk_format": recv_metadata['disk_format'],
                    "image_name": recv_metadata.get('name', None)}
        return response

    @wrap_check_policy
    def extend(self, context, volume, new_size):
        if volume['status'] != 'available':
            msg = _('Volume status must be available to extend.')
            raise exception.InvalidVolume(reason=msg)

        size_increase = (int(new_size)) - volume['size']
        if size_increase <= 0:
            msg = (_("New size for extend must be greater "
                     "than current size. (current: %(size)s, "
                     "extended: %(new_size)s)") % {'new_size': new_size,
                                                   'size': volume['size']})
            raise exception.InvalidInput(reason=msg)

        self.update(context, volume, {'status': 'extending'})
        self.volume_rpcapi.extend_volume(context, volume, new_size)

    @wrap_check_policy
    def migrate_volume(self, context, volume, host, force_host_copy):
        """Migrate the volume to the specified host."""

        # We only handle "available" volumes for now
        if volume['status'] not in ['available', 'in-use']:
            msg = _('Volume status must be available/in-use.')
            LOG.error(msg)
            raise exception.InvalidVolume(reason=msg)

        # Make sure volume is not part of a migration
        if volume['migration_status'] != None:
            msg = _("Volume is already part of an active migration")
            raise exception.InvalidVolume(reason=msg)

        # We only handle volumes without snapshots for now
        snaps = self.db.snapshot_get_all_for_volume(context, volume['id'])
        if snaps:
            msg = _("volume must not have snapshots")
            LOG.error(msg)
            raise exception.InvalidVolume(reason=msg)

        # Make sure the host is in the list of available hosts
        elevated = context.elevated()
        topic = CONF.volume_topic
        services = self.db.service_get_all_by_topic(elevated, topic)
        found = False
        for service in services:
            if utils.service_is_up(service) and service['host'] == host:
                found = True
        if not found:
            msg = (_('No available service named %s') % host)
            LOG.error(msg)
            raise exception.InvalidHost(reason=msg)

        # Make sure the destination host is different than the current one
        if host == volume['host']:
            msg = _('Destination host must be different than current host')
            LOG.error(msg)
            raise exception.InvalidHost(reason=msg)

        self.update(context, volume, {'migration_status': 'starting'})

        # Call the scheduler to ensure that the host exists and that it can
        # accept the volume
        volume_type = {}
        volume_type_id = volume['volume_type_id']
        if volume_type_id:
            volume_type = volume_types.get_volume_type(context, volume_type_id)
        request_spec = {'volume_properties': volume,
                        'volume_type': volume_type,
                        'volume_id': volume['id']}
        self.scheduler_rpcapi.migrate_volume_to_host(context,
                                                     CONF.volume_topic,
                                                     volume['id'],
                                                     host,
                                                     force_host_copy,
                                                     request_spec)

    @wrap_check_policy
    def migrate_volume_completion(self, context, volume, new_volume, error):
        # This is a volume swap initiated by Nova, not Cinder. Nova expects
        # us to return the new_volume_id.
        if not (volume['migration_status'] or new_volume['migration_status']):
            return new_volume['id']

        if not volume['migration_status']:
            msg = _('Source volume not mid-migration.')
            raise exception.InvalidVolume(reason=msg)

        if not new_volume['migration_status']:
            msg = _('Destination volume not mid-migration.')
            raise exception.InvalidVolume(reason=msg)

        expected_status = 'target:%s' % volume['id']
        if not new_volume['migration_status'] == expected_status:
            msg = (_('Destination has migration_status %(stat)s, expected '
                     '%(exp)s.') % {'stat': new_volume['migration_status'],
                                    'exp': expected_status})
            raise exception.InvalidVolume(reason=msg)

        return self.volume_rpcapi.migrate_volume_completion(context, volume,
                                                            new_volume, error)

    @wrap_check_policy
    def update_readonly_flag(self, context, volume, flag):
        if volume['status'] != 'available':
            msg = _('Volume status must be available to update readonly flag.')
            raise exception.InvalidVolume(reason=msg)
        self.update_volume_admin_metadata(context.elevated(), volume,
                                          {'readonly': str(flag)})


class HostAPI(base.Base):
    def __init__(self):
        super(HostAPI, self).__init__()

    """Sub-set of the Volume Manager API for managing host operations."""
    def set_host_enabled(self, context, host, enabled):
        """Sets the specified host's ability to accept new volumes."""
        raise NotImplementedError()

    def get_host_uptime(self, context, host):
        """Returns the result of calling "uptime" on the target host."""
        raise NotImplementedError()

    def host_power_action(self, context, host, action):
        raise NotImplementedError()

    def set_host_maintenance(self, context, host, mode):
        """Start/Stop host maintenance window. On start, it triggers
        volume evacuation.
        """
        raise NotImplementedError()
