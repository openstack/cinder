#    Copyright 2016 EMC Corporation
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

from oslo_versionedobjects import fields

from cinder import db
from cinder import exception
from cinder.i18n import _
from cinder import objects
from cinder.objects import base
from cinder.objects import fields as c_fields
from cinder.volume import volume_utils


@base.CinderObjectRegistry.register
class Group(base.CinderPersistentObject, base.CinderObject,
            base.CinderObjectDictCompat, base.ClusteredObject):
    # Version 1.0: Initial version
    # Version 1.1: Added group_snapshots, group_snapshot_id, and
    #              source_group_id
    # Version 1.2: Added replication_status
    VERSION = '1.2'

    OPTIONAL_FIELDS = ['volumes', 'volume_types', 'group_snapshots']

    # NOTE: When adding a field obj_make_compatible needs to be updated
    fields = {
        'id': fields.UUIDField(),
        'user_id': fields.StringField(),
        'project_id': fields.StringField(),
        'cluster_name': fields.StringField(nullable=True),
        'host': fields.StringField(nullable=True),
        'availability_zone': fields.StringField(nullable=True),
        'name': fields.StringField(nullable=True),
        'description': fields.StringField(nullable=True),
        'group_type_id': fields.StringField(),
        'volume_type_ids': fields.ListOfStringsField(nullable=True),
        'status': c_fields.GroupStatusField(nullable=True),
        'group_snapshot_id': fields.UUIDField(nullable=True),
        'source_group_id': fields.UUIDField(nullable=True),
        'replication_status': c_fields.ReplicationStatusField(nullable=True),
        'volumes': fields.ObjectField('VolumeList', nullable=True),
        'volume_types': fields.ObjectField('VolumeTypeList',
                                           nullable=True),
        'group_snapshots': fields.ObjectField('GroupSnapshotList',
                                              nullable=True),
    }

    @staticmethod
    def _from_db_object(context, group, db_group,
                        expected_attrs=None):
        if expected_attrs is None:
            expected_attrs = []
        for name, field in group.fields.items():
            if name in Group.OPTIONAL_FIELDS:
                continue
            value = db_group.get(name)
            setattr(group, name, value)

        if 'volumes' in expected_attrs:
            volumes = base.obj_make_list(
                context, objects.VolumeList(context),
                objects.Volume,
                db_group['volumes'])
            group.volumes = volumes

        if 'volume_types' in expected_attrs:
            volume_types = base.obj_make_list(
                context, objects.VolumeTypeList(context),
                objects.VolumeType,
                db_group['volume_types'])
            group.volume_types = volume_types

        if 'group_snapshots' in expected_attrs:
            group_snapshots = base.obj_make_list(
                context, objects.GroupSnapshotList(context),
                objects.GroupSnapshot,
                db_group['group_snapshots'])
            group.group_snapshots = group_snapshots

        group._context = context
        group.obj_reset_changes()
        return group

    def create(self, group_snapshot_id=None, source_group_id=None):
        if self.obj_attr_is_set('id'):
            raise exception.ObjectActionError(action='create',
                                              reason=_('already_created'))
        updates = self.cinder_obj_get_changes()

        if 'volume_types' in updates:
            raise exception.ObjectActionError(
                action='create',
                reason=_('volume_types assigned'))

        if 'volumes' in updates:
            raise exception.ObjectActionError(action='create',
                                              reason=_('volumes assigned'))

        if 'group_snapshots' in updates:
            raise exception.ObjectActionError(
                action='create',
                reason=_('group_snapshots assigned'))

        db_groups = db.group_create(self._context,
                                    updates,
                                    group_snapshot_id,
                                    source_group_id)
        self._from_db_object(self._context, self, db_groups)

    def obj_load_attr(self, attrname):
        if attrname not in Group.OPTIONAL_FIELDS:
            raise exception.ObjectActionError(
                action='obj_load_attr',
                reason=_('attribute %s not lazy-loadable') % attrname)
        if not self._context:
            raise exception.OrphanedObjectError(method='obj_load_attr',
                                                objtype=self.obj_name())

        if attrname == 'volume_types':
            self.volume_types = objects.VolumeTypeList.get_all_by_group(
                self._context, self.id)

        if attrname == 'volumes':
            self.volumes = objects.VolumeList.get_all_by_generic_group(
                self._context, self.id)

        if attrname == 'group_snapshots':
            self.group_snapshots = objects.GroupSnapshotList.get_all_by_group(
                self._context, self.id)

        self.obj_reset_changes(fields=[attrname])

    def save(self):
        updates = self.cinder_obj_get_changes()
        if updates:
            if 'volume_types' in updates:
                msg = _('Cannot save volume_types changes in group object '
                        'update.')
                raise exception.ObjectActionError(
                    action='save', reason=msg)
            if 'volumes' in updates:
                msg = _('Cannot save volumes changes in group object update.')
                raise exception.ObjectActionError(
                    action='save', reason=msg)
            if 'group_snapshots' in updates:
                msg = _('Cannot save group_snapshots changes in group object '
                        'update.')
                raise exception.ObjectActionError(
                    action='save', reason=msg)

            db.group_update(self._context, self.id, updates)
            self.obj_reset_changes()

    def destroy(self):
        with self.obj_as_admin():
            db.group_destroy(self._context, self.id)

    @property
    def is_replicated(self):
        if (volume_utils.is_group_a_type(self, "group_replication_enabled") or
                volume_utils.is_group_a_type(
                    self, "consistent_group_replication_enabled")):
            return True
        return False


