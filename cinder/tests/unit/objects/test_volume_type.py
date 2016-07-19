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
from oslo_utils import timeutils
import pytz
import six

from cinder import objects
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_volume
from cinder.tests.unit import objects as test_objects


class TestVolumeType(test_objects.BaseObjectsTestCase):

    @mock.patch('cinder.db.sqlalchemy.api._volume_type_get_full')
    def test_get_by_id(self, volume_type_get):
        db_volume_type = fake_volume.fake_db_volume_type()
        volume_type_get.return_value = db_volume_type
        volume_type = objects.VolumeType.get_by_id(self.context,
                                                   fake.VOLUME_TYPE_ID)
        self._compare(self, db_volume_type, volume_type)

    @mock.patch('cinder.db.sqlalchemy.api._volume_type_get_full')
    def test_get_by_id_null_spec(self, volume_type_get):
        db_volume_type = fake_volume.fake_db_volume_type(
            extra_specs={'foo': None})
        volume_type_get.return_value = db_volume_type
        volume_type = objects.VolumeType.get_by_id(self.context,
                                                   fake.VOLUME_TYPE_ID)
        self._compare(self, db_volume_type, volume_type)

    def test_obj_make_compatible(self):
        volume_type = objects.VolumeType(context=self.context)
        volume_type.extra_specs = {'foo': None, 'bar': 'baz'}
        primitive = volume_type.obj_to_primitive('1.0')
        volume_type = objects.VolumeType.obj_from_primitive(primitive)
        self.assertEqual('', volume_type.extra_specs['foo'])
        self.assertEqual('baz', volume_type.extra_specs['bar'])

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

    @mock.patch('oslo_utils.timeutils.utcnow', return_value=timeutils.utcnow())
    @mock.patch('cinder.db.sqlalchemy.api.volume_type_destroy')
    def test_destroy(self, volume_type_destroy, utcnow_mock):
        volume_type_destroy.return_value = {
            'deleted': True,
            'deleted_at': utcnow_mock.return_value}
        db_volume_type = fake_volume.fake_db_volume_type()
        volume_type = objects.VolumeType._from_db_object(self.context,
                                                         objects.VolumeType(),
                                                         db_volume_type)
        volume_type.destroy()
        self.assertTrue(volume_type_destroy.called)
        admin_context = volume_type_destroy.call_args[0][0]
        self.assertTrue(admin_context.is_admin)
        self.assertTrue(volume_type.deleted)
        self.assertEqual(utcnow_mock.return_value.replace(tzinfo=pytz.UTC),
                         volume_type.deleted_at)

    @mock.patch('cinder.db.sqlalchemy.api._volume_type_get_full')
    def test_refresh(self, volume_type_get):
        db_type1 = fake_volume.fake_db_volume_type()
        db_type2 = db_type1.copy()
        db_type2['description'] = 'foobar'

        # updated description
        volume_type_get.side_effect = [db_type1, db_type2]
        volume_type = objects.VolumeType.get_by_id(self.context,
                                                   fake.VOLUME_TYPE_ID)
        self._compare(self, db_type1, volume_type)

        # description was updated, so a volume type refresh should have a new
        # value for that field
        volume_type.refresh()
        self._compare(self, db_type2, volume_type)
        if six.PY3:
            call_bool = mock.call.__bool__()
        else:
            call_bool = mock.call.__nonzero__()
        volume_type_get.assert_has_calls([mock.call(self.context,
                                                    fake.VOLUME_TYPE_ID),
                                          call_bool,
                                          mock.call(self.context,
                                                    fake.VOLUME_TYPE_ID)])


class TestVolumeTypeList(test_objects.BaseObjectsTestCase):
    @mock.patch('cinder.volume.volume_types.get_all_types')
    def test_get_all(self, get_all_types):
        db_volume_type = fake_volume.fake_db_volume_type()
        get_all_types.return_value = {db_volume_type['name']: db_volume_type}

        volume_types = objects.VolumeTypeList.get_all(self.context)
        self.assertEqual(1, len(volume_types))
        TestVolumeType._compare(self, db_volume_type, volume_types[0])

    @mock.patch('cinder.volume.volume_types.get_all_types')
    def test_get_all_with_pagination(self, get_all_types):
        db_volume_type = fake_volume.fake_db_volume_type()
        get_all_types.return_value = {db_volume_type['name']: db_volume_type}

        volume_types = objects.VolumeTypeList.get_all(self.context,
                                                      filters={'is_public':
                                                               True},
                                                      marker=None,
                                                      limit=1,
                                                      sort_keys='id',
                                                      sort_dirs='desc',
                                                      offset=None)
        self.assertEqual(1, len(volume_types))
        TestVolumeType._compare(self, db_volume_type, volume_types[0])
