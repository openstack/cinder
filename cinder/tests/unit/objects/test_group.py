# Copyright 2016 EMC Corporation
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import mock
import six

from cinder import exception
from cinder import objects
from cinder.objects import fields
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_volume
from cinder.tests.unit import objects as test_objects

fake_group = {
    'id': fake.GROUP_ID,
    'user_id': fake.USER_ID,
    'project_id': fake.PROJECT_ID,
    'host': 'fake_host',
    'availability_zone': 'fake_az',
    'name': 'fake_name',
    'description': 'fake_description',
    'group_type_id': fake.GROUP_TYPE_ID,
    'status': fields.GroupStatus.CREATING,
}


class TestGroup(test_objects.BaseObjectsTestCase):

    @mock.patch('cinder.db.sqlalchemy.api.group_get',
                return_value=fake_group)
    def test_get_by_id(self, group_get):
        group = objects.Group.get_by_id(
            self.context, fake.GROUP_ID)
        self._compare(self, fake_group, group)
        group_get.assert_called_once_with(
            self.context, fake.GROUP_ID)

    @mock.patch('cinder.db.sqlalchemy.api.model_query')
    def test_get_by_id_no_existing_id(self, model_query):
        model_query().filter_by().first.return_value = None
        self.assertRaises(exception.GroupNotFound,
                          objects.Group.get_by_id, self.context,
                          123)

    @mock.patch('cinder.db.group_create',
                return_value=fake_group)
    def test_create(self, group_create):
        fake_grp = fake_group.copy()
        del fake_grp['id']
        group = objects.Group(context=self.context,
                              **fake_grp)
        group.create()
        self._compare(self, fake_group, group)

    def test_create_with_id_except_exception(self, ):
        group = objects.Group(
            context=self.context, **{'id': fake.GROUP_ID})
        self.assertRaises(exception.ObjectActionError, group.create)

    @mock.patch('cinder.db.group_update')
    def test_save(self, group_update):
        group = objects.Group._from_db_object(
            self.context, objects.Group(), fake_group)
        group.status = fields.GroupStatus.AVAILABLE
        group.save()
        group_update.assert_called_once_with(
            self.context,
            group.id,
            {'status': fields.GroupStatus.AVAILABLE})

    def test_save_with_volumes(self):
        group = objects.Group._from_db_object(
            self.context, objects.Group(), fake_group)
        volumes_objs = [objects.Volume(context=self.context, id=i)
                        for i in [fake.VOLUME_ID, fake.VOLUME2_ID,
                                  fake.VOLUME3_ID]]
        volumes = objects.VolumeList(objects=volumes_objs)
        group.name = 'foobar'
        group.volumes = volumes
        self.assertEqual({'name': 'foobar',
                          'volumes': volumes},
                         group.obj_get_changes())
        self.assertRaises(exception.ObjectActionError, group.save)

    @mock.patch('cinder.objects.volume_type.VolumeTypeList.get_all_by_group')
    @mock.patch('cinder.objects.volume.VolumeList.get_all_by_generic_group')
    def test_obj_load_attr(self, mock_vol_get_all_by_group,
                           mock_vol_type_get_all_by_group):
        group = objects.Group._from_db_object(
            self.context, objects.Group(), fake_group)

        # Test volumes lazy-loaded field
        volume_objs = [objects.Volume(context=self.context, id=i)
                       for i in [fake.VOLUME_ID, fake.VOLUME2_ID,
                                 fake.VOLUME3_ID]]
        volumes = objects.VolumeList(context=self.context, objects=volume_objs)
        mock_vol_get_all_by_group.return_value = volumes
        self.assertEqual(volumes, group.volumes)
        mock_vol_get_all_by_group.assert_called_once_with(self.context,
                                                          group.id)

    @mock.patch('cinder.db.group_destroy')
    def test_destroy(self, group_destroy):
        group = objects.Group(
            context=self.context, id=fake.GROUP_ID)
        group.destroy()
        self.assertTrue(group_destroy.called)
        admin_context = group_destroy.call_args[0][0]
        self.assertTrue(admin_context.is_admin)

    @mock.patch('cinder.db.sqlalchemy.api.group_get')
    def test_refresh(self, group_get):
        db_group1 = fake_group.copy()
        db_group2 = db_group1.copy()
        db_group2['description'] = 'foobar'

        # On the second group_get, return the Group with
        # an updated description
        group_get.side_effect = [db_group1, db_group2]
        group = objects.Group.get_by_id(self.context,
                                        fake.GROUP_ID)
        self._compare(self, db_group1, group)

        # description was updated, so a Group refresh should have a
        # new value for that field
        group.refresh()
        self._compare(self, db_group2, group)
        if six.PY3:
            call_bool = mock.call.__bool__()
        else:
            call_bool = mock.call.__nonzero__()
        group_get.assert_has_calls([
            mock.call(
                self.context,
                fake.GROUP_ID),
            call_bool,
            mock.call(
                self.context,
                fake.GROUP_ID)])

    def test_from_db_object_with_all_expected_attributes(self):
        expected_attrs = ['volumes']
        db_volumes = [fake_volume.fake_db_volume(admin_metadata={},
                                                 volume_metadata={})]
        db_group = fake_group.copy()
        db_group['volumes'] = db_volumes
        group = objects.Group._from_db_object(
            self.context, objects.Group(), db_group, expected_attrs)
        self.assertEqual(len(db_volumes), len(group.volumes))
        self._compare(self, db_volumes[0], group.volumes[0])


class TestGroupList(test_objects.BaseObjectsTestCase):
    @mock.patch('cinder.db.group_get_all',
                return_value=[fake_group])
    def test_get_all(self, group_get_all):
        groups = objects.GroupList.get_all(self.context)
        self.assertEqual(1, len(groups))
        TestGroup._compare(self, fake_group,
                           groups[0])

    @mock.patch('cinder.db.group_get_all_by_project',
                return_value=[fake_group])
    def test_get_all_by_project(self, group_get_all_by_project):
        groups = objects.GroupList.get_all_by_project(
            self.context, self.project_id)
        self.assertEqual(1, len(groups))
        TestGroup._compare(self, fake_group,
                           groups[0])

    @mock.patch('cinder.db.group_get_all',
                return_value=[fake_group])
    def test_get_all_with_pagination(self, group_get_all):
        groups = objects.GroupList.get_all(
            self.context, filters={'id': 'fake'}, marker=None, limit=1,
            offset=None, sort_keys='id', sort_dirs='asc')
        self.assertEqual(1, len(groups))
        group_get_all.assert_called_once_with(
            self.context, filters={'id': 'fake'}, marker=None, limit=1,
            offset=None, sort_keys='id', sort_dirs='asc')
        TestGroup._compare(self, fake_group,
                           groups[0])

    @mock.patch('cinder.db.group_get_all_by_project',
                return_value=[fake_group])
    def test_get_all_by_project_with_pagination(
            self, group_get_all_by_project):
        groups = objects.GroupList.get_all_by_project(
            self.context, self.project_id, filters={'id': 'fake'}, marker=None,
            limit=1, offset=None, sort_keys='id', sort_dirs='asc')
        self.assertEqual(1, len(groups))
        group_get_all_by_project.assert_called_once_with(
            self.context, self.project_id, filters={'id': 'fake'}, marker=None,
            limit=1, offset=None, sort_keys='id', sort_dirs='asc')
        TestGroup._compare(self, fake_group,
                           groups[0])