@base.CinderObjectRegistry.register
class GroupList(base.ObjectListBase, base.CinderObject):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'objects': fields.ListOfObjectsField('Group')
    }

    @classmethod
    def get_all(cls, context, filters=None, marker=None, limit=None,
                offset=None, sort_keys=None, sort_dirs=None):
        groups = db.group_get_all(
            context, filters=filters, marker=marker, limit=limit,
            offset=offset, sort_keys=sort_keys, sort_dirs=sort_dirs)
        return base.obj_make_list(context, cls(context),
                                  objects.Group,
                                  groups)

    @classmethod
    def get_all_by_project(cls, context, project_id, filters=None, marker=None,
                           limit=None, offset=None, sort_keys=None,
                           sort_dirs=None):
        groups = db.group_get_all_by_project(
            context, project_id, filters=filters, marker=marker, limit=limit,
            offset=offset, sort_keys=sort_keys, sort_dirs=sort_dirs)
        return base.obj_make_list(context, cls(context),
                                  objects.Group,
                                  groups)

    @classmethod
    def get_all_replicated(cls, context, filters=None, marker=None, limit=None,
                           offset=None, sort_keys=None, sort_dirs=None):
        groups = db.group_get_all(
            context, filters=filters, marker=marker, limit=limit,
            offset=offset, sort_keys=sort_keys, sort_dirs=sort_dirs)
        grp_obj_list = base.obj_make_list(context, cls(context),
                                          objects.Group,
                                          groups)

        out_groups = [grp for grp in grp_obj_list
                      if grp.is_replicated]

        return out_groups

    @staticmethod
    def include_in_cluster(context, cluster, partial_rename=True, **filters):
        """Include all generic groups matching the filters into a cluster.

        When partial_rename is set we will not set the cluster_name with
        cluster parameter value directly, we'll replace provided cluster_name
        or host filter value with cluster instead.

        This is useful when we want to replace just the cluster name but leave
        the backend and pool information as it is.  If we are using
        cluster_name to filter, we'll use that same DB field to replace the
        cluster value and leave the rest as it is.  Likewise if we use the host
        to filter.

        Returns the number of generic groups that have been changed.
        """
        return db.group_include_in_cluster(context, cluster, partial_rename,
                                           **filters)
