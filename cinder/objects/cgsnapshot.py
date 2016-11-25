#    Copyright 2015 Intel Corporation
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

from cinder import db
from cinder import exception
from cinder.i18n import _
from cinder import objects
from cinder.objects import base
from oslo_versionedobjects import fields


@base.CinderObjectRegistry.register
class CGSnapshot(base.CinderPersistentObject, base.CinderObject,
                 base.CinderObjectDictCompat, base.ClusteredObject):
    # Version 1.0: Initial version
    # Version 1.1: Added from_group_snapshot
    VERSION = '1.1'

    OPTIONAL_FIELDS = ['consistencygroup', 'snapshots']

    fields = {
        'id': fields.UUIDField(),
        'consistencygroup_id': fields.UUIDField(nullable=True),
        'project_id': fields.StringField(),
        'user_id': fields.StringField(),
        'name': fields.StringField(nullable=True),
        'description': fields.StringField(nullable=True),
        'status': fields.StringField(nullable=True),
        'consistencygroup': fields.ObjectField('ConsistencyGroup',
                                               nullable=True),
        'snapshots': fields.ObjectField('SnapshotList', nullable=True),
    }

    @property
    def host(self):
        return self.consistencygroup.host

    @property
    def cluster_name(self):
        return self.consistencygroup.cluster_name

    @classmethod
    def _from_db_object(cls, context, cgsnapshot, db_cgsnapshots,
                        expected_attrs=None):
        expected_attrs = expected_attrs or []
        for name, field in cgsnapshot.fields.items():
            if name in cls.OPTIONAL_FIELDS:
                continue
            value = db_cgsnapshots.get(name)
            setattr(cgsnapshot, name, value)

        if 'consistencygroup' in expected_attrs:
            consistencygroup = objects.ConsistencyGroup(context)
            consistencygroup._from_db_object(context, consistencygroup,
                                             db_cgsnapshots[
                                                 'consistencygroup'])
            cgsnapshot.consistencygroup = consistencygroup

        if 'snapshots' in expected_attrs:
            snapshots = base.obj_make_list(
                context, objects.SnapshotsList(context),
                objects.Snapshots,
                db_cgsnapshots['snapshots'])
            cgsnapshot.snapshots = snapshots

        cgsnapshot._context = context
        cgsnapshot.obj_reset_changes()
        return cgsnapshot

    def create(self):
        if self.obj_attr_is_set('id'):
            raise exception.ObjectActionError(action='create',
                                              reason=_('already_created'))
        updates = self.cinder_obj_get_changes()

        if 'consistencygroup' in updates:
            raise exception.ObjectActionError(
                action='create', reason=_('consistencygroup assigned'))

        db_cgsnapshots = db.cgsnapshot_create(self._context, updates)
        self._from_db_object(self._context, self, db_cgsnapshots)

    def from_group_snapshot(self, group_snapshot):
        """Convert a generic volume group object to a cg object."""
        self.id = group_snapshot.id
        self.consistencygroup_id = group_snapshot.group_id
        self.user_id = group_snapshot.user_id
        self.project_id = group_snapshot.project_id
        self.name = group_snapshot.name
        self.description = group_snapshot.description
        self.status = group_snapshot.status

    def obj_load_attr(self, attrname):
        if attrname not in self.OPTIONAL_FIELDS:
            raise exception.ObjectActionError(
                action='obj_load_attr',
                reason=_('attribute %s not lazy-loadable') % attrname)
        if not self._context:
            raise exception.OrphanedObjectError(method='obj_load_attr',
                                                objtype=self.obj_name())

        if attrname == 'consistencygroup':
            self.consistencygroup = objects.ConsistencyGroup.get_by_id(
                self._context, self.consistencygroup_id)

        if attrname == 'snapshots':
            self.snapshots = objects.SnapshotList.get_all_for_cgsnapshot(
                self._context, self.id)

        self.obj_reset_changes(fields=[attrname])

    def save(self):
        updates = self.cinder_obj_get_changes()
        if updates:
            if 'consistencygroup' in updates:
                raise exception.ObjectActionError(
                    action='save', reason=_('consistencygroup changed'))
            if 'snapshots' in updates:
                raise exception.ObjectActionError(
                    action='save', reason=_('snapshots changed'))
            db.cgsnapshot_update(self._context, self.id, updates)
            self.obj_reset_changes()

    def destroy(self):
        with self.obj_as_admin():
            updated_values = db.cgsnapshot_destroy(self._context, self.id)
        self.update(updated_values)
        self.obj_reset_changes(updated_values.keys())


@base.CinderObjectRegistry.register
class CGSnapshotList(base.ObjectListBase, base.CinderObject):
    VERSION = '1.0'

    fields = {
        'objects': fields.ListOfObjectsField('CGSnapshot')
    }

    @classmethod
    def get_all(cls, context, filters=None):
        cgsnapshots = db.cgsnapshot_get_all(context, filters)
        return base.obj_make_list(context, cls(context), objects.CGSnapshot,
                                  cgsnapshots)

    @classmethod
    def get_all_by_project(cls, context, project_id, filters=None):
        cgsnapshots = db.cgsnapshot_get_all_by_project(context, project_id,
                                                       filters)
        return base.obj_make_list(context, cls(context), objects.CGSnapshot,
                                  cgsnapshots)

    @classmethod
    def get_all_by_group(cls, context, group_id, filters=None):
        cgsnapshots = db.cgsnapshot_get_all_by_group(context, group_id,
                                                     filters)
        return base.obj_make_list(context, cls(context),
                                  objects.CGSnapshot,
                                  cgsnapshots)
