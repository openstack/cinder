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

from unittest import mock


from cinder import objects
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_group
from cinder.tests.unit import objects as test_objects


class TestGroupType(test_objects.BaseObjectsTestCase):

    @mock.patch('cinder.db.sqlalchemy.api._group_type_get_full')
    def test_get_by_id(self, group_type_get):
        db_group_type = fake_group.fake_db_group_type()
        group_type_get.return_value = db_group_type
        group_type = objects.GroupType.get_by_id(self.context,
                                                 fake.GROUP_TYPE_ID)
        self._compare(self, db_group_type, group_type)

    @mock.patch('cinder.volume.group_types.create')
    def test_create(self, group_type_create):
        db_group_type = fake_group.fake_db_group_type()
        group_type_create.return_value = db_group_type

        group_type = objects.GroupType(context=self.context)
        group_type.name = db_group_type['name']
        group_type.group_specs = db_group_type['group_specs']
        group_type.is_public = db_group_type['is_public']
        group_type.projects = db_group_type['projects']
        group_type.description = db_group_type['description']
        group_type.create()

        group_type_create.assert_called_once_with(
            self.context, db_group_type['name'],
            db_group_type['group_specs'], db_group_type['is_public'],
            db_group_type['projects'], db_group_type['description'])

    @mock.patch('cinder.volume.group_types.update')
    def test_save(self, group_type_update):
        db_group_type = fake_group.fake_db_group_type()
        group_type = objects.GroupType._from_db_object(self.context,
                                                       objects.GroupType(),
                                                       db_group_type)
        group_type.description = 'foobar'
        group_type.save()
        group_type_update.assert_called_once_with(self.context,
                                                  group_type.id,
                                                  group_type.name,
                                                  group_type.description)

    @mock.patch('cinder.volume.group_types.destroy')
    def test_destroy(self, group_type_destroy):
        db_group_type = fake_group.fake_db_group_type()
        group_type = objects.GroupType._from_db_object(self.context,
                                                       objects.GroupType(),
                                                       db_group_type)
        group_type.destroy()
        self.assertTrue(group_type_destroy.called)
        admin_context = group_type_destroy.call_args[0][0]
        self.assertTrue(admin_context.is_admin)

    @mock.patch('cinder.db.sqlalchemy.api._group_type_get_full')
    def test_refresh(self, group_type_get):
        db_type1 = fake_group.fake_db_group_type()
        db_type2 = db_type1.copy()
        db_type2['description'] = 'foobar'

        # updated description
        group_type_get.side_effect = [db_type1, db_type2]
        group_type = objects.GroupType.get_by_id(self.context,
                                                 fake.GROUP_TYPE_ID)
        self._compare(self, db_type1, group_type)

        # description was updated, so a group type refresh should have a new
        # value for that field
        group_type.refresh()
        self._compare(self, db_type2, group_type)
        group_type_get.assert_has_calls([mock.call(self.context,
                                                   fake.GROUP_TYPE_ID),
                                         mock.call.__bool__(),
                                         mock.call(self.context,
                                                   fake.GROUP_TYPE_ID)])


class TestGroupTypeList(test_objects.BaseObjectsTestCase):
    @mock.patch('cinder.volume.group_types.get_all_group_types')
    def test_get_all(self, get_all_types):
        db_group_type = fake_group.fake_db_group_type()
        get_all_types.return_value = {db_group_type['name']: db_group_type}

        group_types = objects.GroupTypeList.get_all(self.context)
        self.assertEqual(1, len(group_types))
        TestGroupType._compare(self, db_group_type, group_types[0])

    @mock.patch('cinder.volume.group_types.get_all_group_types')
    def test_get_all_with_pagination(self, get_all_types):
        db_group_type = fake_group.fake_db_group_type()
        get_all_types.return_value = {db_group_type['name']: db_group_type}

        group_types = objects.GroupTypeList.get_all(self.context,
                                                    filters={'is_public':
                                                             True},
                                                    marker=None,
                                                    limit=1,
                                                    sort_keys='id',
                                                    sort_dirs='desc',
                                                    offset=None)
        self.assertEqual(1, len(group_types))
        TestGroupType._compare(self, db_group_type, group_types[0])
