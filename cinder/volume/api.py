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
from typing import (Any, DefaultDict, Iterable, Optional, Union)

from castellan import key_manager
from oslo_config import cfg
from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils import excutils
from oslo_utils import strutils
from oslo_utils import timeutils
from oslo_utils import versionutils
import webob

from cinder.api import common
from cinder.common import constants
from cinder import compute
from cinder import context
from cinder import coordination
from cinder import db
from cinder.db import base
from cinder import exception
from cinder import flow_utils
from cinder.i18n import _
from cinder.image import cache as image_cache
from cinder.image import glance
from cinder.image import image_utils
from cinder.message import api as message_api
from cinder.message import message_field
from cinder import objects
from cinder.objects import base as objects_base
from cinder.objects import fields
from cinder.objects import volume_type
from cinder.policies import attachments as attachment_policy
from cinder.policies import services as svr_policy
from cinder.policies import snapshot_metadata as s_meta_policy
from cinder.policies import snapshots as snapshot_policy
from cinder.policies import volume_actions as vol_action_policy
from cinder.policies import volume_metadata as vol_meta_policy
from cinder.policies import volumes as vol_policy
from cinder import quota
from cinder import quota_utils
from cinder.scheduler import rpcapi as scheduler_rpcapi
from cinder import utils
from cinder.volume.flows.api import create_volume
from cinder.volume.flows.api import manage_existing
from cinder.volume import rpcapi as volume_rpcapi
from cinder.volume import volume_types
from cinder.volume import volume_utils

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
AO_LIST = objects.VolumeAttachmentList


