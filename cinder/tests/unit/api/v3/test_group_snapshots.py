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
Tests for group_snapshot code.
"""

import ddt
import mock
from six.moves import http_client
import webob

from cinder.api.v3 import group_snapshots as v3_group_snapshots
from cinder import context
from cinder import db
from cinder import exception
from cinder.group import api as group_api
from cinder import objects
from cinder.objects import fields
from cinder import test
from cinder.tests.unit.api import fakes
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import utils
import cinder.volume

GROUP_MICRO_VERSION = '3.14'
SUPPORT_FILTER_VERSION = '3.29'


@ddt.ddt
class GroupSnapshotsAPITestCase(test.TestCase):
    """Test Case for group_snapshots API."""

    def setUp(self):
        super(GroupSnapshotsAPITestCase, self).setUp()
        self.controller = v3_group_snapshots.GroupSnapshotsController()
        self.volume_api = cinder.volume.API()
        self.context = context.get_admin_context()
        self.context.project_id = fake.PROJECT_ID
        self.context.user_id = fake.USER_ID
        self.user_ctxt = context.RequestContext(
            fake.USER_ID, fake.PROJECT_ID, auth_token=True)
        self.group = utils.create_group(self.context,
                                        group_type_id=fake.GROUP_TYPE_ID,
                                        volume_type_ids=[fake.VOLUME_TYPE_ID])
        self.volume = utils.create_volume(self.context,
                                          group_id=self.group.id,
                                          volume_type_id=fake.VOLUME_TYPE_ID)
        self.g_snapshots_array = [
            utils.create_group_snapshot(
                self.context,
                group_id=self.group.id,
                group_type_id=self.group.group_type_id) for _ in range(3)]
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        for snapshot in self.g_snapshots_array:
            snapshot.destroy()
        self.volume.destroy()
        self.group.destroy()

    def test_show_group_snapshot(self):
        group_snapshot = utils.create_group_snapshot(
            self.context, group_id=self.group.id)
        req = fakes.HTTPRequest.blank('/v3/%s/group_snapshots/%s' %
                                      (fake.PROJECT_ID, group_snapshot.id),
                                      version=GROUP_MICRO_VERSION)
        res_dict = self.controller.show(req, group_snapshot.id)

        self.assertEqual(1, len(res_dict))
        self.assertEqual('this is a test group snapshot',
                         res_dict['group_snapshot']['description'])
        self.assertEqual('test_group_snapshot',
                         res_dict['group_snapshot']['name'])
        self.assertEqual(fields.GroupSnapshotStatus.CREATING,
                         res_dict['group_snapshot']['status'])

        group_snapshot.destroy()

    @ddt.data(True, False)
    def test_list_group_snapshots_with_limit(self, is_detail):

        url = '/v3/%s/group_snapshots?limit=1' % fake.PROJECT_ID
        if is_detail:
            url = '/v3/%s/group_snapshots/detail?limit=1' % fake.PROJECT_ID
        req = fakes.HTTPRequest.blank(url, version=SUPPORT_FILTER_VERSION)
        if is_detail:
            res_dict = self.controller.detail(req)
        else:
            res_dict = self.controller.index(req)

        self.assertEqual(2, len(res_dict))
        self.assertEqual(1, len(res_dict['group_snapshots']))
        self.assertEqual(self.g_snapshots_array[2].id,
                         res_dict['group_snapshots'][0]['id'])
        next_link = (
            'http://localhost/v3/%s/group_snapshots?limit='
            '1&marker=%s' %
            (fake.PROJECT_ID, res_dict['group_snapshots'][0]['id']))
        self.assertEqual(next_link,
                         res_dict['group_snapshot_links'][0]['href'])
        if is_detail:
            self.assertIn('description', res_dict['group_snapshots'][0].keys())
        else:
            self.assertNotIn('description',
                             res_dict['group_snapshots'][0].keys())

    @ddt.data(True, False)
    def test_list_group_snapshot_with_offset(self, is_detail):
        url = '/v3/%s/group_snapshots?offset=1' % fake.PROJECT_ID
        if is_detail:
            url = '/v3/%s/group_snapshots/detail?offset=1' % fake.PROJECT_ID
        req = fakes.HTTPRequest.blank(url, version=SUPPORT_FILTER_VERSION)
        if is_detail:
            res_dict = self.controller.detail(req)
        else:
            res_dict = self.controller.index(req)
        self.assertEqual(1, len(res_dict))
        self.assertEqual(2, len(res_dict['group_snapshots']))
        self.assertEqual(self.g_snapshots_array[1].id,
                         res_dict['group_snapshots'][0]['id'])
        self.assertEqual(self.g_snapshots_array[0].id,
                         res_dict['group_snapshots'][1]['id'])
        if is_detail:
            self.assertIn('description', res_dict['group_snapshots'][0].keys())
        else:
            self.assertNotIn('description',
                             res_dict['group_snapshots'][0].keys())

    @ddt.data(True, False)
    def test_list_group_snapshot_with_offset_out_of_range(self, is_detail):
        url = ('/v3/%s/group_snapshots?offset=234523423455454' %
               fake.PROJECT_ID)
        if is_detail:
            url = ('/v3/%s/group_snapshots/detail?offset=234523423455454' %
                   fake.PROJECT_ID)
        req = fakes.HTTPRequest.blank(url, version=SUPPORT_FILTER_VERSION)
        if is_detail:
            self.assertRaises(webob.exc.HTTPBadRequest, self.controller.detail,
                              req)
        else:
            self.assertRaises(webob.exc.HTTPBadRequest, self.controller.index,
                              req)

    @ddt.data(False, True)
    def test_list_group_snapshot_with_limit_and_offset(self, is_detail):
        group_snapshot = utils.create_group_snapshot(
            self.context,
            group_id=self.group.id,
            group_type_id=self.group.group_type_id)
        url = '/v3/%s/group_snapshots?limit=2&offset=1' % fake.PROJECT_ID
        if is_detail:
            url = ('/v3/%s/group_snapshots/detail?limit=2&offset=1' %
                   fake.PROJECT_ID)
        req = fakes.HTTPRequest.blank(url, version=SUPPORT_FILTER_VERSION)
        if is_detail:
            res_dict = self.controller.detail(req)
        else:
            res_dict = self.controller.index(req)

        self.assertEqual(2, len(res_dict))
        self.assertEqual(2, len(res_dict['group_snapshots']))
        self.assertEqual(self.g_snapshots_array[2].id,
                         res_dict['group_snapshots'][0]['id'])
        self.assertEqual(self.g_snapshots_array[1].id,
                         res_dict['group_snapshots'][1]['id'])
        self.assertIsNotNone(res_dict['group_snapshot_links'][0]['href'])
        if is_detail:
            self.assertIn('description', res_dict['group_snapshots'][0].keys())
        else:
            self.assertNotIn('description',
                             res_dict['group_snapshots'][0].keys())
        group_snapshot.destroy()

    @ddt.data('3.30', '3.31', '3.34')
    @mock.patch('cinder.api.common.reject_invalid_filters')
    def test_group_snapshot_list_with_general_filter(self,
                                                     version, mock_update):
        url = '/v3/%s/group_snapshots' % fake.PROJECT_ID
        req = fakes.HTTPRequest.blank(url,
                                      version=version,
                                      use_admin_context=False)
        self.controller.index(req)

        if version != '3.30':
            support_like = True if version == '3.34' else False
            mock_update.assert_called_once_with(req.environ['cinder.context'],
                                                mock.ANY, 'group_snapshot',
                                                support_like)

    @ddt.data(False, True)
    def test_list_group_snapshot_with_filter(self, is_detail):
        url = ('/v3/%s/group_snapshots?'
               'all_tenants=True&id=%s') % (fake.PROJECT_ID,
                                            self.g_snapshots_array[0].id)
        if is_detail:
            url = ('/v3/%s/group_snapshots/detail?'
                   'all_tenants=True&id=%s') % (fake.PROJECT_ID,
                                                self.g_snapshots_array[0].id)
        req = fakes.HTTPRequest.blank(url, version=SUPPORT_FILTER_VERSION,
                                      use_admin_context=True)
        if is_detail:
            res_dict = self.controller.detail(req)
        else:
            res_dict = self.controller.index(req)

        self.assertEqual(1, len(res_dict))
        self.assertEqual(1, len(res_dict['group_snapshots']))
        self.assertEqual(self.g_snapshots_array[0].id,
                         res_dict['group_snapshots'][0]['id'])
        if is_detail:
            self.assertIn('description', res_dict['group_snapshots'][0].keys())
        else:
            self.assertNotIn('description',
                             res_dict['group_snapshots'][0].keys())

    @ddt.data({'is_detail': True, 'version': GROUP_MICRO_VERSION},
              {'is_detail': False, 'version': GROUP_MICRO_VERSION},
              {'is_detail': True, 'version': '3.28'},
              {'is_detail': False, 'version': '3.28'},)
    @ddt.unpack
    def test_list_group_snapshot_with_filter_previous_version(self, is_detail,
                                                              version):
        url = ('/v3/%s/group_snapshots?'
               'all_tenants=True&id=%s') % (fake.PROJECT_ID,
                                            self.g_snapshots_array[0].id)
        if is_detail:
            url = ('/v3/%s/group_snapshots/detail?'
                   'all_tenants=True&id=%s') % (fake.PROJECT_ID,
                                                self.g_snapshots_array[0].id)
        req = fakes.HTTPRequest.blank(url, version=version,
                                      use_admin_context=True)

        if is_detail:
            res_dict = self.controller.detail(req)
        else:
            res_dict = self.controller.index(req)

        self.assertEqual(1, len(res_dict))
        self.assertEqual(3, len(res_dict['group_snapshots']))

    @ddt.data(False, True)
    def test_list_group_snapshot_with_sort(self, is_detail):
        url = '/v3/%s/group_snapshots?sort=id:asc' % fake.PROJECT_ID
        if is_detail:
            url = ('/v3/%s/group_snapshots/detail?sort=id:asc' %
                   fake.PROJECT_ID)
        req = fakes.HTTPRequest.blank(url, version=SUPPORT_FILTER_VERSION)
        expect_result = [snapshot.id for snapshot in self.g_snapshots_array]
        expect_result.sort()
        if is_detail:
            res_dict = self.controller.detail(req)
        else:
            res_dict = self.controller.index(req)
        self.assertEqual(1, len(res_dict))
        self.assertEqual(3, len(res_dict['group_snapshots']))
        self.assertEqual(expect_result[0],
                         res_dict['group_snapshots'][0]['id'])
        self.assertEqual(expect_result[1],
                         res_dict['group_snapshots'][1]['id'])
        self.assertEqual(expect_result[2],
                         res_dict['group_snapshots'][2]['id'])
        if is_detail:
            self.assertIn('description', res_dict['group_snapshots'][0].keys())
        else:
            self.assertNotIn('description',
                             res_dict['group_snapshots'][0].keys())

    def test_show_group_snapshot_with_group_snapshot_not_found(self):
        req = fakes.HTTPRequest.blank('/v3/%s/group_snapshots/%s' %
                                      (fake.PROJECT_ID,
                                       fake.WILL_NOT_BE_FOUND_ID),
                                      version=GROUP_MICRO_VERSION)
        self.assertRaises(exception.GroupSnapshotNotFound,
                          self.controller.show,
                          req, fake.WILL_NOT_BE_FOUND_ID)

    @ddt.data(True, False)
    def test_list_group_snapshots_json(self, is_detail):
        if is_detail:
            request_url = '/v3/%s/group_snapshots/detail'
        else:
            request_url = '/v3/%s/group_snapshots'
        req = fakes.HTTPRequest.blank(request_url % fake.PROJECT_ID,
                                      version=GROUP_MICRO_VERSION)
        if is_detail:
            res_dict = self.controller.detail(req)
        else:
            res_dict = self.controller.index(req)

        self.assertEqual(1, len(res_dict))
        self.assertEqual(3, len(res_dict['group_snapshots']))
        for index, snapshot in enumerate(self.g_snapshots_array):
            self.assertEqual(snapshot.id,
                             res_dict['group_snapshots'][2 - index]['id'])
            self.assertIsNotNone(
                res_dict['group_snapshots'][2 - index]['name'])
            if is_detail:
                self.assertIn('description',
                              res_dict['group_snapshots'][2 - index].keys())
            else:
                self.assertNotIn('description',
                                 res_dict['group_snapshots'][2 - index].keys())

    @mock.patch(
        'cinder.api.openstack.wsgi.Controller.validate_name_and_description')
    @mock.patch('cinder.db.volume_type_get')
    @mock.patch('cinder.quota.VolumeTypeQuotaEngine.reserve')
    def test_create_group_snapshot_json(self, mock_quota, mock_vol_type,
                                        mock_validate):
        body = {"group_snapshot": {"name": "group_snapshot1",
                                   "description":
                                   "Group Snapshot 1",
                                   "group_id": self.group.id}}
        req = fakes.HTTPRequest.blank('/v3/%s/group_snapshots' %
                                      fake.PROJECT_ID,
                                      version=GROUP_MICRO_VERSION)
        res_dict = self.controller.create(req, body)

        self.assertEqual(1, len(res_dict))
        self.assertIn('id', res_dict['group_snapshot'])
        self.assertTrue(mock_validate.called)
        group_snapshot = objects.GroupSnapshot.get_by_id(
            context.get_admin_context(), res_dict['group_snapshot']['id'])
        group_snapshot.destroy()

    @mock.patch(
        'cinder.api.openstack.wsgi.Controller.validate_name_and_description')
    @mock.patch('cinder.db.volume_type_get')
    def test_create_group_snapshot_when_volume_in_error_status(
            self, mock_vol_type, mock_validate):
        group = utils.create_group(
            self.context,
            group_type_id=fake.GROUP_TYPE_ID,
            volume_type_ids=[fake.VOLUME_TYPE_ID],)
        volume_id = utils.create_volume(
            self.context,
            status='error',
            group_id=group.id,
            volume_type_id=fake.VOLUME_TYPE_ID)['id']
        body = {"group_snapshot": {"name": "group_snapshot1",
                                   "description":
                                   "Group Snapshot 1",
                                   "group_id": group.id}}
        req = fakes.HTTPRequest.blank('/v3/%s/group_snapshots' %
                                      fake.PROJECT_ID,
                                      version=GROUP_MICRO_VERSION)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, body)
        self.assertTrue(mock_validate.called)

        group.destroy()
        db.volume_destroy(context.get_admin_context(),
                          volume_id)

    def test_create_group_snapshot_with_no_body(self):
        # omit body from the request
        req = fakes.HTTPRequest.blank('/v3/%s/group_snapshots' %
                                      fake.PROJECT_ID,
                                      version=GROUP_MICRO_VERSION)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, None)

    @mock.patch.object(group_api.API, 'create_group_snapshot',
                       side_effect=exception.InvalidGroupSnapshot(
                           reason='Invalid group snapshot'))
    def test_create_with_invalid_group_snapshot(self, mock_create_group_snap):
        body = {"group_snapshot": {"name": "group_snapshot1",
                                   "description":
                                   "Group Snapshot 1",
                                   "group_id": self.group.id}}
        req = fakes.HTTPRequest.blank('/v3/%s/group_snapshots' %
                                      fake.PROJECT_ID,
                                      version=GROUP_MICRO_VERSION)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, body)

    @mock.patch.object(group_api.API, 'create_group_snapshot',
                       side_effect=exception.GroupSnapshotNotFound(
                           group_snapshot_id='invalid_id'))
    def test_create_with_group_snapshot_not_found(self, mock_create_grp_snap):
        body = {"group_snapshot": {"name": "group_snapshot1",
                                   "description":
                                   "Group Snapshot 1",
                                   "group_id": self.group.id}}
        req = fakes.HTTPRequest.blank('/v3/%s/group_snapshots' %
                                      fake.PROJECT_ID,
                                      version=GROUP_MICRO_VERSION)
        self.assertRaises(exception.GroupSnapshotNotFound,
                          self.controller.create,
                          req, body)

    def test_create_group_snapshot_from_empty_group(self):
        empty_group = utils.create_group(
            self.context,
            group_type_id=fake.GROUP_TYPE_ID,
            volume_type_ids=[fake.VOLUME_TYPE_ID])
        body = {"group_snapshot": {"name": "group_snapshot1",
                                   "description":
                                   "Group Snapshot 1",
                                   "group_id": empty_group.id}}
        req = fakes.HTTPRequest.blank('/v3/%s/group_snapshots' %
                                      fake.PROJECT_ID,
                                      version=GROUP_MICRO_VERSION)

        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, body)
        empty_group.destroy()

    def test_delete_group_snapshot_available(self):
        group_snapshot = utils.create_group_snapshot(
            self.context,
            group_id=self.group.id,
            status=fields.GroupSnapshotStatus.AVAILABLE)
        req = fakes.HTTPRequest.blank('/v3/%s/group_snapshots/%s' %
                                      (fake.PROJECT_ID, group_snapshot.id),
                                      version=GROUP_MICRO_VERSION)
        res_dict = self.controller.delete(req, group_snapshot.id)

        group_snapshot = objects.GroupSnapshot.get_by_id(self.context,
                                                         group_snapshot.id)
        self.assertEqual(http_client.ACCEPTED, res_dict.status_int)
        self.assertEqual(fields.GroupSnapshotStatus.DELETING,
                         group_snapshot.status)

        group_snapshot.destroy()

    def test_delete_group_snapshot_available_used_as_source(self):
        group_snapshot = utils.create_group_snapshot(
            self.context,
            group_id=self.group.id,
            status=fields.GroupSnapshotStatus.AVAILABLE)

        group2 = utils.create_group(
            self.context, status='creating',
            group_snapshot_id=group_snapshot.id,
            group_type_id=fake.GROUP_TYPE_ID,
            volume_type_ids=[fake.VOLUME_TYPE_ID],)
        req = fakes.HTTPRequest.blank('/v3/%s/group_snapshots/%s' %
                                      (fake.PROJECT_ID, group_snapshot.id),
                                      version=GROUP_MICRO_VERSION)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.delete,
                          req, group_snapshot.id)

        group_snapshot.destroy()
        group2.destroy()

    def test_delete_group_snapshot_with_group_snapshot_NotFound(self):
        req = fakes.HTTPRequest.blank('/v3/%s/group_snapshots/%s' %
                                      (fake.PROJECT_ID,
                                       fake.WILL_NOT_BE_FOUND_ID),
                                      version=GROUP_MICRO_VERSION)
        self.assertRaises(exception.GroupSnapshotNotFound,
                          self.controller.delete,
                          req, fake.WILL_NOT_BE_FOUND_ID)

    def test_delete_group_snapshot_with_invalid_group_snapshot(self):
        group_snapshot = utils.create_group_snapshot(
            self.context,
            group_id=self.group.id,
            status='invalid')
        req = fakes.HTTPRequest.blank('/v3/%s/group_snapshots/%s' %
                                      (fake.PROJECT_ID, group_snapshot.id),
                                      version=GROUP_MICRO_VERSION)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.delete,
                          req, group_snapshot.id)

        group_snapshot.destroy()

    @ddt.data(('3.11', 'fake_snapshot_001',
               fields.GroupSnapshotStatus.AVAILABLE,
               exception.VersionNotFoundForAPIMethod),
              ('3.18', 'fake_snapshot_001',
               fields.GroupSnapshotStatus.AVAILABLE,
               exception.VersionNotFoundForAPIMethod),
              ('3.19', 'fake_snapshot_001',
               fields.GroupSnapshotStatus.AVAILABLE,
               exception.GroupSnapshotNotFound))
    @ddt.unpack
    def test_reset_group_snapshot_status_illegal(self, version,
                                                 group_snapshot_id,
                                                 status, exceptions):
        req = fakes.HTTPRequest.blank('/v3/%s/group_snapshots/%s/action' %
                                      (fake.PROJECT_ID, group_snapshot_id),
                                      version=version)
        body = {"reset_status": {
            "status": status
        }}
        self.assertRaises(exceptions,
                          self.controller.reset_status,
                          req, group_snapshot_id, body)

    def test_reset_group_snapshot_status_invalid_status(self):
        group_snapshot = utils.create_group_snapshot(
            self.context,
            group_id=self.group.id,
            status=fields.GroupSnapshotStatus.CREATING)
        req = fakes.HTTPRequest.blank('/v3/%s/group_snapshots/%s/action' %
                                      (fake.PROJECT_ID, group_snapshot.id),
                                      version='3.19')
        body = {"reset_status": {
            "status": "invalid_test_status"
        }}
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.reset_status,
                          req, group_snapshot.id, body)
        group_snapshot.destroy()

    def test_reset_group_snapshot_status(self):
        group_snapshot = utils.create_group_snapshot(
            self.context,
            group_id=self.group.id,
            status=fields.GroupSnapshotStatus.CREATING)
        req = fakes.HTTPRequest.blank('/v3/%s/group_snapshots/%s/action' %
                                      (fake.PROJECT_ID, group_snapshot.id),
                                      version='3.19')
        body = {"reset_status": {
            "status": fields.GroupSnapshotStatus.AVAILABLE
        }}
        response = self.controller.reset_status(req, group_snapshot.id,
                                                body)

        g_snapshot = objects.GroupSnapshot.get_by_id(self.context,
                                                     group_snapshot.id)
        self.assertEqual(http_client.ACCEPTED, response.status_int)
        self.assertEqual(fields.GroupSnapshotStatus.AVAILABLE,
                         g_snapshot.status)
        group_snapshot.destroy()
