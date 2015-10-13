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

import mock

from cinder import context
from cinder import objects
from cinder.tests.unit import fake_volume
from cinder.tests.unit import objects as test_objects


class TestVolumeType(test_objects.BaseObjectsTestCase):
    def setUp(self):
        super(TestVolumeType, self).setUp()
        # NOTE (e0ne): base tests contains original RequestContext from
        # oslo_context. We change it to our RequestContext implementation
        # to have 'elevated' method
        self.context = context.RequestContext(self.user_id, self.project_id,
                                              is_admin=False)

    @staticmethod
    def _compare(test, db, obj):
        for field, value in db.items():
            test.assertEqual(db[field], obj[field])

    @mock.patch('cinder.db.volume_type_get')
    def test_get_by_id(self, volume_type_get):
        db_volume_type = fake_volume.fake_db_volume_type()
        volume_type_get.return_value = db_volume_type
        volume_type = objects.VolumeType.get_by_id(self.context, '1')
        self._compare(self, db_volume_type, volume_type)

    @mock.patch('cinder.volume.volume_types.create')
    def test_create(self, volume_type_create):
        db_volume_type = fake_volume.fake_db_volume_type()
        volume_type_create.return_value = db_volume_type

        volume_type = objects.VolumeType(context=self.context)
        volume_type.name = db_volume_type['name']
        volume_type.extra_specs = db_volume_type['extra_specs']
        volume_type.is_public = db_volume_type['is_public']
        volume_type.projects = db_volume_type['projects']
        volume_type.description = db_volume_type['description']
        volume_type.create()

        volume_type_create.assert_called_once_with(
            self.context, db_volume_type['name'],
            db_volume_type['extra_specs'], db_volume_type['is_public'],
            db_volume_type['projects'], db_volume_type['description'])

    @mock.patch('cinder.volume.volume_types.update')
    def test_save(self, volume_type_update):
        db_volume_type = fake_volume.fake_db_volume_type()
        volume_type = objects.VolumeType._from_db_object(self.context,
                                                         objects.VolumeType(),
                                                         db_volume_type)
        volume_type.description = 'foobar'
        volume_type.save()
        volume_type_update.assert_called_once_with(self.context,
                                                   volume_type.id,
                                                   volume_type.name,
                                                   volume_type.description)

    @mock.patch('cinder.volume.volume_types.destroy')
    def test_destroy(self, volume_type_destroy):
        db_volume_type = fake_volume.fake_db_volume_type()
        volume_type = objects.VolumeType._from_db_object(self.context,
                                                         objects.VolumeType(),
                                                         db_volume_type)
        volume_type.destroy()
        self.assertTrue(volume_type_destroy.called)
        admin_context = volume_type_destroy.call_args[0][0]
        self.assertTrue(admin_context.is_admin)


class TestVolumeTypeList(test_objects.BaseObjectsTestCase):
    @mock.patch('cinder.volume.volume_types.get_all_types')
    def test_get_all(self, get_all_types):
        db_volume_type = fake_volume.fake_db_volume_type()
        get_all_types.return_value = {db_volume_type['name']: db_volume_type}

        volume_types = objects.VolumeTypeList.get_all(self.context)
        self.assertEqual(1, len(volume_types))
        TestVolumeType._compare(self, db_volume_type, volume_types[0])
