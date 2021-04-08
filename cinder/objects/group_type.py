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

from cinder import exception
from cinder.i18n import _
from cinder import objects
from cinder.objects import base
from cinder.volume import group_types


@base.CinderObjectRegistry.register
class GroupType(base.CinderPersistentObject, base.CinderObject,
                base.CinderObjectDictCompat, base.CinderComparableObject):
    # Version 1.0: Initial version
    VERSION = '1.0'

    OPTIONAL_FIELDS = ['group_specs', 'projects']

    # NOTE: When adding a field obj_make_compatible needs to be updated
    fields = {
        'id': fields.UUIDField(),
        'name': fields.StringField(nullable=True),
        'description': fields.StringField(nullable=True),
        'is_public': fields.BooleanField(default=True, nullable=True),
        'projects': fields.ListOfStringsField(nullable=True),
        'group_specs': fields.DictOfNullableStringsField(nullable=True),
    }

    @classmethod
    def _get_expected_attrs(cls, context):
        return 'group_specs', 'projects'

    @classmethod
    def _from_db_object(cls, context, type, db_type, expected_attrs=None):
        if expected_attrs is None:
            expected_attrs = []
        for name, field in type.fields.items():
            if name in cls.OPTIONAL_FIELDS:
                continue
            value = db_type[name]
            if isinstance(field, fields.IntegerField):
                value = value or 0
            type[name] = value

        # Get data from db_type object that was queried by joined query
        # from DB
        if 'group_specs' in expected_attrs:
            type.group_specs = {}
            specs = db_type.get('group_specs')
            if specs and isinstance(specs, list):
                type.group_specs = {item['key']: item['value']
                                    for item in specs}
            elif specs and isinstance(specs, dict):
                type.group_specs = specs
        if 'projects' in expected_attrs:
            type.projects = db_type.get('projects', [])

        type._context = context
        type.obj_reset_changes()
        return type

    def create(self):
        if self.obj_attr_is_set('id'):
            raise exception.ObjectActionError(action='create',
                                              reason=_('already created'))
        db_group_type = group_types.create(self._context, self.name,
                                           self.group_specs,
                                           self.is_public, self.projects,
                                           self.description)
        self._from_db_object(self._context, self, db_group_type)

    def save(self):
        updates = self.cinder_obj_get_changes()
        if updates:
            group_types.update(self._context, self.id, self.name,
                               self.description)
            self.obj_reset_changes()

    def destroy(self):
        with self.obj_as_admin():
            group_types.destroy(self._context, self.id)


@base.CinderObjectRegistry.register
class GroupTypeList(base.ObjectListBase, base.CinderObject):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'objects': fields.ListOfObjectsField('GroupType'),
    }

    @classmethod
    def get_all(cls, context, inactive=0, filters=None, marker=None,
                limit=None, sort_keys=None, sort_dirs=None, offset=None):
        types = group_types.get_all_group_types(context, inactive, filters,
                                                marker=marker, limit=limit,
                                                sort_keys=sort_keys,
                                                sort_dirs=sort_dirs,
                                                offset=offset)
        expected_attrs = GroupType._get_expected_attrs(context)
        return base.obj_make_list(context, cls(context),
                                  objects.GroupType, types.values(),
                                  expected_attrs=expected_attrs)
