# Copyright 2018 FiberHome Telecommunication Technologies CO.,LTD
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

"""Tests for volume transfer code."""

from http import HTTPStatus
from unittest import mock

import ddt
from oslo_serialization import jsonutils
import webob

from cinder.api.contrib import volume_transfer
from cinder.api import microversions as mv
from cinder.api.v3 import volume_transfer as volume_transfer_v3
from cinder import context
from cinder import db
from cinder.objects import fields
from cinder import quota
from cinder.tests.unit.api import fakes
from cinder.tests.unit.api.v2 import fakes as v2_fakes
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import test
import cinder.transfer


@ddt.ddt
class VolumeTransferAPITestCase(test.TestCase):
    """Test Case for transfers V3 API."""

    microversion = mv.TRANSFER_WITH_SNAPSHOTS
    expect_transfer_history = False
    DETAIL_LEN = 6
    SUMMARY_LEN = 4

    def setUp(self):
        super(VolumeTransferAPITestCase, self).setUp()
        self.volume_transfer_api = cinder.transfer.API()
        self.controller = volume_transfer.VolumeTransferController()
        self.v3_controller = volume_transfer_v3.VolumeTransferController()
        self.user_ctxt = context.RequestContext(
            fake.USER_ID, fake.PROJECT_ID, auth_token=True, is_admin=True)

    def _create_transfer(self, volume_id=fake.VOLUME_ID,
                         display_name='test_transfer'):
        """Create a transfer object."""
        transfer = self.volume_transfer_api.create(context.get_admin_context(),
                                                   volume_id, display_name)
        self.addCleanup(db.transfer_destroy, context.get_admin_context(),
                        transfer['id'])
        return transfer

    def _create_volume(self, display_name='test_volume',
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
        vol['volume_type_id'] = fake.VOLUME_TYPE_ID
        volume_id = db.volume_create(context.get_admin_context(), vol)['id']
        self.addCleanup(db.volume_destroy, context.get_admin_context(),
                        volume_id)
        return volume_id

    def _check_history_in_res(self, transfer_dict):
        tx_history_keys = ['source_project_id',
                           'destination_project_id',
                           'accepted']
        if self.expect_transfer_history:
            for key in tx_history_keys:
                self.assertIn(key, transfer_dict)
        else:
            for key in tx_history_keys:
                self.assertNotIn(key, transfer_dict)

    def test_show_transfer(self):
        volume_id = self._create_volume(size=5)
        transfer = self._create_transfer(volume_id)
        req = webob.Request.blank('/v3/%s/volume-transfers/%s' % (
            fake.PROJECT_ID, transfer['id']))
        req.method = 'GET'
        req.headers = mv.get_mv_header(self.microversion)
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_ctxt))
        res_dict = jsonutils.loads(res.body)
        self.assertEqual(HTTPStatus.OK, res.status_int)
        self.assertEqual('test_transfer', res_dict['transfer']['name'])
        self.assertEqual(transfer['id'], res_dict['transfer']['id'])
        self.assertEqual(volume_id, res_dict['transfer']['volume_id'])

    def test_list_transfers(self):
        volume_id_1 = self._create_volume(size=5)
        volume_id_2 = self._create_volume(size=5)
        transfer1 = self._create_transfer(volume_id_1)
        transfer2 = self._create_transfer(volume_id_2)

        req = webob.Request.blank('/v3/%s/volume-transfers' %
                                  fake.PROJECT_ID)
        req.method = 'GET'
        req.headers = mv.get_mv_header(self.microversion)
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_ctxt))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(HTTPStatus.OK, res.status_int)
        self.assertEqual(self.SUMMARY_LEN, len(res_dict['transfers'][0]))
        self.assertEqual(transfer1['id'], res_dict['transfers'][0]['id'])
        self.assertEqual('test_transfer', res_dict['transfers'][0]['name'])
        self.assertEqual(self.SUMMARY_LEN, len(res_dict['transfers'][1]))
        self.assertEqual(transfer2['id'], res_dict['transfers'][1]['id'])
        self.assertEqual('test_transfer', res_dict['transfers'][1]['name'])

    def test_list_transfers_with_limit(self):
        volume_id_1 = self._create_volume(size=5)
        volume_id_2 = self._create_volume(size=5)
        self._create_transfer(volume_id_1)
        self._create_transfer(volume_id_2)
        url = '/v3/%s/volume-transfers?limit=1' % fake.PROJECT_ID
        req = fakes.HTTPRequest.blank(url,
                                      version=mv.SUPPORT_TRANSFER_PAGINATION,
                                      use_admin_context=True)
        res_dict = self.v3_controller.index(req)

        self.assertEqual(1, len(res_dict['transfers']))

    def test_list_transfers_with_marker(self):
        volume_id_1 = self._create_volume(size=5)
        volume_id_2 = self._create_volume(size=5)
        transfer1 = self._create_transfer(volume_id_1)
        transfer2 = self._create_transfer(volume_id_2)
        url = '/v3/%s/volume-transfers?marker=%s' % (fake.PROJECT_ID,
                                                     transfer2['id'])
        req = fakes.HTTPRequest.blank(url,
                                      version=mv.SUPPORT_TRANSFER_PAGINATION,
                                      use_admin_context=True)
        res_dict = self.v3_controller.index(req)

        self.assertEqual(1, len(res_dict['transfers']))
        self.assertEqual(transfer1['id'],
                         res_dict['transfers'][0]['id'])

    @ddt.data("desc", "asc")
    def test_list_transfers_with_sort(self, sort_dir):
        volume_id_1 = self._create_volume(size=5)
        volume_id_2 = self._create_volume(size=5)
        transfer1 = self._create_transfer(volume_id_1)
        transfer2 = self._create_transfer(volume_id_2)
        url = '/v3/%s/volume-transfers?sort_key=id&sort_dir=%s' % (
            fake.PROJECT_ID, sort_dir)
        req = fakes.HTTPRequest.blank(url,
                                      version=mv.SUPPORT_TRANSFER_PAGINATION,
                                      use_admin_context=True)
        res_dict = self.v3_controller.index(req)

        self.assertEqual(2, len(res_dict['transfers']))
        order_ids = sorted([transfer1['id'],
                            transfer2['id']])
        expect_result = order_ids[1] if sort_dir == "desc" else order_ids[0]
        self.assertEqual(expect_result,
                         res_dict['transfers'][0]['id'])

    def test_list_transfers_detail(self):
        volume_id_1 = self._create_volume(size=5)
        volume_id_2 = self._create_volume(size=5)
        transfer1 = self._create_transfer(volume_id_1)
        transfer2 = self._create_transfer(volume_id_2)

        req = webob.Request.blank('/v3/%s/volume-transfers/detail' %
                                  fake.PROJECT_ID)
        req.method = 'GET'
        req.headers = mv.get_mv_header(self.microversion)
        req.headers['Content-Type'] = 'application/json'
        req.headers['Accept'] = 'application/json'
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_ctxt))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(HTTPStatus.OK, res.status_int)
        self.assertEqual(self.DETAIL_LEN, len(res_dict['transfers'][0]))
        self.assertEqual('test_transfer',
                         res_dict['transfers'][0]['name'])
        self.assertEqual(transfer1['id'], res_dict['transfers'][0]['id'])
        self.assertEqual(volume_id_1, res_dict['transfers'][0]['volume_id'])
        self._check_history_in_res(res_dict['transfers'][0])

        self.assertEqual(self.DETAIL_LEN, len(res_dict['transfers'][1]))
        self.assertEqual('test_transfer',
                         res_dict['transfers'][1]['name'])
        self.assertEqual(transfer2['id'], res_dict['transfers'][1]['id'])
        self.assertEqual(volume_id_2, res_dict['transfers'][1]['volume_id'])
        self._check_history_in_res(res_dict['transfers'][1])

    def test_list_transfers_detail_with_no_snapshots(self):
        volume_id_1 = self._create_volume(size=5)
        volume_id_2 = self._create_volume(size=5)
        transfer1 = self._create_transfer(volume_id_1)
        transfer2 = self._create_transfer(volume_id_2)

        req = webob.Request.blank('/v3/%s/volume-transfers/detail' %
                                  fake.PROJECT_ID)
        req.method = 'GET'
        req.headers = mv.get_mv_header(self.microversion)
        req.headers['Content-Type'] = 'application/json'
        req.headers['Accept'] = 'application/json'
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_ctxt))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(HTTPStatus.OK, res.status_int)
        self.assertEqual(self.DETAIL_LEN, len(res_dict['transfers'][0]))
        self.assertEqual('test_transfer',
                         res_dict['transfers'][0]['name'])
        self.assertEqual(transfer1['id'], res_dict['transfers'][0]['id'])
        self.assertEqual(volume_id_1, res_dict['transfers'][0]['volume_id'])
        self.assertEqual(False, res_dict['transfers'][0]['no_snapshots'])

        self.assertEqual(self.DETAIL_LEN, len(res_dict['transfers'][1]))
        self.assertEqual('test_transfer',
                         res_dict['transfers'][1]['name'])
        self.assertEqual(transfer2['id'], res_dict['transfers'][1]['id'])
        self.assertEqual(volume_id_2, res_dict['transfers'][1]['volume_id'])
        self.assertEqual(False, res_dict['transfers'][1]['no_snapshots'])

    def test_create_transfer(self):
        volume_id = self._create_volume(status='available', size=5)
        body = {"transfer": {"name": "transfer1",
                             "volume_id": volume_id}}

        req = webob.Request.blank('/v3/%s/volume-transfers' %
                                  fake.PROJECT_ID)
        req.method = 'POST'
        req.headers = mv.get_mv_header(self.microversion)
        req.headers['Content-Type'] = 'application/json'
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_ctxt))

        res_dict = jsonutils.loads(res.body)

        self.assertEqual(HTTPStatus.ACCEPTED, res.status_int)
        self.assertIn('id', res_dict['transfer'])
        self.assertIn('auth_key', res_dict['transfer'])
        self.assertIn('created_at', res_dict['transfer'])
        self.assertIn('name', res_dict['transfer'])
        self.assertIn('volume_id', res_dict['transfer'])
        self._check_history_in_res(res_dict['transfer'])

    def test_create_transfer_with_no_snapshots(self):
        volume_id = self._create_volume(status='available', size=5)
        body = {"transfer": {"name": "transfer1",
                             "volume_id": volume_id,
                             'no_snapshots': True}}

        req = webob.Request.blank('/v3/%s/volume-transfers' %
                                  fake.PROJECT_ID)
        req.method = 'POST'
        req.headers = mv.get_mv_header(self.microversion)
        req.headers['Content-Type'] = 'application/json'
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_ctxt))

        res_dict = jsonutils.loads(res.body)

        self.assertEqual(HTTPStatus.ACCEPTED, res.status_int)
        self.assertIn('id', res_dict['transfer'])
        self.assertIn('auth_key', res_dict['transfer'])
        self.assertIn('created_at', res_dict['transfer'])
        self.assertIn('name', res_dict['transfer'])
        self.assertIn('volume_id', res_dict['transfer'])
        self.assertIn('no_snapshots', res_dict['transfer'])
        self._check_history_in_res(res_dict['transfer'])

    def test_delete_transfer_awaiting_transfer(self):
        volume_id = self._create_volume()
        transfer = self.volume_transfer_api.create(context.get_admin_context(),
                                                   volume_id, 'test_transfer')
        req = webob.Request.blank('/v3/%s/volume-transfers/%s' % (
                                  fake.PROJECT_ID, transfer['id']))
        req.method = 'DELETE'
        req.headers = mv.get_mv_header(self.microversion)
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_ctxt))

        self.assertEqual(HTTPStatus.ACCEPTED, res.status_int)

        # verify transfer has been deleted
        req = webob.Request.blank('/v3/%s/volume-transfers/%s' % (
            fake.PROJECT_ID, transfer['id']))
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_ctxt))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(HTTPStatus.NOT_FOUND, res.status_int)
        self.assertEqual(HTTPStatus.NOT_FOUND,
                         res_dict['itemNotFound']['code'])
        self.assertEqual('Transfer %s could not be found.' % transfer['id'],
                         res_dict['itemNotFound']['message'])
        self.assertEqual(db.volume_get(context.get_admin_context(),
                         volume_id)['status'], 'available')

    @mock.patch.object(quota.QUOTAS, 'reserve')
    @mock.patch.object(db, 'volume_type_get', v2_fakes.fake_volume_type_get)
    def test_accept_transfer_volume_id_specified(self, type_get):
        volume_id = self._create_volume()
        transfer = self.volume_transfer_api.create(context.get_admin_context(),
                                                   volume_id, 'test_transfer')

        svc = self.start_service('volume', host='fake_host')
        body = {"accept": {"auth_key": transfer['auth_key']}}
        req = webob.Request.blank('/v3/%s/volume-transfers/%s/accept' % (
                                  fake.PROJECT_ID, transfer['id']))
        req.method = 'POST'
        req.headers = mv.get_mv_header(self.microversion)
        req.headers['Content-Type'] = 'application/json'
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_ctxt))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(HTTPStatus.ACCEPTED, res.status_int)
        self.assertEqual(transfer['id'], res_dict['transfer']['id'])
        self.assertEqual(volume_id, res_dict['transfer']['volume_id'])
        # cleanup
        svc.stop()


class VolumeTransferAPITestCase357(VolumeTransferAPITestCase):

    microversion = mv.TRANSFER_WITH_HISTORY
    DETAIL_LEN = 9
    expect_transfer_history = True
