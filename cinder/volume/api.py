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
from oslo_utils import strutils
from oslo_utils import timeutils
from oslo_utils import uuidutils
import six

from cinder.api import common
from cinder import context
from cinder import db
from cinder.db import base
from cinder import exception
from cinder import flow_utils
from cinder.i18n import _, _LE, _LI, _LW
from cinder.image import cache as image_cache
from cinder.image import glance
from cinder import keymgr
from cinder import objects
from cinder.objects import base as objects_base
from cinder.objects import fields
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
        target.update(
            target_obj.obj_to_primitive()['versioned_object.data'] or {})
    else:
        target.update(target_obj or {})

    _action = 'volume:%s' % action
    cinder.policy.enforce(context, _action, target)


class API(base.Base):
    """API for interacting with the volume manager."""

    AVAILABLE_MIGRATION_STATUS = (None, 'deleting', 'error', 'success')

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
        return (volume['migration_status'] not in
                self.AVAILABLE_MIGRATION_STATUS)

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
        if size and (not strutils.is_int_like(size) or int(size) <= 0):
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
            'metadata': metadata or {},
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
    def delete(self, context, volume,
               force=False,
               unmanage_only=False,
               cascade=False):
        if context.is_admin and context.project_id != volume.project_id:
            project_id = volume.project_id
        else:
            project_id = context.project_id

        if not volume.host:
            volume_utils.notify_about_volume_usage(context,
                                                   volume, "delete.start")
            # NOTE(vish): scheduling failed, so delete it
            # Note(zhiteng): update volume quota reservation
            try:
                reserve_opts = {'volumes': -1, 'gigabytes': -volume.size}
                QUOTAS.add_volume_type_opts(context,
                                            reserve_opts,
                                            volume.volume_type_id)
                reservations = QUOTAS.reserve(context,
                                              project_id=project_id,
                                              **reserve_opts)
            except Exception:
                reservations = None
                LOG.exception(_LE("Failed to update quota while "
                                  "deleting volume."))
            volume.destroy()

            if reservations:
                QUOTAS.commit(context, reservations, project_id=project_id)

            volume_utils.notify_about_volume_usage(context,
                                                   volume, "delete.end")
            LOG.info(_LI("Delete volume request issued successfully."),
                     resource={'type': 'volume',
                               'id': volume.id})
            return

        # Build required conditions for conditional update
        expected = {'attach_status': db.Not('attached'),
                    'migration_status': self.AVAILABLE_MIGRATION_STATUS,
                    'consistencygroup_id': None}

        # If not force deleting we have status conditions
        if not force:
            expected['status'] = ('available', 'error', 'error_restoring',
                                  'error_extending')

        if cascade:
            # Allow deletion if all snapshots are in an expected state
            filters = [~db.volume_has_undeletable_snapshots_filter()]
        else:
            # Don't allow deletion of volume with snapshots
            filters = [~db.volume_has_snapshots_filter()]
        values = {'status': 'deleting', 'terminated_at': timeutils.utcnow()}

        result = volume.conditional_update(values, expected, filters)

        if not result:
            status = utils.build_or_str(expected.get('status'),
                                        _('status must be %s and'))
            msg = _('Volume %s must not be migrating, attached, belong to a '
                    'consistency group or have snapshots.') % status
            LOG.info(msg)
            raise exception.InvalidVolume(reason=msg)

        if cascade:
            values = {'status': 'deleting'}
            expected = {'status': ('available', 'error', 'deleting'),
                        'cgsnapshot_id': None}
            snapshots = objects.snapshot.SnapshotList.get_all_for_volume(
                context, volume.id)
            for s in snapshots:
                result = s.conditional_update(values, expected, filters)

                if not result:
                    volume.update({'status': 'error_deleting'})
                    volume.save()

                    msg = _('Failed to update snapshot.')
                    raise exception.InvalidVolume(reason=msg)

        cache = image_cache.ImageVolumeCache(self.db, self)
        entry = cache.get_by_image_volume(context, volume.id)
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
                LOG.warning(_LW("Unable to delete encryption key for "
                                "volume: %s."), e.msg, resource=volume)

        self.volume_rpcapi.delete_volume(context,
                                         volume,
                                         unmanage_only,
                                         cascade)
        LOG.info(_LI("Delete volume request issued successfully."),
                 resource=volume)

    @wrap_check_policy
    def update(self, context, volume, fields):
        if volume['status'] == 'maintenance':
            LOG.info(_LI("Unable to update volume, "
                         "because it is in maintenance."), resource=volume)
            msg = _("The volume cannot be updated during maintenance.")
            raise exception.InvalidVolume(reason=msg)

        # NOTE(thangp): Update is called by various APIs, some of which are
        # not yet using oslo_versionedobjects.  We need to handle the case
        # where volume is either a dict or an oslo_versionedobject.
        if isinstance(volume, objects_base.CinderObject):
            volume.update(fields)
            volume.save()
            LOG.info(_LI("Volume updated successfully."), resource=volume)
        else:
            vref = self.db.volume_update(context, volume['id'], fields)
            LOG.info(_LI("Volume updated successfully."), resource=vref)

    def get(self, context, volume_id, viewable_admin_meta=False):
        volume = objects.Volume.get_by_id(context, volume_id)

        if viewable_admin_meta:
            ctxt = context.elevated()
            admin_metadata = self.db.volume_admin_metadata_get(ctxt,
                                                               volume_id)
            volume.admin_metadata = admin_metadata
            volume.obj_reset_changes()

        try:
            check_policy(context, 'get', volume)
        except exception.PolicyNotAuthorized:
            # raise VolumeNotFound instead to make sure Cinder behaves
            # as it used to
            raise exception.VolumeNotFound(volume_id=volume_id)
        LOG.info(_LI("Volume info retrieved successfully."), resource=volume)
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
            volumes = objects.VolumeList.get_all(context, marker, limit,
                                                 sort_keys=sort_keys,
                                                 sort_dirs=sort_dirs,
                                                 filters=filters,
                                                 offset=offset)
        else:
            if viewable_admin_meta:
                context = context.elevated()
            volumes = objects.VolumeList.get_all_by_project(
                context, context.project_id, marker, limit,
                sort_keys=sort_keys, sort_dirs=sort_dirs, filters=filters,
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
        volume = objects.Volume.get_by_id(context, volume_id)
        LOG.info(_LI("Volume retrieved successfully."), resource=volume)
        return volume

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

        LOG.info(_LI("Get all snapshots completed successfully."))
        return snapshots

    @wrap_check_policy
    def reserve_volume(self, context, volume):
        expected = {'multiattach': volume.multiattach,
                    'status': (('available', 'in-use') if volume.multiattach
                               else 'available')}

        result = volume.conditional_update({'status': 'attaching'}, expected)

        if not result:
            expected_status = utils.build_or_str(expected['status'])
            msg = _('Volume status must be %s to reserve.') % expected_status
            LOG.error(msg)
            raise exception.InvalidVolume(reason=msg)

        LOG.info(_LI("Reserve volume completed successfully."),
                 resource=volume)

    @wrap_check_policy
    def unreserve_volume(self, context, volume):
        expected = {'status': 'attaching'}
        # Status change depends on whether it has attachments (in-use) or not
        # (available)
        value = {'status': db.Case([(db.volume_has_attachments_filter(),
                                     'in-use')],
                                   else_='available')}
        volume.conditional_update(value, expected)
        LOG.info(_LI("Unreserve volume completed successfully."),
                 resource=volume)

    @wrap_check_policy
    def begin_detaching(self, context, volume):
        # If we are in the middle of a volume migration, we don't want the
        # user to see that the volume is 'detaching'. Having
        # 'migration_status' set will have the same effect internally.
        expected = {'status': 'in-use',
                    'attach_status': 'attached',
                    'migration_status': self.AVAILABLE_MIGRATION_STATUS}

        result = volume.conditional_update({'status': 'detaching'}, expected)

        if not (result or self._is_volume_migrating(volume)):
            msg = _("Unable to detach volume. Volume status must be 'in-use' "
                    "and attach_status must be 'attached' to detach.")
            LOG.error(msg)
            raise exception.InvalidVolume(reason=msg)

        LOG.info(_LI("Begin detaching volume completed successfully."),
                 resource=volume)

    @wrap_check_policy
    def roll_detaching(self, context, volume):
        volume.conditional_update({'status': 'in-use'},
                                  {'status': 'detaching'})
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

        # We add readonly metadata if it doesn't already exist
        readonly = self.update_volume_admin_metadata(context.elevated(),
                                                     volume,
                                                     {'readonly': 'False'},
                                                     update=False)['readonly']
        if readonly == 'True' and mode != 'ro':
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
                              cgsnapshot_id,
                              commit_quota=True):
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

        if commit_quota:
            try:
                if CONF.no_snapshot_gb_quota:
                    reserve_opts = {'snapshots': 1}
                else:
                    reserve_opts = {'snapshots': 1,
                                    'gigabytes': volume['size']}
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
                        msg = _LW("Quota exceeded for %(s_pid)s, tried to "
                                  "create %(s_size)sG snapshot (%(d_consumed)d"
                                  "G of %(d_quota)dG already consumed).")
                        LOG.warning(msg, {'s_pid': context.project_id,
                                          's_size': volume['size'],
                                          'd_consumed': _consumed(over),
                                          'd_quota': quotas[over]})
                        raise exception.VolumeSizeExceedsAvailableQuota(
                            requested=volume['size'],
                            consumed=_consumed('gigabytes'),
                            quota=quotas['gigabytes'])
                    elif 'snapshots' in over:
                        msg = _LW("Quota exceeded for %(s_pid)s, tried to "
                                  "create snapshot (%(d_consumed)d snapshots "
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

            if commit_quota:
                QUOTAS.commit(context, reservations)
        except Exception:
            with excutils.save_and_reraise_exception():
                try:
                    if snapshot.obj_attr_is_set('id'):
                        snapshot.destroy()
                finally:
                    if commit_quota:
                        QUOTAS.rollback(context, reservations)

        return snapshot

    def create_snapshots_in_db(self, context,
                               volume_list,
                               name, description,
                               force, cgsnapshot_id):
        snapshot_list = []
        for volume in volume_list:
            self._create_snapshot_in_db_validate(context, volume, force)
            if volume['status'] == 'error':
                msg = _("The snapshot cannot be created when the volume is "
                        "in error status.")
                LOG.error(msg)
                raise exception.InvalidVolume(reason=msg)

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
        # Build required conditions for conditional update
        expected = {'cgsnapshot_id': None}
        # If not force deleting we have status conditions
        if not force:
            expected['status'] = ('available', 'error')

        result = snapshot.conditional_update({'status': 'deleting'}, expected)
        if not result:
            status = utils.build_or_str(expected.get('status'),
                                        _('status must be %s and'))
            msg = (_('Snapshot %s must not be part of a consistency group.') %
                   status)
            LOG.error(msg)
            raise exception.InvalidSnapshot(reason=msg)

        # Make RPC call to the right host
        volume = objects.Volume.get_by_id(context, snapshot.volume_id)
        self.volume_rpcapi.delete_snapshot(context, snapshot, volume.host,
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
        self._check_metadata_properties(metadata)
        db_meta = self.db.volume_metadata_update(context, volume['id'],
                                                 metadata,
                                                 delete,
                                                 meta_type)

        # TODO(jdg): Implement an RPC call for drivers that may use this info

        LOG.info(_LI("Update volume metadata completed successfully."),
                 resource=volume)
        return db_meta

    @wrap_check_policy
    def get_volume_admin_metadata(self, context, volume):
        """Get all administration metadata associated with a volume."""
        rv = self.db.volume_admin_metadata_get(context, volume['id'])
        LOG.info(_LI("Get volume admin metadata completed successfully."),
                 resource=volume)
        return dict(rv)

    @wrap_check_policy
    def update_volume_admin_metadata(self, context, volume, metadata,
                                     delete=False, add=True, update=True):
        """Updates or creates volume administration metadata.

        If delete is True, metadata items that are not specified in the
        `metadata` argument will be deleted.

        """
        self._check_metadata_properties(metadata)
        db_meta = self.db.volume_admin_metadata_update(context, volume['id'],
                                                       metadata, delete, add,
                                                       update)

        # TODO(jdg): Implement an RPC call for drivers that may use this info

        LOG.info(_LI("Update volume admin metadata completed successfully."),
                 resource=volume)
        return db_meta

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
        LOG.info(_LI("Copy volume to image completed successfully."),
                 resource=volume)
        return response

    @wrap_check_policy
    def extend(self, context, volume, new_size):
        if volume.status != 'available':
            msg = _('Volume %(vol_id)s status must be available '
                    'to extend, but current status is: '
                    '%(vol_status)s.') % {'vol_id': volume.id,
                                          'vol_status': volume.status}
            raise exception.InvalidVolume(reason=msg)

        size_increase = (int(new_size)) - volume.size
        if size_increase <= 0:
            msg = (_("New size for extend must be greater "
                     "than current size. (current: %(size)s, "
                     "extended: %(new_size)s).") % {'new_size': new_size,
                                                    'size': volume.size})
            raise exception.InvalidInput(reason=msg)

        try:
            reserve_opts = {'gigabytes': size_increase}
            QUOTAS.add_volume_type_opts(context, reserve_opts,
                                        volume.volume_type_id)
            reservations = QUOTAS.reserve(context,
                                          project_id=volume.project_id,
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

        if volume.status not in ['available', 'in-use']:
            msg = _('Volume %(vol_id)s status must be available or in-use, '
                    'but current status is: '
                    '%(vol_status)s.') % {'vol_id': volume.id,
                                          'vol_status': volume.status}
            LOG.error(msg)
            raise exception.InvalidVolume(reason=msg)

        # Make sure volume is not part of a migration.
        if self._is_volume_migrating(volume):
            msg = _("Volume %s is already part of an active "
                    "migration.") % volume.id
            LOG.error(msg)
            raise exception.InvalidVolume(reason=msg)

        # We only handle volumes without snapshots for now
        snaps = objects.SnapshotList.get_all_for_volume(context, volume.id)
        if snaps:
            msg = _("Volume %s must not have snapshots.") % volume.id
            LOG.error(msg)
            raise exception.InvalidVolume(reason=msg)

        # We only handle non-replicated volumes for now
        if (volume.replication_status is not None and
                volume.replication_status != 'disabled'):
            msg = _("Volume %s must not be replicated.") % volume.id
            LOG.error(msg)
            raise exception.InvalidVolume(reason=msg)

        if volume.consistencygroup_id:
            msg = _("Volume %s must not be part of a consistency "
                    "group.") % volume.id
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
        if host == volume.host:
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
                   'previous_status': volume.status}
        if lock_volume and volume.status == 'available':
            updates['status'] = 'maintenance'
        self.update(context, volume, updates)

        # Call the scheduler to ensure that the host exists and that it can
        # accept the volume
        volume_type = {}
        if volume.volume_type_id:
            volume_type = volume_types.get_volume_type(context.elevated(),
                                                       volume.volume_type_id)
        request_spec = {'volume_properties': volume,
                        'volume_type': volume_type,
                        'volume_id': volume.id}
        self.scheduler_rpcapi.migrate_volume_to_host(context,
                                                     CONF.volume_topic,
                                                     volume.id,
                                                     host,
                                                     force_host_copy,
                                                     request_spec,
                                                     volume=volume)
        LOG.info(_LI("Migrate volume request issued successfully."),
                 resource=volume)

    @wrap_check_policy
    def migrate_volume_completion(self, context, volume, new_volume, error):
        # This is a volume swap initiated by Nova, not Cinder. Nova expects
        # us to return the new_volume_id.
        if not (volume.migration_status or new_volume.migration_status):
            # When we're not migrating and haven't hit any errors, we issue
            # volume attach and detach requests so the volumes don't end in
            # 'attaching' and 'detaching' state
            if not error:
                attachments = volume.volume_attachment
                for attachment in attachments:
                    self.detach(context, volume, attachment.id)

                    self.attach(context, new_volume,
                                attachment.instance_uuid,
                                attachment.attached_host,
                                attachment.mountpoint,
                                'rw')

            return new_volume.id

        if not volume.migration_status:
            msg = _('Source volume not mid-migration.')
            raise exception.InvalidVolume(reason=msg)

        if not new_volume.migration_status:
            msg = _('Destination volume not mid-migration.')
            raise exception.InvalidVolume(reason=msg)

        expected_status = 'target:%s' % volume.id
        if not new_volume.migration_status == expected_status:
            msg = (_('Destination has migration_status %(stat)s, expected '
                     '%(exp)s.') % {'stat': new_volume.migration_status,
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
        if volume.status not in ['available', 'in-use']:
            msg = _('Unable to update type due to incorrect status: '
                    '%(vol_status)s on volume: %(vol_id)s. Volume status '
                    'must be available or '
                    'in-use.') % {'vol_status': volume.status,
                                  'vol_id': volume.id}
            LOG.error(msg)
            raise exception.InvalidVolume(reason=msg)

        if self._is_volume_migrating(volume):
            msg = (_("Volume %s is already part of an active migration.")
                   % volume.id)
            LOG.error(msg)
            raise exception.InvalidVolume(reason=msg)

        if migration_policy and migration_policy not in ['on-demand', 'never']:
            msg = _('migration_policy must be \'on-demand\' or \'never\', '
                    'passed: %s') % new_type
            LOG.error(msg)
            raise exception.InvalidInput(reason=msg)

        if volume.consistencygroup_id:
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
        old_vol_type_id = volume.volume_type_id
        old_vol_type_qos_id = None

        # Error if the original and new type are the same
        if volume.volume_type_id == vol_type_id:
            msg = _('New volume_type same as original: %s.') % new_type
            LOG.error(msg)
            raise exception.InvalidInput(reason=msg)

        if volume.volume_type_id:
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
        if (volume.status != 'available' and
                old_vol_type_qos_id != vol_type_qos_id):
            for qos_id in [old_vol_type_qos_id, vol_type_qos_id]:
                if qos_id:
                    specs = qos_specs.get_qos_specs(context.elevated(), qos_id)
                    if specs['consumer'] != 'back-end':
                        msg = _('Retype cannot change front-end qos specs for '
                                'in-use volume: %s.') % volume.id
                        raise exception.InvalidInput(reason=msg)

        # We're checking here in so that we can report any quota issues as
        # early as possible, but won't commit until we change the type. We
        # pass the reservations onward in case we need to roll back.
        reservations = quota_utils.get_volume_type_reservation(
            context, volume, vol_type_id, reserve_vol_type_only=True)

        # Get old reservations
        try:
            reserve_opts = {'volumes': -1, 'gigabytes': -volume.size}
            QUOTAS.add_volume_type_opts(context,
                                        reserve_opts,
                                        old_vol_type_id)
            # NOTE(wanghao): We don't need to reserve volumes and gigabytes
            # quota for retyping operation since they didn't changed, just
            # reserve volume_type and type gigabytes is fine.
            reserve_opts.pop('volumes')
            reserve_opts.pop('gigabytes')
            old_reservations = QUOTAS.reserve(context,
                                              project_id=volume.project_id,
                                              **reserve_opts)
        except Exception:
            volume.status = volume.previous_status
            volume.save()
            msg = _("Failed to update quota usage while retyping volume.")
            LOG.exception(msg, resource=volume)
            raise exception.CinderException(msg)

        self.update(context, volume, {'status': 'retyping',
                                      'previous_status': volume.status})

        request_spec = {'volume_properties': volume,
                        'volume_id': volume.id,
                        'volume_type': vol_type,
                        'migration_policy': migration_policy,
                        'quota_reservations': reservations,
                        'old_reservations': old_reservations}

        self.scheduler_rpcapi.retype(context, CONF.volume_topic, volume.id,
                                     request_spec=request_spec,
                                     filter_properties={}, volume=volume)
        LOG.info(_LI("Retype volume request issued successfully."),
                 resource=volume)

    def manage_existing(self, context, host, ref, name=None, description=None,
                        volume_type=None, metadata=None,
                        availability_zone=None, bootable=False):
        if volume_type and 'extra_specs' not in volume_type:
            extra_specs = volume_types.get_volume_type_extra_specs(
                volume_type['id'])
            volume_type['extra_specs'] = extra_specs

        elevated = context.elevated()
        try:
            svc_host = volume_utils.extract_host(host, 'backend')
            service = objects.Service.get_by_args(
                elevated, svc_host, 'cinder-volume')
        except exception.ServiceNotFound:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Unable to find service: %(service)s for '
                              'given host: %(host)s.'),
                          {'service': CONF.volume_topic, 'host': host})

        if service.disabled:
            LOG.error(_LE('Unable to manage_existing volume on a disabled '
                          'service.'))
            raise exception.ServiceUnavailable()

        if availability_zone is None:
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
            # NOTE(jdg): We don't use this, we just make sure it's valid
            # and exists before sending off the call
            service = objects.Service.get_by_args(
                context.elevated(), host, 'cinder-volume')
        except exception.ServiceNotFound:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Unable to find service: %(service)s for '
                              'given host: %(host)s.'),
                          {'service': CONF.volume_topic, 'host': host})
        if service.disabled:
            LOG.error(_LE('Unable to manage_existing snapshot on a disabled '
                          'service.'))
            raise exception.ServiceUnavailable()

        snapshot_object = self.create_snapshot_in_db(context, volume, name,
                                                     description, False,
                                                     metadata, None,
                                                     commit_quota=False)
        self.volume_rpcapi.manage_existing_snapshot(context, snapshot_object,
                                                    ref, host)
        return snapshot_object

    # FIXME(jdg): Move these Cheesecake methods (freeze, thaw and failover)
    # to a services API because that's what they are
    def failover_host(self,
                      ctxt,
                      host,
                      secondary_id=None):

        ctxt = context.get_admin_context()
        svc_host = volume_utils.extract_host(host, 'backend')

        service = objects.Service.get_by_args(
            ctxt, svc_host, 'cinder-volume')
        expected = {'replication_status': [fields.ReplicationStatus.ENABLED,
                    fields.ReplicationStatus.FAILED_OVER]}
        result = service.conditional_update(
            {'replication_status': fields.ReplicationStatus.FAILING_OVER},
            expected)
        if not result:
            expected_status = utils.build_or_str(
                expected['replication_status'])
            msg = (_('Host replication_status must be %s to failover.')
                   % expected_status)
            LOG.error(msg)
            raise exception.InvalidInput(reason=msg)
        self.volume_rpcapi.failover_host(ctxt, host, secondary_id)

    def freeze_host(self, ctxt, host):

        ctxt = context.get_admin_context()
        svc_host = volume_utils.extract_host(host, 'backend')

        service = objects.Service.get_by_args(
            ctxt, svc_host, 'cinder-volume')
        expected = {'frozen': False}
        result = service.conditional_update(
            {'frozen': True}, expected)
        if not result:
            msg = _('Host is already Frozen.')
            LOG.error(msg)
            raise exception.InvalidInput(reason=msg)

        # Should we set service status to disabled to keep
        # scheduler calls from being sent? Just use existing
        # `cinder service-disable reason=freeze`
        self.volume_rpcapi.freeze_host(ctxt, host)

    def thaw_host(self, ctxt, host):

        ctxt = context.get_admin_context()
        svc_host = volume_utils.extract_host(host, 'backend')

        service = objects.Service.get_by_args(
            ctxt, svc_host, 'cinder-volume')
        expected = {'frozen': True}
        result = service.conditional_update(
            {'frozen': False}, expected)
        if not result:
            msg = _('Host is NOT Frozen.')
            LOG.error(msg)
            raise exception.InvalidInput(reason=msg)
        if not self.volume_rpcapi.thaw_host(ctxt, host):
            return "Backend reported error during thaw_host operation."

    def check_volume_filters(self, filters):
        '''Sets the user filter value to accepted format'''
        booleans = self.db.get_booleans_for_table('volume')

        # To translate any true/false equivalent to True/False
        # which is only acceptable format in database queries.
        accepted_true = ['True', 'true', 'TRUE']
        accepted_false = ['False', 'false', 'FALSE']
        for k, v in filters.items():
            try:
                if k in booleans:
                    if v in accepted_false:
                        filters[k] = False
                    elif v in accepted_true:
                        filters[k] = True
                    else:
                        filters[k] = bool(v)
                elif k == 'display_name':
                    # Use the raw value of display name as is for the filter
                    # without passing it through ast.literal_eval(). If the
                    # display name is a properly quoted string (e.g. '"foo"')
                    # then literal_eval() strips the quotes (i.e. 'foo'), so
                    # the filter becomes different from the user input.
                    continue
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
