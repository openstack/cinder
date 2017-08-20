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
Tests for group code.
"""

import ddt
import mock
from six.moves import http_client
import webob

from cinder.api.v3 import groups as v3_groups
from cinder import context
from cinder import db
from cinder import exception
import cinder.group
from cinder import objects
from cinder.objects import fields
from cinder import test
from cinder.tests.unit.api import fakes
from cinder.tests.unit.api.v3 import fakes as v3_fakes
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import utils
from cinder.volume import api as volume_api

GROUP_MICRO_VERSION = '3.13'
GROUP_FROM_SRC_MICRO_VERSION = '3.14'
GROUP_REPLICATION_MICRO_VERSION = '3.38'
INVALID_GROUP_REPLICATION_MICRO_VERSION = '3.37'


@ddt.ddt
class GroupsAPITestCase(test.TestCase):
    """Test Case for groups API."""

    def setUp(self):
        super(GroupsAPITestCase, self).setUp()
        self.controller = v3_groups.GroupsController()
        self.group_api = cinder.group.API()
        self.ctxt = context.RequestContext(fake.USER_ID, fake.PROJECT_ID,
                                           auth_token=True,
                                           is_admin=True)
        self.user_ctxt = context.RequestContext(
            fake.USER_ID, fake.PROJECT_ID, auth_token=True)
        self.volume_type1 = self._create_volume_type(id=fake.VOLUME_TYPE_ID)
        self.group1 = self._create_group()
        self.group2 = self._create_group()
        self.group3 = self._create_group(ctxt=self.user_ctxt)
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        self.group1.destroy()
        self.group2.destroy()
        self.group3.destroy()
        db.volume_type_destroy(self.ctxt, self.volume_type1.id)

    def _create_group(
            self,
            ctxt=None,
            name='test_group',
            description='this is a test group',
            group_type_id=fake.GROUP_TYPE_ID,
            volume_type_ids=[fake.VOLUME_TYPE_ID],
            availability_zone='az1',
            host='fakehost',
            status=fields.GroupStatus.CREATING,
            replication_status=fields.ReplicationStatus.DISABLED,
            **kwargs):
        """Create a group object."""
        ctxt = ctxt or self.ctxt
        group = objects.Group(ctxt)
        group.user_id = fake.USER_ID
        group.project_id = fake.PROJECT_ID
        group.availability_zone = availability_zone
        group.name = name
        group.description = description
        group.group_type_id = group_type_id
        group.volume_type_ids = volume_type_ids
        group.host = host
        group.status = status
        group.replication_status = replication_status
        group.update(kwargs)
        group.create()
        return group

    def _create_volume_type(
            self,
            ctxt=None,
            id=fake.VOLUME_TYPE_ID,
            name='test_volume_type',
            description='this is a test volume type',
            extra_specs={"test_key": "test_val"},
            testcase_instance=None,
            **kwargs):
        """Create a volume type."""
        ctxt = ctxt or self.ctxt
        vol_type = utils.create_volume_type(
            ctxt,
            testcase_instance=testcase_instance,
            id=id,
            name=name,
            description=description,
            extra_specs=extra_specs,
            **kwargs)
        return vol_type

    @mock.patch('cinder.objects.volume_type.VolumeTypeList.get_all_by_group')
    @mock.patch('cinder.objects.volume.VolumeList.get_all_by_generic_group')
    def test_show_group(self, mock_vol_get_all_by_group,
                        mock_vol_type_get_all_by_group):
        volume_objs = [objects.Volume(context=self.ctxt, id=i)
                       for i in [fake.VOLUME_ID]]
        volumes = objects.VolumeList(context=self.ctxt, objects=volume_objs)
        mock_vol_get_all_by_group.return_value = volumes

        vol_type_objs = [objects.VolumeType(context=self.ctxt, id=i)
                         for i in [fake.VOLUME_TYPE_ID]]
        vol_types = objects.VolumeTypeList(context=self.ctxt,
                                           objects=vol_type_objs)
        mock_vol_type_get_all_by_group.return_value = vol_types

        req = fakes.HTTPRequest.blank('/v3/%s/groups/%s' %
                                      (fake.PROJECT_ID, self.group1.id),
                                      version=GROUP_MICRO_VERSION)
        res_dict = self.controller.show(req, self.group1.id)

        self.assertEqual(1, len(res_dict))
        self.assertEqual('az1',
                         res_dict['group']['availability_zone'])
        self.assertEqual('this is a test group',
                         res_dict['group']['description'])
        self.assertEqual('test_group',
                         res_dict['group']['name'])
        self.assertEqual('creating',
                         res_dict['group']['status'])
        self.assertEqual([fake.VOLUME_TYPE_ID],
                         res_dict['group']['volume_types'])

    @ddt.data(('3.24', False), ('3.24', True), ('3.25', False), ('3.25', True))
    @ddt.unpack
    @mock.patch('cinder.objects.volume_type.VolumeTypeList.get_all_by_group')
    @mock.patch('cinder.objects.volume.VolumeList.get_all_by_generic_group')
    def test_list_group_with_list_volume(self, version, has_list_volume,
                                         mock_vol_get_all_by_group,
                                         mock_vol_type_get_all_by_group):
        volume_objs = [objects.Volume(context=self.ctxt, id=i)
                       for i in [fake.VOLUME_ID]]
        volumes = objects.VolumeList(context=self.ctxt, objects=volume_objs)
        mock_vol_get_all_by_group.return_value = volumes

        vol_type_objs = [objects.VolumeType(context=self.ctxt, id=i)
                         for i in [fake.VOLUME_TYPE_ID]]
        vol_types = objects.VolumeTypeList(context=self.ctxt,
                                           objects=vol_type_objs)
        mock_vol_type_get_all_by_group.return_value = vol_types

        if has_list_volume:
            req = fakes.HTTPRequest.blank(
                '/v3/%s/groups/detail?list_volume=True' % fake.PROJECT_ID,
                version=version)
        else:
            req = fakes.HTTPRequest.blank('/v3/%s/groups/detail' %
                                          fake.PROJECT_ID,
                                          version=version)
        res_dict = self.controller.detail(req)

        # If the microversion >= 3.25 and "list_volume=True", "volumes" should
        # be contained in the response body. Else,"volumes" should not be
        # contained in the response body.
        self.assertEqual(3, len(res_dict['groups']))
        if (version, has_list_volume) == ('3.25', True):
            self.assertEqual([fake.VOLUME_ID],
                             res_dict['groups'][0]['volumes'])
        else:
            self.assertIsNone(res_dict['groups'][0].get('volumes', None))

        # "volumes" should not be contained in the response body when list
        # groups without detail.
        res_dict = self.controller.index(req)
        self.assertIsNone(res_dict['groups'][0].get('volumes', None))

    @mock.patch('cinder.objects.volume_type.VolumeTypeList.get_all_by_group')
    @mock.patch('cinder.objects.volume.VolumeList.get_all_by_generic_group')
    def test_show_group_with_list_volume(self, mock_vol_get_all_by_group,
                                         mock_vol_type_get_all_by_group):
        volume_objs = [objects.Volume(context=self.ctxt, id=i)
                       for i in [fake.VOLUME_ID]]
        volumes = objects.VolumeList(context=self.ctxt, objects=volume_objs)
        mock_vol_get_all_by_group.return_value = volumes

        vol_type_objs = [objects.VolumeType(context=self.ctxt, id=i)
                         for i in [fake.VOLUME_TYPE_ID]]
        vol_types = objects.VolumeTypeList(context=self.ctxt,
                                           objects=vol_type_objs)
        mock_vol_type_get_all_by_group.return_value = vol_types

        # If the microversion >= 3.25 and "list_volume=True", "volumes" should
        # be contained in the response body.
        req = fakes.HTTPRequest.blank('/v3/%s/groups/%s?list_volume=True' %
                                      (fake.PROJECT_ID, self.group1.id),
                                      version='3.25')
        res_dict = self.controller.show(req, self.group1.id)
        self.assertEqual(1, len(res_dict))
        self.assertEqual([fake.VOLUME_ID],
                         res_dict['group']['volumes'])

        # If the microversion >= 3.25 but "list_volume" is missing, "volumes"
        # should not be contained in the response body.
        req = fakes.HTTPRequest.blank('/v3/%s/groups/%s' %
                                      (fake.PROJECT_ID, self.group1.id),
                                      version='3.25')
        res_dict = self.controller.show(req, self.group1.id)
        self.assertEqual(1, len(res_dict))
        self.assertIsNone(res_dict['group'].get('volumes', None))

        # If the microversion < 3.25, "volumes" should not be contained in the
        # response body.
        req = fakes.HTTPRequest.blank('/v3/%s/groups/%s?list_volume=True' %
                                      (fake.PROJECT_ID, self.group1.id),
                                      version='3.24')
        res_dict = self.controller.show(req, self.group1.id)
        self.assertEqual(1, len(res_dict))
        self.assertIsNone(res_dict['group'].get('volumes', None))

    def test_show_group_with_group_NotFound(self):
        req = fakes.HTTPRequest.blank('/v3/%s/groups/%s' %
                                      (fake.PROJECT_ID,
                                       fake.WILL_NOT_BE_FOUND_ID),
                                      version=GROUP_MICRO_VERSION)
        self.assertRaises(exception.GroupNotFound, self.controller.show,
                          req, fake.WILL_NOT_BE_FOUND_ID)

    @ddt.data('3.30', '3.31', '3.34')
    @mock.patch('cinder.api.common.reject_invalid_filters')
    def test_group_list_with_general_filter(self, version, mock_update):
        url = '/v3/%s/groups' % fake.PROJECT_ID
        req = fakes.HTTPRequest.blank(url,
                                      version=version,
                                      use_admin_context=False)
        self.controller.index(req)

        if version != '3.30':
            support_like = True if version == '3.34' else False
            mock_update.assert_called_once_with(req.environ['cinder.context'],
                                                mock.ANY, 'group',
                                                support_like)

    def test_list_groups_json(self):
        self.group2.group_type_id = fake.GROUP_TYPE2_ID
        # TODO(geguileo): One `volume_type_ids` gets sorted out make proper
        # changes here
        # self.group2.volume_type_ids = [fake.VOLUME_TYPE2_ID]

        self.group2.save()

        self.group3.group_type_id = fake.GROUP_TYPE3_ID
        # TODO(geguileo): One `volume_type_ids` gets sorted out make proper
        # changes here
        # self.group3.volume_type_ids = [fake.VOLUME_TYPE3_ID]
        self.group3.save()

        req = fakes.HTTPRequest.blank('/v3/%s/groups' % fake.PROJECT_ID,
                                      version=GROUP_MICRO_VERSION)
        res_dict = self.controller.index(req)

        self.assertEqual(1, len(res_dict))
        self.assertEqual(self.group3.id,
                         res_dict['groups'][0]['id'])
        self.assertEqual('test_group',
                         res_dict['groups'][0]['name'])
        self.assertEqual(self.group2.id,
                         res_dict['groups'][1]['id'])
        self.assertEqual('test_group',
                         res_dict['groups'][1]['name'])
        self.assertEqual(self.group1.id,
                         res_dict['groups'][2]['id'])
        self.assertEqual('test_group',
                         res_dict['groups'][2]['name'])

    @ddt.data(False, True)
    def test_list_groups_with_limit(self, is_detail):
        url = '/v3/%s/groups?limit=1' % fake.PROJECT_ID
        if is_detail:
            url = '/v3/%s/groups/detail?limit=1' % fake.PROJECT_ID
        req = fakes.HTTPRequest.blank(url, version=GROUP_MICRO_VERSION)

        if is_detail:
            res_dict = self.controller.detail(req)
        else:
            res_dict = self.controller.index(req)

        self.assertEqual(2, len(res_dict))
        self.assertEqual(1, len(res_dict['groups']))
        self.assertEqual(self.group3.id,
                         res_dict['groups'][0]['id'])
        next_link = (
            'http://localhost/v3/%s/groups?limit='
            '1&marker=%s' %
            (fake.PROJECT_ID, res_dict['groups'][0]['id']))
        self.assertEqual(next_link,
                         res_dict['group_links'][0]['href'])
        if is_detail:
            self.assertIn('description', res_dict['groups'][0].keys())

    @ddt.data(False, True)
    def test_list_groups_with_offset(self, is_detail):
        url = '/v3/%s/groups?offset=1' % fake.PROJECT_ID
        if is_detail:
            url = '/v3/%s/groups/detail?offset=1' % fake.PROJECT_ID
        req = fakes.HTTPRequest.blank(url, version=GROUP_MICRO_VERSION)
        res_dict = self.controller.index(req)

        self.assertEqual(1, len(res_dict))
        self.assertEqual(2, len(res_dict['groups']))
        self.assertEqual(self.group2.id,
                         res_dict['groups'][0]['id'])
        self.assertEqual(self.group1.id,
                         res_dict['groups'][1]['id'])

    @ddt.data(False, True)
    def test_list_groups_with_offset_out_of_range(self, is_detail):
        url = ('/v3/%s/groups?offset=234523423455454' %
               fake.PROJECT_ID)
        if is_detail:
            url = ('/v3/%s/groups/detail?offset=234523423455454' %
                   fake.PROJECT_ID)
        req = fakes.HTTPRequest.blank(url, version=GROUP_MICRO_VERSION)
        if is_detail:
            self.assertRaises(webob.exc.HTTPBadRequest, self.controller.detail,
                              req)
        else:
            self.assertRaises(webob.exc.HTTPBadRequest, self.controller.index,
                              req)

    @ddt.data(False, True)
    def test_list_groups_with_limit_and_offset(self, is_detail):
        url = '/v3/%s/groups?limit=2&offset=1' % fake.PROJECT_ID
        if is_detail:
            url = ('/v3/%s/groups/detail?limit=2&offset=1' %
                   fake.PROJECT_ID)
        req = fakes.HTTPRequest.blank(url, version=GROUP_MICRO_VERSION)

        if is_detail:
            res_dict = self.controller.detail(req)
        else:
            res_dict = self.controller.index(req)

        self.assertEqual(2, len(res_dict))
        self.assertEqual(2, len(res_dict['groups']))
        self.assertEqual(self.group2.id,
                         res_dict['groups'][0]['id'])
        self.assertEqual(self.group1.id,
                         res_dict['groups'][1]['id'])
        if is_detail:
            self.assertIn('description', res_dict['groups'][0].keys())

    @ddt.data(False, True)
    def test_list_groups_with_filter(self, is_detail):
        # Create a group with user context
        url = ('/v3/%s/groups?'
               'all_tenants=True&id=%s') % (fake.PROJECT_ID,
                                            self.group3.id)
        if is_detail:
            url = ('/v3/%s/groups/detail?'
                   'all_tenants=True&id=%s') % (fake.PROJECT_ID,
                                                self.group3.id)
        req = fakes.HTTPRequest.blank(url, version=GROUP_MICRO_VERSION,
                                      use_admin_context=True)

        if is_detail:
            res_dict = self.controller.detail(req)
        else:
            res_dict = self.controller.index(req)

        self.assertEqual(1, len(res_dict))
        self.assertEqual(1, len(res_dict['groups']))
        self.assertEqual(self.group3.id,
                         res_dict['groups'][0]['id'])
        if is_detail:
            self.assertIn('description', res_dict['groups'][0].keys())

    @ddt.data(False, True)
    def test_list_groups_with_sort(self, is_detail):
        url = '/v3/%s/groups?sort=id:asc' % fake.PROJECT_ID
        if is_detail:
            url = ('/v3/%s/groups/detail?sort=id:asc' %
                   fake.PROJECT_ID)
        req = fakes.HTTPRequest.blank(url, version=GROUP_MICRO_VERSION)
        expect_result = [self.group1.id, self.group2.id,
                         self.group3.id]
        expect_result.sort()

        if is_detail:
            res_dict = self.controller.detail(req)
        else:
            res_dict = self.controller.index(req)

        self.assertEqual(1, len(res_dict))
        self.assertEqual(3, len(res_dict['groups']))
        self.assertEqual(expect_result[0],
                         res_dict['groups'][0]['id'])
        self.assertEqual(expect_result[1],
                         res_dict['groups'][1]['id'])
        self.assertEqual(expect_result[2],
                         res_dict['groups'][2]['id'])
        if is_detail:
            self.assertIn('description', res_dict['groups'][0].keys())

    @mock.patch('cinder.objects.volume_type.VolumeTypeList.get_all_by_group')
    def test_list_groups_detail_json(self, mock_vol_type_get_all_by_group):
        volume_type_ids = [fake.VOLUME_TYPE_ID, fake.VOLUME_TYPE2_ID]
        vol_type_objs = [objects.VolumeType(context=self.ctxt, id=i)
                         for i in volume_type_ids]
        vol_types = objects.VolumeTypeList(context=self.ctxt,
                                           objects=vol_type_objs)
        mock_vol_type_get_all_by_group.return_value = vol_types

        # TODO(geguileo): One `volume_type_ids` gets sorted out make proper
        # changes here
        # self.group1.volume_type_ids = volume_type_ids
        # self.group1.save()
        # self.group2.volume_type_ids = volume_type_ids
        # self.group2.save()
        # self.group3.volume_type_ids = volume_type_ids
        # self.group3.save()
        req = fakes.HTTPRequest.blank('/v3/%s/groups/detail' %
                                      fake.PROJECT_ID,
                                      version=GROUP_MICRO_VERSION)
        res_dict = self.controller.detail(req)

        self.assertEqual(1, len(res_dict))
        index = 0
        for group in [self.group3, self.group2, self.group1]:
            self.assertEqual(group.id,
                             res_dict['groups'][index]['id'])
            self.assertEqual([fake.VOLUME_TYPE_ID, fake.VOLUME_TYPE2_ID],
                             res_dict['groups'][index]['volume_types'])
            self.assertEqual('test_group',
                             res_dict['groups'][index]['name'])
            self.assertTrue({'availability_zone', 'description',
                             'status'}.issubset(
                                 set(res_dict['groups'][index].keys())))
            index += 1

    @ddt.data(False, True)
    @mock.patch(
        'cinder.api.openstack.wsgi.Controller.validate_name_and_description')
    def test_create_group_json(self, use_group_type_name, mock_validate):
        # Create volume types and group type
        vol_type = 'test'
        vol_type_id = db.volume_type_create(
            self.ctxt,
            {'name': vol_type, 'extra_specs': {}}).get('id')
        grp_type_name = 'test_grp_type'
        grp_type = db.group_type_create(
            self.ctxt,
            {'name': grp_type_name, 'group_specs': {}}).get('id')
        if use_group_type_name:
            grp_type = grp_type_name
        body = {"group": {"name": "group1",
                          "volume_types": [vol_type_id],
                          "group_type": grp_type,
                          "description":
                          "Group 1", }}
        req = fakes.HTTPRequest.blank('/v3/%s/groups' % fake.PROJECT_ID,
                                      version=GROUP_MICRO_VERSION)
        res_dict = self.controller.create(req, body)

        self.assertEqual(1, len(res_dict))
        self.assertIn('id', res_dict['group'])
        self.assertTrue(mock_validate.called)

        group_id = res_dict['group']['id']
        objects.Group.get_by_id(self.ctxt, group_id)

    def test_create_group_with_no_body(self):
        # omit body from the request
        req = fakes.HTTPRequest.blank('/v3/%s/groups' % fake.PROJECT_ID,
                                      version=GROUP_MICRO_VERSION)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, None)

    def test_delete_group_available(self):
        self.group1.status = fields.GroupStatus.AVAILABLE
        self.group1.save()
        req = fakes.HTTPRequest.blank('/v3/%s/groups/%s/action' %
                                      (fake.PROJECT_ID, self.group1.id),
                                      version=GROUP_MICRO_VERSION)
        body = {"delete": {"delete-volumes": False}}
        res_dict = self.controller.delete_group(
            req, self.group1.id, body)

        group = objects.Group.get_by_id(
            self.ctxt, self.group1.id)
        self.assertEqual(http_client.ACCEPTED, res_dict.status_int)
        self.assertEqual(fields.GroupStatus.DELETING, group.status)

    def test_delete_group_available_no_delete_volumes(self):
        self.group1.status = fields.GroupStatus.AVAILABLE
        self.group1.save()
        req = fakes.HTTPRequest.blank('/v3/%s/groups/%s/action' %
                                      (fake.PROJECT_ID, self.group1.id),
                                      version=GROUP_MICRO_VERSION)
        body = {"delete": {"delete-volumes": False}}
        res_dict = self.controller.delete_group(
            req, self.group1.id, body)

        group = objects.Group.get_by_id(
            self.ctxt, self.group1.id)
        self.assertEqual(http_client.ACCEPTED, res_dict.status_int)
        self.assertEqual(fields.GroupStatus.DELETING,
                         group.status)

    def test_delete_group_with_group_NotFound(self):
        req = fakes.HTTPRequest.blank('/v3/%s/groups/%s/action' %
                                      (fake.PROJECT_ID,
                                       fake.WILL_NOT_BE_FOUND_ID),
                                      version=GROUP_MICRO_VERSION)
        body = {"delete": {"delete-volumes": False}}
        self.assertRaises(exception.GroupNotFound,
                          self.controller.delete_group,
                          req, fake.WILL_NOT_BE_FOUND_ID, body)

    def test_delete_group_with_invalid_group(self):
        req = fakes.HTTPRequest.blank('/v3/%s/groups/%s/action' %
                                      (fake.PROJECT_ID,
                                       self.group1.id),
                                      version=GROUP_MICRO_VERSION)
        body = {"delete": {"delete-volumes": False}}
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.delete_group,
                          req, self.group1.id, body)

    def test_delete_group_invalid_delete_volumes(self):
        req = fakes.HTTPRequest.blank('/v3/%s/groups/%s/action' %
                                      (fake.PROJECT_ID,
                                       self.group1.id),
                                      version=GROUP_MICRO_VERSION)
        body = {"delete": {"delete-volumes": True}}
        res_dict = self.controller.delete_group(
            req, self.group1.id, body)

        group = objects.Group.get_by_id(
            self.ctxt, self.group1.id)
        self.assertEqual(http_client.ACCEPTED, res_dict.status_int)
        self.assertEqual(fields.GroupStatus.DELETING, group.status)

    def test_delete_group_no_host(self):
        self.group1.host = None
        self.group1.status = fields.GroupStatus.ERROR
        self.group1.save()
        req = fakes.HTTPRequest.blank('/v3/%s/groups/%s/action' %
                                      (fake.PROJECT_ID,
                                       self.group1.id),
                                      version=GROUP_MICRO_VERSION)
        body = {"delete": {"delete-volumes": True}}
        res_dict = self.controller.delete_group(
            req, self.group1.id, body)

        self.assertEqual(http_client.ACCEPTED, res_dict.status_int)
        group = objects.Group.get_by_id(
            context.get_admin_context(read_deleted='yes'),
            self.group1.id)
        self.assertEqual(fields.GroupStatus.DELETED, group.status)
        self.assertIsNone(group.host)

    @mock.patch('cinder.quota.GROUP_QUOTAS.reserve',
                return_value='reservations')
    @mock.patch('cinder.quota.GROUP_QUOTAS.commit')
    def test_create_delete_group_update_quota(self, mock_commit, mock_reserve):
        name = 'mygroup'
        description = 'group 1'
        grp_type = {'id': fake.GROUP_TYPE_ID, 'name': 'group_type'}
        fake_type = {'id': fake.VOLUME_TYPE_ID, 'name': 'fake_type'}
        self.mock_object(db, 'volume_types_get_by_name_or_id',
                         return_value=[fake_type])
        self.mock_object(db, 'group_type_get', return_value=grp_type)
        self.mock_object(self.group_api, '_cast_create_group')
        self.mock_object(self.group_api, 'update_quota')
        group = self.group_api.create(self.ctxt, name, description,
                                      grp_type['id'], [fake_type['id']])
        # Verify that quota reservation and commit was called
        mock_reserve.assert_called_once_with(self.ctxt,
                                             project_id=self.ctxt.project_id,
                                             groups=1)
        mock_commit.assert_called_once_with(self.ctxt, 'reservations')

        self.assertEqual(fields.GroupStatus.CREATING, group.status)
        self.assertIsNone(group.host)
        group.status = fields.GroupStatus.ERROR
        self.group_api.delete(self.ctxt, group)

        self.group_api.update_quota.assert_called_once_with(
            self.ctxt, group, -1, self.ctxt.project_id)
        group = objects.Group.get_by_id(
            context.get_admin_context(read_deleted='yes'),
            group.id)
        self.assertEqual(fields.GroupStatus.DELETED, group.status)

    @mock.patch('cinder.group.api.API.create')
    def test_create_group_failed_exceeded_quota(self, mock_group_create):
        mock_group_create.side_effect = exception.GroupLimitExceeded(allowed=1)
        name = 'group1'
        body = {"group": {"group_type": fake.GROUP_TYPE_ID,
                          "volume_types": [fake.VOLUME_TYPE_ID],
                          "name": name,
                          "description":
                          "Group 1", }}
        req = fakes.HTTPRequest.blank('/v3/%s/groups' % fake.PROJECT_ID,
                                      version=GROUP_MICRO_VERSION)
        ex = self.assertRaises(exception.GroupLimitExceeded,
                               self.controller.create,
                               req, body)
        self.assertEqual(http_client.REQUEST_ENTITY_TOO_LARGE, ex.code)

    def test_delete_group_with_invalid_body(self):
        self.group1.status = fields.GroupStatus.AVAILABLE
        self.group1.save()
        req = fakes.HTTPRequest.blank('/v3/%s/groups/%s/action' %
                                      (fake.PROJECT_ID, self.group1.id),
                                      version=GROUP_MICRO_VERSION)
        body = {"invalid_request_element": {"delete-volumes": False}}
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.delete_group,
                          req, self.group1.id, body)

    def test_delete_group_with_invalid_delete_volumes_value_in_body(self):
        self.group1.status = fields.GroupStatus.AVAILABLE
        self.group1.save()
        req = fakes.HTTPRequest.blank('/v3/%s/groups/%s/action' %
                                      (fake.PROJECT_ID, self.group1.id),
                                      version=GROUP_MICRO_VERSION)
        body = {"delete": {"delete-volumes": "abcd"}}
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.delete_group,
                          req, self.group1.id, body)

    def test_delete_group_with_empty_delete_volumes_value_in_body(self):
        self.group1.status = fields.GroupStatus.AVAILABLE
        self.group1.save()
        req = fakes.HTTPRequest.blank('/v3/%s/groups/%s/action' %
                                      (fake.PROJECT_ID, self.group1.id),
                                      version=GROUP_MICRO_VERSION)
        body = {"delete": {"delete-volumes": ""}}
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.delete_group,
                          req, self.group1.id, body)

    def test_delete_group_with_group_snapshot(self):
        self.group1.status = fields.GroupStatus.AVAILABLE
        self.group1.save()
        g_snapshot = utils.create_group_snapshot(self.ctxt, self.group1.id)

        req = fakes.HTTPRequest.blank('/v3/%s/groups/%s/action' %
                                      (fake.PROJECT_ID, self.group1.id),
                                      version=GROUP_MICRO_VERSION)
        body = {"delete": {"delete-volumes": True}}
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.delete_group,
                          req, self.group1.id, body)

        g_snapshot.destroy()

        res_dict = self.controller.delete_group(
            req, self.group1.id, body)

        group = objects.Group.get_by_id(
            self.ctxt, self.group1.id)
        self.assertEqual(http_client.ACCEPTED, res_dict.status_int)
        self.assertEqual(fields.GroupStatus.DELETING, group.status)

    def test_delete_group_delete_volumes(self):
        self.group1.status = fields.GroupStatus.AVAILABLE
        self.group1.save()
        vol = utils.create_volume(self.ctxt, group_id=self.group1.id)
        req = fakes.HTTPRequest.blank('/v3/%s/groups/%s/action' %
                                      (fake.PROJECT_ID, self.group1.id),
                                      version=GROUP_MICRO_VERSION)
        body = {"delete": {"delete-volumes": True}}
        res_dict = self.controller.delete_group(
            req, self.group1.id, body)

        group = objects.Group.get_by_id(
            self.ctxt, self.group1.id)
        self.assertEqual(http_client.ACCEPTED, res_dict.status_int)
        self.assertEqual(fields.GroupStatus.DELETING, group.status)

        vol.destroy()

    def test_delete_group_delete_volumes_with_attached_volumes(self):
        self.group1.status = fields.GroupStatus.AVAILABLE
        self.group1.save()
        vol = utils.create_volume(self.ctxt, group_id=self.group1.id,
                                  attach_status='attached')
        req = fakes.HTTPRequest.blank('/v3/%s/groups/%s/action' %
                                      (fake.PROJECT_ID, self.group1.id),
                                      version=GROUP_MICRO_VERSION)
        body = {"delete": {"delete-volumes": True}}
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.delete_group,
                          req, self.group1.id, body)

        vol.destroy()

    def test_delete_group_delete_volumes_with_snapshots(self):
        self.group1.status = fields.GroupStatus.AVAILABLE
        self.group1.save()
        vol = utils.create_volume(self.ctxt, group_id=self.group1.id)
        utils.create_snapshot(self.ctxt, vol.id)
        req = fakes.HTTPRequest.blank('/v3/%s/groups/%s/action' %
                                      (fake.PROJECT_ID, self.group1.id),
                                      version=GROUP_MICRO_VERSION)
        body = {"delete": {"delete-volumes": True}}
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.delete_group,
                          req, self.group1.id, body)

        vol.destroy()

    def test_delete_group_delete_volumes_with_deleted_snapshots(self):
        self.group1.status = fields.GroupStatus.AVAILABLE
        self.group1.save()
        vol = utils.create_volume(self.ctxt, group_id=self.group1.id)
        utils.create_snapshot(self.ctxt, vol.id,
                              status=fields.SnapshotStatus.DELETED,
                              deleted=True)
        req = fakes.HTTPRequest.blank('/v3/%s/groups/%s/action' %
                                      (fake.PROJECT_ID, self.group1.id),
                                      version=GROUP_MICRO_VERSION)
        body = {"delete": {"delete-volumes": True}}
        res_dict = self.controller.delete_group(
            req, self.group1.id, body)

        group = objects.Group.get_by_id(
            self.ctxt, self.group1.id)
        self.assertEqual(http_client.ACCEPTED, res_dict.status_int)
        self.assertEqual(fields.GroupStatus.DELETING, group.status)

        vol.destroy()

    def test_create_group_failed_no_group_type(self):
        name = 'group1'
        body = {"group": {"volume_types": [fake.VOLUME_TYPE_ID],
                          "name": name,
                          "description":
                          "Group 1", }}
        req = fakes.HTTPRequest.blank('/v3/%s/groups' % fake.PROJECT_ID,
                                      version=GROUP_MICRO_VERSION)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create,
                          req, body)

    def test_create_group_failed_no_volume_types(self):
        name = 'group1'
        body = {"group": {"group_type": fake.GROUP_TYPE_ID,
                          "name": name,
                          "description":
                          "Group 1", }}
        req = fakes.HTTPRequest.blank('/v3/%s/groups' % fake.PROJECT_ID,
                                      version=GROUP_MICRO_VERSION)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create,
                          req, body)

    @mock.patch(
        'cinder.api.openstack.wsgi.Controller.validate_name_and_description')
    def test_update_group_success(self, mock_validate):
        volume_type_id = fake.VOLUME_TYPE_ID
        self.group1.status = fields.GroupStatus.AVAILABLE
        self.group1.host = 'test_host'
        # TODO(geguileo): One `volume_type_ids` gets sorted out make proper
        # changes here
        # self.group1.volume_type_ids = [volume_type_id]
        self.group1.save()

        remove_volume = utils.create_volume(
            self.ctxt,
            volume_type_id=volume_type_id,
            group_id=self.group1.id)
        remove_volume2 = utils.create_volume(
            self.ctxt,
            volume_type_id=volume_type_id,
            group_id=self.group1.id,
            status='error')
        remove_volume3 = utils.create_volume(
            self.ctxt,
            volume_type_id=volume_type_id,
            group_id=self.group1.id,
            status='error_deleting')

        self.assertEqual(fields.GroupStatus.AVAILABLE,
                         self.group1.status)

        group_volumes = db.volume_get_all_by_generic_group(
            self.ctxt.elevated(),
            self.group1.id)
        group_vol_ids = [group_vol['id'] for group_vol in group_volumes]
        self.assertIn(remove_volume.id, group_vol_ids)
        self.assertIn(remove_volume2.id, group_vol_ids)
        self.assertIn(remove_volume3.id, group_vol_ids)

        add_volume = utils.create_volume(
            self.ctxt,
            volume_type_id=volume_type_id)
        add_volume2 = utils.create_volume(
            self.ctxt,
            volume_type_id=volume_type_id)
        req = fakes.HTTPRequest.blank('/v3/%s/groups/%s/update' %
                                      (fake.PROJECT_ID, self.group1.id),
                                      version=GROUP_MICRO_VERSION)
        name = 'newgroup'
        description = 'New Group Description'
        add_volumes = add_volume.id + "," + add_volume2.id
        remove_volumes = ','.join(
            [remove_volume.id, remove_volume2.id, remove_volume3.id])
        body = {"group": {"name": name,
                          "description": description,
                          "add_volumes": add_volumes,
                          "remove_volumes": remove_volumes, }}
        res_dict = self.controller.update(
            req, self.group1.id, body)

        group = objects.Group.get_by_id(
            self.ctxt, self.group1.id)
        self.assertEqual(http_client.ACCEPTED, res_dict.status_int)
        self.assertTrue(mock_validate.called)
        self.assertEqual(fields.GroupStatus.UPDATING,
                         group.status)

        remove_volume.destroy()
        remove_volume2.destroy()
        remove_volume3.destroy()
        add_volume.destroy()
        add_volume2.destroy()

    def test_update_group_add_volume_not_found(self):
        self.group1.status = fields.GroupStatus.AVAILABLE
        self.group1.save()
        req = fakes.HTTPRequest.blank('/v3/%s/groups/%s/update' %
                                      (fake.PROJECT_ID, self.group1.id),
                                      version=GROUP_MICRO_VERSION)
        body = {"group": {"name": None,
                          "description": None,
                          "add_volumes": "fake-volume-uuid",
                          "remove_volumes": None, }}

        self.assertRaises(exception.InvalidVolume,
                          self.controller.update,
                          req, self.group1.id, body)

    def test_update_group_remove_volume_not_found(self):
        self.group1.status = fields.GroupStatus.AVAILABLE
        self.group1.save()
        req = fakes.HTTPRequest.blank('/v3/%s/groups/%s/update' %
                                      (fake.PROJECT_ID, self.group1.id),
                                      version=GROUP_MICRO_VERSION)
        body = {"group": {"name": None,
                          "description": "new description",
                          "add_volumes": None,
                          "remove_volumes": "fake-volume-uuid", }}

        self.assertRaises(exception.InvalidVolume,
                          self.controller.update,
                          req, self.group1.id, body)

    def test_update_group_empty_parameters(self):
        self.group1.status = fields.GroupStatus.AVAILABLE
        self.group1.save()
        req = fakes.HTTPRequest.blank('/v3/%s/groups/%s/update' %
                                      (fake.PROJECT_ID, self.group1.id),
                                      version=GROUP_MICRO_VERSION)
        body = {"group": {"name": None,
                          "description": None,
                          "add_volumes": None,
                          "remove_volumes": None, }}

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.update,
                          req, self.group1.id, body)

    def test_update_group_add_volume_invalid_state(self):
        self.group1.status = fields.GroupStatus.AVAILABLE
        self.group1.save()
        add_volume = utils.create_volume(
            self.ctxt,
            volume_type_id=fake.VOLUME_TYPE_ID,
            status='wrong_status')
        req = fakes.HTTPRequest.blank('/v3/%s/groups/%s/update' %
                                      (fake.PROJECT_ID, self.group1.id),
                                      version=GROUP_MICRO_VERSION)
        add_volumes = add_volume.id
        body = {"group": {"name": "group1",
                          "description": "",
                          "add_volumes": add_volumes,
                          "remove_volumes": None, }}

        self.assertRaises(exception.InvalidVolume,
                          self.controller.update,
                          req, self.group1.id, body)

        add_volume.destroy()

    def test_update_group_add_volume_invalid_volume_type(self):
        self.group1.status = fields.GroupStatus.AVAILABLE
        self.group1.save()
        wrong_type = fake.VOLUME_TYPE2_ID
        add_volume = utils.create_volume(
            self.ctxt,
            volume_type_id=wrong_type)
        req = fakes.HTTPRequest.blank('/v3/%s/groups/%s/update' %
                                      (fake.PROJECT_ID, self.group1.id),
                                      version=GROUP_MICRO_VERSION)
        add_volumes = add_volume.id
        body = {"group": {"name": "group1",
                          "description": "",
                          "add_volumes": add_volumes,
                          "remove_volumes": None, }}

        self.assertRaises(exception.InvalidVolume,
                          self.controller.update,
                          req, self.group1.id, body)

        add_volume.destroy()

    def test_update_group_add_volume_already_in_group(self):
        self.group1.status = fields.GroupStatus.AVAILABLE
        self.group1.save()
        add_volume = utils.create_volume(
            self.ctxt,
            group_id=fake.GROUP2_ID)
        req = fakes.HTTPRequest.blank('/v3/%s/groups/%s/update' %
                                      (fake.PROJECT_ID, self.group1.id),
                                      version=GROUP_MICRO_VERSION)
        add_volumes = add_volume.id
        body = {"group": {"name": "group1",
                          "description": "",
                          "add_volumes": add_volumes,
                          "remove_volumes": None, }}

        self.assertRaises(exception.InvalidVolume,
                          self.controller.update,
                          req, self.group1.id, body)

        add_volume.destroy()

    @ddt.data(fields.GroupStatus.CREATING, fields.GroupStatus.UPDATING)
    def test_update_group_invalid_state(self, status):
        self.group1.status = status
        req = fakes.HTTPRequest.blank('/v3/%s/groups/%s/update' %
                                      (fake.PROJECT_ID, self.group1.id),
                                      version=GROUP_MICRO_VERSION)
        body = {"group": {"name": "new name",
                          "description": None,
                          "add_volumes": None,
                          "remove_volumes": None, }}

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.update,
                          req, self.group1.id, body)

    @ddt.data(('3.11', 'fake_group_001',
               fields.GroupStatus.AVAILABLE,
               exception.VersionNotFoundForAPIMethod),
              ('3.19', 'fake_group_001',
               fields.GroupStatus.AVAILABLE,
               exception.VersionNotFoundForAPIMethod),
              ('3.20', 'fake_group_001',
               fields.GroupStatus.AVAILABLE,
               exception.GroupNotFound),
              ('3.20', None,
               'invalid_test_status',
               webob.exc.HTTPBadRequest),
              )
    @ddt.unpack
    def test_reset_group_status_illegal(self, version, group_id,
                                        status, exceptions):
        g_id = group_id or self.group2.id
        req = fakes.HTTPRequest.blank('/v3/%s/groups/%s/action' %
                                      (fake.PROJECT_ID, g_id),
                                      version=version)
        body = {"reset_status": {
            "status": status
        }}
        self.assertRaises(exceptions,
                          self.controller.reset_status,
                          req, g_id, body)

    def test_reset_group_status(self):
        req = fakes.HTTPRequest.blank('/v3/%s/groups/%s/action' %
                                      (fake.PROJECT_ID, self.group2.id),
                                      version='3.20')
        body = {"reset_status": {
            "status": fields.GroupStatus.AVAILABLE
        }}
        response = self.controller.reset_status(req,
                                                self.group2.id, body)

        group = objects.Group.get_by_id(self.ctxt, self.group2.id)
        self.assertEqual(http_client.ACCEPTED, response.status_int)
        self.assertEqual(fields.GroupStatus.AVAILABLE, group.status)

    @mock.patch(
        'cinder.api.openstack.wsgi.Controller.validate_name_and_description')
    def test_create_group_from_src_snap(self, mock_validate):
        self.mock_object(volume_api.API, "create", v3_fakes.fake_volume_create)

        group = utils.create_group(self.ctxt,
                                   group_type_id=fake.GROUP_TYPE_ID,
                                   volume_type_ids=[fake.VOLUME_TYPE_ID])
        volume = utils.create_volume(
            self.ctxt,
            group_id=group.id,
            volume_type_id=fake.VOLUME_TYPE_ID)
        group_snapshot = utils.create_group_snapshot(
            self.ctxt, group_id=group.id,
            group_type_id=group.group_type_id)
        snapshot = utils.create_snapshot(
            self.ctxt,
            volume.id,
            group_snapshot_id=group_snapshot.id,
            status=fields.SnapshotStatus.AVAILABLE,
            volume_type_id=volume.volume_type_id)

        test_grp_name = 'test grp'
        body = {"create-from-src": {"name": test_grp_name,
                                    "description": "Group 1",
                                    "group_snapshot_id": group_snapshot.id}}
        req = fakes.HTTPRequest.blank('/v3/%s/groups/action' %
                                      fake.PROJECT_ID,
                                      version=GROUP_FROM_SRC_MICRO_VERSION)
        res_dict = self.controller.create_from_src(req, body)

        self.assertIn('id', res_dict['group'])
        self.assertEqual(test_grp_name, res_dict['group']['name'])
        self.assertTrue(mock_validate.called)

        grp_ref = objects.Group.get_by_id(
            self.ctxt.elevated(), res_dict['group']['id'])

        grp_ref.destroy()
        snapshot.destroy()
        volume.destroy()
        group.destroy()
        group_snapshot.destroy()

    def test_create_group_from_src_grp(self):
        self.mock_object(volume_api.API, "create", v3_fakes.fake_volume_create)

        source_grp = utils.create_group(self.ctxt,
                                        group_type_id=fake.GROUP_TYPE_ID,
                                        volume_type_ids=[fake.VOLUME_TYPE_ID])
        volume = utils.create_volume(
            self.ctxt,
            group_id=source_grp.id,
            volume_type_id=fake.VOLUME_TYPE_ID)

        test_grp_name = 'test cg'
        body = {"create-from-src": {"name": test_grp_name,
                                    "description": "Consistency Group 1",
                                    "source_group_id": source_grp.id}}
        req = fakes.HTTPRequest.blank('/v3/%s/groups/action' %
                                      fake.PROJECT_ID,
                                      version=GROUP_FROM_SRC_MICRO_VERSION)
        res_dict = self.controller.create_from_src(req, body)

        self.assertIn('id', res_dict['group'])
        self.assertEqual(test_grp_name, res_dict['group']['name'])

        grp = objects.Group.get_by_id(
            self.ctxt, res_dict['group']['id'])
        grp.destroy()
        volume.destroy()
        source_grp.destroy()

    @mock.patch('cinder.volume.utils.is_replicated_spec',
                return_value=True)
    @mock.patch('cinder.volume.utils.is_group_a_type',
                return_value=True)
    def test_enable_replication(self, mock_rep_grp_type, mock_rep_vol_type):
        req = fakes.HTTPRequest.blank('/v3/%s/groups/%s/action' %
                                      (fake.PROJECT_ID, self.group3.id),
                                      version=GROUP_REPLICATION_MICRO_VERSION)
        self.group3.status = fields.GroupStatus.AVAILABLE
        self.group3.save()
        body = {"enable_replication": {}}
        response = self.controller.enable_replication(req,
                                                      self.group3.id, body)

        group = objects.Group.get_by_id(self.ctxt, self.group3.id)
        self.assertEqual(202, response.status_int)
        self.assertEqual(fields.GroupStatus.AVAILABLE, group.status)
        self.assertEqual(fields.ReplicationStatus.ENABLING,
                         group.replication_status)

    @ddt.data((True, False), (False, True), (False, False))
    @ddt.unpack
    @mock.patch('cinder.volume.utils.is_replicated_spec')
    @mock.patch('cinder.volume.utils.is_group_a_type')
    def test_enable_replication_wrong_type(self, is_grp_rep_type,
                                           is_vol_rep_type,
                                           mock_rep_grp_type,
                                           mock_rep_vol_type):
        mock_rep_grp_type.return_value = is_grp_rep_type
        mock_rep_vol_type.return_value = is_vol_rep_type
        req = fakes.HTTPRequest.blank('/v3/%s/groups/%s/action' %
                                      (fake.PROJECT_ID, self.group3.id),
                                      version=GROUP_REPLICATION_MICRO_VERSION)
        self.group3.status = fields.GroupStatus.AVAILABLE
        self.group3.save()
        body = {"enable_replication": {}}
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.enable_replication,
                          req, self.group3.id, body)

    @mock.patch('cinder.volume.utils.is_replicated_spec',
                return_value=False)
    @mock.patch('cinder.volume.utils.is_group_a_type',
                return_value=True)
    def test_enable_replication_wrong_group_type(self, mock_rep_grp_type,
                                                 mock_rep_vol_type):
        req = fakes.HTTPRequest.blank('/v3/%s/groups/%s/action' %
                                      (fake.PROJECT_ID, self.group3.id),
                                      version=GROUP_REPLICATION_MICRO_VERSION)
        self.group3.status = fields.GroupStatus.AVAILABLE
        self.group3.save()
        body = {"enable_replication": {}}
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.enable_replication,
                          req, self.group3.id, body)

    @mock.patch('cinder.volume.utils.is_replicated_spec',
                return_value=True)
    @mock.patch('cinder.volume.utils.is_group_a_type',
                return_value=True)
    @ddt.data((GROUP_REPLICATION_MICRO_VERSION, True,
               fields.GroupStatus.CREATING,
               webob.exc.HTTPBadRequest),
              (GROUP_REPLICATION_MICRO_VERSION, False,
               fields.GroupStatus.AVAILABLE,
               exception.GroupNotFound),
              (INVALID_GROUP_REPLICATION_MICRO_VERSION, True,
               fields.GroupStatus.AVAILABLE,
               exception.VersionNotFoundForAPIMethod),
              )
    @ddt.unpack
    def test_enable_replication_negative(self, version, not_fake,
                                         status, exceptions,
                                         mock_rep_grp_type, mock_rep_vol_type):
        if not_fake:
            group_id = self.group3.id
        else:
            group_id = fake.GROUP_ID
        req = fakes.HTTPRequest.blank('/v3/%s/groups/%s/action' %
                                      (fake.PROJECT_ID, group_id),
                                      version=version)
        if not_fake:
            self.group3.status = status
            self.group3.save()
        body = {"enable_replication": {}}
        self.assertRaises(exceptions,
                          self.controller.enable_replication,
                          req, group_id, body)

    @mock.patch('cinder.volume.utils.is_replicated_spec',
                return_value=True)
    @mock.patch('cinder.volume.utils.is_group_a_type',
                return_value=True)
    def test_disable_replication(self, mock_rep_grp_type, mock_rep_vol_type):
        req = fakes.HTTPRequest.blank('/v3/%s/groups/%s/action' %
                                      (fake.PROJECT_ID, self.group3.id),
                                      version=GROUP_REPLICATION_MICRO_VERSION)
        self.group3.status = fields.GroupStatus.AVAILABLE
        self.group3.replication_status = fields.ReplicationStatus.ENABLED
        self.group3.save()
        body = {"disable_replication": {}}
        response = self.controller.disable_replication(req,
                                                       self.group3.id, body)

        group = objects.Group.get_by_id(self.ctxt, self.group3.id)
        self.assertEqual(202, response.status_int)
        self.assertEqual(fields.GroupStatus.AVAILABLE, group.status)
        self.assertEqual(fields.ReplicationStatus.DISABLING,
                         group.replication_status)

    @mock.patch('cinder.volume.utils.is_replicated_spec',
                return_value=True)
    @mock.patch('cinder.volume.utils.is_group_a_type',
                return_value=True)
    @ddt.data((GROUP_REPLICATION_MICRO_VERSION, True,
               fields.GroupStatus.CREATING,
               fields.ReplicationStatus.ENABLED,
               webob.exc.HTTPBadRequest),
              (GROUP_REPLICATION_MICRO_VERSION, True,
               fields.GroupStatus.AVAILABLE,
               fields.ReplicationStatus.DISABLED,
               webob.exc.HTTPBadRequest),
              (GROUP_REPLICATION_MICRO_VERSION, False,
               fields.GroupStatus.AVAILABLE,
               fields.ReplicationStatus.DISABLED,
               exception.GroupNotFound),
              (INVALID_GROUP_REPLICATION_MICRO_VERSION, True,
               fields.GroupStatus.AVAILABLE,
               fields.ReplicationStatus.ENABLED,
               exception.VersionNotFoundForAPIMethod),
              )
    @ddt.unpack
    def test_disable_replication_negative(self, version, not_fake,
                                          status, rep_status, exceptions,
                                          mock_rep_grp_type,
                                          mock_rep_vol_type):
        if not_fake:
            group_id = self.group3.id
        else:
            group_id = fake.GROUP_ID
        req = fakes.HTTPRequest.blank('/v3/%s/groups/%s/action' %
                                      (fake.PROJECT_ID, group_id),
                                      version=version)
        if not_fake:
            self.group3.status = status
            self.group3.replication_status = rep_status
            self.group3.save()
        body = {"disable_replication": {}}
        self.assertRaises(exceptions,
                          self.controller.disable_replication,
                          req, group_id, body)

    @mock.patch('cinder.volume.utils.is_replicated_spec',
                return_value=True)
    @mock.patch('cinder.volume.utils.is_group_a_type',
                return_value=True)
    def test_failover_replication(self, mock_rep_grp_type, mock_rep_vol_type):
        req = fakes.HTTPRequest.blank('/v3/%s/groups/%s/action' %
                                      (fake.PROJECT_ID, self.group3.id),
                                      version=GROUP_REPLICATION_MICRO_VERSION)
        self.group3.status = fields.GroupStatus.AVAILABLE
        self.group3.replication_status = fields.ReplicationStatus.ENABLED
        self.group3.save()
        body = {"failover_replication": {}}
        response = self.controller.failover_replication(req,
                                                        self.group3.id, body)

        group = objects.Group.get_by_id(self.ctxt, self.group3.id)
        self.assertEqual(202, response.status_int)
        self.assertEqual(fields.GroupStatus.AVAILABLE, group.status)
        self.assertEqual(fields.ReplicationStatus.FAILING_OVER,
                         group.replication_status)

    @mock.patch('cinder.volume.utils.is_replicated_spec',
                return_value=True)
    @mock.patch('cinder.volume.utils.is_group_a_type',
                return_value=True)
    @ddt.data((GROUP_REPLICATION_MICRO_VERSION, True,
               fields.GroupStatus.CREATING,
               fields.ReplicationStatus.ENABLED,
               webob.exc.HTTPBadRequest),
              (GROUP_REPLICATION_MICRO_VERSION, True,
               fields.GroupStatus.AVAILABLE,
               fields.ReplicationStatus.DISABLED,
               webob.exc.HTTPBadRequest),
              (GROUP_REPLICATION_MICRO_VERSION, False,
               fields.GroupStatus.AVAILABLE,
               fields.ReplicationStatus.DISABLED,
               exception.GroupNotFound),
              (INVALID_GROUP_REPLICATION_MICRO_VERSION, True,
               fields.GroupStatus.AVAILABLE,
               fields.ReplicationStatus.ENABLED,
               exception.VersionNotFoundForAPIMethod),
              )
    @ddt.unpack
    def test_failover_replication_negative(self, version, not_fake,
                                           status, rep_status, exceptions,
                                           mock_rep_grp_type,
                                           mock_rep_vol_type):
        if not_fake:
            group_id = self.group3.id
        else:
            group_id = fake.GROUP_ID
        req = fakes.HTTPRequest.blank('/v3/%s/groups/%s/action' %
                                      (fake.PROJECT_ID, group_id),
                                      version=version)
        if not_fake:
            self.group3.status = status
            self.group3.replication_status = rep_status
            self.group3.save()
        body = {"failover_replication": {}}
        self.assertRaises(exceptions,
                          self.controller.failover_replication,
                          req, group_id, body)

    @mock.patch('cinder.volume.utils.is_replicated_spec',
                return_value=True)
    @mock.patch('cinder.volume.utils.is_group_a_type',
                return_value=True)
    @mock.patch('cinder.volume.rpcapi.VolumeAPI.list_replication_targets')
    def test_list_replication_targets(self, mock_list_rep_targets,
                                      mock_rep_grp_type, mock_rep_vol_type):
        req = fakes.HTTPRequest.blank('/v3/%s/groups/%s/action' %
                                      (fake.PROJECT_ID, self.group3.id),
                                      version=GROUP_REPLICATION_MICRO_VERSION)
        targets = {
            'replication_targets': [
                {'backend_id': 'lvm_backend_1'}
            ]
        }
        mock_list_rep_targets.return_value = targets
        self.group3.status = fields.GroupStatus.AVAILABLE
        self.group3.save()
        body = {"list_replication_targets": {}}
        response = self.controller.list_replication_targets(
            req, self.group3.id, body)

        self.assertIn('replication_targets', response)
        self.assertEqual('lvm_backend_1',
                         response['replication_targets'][0]['backend_id'])
