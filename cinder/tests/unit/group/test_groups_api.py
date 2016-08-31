# Copyright (C) 2016 EMC Corporation.
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

"""
Tests for group API.
"""

import ddt
import mock

from cinder import context
import cinder.group
from cinder import objects
from cinder.objects import fields
from cinder import test
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import utils


@ddt.ddt
class GroupAPITestCase(test.TestCase):
    """Test Case for group API."""

    def setUp(self):
        super(GroupAPITestCase, self).setUp()
        self.group_api = cinder.group.API()
        self.ctxt = context.RequestContext(fake.USER_ID, fake.PROJECT_ID,
                                           auth_token=True,
                                           is_admin=True)
        self.user_ctxt = context.RequestContext(
            fake.USER_ID, fake.PROJECT_ID, auth_token=True)

    @mock.patch('cinder.objects.Group.get_by_id')
    @mock.patch('cinder.group.api.check_policy')
    def test_get(self, mock_policy, mock_group_get):
        fake_group = 'fake_group'
        mock_group_get.return_value = fake_group
        grp = self.group_api.get(self.ctxt, fake.GROUP_ID)
        self.assertEqual(fake_group, grp)

    @ddt.data(True, False)
    @mock.patch('cinder.objects.GroupList.get_all')
    @mock.patch('cinder.objects.GroupList.get_all_by_project')
    @mock.patch('cinder.group.api.check_policy')
    def test_get_all(self, is_admin, mock_policy, mock_get_all_by_project,
                     mock_get_all):
        self.group_api.LOG = mock.Mock()
        fake_groups = ['fake_group1', 'fake_group2']
        fake_groups_by_project = ['fake_group1']
        mock_get_all.return_value = fake_groups
        mock_get_all_by_project.return_value = fake_groups_by_project

        if is_admin:
            grps = self.group_api.get_all(self.ctxt,
                                          filters={'all_tenants': True})
            self.assertEqual(fake_groups, grps)
        else:
            grps = self.group_api.get_all(self.user_ctxt)
            self.assertEqual(fake_groups_by_project, grps)

    @mock.patch('cinder.volume.rpcapi.VolumeAPI.delete_group')
    @mock.patch('cinder.db.volume_get_all_by_generic_group')
    @mock.patch('cinder.db.volumes_update')
    @mock.patch('cinder.group.api.API._cast_create_group')
    @mock.patch('cinder.group.api.API.update_quota')
    @mock.patch('cinder.objects.Group')
    @mock.patch('cinder.db.group_type_get')
    @mock.patch('cinder.db.volume_types_get_by_name_or_id')
    @mock.patch('cinder.group.api.check_policy')
    def test_create_delete(self, mock_policy, mock_volume_types_get,
                           mock_group_type_get, mock_group,
                           mock_update_quota, mock_cast_create_group,
                           mock_volumes_update, mock_volume_get_all,
                           mock_rpc_delete_group):
        mock_volume_types_get.return_value = [{'id': fake.VOLUME_TYPE_ID}]
        mock_group_type_get.return_value = {'id': fake.GROUP_TYPE_ID}
        name = "test_group"
        description = "this is a test group"
        grp = utils.create_group(self.ctxt, group_type_id = fake.GROUP_TYPE_ID,
                                 volume_type_ids = [fake.VOLUME_TYPE_ID],
                                 availability_zone = 'nova', host = None,
                                 name = name, description = description,
                                 status = fields.GroupStatus.CREATING)
        mock_group.return_value = grp

        ret_group = self.group_api.create(self.ctxt, name, description,
                                          fake.GROUP_TYPE_ID,
                                          [fake.VOLUME_TYPE_ID],
                                          availability_zone = 'nova')
        self.assertEqual(grp.obj_to_primitive(), ret_group.obj_to_primitive())

        ret_group.host = "test_host@fakedrv#fakepool"
        ret_group.status = fields.GroupStatus.AVAILABLE
        self.group_api.delete(self.ctxt, ret_group, delete_volumes = True)
        mock_volume_get_all.assert_called_once_with(mock.ANY, ret_group.id)
        mock_volumes_update.assert_called_once_with(self.ctxt, [])
        mock_rpc_delete_group.assert_called_once_with(self.ctxt, ret_group)

    @mock.patch('cinder.volume.rpcapi.VolumeAPI.update_group')
    @mock.patch('cinder.db.volume_get_all_by_generic_group')
    @mock.patch('cinder.group.api.API._cast_create_group')
    @mock.patch('cinder.group.api.API.update_quota')
    @mock.patch('cinder.objects.Group')
    @mock.patch('cinder.db.group_type_get')
    @mock.patch('cinder.db.volume_types_get_by_name_or_id')
    @mock.patch('cinder.group.api.check_policy')
    def test_update(self, mock_policy, mock_volume_types_get,
                    mock_group_type_get, mock_group,
                    mock_update_quota, mock_cast_create_group,
                    mock_volume_get_all, mock_rpc_update_group):
        vol_type_dict = {'id': fake.VOLUME_TYPE_ID,
                         'name': 'fake_volume_type'}
        vol_type = objects.VolumeType(self.ctxt, **vol_type_dict)

        mock_volume_types_get.return_value = [{'id': fake.VOLUME_TYPE_ID}]
        mock_group_type_get.return_value = {'id': fake.GROUP_TYPE_ID}
        name = "test_group"
        description = "this is a test group"
        grp = utils.create_group(self.ctxt, group_type_id = fake.GROUP_TYPE_ID,
                                 volume_type_ids = [fake.VOLUME_TYPE_ID],
                                 availability_zone = 'nova', host = None,
                                 name = name, description = description,
                                 status = fields.GroupStatus.CREATING)
        mock_group.return_value = grp

        ret_group = self.group_api.create(self.ctxt, name, description,
                                          fake.GROUP_TYPE_ID,
                                          [fake.VOLUME_TYPE_ID],
                                          availability_zone = 'nova')
        self.assertEqual(grp.obj_to_primitive(), ret_group.obj_to_primitive())

        ret_group.volume_types = [vol_type]
        ret_group.host = "test_host@fakedrv#fakepool"
        ret_group.status = fields.GroupStatus.AVAILABLE
        ret_group.id = fake.GROUP_ID

        vol1 = utils.create_volume(
            self.ctxt, host = ret_group.host,
            availability_zone = ret_group.availability_zone,
            volume_type_id = fake.VOLUME_TYPE_ID)

        vol2 = utils.create_volume(
            self.ctxt, host = ret_group.host,
            availability_zone = ret_group.availability_zone,
            volume_type_id = fake.VOLUME_TYPE_ID,
            group_id = fake.GROUP_ID)
        vol2_dict = {
            'id': vol2.id,
            'group_id': fake.GROUP_ID,
            'volume_type_id': fake.VOLUME_TYPE_ID,
            'availability_zone': ret_group.availability_zone,
            'host': ret_group.host,
            'status': 'available',
        }
        mock_volume_get_all.return_value = [vol2_dict]

        new_name = "new_group_name"
        new_desc = "this is a new group"
        self.group_api.update(self.ctxt, ret_group, new_name, new_desc,
                              vol1.id, vol2.id)
        mock_volume_get_all.assert_called_once_with(mock.ANY, ret_group.id)
        mock_rpc_update_group.assert_called_once_with(self.ctxt, ret_group,
                                                      add_volumes = vol1.id,
                                                      remove_volumes = vol2.id)
