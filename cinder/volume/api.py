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

"""Handles all requests relating to volumes."""

import ast
import collections
import datetime
import functools

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import timeutils
from oslo_utils import uuidutils
import six

from cinder.api import common
from cinder import context
from cinder.db import base
from cinder import exception
from cinder import flow_utils
from cinder.i18n import _, _LE, _LI, _LW
from cinder.image import cache as image_cache
from cinder.image import glance
from cinder import keymgr
from cinder import objects
from cinder.objects import base as objects_base
import cinder.policy
from cinder import quota
from cinder import quota_utils
from cinder.scheduler import rpcapi as scheduler_rpcapi
from cinder import utils
from cinder.volume.flows.api import create_volume
from cinder.volume.flows.api import manage_existing
from cinder.volume import qos_specs
from cinder.volume import rpcapi as volume_rpcapi
from cinder.volume import utils as volume_utils
from cinder.volume import volume_types


allow_force_upload_opt = cfg.BoolOpt('enable_force_upload',
                                     default=False,
                                     help='Enables the Force option on '
                                          'upload_to_image. This enables '
                                          'running upload_volume on in-use '
                                          'volumes for backends that '
                                          'support it.')
volume_host_opt = cfg.BoolOpt('snapshot_same_host',
                              default=True,
                              help='Create volume from snapshot at the host '
                                   'where snapshot resides')
volume_same_az_opt = cfg.BoolOpt('cloned_volume_same_az',
                                 default=True,
                                 help='Ensure that the new volumes are the '
                                      'same AZ as snapshot or source volume')
az_cache_time_opt = cfg.IntOpt('az_cache_duration',
                               default=3600,
                               help='Cache volume availability zones in '
                                    'memory for the provided duration in '
                                    'seconds')

CONF = cfg.CONF
CONF.register_opt(allow_force_upload_opt)
CONF.register_opt(volume_host_opt)
CONF.register_opt(volume_same_az_opt)
CONF.register_opt(az_cache_time_opt)

CONF.import_opt('glance_core_properties', 'cinder.image.glance')

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

    if isinstance(target_obj, objects_base.CinderObject):
        # Turn object into dict so target.update can work
        target.update(target_obj.obj_to_primitive() or {})
    else:
        target.update(target_obj or {})

    _action = 'volume:%s' % action
    cinder.policy.enforce(context, _action, target)


def valid_replication_volume(func):
    """Check that the volume is capable of replication.

    This decorator requires the first 3 args of the wrapped function
    to be (self, context, volume)
    """
    @functools.wraps(func)
    def wrapped(self, context, volume, *args, **kwargs):
        rep_capable = False
        if volume.get('volume_type_id', None):
            extra_specs = volume_types.get_volume_type_extra_specs(
                volume.get('volume_type_id'))
            rep_capable = extra_specs.get('replication_enabled',
                                          False) == "<is> True"
        if not rep_capable:
            msg = _("Volume is not a replication enabled volume, "
                    "replication operations can only be performed "
                    "on volumes that are of type replication_enabled.")
            raise exception.InvalidVolume(reason=msg)
        return func(self, context, volume, *args, **kwargs)
    return wrapped


