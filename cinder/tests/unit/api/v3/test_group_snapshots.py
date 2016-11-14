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

    def test_show_group_snapshot(self):
        group = utils.create_group(
            self.context,
            group_type_id=fake.GROUP_TYPE_ID,
            volume_type_ids=[fake.VOLUME_TYPE_ID],)
        volume_id = utils.create_volume(
            self.context,
            group_id=group.id,
            volume_type_id=fake.VOLUME_TYPE_ID)['id']
        group_snapshot = utils.create_group_snapshot(
            self.context, group_id=group.id)
        req = fakes.HTTPRequest.blank('/v3/%s/group_snapshots/%s' %
                                      (fake.PROJECT_ID, group_snapshot.id),
                                      version=GROUP_MICRO_VERSION)
        res_dict = self.controller.show(req, group_snapshot.id)

        self.assertEqual(1, len(res_dict))
        self.assertEqual('this is a test group snapshot',
                         res_dict['group_snapshot']['description'])
        self.assertEqual('test_group_snapshot',
                         res_dict['group_snapshot']['name'])
        self.assertEqual('creating', res_dict['group_snapshot']['status'])

        group_snapshot.destroy()
        db.volume_destroy(context.get_admin_context(),
                          volume_id)
        group.destroy()

    def test_show_group_snapshot_with_group_snapshot_NotFound(self):
        req = fakes.HTTPRequest.blank('/v3/%s/group_snapshots/%s' %
                                      (fake.PROJECT_ID,
                                       fake.WILL_NOT_BE_FOUND_ID),
                                      version=GROUP_MICRO_VERSION)
        self.assertRaises(exception.GroupSnapshotNotFound,
                          self.controller.show,
                          req, fake.WILL_NOT_BE_FOUND_ID)

    def test_list_group_snapshots_json(self):
        group = utils.create_group(
            self.context,
            group_type_id=fake.GROUP_TYPE_ID,
            volume_type_ids=[fake.VOLUME_TYPE_ID],)
        volume_id = utils.create_volume(
            self.context,
            group_id=group.id,
            volume_type_id=fake.VOLUME_TYPE_ID)['id']
        group_snapshot1 = utils.create_group_snapshot(
            self.context, group_id=group.id,
            group_type_id=group.group_type_id)
        group_snapshot2 = utils.create_group_snapshot(
            self.context, group_id=group.id,
            group_type_id=group.group_type_id)
        group_snapshot3 = utils.create_group_snapshot(
            self.context, group_id=group.id,
            group_type_id=group.group_type_id)

        req = fakes.HTTPRequest.blank('/v3/%s/group_snapshots' %
                                      fake.PROJECT_ID,
                                      version=GROUP_MICRO_VERSION)
        res_dict = self.controller.index(req)

        self.assertEqual(1, len(res_dict))
        self.assertEqual(group_snapshot1.id,
                         res_dict['group_snapshots'][0]['id'])
        self.assertEqual('test_group_snapshot',
                         res_dict['group_snapshots'][0]['name'])
        self.assertEqual(group_snapshot2.id,
                         res_dict['group_snapshots'][1]['id'])
        self.assertEqual('test_group_snapshot',
                         res_dict['group_snapshots'][1]['name'])
        self.assertEqual(group_snapshot3.id,
                         res_dict['group_snapshots'][2]['id'])
        self.assertEqual('test_group_snapshot',
                         res_dict['group_snapshots'][2]['name'])

        group_snapshot3.destroy()
        group_snapshot2.destroy()
        group_snapshot1.destroy()
        db.volume_destroy(context.get_admin_context(),
                          volume_id)
        group.destroy()

    def test_list_group_snapshots_detail_json(self):
        group = utils.create_group(
            self.context,
            group_type_id=fake.GROUP_TYPE_ID,
            volume_type_ids=[fake.VOLUME_TYPE_ID],)
        volume_id = utils.create_volume(
            self.context,
            group_id=group.id,
            volume_type_id=fake.VOLUME_TYPE_ID)['id']
        group_snapshot1 = utils.create_group_snapshot(
            self.context, group_id=group.id)
        group_snapshot2 = utils.create_group_snapshot(
            self.context, group_id=group.id)
        group_snapshot3 = utils.create_group_snapshot(
            self.context, group_id=group.id)

        req = fakes.HTTPRequest.blank('/v3/%s/group_snapshots/detail' %
                                      fake.PROJECT_ID,
                                      version=GROUP_MICRO_VERSION)
        res_dict = self.controller.detail(req)

        self.assertEqual(1, len(res_dict))
        self.assertEqual(3, len(res_dict['group_snapshots']))
        self.assertEqual('this is a test group snapshot',
                         res_dict['group_snapshots'][0]['description'])
        self.assertEqual('test_group_snapshot',
                         res_dict['group_snapshots'][0]['name'])
        self.assertEqual(group_snapshot1.id,
                         res_dict['group_snapshots'][0]['id'])
        self.assertEqual('creating',
                         res_dict['group_snapshots'][0]['status'])

        self.assertEqual('this is a test group snapshot',
                         res_dict['group_snapshots'][1]['description'])
        self.assertEqual('test_group_snapshot',
                         res_dict['group_snapshots'][1]['name'])
        self.assertEqual(group_snapshot2.id,
                         res_dict['group_snapshots'][1]['id'])
        self.assertEqual('creating',
                         res_dict['group_snapshots'][1]['status'])

        self.assertEqual('this is a test group snapshot',
                         res_dict['group_snapshots'][2]['description'])
        self.assertEqual('test_group_snapshot',
                         res_dict['group_snapshots'][2]['name'])
        self.assertEqual(group_snapshot3.id,
                         res_dict['group_snapshots'][2]['id'])
        self.assertEqual('creating',
                         res_dict['group_snapshots'][2]['status'])

        group_snapshot3.destroy()
        group_snapshot2.destroy()
        group_snapshot1.destroy()
        db.volume_destroy(context.get_admin_context(),
                          volume_id)
        group.destroy()

    @mock.patch(
        'cinder.api.openstack.wsgi.Controller.validate_name_and_description')
    @mock.patch('cinder.db.volume_type_get')
    @mock.patch('cinder.quota.VolumeTypeQuotaEngine.reserve')
    def test_create_group_snapshot_json(self, mock_quota, mock_vol_type,
                                        mock_validate):
        group = utils.create_group(
            self.context,
            group_type_id=fake.GROUP_TYPE_ID,
            volume_type_ids=[fake.VOLUME_TYPE_ID],)
        volume_id = utils.create_volume(
            self.context,
            group_id=group.id,
            volume_type_id=fake.VOLUME_TYPE_ID)['id']
        body = {"group_snapshot": {"name": "group_snapshot1",
                                   "description":
                                   "Group Snapshot 1",
                                   "group_id": group.id}}
        req = fakes.HTTPRequest.blank('/v3/%s/group_snapshots' %
                                      fake.PROJECT_ID,
                                      version=GROUP_MICRO_VERSION)
        res_dict = self.controller.create(req, body)

        self.assertEqual(1, len(res_dict))
        self.assertIn('id', res_dict['group_snapshot'])
        self.assertTrue(mock_validate.called)

        group.destroy()
        group_snapshot = objects.GroupSnapshot.get_by_id(
            context.get_admin_context(), res_dict['group_snapshot']['id'])
        db.volume_destroy(context.get_admin_context(),
                          volume_id)
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

        group.destroy()
        db.volume_destroy(context.get_admin_context(),
                          volume_id)

    @mock.patch.object(group_api.API, 'create_group_snapshot',
                       side_effect=exception.GroupSnapshotNotFound(
                           group_snapshot_id='invalid_id'))
    def test_create_with_group_snapshot_not_found(self, mock_create_grp_snap):
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
        self.assertRaises(exception.GroupSnapshotNotFound,
                          self.controller.create,
                          req, body)

        group.destroy()
        db.volume_destroy(context.get_admin_context(),
                          volume_id)

    def test_create_group_snapshot_from_empty_group(self):
        group = utils.create_group(
            self.context,
            group_type_id=fake.GROUP_TYPE_ID,
            volume_type_ids=[fake.VOLUME_TYPE_ID],)
        body = {"group_snapshot": {"name": "group_snapshot1",
                                   "description":
                                   "Group Snapshot 1",
                                   "group_id": group.id}}
        req = fakes.HTTPRequest.blank('/v3/%s/group_snapshots' %
                                      fake.PROJECT_ID,
                                      version=GROUP_MICRO_VERSION)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, body)

        group.destroy()

    def test_delete_group_snapshot_available(self):
        group = utils.create_group(
            self.context,
            group_type_id=fake.GROUP_TYPE_ID,
            volume_type_ids=[fake.VOLUME_TYPE_ID],)
        volume_id = utils.create_volume(
            self.context,
            group_id=group.id,
            volume_type_id=fake.VOLUME_TYPE_ID)['id']
        group_snapshot = utils.create_group_snapshot(
            self.context,
            group_id=group.id,
            status='available')
        req = fakes.HTTPRequest.blank('/v3/%s/group_snapshots/%s' %
                                      (fake.PROJECT_ID, group_snapshot.id),
                                      version=GROUP_MICRO_VERSION)
        res_dict = self.controller.delete(req, group_snapshot.id)

        group_snapshot = objects.GroupSnapshot.get_by_id(self.context,
                                                         group_snapshot.id)
        self.assertEqual(202, res_dict.status_int)
        self.assertEqual('deleting', group_snapshot.status)

        group_snapshot.destroy()
        db.volume_destroy(context.get_admin_context(),
                          volume_id)
        group.destroy()

    def test_delete_group_snapshot_available_used_as_source(self):
        group = utils.create_group(
            self.context,
            group_type_id=fake.GROUP_TYPE_ID,
            volume_type_ids=[fake.VOLUME_TYPE_ID],)
        volume_id = utils.create_volume(
            self.context,
            group_id=group.id,
            volume_type_id=fake.VOLUME_TYPE_ID)['id']
        group_snapshot = utils.create_group_snapshot(
            self.context,
            group_id=group.id,
            status='available')

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
        db.volume_destroy(context.get_admin_context(),
                          volume_id)
        group.destroy()
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
        group = utils.create_group(
            self.context,
            group_type_id=fake.GROUP_TYPE_ID,
            volume_type_ids=[fake.VOLUME_TYPE_ID],)
        volume_id = utils.create_volume(
            self.context,
            group_id=group.id,
            volume_type_id=fake.VOLUME_TYPE_ID)['id']
        group_snapshot = utils.create_group_snapshot(
            self.context,
            group_id=group.id,
            status='invalid')
        req = fakes.HTTPRequest.blank('/v3/%s/group_snapshots/%s' %
                                      (fake.PROJECT_ID, group_snapshot.id),
                                      version=GROUP_MICRO_VERSION)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.delete,
                          req, group_snapshot.id)

        group_snapshot.destroy()
        db.volume_destroy(context.get_admin_context(),
                          volume_id)
        group.destroy()

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
        group = utils.create_group(
            self.context,
            group_type_id=fake.GROUP_TYPE_ID,
            volume_type_ids=[fake.VOLUME_TYPE_ID])
        group_snapshot = utils.create_group_snapshot(
            self.context,
            group_id=group.id,
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

    def test_reset_group_snapshot_status(self):
        group = utils.create_group(
            self.context,
            group_type_id=fake.GROUP_TYPE_ID,
            volume_type_ids=[fake.VOLUME_TYPE_ID])
        group_snapshot = utils.create_group_snapshot(
            self.context,
            group_id=group.id,
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
        self.assertEqual(202, response.status_int)
        self.assertEqual(fields.GroupSnapshotStatus.AVAILABLE,
                         g_snapshot.status)
