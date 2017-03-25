# Copyright (C) 2012 Hewlett-Packard Development Company, L.P.
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
Tests for volume transfer code.
"""

import mock

from oslo_serialization import jsonutils
from six.moves import http_client
import webob

from cinder.api.contrib import volume_transfer
from cinder import context
from cinder import db
from cinder import exception
from cinder.objects import fields
from cinder import test
from cinder.tests.unit.api import fakes
from cinder.tests.unit import fake_constants as fake
import cinder.transfer


class VolumeTransferAPITestCase(test.TestCase):
    """Test Case for transfers API."""

    def setUp(self):
        super(VolumeTransferAPITestCase, self).setUp()
        self.volume_transfer_api = cinder.transfer.API()
        self.controller = volume_transfer.VolumeTransferController()
        self.user_ctxt = context.RequestContext(
            fake.USER_ID, fake.PROJECT_ID, auth_token=True, is_admin=True)

    def _create_transfer(self, volume_id=fake.VOLUME_ID,
                         display_name='test_transfer'):
        """Create a transfer object."""
        return self.volume_transfer_api.create(context.get_admin_context(),
                                               volume_id,
                                               display_name)

    @staticmethod
    def _create_volume(display_name='test_volume',
                       display_description='this is a test volume',
                       status='available',
                       size=1,
                       project_id=fake.PROJECT_ID,
                       attach_status=fields.VolumeAttachStatus.DETACHED):
        """Create a volume object."""
        vol = {}
        vol['host'] = 'fake_host'
        vol['size'] = size
        vol['user_id'] = fake.USER_ID
        vol['project_id'] = project_id
        vol['status'] = status
        vol['display_name'] = display_name
        vol['display_description'] = display_description
        vol['attach_status'] = attach_status
        vol['availability_zone'] = 'fake_zone'
        return db.volume_create(context.get_admin_context(), vol)['id']

    def test_show_transfer(self):
        volume_id = self._create_volume(size=5)
        transfer = self._create_transfer(volume_id)
        req = webob.Request.blank('/v2/%s/os-volume-transfer/%s' % (
            fake.PROJECT_ID, transfer['id']))
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_ctxt))
        res_dict = jsonutils.loads(res.body)
        self.assertEqual(http_client.OK, res.status_int)
        self.assertEqual('test_transfer', res_dict['transfer']['name'])
        self.assertEqual(transfer['id'], res_dict['transfer']['id'])
        self.assertEqual(volume_id, res_dict['transfer']['volume_id'])

        db.transfer_destroy(context.get_admin_context(), transfer['id'])
        db.volume_destroy(context.get_admin_context(), volume_id)

    def test_show_transfer_with_transfer_NotFound(self):
        req = webob.Request.blank('/v2/%s/os-volume-transfer/%s' % (
            fake.PROJECT_ID, fake.WILL_NOT_BE_FOUND_ID))
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_ctxt))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(http_client.NOT_FOUND, res.status_int)
        self.assertEqual(http_client.NOT_FOUND,
                         res_dict['itemNotFound']['code'])
        self.assertEqual('Transfer %s could not be found.' %
                         fake.WILL_NOT_BE_FOUND_ID,
                         res_dict['itemNotFound']['message'])

    def test_list_transfers_json(self):
        volume_id_1 = self._create_volume(size=5)
        volume_id_2 = self._create_volume(size=5)
        transfer1 = self._create_transfer(volume_id_1)
        transfer2 = self._create_transfer(volume_id_2)

        req = webob.Request.blank('/v2/%s/os-volume-transfer' %
                                  fake.PROJECT_ID)
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_ctxt))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(http_client.OK, res.status_int)
        self.assertEqual(4, len(res_dict['transfers'][0]))
        self.assertEqual(transfer1['id'], res_dict['transfers'][0]['id'])
        self.assertEqual('test_transfer', res_dict['transfers'][0]['name'])
        self.assertEqual(4, len(res_dict['transfers'][1]))
        self.assertEqual('test_transfer', res_dict['transfers'][1]['name'])

        db.transfer_destroy(context.get_admin_context(), transfer2['id'])
        db.transfer_destroy(context.get_admin_context(), transfer1['id'])
        db.volume_destroy(context.get_admin_context(), volume_id_1)
        db.volume_destroy(context.get_admin_context(), volume_id_2)

    def test_list_transfers_detail_json(self):
        volume_id_1 = self._create_volume(size=5)
        volume_id_2 = self._create_volume(size=5)
        transfer1 = self._create_transfer(volume_id_1)
        transfer2 = self._create_transfer(volume_id_2)

        req = webob.Request.blank('/v2/%s/os-volume-transfer/detail' %
                                  fake.PROJECT_ID)
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/json'
        req.headers['Accept'] = 'application/json'
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_ctxt))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(http_client.OK, res.status_int)
        self.assertEqual(5, len(res_dict['transfers'][0]))
        self.assertEqual('test_transfer',
                         res_dict['transfers'][0]['name'])
        self.assertEqual(transfer1['id'], res_dict['transfers'][0]['id'])
        self.assertEqual(volume_id_1, res_dict['transfers'][0]['volume_id'])

        self.assertEqual(5, len(res_dict['transfers'][1]))
        self.assertEqual('test_transfer',
                         res_dict['transfers'][1]['name'])
        self.assertEqual(transfer2['id'], res_dict['transfers'][1]['id'])
        self.assertEqual(volume_id_2, res_dict['transfers'][1]['volume_id'])

        db.transfer_destroy(context.get_admin_context(), transfer2['id'])
        db.transfer_destroy(context.get_admin_context(), transfer1['id'])
        db.volume_destroy(context.get_admin_context(), volume_id_2)
        db.volume_destroy(context.get_admin_context(), volume_id_1)

    def test_list_transfers_with_all_tenants(self):
        volume_id_1 = self._create_volume(size=5)
        volume_id_2 = self._create_volume(size=5, project_id=fake.PROJECT_ID)
        transfer1 = self._create_transfer(volume_id_1)
        transfer2 = self._create_transfer(volume_id_2)

        req = fakes.HTTPRequest.blank('/v2/%s/os-volume-transfer?'
                                      'all_tenants=1' % fake.PROJECT_ID,
                                      use_admin_context=True)
        res_dict = self.controller.index(req)

        expected = [(transfer1['id'], 'test_transfer'),
                    (transfer2['id'], 'test_transfer')]
        ret = []
        for item in res_dict['transfers']:
            ret.append((item['id'], item['name']))
        self.assertEqual(set(expected), set(ret))

        db.transfer_destroy(context.get_admin_context(), transfer2['id'])
        db.transfer_destroy(context.get_admin_context(), transfer1['id'])
        db.volume_destroy(context.get_admin_context(), volume_id_1)

    @mock.patch(
        'cinder.api.openstack.wsgi.Controller.validate_string_length')
    def test_create_transfer_json(self, mock_validate):
        volume_id = self._create_volume(status='available', size=5)
        body = {"transfer": {"name": "transfer1",
                             "volume_id": volume_id}}

        req = webob.Request.blank('/v2/%s/os-volume-transfer' %
                                  fake.PROJECT_ID)
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_ctxt))

        res_dict = jsonutils.loads(res.body)

        self.assertEqual(http_client.ACCEPTED, res.status_int)
        self.assertIn('id', res_dict['transfer'])
        self.assertIn('auth_key', res_dict['transfer'])
        self.assertIn('created_at', res_dict['transfer'])
        self.assertIn('name', res_dict['transfer'])
        self.assertIn('volume_id', res_dict['transfer'])
        self.assertTrue(mock_validate.called)

        db.volume_destroy(context.get_admin_context(), volume_id)

    def test_create_transfer_with_no_body(self):
        req = webob.Request.blank('/v2/%s/os-volume-transfer' %
                                  fake.PROJECT_ID)
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
        self.assertEqual("Missing required element 'transfer' in "
                         "request body.",
                         res_dict['badRequest']['message'])

    def test_create_transfer_with_body_KeyError(self):
        body = {"transfer": {"name": "transfer1"}}
        req = webob.Request.blank('/v2/%s/os-volume-transfer' %
                                  fake.PROJECT_ID)
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_ctxt))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(http_client.BAD_REQUEST, res.status_int)
        self.assertEqual(http_client.BAD_REQUEST,
                         res_dict['badRequest']['code'])
        self.assertEqual('Incorrect request body format',
                         res_dict['badRequest']['message'])

    def test_create_transfer_with_VolumeNotFound(self):
        body = {"transfer": {"name": "transfer1",
                             "volume_id": 1234}}

        req = webob.Request.blank('/v2/%s/os-volume-transfer' %
                                  fake.PROJECT_ID)
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_ctxt))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(http_client.NOT_FOUND, res.status_int)
        self.assertEqual(http_client.NOT_FOUND,
                         res_dict['itemNotFound']['code'])
        self.assertEqual('Volume 1234 could not be found.',
                         res_dict['itemNotFound']['message'])

    def test_create_transfer_with_InvalidVolume(self):
        volume_id = self._create_volume(status='attached')
        body = {"transfer": {"name": "transfer1",
                             "volume_id": volume_id}}
        req = webob.Request.blank('/v2/%s/os-volume-transfer' %
                                  fake.PROJECT_ID)
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_ctxt))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(http_client.BAD_REQUEST, res.status_int)
        self.assertEqual(http_client.BAD_REQUEST,
                         res_dict['badRequest']['code'])
        self.assertEqual('Invalid volume: status must be available',
                         res_dict['badRequest']['message'])

        db.volume_destroy(context.get_admin_context(), volume_id)

    def test_delete_transfer_awaiting_transfer(self):
        volume_id = self._create_volume()
        transfer = self._create_transfer(volume_id)
        req = webob.Request.blank('/v2/%s/os-volume-transfer/%s' % (
                                  fake.PROJECT_ID, transfer['id']))
        req.method = 'DELETE'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_ctxt))

        self.assertEqual(http_client.ACCEPTED, res.status_int)

        # verify transfer has been deleted
        req = webob.Request.blank('/v2/%s/os-volume-transfer/%s' % (
            fake.PROJECT_ID, transfer['id']))
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_ctxt))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(http_client.NOT_FOUND, res.status_int)
        self.assertEqual(http_client.NOT_FOUND,
                         res_dict['itemNotFound']['code'])
        self.assertEqual('Transfer %s could not be found.' % transfer['id'],
                         res_dict['itemNotFound']['message'])
        self.assertEqual(db.volume_get(context.get_admin_context(),
                         volume_id)['status'], 'available')

        db.volume_destroy(context.get_admin_context(), volume_id)

    def test_delete_transfer_with_transfer_NotFound(self):
        req = webob.Request.blank('/v2/%s/os-volume-transfer/%s' % (
            fake.PROJECT_ID, fake.WILL_NOT_BE_FOUND_ID))
        req.method = 'DELETE'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_ctxt))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(http_client.NOT_FOUND, res.status_int)
        self.assertEqual(http_client.NOT_FOUND,
                         res_dict['itemNotFound']['code'])
        self.assertEqual('Transfer %s could not be found.' %
                         fake.WILL_NOT_BE_FOUND_ID,
                         res_dict['itemNotFound']['message'])

    def test_accept_transfer_volume_id_specified_json(self):
        volume_id = self._create_volume()
        transfer = self._create_transfer(volume_id)

        svc = self.start_service('volume', host='fake_host')
        body = {"accept": {"id": transfer['id'],
                           "auth_key": transfer['auth_key']}}
        req = webob.Request.blank('/v2/%s/os-volume-transfer/%s/accept' % (
                                  fake.PROJECT_ID, transfer['id']))
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_ctxt))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(http_client.ACCEPTED, res.status_int)
        self.assertEqual(transfer['id'], res_dict['transfer']['id'])
        self.assertEqual(volume_id, res_dict['transfer']['volume_id'])
        # cleanup
        svc.stop()

    def test_accept_transfer_with_no_body(self):
        volume_id = self._create_volume(size=5)
        transfer = self._create_transfer(volume_id)

        req = webob.Request.blank('/v2/%s/os-volume-transfer/%s/accept' % (
                                  fake.PROJECT_ID, transfer['id']))
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
        self.assertEqual("Missing required element 'accept' in request body.",
                         res_dict['badRequest']['message'])

        db.volume_destroy(context.get_admin_context(), volume_id)

    def test_accept_transfer_with_body_KeyError(self):
        volume_id = self._create_volume(size=5)
        transfer = self._create_transfer(volume_id)

        req = webob.Request.blank('/v2/%s/os-volume-transfer/%s/accept' % (
                                  fake.PROJECT_ID, transfer['id']))
        body = {"": {}}
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.headers['Accept'] = 'application/json'
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_ctxt))

        res_dict = jsonutils.loads(res.body)

        self.assertEqual(http_client.BAD_REQUEST, res.status_int)
        self.assertEqual(http_client.BAD_REQUEST,
                         res_dict['badRequest']['code'])
        self.assertEqual("Missing required element 'accept' in request body.",
                         res_dict['badRequest']['message'])

    def test_accept_transfer_invalid_id_auth_key(self):
        volume_id = self._create_volume()
        transfer = self._create_transfer(volume_id)

        body = {"accept": {"id": transfer['id'],
                           "auth_key": 1}}
        req = webob.Request.blank('/v2/%s/os-volume-transfer/%s/accept' % (
                                  fake.PROJECT_ID, transfer['id']))
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_ctxt))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(http_client.BAD_REQUEST, res.status_int)
        self.assertEqual(http_client.BAD_REQUEST,
                         res_dict['badRequest']['code'])
        self.assertEqual(res_dict['badRequest']['message'],
                         'Invalid auth key: Attempt to transfer %s with '
                         'invalid auth key.' % transfer['id'])

        db.transfer_destroy(context.get_admin_context(), transfer['id'])
        db.volume_destroy(context.get_admin_context(), volume_id)

    def test_accept_transfer_with_invalid_transfer(self):
        volume_id = self._create_volume()
        transfer = self._create_transfer(volume_id)

        body = {"accept": {"id": transfer['id'],
                           "auth_key": 1}}
        req = webob.Request.blank('/v2/%s/os-volume-transfer/%s/accept' % (
            fake.PROJECT_ID, fake.WILL_NOT_BE_FOUND_ID))
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_ctxt))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(http_client.NOT_FOUND, res.status_int)
        self.assertEqual(http_client.NOT_FOUND,
                         res_dict['itemNotFound']['code'])
        self.assertEqual('Transfer %s could not be found.' %
                         fake.WILL_NOT_BE_FOUND_ID,
                         res_dict['itemNotFound']['message'])

        db.transfer_destroy(context.get_admin_context(), transfer['id'])
        db.volume_destroy(context.get_admin_context(), volume_id)

    def test_accept_transfer_with_VolumeSizeExceedsAvailableQuota(self):

        def fake_transfer_api_accept_throwing_VolumeSizeExceedsAvailableQuota(
                cls, context, transfer, volume_id):
            raise exception.VolumeSizeExceedsAvailableQuota(requested='2',
                                                            consumed='2',
                                                            quota='3')

        self.mock_object(
            cinder.transfer.API,
            'accept',
            fake_transfer_api_accept_throwing_VolumeSizeExceedsAvailableQuota)

        volume_id = self._create_volume()
        transfer = self._create_transfer(volume_id)

        body = {"accept": {"id": transfer['id'],
                           "auth_key": transfer['auth_key']}}
        req = webob.Request.blank('/v2/%s/os-volume-transfer/%s/accept' % (
                                  fake.PROJECT_ID, transfer['id']))

        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_ctxt))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(413, res.status_int)
        self.assertEqual(413, res_dict['overLimit']['code'])
        self.assertEqual('Requested volume or snapshot exceeds allowed '
                         'gigabytes quota. Requested 2G, quota is 3G and '
                         '2G has been consumed.',
                         res_dict['overLimit']['message'])

    def test_accept_transfer_with_VolumeLimitExceeded(self):

        def fake_transfer_api_accept_throwing_VolumeLimitExceeded(cls,
                                                                  context,
                                                                  transfer,
                                                                  volume_id):
            raise exception.VolumeLimitExceeded(allowed=1)

        self.mock_object(cinder.transfer.API, 'accept',
                         fake_transfer_api_accept_throwing_VolumeLimitExceeded)

        volume_id = self._create_volume()
        transfer = self._create_transfer(volume_id)

        body = {"accept": {"id": transfer['id'],
                           "auth_key": transfer['auth_key']}}
        req = webob.Request.blank('/v2/%s/os-volume-transfer/%s/accept' % (
                                  fake.PROJECT_ID, transfer['id']))

        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_ctxt))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(413, res.status_int)
        self.assertEqual(413, res_dict['overLimit']['code'])
        self.assertEqual("VolumeLimitExceeded: Maximum number of volumes "
                         "allowed (1) exceeded for quota 'volumes'.",
                         res_dict['overLimit']['message'])
