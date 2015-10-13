#    Copyright 2015 SimpliVity Corp.
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

from oslo_config import cfg
from oslo_log import log as logging
from oslo_versionedobjects import fields

from cinder import exception
from cinder.i18n import _
from cinder import objects
from cinder.objects import base
from cinder.volume import volume_types

CONF = cfg.CONF
OPTIONAL_FIELDS = ['extra_specs', 'projects']
LOG = logging.getLogger(__name__)


@base.CinderObjectRegistry.register
class VolumeType(base.CinderPersistentObject, base.CinderObject,
                 base.CinderObjectDictCompat, base.CinderComparableObject):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'id': fields.UUIDField(),
        'name': fields.StringField(nullable=True),
        'description': fields.StringField(nullable=True),
        'is_public': fields.BooleanField(default=True),
        'projects': fields.ListOfStringsField(nullable=True),
        'extra_specs': fields.DictOfStringsField(nullable=True),
    }

    @staticmethod
    def _from_db_object(context, type, db_type, expected_attrs=None):
        if expected_attrs is None:
            expected_attrs = []
        for name, field in type.fields.items():
            if name in OPTIONAL_FIELDS:
                continue
            value = db_type[name]
            if isinstance(field, fields.IntegerField):
                value = value or 0
            type[name] = value

        # Get data from db_type object that was queried by joined query
        # from DB
        if 'extra_specs' in expected_attrs:
            type.extra_specs = {}
            specs = db_type.get('extra_specs')
            if specs and isinstance(specs, list):
                type.extra_specs = {item['key']: item['value']
                                    for item in specs}
            elif specs and isinstance(specs, dict):
                type.extra_specs = specs
        if 'projects' in expected_attrs:
            type.projects = db_type.get('projects', [])

        type._context = context
        type.obj_reset_changes()
        return type

    @base.remotable_classmethod
    def get_by_id(cls, context, id):
        db_volume_type = volume_types.get_volume_type(
            context, id, expected_fields=['extra_specs', 'projects'])
        expected_attrs = ['extra_specs', 'projects']
        return cls._from_db_object(context, cls(context), db_volume_type,
                                   expected_attrs=expected_attrs)

    @base.remotable
    def create(self):
        if self.obj_attr_is_set('id'):
            raise exception.ObjectActionError(action='create',
                                              reason=_('already created'))
        db_volume_type = volume_types.create(self._context, self.name,
                                             self.extra_specs,
                                             self.is_public, self.projects,
                                             self.description)
        self._from_db_object(self._context, self, db_volume_type)

    @base.remotable
    def save(self):
        updates = self.cinder_obj_get_changes()
        if updates:
            volume_types.update(self._context, self.id, self.name,
                                self.description)
            self.obj_reset_changes()

    @base.remotable
    def destroy(self):
        with self.obj_as_admin():
            volume_types.destroy(self._context, self.id)


@base.CinderObjectRegistry.register
class VolumeTypeList(base.ObjectListBase, base.CinderObject):
    VERSION = '1.0'

    fields = {
        'objects': fields.ListOfObjectsField('VolumeType'),
    }

    child_versions = {
        '1.0': '1.0',
    }

    @base.remotable_classmethod
    def get_all(cls, context, inactive=0, search_opts=None):
        types = volume_types.get_all_types(context, inactive, search_opts)
        expected_attrs = ['extra_specs', 'projects']
        return base.obj_make_list(context, cls(context),
                                  objects.VolumeType, types.values(),
                                  expected_attrs=expected_attrs)
