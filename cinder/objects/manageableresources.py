#   Copyright 2016 Intel Corporation
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

from cinder.objects import base


class ManageableObject(object):

    fields = {
        'reference': fields.DictOfNullableStringsField(nullable=False),
        'size': fields.IntegerField(nullable=True),
        'safe_to_manage': fields.BooleanField(default=False, nullable=True),
        'reason_not_safe': fields.StringField(nullable=True),
        'cinder_id': fields.UUIDField(nullable=True),
        'extra_info': fields.DictOfNullableStringsField(nullable=True),
    }

    @classmethod
    def from_primitives(cls, context, dict_resource):
        resource = cls()
        driverkeys = set(dict_resource.keys()) - set(cls.fields.keys())
        for name, field in cls.fields.items():
            value = dict_resource.get(name)
            resource[name] = value

        for key in driverkeys:
            if resource['extra_info'] is None:
                resource['extra_info'] = {key: dict_resource[key]}

        resource._context = context
        resource.obj_reset_changes()
        return resource


@base.CinderObjectRegistry.register
class ManageableVolume(base.CinderObject, base.CinderObjectDictCompat,
                       base.CinderComparableObject, ManageableObject):
    # Version 1.0: Initial version
    VERSION = '1.0'


@base.CinderObjectRegistry.register
class ManageableSnapshot(base.CinderObject, base.CinderObjectDictCompat,
                         ManageableObject):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'source_reference': fields.DictOfNullableStringsField(),
    }


@base.CinderObjectRegistry.register
class ManageableVolumeList(base.ObjectListBase, base.CinderObject):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'objects': fields.ListOfObjectsField('ManageableVolume'),
    }

    @classmethod
    def from_primitives(cls, context, data):
        ManageableVolumeList.objects = []

        for item in data:
            manage_vol_obj = ManageableVolume.from_primitives(context, item)
            ManageableVolumeList.objects.append(manage_vol_obj)
        ManageableVolumeList._context = context
        return ManageableVolumeList.objects


@base.CinderObjectRegistry.register
class ManageableSnapshotList(base.ObjectListBase, base.CinderObject):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'objects': fields.ListOfObjectsField('ManageableSnapshot'),
    }

    @classmethod
    def from_primitives(cls, context, data):
        ManageableSnapshotList.objects = []

        for item in data:
            manage_snap_obj = ManageableSnapshot.from_primitives(context, item)
            ManageableSnapshotList.objects.append(manage_snap_obj)
        ManageableSnapshotList._context = context
        return ManageableSnapshotList.objects
