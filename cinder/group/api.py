# Copyright (C) 2016 EMC Corporation.
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
Handles all requests relating to groups.
"""


from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import timeutils
from oslo_utils import uuidutils

from cinder import db
from cinder.db import base
from cinder import exception
from cinder.i18n import _
from cinder import objects
from cinder.objects import fields as c_fields
from cinder.policies import group_actions as gp_action_policy
from cinder.policies import group_snapshot_actions as gsnap_action_policy
from cinder.policies import group_snapshots as gsnap_policy
from cinder.policies import groups as group_policy
from cinder import quota
from cinder import quota_utils
from cinder.scheduler import rpcapi as scheduler_rpcapi
from cinder.volume import api as volume_api
from cinder.volume import rpcapi as volume_rpcapi
from cinder.volume import volume_types
from cinder.volume import volume_utils


CONF = cfg.CONF

LOG = logging.getLogger(__name__)
GROUP_QUOTAS = quota.GROUP_QUOTAS
VALID_REMOVE_VOL_FROM_GROUP_STATUS = (
    'available',
    'in-use',
    'error',
    'error_deleting')
VALID_ADD_VOL_TO_GROUP_STATUS = (
    'available',
    'in-use')


class API(base.Base):
    """API for interacting with the volume manager for groups."""

    def __init__(self):
        self.scheduler_rpcapi = scheduler_rpcapi.SchedulerAPI()
        self.volume_rpcapi = volume_rpcapi.VolumeAPI()
        self.volume_api = volume_api.API()

        super().__init__()

    def _extract_availability_zone(self, availability_zone):
        raw_zones = self.volume_api.list_availability_zones(enable_cache=True)
        availability_zones = set([az['name'] for az in raw_zones])
        if CONF.storage_availability_zone:
            availability_zones.add(CONF.storage_availability_zone)

        if availability_zone is None:
            if CONF.default_availability_zone:
                availability_zone = CONF.default_availability_zone
            else:
                # For backwards compatibility use the storage_availability_zone
                availability_zone = CONF.storage_availability_zone

        if availability_zone not in availability_zones:
            if CONF.allow_availability_zone_fallback:
                original_az = availability_zone
                availability_zone = (
                    CONF.default_availability_zone or
                    CONF.storage_availability_zone)
                LOG.warning("Availability zone '%(s_az)s' not found, falling "
                            "back to '%(s_fallback_az)s'.",
                            {'s_az': original_az,
                             's_fallback_az': availability_zone})
            else:
                msg = _("Availability zone '%(s_az)s' is invalid.")
                msg = msg % {'s_az': availability_zone}
                raise exception.InvalidInput(reason=msg)

        return availability_zone

    def _update_volumes_host(self, context, group):
        volumes = objects.VolumeList.get_all_by_generic_group(context,
                                                              group.id)
        for vol in volumes:
            # Update the host field for the volume.
            vol.host = group.host
            vol.cluster_name = group.cluster_name
            vol.save()

    def create(self, context, name, description, group_type,
               volume_types, availability_zone=None):
        context.authorize(group_policy.CREATE_POLICY)

        req_volume_types = []
        # NOTE: Admin context is required to get extra_specs of volume_types.
        req_volume_types = (self.db.volume_types_get_by_name_or_id(
            context.elevated(), volume_types))

        if not uuidutils.is_uuid_like(group_type):
            req_group_type = self.db.group_type_get_by_name(context,
                                                            group_type)
        else:
            try:
                req_group_type = self.db.group_type_get(context, group_type)
            except exception.GroupTypeNotFound:
                # check again if we get this group type by uuid-like name
                try:
                    req_group_type = self.db.group_type_get_by_name(
                        context, group_type)
                except exception.GroupTypeNotFoundByName:
                    raise exception.GroupTypeNotFound(group_type_id=group_type)

        availability_zone = self._extract_availability_zone(availability_zone)
        kwargs = {'user_id': context.user_id,
                  'project_id': context.project_id,
                  'availability_zone': availability_zone,
                  'status': c_fields.GroupStatus.CREATING,
                  'name': name,
                  'description': description,
                  'volume_type_ids': [t['id'] for t in req_volume_types],
                  'group_type_id': req_group_type['id'],
                  'replication_status': c_fields.ReplicationStatus.DISABLED}
        try:
            reservations = GROUP_QUOTAS.reserve(context,
                                                project_id=context.project_id,
                                                groups=1)
        except exception.OverQuota as e:
            quota_utils.process_reserve_over_quota(context, e,
                                                   resource='groups')
        group = None
        try:
            group = objects.Group(context=context, **kwargs)
            group.create()
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error("Error occurred when creating group"
                          " %s.", name)
                GROUP_QUOTAS.rollback(context, reservations)

        request_spec_list = []
        filter_properties_list = []
        for req_volume_type in req_volume_types:
            request_spec = {'volume_type': req_volume_type.copy(),
                            'group_id': group.id}
            filter_properties = {}
            request_spec_list.append(request_spec)
            filter_properties_list.append(filter_properties)

        group_spec = {'group_type': req_group_type.copy(),
                      'group_id': group.id}
        group_filter_properties = {}

        # Update quota for groups
        GROUP_QUOTAS.commit(context, reservations)

        self._cast_create_group(context, group,
                                group_spec,
                                request_spec_list,
                                group_filter_properties,
                                filter_properties_list)

        return group

    def create_from_src(self, context, name, description=None,
                        group_snapshot_id=None, source_group_id=None):
        context.authorize(group_policy.CREATE_POLICY)

        # Populate group_type_id and volume_type_ids
        group_type_id = None
        volume_type_ids = []
        size = 0
        if group_snapshot_id:
            grp_snap = self.get_group_snapshot(context, group_snapshot_id)
            group_type_id = grp_snap.group_type_id
            grp_snap_src_grp = self.get(context, grp_snap.group_id)
            volume_type_ids = [vt.id for vt in grp_snap_src_grp.volume_types]
            snapshots = objects.SnapshotList.get_all_for_group_snapshot(
                context, group_snapshot_id)
            size = sum(s.volume.size for s in snapshots)
        elif source_group_id:
            source_group = self.get(context, source_group_id)
            group_type_id = source_group.group_type_id
            volume_type_ids = [vt.id for vt in source_group.volume_types]
            source_vols = objects.VolumeList.get_all_by_generic_group(
                context, source_group.id)
            size = sum(v.size for v in source_vols)

        kwargs = {
            'user_id': context.user_id,
            'project_id': context.project_id,
            'status': c_fields.GroupStatus.CREATING,
            'name': name,
            'description': description,
            'group_snapshot_id': group_snapshot_id,
            'source_group_id': source_group_id,
            'group_type_id': group_type_id,
            'volume_type_ids': volume_type_ids,
            'replication_status': c_fields.ReplicationStatus.DISABLED
        }
        try:
            reservations = GROUP_QUOTAS.reserve(context,
                                                project_id=context.project_id,
                                                groups=1)
        except exception.OverQuota as e:
            quota_utils.process_reserve_over_quota(context, e,
                                                   resource='groups')
        group = None
        try:
            group = objects.Group(context=context, **kwargs)
            group.create(group_snapshot_id=group_snapshot_id,
                         source_group_id=source_group_id)
        except exception.GroupNotFound:
            with excutils.save_and_reraise_exception():
                LOG.error("Source Group %(source_group)s not found when "
                          "creating group %(group)s from source.",
                          {'group': name, 'source_group': source_group_id})
                GROUP_QUOTAS.rollback(context, reservations)
        except exception.GroupSnapshotNotFound:
            with excutils.save_and_reraise_exception():
                LOG.error("Group snapshot %(group_snap)s not found when "
                          "creating group %(group)s from source.",
                          {'group': name, 'group_snap': group_snapshot_id})
                GROUP_QUOTAS.rollback(context, reservations)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error("Error occurred when creating group"
                          " %(group)s from group_snapshot %(grp_snap)s.",
                          {'group': name, 'grp_snap': group_snapshot_id})
                GROUP_QUOTAS.rollback(context, reservations)

        # Update quota for groups
        GROUP_QUOTAS.commit(context, reservations)

        # NOTE(tommylikehu): We wrap the size inside of the attribute
        # 'volume_properties' as scheduler's filter logic are all designed
        # based on this attribute.
        kwargs = {'group_id': group.id,
                  'volume_properties': objects.VolumeProperties(size=size)}

        host = group.resource_backend
        if not host or not self.scheduler_rpcapi.validate_host_capacity(
                context, host, objects.RequestSpec(**kwargs)):
            msg = _("No valid host to create group %s.") % group.id
            LOG.error(msg)
            raise exception.InvalidGroup(reason=msg)

        group.assert_not_frozen()

        if group_snapshot_id:
            self._create_group_from_group_snapshot(context, group,
                                                   group_snapshot_id)
        elif source_group_id:
            self._create_group_from_source_group(context, group,
                                                 source_group_id)

        return group

    def _create_group_from_group_snapshot(self, context, group,
                                          group_snapshot_id):
        try:
            group_snapshot = objects.GroupSnapshot.get_by_id(
                context, group_snapshot_id)
            snapshots = objects.SnapshotList.get_all_for_group_snapshot(
                context, group_snapshot.id)

            if not snapshots:
                msg = _("Group snapshot is empty. No group will be created.")
                raise exception.InvalidGroup(reason=msg)

            for snapshot in snapshots:
                kwargs = {}
                kwargs['availability_zone'] = group.availability_zone
                kwargs['group_snapshot'] = group_snapshot
                kwargs['group'] = group
                kwargs['snapshot'] = snapshot
                volume_type_id = snapshot.volume_type_id
                if volume_type_id:
                    kwargs['volume_type'] = (
                        objects.VolumeType.get_by_name_or_id(
                            context, volume_type_id))
                    # Create group volume_type mapping entries
                    try:
                        db.group_volume_type_mapping_create(context, group.id,
                                                            volume_type_id)
                    except exception.GroupVolumeTypeMappingExists:
                        # Only need to create one group volume_type mapping
                        # entry for the same combination, skipping.
                        LOG.info("A mapping entry already exists for group"
                                 " %(grp)s and volume type %(vol_type)s. "
                                 "Do not need to create again.",
                                 {'grp': group.id,
                                  'vol_type': volume_type_id})

                # Since group snapshot is passed in, the following call will
                # create a db entry for the volume, but will not call the
                # volume manager to create a real volume in the backend yet.
                # If error happens, taskflow will handle rollback of quota
                # and removal of volume entry in the db.
                try:
                    self.volume_api.create(context,
                                           snapshot.volume_size,
                                           None,
                                           None,
                                           **kwargs)
                except exception.CinderException:
                    with excutils.save_and_reraise_exception():
                        LOG.error("Error occurred when creating volume "
                                  "entry from snapshot in the process of "
                                  "creating group %(group)s "
                                  "from group snapshot %(group_snap)s.",
                                  {'group': group.id,
                                   'group_snap': group_snapshot.id})
        except Exception:
            with excutils.save_and_reraise_exception():
                try:
                    volumes = objects.VolumeList.get_all_by_generic_group(
                        context, group.id)
                    for vol in volumes:
                        # NOTE(tommylikehu): `delete` is used here in order to
                        # revert consumed quota.
                        self.volume_api.delete(context, vol)
                    group.destroy()
                finally:
                    LOG.error("Error occurred when creating group "
                              "%(group)s from group snapshot %(group_snap)s.",
                              {'group': group.id,
                               'group_snap': group_snapshot.id})

        self._update_volumes_host(context, group)

        self.volume_rpcapi.create_group_from_src(
            context, group, group_snapshot)

    def _create_group_from_source_group(self, context, group,
                                        source_group_id):
        try:
            source_group = objects.Group.get_by_id(context,
                                                   source_group_id)
            source_vols = objects.VolumeList.get_all_by_generic_group(
                context, source_group.id)

            if not source_vols:
                msg = _("Source Group is empty. No group "
                        "will be created.")
                raise exception.InvalidGroup(reason=msg)

            for source_vol in source_vols:
                kwargs = {}
                kwargs['availability_zone'] = group.availability_zone
                kwargs['source_group'] = source_group
                kwargs['group'] = group
                kwargs['source_volume'] = source_vol
                volume_type_id = source_vol.volume_type_id
                if volume_type_id:
                    kwargs['volume_type'] = (
                        objects.VolumeType.get_by_name_or_id(
                            context, volume_type_id))
                    # Create group volume_type mapping entries
                    try:
                        db.group_volume_type_mapping_create(context, group.id,
                                                            volume_type_id)
                    except exception.GroupVolumeTypeMappingExists:
                        # Only need to create one group volume_type mapping
                        # entry for the same combination, skipping.
                        LOG.info("A mapping entry already exists for group"
                                 " %(grp)s and volume type %(vol_type)s. "
                                 "Do not need to create again.",
                                 {'grp': group.id,
                                  'vol_type': volume_type_id})

                # Since source_group is passed in, the following call will
                # create a db entry for the volume, but will not call the
                # volume manager to create a real volume in the backend yet.
                # If error happens, taskflow will handle rollback of quota
                # and removal of volume entry in the db.
                try:
                    self.volume_api.create(context,
                                           source_vol.size,
                                           None,
                                           None,
                                           **kwargs)
                except exception.CinderException:
                    with excutils.save_and_reraise_exception():
                        LOG.error("Error occurred when creating cloned "
                                  "volume in the process of creating "
                                  "group %(group)s from "
                                  "source group %(source_group)s.",
                                  {'group': group.id,
                                   'source_group': source_group.id})
        except Exception:
            with excutils.save_and_reraise_exception():
                try:
                    volumes = objects.VolumeList.get_all_by_generic_group(
                        context, group.id)
                    for vol in volumes:
                        # NOTE(tommylikehu): `delete` is used here in order to
                        # revert consumed quota.
                        self.volume_api.delete(context, vol)
                    group.destroy()
                finally:
                    LOG.error("Error occurred when creating "
                              "group %(group)s from source group "
                              "%(source_group)s.",
                              {'group': group.id,
                               'source_group': source_group.id})

        self._update_volumes_host(context, group)

        self.volume_rpcapi.create_group_from_src(context, group,
                                                 None, source_group)

    def _cast_create_group(self, context, group,
                           group_spec,
                           request_spec_list,
                           group_filter_properties,
                           filter_properties_list):

        try:
            for request_spec in request_spec_list:
                volume_type = request_spec.get('volume_type')
                volume_type_id = None
                if volume_type:
                    volume_type_id = volume_type.get('id')

                specs = {}
                if volume_type_id:
                    qos_specs = volume_types.get_volume_type_qos_specs(
                        volume_type_id)
                    specs = qos_specs['qos_specs']
                if not specs:
                    # to make sure we don't pass empty dict
                    specs = None

                volume_properties = {
                    'size': 0,  # Need to populate size for the scheduler
                    'user_id': context.user_id,
                    'project_id': context.project_id,
                    'status': 'creating',
                    'attach_status': 'detached',
                    'encryption_key_id': request_spec.get('encryption_key_id'),
                    'display_description': request_spec.get('description'),
                    'display_name': request_spec.get('name'),
                    'volume_type_id': volume_type_id,
                    'group_type_id': group.group_type_id,
                    'availability_zone': group.availability_zone
                }

                request_spec['volume_properties'] = volume_properties
                request_spec['qos_specs'] = specs

            group_properties = {
                'size': 0,  # Need to populate size for the scheduler
                'user_id': context.user_id,
                'project_id': context.project_id,
                'status': 'creating',
                'display_description': group_spec.get('description'),
                'display_name': group_spec.get('name'),
                'group_type_id': group.group_type_id,
            }

            group_spec['volume_properties'] = group_properties
            group_spec['qos_specs'] = None

        except Exception:
            with excutils.save_and_reraise_exception():
                try:
                    group.destroy()
                finally:
                    LOG.error("Error occurred when building request spec "
                              "list for group %s.", group.id)

        # Cast to the scheduler and let it handle whatever is needed
        # to select the target host for this group.
        self.scheduler_rpcapi.create_group(
            context,
            group,
            group_spec=group_spec,
            request_spec_list=request_spec_list,
            group_filter_properties=group_filter_properties,
            filter_properties_list=filter_properties_list)

    def update_quota(self, context, group, num, project_id=None):
        reserve_opts = {'groups': num}
        try:
            reservations = GROUP_QUOTAS.reserve(context,
                                                project_id=project_id,
                                                **reserve_opts)
            if reservations:
                GROUP_QUOTAS.commit(context, reservations)
        except Exception as e:
            with excutils.save_and_reraise_exception():
                try:
                    group.destroy()
                    if isinstance(e, exception.OverQuota):
                        quota_utils.process_reserve_over_quota(
                            context, e, resource='groups')
                finally:
                    LOG.error("Failed to update quota for group %s.", group.id)

    def delete(self, context, group, delete_volumes=False):
        context.authorize(gp_action_policy.DELETE_POLICY, target_obj=group)
        if not group.host:
            self.update_quota(context, group, -1, group.project_id)

            LOG.debug("No host for group %s. Deleting from "
                      "the database.", group.id)
            group.destroy()

            return

        group.assert_not_frozen()

        if not delete_volumes and group.status not in (
                [c_fields.GroupStatus.AVAILABLE,
                 c_fields.GroupStatus.ERROR]):
            msg = _("Group status must be available or error, "
                    "but current status is: %s") % group.status
            raise exception.InvalidGroup(reason=msg)

        # NOTE(tommylikehu): Admin context is required to load group snapshots.
        with group.obj_as_admin():
            if group.group_snapshots:
                raise exception.InvalidGroup(
                    reason=_("Group has existing snapshots."))

        # TODO(smcginnis): Add conditional update handling for volumes
        # Should probably utilize the volume_api.delete code to handle
        # cascade snapshot deletion and force delete.
        volumes = self.db.volume_get_all_by_generic_group(context.elevated(),
                                                          group.id)
        if volumes and not delete_volumes:
            msg = (_("Group %s still contains volumes. "
                     "The delete-volumes flag is required to delete it.")
                   % group.id)
            LOG.error(msg)
            raise exception.InvalidGroup(reason=msg)

        volumes_model_update = []
        for volume in volumes:
            if volume['attach_status'] == "attached":
                msg = _("Volume in group %s is attached. "
                        "Need to detach first.") % group.id
                LOG.error(msg)
                raise exception.InvalidGroup(reason=msg)

            snapshots = objects.SnapshotList.get_all_for_volume(context,
                                                                volume['id'])
            if snapshots:
                msg = _("Volume in group still has "
                        "dependent snapshots.")
                LOG.error(msg)
                raise exception.InvalidGroup(reason=msg)

            volumes_model_update.append({'id': volume['id'],
                                         'status': 'deleting'})

        self.db.volumes_update(context, volumes_model_update)

        if delete_volumes:
            # We're overloading the term "delete_volumes" somewhat to also
            # mean to delete the group regardless of the state.
            expected = {}
        else:
            expected = {'status': (c_fields.GroupStatus.AVAILABLE,
                                   c_fields.GroupStatus.ERROR)}
        filters = [~db.group_has_group_snapshot_filter(),
                   ~db.group_has_volumes_filter(
                       attached_or_with_snapshots=delete_volumes),
                   ~db.group_creating_from_src(group_id=group.id)]
        values = {'status': c_fields.GroupStatus.DELETING}

        if not group.conditional_update(values, expected, filters):
            if delete_volumes:
                reason = _('Group status must be available or error and must '
                           'not have dependent group snapshots')
            else:
                reason = _('Group must not have attached volumes, volumes '
                           'with snapshots, or dependent group snapshots')
            msg = _('Cannot delete group %(id)s. %(reason)s, and '
                    'it cannot be the source for an ongoing group or group '
                    'snapshot creation.') % {
                'id': group.id, 'reason': reason}
            raise exception.InvalidGroup(reason=msg)

        self.volume_rpcapi.delete_group(context, group)

    def update(self, context, group, name, description,
               add_volumes, remove_volumes):
        """Update group."""
        context.authorize(group_policy.UPDATE_POLICY, target_obj=group)
        # Validate name.
        if name == group.name:
            name = None

        # Validate description.
        if description == group.description:
            description = None

        add_volumes_list = []
        remove_volumes_list = []
        if add_volumes:
            add_volumes = add_volumes.strip(',')
            add_volumes_list = add_volumes.split(',')
        if remove_volumes:
            remove_volumes = remove_volumes.strip(',')
            remove_volumes_list = remove_volumes.split(',')

        invalid_uuids = []
        for uuid in add_volumes_list:
            if uuid in remove_volumes_list:
                invalid_uuids.append(uuid)
        if invalid_uuids:
            msg = _("UUIDs %s are in both add and remove volume "
                    "list.") % invalid_uuids
            raise exception.InvalidVolume(reason=msg)

        volumes = self.db.volume_get_all_by_generic_group(context, group.id)

        # Validate volumes in add_volumes and remove_volumes.
        add_volumes_new = ""
        remove_volumes_new = ""
        if add_volumes_list:
            add_volumes_new = self._validate_add_volumes(
                context, volumes, add_volumes_list, group)
        if remove_volumes_list:
            remove_volumes_new = self._validate_remove_volumes(
                volumes, remove_volumes_list, group)

        if (name is None and description is None and not add_volumes_new and
                not remove_volumes_new):
            msg = (_("Cannot update group %(group_id)s "
                     "because no valid name, description, add_volumes, "
                     "or remove_volumes were provided.") %
                   {'group_id': group.id})
            raise exception.InvalidGroup(reason=msg)

        expected = {}
        fields = {'updated_at': timeutils.utcnow()}

        # Update name and description in db now. No need to
        # to send them over through an RPC call.
        if name is not None:
            fields['name'] = name
        if description is not None:
            fields['description'] = description
        if not add_volumes_new and not remove_volumes_new:
            # Only update name or description. Set status to available.
            fields['status'] = c_fields.GroupStatus.AVAILABLE
        else:
            expected['status'] = c_fields.GroupStatus.AVAILABLE
            fields['status'] = c_fields.GroupStatus.UPDATING

        if not group.conditional_update(fields, expected):
            msg = _("Group status must be available.")
            raise exception.InvalidGroup(reason=msg)

        # Do an RPC call only if the update request includes
        # adding/removing volumes. add_volumes_new and remove_volumes_new
        # are strings of volume UUIDs separated by commas with no spaces
        # in between.
        if add_volumes_new or remove_volumes_new:
            self.volume_rpcapi.update_group(
                context, group,
                add_volumes=add_volumes_new,
                remove_volumes=remove_volumes_new)

    def _validate_remove_volumes(self, volumes, remove_volumes_list, group):
        # Validate volumes in remove_volumes.
        remove_volumes_new = ""
        for volume in volumes:
            if volume['id'] in remove_volumes_list:
                if volume['status'] not in VALID_REMOVE_VOL_FROM_GROUP_STATUS:
                    msg = (_("Cannot remove volume %(volume_id)s from "
                             "group %(group_id)s because volume "
                             "is in an invalid state: %(status)s. Valid "
                             "states are: %(valid)s.") %
                           {'volume_id': volume['id'],
                            'group_id': group.id,
                            'status': volume['status'],
                            'valid': VALID_REMOVE_VOL_FROM_GROUP_STATUS})
                    raise exception.InvalidVolume(reason=msg)
                # Volume currently in group. It will be removed from group.
                if remove_volumes_new:
                    remove_volumes_new += ","
                remove_volumes_new += volume['id']

        for rem_vol in remove_volumes_list:
            if rem_vol not in remove_volumes_new:
                msg = (_("Cannot remove volume %(volume_id)s from "
                         "group %(group_id)s because it "
                         "is not in the group.") %
                       {'volume_id': rem_vol,
                        'group_id': group.id})
                raise exception.InvalidVolume(reason=msg)

        return remove_volumes_new

    def _validate_add_volumes(self, context, volumes, add_volumes_list, group):
        add_volumes_new = ""
        for volume in volumes:
            if volume['id'] in add_volumes_list:
                # Volume already in group. Remove from add_volumes.
                add_volumes_list.remove(volume['id'])

        for add_vol in add_volumes_list:
            try:
                add_vol_ref = objects.Volume.get_by_id(context, add_vol)
            except exception.VolumeNotFound:
                msg = (_("Cannot add volume %(volume_id)s to "
                         "group %(group_id)s because volume cannot be "
                         "found.") %
                       {'volume_id': add_vol,
                        'group_id': group.id})
                raise exception.InvalidVolume(reason=msg)
            orig_group = add_vol_ref.group_id
            if orig_group:
                # If volume to be added is already in the group to be updated,
                # it should have been removed from the add_volumes_list in the
                # beginning of this function. If we are here, it means it is
                # in a different group.
                msg = (_("Cannot add volume %(volume_id)s to group "
                         "%(group_id)s because it is already in "
                         "group %(orig_group)s.") %
                       {'volume_id': add_vol_ref.id,
                        'group_id': group.id,
                        'orig_group': orig_group})
                raise exception.InvalidVolume(reason=msg)
            if add_vol_ref:
                if add_vol_ref.project_id != group.project_id:
                    msg = (_("Cannot add volume %(volume_id)s to group "
                             "%(group_id)s as they belong to different "
                             "projects.") %
                           {'volume_id': add_vol_ref.id,
                            'group_id': group.id})
                    raise exception.InvalidVolume(reason=msg)
                add_vol_type_id = add_vol_ref.volume_type_id
                if not add_vol_type_id:
                    msg = (_("Cannot add volume %(volume_id)s to group "
                             "%(group_id)s because it has no volume "
                             "type.") %
                           {'volume_id': add_vol_ref.id,
                            'group_id': group.id})
                    raise exception.InvalidVolume(reason=msg)
                vol_type_ids = [v_type.id for v_type in group.volume_types]
                if add_vol_type_id not in vol_type_ids:
                    msg = (_("Cannot add volume %(volume_id)s to group "
                             "%(group_id)s because volume type "
                             "%(volume_type)s is not supported by the "
                             "group.") %
                           {'volume_id': add_vol_ref.id,
                            'group_id': group.id,
                            'volume_type': add_vol_type_id})
                    raise exception.InvalidVolume(reason=msg)
                if (add_vol_ref.status not in
                        VALID_ADD_VOL_TO_GROUP_STATUS):
                    msg = (_("Cannot add volume %(volume_id)s to group "
                             "%(group_id)s because volume is in an "
                             "invalid state: %(status)s. Valid states are: "
                             "%(valid)s.") %
                           {'volume_id': add_vol_ref.id,
                            'group_id': group.id,
                            'status': add_vol_ref.status,
                            'valid': VALID_ADD_VOL_TO_GROUP_STATUS})
                    raise exception.InvalidVolume(reason=msg)

                # group.resource_backend and add_vol_ref.resource_backend are
                # in this format like 'host@backend#pool' in a non-HA
                # deployment and will contain cluster_name in
                # A/A HA deployment.
                vol_host = volume_utils.extract_host(
                    add_vol_ref.resource_backend)
                group_host = volume_utils.extract_host(group.resource_backend)
                if group_host != vol_host:
                    raise exception.InvalidVolume(
                        reason=_("Volume is not local to this node."))

                # Volume exists. It will be added to CG.
                if add_volumes_new:
                    add_volumes_new += ","
                add_volumes_new += add_vol_ref.id

            else:
                msg = (_("Cannot add volume %(volume_id)s to group "
                         "%(group_id)s because volume does not exist.") %
                       {'volume_id': add_vol_ref.id,
                        'group_id': group.id})
                raise exception.InvalidVolume(reason=msg)

        return add_volumes_new

    def get(self, context, group_id):
        group = objects.Group.get_by_id(context, group_id)
        context.authorize(group_policy.GET_POLICY, target_obj=group)
        return group

    def get_all(self, context, filters=None, marker=None, limit=None,
                offset=None, sort_keys=None, sort_dirs=None):
        context.authorize(group_policy.GET_ALL_POLICY)
        if filters is None:
            filters = {}

        if filters:
            LOG.debug("Searching by: %s", filters)

        if (context.is_admin and 'all_tenants' in filters):
            del filters['all_tenants']
            groups = objects.GroupList.get_all(
                context, filters=filters, marker=marker, limit=limit,
                offset=offset, sort_keys=sort_keys, sort_dirs=sort_dirs)
        else:
            groups = objects.GroupList.get_all_by_project(
                context, context.project_id, filters=filters, marker=marker,
                limit=limit, offset=offset, sort_keys=sort_keys,
                sort_dirs=sort_dirs)
        return groups

    def reset_status(self, context, group, status):
        """Reset status of generic group"""
        context.authorize(gp_action_policy.RESET_STATUS, target_obj=group)
        field = {'updated_at': timeutils.utcnow(),
                 'status': status}
        group.update(field)
        group.save()

    def create_group_snapshot(self, context, group, name, description):
        context.authorize(gsnap_policy.CREATE_POLICY, target_obj=group)
        group.assert_not_frozen()
        options = {'group_id': group.id,
                   'user_id': context.user_id,
                   'project_id': context.project_id,
                   'status': "creating",
                   'name': name,
                   'description': description,
                   'group_type_id': group.group_type_id}

        group_snapshot = None
        group_snapshot_id = None
        try:
            group_snapshot = objects.GroupSnapshot(context, **options)
            group_snapshot.create()
            group_snapshot_id = group_snapshot.id

            snap_name = group_snapshot.name
            snap_desc = group_snapshot.description
            with group.obj_as_admin():
                self.volume_api.create_snapshots_in_db(
                    context, group.volumes, snap_name, snap_desc,
                    None, group_snapshot_id)

        except Exception:
            with excutils.save_and_reraise_exception():
                try:
                    # If the group_snapshot has been created
                    if group_snapshot.obj_attr_is_set('id'):
                        group_snapshot.destroy()
                finally:
                    LOG.error("Error occurred when creating group_snapshot"
                              " %s.", group_snapshot_id)

        self.volume_rpcapi.create_group_snapshot(context, group_snapshot)

        return group_snapshot

    def delete_group_snapshot(self, context, group_snapshot, force=False):
        context.authorize(gsnap_policy.DELETE_POLICY,
                          target_obj=group_snapshot)
        group_snapshot.assert_not_frozen()
        values = {'status': 'deleting'}
        expected = {'status': ('available', 'error')}
        filters = [~db.group_creating_from_src(
                   group_snapshot_id=group_snapshot.id)]
        res = group_snapshot.conditional_update(values, expected, filters)

        if not res:
            msg = _('GroupSnapshot status must be available or error, and no '
                    'Group can be currently using it as source for its '
                    'creation.')
            raise exception.InvalidGroupSnapshot(reason=msg)

        snapshots = objects.SnapshotList.get_all_for_group_snapshot(
            context, group_snapshot.id)

        # TODO(xyang): Add a new db API to update all snapshots statuses
        # in one db API call.
        for snap in snapshots:
            snap.status = c_fields.SnapshotStatus.DELETING
            snap.save()

        self.volume_rpcapi.delete_group_snapshot(context.elevated(),
                                                 group_snapshot)

    def update_group_snapshot(self, context, group_snapshot, fields):
        context.authorize(gsnap_policy.UPDATE_POLICY,
                          target_obj=group_snapshot)
        group_snapshot.update(fields)
        group_snapshot.save()

    def get_group_snapshot(self, context, group_snapshot_id):
        group_snapshot = objects.GroupSnapshot.get_by_id(context,
                                                         group_snapshot_id)
        context.authorize(gsnap_policy.GET_POLICY,
                          target_obj=group_snapshot)

        return group_snapshot

    def get_all_group_snapshots(self, context, filters=None, marker=None,
                                limit=None, offset=None, sort_keys=None,
                                sort_dirs=None):
        context.authorize(gsnap_policy.GET_ALL_POLICY)
        filters = filters or {}

        if context.is_admin and 'all_tenants' in filters:
            # Need to remove all_tenants to pass the filtering below.
            del filters['all_tenants']
            group_snapshots = objects.GroupSnapshotList.get_all(
                context, filters=filters, marker=marker, limit=limit,
                offset=offset, sort_keys=sort_keys, sort_dirs=sort_dirs)
        else:
            group_snapshots = objects.GroupSnapshotList.get_all_by_project(
                context.elevated(), context.project_id, filters=filters,
                marker=marker, limit=limit, offset=offset, sort_keys=sort_keys,
                sort_dirs=sort_dirs)
        return group_snapshots

    def reset_group_snapshot_status(self, context, gsnapshot, status):
        """Reset status of group snapshot"""

        context.authorize(gsnap_action_policy.RESET_STATUS,
                          target_obj=gsnapshot)
        field = {'updated_at': timeutils.utcnow(),
                 'status': status}
        gsnapshot.update(field)
        gsnapshot.save()

    def _check_type(self, group):
        if not group.is_replicated:
            msg = _("Group %s is not a replication group type.") % group.id
            LOG.error(msg)
            raise exception.InvalidGroupType(reason=msg)

        for vol_type in group.volume_types:
            if not volume_utils.is_replicated_spec(vol_type.extra_specs):
                msg = _("Volume type %s does not have 'replication_enabled' "
                        "spec key set to '<is> True'.") % vol_type.id
                LOG.error(msg)
                raise exception.InvalidVolumeType(reason=msg)

    # Replication group API (Tiramisu)
    def enable_replication(self, context, group):
        context.authorize(gp_action_policy.ENABLE_REP, target_obj=group)
        self._check_type(group)

        valid_status = [c_fields.GroupStatus.AVAILABLE]
        if group.status not in valid_status:
            params = {'valid': valid_status,
                      'current': group.status,
                      'id': group.id}
            msg = _("Group %(id)s status must be %(valid)s, "
                    "but current status is: %(current)s. "
                    "Cannot enable replication.") % params
            LOG.error(msg)
            raise exception.InvalidGroup(reason=msg)

        valid_rep_status = [c_fields.ReplicationStatus.DISABLED,
                            c_fields.ReplicationStatus.ENABLED]
        if group.replication_status not in valid_rep_status:
            params = {'valid': valid_rep_status,
                      'current': group.replication_status,
                      'id': group.id}
            msg = _("Group %(id)s replication status must be %(valid)s, "
                    "but current status is: %(current)s. "
                    "Cannot enable replication.") % params
            LOG.error(msg)
            raise exception.InvalidGroup(reason=msg)

        volumes = objects.VolumeList.get_all_by_generic_group(
            context.elevated(), group.id)

        valid_status = ['available', 'in-use']
        for vol in volumes:
            if vol.status not in valid_status:
                params = {'valid': valid_status,
                          'current': vol.status,
                          'id': vol.id}
                msg = _("Volume %(id)s status must be %(valid)s, "
                        "but current status is: %(current)s. "
                        "Cannot enable replication.") % params
                LOG.error(msg)
                raise exception.InvalidVolume(reason=msg)
                # replication_status could be set to enabled when volume is
                # created and the mirror is built.
            if vol.replication_status not in valid_rep_status:
                params = {'valid': valid_rep_status,
                          'current': vol.replication_status,
                          'id': vol.id}
                msg = _("Volume %(id)s replication status must be %(valid)s, "
                        "but current status is: %(current)s. "
                        "Cannot enable replication.") % params
                LOG.error(msg)
                raise exception.InvalidVolume(reason=msg)

            vol.replication_status = c_fields.ReplicationStatus.ENABLING
            vol.save()

        group.replication_status = c_fields.ReplicationStatus.ENABLING
        group.save()

        self.volume_rpcapi.enable_replication(context, group)

    def disable_replication(self, context, group):
        context.authorize(gp_action_policy.DISABLE_REP, target_obj=group)
        self._check_type(group)

        valid_status = [c_fields.GroupStatus.AVAILABLE,
                        c_fields.GroupStatus.ERROR]
        if group.status not in valid_status:
            params = {'valid': valid_status,
                      'current': group.status,
                      'id': group.id}
            msg = _("Group %(id)s status must be %(valid)s, "
                    "but current status is: %(current)s. "
                    "Cannot disable replication.") % params
            LOG.error(msg)
            raise exception.InvalidGroup(reason=msg)

        valid_rep_status = [c_fields.ReplicationStatus.ENABLED,
                            c_fields.ReplicationStatus.ERROR]
        if group.replication_status not in valid_rep_status:
            params = {'valid': valid_rep_status,
                      'current': group.replication_status,
                      'id': group.id}
            msg = _("Group %(id)s replication status must be %(valid)s, "
                    "but current status is: %(current)s. "
                    "Cannot disable replication.") % params
            LOG.error(msg)
            raise exception.InvalidGroup(reason=msg)

        volumes = objects.VolumeList.get_all_by_generic_group(
            context.elevated(), group.id)

        for vol in volumes:
            if vol.replication_status not in valid_rep_status:
                params = {'valid': valid_rep_status,
                          'current': vol.replication_status,
                          'id': vol.id}
                msg = _("Volume %(id)s replication status must be %(valid)s, "
                        "but current status is: %(current)s. "
                        "Cannot disable replication.") % params
                LOG.error(msg)
                raise exception.InvalidVolume(reason=msg)

            vol.replication_status = c_fields.ReplicationStatus.DISABLING
            vol.save()

        group.replication_status = c_fields.ReplicationStatus.DISABLING
        group.save()

        self.volume_rpcapi.disable_replication(context, group)

    def failover_replication(self, context, group,
                             allow_attached_volume=False,
                             secondary_backend_id=None):
        context.authorize(gp_action_policy.FAILOVER_REP, target_obj=group)
        self._check_type(group)

        valid_status = [c_fields.GroupStatus.AVAILABLE]
        if group.status not in valid_status:
            params = {'valid': valid_status,
                      'current': group.status,
                      'id': group.id}
            msg = _("Group %(id)s status must be %(valid)s, "
                    "but current status is: %(current)s. "
                    "Cannot failover replication.") % params
            LOG.error(msg)
            raise exception.InvalidGroup(reason=msg)

        valid_rep_status = [c_fields.ReplicationStatus.ENABLED,
                            c_fields.ReplicationStatus.FAILED_OVER]
        if group.replication_status not in valid_rep_status:
            params = {'valid': valid_rep_status,
                      'current': group.replication_status,
                      'id': group.id}
            msg = _("Group %(id)s replication status must be %(valid)s, "
                    "but current status is: %(current)s. "
                    "Cannot failover replication.") % params
            LOG.error(msg)
            raise exception.InvalidGroup(reason=msg)

        volumes = objects.VolumeList.get_all_by_generic_group(
            context.elevated(), group.id)

        valid_status = ['available', 'in-use']
        for vol in volumes:
            if vol.status not in valid_status:
                params = {'valid': valid_status,
                          'current': vol.status,
                          'id': vol.id}
                msg = _("Volume %(id)s status must be %(valid)s, "
                        "but current status is: %(current)s. "
                        "Cannot failover replication.") % params
                LOG.error(msg)
                raise exception.InvalidVolume(reason=msg)
            if vol.status == 'in-use' and not allow_attached_volume:
                msg = _("Volume %s is attached but allow_attached_volume flag "
                        "is False. Cannot failover replication.") % vol.id
                LOG.error(msg)
                raise exception.InvalidVolume(reason=msg)
            if vol.replication_status not in valid_rep_status:
                params = {'valid': valid_rep_status,
                          'current': vol.replication_status,
                          'id': vol.id}
                msg = _("Volume %(id)s replication status must be %(valid)s, "
                        "but current status is: %(current)s. "
                        "Cannot failover replication.") % params
                LOG.error(msg)
                raise exception.InvalidVolume(reason=msg)

            vol.replication_status = c_fields.ReplicationStatus.FAILING_OVER
            vol.save()

        group.replication_status = c_fields.ReplicationStatus.FAILING_OVER
        group.save()

        self.volume_rpcapi.failover_replication(context, group,
                                                allow_attached_volume,
                                                secondary_backend_id)

    def list_replication_targets(self, context, group):
        context.authorize(gp_action_policy.LIST_REP, target_obj=group)
        self._check_type(group)

        return self.volume_rpcapi.list_replication_targets(context, group)
