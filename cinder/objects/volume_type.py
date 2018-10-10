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

from oslo_utils import versionutils
from oslo_versionedobjects import fields
import six

from cinder import db
from cinder import exception
from cinder.i18n import _
from cinder import objects
from cinder.objects import base
from cinder.volume import utils
from cinder.volume import volume_types


@base.CinderObjectRegistry.register
class VolumeType(base.CinderPersistentObject, base.CinderObject,
                 base.CinderObjectDictCompat, base.CinderComparableObject):
    # Version 1.0: Initial version
    # Version 1.1: Changed extra_specs to DictOfNullableStringsField
    # Version 1.2: Added qos_specs
    # Version 1.3: Add qos_specs_id
    VERSION = '1.3'

    OPTIONAL_FIELDS = ('extra_specs', 'projects', 'qos_specs')

    fields = {
        'id': fields.UUIDField(),
        'name': fields.StringField(nullable=True),
        'description': fields.StringField(nullable=True),
        'is_public': fields.BooleanField(default=True, nullable=True),
        'projects': fields.ListOfStringsField(nullable=True),
        'extra_specs': fields.DictOfNullableStringsField(nullable=True),
        'qos_specs_id': fields.UUIDField(nullable=True),
        'qos_specs': fields.ObjectField('QualityOfServiceSpecs',
                                        nullable=True),
    }

    def obj_make_compatible(self, primitive, target_version):
        super(VolumeType, self).obj_make_compatible(primitive, target_version)

        target_version = versionutils.convert_version_to_tuple(target_version)
        if target_version < (1, 1):
            if primitive.get('extra_specs'):
                # Before 1.1 extra_specs field didn't allowed None values. To
                # make sure we won't explode on receiver side - change Nones to
                # empty string.
                for k, v in primitive['extra_specs'].items():
                    if v is None:
                        primitive['extra_specs'][k] = ''
        if target_version < (1, 3):
            primitive.pop('qos_specs_id', None)

    @classmethod
    def _get_expected_attrs(cls, context, *args, **kwargs):
        return 'extra_specs', 'projects'

    @classmethod
    def _from_db_object(cls, context, type, db_type, expected_attrs=None):
        if expected_attrs is None:
            expected_attrs = ['extra_specs', 'projects']
        for name, field in type.fields.items():
            if name in cls.OPTIONAL_FIELDS:
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
            # NOTE(geguileo): Until projects stops being a polymorphic value we
            # have to do a conversion here for VolumeTypeProjects ORM instance
            # lists.
            projects = db_type.get('projects', [])
            if projects and not isinstance(projects[0], six.string_types):
                projects = [p.project_id for p in projects]
            type.projects = projects
        if 'qos_specs' in expected_attrs:
            qos_specs = objects.QualityOfServiceSpecs(context)
            qos_specs._from_db_object(context, qos_specs, db_type['qos_specs'])
            type.qos_specs = qos_specs
        type._context = context
        type.obj_reset_changes()
        return type

    def create(self):
        if self.obj_attr_is_set('id'):
            raise exception.ObjectActionError(action='create',
                                              reason=_('already created'))
        db_volume_type = volume_types.create(self._context, self.name,
                                             self.extra_specs,
                                             self.is_public, self.projects,
                                             self.description)
        self._from_db_object(self._context, self, db_volume_type)

    def save(self):
        updates = self.cinder_obj_get_changes()
        if updates:
            volume_types.update(self._context, self.id, self.name,
                                self.description)
            self.obj_reset_changes()

    def destroy(self):
        with self.obj_as_admin():
            updated_values = volume_types.destroy(self._context, self.id)
        self.update(updated_values)
        self.obj_reset_changes(updated_values.keys())

    def obj_load_attr(self, attrname):
        if attrname not in self.OPTIONAL_FIELDS:
            raise exception.ObjectActionError(
                action='obj_load_attr',
                reason=_('attribute %s not lazy-loadable') % attrname)
        if not self._context:
            raise exception.OrphanedObjectError(method='obj_load_attr',
                                                objtype=self.obj_name())

        if attrname == 'extra_specs':
            self.extra_specs = db.volume_type_extra_specs_get(self._context,
                                                              self.id)

        elif attrname == 'qos_specs':
            if self.qos_specs_id:
                self.qos_specs = objects.QualityOfServiceSpecs.get_by_id(
                    self._context, self.qos_specs_id)
            else:
                self.qos_specs = None

        elif attrname == 'projects':
            volume_type_projects = db.volume_type_access_get_all(self._context,
                                                                 self.id)
            self.projects = [x.project_id for x in volume_type_projects]

        self.obj_reset_changes(fields=[attrname])

    @classmethod
    def get_by_name_or_id(cls, context, identity):
        orm_obj = volume_types.get_by_name_or_id(context, identity)
        expected_attrs = cls._get_expected_attrs(context)
        return cls._from_db_object(context, cls(context),
                                   orm_obj, expected_attrs=expected_attrs)

    def is_replicated(self):
        return utils.is_replicated_spec(self.extra_specs)

    def is_multiattach(self):
        return utils.is_multiattach_spec(self.extra_specs)


@base.CinderObjectRegistry.register
class VolumeTypeList(base.ObjectListBase, base.CinderObject):
    # Version 1.0: Initial version
    # Version 1.1: Add pagination support to volume type
    VERSION = '1.1'

    fields = {
        'objects': fields.ListOfObjectsField('VolumeType'),
    }

    @classmethod
    def get_all(cls, context, inactive=0, filters=None, marker=None,
                limit=None, sort_keys=None, sort_dirs=None, offset=None):
        types = volume_types.get_all_types(context, inactive, filters,
                                           marker=marker, limit=limit,
                                           sort_keys=sort_keys,
                                           sort_dirs=sort_dirs, offset=offset)
        expected_attrs = VolumeType._get_expected_attrs(context)
        return base.obj_make_list(context, cls(context),
                                  objects.VolumeType, types.values(),
                                  expected_attrs=expected_attrs)

    @classmethod
    def get_all_types_for_qos(cls, context, qos_id):
        types = db.qos_specs_associations_get(context, qos_id)
        return base.obj_make_list(context, cls(context), objects.VolumeType,
                                  types)

    @classmethod
    def get_all_by_group(cls, context, group_id):
        # Generic volume group
        types = volume_types.get_all_types_by_group(
            context.elevated(), group_id)
        expected_attrs = VolumeType._get_expected_attrs(context)
        return base.obj_make_list(context, cls(context),
                                  objects.VolumeType, types,
                                  expected_attrs=expected_attrs)
