#    Copyright 2016 Intel Corporation
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

from cinder import objects
from cinder.objects import base


@base.CinderObjectRegistry.register
class RequestSpec(base.CinderObject, base.CinderObjectDictCompat,
                  base.CinderComparableObject):
    # Version 1.0: Initial version
    # Version 1.1: Added group_id and group_backend
    VERSION = '1.1'

    fields = {
        'consistencygroup_id': fields.UUIDField(nullable=True),
        'group_id': fields.UUIDField(nullable=True),
        'cgsnapshot_id': fields.UUIDField(nullable=True),
        'image_id': fields.UUIDField(nullable=True),
        'snapshot_id': fields.UUIDField(nullable=True),
        'source_replicaid': fields.UUIDField(nullable=True),
        'source_volid': fields.UUIDField(nullable=True),
        'volume_id': fields.UUIDField(nullable=True),
        'volume': fields.ObjectField('Volume', nullable=True),
        'volume_type': fields.ObjectField('VolumeType', nullable=True),
        'volume_properties': fields.ObjectField('VolumeProperties',
                                                nullable=True),
        'CG_backend': fields.StringField(nullable=True),
        'group_backend': fields.StringField(nullable=True),
    }

    obj_extra_fields = ['resource_properties']

    @property
    def resource_properties(self):
        # TODO(dulek): This is to maintain compatibility with filters from
        # oslo-incubator. As we've moved them into our codebase we should adapt
        # them to use volume_properties and remove this shim.
        return self.volume_properties

    @classmethod
    def from_primitives(cls, spec):
        """Returns RequestSpec object creating it from legacy dictionary.

        FIXME(dulek): This should go away in early O as we stop supporting
        backward compatibility with M.
        """
        spec = spec.copy()
        spec_obj = cls()

        vol_props = spec.pop('volume_properties', {})
        if vol_props is not None:
            vol_props = VolumeProperties(**vol_props)
        spec_obj.volume_properties = vol_props

        if 'volume' in spec:
            vol = spec.pop('volume', {})
            vol.pop('name', None)
            if vol is not None:
                vol = objects.Volume(**vol)
            spec_obj.volume = vol

        if 'volume_type' in spec:
            vol_type = spec.pop('volume_type', {})
            if vol_type is not None:
                vol_type = objects.VolumeType(**vol_type)
            spec_obj.volume_type = vol_type

        spec.pop('resource_properties', None)

        for k, v in spec.items():
            setattr(spec_obj, k, v)

        return spec_obj


@base.CinderObjectRegistry.register
class VolumeProperties(base.CinderObject, base.CinderObjectDictCompat):
    # Version 1.0: Initial version
    # Version 1.1: Added group_id and group_type_id
    VERSION = '1.1'

    # TODO(dulek): We should add this to initially move volume_properites to
    # ovo, but this should be removed as soon as possible. Most of the data
    # here is already in request_spec and volume there. Outstanding ones would
    # be reservation, and qos_specs. First one may be moved to request_spec and
    # second added as relationship in volume_type field and whole
    # volume_properties (and resource_properties) in request_spec won't be
    # needed.

    fields = {
        'attach_status': fields.StringField(nullable=True),
        'availability_zone': fields.StringField(nullable=True),
        'cgsnapshot_id': fields.UUIDField(nullable=True),
        'consistencygroup_id': fields.UUIDField(nullable=True),
        'group_id': fields.UUIDField(nullable=True),
        'display_description': fields.StringField(nullable=True),
        'display_name': fields.StringField(nullable=True),
        'encryption_key_id': fields.UUIDField(nullable=True),
        'metadata': fields.DictOfStringsField(nullable=True),
        'multiattach': fields.BooleanField(nullable=True),
        'project_id': fields.StringField(nullable=True),
        'qos_specs': fields.DictOfStringsField(nullable=True),
        'replication_status': fields.StringField(nullable=True),
        'reservations': fields.ListOfStringsField(nullable=True),
        'size': fields.IntegerField(nullable=True),
        'snapshot_id': fields.UUIDField(nullable=True),
        'source_replicaid': fields.UUIDField(nullable=True),
        'source_volid': fields.UUIDField(nullable=True),
        'status': fields.StringField(nullable=True),
        'user_id': fields.StringField(nullable=True),
        'volume_type_id': fields.UUIDField(nullable=True),
        'group_type_id': fields.UUIDField(nullable=True),
    }
