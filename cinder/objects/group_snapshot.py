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


@base.CinderObjectRegistry.register
class GroupSnapshot(base.CinderPersistentObject, base.CinderObject,
                    base.CinderObjectDictCompat, base.ClusteredObject):
    VERSION = '1.0'

    OPTIONAL_FIELDS = ['group', 'snapshots']

    # NOTE: When adding a field obj_make_compatible needs to be updated
    fields = {
        'id': fields.UUIDField(),
        'group_id': fields.UUIDField(nullable=False),
        'project_id': fields.StringField(nullable=True),
        'user_id': fields.StringField(nullable=True),
        'name': fields.StringField(nullable=True),
        'description': fields.StringField(nullable=True),
        'status': fields.StringField(nullable=True),
        'group_type_id': fields.UUIDField(nullable=True),
        'group': fields.ObjectField('Group', nullable=True),
        'snapshots': fields.ObjectField('SnapshotList', nullable=True),
    }

    @property
    def host(self):
        return self.group.host

    @property
    def cluster_name(self):
        return self.group.cluster_name

    @classmethod
    def _from_db_object(cls, context, group_snapshot, db_group_snapshots,
                        expected_attrs=None):
        expected_attrs = expected_attrs or []
        for name, field in group_snapshot.fields.items():
            if name in cls.OPTIONAL_FIELDS:
                continue
            value = db_group_snapshots.get(name)
            setattr(group_snapshot, name, value)

        if 'group' in expected_attrs:
            group = objects.Group(context)
            group._from_db_object(context, group,
                                  db_group_snapshots['group'])
            group_snapshot.group = group

        if 'snapshots' in expected_attrs:
            snapshots = base.obj_make_list(
                context, objects.SnapshotsList(context),
                objects.Snapshots,
                db_group_snapshots['snapshots'])
            group_snapshot.snapshots = snapshots

        group_snapshot._context = context
        group_snapshot.obj_reset_changes()
        return group_snapshot

    def create(self):
        if self.obj_attr_is_set('id'):
            raise exception.ObjectActionError(action='create',
                                              reason=_('already_created'))
        updates = self.cinder_obj_get_changes()

        if 'group' in updates:
            raise exception.ObjectActionError(
                action='create', reason=_('group assigned'))

        db_group_snapshots = db.group_snapshot_create(self._context, updates)
        self._from_db_object(self._context, self, db_group_snapshots)

    def obj_load_attr(self, attrname):
        if attrname not in self.OPTIONAL_FIELDS:
            raise exception.ObjectActionError(
                action='obj_load_attr',
                reason=_('attribute %s not lazy-loadable') % attrname)
        if not self._context:
            raise exception.OrphanedObjectError(method='obj_load_attr',
                                                objtype=self.obj_name())

        if attrname == 'group':
            self.group = objects.Group.get_by_id(
                self._context, self.group_id)

        if attrname == 'snapshots':
            self.snapshots = objects.SnapshotList.get_all_for_group_snapshot(
                self._context, self.id)

        self.obj_reset_changes(fields=[attrname])

    def save(self):
        updates = self.cinder_obj_get_changes()
        if updates:
            if 'group' in updates:
                raise exception.ObjectActionError(
                    action='save', reason=_('group changed'))
            if 'snapshots' in updates:
                raise exception.ObjectActionError(
                    action='save', reason=_('snapshots changed'))
            db.group_snapshot_update(self._context, self.id, updates)
            self.obj_reset_changes()

    def destroy(self):
        with self.obj_as_admin():
            updated_values = db.group_snapshot_destroy(self._context, self.id)
        self.update(updated_values)
        self.obj_reset_changes(updated_values.keys())


@base.CinderObjectRegistry.register
class GroupSnapshotList(base.ObjectListBase, base.CinderObject):
    VERSION = '1.0'

    fields = {
        'objects': fields.ListOfObjectsField('GroupSnapshot')
    }

    @classmethod
    def get_all(cls, context, filters=None, marker=None, limit=None,
                offset=None, sort_keys=None, sort_dirs=None):
        group_snapshots = db.group_snapshot_get_all(context,
                                                    filters=filters,
                                                    marker=marker,
                                                    limit=limit,
                                                    offset=offset,
                                                    sort_keys=sort_keys,
                                                    sort_dirs=sort_dirs)
        return base.obj_make_list(context, cls(context), objects.GroupSnapshot,
                                  group_snapshots)

    @classmethod
    def get_all_by_project(cls, context, project_id, filters=None, marker=None,
                           limit=None, offset=None, sort_keys=None,
                           sort_dirs=None):
        group_snapshots = db.group_snapshot_get_all_by_project(
            context, project_id, filters=filters, marker=marker,
            limit=limit, offset=offset, sort_keys=sort_keys,
            sort_dirs=sort_dirs)
        return base.obj_make_list(context, cls(context), objects.GroupSnapshot,
                                  group_snapshots)

    @classmethod
    def get_all_by_group(cls, context, group_id, filters=None, marker=None,
                         limit=None, offset=None, sort_keys=None,
                         sort_dirs=None):
        group_snapshots = db.group_snapshot_get_all_by_group(
            context, group_id, filters=filters, marker=marker, limit=limit,
            offset=offset, sort_keys=sort_keys, sort_dirs=sort_dirs)
        return base.obj_make_list(context, cls(context), objects.GroupSnapshot,
                                  group_snapshots)
