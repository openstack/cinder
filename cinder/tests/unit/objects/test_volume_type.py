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

from unittest import mock

import ddt
from oslo_utils import timeutils
import pytz

from cinder import db
from cinder.db.sqlalchemy import models
from cinder import objects
from cinder.tests.unit.api.v2 import fakes as v2_fakes
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_volume
from cinder.tests.unit import objects as test_objects


@ddt.ddt
class TestVolumeType(test_objects.BaseObjectsTestCase):

    @mock.patch('cinder.db.sqlalchemy.api._volume_type_get_full')
    def test_get_by_id(self, volume_type_get):
        db_volume_type = fake_volume.fake_db_volume_type()
        volume_type_get.return_value = db_volume_type
        volume_type = objects.VolumeType.get_by_id(self.context,
                                                   fake.VOLUME_TYPE_ID)
        self._compare(self, db_volume_type, volume_type)

    @mock.patch('cinder.db.sqlalchemy.api._volume_type_get_full')
    def test_get_by_id_with_projects(self, volume_type_get):
        projects = [models.VolumeTypeProjects(project_id=fake.PROJECT_ID),
                    models.VolumeTypeProjects(project_id=fake.PROJECT2_ID)]
        db_volume_type = fake_volume.fake_db_volume_type(projects=projects)
        volume_type_get.return_value = db_volume_type
        volume_type = objects.VolumeType.get_by_id(self.context,
                                                   fake.VOLUME_TYPE_ID)
        db_volume_type['projects'] = [p.project_id for p in projects]
        self._compare(self, db_volume_type, volume_type)

    @mock.patch('cinder.db.sqlalchemy.api._volume_type_get_full')
    def test_get_by_id_with_string_projects(self, volume_type_get):
        projects = [fake.PROJECT_ID, fake.PROJECT2_ID]
        db_volume_type = fake_volume.fake_db_volume_type(projects=projects)
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

    @mock.patch('cinder.volume.volume_types.get_by_name_or_id')
    def test_get_by_name_or_id(self, volume_type_get):
        db_volume_type = fake_volume.fake_db_volume_type()
        volume_type_get.return_value = db_volume_type
        volume_type = objects.VolumeType.get_by_name_or_id(
            self.context, fake.VOLUME_TYPE_ID)
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

    @mock.patch('oslo_utils.timeutils.utcnow', return_value=timeutils.utcnow())
    @mock.patch('cinder.db.sqlalchemy.api.volume_type_destroy')
    @mock.patch.object(db.sqlalchemy.api, 'volume_type_get',
                       v2_fakes.fake_volume_type_get)
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
        volume_type_get.assert_has_calls([mock.call(self.context,
                                                    fake.VOLUME_TYPE_ID),
                                          mock.call.__bool__(),
                                          mock.call(self.context,
                                                    fake.VOLUME_TYPE_ID)])

    @mock.patch('cinder.objects.QualityOfServiceSpecs.get_by_id')
    @mock.patch('cinder.db.sqlalchemy.api._volume_type_get')
    def test_lazy_loading_qos(self, get_mock, qos_get_mock):
        qos_get_mock.return_value = objects.QualityOfServiceSpecs(
            id=fake.QOS_SPEC_ID)
        vol_type = fake_volume.fake_db_volume_type(
            qos_specs_id=fake.QOS_SPEC_ID)
        get_mock.return_value = vol_type

        volume_type = objects.VolumeType.get_by_id(self.context,
                                                   vol_type['id'])
        self._compare(self, qos_get_mock.return_value, volume_type.qos_specs)
        qos_get_mock.assert_called_once_with(self.context, fake.QOS_SPEC_ID)

    @mock.patch('cinder.db.volume_type_access_get_all')
    @mock.patch('cinder.db.sqlalchemy.api._volume_type_get')
    def test_lazy_loading_projects(self, get_mock, get_projects_mock):
        vol_type = fake_volume.fake_db_volume_type(
            qos_specs_id=fake.QOS_SPEC_ID)
        get_mock.return_value = vol_type

        projects = [models.VolumeTypeProjects(project_id=fake.PROJECT_ID),
                    models.VolumeTypeProjects(project_id=fake.PROJECT2_ID)]
        get_projects_mock.return_value = projects

        volume_type = objects.VolumeType.get_by_id(self.context,
                                                   vol_type['id'])
        # Simulate this type has been loaded by a volume get_all method
        del volume_type.projects

        self.assertEqual([p.project_id for p in projects],
                         volume_type.projects)
        get_projects_mock.assert_called_once_with(self.context, vol_type['id'])

    @mock.patch('cinder.db.volume_type_extra_specs_get')
    @mock.patch('cinder.db.sqlalchemy.api._volume_type_get')
    def test_lazy_loading_extra_specs(self, get_mock, get_specs_mock):
        get_specs_mock.return_value = {'key': 'value', 'key2': 'value2'}
        vol_type = fake_volume.fake_db_volume_type(
            qos_specs_id=fake.QOS_SPEC_ID)
        get_mock.return_value = vol_type

        volume_type = objects.VolumeType.get_by_id(self.context,
                                                   vol_type['id'])
        # Simulate this type has been loaded by a volume get_all method
        del volume_type.extra_specs

        self.assertEqual(get_specs_mock.return_value, volume_type.extra_specs)
        get_specs_mock.assert_called_once_with(self.context, vol_type['id'])

    @ddt.data('<is> True', '<is> true', '<is> yes')
    def test_is_replicated_true(self, enabled):
        volume_type = fake_volume.fake_volume_type_obj(
            self.context, extra_specs={'replication_enabled': enabled})
        self.assertTrue(volume_type.is_replicated())

    def test_is_replicated_no_specs(self):
        volume_type = fake_volume.fake_volume_type_obj(
            self.context, extra_specs={})
        self.assertFalse(bool(volume_type.is_replicated()))

    @ddt.data('<is> False', '<is> false', '<is> f', 'baddata', 'bad data')
    def test_is_replicated_specs_false(self, not_enabled):
        volume_type = fake_volume.fake_volume_type_obj(
            self.context, extra_specs={'replication_enabled': not_enabled})
        self.assertFalse(volume_type.is_replicated())

    @ddt.data('<is> False', '<is> false', '<is> f')
    def test_is_multiattach_specs_false(self, false):
        volume_type = fake_volume.fake_volume_type_obj(
            self.context, extra_specs={'multiattach': false})
        self.assertFalse(volume_type.is_multiattach())

    @ddt.data('<is> True', '<is>   True')
    def test_is_multiattach_specs_true(self, true):
        volume_type = fake_volume.fake_volume_type_obj(
            self.context, extra_specs={'multiattach': true})
        self.assertTrue(volume_type.is_multiattach())


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
