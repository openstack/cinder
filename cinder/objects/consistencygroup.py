#    Copyright 2015 Yahoo Inc.
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
class ConsistencyGroup(base.CinderPersistentObject, base.CinderObject,
                       base.CinderObjectDictCompat):
    VERSION = '1.0'

    fields = {
        'id': fields.UUIDField(),
        'user_id': fields.UUIDField(),
        'project_id': fields.UUIDField(),
        'host': fields.StringField(nullable=True),
        'availability_zone': fields.StringField(nullable=True),
        'name': fields.StringField(nullable=True),
        'description': fields.StringField(nullable=True),
        'volume_type_id': fields.UUIDField(nullable=True),
        'status': fields.StringField(nullable=True),
        'cgsnapshot_id': fields.UUIDField(nullable=True),
        'source_cgid': fields.UUIDField(nullable=True),
    }

    @staticmethod
    def _from_db_object(context, consistencygroup, db_consistencygroup):
        for name, field in consistencygroup.fields.items():
            value = db_consistencygroup.get(name)
            setattr(consistencygroup, name, value)

        consistencygroup._context = context
        consistencygroup.obj_reset_changes()
        return consistencygroup

    @base.remotable_classmethod
    def get_by_id(cls, context, id):
        db_consistencygroup = db.consistencygroup_get(context, id)
        return cls._from_db_object(context, cls(context),
                                   db_consistencygroup)

    @base.remotable
    def create(self):
        if self.obj_attr_is_set('id'):
            raise exception.ObjectActionError(action='create',
                                              reason=_('already_created'))
        updates = self.cinder_obj_get_changes()
        db_consistencygroups = db.consistencygroup_create(self._context,
                                                          updates)
        self._from_db_object(self._context, self, db_consistencygroups)

    @base.remotable
    def save(self):
        updates = self.cinder_obj_get_changes()
        if updates:
            db.consistencygroup_update(self._context, self.id, updates)
            self.obj_reset_changes()

    @base.remotable
    def destroy(self):
        with self.obj_as_admin():
            db.consistencygroup_destroy(self._context, self.id)


@base.CinderObjectRegistry.register
class ConsistencyGroupList(base.ObjectListBase, base.CinderObject):
    VERSION = '1.0'

    fields = {
        'objects': fields.ListOfObjectsField('ConsistencyGroup')
    }
    child_version = {
        '1.0': '1.0'
    }

    @base.remotable_classmethod
    def get_all(cls, context):
        consistencygroups = db.consistencygroup_get_all(context)
        return base.obj_make_list(context, cls(context),
                                  objects.ConsistencyGroup,
                                  consistencygroups)

    @base.remotable_classmethod
    def get_all_by_project(cls, context, project_id):
        consistencygroups = db.consistencygroup_get_all_by_project(context,
                                                                   project_id)
        return base.obj_make_list(context, cls(context),
                                  objects.ConsistencyGroup,
                                  consistencygroups)