class API(base.Base):
    """API for interacting with the volume manager."""

    AVAILABLE_MIGRATION_STATUS = (None, 'deleting', 'error', 'success')

    def __init__(self, image_service=None):
        self.image_service = (image_service or
                              glance.get_default_image_service())
        self.scheduler_rpcapi = scheduler_rpcapi.SchedulerAPI()
        self.volume_rpcapi = volume_rpcapi.VolumeAPI()
        self.availability_zones = []
        self.availability_zones_last_fetched = None
        self.key_manager = key_manager.API(CONF)
        self.message = message_api.API()
        super().__init__()

    def list_availability_zones(self,
                                enable_cache: bool = False,
                                refresh_cache: bool = False) -> tuple:
        """Describe the known availability zones

        :param enable_cache: Enable az cache
        :param refresh_cache: Refresh cache immediately
        :return: tuple of dicts, each with a 'name' and 'available' key
        """
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
            topic = constants.VOLUME_TOPIC
            ctxt = context.get_admin_context()
            services = objects.ServiceList.get_all_by_topic(ctxt, topic)
            az_data = [(s.availability_zone, s.disabled)
                       for s in services]
            disabled_map: dict[str, bool] = {}
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
        LOG.info("Availability Zones retrieved successfully.")
        return tuple(azs)

    def _retype_is_possible(self,
                            context: context.RequestContext,
                            source_type: objects.VolumeType,
                            target_type: objects.VolumeType) -> bool:
        elevated = context.elevated()
        # If encryptions are different, it is not allowed
        # to create volume from source volume or snapshot.
        if volume_types.volume_types_encryption_changed(
                elevated,
                source_type.id if source_type else None,
                target_type.id if target_type else None):
            return False
        services = objects.ServiceList.get_all_by_topic(
            elevated,
            constants.VOLUME_TOPIC,
            disabled=True)
        if len(services.objects) == 1:
            return True

        source_extra_specs = {}
        if source_type:
            with source_type.obj_as_admin():
                source_extra_specs = source_type.extra_specs
        target_extra_specs = {}
        if target_type:
            with target_type.obj_as_admin():
                target_extra_specs = target_type.extra_specs
        if (volume_utils.matching_backend_name(
                source_extra_specs, target_extra_specs)):
            return True
        return False

    def _is_volume_migrating(self, volume: objects.Volume) -> bool:
        # The migration status 'none' means no migration has ever been done
        # before. The migration status 'error' means the previous migration
        # failed. The migration status 'success' means the previous migration
        # succeeded. The migration status 'deleting' means the source volume
        # fails to delete after a migration.
        # All of the statuses above means the volume is not in the process
        # of a migration.
        return (volume['migration_status'] not in
                self.AVAILABLE_MIGRATION_STATUS)

    def _is_multiattach(self,
                        volume_type: objects.VolumeType) -> bool:
        # TODO: getattr not needed if using obj?
        specs = getattr(volume_type, 'extra_specs', {})
        return specs.get('multiattach', 'False') == '<is> True'

    def _is_encrypted(self,
                      volume_type: objects.volume_type.VolumeType) -> bool:
        specs = volume_type.get('extra_specs', {})
        if 'encryption' not in specs:
            return False
        return specs.get('encryption', {}) is not {}

    def create(self,
               context: context.RequestContext,
               size: Union[str, int],
               name: Optional[str],
               description: Optional[str],
               snapshot: Optional[objects.Snapshot] = None,
               image_id: Optional[str] = None,
               volume_type: Optional[objects.VolumeType] = None,
               metadata: Optional[dict] = None,
               availability_zone: Optional[str] = None,
               source_volume: Optional[objects.Volume] = None,
               scheduler_hints=None,
               source_replica=None,
               consistencygroup: Optional[objects.ConsistencyGroup] = None,
               cgsnapshot: Optional[objects.CGSnapshot] = None,
               source_cg=None,
               group: Optional[objects.Group] = None,
               group_snapshot=None,
               source_group=None,
               backup: Optional[objects.Backup] = None):

        if image_id:
            context.authorize(vol_policy.CREATE_FROM_IMAGE_POLICY)
        else:
            context.authorize(vol_policy.CREATE_POLICY)

        # Check up front for legacy replication parameters to quick fail
        if source_replica:
            msg = _("Creating a volume from a replica source was part of the "
                    "replication v1 implementation which is no longer "
                    "available.")
            raise exception.InvalidInput(reason=msg)

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

        # ensure we pass the volume_type provisioning filter on size
        volume_types.provision_filter_on_size(context, volume_type, size)

        if consistencygroup and (not cgsnapshot and not source_cg):
            if not volume_type:
                msg = _("volume_type must be provided when creating "
                        "a volume in a consistency group.")
                raise exception.InvalidInput(reason=msg)
            cg_voltypeids = consistencygroup.volume_type_id
            if volume_type.id not in cg_voltypeids:
                msg = _("Invalid volume_type provided: %s (requested "
                        "type must be supported by this consistency "
                        "group).") % volume_type
                raise exception.InvalidInput(reason=msg)

        if group and (not group_snapshot and not source_group):
            if not volume_type:
                msg = _("volume_type must be provided when creating "
                        "a volume in a group.")
                raise exception.InvalidInput(reason=msg)
            vol_type_ids = [v_type.id for v_type in group.volume_types]
            if volume_type.id not in vol_type_ids:
                msg = _("Invalid volume_type provided: %s (requested "
                        "type must be supported by this "
                        "group).") % volume_type
                raise exception.InvalidInput(reason=msg)

        if source_volume and volume_type:
            if volume_type.id != source_volume.volume_type_id:
                if not self._retype_is_possible(
                        context,
                        source_volume.volume_type,
                        volume_type):
                    msg = _("Invalid volume_type provided: %s (requested type "
                            "is not compatible; either match source volume, "
                            "or omit type argument).") % volume_type.id
                    raise exception.InvalidInput(reason=msg)

        if snapshot and volume_type:
            if volume_type.id != snapshot.volume_type_id:
                if not self._retype_is_possible(context,
                                                snapshot.volume.volume_type,
                                                volume_type):
                    msg = _("Invalid volume_type provided: %s (requested "
                            "type is not compatible; recommend omitting "
                            "the type argument).") % volume_type.id
                    raise exception.InvalidInput(reason=msg)

        # Determine the valid availability zones that the volume could be
        # created in (a task in the flow will/can use this information to
        # ensure that the availability zone requested is valid).
        raw_zones = self.list_availability_zones(enable_cache=True)
        availability_zones = set([az['name'] for az in raw_zones])
        if CONF.storage_availability_zone:
            availability_zones.add(CONF.storage_availability_zone)

        utils.check_metadata_properties(metadata)

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
            'optional_args': {'is_quota_committed': False},
            'consistencygroup': consistencygroup,
            'cgsnapshot': cgsnapshot,
            'group': group,
            'group_snapshot': group_snapshot,
            'source_group': source_group,
            'backup': backup,
        }
        try:
            sched_rpcapi = (self.scheduler_rpcapi if (
                            not cgsnapshot and not source_cg and
                            not group_snapshot and not source_group)
                            else None)
            volume_rpcapi = (self.volume_rpcapi if (
                             not cgsnapshot and not source_cg and
                             not group_snapshot and not source_group)
                             else None)
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
            try:
                flow_engine.run()
                vref = flow_engine.storage.fetch('volume')
                # NOTE(tommylikehu): If the target az is not hit,
                # refresh the az cache immediately.
                if flow_engine.storage.fetch('refresh_az'):
                    self.list_availability_zones(enable_cache=True,
                                                 refresh_cache=True)
                LOG.info("Create volume request issued successfully.",
                         resource=vref)
                return vref
            except exception.InvalidAvailabilityZone:
                with excutils.save_and_reraise_exception():
                    self.list_availability_zones(enable_cache=True,
                                                 refresh_cache=True)

    def revert_to_snapshot(self,
                           context: context.RequestContext,
                           volume: objects.Volume,
                           snapshot: objects.Snapshot) -> None:
        """revert a volume to a snapshot"""
        context.authorize(vol_action_policy.REVERT_POLICY,
                          target_obj=volume)
        v_res = volume.update_single_status_where(
            'reverting', 'available')
        if not v_res:
            msg = (_("Can't revert volume %(vol_id)s to its latest snapshot "
                     "%(snap_id)s. Volume's status must be 'available'.")
                   % {"vol_id": volume.id,
                      "snap_id": snapshot.id})
            raise exception.InvalidVolume(reason=msg)
        s_res = snapshot.update_single_status_where(
            fields.SnapshotStatus.RESTORING,
            fields.SnapshotStatus.AVAILABLE)
        if not s_res:
            msg = (_("Can't revert volume %(vol_id)s to its latest snapshot "
                     "%(snap_id)s. Snapshot's status must be 'available'.")
                   % {"vol_id": volume.id,
                      "snap_id": snapshot.id})
            raise exception.InvalidSnapshot(reason=msg)

        self.volume_rpcapi.revert_to_snapshot(context, volume, snapshot)

    def delete(self,
               context: context.RequestContext,
               volume: objects.Volume,
               force: bool = False,
               unmanage_only: bool = False,
               cascade: bool = False) -> None:
        context.authorize(vol_policy.DELETE_POLICY, target_obj=volume)
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
                reservations = None
                if volume.status != 'error_managing' and volume.use_quota:
                    LOG.debug("Decrease volume quotas for non temporary volume"
                              " in non error_managing status.")
                    reserve_opts = {'volumes': -1, 'gigabytes': -volume.size}
                    QUOTAS.add_volume_type_opts(context,
                                                reserve_opts,
                                                volume.volume_type_id)
                    reservations = QUOTAS.reserve(context,
                                                  project_id=project_id,
                                                  **reserve_opts)
            except Exception:
                LOG.exception("Failed to update quota while "
                              "deleting volume.")
            volume.destroy()

            if reservations:
                QUOTAS.commit(context, reservations, project_id=project_id)

            volume_utils.notify_about_volume_usage(context,
                                                   volume, "delete.end")
            LOG.info("Delete volume request issued successfully.",
                     resource={'type': 'volume',
                               'id': volume.id})
            utils.api_clean_volume_file_locks(volume.id)
            return

        if not unmanage_only:
            volume.assert_not_frozen()

        if unmanage_only and volume.encryption_key_id is not None:
            msg = _("Unmanaging encrypted volumes is not supported.")
            e = exception.Invalid(reason=msg)
            self.message.create(
                context,
                message_field.Action.UNMANAGE_VOLUME,
                resource_uuid=volume.id,
                detail=message_field.Detail.UNMANAGE_ENC_NOT_SUPPORTED,
                exception=e)
            raise e

        # Build required conditions for conditional update
        expected = {
            'attach_status': db.Not(fields.VolumeAttachStatus.ATTACHED),
            'migration_status': self.AVAILABLE_MIGRATION_STATUS,
            'consistencygroup_id': None,
            'group_id': None}

        # If not force deleting we have status conditions
        if not force:
            expected['status'] = ('available', 'error', 'error_restoring',
                                  'error_extending', 'error_managing')

        if cascade:
            if force:
                # Ignore status checks, but ensure snapshots are not part
                # of a cgsnapshot.
                filters = [~db.volume_has_snapshots_in_a_cgsnapshot_filter()]
            else:
                # Allow deletion if all snapshots are in an expected state
                filters = [~db.volume_has_undeletable_snapshots_filter()]
                # Check if the volume has snapshots which are existing in
                # other project now.
                if not context.is_admin:
                    filters.append(~db.volume_has_other_project_snp_filter())
        else:
            # Don't allow deletion of volume with snapshots
            filters = [~db.volume_has_snapshots_filter()]
        values = {'status': 'deleting', 'terminated_at': timeutils.utcnow()}
        if unmanage_only is True:
            values['status'] = 'unmanaging'
        if volume.status == 'error_managing':
            values['status'] = 'error_managing_deleting'

        result = volume.conditional_update(values, expected, filters)

        if not result:
            status = utils.build_or_str(expected.get('status'),
                                        _('status must be %s and'))
            msg = _('Volume %s must not be migrating, attached, belong to a '
                    'group, have snapshots, awaiting a transfer, '
                    'or be disassociated from '
                    'snapshots after volume transfer.') % status
            LOG.info(msg)
            raise exception.InvalidVolume(reason=msg)

        if cascade:
            values = {'status': 'deleting'}
            expected = {'cgsnapshot_id': None,
                        'group_snapshot_id': None}
            if not force:
                expected['status'] = ('available', 'error', 'deleting')

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
                volume_utils.delete_encryption_key(context,
                                                   self.key_manager,
                                                   encryption_key_id)
            except Exception as e:
                volume.update({'status': 'error_deleting'})
                volume.save()
                if hasattr(e, 'msg'):
                    # ignore type (Exception has no attr "msg") error
                    msg = _("Unable to delete encryption key for "
                            "volume: %s") % (e.msg)
                else:
                    msg = _("Unable to delete encryption key for volume.")
                LOG.error(msg)
                raise exception.InvalidVolume(reason=msg)

        self.volume_rpcapi.delete_volume(context,
                                         volume,
                                         unmanage_only,
                                         cascade)
        utils.api_clean_volume_file_locks(volume.id)
        LOG.info("Delete volume request issued successfully.",
                 resource=volume)

    def update(self,
               context: context.RequestContext,
               volume: objects.Volume,
               fields: dict) -> None:
        context.authorize(vol_policy.UPDATE_POLICY, target_obj=volume)
        # TODO(karthikp): Making sure volume is always oslo-versioned
        # If not we convert it at the start of update method. This check
        # needs to be removed once we have moved to ovo.
        if not isinstance(volume, objects_base.CinderObject):
            vol_obj = objects.Volume()
            volume = objects.Volume._from_db_object(context, vol_obj, volume)

        if volume.status == 'maintenance':
            LOG.info("Unable to update volume, "
                     "because it is in maintenance.", resource=volume)
            msg = _("The volume cannot be updated during maintenance.")
            raise exception.InvalidVolume(reason=msg)

        utils.check_metadata_properties(fields.get('metadata', None))

        volume.update(fields)
        volume.save()
        LOG.info("Volume updated successfully.", resource=volume)

    def get(self,
            context: context.RequestContext,
            volume_id: str,
            viewable_admin_meta: bool = False) -> objects.Volume:
        volume = objects.Volume.get_by_id(context, volume_id)

        try:
            context.authorize(vol_policy.GET_POLICY, target_obj=volume)
        except exception.PolicyNotAuthorized:
            # raise VolumeNotFound to avoid providing info about
            # the existence of an unauthorized volume id
            raise exception.VolumeNotFound(volume_id=volume_id)

        if viewable_admin_meta:
            ctxt = context.elevated()
            admin_metadata = self.db.volume_admin_metadata_get(ctxt,
                                                               volume_id)
            volume.admin_metadata = admin_metadata
            volume.obj_reset_changes()

        LOG.info("Volume info retrieved successfully.", resource=volume)
        return volume

    def calculate_resource_count(self,
                                 context: context.RequestContext,
                                 resource_type: str,
                                 filters: Optional[dict]) -> int:
        filters = filters if filters else {}
        allTenants = utils.get_bool_param('all_tenants', filters)
        if context.is_admin and allTenants:
            del filters['all_tenants']
        else:
            filters['project_id'] = context.project_id
        return db.calculate_resource_count(context, resource_type, filters)

    def get_all(self,
                context: context.RequestContext,
                marker: Optional[str] = None,
                limit: Optional[int] = None,
                sort_keys: Optional[Iterable[str]] = None,
                sort_dirs: Optional[Iterable[str]] = None,
                filters: Optional[dict] = None,
                viewable_admin_meta: bool = False,
                offset: Optional[int] = None) -> objects.VolumeList:
        context.authorize(vol_policy.GET_ALL_POLICY)

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
            LOG.debug("Searching by: %s.", filters)

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

        LOG.info("Get all volumes completed successfully.")
        return volumes

    def get_volume_summary(
            self,
            context: context.RequestContext,
            filters: Optional[dict] = None) -> objects.VolumeList:
        context.authorize(vol_policy.GET_ALL_POLICY)

        if filters is None:
            filters = {}

        all_tenants = utils.get_bool_param('all_tenants', filters)
        filters.pop('all_tenants', None)
        project_only = not (all_tenants and context.is_admin)
        volumes = objects.VolumeList.get_volume_summary(context, project_only)

        LOG.info("Get summary completed successfully.")
        return volumes

    def get_snapshot(self,
                     context: context.RequestContext,
                     snapshot_id: str) -> objects.Snapshot:
        snapshot = objects.Snapshot.get_by_id(context, snapshot_id)
        context.authorize(snapshot_policy.GET_POLICY, target_obj=snapshot)

        # FIXME(jdg): The objects don't have the db name entries
        # so build the resource tag manually for now.
        LOG.info("Snapshot retrieved successfully.",
                 resource={'type': 'snapshot',
                           'id': snapshot.id})
        return snapshot

    def get_volume(self,
                   context: context.RequestContext,
                   volume_id: str) -> objects.Volume:
        volume = objects.Volume.get_by_id(context, volume_id)
        context.authorize(vol_policy.GET_POLICY, target_obj=volume)
        LOG.info("Volume retrieved successfully.", resource=volume)
        return volume

    def get_all_snapshots(
            self,
            context: context.RequestContext,
            search_opts: Optional[dict] = None,
            marker: Optional[str] = None,
            limit: Optional[int] = None,
            sort_keys: Optional[list[str]] = None,
            sort_dirs: Optional[list[str]] = None,
            offset: Optional[int] = None) -> objects.SnapshotList:
        context.authorize(snapshot_policy.GET_ALL_POLICY)

        search_opts = search_opts or {}

        # Need to remove all_tenants to pass the filtering below.
        all_tenants = strutils.bool_from_string(search_opts.pop('all_tenants',
                                                                'false'))
        if context.is_admin and all_tenants:
            snapshots = objects.SnapshotList.get_all(
                context, search_opts, marker, limit, sort_keys, sort_dirs,
                offset)
        else:
            snapshots = objects.SnapshotList.get_all_by_project(
                context, context.project_id, search_opts, marker, limit,
                sort_keys, sort_dirs, offset)

        LOG.info("Get all snapshots completed successfully.")
        return snapshots

    def reserve_volume(self,
                       context: context.RequestContext,
                       volume: objects.Volume) -> None:
        context.authorize(vol_action_policy.RESERVE_POLICY, target_obj=volume)
        expected = {'multiattach': volume.multiattach,
                    'status': (('available', 'in-use') if volume.multiattach
                               else 'available')}

        result = volume.conditional_update({'status': 'attaching'}, expected)

        if not result:
            expected_status = utils.build_or_str(expected['status'])
            msg = _('Volume status must be %(expected)s to reserve, but the '
                    'status is %(current)s.') % {'expected': expected_status,
                                                 'current': volume.status}
            LOG.error(msg)
            raise exception.InvalidVolume(reason=msg)

        LOG.info("Reserve volume completed successfully.",
                 resource=volume)

    def unreserve_volume(self,
                         context: context.RequestContext,
                         volume: objects.Volume) -> None:
        context.authorize(vol_action_policy.UNRESERVE_POLICY,
                          target_obj=volume)
        expected = {'status': 'attaching'}
        # Status change depends on whether it has attachments (in-use) or not
        # (available)
        value = {'status': db.Case([(db.volume_has_attachments_filter(),
                                     'in-use')],
                                   else_='available')}
        result = volume.conditional_update(value, expected)
        if not result:
            LOG.debug("Attempted to unreserve volume that was not "
                      "reserved, nothing to do.",
                      resource=volume)
            return

        LOG.info("Unreserve volume completed successfully.",
                 resource=volume)

    def begin_detaching(self,
                        context: context.RequestContext,
                        volume: objects.Volume) -> None:
        context.authorize(vol_action_policy.BEGIN_DETACHING_POLICY,
                          target_obj=volume)
        # If we are in the middle of a volume migration, we don't want the
        # user to see that the volume is 'detaching'. Having
        # 'migration_status' set will have the same effect internally.
        expected = {'status': 'in-use',
                    'attach_status': fields.VolumeAttachStatus.ATTACHED,
                    'migration_status': self.AVAILABLE_MIGRATION_STATUS}

        result = volume.conditional_update({'status': 'detaching'}, expected)

        if not (result or self._is_volume_migrating(volume)):
            msg = _("Unable to detach volume. Volume status must be 'in-use' "
                    "and attach_status must be 'attached' to detach.")
            LOG.error(msg)
            raise exception.InvalidVolume(reason=msg)

        LOG.info("Begin detaching volume completed successfully.",
                 resource=volume)

    def roll_detaching(self,
                       context: context.RequestContext,
                       volume: objects.Volume) -> None:
        context.authorize(vol_action_policy.ROLL_DETACHING_POLICY,
                          target_obj=volume)
        volume.conditional_update({'status': 'in-use'},
                                  {'status': 'detaching'})
        LOG.info("Roll detaching of volume completed successfully.",
                 resource=volume)

    def attach(self,
               context: context.RequestContext,
               volume: objects.Volume,
               instance_uuid: str,
               host_name: str,
               mountpoint: str,
               mode: str) -> objects.VolumeAttachment:
        context.authorize(vol_action_policy.ATTACH_POLICY,
                          target_obj=volume)
        if volume.status == 'maintenance':
            LOG.info('Unable to attach volume, '
                     'because it is in maintenance.', resource=volume)
            msg = _("The volume cannot be attached in maintenance mode.")
            raise exception.InvalidVolume(reason=msg)

        # We add readonly metadata if it doesn't already exist
        readonly = self.update_volume_admin_metadata(context.elevated(),
                                                     volume,
                                                     {'readonly': 'False'},
                                                     update=False)['readonly']
        if readonly == 'True' and mode != 'ro':
            raise exception.InvalidVolumeAttachMode(mode=mode,
                                                    volume_id=volume.id)

        attach_results = self.volume_rpcapi.attach_volume(context,
                                                          volume,
                                                          instance_uuid,
                                                          host_name,
                                                          mountpoint,
                                                          mode)
        LOG.info("Attach volume completed successfully.",
                 resource=volume)
        return attach_results

    def detach(self,
               context: context.RequestContext,
               volume: objects.Volume,
               attachment_id: str) -> None:
        context.authorize(vol_action_policy.DETACH_POLICY,
                          target_obj=volume)
        self.attachment_deletion_allowed(context, attachment_id, volume)

        if volume['status'] == 'maintenance':
            LOG.info('Unable to detach volume, '
                     'because it is in maintenance.', resource=volume)
            msg = _("The volume cannot be detached in maintenance mode.")
            raise exception.InvalidVolume(reason=msg)

        detach_results = self.volume_rpcapi.detach_volume(context, volume,
                                                          attachment_id)
        LOG.info("Detach volume completed successfully.",
                 resource=volume)
        return detach_results

    def initialize_connection(self,
                              context: context.RequestContext,
                              volume: objects.Volume,
                              connector: dict) -> dict:
        context.authorize(vol_action_policy.INITIALIZE_POLICY,
                          target_obj=volume)
        if volume.status == 'maintenance':
            LOG.info('Unable to initialize the connection for '
                     'volume, because it is in '
                     'maintenance.', resource=volume)
            msg = _("The volume connection cannot be initialized in "
                    "maintenance mode.")
            raise exception.InvalidVolume(reason=msg)
        init_results = self.volume_rpcapi.initialize_connection(context,
                                                                volume,
                                                                connector)
        LOG.info("Initialize volume connection completed successfully.",
                 resource=volume)
        return init_results

    @staticmethod
    def is_service_request(ctxt: 'context.RequestContext') -> bool:
        """Check if a request is coming from a service

        A request is coming from a service if it has a service token and the
        service user has one of the roles configured in the
        `service_token_roles` configuration option in the
        `[keystone_authtoken]` section (defaults to `service`).
        """
        roles = ctxt.service_roles
        service_roles = set(CONF.keystone_authtoken.service_token_roles)
        return bool(roles and service_roles.intersection(roles))

    def terminate_connection(self,
                             context: context.RequestContext,
                             volume: objects.Volume,
                             connector: dict,
                             force: bool = False) -> None:
        context.authorize(vol_action_policy.TERMINATE_POLICY,
                          target_obj=volume)
        self.attachment_deletion_allowed(context, None, volume)

        self.volume_rpcapi.terminate_connection(context,
                                                volume,
                                                connector,
                                                force)
        LOG.info("Terminate volume connection completed successfully.",
                 resource=volume)
        self.unreserve_volume(context, volume)

    def accept_transfer(self,
                        context: context.RequestContext,
                        volume: objects.Volume,
                        new_user: str,
                        new_project: str,
                        no_snapshots: bool = False) -> dict:
        if volume['status'] == 'maintenance':
            LOG.info('Unable to accept transfer for volume, '
                     'because it is in maintenance.', resource=volume)
            msg = _("The volume cannot accept transfer in maintenance mode.")
            raise exception.InvalidVolume(reason=msg)
        results = self.volume_rpcapi.accept_transfer(context,
                                                     volume,
                                                     new_user,
                                                     new_project,
                                                     no_snapshots=no_snapshots)
        LOG.info("Transfer volume completed successfully.",
                 resource=volume)
        return results

    def _create_snapshot(
            self,
            context: context.RequestContext,
            volume: objects.Volume,
            name: str,
            description: str,
            force: bool = False,
            metadata: Optional[dict] = None,
            cgsnapshot_id: Optional[str] = None,
            group_snapshot_id: Optional[str] = None,
            allow_in_use: bool = False) -> objects.Snapshot:
        volume.assert_not_frozen()
        snapshot = self.create_snapshot_in_db(
            context, volume, name,
            description, force, metadata, cgsnapshot_id,
            True, group_snapshot_id, allow_in_use)
        # NOTE(tommylikehu): We only wrap the 'size' attribute here
        # because only the volume's host is passed and only capacity is
        # validated in the scheduler now.
        kwargs = {'snapshot_id': snapshot.id,
                  'volume_properties': objects.VolumeProperties(
                      size=volume.size)}
        self.scheduler_rpcapi.create_snapshot(context, volume, snapshot,
                                              volume.service_topic_queue,
                                              objects.RequestSpec(**kwargs))
        return snapshot

    def create_snapshot_in_db(
            self,
            context: context.RequestContext,
            volume: objects.Volume,
            name: Optional[str],
            description: Optional[str],
            force: bool,
            metadata: Optional[dict],
            cgsnapshot_id: Optional[str],
            commit_quota: bool = True,
            group_snapshot_id: Optional[str] = None,
            allow_in_use: bool = False) -> objects.Snapshot:
        self._create_snapshot_in_db_validate(context, volume)

        utils.check_metadata_properties(metadata)

        valid_status: tuple[str, ...]
        valid_status = ('available',)
        if force or allow_in_use:
            valid_status = ('available', 'in-use')

        if volume['status'] not in valid_status:
            msg = _("Volume %(vol_id)s status must be %(status)s, "
                    "but current status is: "
                    "%(vol_status)s.") % {'vol_id': volume['id'],
                                          'status': ', '.join(valid_status),
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
                quota_utils.process_reserve_over_quota(
                    context, e,
                    resource='snapshots',
                    size=volume.size)

        snapshot = None
        try:
            kwargs = {
                'volume_id': volume['id'],
                'cgsnapshot_id': cgsnapshot_id,
                'group_snapshot_id': group_snapshot_id,
                'user_id': context.user_id,
                'project_id': context.project_id,
                'status': fields.SnapshotStatus.CREATING,
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
            volume.refresh()

            if volume['status'] not in valid_status:
                msg = _("Volume %(vol_id)s status must be %(status)s , "
                        "but current status is: "
                        "%(vol_status)s.") % {'vol_id': volume['id'],
                                              'status':
                                                  ', '.join(valid_status),
                                              'vol_status':
                                                  volume['status']}
                raise exception.InvalidVolume(reason=msg)
            if commit_quota:
                QUOTAS.commit(context, reservations)
        except Exception:
            with excutils.save_and_reraise_exception():
                try:
                    assert snapshot is not None
                    if snapshot.obj_attr_is_set('id'):
                        snapshot.destroy()
                finally:
                    if commit_quota:
                        QUOTAS.rollback(context, reservations)

        return snapshot

    def create_snapshots_in_db(
            self,
            context: context.RequestContext,
            volume_list: list,
            name: str,
            description: str,
            cgsnapshot_id: str,
            group_snapshot_id: Optional[str] = None) -> list:
        snapshot_list = []
        for volume in volume_list:
            self._create_snapshot_in_db_validate(context, volume)

        reservations = self._create_snapshots_in_db_reserve(
            context, volume_list)

        options_list = []
        for volume in volume_list:
            options = self._create_snapshot_in_db_options(
                context, volume, name, description, cgsnapshot_id,
                group_snapshot_id)
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

    def _create_snapshot_in_db_validate(self,
                                        context: context.RequestContext,
                                        volume: objects.Volume) -> None:
        context.authorize(snapshot_policy.CREATE_POLICY, target_obj=volume)

        if not volume.host:
            msg = _("The snapshot cannot be created because volume has "
                    "not been scheduled to any host.")
            raise exception.InvalidVolume(reason=msg)
        if volume['status'] == 'maintenance':
            LOG.info('Unable to create the snapshot for volume, '
                     'because it is in maintenance.', resource=volume)
            msg = _("The snapshot cannot be created when the volume is in "
                    "maintenance mode.")
            raise exception.InvalidVolume(reason=msg)
        if self._is_volume_migrating(volume):
            # Volume is migrating, wait until done
            msg = _("Snapshot cannot be created while volume is migrating.")
            raise exception.InvalidVolume(reason=msg)
        if volume['status'] == 'error':
            msg = _("The snapshot cannot be created when the volume is "
                    "in error status.")
            LOG.error(msg)
            raise exception.InvalidVolume(reason=msg)
        if volume['status'].startswith('replica_'):
            # Can't snapshot secondary replica
            msg = _("Snapshot of secondary replica is not allowed.")
            raise exception.InvalidVolume(reason=msg)

    def _create_snapshots_in_db_reserve(
            self,
            context: context.RequestContext,
            volume_list: objects.VolumeList) -> list:
        reserve_opts_list = []
        total_reserve_opts: dict[str, int] = {}
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
            quota_utils.process_reserve_over_quota(
                context,
                e,
                resource='snapshots',
                size=total_reserve_opts.get('gigabytes', volume.size))

        return reservations

    def _create_snapshot_in_db_options(
            self,
            context: context.RequestContext,
            volume: objects.Volume,
            name: str,
            description: str,
            cgsnapshot_id: str,
            group_snapshot_id: Optional[str] = None) -> dict[str, Any]:
        options = {'volume_id': volume['id'],
                   'cgsnapshot_id': cgsnapshot_id,
                   'group_snapshot_id': group_snapshot_id,
                   'user_id': context.user_id,
                   'project_id': context.project_id,
                   'status': fields.SnapshotStatus.CREATING,
                   'progress': '0%',
                   'volume_size': volume['size'],
                   'display_name': name,
                   'display_description': description,
                   'volume_type_id': volume['volume_type_id'],
                   'encryption_key_id': volume['encryption_key_id']}
        return options

    def create_snapshot(
            self,
            context: context.RequestContext,
            volume: objects.Volume,
            name: str,
            description: str,
            metadata: Optional[dict[str, Any]] = None,
            cgsnapshot_id: Optional[str] = None,
            group_snapshot_id: Optional[str] = None,
            allow_in_use: bool = False) -> objects.Snapshot:
        result = self._create_snapshot(context, volume, name, description,
                                       False, metadata, cgsnapshot_id,
                                       group_snapshot_id, allow_in_use)
        LOG.info("Snapshot create request issued successfully.",
                 resource=result)
        return result

    def create_snapshot_force(
            self,
            context: context.RequestContext,
            volume: objects.Volume,
            name: str,
            description: str,
            metadata: Optional[dict[str, Any]] = None) -> objects.Snapshot:
        result = self._create_snapshot(context, volume, name, description,
                                       True, metadata)
        LOG.info("Snapshot force create request issued successfully.",
                 resource=result)
        return result

    def delete_snapshot(self,
                        context: context.RequestContext,
                        snapshot: objects.Snapshot,
                        force: bool = False,
                        unmanage_only: bool = False) -> None:
        context.authorize(snapshot_policy.DELETE_POLICY,
                          target_obj=snapshot)
        if not unmanage_only:
            snapshot.assert_not_frozen()

        # Build required conditions for conditional update
        expected: dict[str, Any] = {'cgsnapshot_id': None,
                                    'group_snapshot_id': None}
        # If not force deleting we have status conditions
        if not force:
            expected['status'] = (fields.SnapshotStatus.AVAILABLE,
                                  fields.SnapshotStatus.ERROR)

        values = {'status': fields.SnapshotStatus.DELETING}
        if unmanage_only is True:
            values['status'] = fields.SnapshotStatus.UNMANAGING
        result = snapshot.conditional_update(values, expected)
        if not result:
            status = utils.build_or_str(expected.get('status'),
                                        _('status must be %s and'))
            msg = (_('Snapshot %s must not be part of a group.') %
                   status)
            LOG.error(msg)
            raise exception.InvalidSnapshot(reason=msg)

        self.volume_rpcapi.delete_snapshot(context, snapshot, unmanage_only)
        LOG.info("Snapshot delete request issued successfully.",
                 resource=snapshot)

    def update_snapshot(self,
                        context: context.RequestContext,
                        snapshot: objects.Snapshot,
                        fields: dict[str, Any]) -> None:
        context.authorize(snapshot_policy.UPDATE_POLICY,
                          target_obj=snapshot)
        snapshot.update(fields)
        snapshot.save()

    def get_volume_metadata(self,
                            context: context.RequestContext,
                            volume: objects.Volume) -> dict:
        """Get all metadata associated with a volume."""
        context.authorize(vol_meta_policy.GET_POLICY, target_obj=volume)
        rv = self.db.volume_metadata_get(context, volume['id'])
        LOG.info("Get volume metadata completed successfully.",
                 resource=volume)
        return dict(rv)

    def create_volume_metadata(self,
                               context: context.RequestContext,
                               volume: objects.Volume,
                               metadata: dict[str, Any]) -> dict:
        """Creates volume metadata."""
        context.authorize(vol_meta_policy.CREATE_POLICY, target_obj=volume)
        db_meta = self._update_volume_metadata(context, volume, metadata)

        LOG.info("Create volume metadata completed successfully.",
                 resource=volume)
        return db_meta

    def delete_volume_metadata(self,
                               context: context.RequestContext,
                               volume: objects.Volume,
                               key: str,
                               meta_type=common.METADATA_TYPES.user) -> None:
        """Delete the given metadata item from a volume."""
        context.authorize(vol_meta_policy.DELETE_POLICY, target_obj=volume)
        if volume.status in ('maintenance', 'uploading'):
            msg = _('Deleting volume metadata is not allowed for volumes in '
                    '%s status.') % volume.status
            LOG.info(msg, resource=volume)
            raise exception.InvalidVolume(reason=msg)
        self.db.volume_metadata_delete(context, volume.id, key, meta_type)
        LOG.info("Delete volume metadata completed successfully.",
                 resource=volume)

    def _update_volume_metadata(self,
                                context: context.RequestContext,
                                volume: objects.Volume,
                                metadata: dict[str, Any],
                                delete: bool = False,
                                meta_type=common.METADATA_TYPES.user) -> dict:
        if volume['status'] in ('maintenance', 'uploading'):
            msg = _('Updating volume metadata is not allowed for volumes in '
                    '%s status.') % volume['status']
            LOG.info(msg, resource=volume)
            raise exception.InvalidVolume(reason=msg)
        return self.db.volume_metadata_update(context, volume['id'],
                                              metadata, delete, meta_type)

    def update_volume_metadata(self,
                               context: context.RequestContext,
                               volume: objects.Volume,
                               metadata: dict[str, Any],
                               delete: bool = False,
                               meta_type=common.METADATA_TYPES.user) -> dict:
        """Updates volume metadata.

        If delete is True, metadata items that are not specified in the
        `metadata` argument will be deleted.

        """
        context.authorize(vol_meta_policy.UPDATE_POLICY, target_obj=volume)
        db_meta = self._update_volume_metadata(context, volume, metadata,
                                               delete, meta_type)

        # TODO(jdg): Implement an RPC call for drivers that may use this info

        LOG.info("Update volume metadata completed successfully.",
                 resource=volume)
        return db_meta

    def update_volume_admin_metadata(self,
                                     context: context.RequestContext,
                                     volume: objects.Volume,
                                     metadata: dict[str, Any],
                                     delete: Optional[bool] = False,
                                     add: Optional[bool] = True,
                                     update: Optional[bool] = True) -> dict:
        """Updates or creates volume administration metadata.

        If delete is True, metadata items that are not specified in the
        `metadata` argument will be deleted.

        """
        context.authorize(vol_meta_policy.UPDATE_ADMIN_METADATA_POLICY,
                          target_obj=volume)
        utils.check_metadata_properties(metadata)
        # Policy could allow non admin users to update admin metadata, but
        # underlying DB methods require admin privileges, so we elevate the
        # context.
        with volume.obj_as_admin():
            volume.admin_metadata_update(metadata, delete, add, update)

        # TODO(jdg): Implement an RPC call for drivers that may use this info

        LOG.info("Update volume admin metadata completed successfully.",
                 resource=volume)
        return volume.admin_metadata

    def get_snapshot_metadata(self,
                              context: context.RequestContext,
                              snapshot: objects.Snapshot) -> dict:
        """Get all metadata associated with a snapshot."""
        context.authorize(s_meta_policy.GET_POLICY,
                          target_obj=snapshot)
        LOG.info("Get snapshot metadata completed successfully.",
                 resource=snapshot)
        return snapshot.metadata

    def delete_snapshot_metadata(self,
                                 context: context.RequestContext,
                                 snapshot: objects.Snapshot,
                                 key: str) -> None:
        """Delete the given metadata item from a snapshot."""
        context.authorize(s_meta_policy.DELETE_POLICY,
                          target_obj=snapshot)
        snapshot.delete_metadata_key(context, key)
        LOG.info("Delete snapshot metadata completed successfully.",
                 resource=snapshot)

    def update_snapshot_metadata(self,
                                 context: context.RequestContext,
                                 snapshot: objects.Snapshot,
                                 metadata: dict[str, Any],
                                 delete: bool = False) -> dict:
        """Updates or creates snapshot metadata.

        If delete is True, metadata items that are not specified in the
        `metadata` argument will be deleted.

        """
        context.authorize(s_meta_policy.UPDATE_POLICY,
                          target_obj=snapshot)
        if delete:
            _metadata = metadata
        else:
            orig_meta = snapshot.metadata
            _metadata = orig_meta.copy()
            _metadata.update(metadata)

        utils.check_metadata_properties(_metadata)

        snapshot.metadata = _metadata
        snapshot.save()

        # TODO(jdg): Implement an RPC call for drivers that may use this info

        LOG.info("Update snapshot metadata completed successfully.",
                 resource=snapshot)
        return snapshot.metadata

    def get_volumes_image_metadata(
            self,
            context: context.RequestContext) -> collections.defaultdict:
        context.authorize(vol_meta_policy.GET_POLICY)
        db_data = self.db.volume_glance_metadata_get_all(context)
        results: collections.defaultdict = collections.defaultdict(dict)
        for meta_entry in db_data:
            results[meta_entry['volume_id']].update({meta_entry['key']:
                                                     meta_entry['value']})
        return results

    def get_volume_image_metadata(self,
                                  context: context.RequestContext,
                                  volume: objects.Volume) -> dict[str, str]:
        context.authorize(vol_meta_policy.GET_POLICY, target_obj=volume)
        db_data = self.db.volume_glance_metadata_get(context, volume['id'])
        LOG.info("Get volume image-metadata completed successfully.",
                 resource=volume)
        return {meta_entry.key: meta_entry.value for meta_entry in db_data}

    def get_list_volumes_image_metadata(
            self,
            context: context.RequestContext,
            volume_id_list: list[str]) -> DefaultDict[str, str]:
        db_data = self.db.volume_glance_metadata_list_get(context,
                                                          volume_id_list)
        results: collections.defaultdict = collections.defaultdict(dict)
        for meta_entry in db_data:
            results[meta_entry['volume_id']].update({meta_entry['key']:
                                                     meta_entry['value']})
        return results

    def _merge_volume_image_meta(self,
                                 context: context.RequestContext,
                                 volume: objects.Volume,
                                 image_meta: dict) -> None:
        """Merges the image metadata from volume into image_meta"""
        glance_core_props = CONF.glance_core_properties
        if glance_core_props:
            try:
                vol_img_metadata = self.get_volume_image_metadata(
                    context, volume)
                custom_property_set = (
                    set(vol_img_metadata).difference(glance_core_props))
                if custom_property_set:
                    # only include elements that haven't already been
                    # assigned values
                    filtered_property_set = custom_property_set.difference(
                        image_meta)
                    image_meta['properties'] = {
                        custom_prop: vol_img_metadata[custom_prop]
                        for custom_prop in filtered_property_set}
            except exception.GlanceMetadataNotFound:
                # If volume is not created from image, No glance metadata
                # would be available for that volume in
                # volume glance metadata table
                pass

    def copy_volume_to_image(self,
                             context: context.RequestContext,
                             volume: objects.Volume,
                             metadata: dict[str, str],
                             force: bool) -> dict[str, Optional[str]]:
        """Create a new image from the specified volume."""
        if not CONF.enable_force_upload and force:
            LOG.info("Force upload to image is disabled, "
                     "Force option will be ignored.",
                     resource={'type': 'volume', 'id': volume['id']})
            force = False

        # Build required conditions for conditional update
        expected = {'status': ('available', 'in-use') if force
                    else 'available'}
        values = {'status': 'uploading',
                  'previous_status': volume.model.status}

        result = volume.conditional_update(values, expected)
        if not result:
            msg = (_('Volume %(vol_id)s status must be %(statuses)s') %
                   {'vol_id': volume.id,
                    'statuses': utils.build_or_str(expected['status'])})
            raise exception.InvalidVolume(reason=msg)

        try:
            self._merge_volume_image_meta(context, volume, metadata)
            metadata = image_utils.filter_out_reserved_namespaces_metadata(
                metadata)

            recv_metadata = self.image_service.create(context, metadata)

            # NOTE(ZhengMa): Check if allow image compression before image
            # uploading
            if recv_metadata.get('container_format') == 'compressed':
                allow_compression = CONF.allow_compression_on_image_upload
                if allow_compression is False:
                    raise exception.ImageCompressionNotAllowed()
        except Exception:
            # NOTE(geguileo): To mimic behavior before conditional_update we
            # will rollback status if image create fails
            with excutils.save_and_reraise_exception():
                volume.conditional_update(
                    {'status': volume.model.previous_status,
                     'previous_status': None},
                    {'status': 'uploading'})

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
        if 'protected' in recv_metadata:
            response['protected'] = recv_metadata.get('protected')
        if 'is_public' in recv_metadata:
            response['is_public'] = recv_metadata.get('is_public')
        elif 'visibility' in recv_metadata:
            response['visibility'] = recv_metadata.get('visibility')
        LOG.info("Copy volume to image completed successfully.",
                 resource=volume)
        return response

    def _extend(self,
                context: context.RequestContext,
                volume: objects.Volume,
                new_size: int,
                attached: bool = False) -> None:
        value = {'status': 'extending',
                 'previous_status': volume.status}
        expected: dict
        if attached:
            expected = {'status': 'in-use'}
        else:
            expected = {'status': 'available'}
        orig_status = {'status': volume.status}

        def _roll_back_status() -> None:
            status = orig_status['status']
            msg = _('Could not return volume %(id)s to %(status)s.')
            try:
                if not volume.conditional_update(orig_status, value):
                    LOG.error(msg, {'id': volume.id, 'status': status})
            except Exception:
                LOG.exception(msg, {'id': volume.id, 'status': status})

        size_increase = (int(new_size)) - volume.size
        if size_increase <= 0:
            msg = (_("New size for extend must be greater "
                     "than current size. (current: %(size)s, "
                     "extended: %(new_size)s).") % {'new_size': new_size,
                                                    'size': volume.size})
            raise exception.InvalidInput(reason=msg)

        # Make sure we pass the potential size limitations in the volume type
        try:
            volume_type = volume_types.get_volume_type(context,
                                                       volume.volume_type_id)
        except (exception.InvalidVolumeType, exception.VolumeTypeNotFound):
            volume_type = None
        volume_types.provision_filter_on_size(context, volume_type, new_size)

        result = volume.conditional_update(value, expected)
        if not result:
            msg = (_("Volume %(vol_id)s status must be '%(expected)s' "
                     "to extend, currently %(status)s.")
                   % {'vol_id': volume.id,
                      'status': volume.status,
                      'expected': str(expected)})
            raise exception.InvalidVolume(reason=msg)

        rollback = True
        try:
            values = {'per_volume_gigabytes': new_size}
            QUOTAS.limit_check(context, project_id=context.project_id,
                               **values)
            rollback = False
        except exception.OverQuota as e:
            quotas = e.kwargs['quotas']
            raise exception.VolumeSizeExceedsLimit(
                size=new_size, limit=quotas['per_volume_gigabytes'])
        finally:
            # NOTE(geguileo): To mimic behavior before conditional_update we
            # will rollback status on quota reservation failure regardless of
            # the exception that caused the failure.
            if rollback:
                _roll_back_status()

        reservations = None
        try:
            reserve_opts = {'gigabytes': size_increase}
            QUOTAS.add_volume_type_opts(context, reserve_opts,
                                        volume.volume_type_id)
            reservations = QUOTAS.reserve(context,
                                          project_id=volume.project_id,
                                          **reserve_opts)
        except exception.OverQuota as exc:
            gigabytes = exc.kwargs['usages']['gigabytes']
            gb_quotas = exc.kwargs['quotas']['gigabytes']

            consumed = gigabytes['reserved'] + gigabytes['in_use']
            LOG.error("Quota exceeded for %(s_pid)s, tried to extend volume "
                      "by %(s_size)sG, (%(d_consumed)dG of %(d_quota)dG "
                      "already consumed).",
                      {'s_pid': context.project_id,
                       's_size': size_increase,
                       'd_consumed': consumed,
                       'd_quota': gb_quotas})
            raise exception.VolumeSizeExceedsAvailableQuota(
                requested=size_increase, consumed=consumed, quota=gb_quotas)
        finally:
            # NOTE(geguileo): To mimic behavior before conditional_update we
            # will rollback status on quota reservation failure regardless of
            # the exception that caused the failure.
            if reservations is None:
                _roll_back_status()

        volume_type = {}
        if volume.volume_type_id:
            volume_type = volume_types.get_volume_type(context.elevated(),
                                                       volume.volume_type_id)

        request_spec = {
            'volume_properties': volume,
            'volume_type': volume_type,
            'volume_id': volume.id
        }

        self.scheduler_rpcapi.extend_volume(context, volume, new_size,
                                            reservations, request_spec)

        LOG.info("Extend volume request issued successfully.",
                 resource=volume)

    def extend(self,
               context: context.RequestContext,
               volume: objects.Volume,
               new_size: int) -> None:
        context.authorize(vol_action_policy.EXTEND_POLICY,
                          target_obj=volume)
        self._extend(context, volume, new_size, attached=False)

    # NOTE(tommylikehu): New method is added here so that administrator
    # can enable/disable this ability by editing the policy file if the
    # cloud environment doesn't allow this operation.
    def extend_attached_volume(self,
                               context: context.RequestContext,
                               volume: objects.Volume,
                               new_size: int) -> None:
        context.authorize(vol_action_policy.EXTEND_ATTACHED_POLICY,
                          target_obj=volume)
        self._extend(context, volume, new_size, attached=True)

    def extend_volume_completion(self,
                                 context: context.RequestContext,
                                 volume: objects.Volume,
                                 error: bool):
        context.authorize(vol_action_policy.EXTEND_COMPLETE_POLICY,
                          target_obj=volume)

        if volume.status != 'extending':
            msg = _('Volume is not being extended.')
            raise exception.InvalidVolume(reason=msg)

        try:
            with volume.obj_as_admin():
                new_size = int(volume.admin_metadata['extend_new_size'])
                reservations = jsonutils.loads(
                    volume.admin_metadata['extend_reservations'])
        except (KeyError, ValueError, jsonutils.json.decoder.JSONDecodeError):
            msg = _('Required volume admin metadata is malformed or missing.')
            raise exception.InvalidVolume(reason=msg)

        if new_size <= volume.size:
            msg = _('The target volume size provided in volume admin metadata '
                    '%(size)s is smaller or equal to the current volume size.'
                    % volume.admin_metadata["extend_new_size"])
            raise exception.InvalidVolume(reason=msg)

        if type(reservations) is not list:
            msg = _('The stored quota reservations for extending the volume '
                    'must be in a list format.')
            raise exception.InvalidVolume(reason=msg)

        with volume.obj_as_admin():
            del volume.admin_metadata['extend_new_size']
            del volume.admin_metadata['extend_reservations']
            volume.save()

        self.volume_rpcapi.extend_volume_completion(context, volume, new_size,
                                                    reservations, error)

        LOG.info("Extend volume completion issued successfully.",
                 resource=volume)

    def migrate_volume(self,
                       context: context.RequestContext,
                       volume: objects.Volume,
                       host: str,
                       cluster_name: str,
                       force_copy: bool,
                       lock_volume: bool) -> None:
        """Migrate the volume to the specified host or cluster."""
        elevated = context.elevated()
        context.authorize(vol_action_policy.MIGRATE_POLICY,
                          target_obj=volume)

        # If we received a request to migrate to a host
        # Look for the service - must be up and enabled
        svc_host = host and volume_utils.extract_host(host, 'backend')
        svc_cluster = cluster_name and volume_utils.extract_host(cluster_name,
                                                                 'backend')
        # NOTE(geguileo): Only svc_host or svc_cluster is set, so when we get
        # a service from the DB we are getting either one specific service from
        # a host or any service from a cluster that is up, which means that the
        # cluster itself is also up.
        try:
            svc = objects.Service.get_by_id(elevated, None, is_up=True,
                                            topic=constants.VOLUME_TOPIC,
                                            host=svc_host, disabled=False,
                                            cluster_name=svc_cluster,
                                            backend_match_level='pool')
        except exception.ServiceNotFound:
            msg = _("No available service named '%s'") % (cluster_name or host)
            LOG.error(msg)
            raise exception.InvalidHost(reason=msg)
        # Even if we were requested to do a migration to a host, if the host is
        # in a cluster we will do a cluster migration.
        cluster_name = svc.cluster_name

        # Build required conditions for conditional update
        expected = {'status': ('available', 'in-use'),
                    'migration_status': self.AVAILABLE_MIGRATION_STATUS,
                    'replication_status': (
                        None,
                        fields.ReplicationStatus.DISABLED,
                        fields.ReplicationStatus.NOT_CAPABLE),
                    'consistencygroup_id': (None, ''),
                    'group_id': (None, '')}

        # We want to make sure that the migration is to another host or
        # another cluster.
        if cluster_name:
            expected['cluster_name'] = db.Not(cluster_name)
        else:
            expected['host'] = db.Not(host)

        filters = [~db.volume_has_snapshots_filter()]

        updates = {'migration_status': 'starting',
                   'previous_status': volume.model.status}

        # When the migration of an available volume starts, both the status
        # and the migration status of the volume will be changed.
        # If the admin sets lock_volume flag to True, the volume
        # status is changed to 'maintenance', telling users
        # that this volume is in maintenance mode, and no action is allowed
        # on this volume, e.g. attach, detach, retype, migrate, etc.
        if lock_volume:
            updates['status'] = db.Case(
                [(volume.model.status == 'available', 'maintenance')],
                else_=volume.model.status)

        result = volume.conditional_update(updates, expected, filters)

        if not result:
            msg = _('Volume %s status must be available or in-use, must not '
                    'be migrating, have snapshots, be replicated, be part of '
                    'a group and destination host/cluster must be different '
                    'than the current one') % volume.id
            LOG.error(msg)
            raise exception.InvalidVolume(reason=msg)

        # Call the scheduler to ensure that the host exists and that it can
        # accept the volume
        volume_type = {}
        if volume.volume_type_id:
            volume_type = volume_types.get_volume_type(context.elevated(),
                                                       volume.volume_type_id)
        request_spec = {'volume_properties': volume,
                        'volume_type': volume_type,
                        'volume_id': volume.id}
        self.scheduler_rpcapi.migrate_volume(context,
                                             volume,
                                             cluster_name or host,
                                             force_copy,
                                             request_spec)
        LOG.info("Migrate volume request issued successfully.",
                 resource=volume)

    def migrate_volume_completion(self,
                                  context: context.RequestContext,
                                  volume: objects.Volume,
                                  new_volume: objects.Volume,
                                  error: bool) -> str:
        context.authorize(vol_action_policy.MIGRATE_COMPLETE_POLICY,
                          target_obj=volume)
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

        LOG.info("Migrate volume completion issued successfully.",
                 resource=volume)
        return self.volume_rpcapi.migrate_volume_completion(context, volume,
                                                            new_volume, error)

    def update_readonly_flag(self,
                             context: context.RequestContext,
                             volume: objects.Volume,
                             flag) -> None:
        context.authorize(vol_action_policy.UPDATE_READONLY_POLICY,
                          target_obj=volume)
        if volume['status'] != 'available':
            msg = _('Volume %(vol_id)s status must be available '
                    'to update readonly flag, but current status is: '
                    '%(vol_status)s.') % {'vol_id': volume['id'],
                                          'vol_status': volume['status']}
            raise exception.InvalidVolume(reason=msg)
        self.update_volume_admin_metadata(context.elevated(), volume,
                                          {'readonly': str(flag)})
        LOG.info("Update readonly setting on volume "
                 "completed successfully.",
                 resource=volume)

    def retype(self,
               context: context.RequestContext,
               volume: objects.Volume,
               new_type: Union[str, objects.VolumeType],
               migration_policy: Optional[str] = None) -> None:
        """Attempt to modify the type associated with an existing volume."""
        context.authorize(vol_action_policy.RETYPE_POLICY, target_obj=volume)

        # Support specifying volume type by ID or name
        try:
            new_type = (
                volume_type.VolumeType.get_by_name_or_id(context.elevated(),
                                                         new_type))
        except exception.InvalidVolumeType:
            msg = _('Invalid volume_type passed: %s.') % new_type
            LOG.error(msg)
            raise exception.InvalidInput(reason=msg)

        new_type_id = new_type['id']

        # Make sure we pass the potential size limitations in the volume type
        volume_types.provision_filter_on_size(context, new_type, volume.size)

        # NOTE(jdg): We check here if multiattach is involved in either side
        # of the retype, we can't change multiattach on an in-use volume
        # because there's things the hypervisor needs when attaching, so
        # we just disallow retype of in-use volumes in this case.  You still
        # have to get through scheduling if all the conditions are met, we
        # should consider an up front capabilities check to give fast feedback
        # rather than "No hosts found" and error status
        src_is_multiattach = volume.multiattach
        tgt_is_multiattach = False

        if new_type:
            tgt_is_multiattach = self._is_multiattach(new_type)

        if src_is_multiattach != tgt_is_multiattach:
            if volume.status != "available":
                msg = _('Invalid volume_type passed, retypes affecting '
                        'multiattach are only allowed on available volumes, '
                        'the specified volume however currently has a status '
                        'of: %s.') % volume.status
                LOG.info(msg)
                raise exception.InvalidInput(reason=msg)

            # If they are retyping to a multiattach capable, make sure they
            # are allowed to do so.
            if tgt_is_multiattach:
                context.authorize(vol_policy.MULTIATTACH_POLICY,
                                  target_obj=volume)

        if tgt_is_multiattach and self._is_encrypted(new_type):
            msg = ('Retype requested both encryption and multi-attach, '
                   'which is not supported.')
            raise exception.InvalidInput(reason=msg)

        # We're checking here in so that we can report any quota issues as
        # early as possible, but won't commit until we change the type. We
        # pass the reservations onward in case we need to roll back.
        reservations = quota_utils.get_volume_type_reservation(
            context, volume, new_type_id, reserve_vol_type_only=True)

        # Get old reservations
        try:
            old_reservations = quota_utils.get_volume_type_reservation(
                context, volume, volume.volume_type_id,
                reserve_vol_type_only=True, negative=True)

        except Exception:
            volume.status = volume.previous_status
            volume.save()
            msg = _("Failed to update quota usage while retyping volume.")
            LOG.exception(msg, resource=volume)
            raise exception.CinderException(msg)

        # Build required conditions for conditional update
        expected = {'status': ('available', 'in-use'),
                    'migration_status': self.AVAILABLE_MIGRATION_STATUS,
                    'consistencygroup_id': (None, ''),
                    'group_id': (None, ''),
                    'volume_type_id': db.Not(new_type_id)}

        # We don't support changing QoS at the front-end yet for in-use volumes
        # TODO(avishay): Call Nova to change QoS setting (libvirt has support
        # - virDomainSetBlockIoTune() - Nova does not have support yet).
        filters = [db.volume_qos_allows_retype(new_type_id)]

        updates = {'status': 'retyping',
                   'previous_status': objects.Volume.model.status}

        if not volume.conditional_update(updates, expected, filters):
            msg = _('Retype needs volume to be in available or in-use state, '
                    'not be part of an active migration or a consistency '
                    'group, requested type has to be different that the '
                    'one from the volume, and for in-use volumes front-end '
                    'qos specs cannot change.')
            LOG.error(msg)
            QUOTAS.rollback(context, reservations + old_reservations,
                            project_id=volume.project_id)
            raise exception.InvalidVolume(reason=msg)

        request_spec = {'volume_properties': volume,
                        'volume_id': volume.id,
                        'volume_type': new_type,
                        'migration_policy': migration_policy,
                        'quota_reservations': reservations,
                        'old_reservations': old_reservations}

        type_azs = volume_utils.extract_availability_zones_from_volume_type(
            new_type)
        if type_azs is not None:
            request_spec['availability_zones'] = type_azs
        else:
            request_spec['availability_zones'] = [volume.availability_zone]

        self.scheduler_rpcapi.retype(context, volume,
                                     request_spec=request_spec,
                                     filter_properties={})
        volume.multiattach = tgt_is_multiattach
        volume.save()
        LOG.info("Retype volume request issued successfully.",
                 resource=volume)

    def _get_service_by_host_cluster(
            self,
            context: context.RequestContext,
            host: str,
            cluster_name: Optional[str],
            resource: str = 'volume') -> objects.Service:
        elevated = context.elevated()

        svc_cluster = cluster_name and volume_utils.extract_host(cluster_name,
                                                                 'backend')
        svc_host = host and volume_utils.extract_host(host, 'backend')

        # NOTE(geguileo): Only svc_host or svc_cluster is set, so when we get
        # a service from the DB we are getting either one specific service from
        # a host or any service that is up from a cluster, which means that the
        # cluster itself is also up.
        try:
            service = objects.Service.get_by_id(elevated, None, host=svc_host,
                                                binary=constants.VOLUME_BINARY,
                                                cluster_name=svc_cluster)
        except exception.ServiceNotFound:
            with excutils.save_and_reraise_exception():
                LOG.error('Unable to find service: %(service)s for '
                          'given host: %(host)s and cluster %(cluster)s.',
                          {'service': constants.VOLUME_BINARY, 'host': host,
                           'cluster': cluster_name})

        if service.disabled and (not service.cluster_name or
                                 service.cluster.disabled):
            LOG.error('Unable to manage existing %s on a disabled '
                      'service.', resource)
            raise exception.ServiceUnavailable()

        if not service.is_up:
            LOG.error('Unable to manage existing %s on a service that is '
                      'down.', resource)
            raise exception.ServiceUnavailable()

        return service

    def manage_existing(self,
                        context: context.RequestContext,
                        host: str,
                        cluster_name: Optional[str],
                        ref: dict,
                        name: Optional[str] = None,
                        description: Optional[str] = None,
                        volume_type: Optional[objects.VolumeType] = None,
                        metadata: Optional[dict] = None,
                        availability_zone: Optional[str] = None,
                        bootable: Optional[bool] = False) -> objects.Volume:

        if 'source-name' in ref:
            vol_id = volume_utils.extract_id_from_volume_name(
                ref['source-name'])
            if vol_id and volume_utils.check_already_managed_volume(vol_id):
                raise exception.InvalidVolume(
                    _("Unable to manage existing volume."
                      " The volume is already managed"))
        if not volume_type:
            try:
                volume_type = volume_types.get_default_volume_type(context)
            except exception.VolumeTypeDefaultMisconfiguredError:
                LOG.error('Default volume type not found. This must be '
                          'corrected immediately or all volume-create '
                          'requests that do not specify a volume type '
                          'will fail.')
                raise
        is_encrypted = False
        if volume_type:
            is_encrypted = self._is_encrypted(volume_type)
        if is_encrypted:
            msg = _("Managing to an encrypted volume type is not supported.")
            LOG.error(msg)
            raise exception.InvalidVolumeType(msg)

        if volume_type and 'extra_specs' not in volume_type:
            extra_specs = volume_types.get_volume_type_extra_specs(
                volume_type['id'])
            volume_type['extra_specs'] = extra_specs

        service = self._get_service_by_host_cluster(context, host,
                                                    cluster_name)

        if availability_zone is None:
            availability_zone = service.availability_zone

        if not cluster_name and bool(volume_utils.extract_host(host, 'pool')):
            manage_host = host
        else:
            manage_host = service.host

        manage_what = {
            'context': context,
            'name': name,
            'description': description,
            'host': manage_host,
            'cluster_name': service.cluster_name,
            'ref': ref,
            'volume_type': volume_type,
            'metadata': metadata,
            'availability_zone': availability_zone,
            'bootable': bootable,
            'size': 0,
            'group_snapshot': None,
            'optional_args': {'is_quota_committed': False},
            'volume_type_id': None if not volume_type else volume_type['id'],
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
            LOG.info("Manage volume request issued successfully.",
                     resource=vol_ref)
            return vol_ref

    def get_manageable_volumes(self,
                               context: context.RequestContext,
                               host: str,
                               cluster_name,
                               marker: Optional[str] = None,
                               limit: Optional[int] = None,
                               offset: Optional[int] = None,
                               sort_keys: Optional[list[str]] = None,
                               sort_dirs: Optional[list[str]] = None):
        svc = self._get_service_by_host_cluster(context, host, cluster_name)
        return self.volume_rpcapi.get_manageable_volumes(context, svc,
                                                         marker, limit,
                                                         offset, sort_keys,
                                                         sort_dirs)

    def manage_existing_snapshot(
            self,
            context: context.RequestContext,
            ref: dict,
            volume: objects.Volume,
            name: Optional[str] = None,
            description: Optional[str] = None,
            metadata: Optional[dict] = None) -> objects.Snapshot:
        # Ensure the service is up and not disabled.
        self._get_service_by_host_cluster(context, volume.host,
                                          volume.cluster_name,
                                          'snapshot')

        snapshot_object = self.create_snapshot_in_db(context, volume, name,
                                                     description, True,
                                                     metadata, None,
                                                     commit_quota=True)
        kwargs = {'snapshot_id': snapshot_object.id,
                  'volume_properties':
                      objects.VolumeProperties(size=volume.size)}
        self.scheduler_rpcapi.manage_existing_snapshot(
            context, volume, snapshot_object, ref,
            request_spec=objects.RequestSpec(**kwargs))
        return snapshot_object

    def get_manageable_snapshots(
            self,
            context: context.RequestContext,
            host: str,
            cluster_name: Optional[str],
            marker: Optional[str] = None,
            limit: Optional[int] = None,
            offset: Optional[int] = None,
            sort_keys: Optional[list[str]] = None,
            sort_dirs: Optional[list[str]] = None) -> list[dict]:
        svc = self._get_service_by_host_cluster(context, host, cluster_name,
                                                'snapshot')
        return self.volume_rpcapi.get_manageable_snapshots(context, svc,
                                                           marker, limit,
                                                           offset, sort_keys,
                                                           sort_dirs)

    def _get_cluster_and_services_for_replication(
            self,
            ctxt: context.RequestContext,
            host: str,
            cluster_name: str) -> tuple:
        services = objects.ServiceList.get_all(
            ctxt, filters={'host': host, 'cluster_name': cluster_name,
                           'binary': constants.VOLUME_BINARY})

        if not services:
            if host:
                msg = _("No service found with host=%s") % host
            else:
                msg = _("No service found with cluster=%s") % cluster_name

            raise exception.ServiceNotFound(msg)

        cluster = services[0].cluster
        # Check that the host or cluster we received only results in 1 host or
        # hosts from the same cluster.
        if cluster_name:
            check_attribute = 'cluster_name'
            expected = cluster.name
        else:
            check_attribute = 'host'
            expected = services[0].host
        if any(getattr(s, check_attribute) != expected for s in services):
            msg = _('Services from different clusters found.')
            raise exception.InvalidParameterValue(msg)

        # If we received host parameter but host belongs to a cluster we have
        # to change all the services in the cluster, not just one host
        if host and cluster:
            services = cluster.services

        return cluster, services

    def _replication_db_change(self,
                               ctxt: context.RequestContext,
                               field: str,
                               expected_value: Union[bool, list],
                               new_value: Union[bool, str],
                               host: str,
                               cluster_name: str,
                               check_up: bool = False) -> tuple:
        def _error_msg(service) -> str:
            expected = utils.build_or_str(str(expected_value))
            up_msg = 'and must be up ' if check_up else ''
            msg = (_('%(field)s in %(service)s must be %(expected)s '
                     '%(up_msg)sto failover.')
                   % {'field': field, 'service': service,
                      'expected': expected, 'up_msg': up_msg})
            LOG.error(msg)
            return msg

        cluster, services = self._get_cluster_and_services_for_replication(
            ctxt, host, cluster_name)

        expect = {field: expected_value}
        change = {field: new_value}

        if cluster:
            old_value = getattr(cluster, field)
            if ((check_up and not cluster.is_up)
                    or not cluster.conditional_update(change, expect)):
                msg = _error_msg(cluster.name)
                raise exception.InvalidInput(reason=msg)

        changed = []
        not_changed = []
        for service in services:
            if ((not check_up or service.is_up)
                    and service.conditional_update(change, expect)):
                changed.append(service)
            else:
                not_changed.append(service)

        # If there were some services that couldn't be changed we should at
        # least log the error.
        if not_changed:
            msg = _error_msg([s.host for s in not_changed])
            # If we couldn't change any of the services
            if not changed:
                # Undo the cluster change
                if cluster:
                    setattr(cluster, field, old_value)
                    cluster.save()
                raise exception.InvalidInput(
                    reason=_('No service could be changed: %s') % msg)
            LOG.warning('Some services could not be changed: %s', msg)

        return cluster, services

    def failover(self,
                 ctxt: context.RequestContext,
                 host: str,
                 cluster_name: str,
                 secondary_id: Optional[str] = None) -> None:
        ctxt.authorize(svr_policy.FAILOVER_POLICY)
        ctxt = ctxt if ctxt.is_admin else ctxt.elevated()

        # TODO(geguileo): In P - Remove this version check
        rpc_version = self.volume_rpcapi.determine_rpc_version_cap()
        rpc_version = versionutils.convert_version_to_tuple(rpc_version)
        if cluster_name and rpc_version < (3, 5):
            msg = _('replication operations with cluster field')
            raise exception.UnavailableDuringUpgrade(action=msg)

        rep_fields = fields.ReplicationStatus
        expected_values = [rep_fields.ENABLED, rep_fields.FAILED_OVER]
        new_value = rep_fields.FAILING_OVER

        cluster, services = self._replication_db_change(
            ctxt, 'replication_status', expected_values, new_value, host,
            cluster_name, check_up=True)

        self.volume_rpcapi.failover(ctxt, services[0], secondary_id)

    def freeze_host(self,
                    ctxt: context.RequestContext,
                    host: str,
                    cluster_name: str) -> None:
        ctxt.authorize(svr_policy.FREEZE_POLICY)
        ctxt = ctxt if ctxt.is_admin else ctxt.elevated()

        expected = False
        new_value = True
        cluster, services = self._replication_db_change(
            ctxt, 'frozen', expected, new_value, host, cluster_name,
            check_up=False)

        # Should we set service status to disabled to keep
        # scheduler calls from being sent? Just use existing
        # `cinder service-disable reason=freeze`
        self.volume_rpcapi.freeze_host(ctxt, services[0])

    def thaw_host(self,
                  ctxt: context.RequestContext,
                  host: str,
                  cluster_name: str) -> Optional[str]:
        ctxt.authorize(svr_policy.THAW_POLICY)
        ctxt = ctxt if ctxt.is_admin else ctxt.elevated()

        expected = True
        new_value = False
        cluster, services = self._replication_db_change(
            ctxt, 'frozen', expected, new_value, host, cluster_name,
            check_up=False)

        if not self.volume_rpcapi.thaw_host(ctxt, services[0]):
            return "Backend reported error during thaw_host operation."

        return None

    def check_volume_filters(self,
                             filters: dict,
                             strict: bool = False) -> None:
        """Sets the user filter value to accepted format"""
        booleans = self.db.get_booleans_for_table('volume')

        # To translate any true/false equivalent to True/False
        # which is only acceptable format in database queries.
        temp_dict = filters.copy()
        for key, val in temp_dict.items():
            try:
                if key in booleans:
                    filters[key] = self._check_boolean_filter_value(
                        key, val, strict)
                elif key == 'display_name':
                    # Use the raw value of display name as is for the filter
                    # without passing it through ast.literal_eval(). If the
                    # display name is a properly quoted string (e.g. '"foo"')
                    # then literal_eval() strips the quotes (i.e. 'foo'), so
                    # the filter becomes different from the user input.
                    continue
                else:
                    # this is required as ast.literal_eval(<int>/<float>)
                    # raises exception. Eg: ast.literal_eval(5) generates
                    # ValueError: malformed node or string: 5
                    if not isinstance(val, str):
                        val = str(val)
                    filters[key] = ast.literal_eval(val)
            except (ValueError, SyntaxError):
                LOG.debug('Could not evaluate value %s, assuming string', val)

    def _check_boolean_filter_value(self,
                                    key: str,
                                    val: str,
                                    strict: bool = False) -> bool:
        """Boolean filter values in Volume GET.

        Before VOLUME_LIST_BOOTABLE, all values other than 'False', 'false',
        'FALSE' were trated as True for specific boolean filter parameters in
        Volume GET request.

        But VOLUME_LIST_BOOTABLE onwards, only true/True/0/1/False/false
        parameters are supported.
        All other input values to specific boolean filter parameter will
        lead to raising exception.

        This changes API behavior. So, micro version introduced for
        VOLUME_LIST_BOOTABLE onwards.
        """
        if strict:
            # for updated behavior, from VOLUME_LIST_BOOTABLE onwards.
            # To translate any true/false/t/f/0/1 to True/False
            # which is only acceptable format in database queries.
            try:
                return strutils.bool_from_string(val, strict=True)
            except ValueError:
                msg = _('\'%(key)s = %(value)s\'') % {'key': key,
                                                      'value': val}
                raise exception.InvalidInput(reason=msg)
        else:
            # For existing behavior(before version VOLUME_LIST_BOOTABLE)
            accepted_true = ['True', 'true', 'TRUE']
            accepted_false = ['False', 'false', 'FALSE']

            if val in accepted_false:
                return False
            elif val in accepted_true:
                return True
            else:
                return bool(val)

    def _attachment_reserve(
            self,
            ctxt: context.RequestContext,
            vref: objects.Volume,
            instance_uuid: Optional[str] = None) -> objects.VolumeAttachment:
        # NOTE(jdg): Reserved is a special case, we're avoiding allowing
        # creation of other new reserves/attachments while in this state
        # so we avoid contention issues with shared connections

        # Multiattach of bootable volumes is a special case with it's own
        # policy, check that here right off the bat
        if (vref.get('multiattach', False) and
                vref.status == 'in-use' and
                vref.bootable):
            ctxt.authorize(
                attachment_policy.MULTIATTACH_BOOTABLE_VOLUME_POLICY,
                target_obj=vref)

        # FIXME(JDG):  We want to be able to do things here like reserve a
        # volume for Nova to do BFV WHILE the volume may be in the process of
        # downloading image, we add downloading here; that's easy enough but
        # we've got a race between with the attaching/detaching that we do
        # locally on the Cinder node.  Just come up with an easy way to
        # determine if we're attaching to the Cinder host for some work or if
        # we're being used by the outside world.
        expected = {'multiattach': vref.multiattach,
                    'status': (('available', 'in-use', 'downloading')
                               if vref.multiattach
                               else ('available', 'downloading'))}

        result = vref.conditional_update({'status': 'reserved'}, expected)

        if not result:
            override = False
            if instance_uuid and vref.status in ('in-use', 'reserved'):
                # Refresh the volume reference in case multiple instances were
                # being concurrently attached to the same non-multiattach
                # volume.
                vref = objects.Volume.get_by_id(ctxt, vref.id)
                for attachment in vref.volume_attachment:
                    # If we're attaching the same volume to the same instance,
                    # we could be migrating the instance to another host in
                    # which case we want to allow the reservation.
                    # (LP BUG: 1694530)
                    if attachment.instance_uuid == instance_uuid:
                        override = True
                        break

            if not override:
                msg = (_('Volume %(vol_id)s status must be %(statuses)s to '
                         'reserve, but the current status is %(current)s.') %
                       {'vol_id': vref.id,
                        'statuses': utils.build_or_str(expected['status']),
                        'current': vref.status})
                raise exception.InvalidVolume(reason=msg)

        values = {'volume_id': vref.id,
                  'volume_host': vref.host,
                  'attach_status': 'reserved',
                  'instance_uuid': instance_uuid}
        db_ref = self.db.volume_attach(ctxt.elevated(), values)
        return objects.VolumeAttachment.get_by_id(ctxt, db_ref['id'])

    def attachment_create(
            self,
            ctxt: context.RequestContext,
            volume_ref: objects.Volume,
            instance_uuid: str,
            connector: Optional[dict] = None,
            attach_mode: Optional[str] = 'null') -> objects.VolumeAttachment:
        """Create an attachment record for the specified volume."""
        ctxt.authorize(attachment_policy.CREATE_POLICY, target_obj=volume_ref)
        connection_info = {}
        if "error" in volume_ref.status:
            msg = ('Volume attachments can not be created if the volume '
                   'is in an error state. '
                   'The Volume %(volume_id)s currently has a status of: '
                   '%(volume_status)s ') % {
                       'volume_id': volume_ref.id,
                       'volume_status': volume_ref.status}
            LOG.error(msg)
            raise exception.InvalidVolume(reason=msg)
        attachment_ref = self._attachment_reserve(ctxt,
                                                  volume_ref,
                                                  instance_uuid)
        if connector:
            connection_info = (
                self.volume_rpcapi.attachment_update(ctxt,
                                                     volume_ref,
                                                     connector,
                                                     attachment_ref.id))
        attachment_ref.connection_info = connection_info

        # Use of admin_metadata for RO settings is deprecated
        # switch to using mode argument to attachment-create
        if self.db.volume_admin_metadata_get(
                ctxt.elevated(),
                volume_ref['id']).get('readonly', False):
            LOG.warning("Using volume_admin_metadata to set "
                        "Read Only mode is deprecated!  Please "
                        "use the mode argument in attachment-create.")
            attachment_ref.attach_mode = 'ro'
            # for now we have to let the admin_metadata override
            # so we're using an else in the next step here, in
            # other words, using volume_admin_metadata and mode params
            # are NOT compatible
        else:
            attachment_ref.attach_mode = attach_mode

        attachment_ref.save()
        return attachment_ref

    @coordination.synchronized(
        '{f_name}-{attachment_ref.volume_id}-{connector[host]}')
    def attachment_update(self,
                          ctxt: context.RequestContext,
                          attachment_ref: objects.VolumeAttachment,
                          connector) -> objects.VolumeAttachment:
        """Update an existing attachment record."""
        # Valid items to update (connector includes mode and mountpoint):
        #   1. connector (required)
        #     a. mode (if None use value from attachment_ref)
        #     b. mountpoint (if None use value from attachment_ref)
        #     c. instance_uuid(if None use value from attachment_ref)

        # This method has a synchronized() lock on the volume id
        # because we have to prevent race conditions around checking
        # for duplicate attachment requests to the same host.

        # We fetch the volume object and pass it to the rpc call because we
        # need to direct this to the correct host/backend

        ctxt.authorize(attachment_policy.UPDATE_POLICY,
                       target_obj=attachment_ref)
        volume_ref = objects.Volume.get_by_id(ctxt, attachment_ref.volume_id)
        if "error" in volume_ref.status:
            msg = ('Volume attachments can not be updated if the volume '
                   'is in an error state. The Volume %(volume_id)s '
                   'currently has a status of: %(volume_status)s ') % {
                       'volume_id': volume_ref.id,
                       'volume_status': volume_ref.status}
            LOG.error(msg)
            raise exception.InvalidVolume(reason=msg)

        if (len(volume_ref.volume_attachment) > 1 and
            not (volume_ref.multiattach or
                 self._is_multiattach(volume_ref.volume_type))):
            # Check whether all connection hosts are unique
            # Multiple attachments to different hosts is permitted to
            # support Nova instance migration.

            # This particular check also does not prevent multiple attachments
            # for a multiattach volume to the same instance.

            connection_hosts = set(a.connector['host']
                                   for a in volume_ref.volume_attachment
                                   if a.connection_info)

            if len(connection_hosts) > 0:
                # We raced, and have more than one connection

                msg = _('duplicate connectors detected on volume '
                        '%(vol)s') % {'vol': volume_ref.id}

                raise exception.InvalidVolume(reason=msg)

        connection_info = (
            self.volume_rpcapi.attachment_update(ctxt,
                                                 volume_ref,
                                                 connector,
                                                 attachment_ref.id))
        attachment_ref.connection_info = connection_info
        attachment_ref.save()
        return attachment_ref

    def attachment_deletion_allowed(self,
                                    ctxt: context.RequestContext,
                                    attachment_or_attachment_id,
                                    volume=None):
        """Check if deleting an attachment is allowed (Bug #2004555)

        Allowed is based on the REST API policy, the status of the attachment,
        where it is used, and who is making the request.

        Deleting an attachment on the Cinder side while leaving the volume
        connected to the nova host results in leftover devices that can lead to
        data leaks/corruption.

        OS-Brick may have code to detect it, but in some cases it is detected
        after it has already been exposed, so it's better to prevent users from
        being able to intentionally triggering the issue.
        """
        # It's ok to delete an attachment if the request comes from a service
        if self.is_service_request(ctxt):
            return

        if not attachment_or_attachment_id and volume:
            if not volume.volume_attachment:
                return
            if len(volume.volume_attachment) == 1:
                attachment_or_attachment_id = volume.volume_attachment[0]

        if isinstance(attachment_or_attachment_id, str):
            try:
                attachment = objects.VolumeAttachment.get_by_id(
                    ctxt, attachment_or_attachment_id)
            except exception.VolumeAttachmentNotFound:
                attachment = None
        else:
            attachment = attachment_or_attachment_id

        if attachment:
            if volume:
                if volume.id != attachment.volume_id:
                    raise exception.InvalidInput(
                        reason='Mismatched volume and attachment')

            server_id = attachment.instance_uuid
            # It's ok to delete if it's not connected to a vm.
            if not server_id or not attachment.connection_info:
                return

            volume = volume or attachment.volume
            nova = compute.API()
            LOG.info('Attachment connected to vm %s, checking data on nova',
                     server_id)
            # If nova is down the client raises 503 and we report that
            try:
                nova_volume = nova.get_server_volume(ctxt, server_id,
                                                     volume.id)
            except nova.NotFound:
                LOG.warning('Instance or volume not found on Nova, deleting '
                            'attachment locally, which may leave leftover '
                            'devices on Nova compute')
                return

            if nova_volume.attachment_id != attachment.id:
                LOG.warning('Mismatch! Nova has different attachment id (%s) '
                            'for the volume, deleting attachment locally. '
                            'May leave leftover devices in a compute node',
                            nova_volume.attachment_id)
                return
        else:
            server_id = ''

        LOG.error('Detected user call to delete in-use attachment. Call must '
                  'come from the nova service and nova must be configured to '
                  'send the service token. Bug #2004555')
        raise exception.ConflictNovaUsingAttachment(instance_id=server_id)

    def attachment_delete(self,
                          ctxt: context.RequestContext,
                          attachment) -> objects.VolumeAttachmentList:
        # Check if policy allows user to delete attachment
        ctxt.authorize(attachment_policy.DELETE_POLICY,
                       target_obj=attachment)

        self.attachment_deletion_allowed(ctxt, attachment)

        volume = attachment.volume

        if attachment.attach_status == fields.VolumeAttachStatus.RESERVED:
            volume_utils.notify_about_volume_usage(ctxt,
                                                   volume, "detach.start")
        else:
            # Generate the detach.start notification on the volume service to
            # include the host doing the operation.
            self.volume_rpcapi.attachment_delete(ctxt, attachment.id, volume)

        # Trigger attachments lazy load (missing since volume was loaded in the
        # attachment without joined tables). With them loaded the finish_detach
        # call removes the detached one from the list, and the notification and
        # return have the right attachment list.
        volume.volume_attachment
        volume.finish_detach(attachment.id)

        # Do end notification on the API so it comes after finish_detach.
        # Doing it on the volume service leads to race condition from bug
        # #1937084, and doing the notification there with the finish here leads
        # to bug #1916980.
        volume_utils.notify_about_volume_usage(ctxt, volume, "detach.end")
        return volume.volume_attachment

    def reimage(self, context, volume, image_id, reimage_reserved=False,
                image_snap=None):
        if volume.status in ['reserved']:
            context.authorize(vol_action_policy.REIMAGE_RESERVED_POLICY,
                              target_obj=volume)
        else:
            context.authorize(vol_action_policy.REIMAGE_POLICY,
                              target_obj=volume)
        if len(volume.volume_attachment) > 1:
            msg = _("Cannot re-image a volume which is attached to more than "
                    "one server.")
            raise webob.exc.HTTPConflict(explanation=msg)
        # Build required conditions for conditional update
        expected = {'status': ('available', 'error', 'reserved'
                               ) if reimage_reserved else ('available',
                                                           'error')}
        values = {'status': 'downloading',
                  'previous_status': volume.model.status}

        result = volume.conditional_update(values, expected)
        if not result:
            msg = (_('Volume %(vol_id)s status must be %(statuses)s, but '
                     'current status is %(status)s.') %
                   {'vol_id': volume.id,
                    'statuses': utils.build_or_str(expected['status']),
                    'status': volume.status})
            raise exception.InvalidVolume(reason=msg)
        image_meta = self.image_service.show(context, image_id)
        try:
            # If the source of the image is a volume snapshot
            # (image_snap is not None), we will get image 'size' as 0 and
            # 'virtual_size' as None but at least we will verify the image
            # 'status' and 'min_disk' properties.
            volume_utils.check_image_metadata(image_meta, volume['size'])
        # Currently we only raise InvalidInput and ImageUnacceptable
        # exceptions in the check_image_metadata call but having Exception
        # here makes it more generic since we want to roll back to original
        # state in any case and we re-raise anyway.
        # Also this helps makes adding new exceptions easier in the future.
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception("Failed to reimage volume %(volume_id)s "
                              "with image %(image_id)s",
                              {'volume_id': volume.id,
                               'image_id': image_id})
                volume.conditional_update(
                    {'status': volume.model.previous_status,
                     'previous_status': None},
                    {'status': 'downloading'})
        self.volume_rpcapi.reimage(context,
                                   volume,
                                   image_meta,
                                   image_snap=image_snap)


class HostAPI(base.Base):
    """Sub-set of the Volume Manager API for managing host operations."""

    def set_host_enabled(self, context, host, enabled):
        """Sets the specified host's ability to accept new volumes."""
        raise NotImplementedError()
