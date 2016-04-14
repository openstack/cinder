# Copyright (c) 2016 Red Hat Inc.
# Copyright (c) 2016 Intel Corp.
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

from oslo_utils import versionutils

from cinder import objects


@objects.base.CinderObjectRegistry.register_if(False)
class ChildObject(objects.base.CinderObject):
    VERSION = '1.2'

    fields = {
        'scheduled_at': objects.base.fields.DateTimeField(nullable=True),
        'uuid': objects.base.fields.UUIDField(),
        'text': objects.base.fields.StringField(nullable=True),
        'integer': objects.base.fields.IntegerField(nullable=True),
    }

    def obj_make_compatible(self, primitive, target_version):
        super(ChildObject, self).obj_make_compatible(primitive,
                                                     target_version)
        target_version = versionutils.convert_version_to_tuple(target_version)
        if target_version < (1, 1):
            primitive.pop('text', None)
        if target_version < (1, 2):
            primitive.pop('integer', None)


@objects.base.CinderObjectRegistry.register_if(False)
class ParentObject(objects.base.CinderObject):
    VERSION = '1.1'

    fields = {
        'uuid': objects.base.fields.UUIDField(),
        'child': objects.base.fields.ObjectField('ChildObject', nullable=True),
        'scheduled_at': objects.base.fields.DateTimeField(nullable=True),
    }

    def obj_make_compatible(self, primitive, target_version):
        super(ParentObject, self).obj_make_compatible(primitive,
                                                      target_version)
        target_version = versionutils.convert_version_to_tuple(target_version)
        if target_version < (1, 1):
            primitive.pop('scheduled_at', None)


@objects.base.CinderObjectRegistry.register_if(False)
class ParentObjectList(objects.base.CinderObject, objects.base.ObjectListBase):
    VERSION = ParentObject.VERSION

    fields = {
        'objects': objects.base.fields.ListOfObjectsField('ParentObject'),
    }


class MyHistory(objects.base.CinderObjectVersionsHistory):
    linked_objects = {'ParentObject': 'ParentObjectList'}

    def __init__(self):
        self.versions = ['1.0']
        self['1.0'] = {'ChildObject': '1.0'}
        self.add('1.1', {'ChildObject': '1.1'})
        self.add('1.2', {'ParentObject': '1.0'})
        self.add('1.3', {'ParentObjectList': '1.0'})
        self.add('1.4', {'ParentObject': '1.1'})
        self.add('1.5', {'ParentObjectList': '1.1'})
        self.add('1.6', {'ChildObject': '1.2'})
