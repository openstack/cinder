# Copyright (C) 2012 - 2014 EMC Corporation.
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
Tests for cgsnapshot code.
"""

import mock
from oslo_serialization import jsonutils
from six.moves import http_client
import webob

from cinder import context
from cinder import db
from cinder import exception
from cinder.group import api as groupAPI
from cinder import objects
from cinder import test
from cinder.tests.unit.api import fakes
from cinder.tests.unit import fake_constants as fake

from cinder.tests.unit import utils
import cinder.volume


class CgsnapshotsAPITestCase(test.TestCase):
    """Test Case for cgsnapshots API."""

    def setUp(self):
        super(CgsnapshotsAPITestCase, self).setUp()
        self.volume_api = cinder.volume.API()
        self.context = context.get_admin_context()
        self.context.project_id = fake.PROJECT_ID
        self.context.user_id = fake.USER_ID
        self.user_ctxt = context.RequestContext(
            fake.USER_ID, fake.PROJECT_ID, auth_token=True)

    def test_show_cgsnapshot(self):
        vol_type = utils.create_volume_type(context.get_admin_context(),
                                            self, name='my_vol_type')
        consistencygroup = utils.create_group(
            self.context,
            group_type_id=fake.GROUP_TYPE_ID,
            volume_type_ids=[vol_type['id']])
        volume_id = utils.create_volume(self.context,
                                        volume_type_id=vol_type['id'],
                                        group_id=
                                        consistencygroup.id)['id']
        cgsnapshot = utils.create_group_snapshot(
            self.context, group_id=consistencygroup.id,
            group_type_id=fake.GROUP_TYPE_ID,)
        snapshot_id = utils.create_snapshot(
            self.context,
            volume_type_id=vol_type['id'],
            volume_id=volume_id,
            group_snapshot_id=cgsnapshot.id)['id']

        req = webob.Request.blank('/v2/%s/cgsnapshots/%s' % (
            fake.PROJECT_ID, cgsnapshot.id))
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_ctxt))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(http_client.OK, res.status_int)
        self.assertEqual('this is a test group snapshot',
                         res_dict['cgsnapshot']['description'])

        self.assertEqual('test_group_snapshot',
                         res_dict['cgsnapshot']['name'])
        self.assertEqual('creating', res_dict['cgsnapshot']['status'])

        db.snapshot_destroy(context.get_admin_context(), snapshot_id)
        cgsnapshot.destroy()
        db.volume_destroy(context.get_admin_context(), volume_id)
        consistencygroup.destroy()

    def test_show_cgsnapshot_with_cgsnapshot_NotFound(self):
        req = webob.Request.blank('/v2/%s/cgsnapshots/%s' % (
            fake.PROJECT_ID, fake.WILL_NOT_BE_FOUND_ID))
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_ctxt))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(http_client.NOT_FOUND, res.status_int)
        self.assertEqual(http_client.NOT_FOUND,
                         res_dict['itemNotFound']['code'])
        self.assertEqual('GroupSnapshot %s could not be found.' %
                         fake.WILL_NOT_BE_FOUND_ID,
                         res_dict['itemNotFound']['message'])

    def test_list_cgsnapshots_json(self):
        vol_type = utils.create_volume_type(context.get_admin_context(),
                                            self, name='my_vol_type')
        consistencygroup = utils.create_group(
            self.context,
            group_type_id=fake.GROUP_TYPE_ID,
            volume_type_ids=[vol_type['id']])
        volume_id = utils.create_volume(self.context,
                                        volume_type_id=vol_type['id'],
                                        group_id=
                                        consistencygroup.id)['id']
        cgsnapshot1 = utils.create_group_snapshot(
            self.context, group_id=consistencygroup.id,
            group_type_id=fake.GROUP_TYPE_ID,)
        cgsnapshot2 = utils.create_group_snapshot(
            self.context, group_id=consistencygroup.id,
            group_type_id=fake.GROUP_TYPE_ID,)
        cgsnapshot3 = utils.create_group_snapshot(
            self.context, group_id=consistencygroup.id,
            group_type_id=fake.GROUP_TYPE_ID,)

        req = webob.Request.blank('/v2/%s/cgsnapshots' % fake.PROJECT_ID)
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_ctxt))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(http_client.OK, res.status_int)
        self.assertEqual(cgsnapshot3.id,
                         res_dict['cgsnapshots'][0]['id'])
        self.assertEqual('test_group_snapshot',
                         res_dict['cgsnapshots'][0]['name'])
        self.assertEqual(cgsnapshot2.id,
                         res_dict['cgsnapshots'][1]['id'])
        self.assertEqual('test_group_snapshot',
                         res_dict['cgsnapshots'][1]['name'])
        self.assertEqual(cgsnapshot1.id,
                         res_dict['cgsnapshots'][2]['id'])
        self.assertEqual('test_group_snapshot',
                         res_dict['cgsnapshots'][2]['name'])

        cgsnapshot3.destroy()
        cgsnapshot2.destroy()
        cgsnapshot1.destroy()
        db.volume_destroy(context.get_admin_context(), volume_id)
        consistencygroup.destroy()

    def test_list_cgsnapshots_detail_json(self):
        vol_type = utils.create_volume_type(context.get_admin_context(),
                                            self, name='my_vol_type')
        consistencygroup = utils.create_group(
            self.context,
            group_type_id=fake.GROUP_TYPE_ID,
            volume_type_ids=[vol_type['id']])
        volume_id = utils.create_volume(self.context,
                                        volume_type_id=vol_type['id'],
                                        group_id=
                                        consistencygroup.id)['id']
        cgsnapshot1 = utils.create_group_snapshot(
            self.context, group_id=consistencygroup.id,
            group_type_id=fake.GROUP_TYPE_ID,)
        cgsnapshot2 = utils.create_group_snapshot(
            self.context, group_id=consistencygroup.id,
            group_type_id=fake.GROUP_TYPE_ID,)
        cgsnapshot3 = utils.create_group_snapshot(
            self.context, group_id=consistencygroup.id,
            group_type_id=fake.GROUP_TYPE_ID,)

        req = webob.Request.blank('/v2/%s/cgsnapshots/detail' %
                                  fake.PROJECT_ID)
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/json'
        req.headers['Accept'] = 'application/json'
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_ctxt))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(http_client.OK, res.status_int)
        self.assertEqual('this is a test group snapshot',
                         res_dict['cgsnapshots'][0]['description'])
        self.assertEqual('test_group_snapshot',
                         res_dict['cgsnapshots'][0]['name'])
        self.assertEqual(cgsnapshot3.id,
                         res_dict['cgsnapshots'][0]['id'])
        self.assertEqual('creating',
                         res_dict['cgsnapshots'][0]['status'])

        self.assertEqual('this is a test group snapshot',
                         res_dict['cgsnapshots'][1]['description'])
        self.assertEqual('test_group_snapshot',
                         res_dict['cgsnapshots'][1]['name'])
        self.assertEqual(cgsnapshot2.id,
                         res_dict['cgsnapshots'][1]['id'])
        self.assertEqual('creating',
                         res_dict['cgsnapshots'][1]['status'])

        self.assertEqual('this is a test group snapshot',
                         res_dict['cgsnapshots'][2]['description'])
        self.assertEqual('test_group_snapshot',
                         res_dict['cgsnapshots'][2]['name'])
        self.assertEqual(cgsnapshot1.id,
                         res_dict['cgsnapshots'][2]['id'])
        self.assertEqual('creating',
                         res_dict['cgsnapshots'][2]['status'])

        cgsnapshot3.destroy()
        cgsnapshot2.destroy()
        cgsnapshot1.destroy()
        db.volume_destroy(context.get_admin_context(), volume_id)
        consistencygroup.destroy()

    @mock.patch(
        'cinder.api.openstack.wsgi.Controller.validate_name_and_description')
    def test_create_cgsnapshot_json(self, mock_validate):
        vol_type = utils.create_volume_type(context.get_admin_context(),
                                            self, name='my_vol_type')
        consistencygroup = utils.create_group(
            self.context,
            group_type_id=fake.GROUP_TYPE_ID,
            volume_type_ids=[vol_type['id']])
        volume_id = utils.create_volume(self.context,
                                        volume_type_id=vol_type['id'],
                                        group_id=
                                        consistencygroup.id)['id']

        body = {"cgsnapshot": {"name": "cg1",
                               "description":
                               "CG Snapshot 1",
                               "consistencygroup_id": consistencygroup.id}}
        req = webob.Request.blank('/v2/%s/cgsnapshots' % fake.PROJECT_ID)
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_ctxt))

        res_dict = jsonutils.loads(res.body)

        self.assertEqual(http_client.ACCEPTED, res.status_int)
        self.assertIn('id', res_dict['cgsnapshot'])
        self.assertTrue(mock_validate.called)

        cgsnapshot = objects.GroupSnapshot.get_by_id(
            context.get_admin_context(), res_dict['cgsnapshot']['id'])
        cgsnapshot.destroy()
        db.volume_destroy(context.get_admin_context(), volume_id)
        consistencygroup.destroy()

    @mock.patch(
        'cinder.api.openstack.wsgi.Controller.validate_name_and_description')
    def test_create_cgsnapshot_when_volume_in_error_status(self,
                                                           mock_validate):
        vol_type = utils.create_volume_type(context.get_admin_context(),
                                            self, name='my_vol_type')
        consistencygroup = utils.create_group(
            self.context,
            group_type_id=fake.GROUP_TYPE_ID,
            volume_type_ids=[vol_type['id']])
        volume_id = utils.create_volume(self.context,
                                        volume_type_id=vol_type['id'],
                                        group_id=consistencygroup.id,
                                        status='error')['id']

        body = {"cgsnapshot": {"name": "cg1",
                               "description":
                               "CG Snapshot 1",
                               "consistencygroup_id": consistencygroup.id}}
        req = webob.Request.blank('/v2/%s/cgsnapshots' % fake.PROJECT_ID)
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_ctxt))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(http_client.BAD_REQUEST, res.status_int)
        self.assertEqual(http_client.BAD_REQUEST,
                         res_dict['badRequest']['code'])
        self.assertEqual(
            "Invalid volume: The snapshot cannot be created when the volume "
            "is in error status.",
            res_dict['badRequest']['message']
        )
        self.assertTrue(mock_validate.called)

        db.volume_destroy(context.get_admin_context(), volume_id)
        consistencygroup.destroy()

    def test_create_cgsnapshot_with_no_body(self):
        # omit body from the request
        req = webob.Request.blank('/v2/%s/cgsnapshots' % fake.PROJECT_ID)
        req.body = jsonutils.dump_as_bytes(None)
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.headers['Accept'] = 'application/json'
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_ctxt))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(http_client.BAD_REQUEST, res.status_int)
        self.assertEqual(http_client.BAD_REQUEST,
                         res_dict['badRequest']['code'])
        self.assertEqual("Missing required element 'cgsnapshot' in "
                         "request body.",
                         res_dict['badRequest']['message'])

    @mock.patch.object(groupAPI.API, 'create_group_snapshot',
                       side_effect=exception.InvalidGroupSnapshot(
                           reason='invalid group_snapshot'))
    def test_create_with_invalid_cgsnapshot(self, mock_create_cgsnapshot):
        vol_type = utils.create_volume_type(context.get_admin_context(),
                                            self, name='my_vol_type')
        consistencygroup = utils.create_group(
            self.context,
            group_type_id=fake.GROUP_TYPE_ID,
            volume_type_ids=[vol_type['id']])
        volume_id = utils.create_volume(self.context,
                                        volume_type_id=vol_type['id'],
                                        group_id=consistencygroup.id)['id']

        body = {"cgsnapshot": {"name": "cg1",
                               "description":
                               "CG Snapshot 1",
                               "consistencygroup_id": consistencygroup.id}}
        req = webob.Request.blank('/v2/%s/cgsnapshots' % fake.PROJECT_ID)
        req.body = jsonutils.dump_as_bytes(body)
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_ctxt))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(http_client.BAD_REQUEST, res.status_int)
        self.assertEqual(http_client.BAD_REQUEST,
                         res_dict['badRequest']['code'])
        self.assertEqual('Invalid GroupSnapshot: invalid group_snapshot',
                         res_dict['badRequest']['message'])

        db.volume_destroy(context.get_admin_context(), volume_id)
        consistencygroup.destroy()

    @mock.patch.object(groupAPI.API, 'create_group_snapshot',
                       side_effect=exception.GroupSnapshotNotFound(
                           group_snapshot_id='invalid_id'))
    def test_create_with_cgsnapshot_not_found(self, mock_create_cgsnapshot):
        vol_type = utils.create_volume_type(context.get_admin_context(),
                                            self, name='my_vol_type')
        consistencygroup = utils.create_group(
            self.context,
            group_type_id=fake.GROUP_TYPE_ID,
            volume_type_ids=[vol_type['id']])
        volume_id = utils.create_volume(self.context,
                                        volume_type_id=vol_type['id'],
                                        group_id=consistencygroup.id)['id']

        body = {"cgsnapshot": {"name": "cg1",
                               "description":
                               "CG Snapshot 1",
                               "consistencygroup_id": consistencygroup.id}}

        req = webob.Request.blank('/v2/%s/cgsnapshots' % fake.PROJECT_ID)
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_ctxt))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(http_client.NOT_FOUND, res.status_int)
        self.assertEqual(http_client.NOT_FOUND,
                         res_dict['itemNotFound']['code'])
        self.assertEqual('GroupSnapshot invalid_id could not be found.',
                         res_dict['itemNotFound']['message'])

        db.volume_destroy(context.get_admin_context(), volume_id)
        consistencygroup.destroy()

    def test_create_cgsnapshot_from_empty_consistencygroup(self):
        vol_type = utils.create_volume_type(context.get_admin_context(),
                                            self, name='my_vol_type')
        consistencygroup = utils.create_group(
            self.context,
            group_type_id=fake.GROUP_TYPE_ID,
            volume_type_ids=[vol_type['id']])

        body = {"cgsnapshot": {"name": "cg1",
                               "description":
                               "CG Snapshot 1",
                               "consistencygroup_id": consistencygroup.id}}

        req = webob.Request.blank('/v2/%s/cgsnapshots' % fake.PROJECT_ID)
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_ctxt))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(http_client.BAD_REQUEST, res.status_int)
        self.assertEqual(http_client.BAD_REQUEST,
                         res_dict['badRequest']['code'])
        self.assertIsNotNone(res_dict['badRequest']['message'])

        # If failed to create cgsnapshot, its DB object should not be created
        self.assertListEqual(
            [],
            list(objects.GroupSnapshotList.get_all(self.context)))
        consistencygroup.destroy()

    def test_delete_cgsnapshot_available(self):
        vol_type = utils.create_volume_type(context.get_admin_context(),
                                            self, name='my_vol_type')
        consistencygroup = utils.create_group(
            self.context,
            group_type_id=fake.GROUP_TYPE_ID,
            volume_type_ids=[vol_type['id']])
        volume_id = utils.create_volume(self.context,
                                        volume_type_id=vol_type['id'],
                                        group_id=
                                        consistencygroup.id)['id']
        cgsnapshot = utils.create_group_snapshot(
            self.context, group_id=consistencygroup.id,
            group_type_id=fake.GROUP_TYPE_ID,
            status='available')
        req = webob.Request.blank('/v2/%s/cgsnapshots/%s' %
                                  (fake.PROJECT_ID, cgsnapshot.id))
        req.method = 'DELETE'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_ctxt))

        cgsnapshot = objects.GroupSnapshot.get_by_id(self.context,
                                                     cgsnapshot.id)
        self.assertEqual(http_client.ACCEPTED, res.status_int)
        self.assertEqual('deleting', cgsnapshot.status)

        cgsnapshot.destroy()
        db.volume_destroy(context.get_admin_context(), volume_id)
        consistencygroup.destroy()

    def test_delete_cgsnapshot_available_used_as_source(self):
        vol_type = utils.create_volume_type(context.get_admin_context(),
                                            self, name='my_vol_type')
        consistencygroup = utils.create_group(
            self.context,
            group_type_id=fake.GROUP_TYPE_ID,
            volume_type_ids=[vol_type['id']])
        volume_id = utils.create_volume(self.context,
                                        volume_type_id=vol_type['id'],
                                        group_id=
                                        consistencygroup.id)['id']
        cgsnapshot = utils.create_group_snapshot(
            self.context, group_id=consistencygroup.id,
            group_type_id=fake.GROUP_TYPE_ID,
            status='available')

        cg2 = utils.create_consistencygroup(
            self.context, status='creating',
            group_snapshot_id=cgsnapshot.id,
            group_type_id=fake.GROUP_TYPE_ID)
        req = webob.Request.blank('/v2/fake/cgsnapshots/%s' %
                                  cgsnapshot.id)
        req.method = 'DELETE'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app())

        cgsnapshot = objects.GroupSnapshot.get_by_id(self.context,
                                                     cgsnapshot.id)
        self.assertEqual(http_client.BAD_REQUEST, res.status_int)
        self.assertEqual('available', cgsnapshot.status)

        cgsnapshot.destroy()
        db.volume_destroy(context.get_admin_context(), volume_id)
        consistencygroup.destroy()
        cg2.destroy()

    def test_delete_cgsnapshot_with_cgsnapshot_NotFound(self):
        req = webob.Request.blank('/v2/%s/cgsnapshots/%s' %
                                  (fake.PROJECT_ID, fake.WILL_NOT_BE_FOUND_ID))
        req.method = 'DELETE'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_ctxt))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(http_client.NOT_FOUND, res.status_int)
        self.assertEqual(http_client.NOT_FOUND,
                         res_dict['itemNotFound']['code'])
        self.assertEqual('GroupSnapshot %s could not be found.' %
                         fake.WILL_NOT_BE_FOUND_ID,
                         res_dict['itemNotFound']['message'])

    def test_delete_cgsnapshot_with_invalid_cgsnapshot(self):
        vol_type = utils.create_volume_type(context.get_admin_context(),
                                            self, name='my_vol_type')
        consistencygroup = utils.create_group(
            self.context,
            group_type_id=fake.GROUP_TYPE_ID,
            volume_type_ids=[vol_type['id']])
        volume_id = utils.create_volume(self.context,
                                        volume_type_id=vol_type['id'],
                                        group_id=
                                        consistencygroup.id)['id']
        cgsnapshot = utils.create_group_snapshot(
            self.context, group_id=consistencygroup.id,
            group_type_id=fake.GROUP_TYPE_ID,
            status='invalid')

        req = webob.Request.blank('/v2/%s/cgsnapshots/%s' % (
            fake.PROJECT_ID, cgsnapshot.id))
        req.method = 'DELETE'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_ctxt))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(http_client.BAD_REQUEST, res.status_int)
        self.assertEqual(http_client.BAD_REQUEST,
                         res_dict['badRequest']['code'])
        self.assertIsNotNone(res_dict['badRequest']['message'])

        cgsnapshot.destroy()
        db.volume_destroy(context.get_admin_context(), volume_id)
        consistencygroup.destroy()

    @mock.patch('cinder.group.API.delete_group_snapshot')
    def test_delete_cgsnapshot_delete_policy_not_auth(self, mock_delete):
        vol_type = utils.create_volume_type(context.get_admin_context(),
                                            self, name='my_vol_type')
        consistencygroup = utils.create_group(
            self.context,
            group_type_id=fake.GROUP_TYPE_ID,
            volume_type_ids=[vol_type['id']])
        volume_id = utils.create_volume(self.context,
                                        volume_type_id=vol_type['id'],
                                        group_id=
                                        consistencygroup.id)['id']
        cgsnapshot = utils.create_group_snapshot(
            self.context, group_id=consistencygroup.id,
            group_type_id=fake.GROUP_TYPE_ID,
            status='available')
        mock_delete.side_effect = exception.PolicyNotAuthorized(
            message='PolicyNotAuthorized')
        req = webob.Request.blank('/v2/%s/cgsnapshots/%s' %
                                  (fake.PROJECT_ID, cgsnapshot.id))
        req.method = 'DELETE'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_ctxt))
        res_dict = jsonutils.loads(res.body)
        self.assertEqual('PolicyNotAuthorized',
                         res_dict['forbidden']['message'])
        cgsnapshot.destroy()
        db.volume_destroy(context.get_admin_context(), volume_id)
        consistencygroup.destroy()