class API(base.Base):
    """API for interacting with the volume manager."""

    def __init__(self, db_driver=None, image_service=None):
        self.image_service = (image_service or
                              glance.get_default_image_service())
        self.scheduler_rpcapi = scheduler_rpcapi.SchedulerAPI()
        self.volume_rpcapi = volume_rpcapi.VolumeAPI()
        self.availability_zones = []
        self.availability_zones_last_fetched = None
        self.key_manager = keymgr.API()
        super(API, self).__init__(db_driver)

    def list_availability_zones(self, enable_cache=False):
        """Describe the known availability zones

        :retval tuple of dicts, each with a 'name' and 'available' key
        """
        refresh_cache = False
        if enable_cache:
            if self.availability_zones_last_fetched is None:
                refresh_cache = True
            else:
                cache_age = timeutils.delta_seconds(
                    self.availability_zones_last_fetched,
                    timeutils.utcnow())
                if cache_age >= CONF.az_cache_duration:
                    refresh_cache = True
        if refresh_cache or not enable_cache:
            topic = CONF.volume_topic
            ctxt = context.get_admin_context()
            services = objects.ServiceList.get_all_by_topic(ctxt, topic)
            az_data = [(s.availability_zone, s.disabled)
                       for s in services]
            disabled_map = {}
            for (az_name, disabled) in az_data:
                tracked_disabled = disabled_map.get(az_name, True)
                disabled_map[az_name] = tracked_disabled and disabled
            azs = [{'name': name, 'available': not disabled}
                   for (name, disabled) in disabled_map.items()]
            if refresh_cache:
                now = timeutils.utcnow()
                self.availability_zones = azs
                self.availability_zones_last_fetched = now
                LOG.debug("Availability zone cache updated, next update will"
                          " occur around %s.", now + datetime.timedelta(
                              seconds=CONF.az_cache_duration))
        else:
            azs = self.availability_zones
        LOG.info(_LI("Availability Zones retrieved successfully."))
        return tuple(azs)

    def _retype_is_possible(self, context,
                            first_type_id, second_type_id,
                            first_type=None, second_type=None):
        safe = False
        elevated = context.elevated()
        services = objects.ServiceList.get_all_by_topic(elevated,
                                                        'cinder-volume',
                                                        disabled=True)
        if len(services.objects) == 1:
            safe = True
        else:
            type_a = first_type or volume_types.get_volume_type(
                elevated,
                first_type_id)
            type_b = second_type or volume_types.get_volume_type(
                elevated,
                second_type_id)
            if (volume_utils.matching_backend_name(type_a['extra_specs'],
                                                   type_b['extra_specs'])):
                safe = True
        return safe

    def _is_volume_migrating(self, volume):
        # The migration status 'none' means no migration has ever been done
        # before. The migration status 'error' means the previous migration
        # failed. The migration status 'success' means the previous migration
        # succeeded. The migration status 'deleting' means the source volume
        # fails to delete after a migration.
        # All of the statuses above means the volume is not in the process
        # of a migration.
        return volume['migration_status'] not in (None, 'deleting',
                                                  'error', 'success')

    def create(self, context, size, name, description, snapshot=None,
               image_id=None, volume_type=None, metadata=None,
               availability_zone=None, source_volume=None,
               scheduler_hints=None,
               source_replica=None, consistencygroup=None,
               cgsnapshot=None, multiattach=False, source_cg=None):

        check_policy(context, 'create')

        # NOTE(jdg): we can have a create without size if we're
        # doing a create from snap or volume.  Currently
        # the taskflow api will handle this and pull in the
        # size from the source.

        # NOTE(jdg): cinderclient sends in a string representation
        # of the size value.  BUT there is a possibility that somebody
        # could call the API directly so the is_int_like check
        # handles both cases (string representation of true float or int).
        if size and (not utils.is_int_like(size) or int(size) <= 0):
            msg = _('Invalid volume size provided for create request: %s '
                    '(size argument must be an integer (or string '
                    'representation of an integer) and greater '
                    'than zero).') % size
            raise exception.InvalidInput(reason=msg)

        if consistencygroup and (not cgsnapshot and not source_cg):
            if not volume_type:
                msg = _("volume_type must be provided when creating "
                        "a volume in a consistency group.")
                raise exception.InvalidInput(reason=msg)
            cg_voltypeids = consistencygroup.get('volume_type_id')
            if volume_type.get('id') not in cg_voltypeids:
                msg = _("Invalid volume_type provided: %s (requested "
                        "type must be supported by this consistency "
                        "group).") % volume_type
                raise exception.InvalidInput(reason=msg)

        if volume_type and 'extra_specs' not in volume_type:
            extra_specs = volume_types.get_volume_type_extra_specs(
                volume_type['id'])
            volume_type['extra_specs'] = extra_specs

        if source_volume and volume_type:
            if volume_type['id'] != source_volume['volume_type_id']:
                if not self._retype_is_possible(
                        context,
                        volume_type['id'],
                        source_volume['volume_type_id'],
                        volume_type):
                    msg = _("Invalid volume_type provided: %s (requested type "
                            "is not compatible; either match source volume, "
                            "or omit type argument).") % volume_type['id']
                    raise exception.InvalidInput(reason=msg)

        # When cloning replica (for testing), volume type must be omitted
        if source_replica and volume_type:
            msg = _("No volume_type should be provided when creating test "
                    "replica.")
            raise exception.InvalidInput(reason=msg)

        if snapshot and volume_type:
            if volume_type['id'] != snapshot.volume_type_id:
                if not self._retype_is_possible(context,
                                                volume_type['id'],
                                                snapshot.volume_type_id,
                                                volume_type):
                    msg = _("Invalid volume_type provided: %s (requested "
                            "type is not compatible; recommend omitting "
                            "the type argument).") % volume_type['id']
                    raise exception.InvalidInput(reason=msg)

        # Determine the valid availability zones that the volume could be
        # created in (a task in the flow will/can use this information to
        # ensure that the availability zone requested is valid).
        raw_zones = self.list_availability_zones(enable_cache=True)
        availability_zones = set([az['name'] for az in raw_zones])
        if CONF.storage_availability_zone:
            availability_zones.add(CONF.storage_availability_zone)

        create_what = {
            'context': context,
            'raw_size': size,
            'name': name,
            'description': description,
            'snapshot': snapshot,
            'image_id': image_id,
            'raw_volume_type': volume_type,
            'metadata': metadata,
            'raw_availability_zone': availability_zone,
            'source_volume': source_volume,
            'scheduler_hints': scheduler_hints,
            'key_manager': self.key_manager,
            'source_replica': source_replica,
            'optional_args': {'is_quota_committed': False},
            'consistencygroup': consistencygroup,
            'cgsnapshot': cgsnapshot,
            'multiattach': multiattach,
        }
        try:
            sched_rpcapi = (self.scheduler_rpcapi if (not cgsnapshot and
                            not source_cg) else None)
            volume_rpcapi = (self.volume_rpcapi if (not cgsnapshot and
                             not source_cg) else None)
            flow_engine = create_volume.get_flow(self.db,
                                                 self.image_service,
                                                 availability_zones,
                                                 create_what,
                                                 sched_rpcapi,
                                                 volume_rpcapi)
        except Exception:
            msg = _('Failed to create api volume flow.')
            LOG.exception(msg)
            raise exception.CinderException(msg)

        # Attaching this listener will capture all of the notifications that
        # taskflow sends out and redirect them to a more useful log for
        # cinders debugging (or error reporting) usage.
        with flow_utils.DynamicLogListener(flow_engine, logger=LOG):
            flow_engine.run()
            vref = flow_engine.storage.fetch('volume')
            LOG.info(_LI("Volume created successfully."), resource=vref)
            return vref

    @wrap_check_policy
    def delete(self, context, volume, force=False, unmanage_only=False):
        if context.is_admin and context.project_id != volume['project_id']:
            project_id = volume['project_id']
        else:
            project_id = context.project_id

        volume_id = volume['id']
        if not volume['host']:
            volume_utils.notify_about_volume_usage(context,
                                                   volume, "delete.start")
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
                LOG.exception(_LE("Failed to update quota while "
                                  "deleting volume."))
            self.db.volume_destroy(context.elevated(), volume_id)

            if reservations:
                QUOTAS.commit(context, reservations, project_id=project_id)

            volume_utils.notify_about_volume_usage(context,
                                                   volume, "delete.end")
            LOG.info(_LI("Delete volume request issued successfully."),
                     resource={'type': 'volume',
                               'id': volume_id})
            return
        if volume['attach_status'] == "attached":
            # Volume is still attached, need to detach first
            LOG.info(_LI('Unable to delete volume: %s, '
                         'volume is attached.'), volume['id'])
            raise exception.VolumeAttached(volume_id=volume_id)

        if not force and volume['status'] not in ["available", "error",
                                                  "error_restoring",
                                                  "error_extending"]:
            msg = _("Volume status must be available or error, "
                    "but current status is: %s.") % volume['status']
            LOG.info(_LI('Unable to delete volume: %(vol_id)s, '
                         'volume must be available or '
                         'error, but is %(vol_status)s.'),
                     {'vol_id': volume['id'],
                      'vol_status': volume['status']})
            raise exception.InvalidVolume(reason=msg)

        if self._is_volume_migrating(volume):
            # Volume is migrating, wait until done
            LOG.info(_LI('Unable to delete volume: %s, '
                         'volume is currently migrating.'), volume['id'])
            msg = _("Volume cannot be deleted while migrating")
            raise exception.InvalidVolume(reason=msg)

        if volume['consistencygroup_id'] is not None:
            msg = _("Volume cannot be deleted while in a consistency group.")
            LOG.info(_LI('Unable to delete volume: %s, '
                         'volume is currently part of a '
                         'consistency group.'), volume['id'])
            raise exception.InvalidVolume(reason=msg)

        snapshots = objects.SnapshotList.get_all_for_volume(context,
                                                            volume_id)
        if len(snapshots):
            LOG.info(_LI('Unable to delete volume: %s, '
                         'volume currently has snapshots.'), volume['id'])
            msg = _("Volume still has %d dependent "
                    "snapshots.") % len(snapshots)
            raise exception.InvalidVolume(reason=msg)

        cache = image_cache.ImageVolumeCache(self.db, self)
        entry = cache.get_by_image_volume(context, volume_id)
        if entry:
            cache.evict(context, entry)

        # If the volume is encrypted, delete its encryption key from the key
        # manager. This operation makes volume deletion an irreversible process
        # because the volume cannot be decrypted without its key.
        encryption_key_id = volume.get('encryption_key_id', None)
        if encryption_key_id is not None:
            try:
                self.key_manager.delete_key(context, encryption_key_id)
            except Exception as e:
                msg = _("Unable to delete encrypted volume: %s.") % e.msg
                raise exception.InvalidVolume(reason=msg)

        now = timeutils.utcnow()
        vref = self.db.volume_update(context,
                                     volume_id,
                                     {'status': 'deleting',
                                      'terminated_at': now})

        self.volume_rpcapi.delete_volume(context, volume, unmanage_only)
        LOG.info(_LI("Delete volume request issued successfully."),
                 resource=vref)

    @wrap_check_policy
    def update(self, context, volume, fields):
        if volume['status'] == 'maintenance':
            LOG.info(_LI("Unable to update volume, "
                         "because it is in maintenance."), resource=volume)
            msg = _("The volume cannot be updated during maintenance.")
            raise exception.InvalidVolume(reason=msg)

        vref = self.db.volume_update(context, volume['id'], fields)
        LOG.info(_LI("Volume updated successfully."), resource=vref)

    def get(self, context, volume_id, viewable_admin_meta=False):
        rv = self.db.volume_get(context, volume_id)

        volume = dict(rv)

        if viewable_admin_meta:
            ctxt = context.elevated()
            admin_metadata = self.db.volume_admin_metadata_get(ctxt,
                                                               volume_id)
            volume['volume_admin_metadata'] = admin_metadata

        try:
            check_policy(context, 'get', volume)
        except exception.PolicyNotAuthorized:
            # raise VolumeNotFound instead to make sure Cinder behaves
            # as it used to
            raise exception.VolumeNotFound(volume_id=volume_id)
        LOG.info(_LI("Volume info retrieved successfully."), resource=rv)
        return volume

    def get_all(self, context, marker=None, limit=None, sort_keys=None,
                sort_dirs=None, filters=None, viewable_admin_meta=False,
                offset=None):
        check_policy(context, 'get_all')

        if filters is None:
            filters = {}

        allTenants = utils.get_bool_param('all_tenants', filters)

        try:
            if limit is not None:
                limit = int(limit)
                if limit < 0:
                    msg = _('limit param must be positive')
                    raise exception.InvalidInput(reason=msg)
        except ValueError:
            msg = _('limit param must be an integer')
            raise exception.InvalidInput(reason=msg)

        # Non-admin shouldn't see temporary target of a volume migration, add
        # unique filter data to reflect that only volumes with a NULL
        # 'migration_status' or a 'migration_status' that does not start with
        # 'target:' should be returned (processed in db/sqlalchemy/api.py)
        if not context.is_admin:
            filters['no_migration_targets'] = True

        if filters:
            LOG.debug("Searching by: %s.", six.text_type(filters))

        if context.is_admin and allTenants:
            # Need to remove all_tenants to pass the filtering below.
            del filters['all_tenants']
            volumes = self.db.volume_get_all(context, marker, limit,
                                             sort_keys=sort_keys,
                                             sort_dirs=sort_dirs,
                                             filters=filters,
                                             offset=offset)
        else:
            if viewable_admin_meta:
                context = context.elevated()
            volumes = self.db.volume_get_all_by_project(context,
                                                        context.project_id,
                                                        marker, limit,
                                                        sort_keys=sort_keys,
                                                        sort_dirs=sort_dirs,
                                                        filters=filters,
                                                        offset=offset)

        LOG.info(_LI("Get all volumes completed successfully."))
        return volumes

    def get_snapshot(self, context, snapshot_id):
        snapshot = objects.Snapshot.get_by_id(context, snapshot_id)

        # FIXME(jdg): The objects don't have the db name entries
        # so build the resource tag manually for now.
        LOG.info(_LI("Snapshot retrieved successfully."),
                 resource={'type': 'snapshot',
                           'id': snapshot.id})
        return snapshot

    def get_volume(self, context, volume_id):
        check_policy(context, 'get_volume')
        vref = self.db.volume_get(context, volume_id)
        LOG.info(_LI("Volume retrieved successfully."), resource=vref)
        return dict(vref)

    def get_all_snapshots(self, context, search_opts=None, marker=None,
                          limit=None, sort_keys=None, sort_dirs=None,
                          offset=None):
        check_policy(context, 'get_all_snapshots')

        search_opts = search_opts or {}

        if context.is_admin and 'all_tenants' in search_opts:
            # Need to remove all_tenants to pass the filtering below.
            del search_opts['all_tenants']
            snapshots = objects.SnapshotList.get_all(
                context, search_opts, marker, limit, sort_keys, sort_dirs,
                offset)
        else:
            snapshots = objects.SnapshotList.get_all_by_project(
                context, context.project_id, search_opts, marker, limit,
                sort_keys, sort_dirs, offset)

        LOG.info(_LI("Get all snaphsots completed successfully."))
        return snapshots

    @wrap_check_policy
    def reserve_volume(self, context, volume):
        # NOTE(jdg): check for Race condition bug 1096983
        # explicitly get updated ref and check
        volume = self.db.volume_get(context, volume['id'])
        if volume['status'] == 'available':
            self.update(context, volume, {"status": "attaching"})
        elif volume['status'] == 'in-use':
            if volume['multiattach']:
                self.update(context, volume, {"status": "attaching"})
            else:
                msg = _("Volume must be multiattachable to reserve again.")
                LOG.error(msg)
                raise exception.InvalidVolume(reason=msg)
        else:
            msg = _("Volume status must be available to reserve.")
            LOG.error(msg)
            raise exception.InvalidVolume(reason=msg)
        LOG.info(_LI("Reserve volume completed successfully."),
                 resource=volume)

    @wrap_check_policy
    def unreserve_volume(self, context, volume):
        volume = self.db.volume_get(context, volume['id'])
        if volume['status'] == 'attaching':
            attaches = self.db.volume_attachment_get_used_by_volume_id(
                context, volume['id'])
            if attaches:
                self.update(context, volume, {"status": "in-use"})
            else:
                self.update(context, volume, {"status": "available"})
        LOG.info(_LI("Unreserve volume completed successfully."),
                 resource=volume)

    @wrap_check_policy
    def begin_detaching(self, context, volume):
        # NOTE(vbala): The volume status might be 'detaching' already due to
        # a previous begin_detaching call. Get updated volume status so that
        # we fail such cases.
        volume = self.db.volume_get(context, volume['id'])
        # If we are in the middle of a volume migration, we don't want the user
        # to see that the volume is 'detaching'. Having 'migration_status' set
        # will have the same effect internally.
        if self._is_volume_migrating(volume):
            return

        if (volume['status'] != 'in-use' or
                volume['attach_status'] != 'attached'):
            msg = (_("Unable to detach volume. Volume status must be 'in-use' "
                     "and attach_status must be 'attached' to detach. "
                     "Currently: status: '%(status)s', "
                     "attach_status: '%(attach_status)s.'") %
                   {'status': volume['status'],
                    'attach_status': volume['attach_status']})
            LOG.error(msg)
            raise exception.InvalidVolume(reason=msg)
        self.update(context, volume, {"status": "detaching"})
        LOG.info(_LI("Begin detaching volume completed successfully."),
                 resource=volume)

    @wrap_check_policy
    def roll_detaching(self, context, volume):
        if volume['status'] == "detaching":
            self.update(context, volume, {"status": "in-use"})
        LOG.info(_LI("Roll detaching of volume completed successfully."),
                 resource=volume)

    @wrap_check_policy
    def attach(self, context, volume, instance_uuid, host_name,
               mountpoint, mode):
        if volume['status'] == 'maintenance':
            LOG.info(_LI('Unable to attach volume, '
                         'because it is in maintenance.'), resource=volume)
            msg = _("The volume cannot be attached in maintenance mode.")
            raise exception.InvalidVolume(reason=msg)
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

        attach_results = self.volume_rpcapi.attach_volume(context,
                                                          volume,
                                                          instance_uuid,
                                                          host_name,
                                                          mountpoint,
                                                          mode)
        LOG.info(_LI("Attach volume completed successfully."),
                 resource=volume)
        return attach_results

    @wrap_check_policy
    def detach(self, context, volume, attachment_id):
        if volume['status'] == 'maintenance':
            LOG.info(_LI('Unable to detach volume, '
                         'because it is in maintenance.'), resource=volume)
            msg = _("The volume cannot be detached in maintenance mode.")
            raise exception.InvalidVolume(reason=msg)
        detach_results = self.volume_rpcapi.detach_volume(context, volume,
                                                          attachment_id)
        LOG.info(_LI("Detach volume completed successfully."),
                 resource=volume)
        return detach_results

    @wrap_check_policy
    def initialize_connection(self, context, volume, connector):
        if volume['status'] == 'maintenance':
            LOG.info(_LI('Unable to initialize the connection for '
                         'volume, because it is in '
                         'maintenance.'), resource=volume)
            msg = _("The volume connection cannot be initialized in "
                    "maintenance mode.")
            raise exception.InvalidVolume(reason=msg)
        init_results = self.volume_rpcapi.initialize_connection(context,
                                                                volume,
                                                                connector)
        LOG.info(_LI("Initialize volume connection completed successfully."),
                 resource=volume)
        return init_results

    @wrap_check_policy
    def terminate_connection(self, context, volume, connector, force=False):
        self.volume_rpcapi.terminate_connection(context,
                                                volume,
                                                connector,
                                                force)
        LOG.info(_LI("Terminate volume connection completed successfully."),
                 resource=volume)
        self.unreserve_volume(context, volume)

    @wrap_check_policy
    def accept_transfer(self, context, volume, new_user, new_project):
        if volume['status'] == 'maintenance':
            LOG.info(_LI('Unable to accept transfer for volume, '
                         'because it is in maintenance.'), resource=volume)
            msg = _("The volume cannot accept transfer in maintenance mode.")
            raise exception.InvalidVolume(reason=msg)
        results = self.volume_rpcapi.accept_transfer(context,
                                                     volume,
                                                     new_user,
                                                     new_project)
        LOG.info(_LI("Transfer volume completed successfully."),
                 resource=volume)
        return results

    def _create_snapshot(self, context,
                         volume, name, description,
                         force=False, metadata=None,
                         cgsnapshot_id=None):
        snapshot = self.create_snapshot_in_db(
            context, volume, name,
            description, force, metadata, cgsnapshot_id)
        self.volume_rpcapi.create_snapshot(context, volume, snapshot)

        return snapshot

    def create_snapshot_in_db(self, context,
                              volume, name, description,
                              force, metadata,
                              cgsnapshot_id):
        check_policy(context, 'create_snapshot', volume)

        if volume['status'] == 'maintenance':
            LOG.info(_LI('Unable to create the snapshot for volume, '
                         'because it is in maintenance.'), resource=volume)
            msg = _("The snapshot cannot be created when the volume is in "
                    "maintenance mode.")
            raise exception.InvalidVolume(reason=msg)
        if self._is_volume_migrating(volume):
            # Volume is migrating, wait until done
            msg = _("Snapshot cannot be created while volume is migrating.")
            raise exception.InvalidVolume(reason=msg)

        if volume['status'].startswith('replica_'):
            # Can't snapshot secondary replica
            msg = _("Snapshot of secondary replica is not allowed.")
            raise exception.InvalidVolume(reason=msg)

        if ((not force) and (volume['status'] != "available")):
            msg = _("Volume %(vol_id)s status must be available, "
                    "but current status is: "
                    "%(vol_status)s.") % {'vol_id': volume['id'],
                                          'vol_status': volume['status']}
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
                    msg = _LW("Quota exceeded for %(s_pid)s, tried to create "
                              "%(s_size)sG snapshot (%(d_consumed)dG of "
                              "%(d_quota)dG already consumed).")
                    LOG.warning(msg, {'s_pid': context.project_id,
                                      's_size': volume['size'],
                                      'd_consumed': _consumed(over),
                                      'd_quota': quotas[over]})
                    raise exception.VolumeSizeExceedsAvailableQuota(
                        requested=volume['size'],
                        consumed=_consumed('gigabytes'),
                        quota=quotas['gigabytes'])
                elif 'snapshots' in over:
                    msg = _LW("Quota exceeded for %(s_pid)s, tried to create "
                              "snapshot (%(d_consumed)d snapshots "
                              "already consumed).")

                    LOG.warning(msg, {'s_pid': context.project_id,
                                      'd_consumed': _consumed(over)})
                    raise exception.SnapshotLimitExceeded(
                        allowed=quotas[over])

        self._check_metadata_properties(metadata)

        snapshot = None
        try:
            kwargs = {
                'volume_id': volume['id'],
                'cgsnapshot_id': cgsnapshot_id,
                'user_id': context.user_id,
                'project_id': context.project_id,
                'status': 'creating',
                'progress': '0%',
                'volume_size': volume['size'],
                'display_name': name,
                'display_description': description,
                'volume_type_id': volume['volume_type_id'],
                'encryption_key_id': volume['encryption_key_id'],
                'metadata': metadata or {}
            }
            snapshot = objects.Snapshot(context=context, **kwargs)
            snapshot.create()

            QUOTAS.commit(context, reservations)
        except Exception:
            with excutils.save_and_reraise_exception():
                try:
                    if snapshot.obj_attr_is_set('id'):
                        snapshot.destroy()
                finally:
                    QUOTAS.rollback(context, reservations)

        return snapshot

    def create_snapshots_in_db(self, context,
                               volume_list,
                               name, description,
                               force, cgsnapshot_id):
        snapshot_list = []
        for volume in volume_list:
            self._create_snapshot_in_db_validate(context, volume, force)

        reservations = self._create_snapshots_in_db_reserve(
            context, volume_list)

        options_list = []
        for volume in volume_list:
            options = self._create_snapshot_in_db_options(
                context, volume, name, description, cgsnapshot_id)
            options_list.append(options)

        try:
            for options in options_list:
                snapshot = objects.Snapshot(context=context, **options)
                snapshot.create()
                snapshot_list.append(snapshot)

            QUOTAS.commit(context, reservations)
        except Exception:
            with excutils.save_and_reraise_exception():
                try:
                    for snap in snapshot_list:
                        snap.destroy()
                finally:
                    QUOTAS.rollback(context, reservations)

        return snapshot_list

    def _create_snapshot_in_db_validate(self, context, volume, force):
        check_policy(context, 'create_snapshot', volume)

        if volume['status'] == 'maintenance':
            LOG.info(_LI('Unable to create the snapshot for volume, '
                         'because it is in maintenance.'), resource=volume)
            msg = _("The snapshot cannot be created when the volume is in "
                    "maintenance mode.")
            raise exception.InvalidVolume(reason=msg)
        if self._is_volume_migrating(volume):
            # Volume is migrating, wait until done
            msg = _("Snapshot cannot be created while volume is migrating.")
            raise exception.InvalidVolume(reason=msg)

        if ((not force) and (volume['status'] != "available")):
            msg = _("Snapshot cannot be created because volume %(vol_id)s "
                    "is not available, current volume status: "
                    "%(vol_status)s.") % {'vol_id': volume['id'],
                                          'vol_status': volume['status']}
            raise exception.InvalidVolume(reason=msg)

    def _create_snapshots_in_db_reserve(self, context, volume_list):
        reserve_opts_list = []
        total_reserve_opts = {}
        try:
            for volume in volume_list:
                if CONF.no_snapshot_gb_quota:
                    reserve_opts = {'snapshots': 1}
                else:
                    reserve_opts = {'snapshots': 1,
                                    'gigabytes': volume['size']}
                QUOTAS.add_volume_type_opts(context,
                                            reserve_opts,
                                            volume.get('volume_type_id'))
                reserve_opts_list.append(reserve_opts)

            for reserve_opts in reserve_opts_list:
                for (key, value) in reserve_opts.items():
                    if key not in total_reserve_opts.keys():
                        total_reserve_opts[key] = value
                    else:
                        total_reserve_opts[key] = \
                            total_reserve_opts[key] + value
            reservations = QUOTAS.reserve(context, **total_reserve_opts)
        except exception.OverQuota as e:
            overs = e.kwargs['overs']
            usages = e.kwargs['usages']
            quotas = e.kwargs['quotas']
            volume_utils.process_reserve_over_quota(context, overs, usages,
                                                    quotas, volume['size'])

        return reservations

    def _create_snapshot_in_db_options(self, context, volume,
                                       name, description,
                                       cgsnapshot_id):
        options = {'volume_id': volume['id'],
                   'cgsnapshot_id': cgsnapshot_id,
                   'user_id': context.user_id,
                   'project_id': context.project_id,
                   'status': "creating",
                   'progress': '0%',
                   'volume_size': volume['size'],
                   'display_name': name,
                   'display_description': description,
                   'volume_type_id': volume['volume_type_id'],
                   'encryption_key_id': volume['encryption_key_id']}
        return options

    def create_snapshot(self, context,
                        volume, name, description,
                        metadata=None, cgsnapshot_id=None):
        result = self._create_snapshot(context, volume, name, description,
                                       False, metadata, cgsnapshot_id)
        LOG.info(_LI("Snapshot create request issued successfully."),
                 resource=result)
        return result

    def create_snapshot_force(self, context,
                              volume, name,
                              description, metadata=None):
        result = self._create_snapshot(context, volume, name, description,
                                       True, metadata)
        LOG.info(_LI("Snapshot force create request issued successfully."),
                 resource=result)
        return result

    @wrap_check_policy
    def delete_snapshot(self, context, snapshot, force=False,
                        unmanage_only=False):
        if not force and snapshot.status not in ["available", "error"]:
            LOG.error(_LE('Unable to delete snapshot: %(snap_id)s, '
                          'due to invalid status. '
                          'Status must be available or '
                          'error, not %(snap_status)s.'),
                      {'snap_id': snapshot.id,
                       'snap_status': snapshot.status})
            msg = _("Volume Snapshot status must be available or error.")
            raise exception.InvalidSnapshot(reason=msg)
        cgsnapshot_id = snapshot.cgsnapshot_id
        if cgsnapshot_id:
            msg = _('Unable to delete snapshot %s because it is part of a '
                    'consistency group.') % snapshot.id
            LOG.error(msg)
            raise exception.InvalidSnapshot(reason=msg)

        snapshot_obj = self.get_snapshot(context, snapshot.id)
        snapshot_obj.status = 'deleting'
        snapshot_obj.save()

        volume = self.db.volume_get(context, snapshot_obj.volume_id)
        self.volume_rpcapi.delete_snapshot(context, snapshot_obj,
                                           volume['host'],
                                           unmanage_only=unmanage_only)
        LOG.info(_LI("Snapshot delete request issued successfully."),
                 resource=snapshot)

    @wrap_check_policy
    def update_snapshot(self, context, snapshot, fields):
        snapshot.update(fields)
        snapshot.save()

    @wrap_check_policy
    def get_volume_metadata(self, context, volume):
        """Get all metadata associated with a volume."""
        rv = self.db.volume_metadata_get(context, volume['id'])
        LOG.info(_LI("Get volume metadata completed successfully."),
                 resource=volume)
        return dict(rv)

    @wrap_check_policy
    def delete_volume_metadata(self, context, volume,
                               key, meta_type=common.METADATA_TYPES.user):
        """Delete the given metadata item from a volume."""
        if volume['status'] == 'maintenance':
            LOG.info(_LI('Unable to delete the volume metadata, '
                         'because it is in maintenance.'), resource=volume)
            msg = _("The volume metadata cannot be deleted when the volume "
                    "is in maintenance mode.")
            raise exception.InvalidVolume(reason=msg)
        self.db.volume_metadata_delete(context, volume['id'], key, meta_type)
        LOG.info(_LI("Delete volume metadata completed successfully."),
                 resource=volume)

    def _check_metadata_properties(self, metadata=None):
        if not metadata:
            metadata = {}

        for k, v in metadata.items():
            if len(k) == 0:
                msg = _("Metadata property key blank.")
                LOG.warning(msg)
                raise exception.InvalidVolumeMetadata(reason=msg)
            if len(k) > 255:
                msg = _("Metadata property key greater than 255 characters.")
                LOG.warning(msg)
                raise exception.InvalidVolumeMetadataSize(reason=msg)
            if len(v) > 255:
                msg = _("Metadata property value greater than 255 characters.")
                LOG.warning(msg)
                raise exception.InvalidVolumeMetadataSize(reason=msg)

    @wrap_check_policy
    def update_volume_metadata(self, context, volume,
                               metadata, delete=False,
                               meta_type=common.METADATA_TYPES.user):
        """Updates or creates volume metadata.

        If delete is True, metadata items that are not specified in the
        `metadata` argument will be deleted.

        """
        if volume['status'] == 'maintenance':
            LOG.info(_LI('Unable to update the metadata for volume, '
                         'because it is in maintenance.'), resource=volume)
            msg = _("The volume metadata cannot be updated when the volume "
                    "is in maintenance mode.")
            raise exception.InvalidVolume(reason=msg)
        if delete:
            _metadata = metadata
        else:
            if meta_type == common.METADATA_TYPES.user:
                orig_meta = self.get_volume_metadata(context, volume)
            elif meta_type == common.METADATA_TYPES.image:
                try:
                    orig_meta = self.get_volume_image_metadata(context,
                                                               volume)
                except exception.GlanceMetadataNotFound:
                    orig_meta = {}
            else:
                raise exception.InvalidMetadataType(metadata_type=meta_type,
                                                    id=volume['id'])
            _metadata = orig_meta.copy()
            _metadata.update(metadata)

        self._check_metadata_properties(_metadata)
        db_meta = self.db.volume_metadata_update(context, volume['id'],
                                                 _metadata,
                                                 delete,
                                                 meta_type)

        # TODO(jdg): Implement an RPC call for drivers that may use this info

        LOG.info(_LI("Update volume metadata completed successfully."),
                 resource=volume)
        return db_meta

    def get_volume_metadata_value(self, volume, key):
        """Get value of particular metadata key."""
        metadata = volume.get('volume_metadata')
        if metadata:
            for i in volume['volume_metadata']:
                if i['key'] == key:
                    return i['value']
        LOG.info(_LI("Get volume metadata key completed successfully."),
                 resource=volume)
        return None

    @wrap_check_policy
    def get_volume_admin_metadata(self, context, volume):
        """Get all administration metadata associated with a volume."""
        rv = self.db.volume_admin_metadata_get(context, volume['id'])
        LOG.info(_LI("Get volume admin metadata completed successfully."),
                 resource=volume)
        return dict(rv)

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

        self._check_metadata_properties(_metadata)

        self.db.volume_admin_metadata_update(context, volume['id'],
                                             _metadata, delete)

        # TODO(jdg): Implement an RPC call for drivers that may use this info

        LOG.info(_LI("Update volume admin metadata completed successfully."),
                 resource=volume)
        return _metadata

    def get_snapshot_metadata(self, context, snapshot):
        """Get all metadata associated with a snapshot."""
        snapshot_obj = self.get_snapshot(context, snapshot.id)
        LOG.info(_LI("Get snapshot metadata completed successfully."),
                 resource=snapshot)
        return snapshot_obj.metadata

    def delete_snapshot_metadata(self, context, snapshot, key):
        """Delete the given metadata item from a snapshot."""
        snapshot_obj = self.get_snapshot(context, snapshot.id)
        snapshot_obj.delete_metadata_key(context, key)
        LOG.info(_LI("Delete snapshot metadata completed successfully."),
                 resource=snapshot)

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
            orig_meta = snapshot.metadata
            _metadata = orig_meta.copy()
            _metadata.update(metadata)

        self._check_metadata_properties(_metadata)

        snapshot.metadata = _metadata
        snapshot.save()

        # TODO(jdg): Implement an RPC call for drivers that may use this info

        LOG.info(_LI("Update snapshot metadata completed successfully."),
                 resource=snapshot)
        return snapshot.metadata

    def get_snapshot_metadata_value(self, snapshot, key):
        LOG.info(_LI("Get snapshot metadata value not implemented."),
                 resource=snapshot)
        # FIXME(jdg): Huh?  Pass?
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
        LOG.info(_LI("Get volume image-metadata completed successfully."),
                 resource=volume)
        return {meta_entry.key: meta_entry.value for meta_entry in db_data}

    def get_list_volumes_image_metadata(self, context, volume_id_list):
        db_data = self.db.volume_glance_metadata_list_get(context,
                                                          volume_id_list)
        results = collections.defaultdict(dict)
        for meta_entry in db_data:
            results[meta_entry['volume_id']].update({meta_entry['key']:
                                                     meta_entry['value']})
        return results

    def _check_volume_availability(self, volume, force):
        """Check if the volume can be used."""
        if volume['status'] not in ['available', 'in-use']:
            msg = _('Volume %(vol_id)s status must be '
                    'available or in-use, but current status is: '
                    '%(vol_status)s.') % {'vol_id': volume['id'],
                                          'vol_status': volume['status']}
            raise exception.InvalidVolume(reason=msg)
        if not force and 'in-use' == volume['status']:
            msg = _('Volume status is in-use.')
            raise exception.InvalidVolume(reason=msg)

    @wrap_check_policy
    def copy_volume_to_image(self, context, volume, metadata, force):
        """Create a new image from the specified volume."""

        if not CONF.enable_force_upload and force:
            LOG.info(_LI("Force upload to image is disabled, "
                         "Force option will be ignored."),
                     resource={'type': 'volume', 'id': volume['id']})
            force = False

        self._check_volume_availability(volume, force)
        glance_core_properties = CONF.glance_core_properties
        if glance_core_properties:
            try:
                volume_image_metadata = self.get_volume_image_metadata(context,
                                                                       volume)
                custom_property_set = (set(volume_image_metadata).difference
                                       (set(glance_core_properties)))
                if custom_property_set:
                    properties = {custom_property:
                                  volume_image_metadata[custom_property]
                                  for custom_property in custom_property_set}
                    metadata.update(dict(properties=properties))
            except exception.GlanceMetadataNotFound:
                # If volume is not created from image, No glance metadata
                # would be available for that volume in
                # volume glance metadata table

                pass

        recv_metadata = self.image_service.create(
            context, self.image_service._translate_to_glance(metadata))
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
        LOG.info(_LI("Copy image to volume completed successfully."),
                 resource=volume)
        return response

    @wrap_check_policy
    def extend(self, context, volume, new_size):
        if volume['status'] != 'available':
            msg = _('Volume %(vol_id)s status must be available '
                    'to extend, but current status is: '
                    '%(vol_status)s.') % {'vol_id': volume['id'],
                                          'vol_status': volume['status']}
            raise exception.InvalidVolume(reason=msg)

        size_increase = (int(new_size)) - volume['size']
        if size_increase <= 0:
            msg = (_("New size for extend must be greater "
                     "than current size. (current: %(size)s, "
                     "extended: %(new_size)s).") % {'new_size': new_size,
                                                    'size': volume['size']})
            raise exception.InvalidInput(reason=msg)

        try:
            reserve_opts = {'gigabytes': size_increase}
            QUOTAS.add_volume_type_opts(context, reserve_opts,
                                        volume.get('volume_type_id'))
            reservations = QUOTAS.reserve(context,
                                          project_id=volume['project_id'],
                                          **reserve_opts)
        except exception.OverQuota as exc:
            usages = exc.kwargs['usages']
            quotas = exc.kwargs['quotas']

            def _consumed(name):
                return (usages[name]['reserved'] + usages[name]['in_use'])

            msg = _LE("Quota exceeded for %(s_pid)s, tried to extend volume "
                      "by %(s_size)sG, (%(d_consumed)dG of %(d_quota)dG "
                      "already consumed).")
            LOG.error(msg, {'s_pid': context.project_id,
                            's_size': size_increase,
                            'd_consumed': _consumed('gigabytes'),
                            'd_quota': quotas['gigabytes']})
            raise exception.VolumeSizeExceedsAvailableQuota(
                requested=size_increase,
                consumed=_consumed('gigabytes'),
                quota=quotas['gigabytes'])

        self.update(context, volume, {'status': 'extending'})
        self.volume_rpcapi.extend_volume(context, volume, new_size,
                                         reservations)
        LOG.info(_LI("Extend volume request issued successfully."),
                 resource=volume)

    @wrap_check_policy
    def migrate_volume(self, context, volume, host, force_host_copy,
                       lock_volume):
        """Migrate the volume to the specified host."""

        if volume['status'] not in ['available', 'in-use']:
            msg = _('Volume %(vol_id)s status must be available or in-use, '
                    'but current status is: '
                    '%(vol_status)s.') % {'vol_id': volume['id'],
                                          'vol_status': volume['status']}
            LOG.error(msg)
            raise exception.InvalidVolume(reason=msg)

        # Make sure volume is not part of a migration.
        if self._is_volume_migrating(volume):
            msg = _("Volume %s is already part of an active "
                    "migration.") % volume['id']
            LOG.error(msg)
            raise exception.InvalidVolume(reason=msg)

        # We only handle volumes without snapshots for now
        snaps = objects.SnapshotList.get_all_for_volume(context, volume['id'])
        if snaps:
            msg = _("Volume %s must not have snapshots.") % volume['id']
            LOG.error(msg)
            raise exception.InvalidVolume(reason=msg)

        # We only handle non-replicated volumes for now
        rep_status = volume['replication_status']
        if rep_status is not None and rep_status != 'disabled':
            msg = _("Volume %s must not be replicated.") % volume['id']
            LOG.error(msg)
            raise exception.InvalidVolume(reason=msg)

        cg_id = volume.get('consistencygroup_id', None)
        if cg_id:
            msg = _("Volume %s must not be part of a consistency "
                    "group.") % volume['id']
            LOG.error(msg)
            raise exception.InvalidVolume(reason=msg)

        # Make sure the host is in the list of available hosts
        elevated = context.elevated()
        topic = CONF.volume_topic
        services = objects.ServiceList.get_all_by_topic(
            elevated, topic, disabled=False)
        found = False
        for service in services:
            svc_host = volume_utils.extract_host(host, 'backend')
            if utils.service_is_up(service) and service.host == svc_host:
                found = True
        if not found:
            msg = _('No available service named %s') % host
            LOG.error(msg)
            raise exception.InvalidHost(reason=msg)

        # Make sure the destination host is different than the current one
        if host == volume['host']:
            msg = _('Destination host must be different '
                    'than the current host.')
            LOG.error(msg)
            raise exception.InvalidHost(reason=msg)

        # When the migration of an available volume starts, both the status
        # and the migration status of the volume will be changed.
        # If the admin sets lock_volume flag to True, the volume
        # status is changed to 'maintenance', telling users
        # that this volume is in maintenance mode, and no action is allowed
        # on this volume, e.g. attach, detach, retype, migrate, etc.
        updates = {'migration_status': 'starting',
                   'previous_status': volume['status']}
        if lock_volume and volume['status'] == 'available':
            updates['status'] = 'maintenance'
        self.update(context, volume, updates)

        # Call the scheduler to ensure that the host exists and that it can
        # accept the volume
        volume_type = {}
        volume_type_id = volume['volume_type_id']
        if volume_type_id:
            volume_type = volume_types.get_volume_type(context.elevated(),
                                                       volume_type_id)
        request_spec = {'volume_properties': volume,
                        'volume_type': volume_type,
                        'volume_id': volume['id']}
        self.scheduler_rpcapi.migrate_volume_to_host(context,
                                                     CONF.volume_topic,
                                                     volume['id'],
                                                     host,
                                                     force_host_copy,
                                                     request_spec)
        LOG.info(_LI("Migrate volume request issued successfully."),
                 resource=volume)

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

        LOG.info(_LI("Migrate volume completion issued successfully."),
                 resource=volume)
        return self.volume_rpcapi.migrate_volume_completion(context, volume,
                                                            new_volume, error)

    @wrap_check_policy
    def update_readonly_flag(self, context, volume, flag):
        if volume['status'] != 'available':
            msg = _('Volume %(vol_id)s status must be available '
                    'to update readonly flag, but current status is: '
                    '%(vol_status)s.') % {'vol_id': volume['id'],
                                          'vol_status': volume['status']}
            raise exception.InvalidVolume(reason=msg)
        self.update_volume_admin_metadata(context.elevated(), volume,
                                          {'readonly': six.text_type(flag)})
        LOG.info(_LI("Update readonly setting on volume "
                     "completed successfully."),
                 resource=volume)

    @wrap_check_policy
    def retype(self, context, volume, new_type, migration_policy=None):
        """Attempt to modify the type associated with an existing volume."""
        if volume['status'] not in ['available', 'in-use']:
            msg = _('Unable to update type due to incorrect status: '
                    '%(vol_status)s on volume: %(vol_id)s. Volume status '
                    'must be available or '
                    'in-use.') % {'vol_status': volume['status'],
                                  'vol_id': volume['id']}
            LOG.error(msg)
            raise exception.InvalidVolume(reason=msg)

        if self._is_volume_migrating(volume):
            msg = (_("Volume %s is already part of an active migration.")
                   % volume['id'])
            LOG.error(msg)
            raise exception.InvalidVolume(reason=msg)

        if migration_policy and migration_policy not in ['on-demand', 'never']:
            msg = _('migration_policy must be \'on-demand\' or \'never\', '
                    'passed: %s') % new_type
            LOG.error(msg)
            raise exception.InvalidInput(reason=msg)

        cg_id = volume.get('consistencygroup_id', None)
        if cg_id:
            msg = _("Volume must not be part of a consistency group.")
            LOG.error(msg)
            raise exception.InvalidVolume(reason=msg)

        # Support specifying volume type by ID or name
        try:
            if uuidutils.is_uuid_like(new_type):
                vol_type = volume_types.get_volume_type(context.elevated(),
                                                        new_type)
            else:
                vol_type = volume_types.get_volume_type_by_name(
                    context.elevated(), new_type)
        except exception.InvalidVolumeType:
            msg = _('Invalid volume_type passed: %s.') % new_type
            LOG.error(msg)
            raise exception.InvalidInput(reason=msg)

        vol_type_id = vol_type['id']
        vol_type_qos_id = vol_type['qos_specs_id']

        old_vol_type = None
        old_vol_type_id = volume['volume_type_id']
        old_vol_type_qos_id = None

        # Error if the original and new type are the same
        if volume['volume_type_id'] == vol_type_id:
            msg = _('New volume_type same as original: %s.') % new_type
            LOG.error(msg)
            raise exception.InvalidInput(reason=msg)

        if volume['volume_type_id']:
            old_vol_type = volume_types.get_volume_type(
                context, old_vol_type_id)
            old_vol_type_qos_id = old_vol_type['qos_specs_id']

        # We don't support changing encryption requirements yet
        old_enc = volume_types.get_volume_type_encryption(context,
                                                          old_vol_type_id)
        new_enc = volume_types.get_volume_type_encryption(context,
                                                          vol_type_id)
        if old_enc != new_enc:
            msg = _('Retype cannot change encryption requirements.')
            raise exception.InvalidInput(reason=msg)

        # We don't support changing QoS at the front-end yet for in-use volumes
        # TODO(avishay): Call Nova to change QoS setting (libvirt has support
        # - virDomainSetBlockIoTune() - Nova does not have support yet).
        if (volume['status'] != 'available' and
                old_vol_type_qos_id != vol_type_qos_id):
            for qos_id in [old_vol_type_qos_id, vol_type_qos_id]:
                if qos_id:
                    specs = qos_specs.get_qos_specs(context.elevated(), qos_id)
                    if specs['consumer'] != 'back-end':
                        msg = _('Retype cannot change front-end qos specs for '
                                'in-use volume: %s.') % volume['id']
                        raise exception.InvalidInput(reason=msg)

        # We're checking here in so that we can report any quota issues as
        # early as possible, but won't commit until we change the type. We
        # pass the reservations onward in case we need to roll back.
        reservations = quota_utils.get_volume_type_reservation(context, volume,
                                                               vol_type_id)

        self.update(context, volume, {'status': 'retyping',
                                      'previous_status': volume['status']})

        request_spec = {'volume_properties': volume,
                        'volume_id': volume['id'],
                        'volume_type': vol_type,
                        'migration_policy': migration_policy,
                        'quota_reservations': reservations}

        self.scheduler_rpcapi.retype(context, CONF.volume_topic, volume['id'],
                                     request_spec=request_spec,
                                     filter_properties={})
        LOG.info(_LI("Retype volume request issued successfully."),
                 resource=volume)

    def manage_existing(self, context, host, ref, name=None, description=None,
                        volume_type=None, metadata=None,
                        availability_zone=None, bootable=False):
        if volume_type and 'extra_specs' not in volume_type:
            extra_specs = volume_types.get_volume_type_extra_specs(
                volume_type['id'])
            volume_type['extra_specs'] = extra_specs
        if availability_zone is None:
            elevated = context.elevated()
            try:
                svc_host = volume_utils.extract_host(host, 'backend')
                service = objects.Service.get_by_host_and_topic(
                    elevated, svc_host, CONF.volume_topic)
            except exception.ServiceNotFound:
                with excutils.save_and_reraise_exception():
                    LOG.error(_LE('Unable to find service: %(service)s for '
                                  'given host: %(host)s.'),
                              {'service': CONF.volume_topic, 'host': host})
            availability_zone = service.get('availability_zone')

        manage_what = {
            'context': context,
            'name': name,
            'description': description,
            'host': host,
            'ref': ref,
            'volume_type': volume_type,
            'metadata': metadata,
            'availability_zone': availability_zone,
            'bootable': bootable,
        }

        try:
            flow_engine = manage_existing.get_flow(self.scheduler_rpcapi,
                                                   self.db,
                                                   manage_what)
        except Exception:
            msg = _('Failed to manage api volume flow.')
            LOG.exception(msg)
            raise exception.CinderException(msg)

        # Attaching this listener will capture all of the notifications that
        # taskflow sends out and redirect them to a more useful log for
        # cinder's debugging (or error reporting) usage.
        with flow_utils.DynamicLogListener(flow_engine, logger=LOG):
            flow_engine.run()
            vol_ref = flow_engine.storage.fetch('volume')
            LOG.info(_LI("Manage volume request issued successfully."),
                     resource=vol_ref)
            return vol_ref

    def manage_existing_snapshot(self, context, ref, volume,
                                 name=None, description=None,
                                 metadata=None):
        host = volume_utils.extract_host(volume['host'])
        try:
            objects.Service.get_by_host_and_topic(context.elevated(), host,
                                                  CONF.volume_topic)
        except exception.ServiceNotFound:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Unable to find service: %(service)s for '
                              'given host: %(host)s.'),
                          {'service': CONF.volume_topic, 'host': host})

        snapshot_object = self.create_snapshot_in_db(context, volume, name,
                                                     description, False,
                                                     metadata, None)
        self.volume_rpcapi.manage_existing_snapshot(context, snapshot_object,
                                                    ref, host)
        return snapshot_object

    #  Replication V2 methods ##

    # NOTE(jdg): It might be kinda silly to propogate the named
    # args with defaults all the way down through rpc into manager
    # but for now the consistency is useful, and there may be
    # some usefulness in the future (direct calls in manager?)

    # NOTE(jdg): Relying solely on the volume-type quota mechanism
    # need to consider looking at how we handle configured backends
    # WRT quotas, do they count against normal quotas or not?  For
    # now they're a special resource, so no.

    @wrap_check_policy
    @valid_replication_volume
    def enable_replication(self, ctxt, volume):
        # NOTE(jdg): details like sync vs async
        # and replica count are to be set via the
        # volume-type and config files.

        # Get a fresh ref from db and check status
        volume = self.db.volume_get(ctxt, volume['id'])

        # NOTE(jdg): Set a valid status as a var to minimize errors via typos
        # also, use a list, we may want to add to it some day

        # TODO(jdg): Move these up to a global list for each call and ban the
        # free form typing of states and state checks going forward

        # NOTE(jdg): There may be a need for some backends to allow this
        # call to driver regardless of replication_status, most likely
        # this indicates an issue with the driver, but might be useful
        # cases to  consider modifying this for in the future.
        valid_rep_status = ['disabled']
        rep_status = volume.get('replication_status', valid_rep_status[0])

        if rep_status not in valid_rep_status:
            msg = (_("Invalid status to enable replication. "
                     "valid states are: %(valid_states)s, "
                     "current replication-state is: %(curr_state)s.") %
                   {'valid_states': valid_rep_status,
                    'curr_state': rep_status})

            raise exception.InvalidVolume(reason=msg)

        vref = self.db.volume_update(ctxt,
                                     volume['id'],
                                     {'replication_status': 'enabling'})
        self.volume_rpcapi.enable_replication(ctxt, vref)

    @wrap_check_policy
    @valid_replication_volume
    def disable_replication(self, ctxt, volume):

        valid_disable_status = ['disabled', 'enabled']

        # NOTE(jdg): Just use disabled here (item 1 in the list) this
        # way if someone says disable_rep on a volume that's not being
        # replicated we just say "ok, done"
        rep_status = volume.get('replication_status', valid_disable_status[0])

        if rep_status not in valid_disable_status:
            msg = (_("Invalid status to disable replication. "
                     "valid states are: %(valid_states)s, "
                     "current replication-state is: %(curr_state)s.") %
                   {'valid_states': valid_disable_status,
                    'curr_state': rep_status})

            raise exception.InvalidVolume(reason=msg)

        vref = self.db.volume_update(ctxt,
                                     volume['id'],
                                     {'replication_status': 'disabling'})

        self.volume_rpcapi.disable_replication(ctxt, vref)

    @wrap_check_policy
    @valid_replication_volume
    def failover_replication(self,
                             ctxt,
                             volume,
                             secondary=None):

        # FIXME(jdg):  What is the secondary argument?
        # for managed secondaries that's easy; it's a host
        # for others, it's tricky; will propose a format for
        # secondaries that includes an ID/Name that can be
        # used as a handle
        valid_failover_status = ['enabled']
        rep_status = volume.get('replication_status', 'na')

        if rep_status not in valid_failover_status:
            msg = (_("Invalid status to failover replication. "
                     "valid states are: %(valid_states)s, "
                     "current replication-state is: %(curr_state)s.") %
                   {'valid_states': valid_failover_status,
                    'curr_state': rep_status})

            raise exception.InvalidVolume(reason=msg)

        vref = self.db.volume_update(
            ctxt,
            volume['id'],
            {'replication_status': 'enabling_secondary'})

        self.volume_rpcapi.failover_replication(ctxt,
                                                vref,
                                                secondary)

    @wrap_check_policy
    @valid_replication_volume
    def list_replication_targets(self, ctxt, volume):

        # NOTE(jdg): This collects info for the specified volume
        # it is NOT an error if the volume is not being replicated
        # also, would be worth having something at a backend/host
        # level to show an admin how a backend is configured.
        return self.volume_rpcapi.list_replication_targets(ctxt, volume)

    def check_volume_filters(self, filters):
        booleans = self.db.get_booleans_for_table('volume')
        for k, v in filters.iteritems():
            try:
                if k in booleans:
                    filters[k] = bool(v)
                else:
                    filters[k] = ast.literal_eval(v)
            except (ValueError, SyntaxError):
                LOG.debug('Could not evaluate value %s, assuming string', v)


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
        """Start/Stop host maintenance window.

        On start, it triggers volume evacuation.
        """
        raise NotImplementedError()
