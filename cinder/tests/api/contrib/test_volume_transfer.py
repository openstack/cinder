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

import json
from xml.dom import minidom

from oslo_log import log as logging
import webob

from cinder.api.contrib import volume_transfer
from cinder import context
from cinder import db
from cinder import exception
from cinder import test
from cinder.tests.api import fakes
from cinder import transfer
import cinder.volume


LOG = logging.getLogger(__name__)


class VolumeTransferAPITestCase(test.TestCase):
    """Test Case for transfers API."""

    def setUp(self):
        super(VolumeTransferAPITestCase, self).setUp()
        self.volume_transfer_api = transfer.API()
        self.controller = volume_transfer.VolumeTransferController()

    def _create_transfer(self, volume_id=1,
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
                       project_id='fake'):
        """Create a volume object."""
        vol = {}
        vol['host'] = 'fake_host'
        vol['size'] = size
        vol['user_id'] = 'fake'
        vol['project_id'] = project_id
        vol['status'] = status
        vol['display_name'] = display_name
        vol['display_description'] = display_description
        vol['attach_status'] = status
        return db.volume_create(context.get_admin_context(), vol)['id']

    def test_show_transfer(self):
        volume_id = self._create_volume(size=5)
        transfer = self._create_transfer(volume_id)
        LOG.debug('Created transfer with id %s' % transfer)
        req = webob.Request.blank('/v2/fake/os-volume-transfer/%s' %
                                  transfer['id'])
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)
        self.assertEqual(res.status_int, 200)
        self.assertEqual(res_dict['transfer']['name'], 'test_transfer')
        self.assertEqual(res_dict['transfer']['id'], transfer['id'])
        self.assertEqual(res_dict['transfer']['volume_id'], volume_id)

        db.transfer_destroy(context.get_admin_context(), transfer['id'])
        db.volume_destroy(context.get_admin_context(), volume_id)

    def test_show_transfer_xml_content_type(self):
        volume_id = self._create_volume(size=5)
        transfer = self._create_transfer(volume_id)
        req = webob.Request.blank('/v2/fake/os-volume-transfer/%s' %
                                  transfer['id'])
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/xml'
        req.headers['Accept'] = 'application/xml'
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        dom = minidom.parseString(res.body)
        transfer_xml = dom.getElementsByTagName('transfer')
        name = transfer_xml.item(0).getAttribute('name')
        self.assertEqual(name.strip(), "test_transfer")

        db.transfer_destroy(context.get_admin_context(), transfer['id'])
        db.volume_destroy(context.get_admin_context(), volume_id)

    def test_show_transfer_with_transfer_NotFound(self):
        req = webob.Request.blank('/v2/fake/os-volume-transfer/1234')
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(res.status_int, 404)
        self.assertEqual(res_dict['itemNotFound']['code'], 404)
        self.assertEqual(res_dict['itemNotFound']['message'],
                         'Transfer 1234 could not be found.')

    def test_list_transfers_json(self):
        volume_id_1 = self._create_volume(size=5)
        volume_id_2 = self._create_volume(size=5)
        transfer1 = self._create_transfer(volume_id_1)
        transfer2 = self._create_transfer(volume_id_2)

        req = webob.Request.blank('/v2/fake/os-volume-transfer')
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(res.status_int, 200)
        self.assertEqual(len(res_dict['transfers'][0]), 4)
        self.assertEqual(res_dict['transfers'][0]['id'], transfer1['id'])
        self.assertEqual(res_dict['transfers'][0]['name'], 'test_transfer')
        self.assertEqual(len(res_dict['transfers'][1]), 4)
        self.assertEqual(res_dict['transfers'][1]['name'], 'test_transfer')

        db.transfer_destroy(context.get_admin_context(), transfer2['id'])
        db.transfer_destroy(context.get_admin_context(), transfer1['id'])
        db.volume_destroy(context.get_admin_context(), volume_id_1)
        db.volume_destroy(context.get_admin_context(), volume_id_2)

    def test_list_transfers_xml(self):
        volume_id_1 = self._create_volume(size=5)
        volume_id_2 = self._create_volume(size=5)
        transfer1 = self._create_transfer(volume_id_1)
        transfer2 = self._create_transfer(volume_id_2)

        req = webob.Request.blank('/v2/fake/os-volume-transfer')
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/xml'
        req.headers['Accept'] = 'application/xml'
        res = req.get_response(fakes.wsgi_app())

        self.assertEqual(res.status_int, 200)
        dom = minidom.parseString(res.body)
        transfer_list = dom.getElementsByTagName('transfer')
        self.assertEqual(transfer_list.item(0).attributes.length, 3)
        self.assertEqual(transfer_list.item(0).getAttribute('id'),
                         transfer1['id'])
        self.assertEqual(transfer_list.item(1).attributes.length, 3)
        self.assertEqual(transfer_list.item(1).getAttribute('id'),
                         transfer2['id'])

        db.transfer_destroy(context.get_admin_context(), transfer2['id'])
        db.transfer_destroy(context.get_admin_context(), transfer1['id'])
        db.volume_destroy(context.get_admin_context(), volume_id_2)
        db.volume_destroy(context.get_admin_context(), volume_id_1)

    def test_list_transfers_detail_json(self):
        volume_id_1 = self._create_volume(size=5)
        volume_id_2 = self._create_volume(size=5)
        transfer1 = self._create_transfer(volume_id_1)
        transfer2 = self._create_transfer(volume_id_2)

        req = webob.Request.blank('/v2/fake/os-volume-transfer/detail')
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/json'
        req.headers['Accept'] = 'application/json'
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(res.status_int, 200)
        self.assertEqual(len(res_dict['transfers'][0]), 5)
        self.assertEqual(res_dict['transfers'][0]['name'],
                         'test_transfer')
        self.assertEqual(res_dict['transfers'][0]['id'], transfer1['id'])
        self.assertEqual(res_dict['transfers'][0]['volume_id'], volume_id_1)

        self.assertEqual(len(res_dict['transfers'][1]), 5)
        self.assertEqual(res_dict['transfers'][1]['name'],
                         'test_transfer')
        self.assertEqual(res_dict['transfers'][1]['id'], transfer2['id'])
        self.assertEqual(res_dict['transfers'][1]['volume_id'], volume_id_2)

        db.transfer_destroy(context.get_admin_context(), transfer2['id'])
        db.transfer_destroy(context.get_admin_context(), transfer1['id'])
        db.volume_destroy(context.get_admin_context(), volume_id_2)
        db.volume_destroy(context.get_admin_context(), volume_id_1)

    def test_list_transfers_detail_xml(self):
        volume_id_1 = self._create_volume(size=5)
        volume_id_2 = self._create_volume(size=5)
        transfer1 = self._create_transfer(volume_id_1)
        transfer2 = self._create_transfer(volume_id_2)

        req = webob.Request.blank('/v2/fake/os-volume-transfer/detail')
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/xml'
        req.headers['Accept'] = 'application/xml'
        res = req.get_response(fakes.wsgi_app())

        self.assertEqual(res.status_int, 200)
        dom = minidom.parseString(res.body)
        transfer_detail = dom.getElementsByTagName('transfer')

        self.assertEqual(transfer_detail.item(0).attributes.length, 4)
        self.assertEqual(
            transfer_detail.item(0).getAttribute('name'), 'test_transfer')
        self.assertEqual(
            transfer_detail.item(0).getAttribute('id'), transfer1['id'])
        self.assertEqual(transfer_detail.item(0).getAttribute('volume_id'),
                         volume_id_1)

        self.assertEqual(transfer_detail.item(1).attributes.length, 4)
        self.assertEqual(
            transfer_detail.item(1).getAttribute('name'), 'test_transfer')
        self.assertEqual(
            transfer_detail.item(1).getAttribute('id'), transfer2['id'])
        self.assertEqual(transfer_detail.item(1).getAttribute('volume_id'),
                         volume_id_2)

        db.transfer_destroy(context.get_admin_context(), transfer2['id'])
        db.transfer_destroy(context.get_admin_context(), transfer1['id'])
        db.volume_destroy(context.get_admin_context(), volume_id_2)
        db.volume_destroy(context.get_admin_context(), volume_id_1)

    def test_list_transfers_with_all_tenants(self):
        volume_id_1 = self._create_volume(size=5)
        volume_id_2 = self._create_volume(size=5, project_id='fake1')
        transfer1 = self._create_transfer(volume_id_1)
        transfer2 = self._create_transfer(volume_id_2)

        req = fakes.HTTPRequest.blank('/v2/fake/os-volume-transfer?'
                                      'all_tenants=1',
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

    def test_create_transfer_json(self):
        volume_id = self._create_volume(status='available', size=5)
        body = {"transfer": {"display_name": "transfer1",
                             "volume_id": volume_id}}

        req = webob.Request.blank('/v2/fake/os-volume-transfer')
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())

        res_dict = json.loads(res.body)
        LOG.info(res_dict)

        self.assertEqual(res.status_int, 202)
        self.assertIn('id', res_dict['transfer'])
        self.assertIn('auth_key', res_dict['transfer'])
        self.assertIn('created_at', res_dict['transfer'])
        self.assertIn('name', res_dict['transfer'])
        self.assertIn('volume_id', res_dict['transfer'])

        db.volume_destroy(context.get_admin_context(), volume_id)

    def test_create_transfer_xml(self):
        volume_size = 2
        volume_id = self._create_volume(status='available', size=volume_size)

        req = webob.Request.blank('/v2/fake/os-volume-transfer')
        req.body = ('<transfer name="transfer-001" '
                    'volume_id="%s"/>' % volume_id)
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/xml'
        req.headers['Accept'] = 'application/xml'
        res = req.get_response(fakes.wsgi_app())

        self.assertEqual(res.status_int, 202)
        dom = minidom.parseString(res.body)
        transfer = dom.getElementsByTagName('transfer')
        self.assertTrue(transfer.item(0).hasAttribute('id'))
        self.assertTrue(transfer.item(0).hasAttribute('auth_key'))
        self.assertTrue(transfer.item(0).hasAttribute('created_at'))
        self.assertEqual(transfer.item(0).getAttribute('name'), 'transfer-001')
        self.assertTrue(transfer.item(0).hasAttribute('volume_id'))
        db.volume_destroy(context.get_admin_context(), volume_id)

    def test_create_transfer_with_no_body(self):
        req = webob.Request.blank('/v2/fake/os-volume-transfer')
        req.body = json.dumps(None)
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.headers['Accept'] = 'application/json'
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(res.status_int, 400)
        self.assertEqual(res_dict['badRequest']['code'], 400)
        self.assertEqual(res_dict['badRequest']['message'],
                         'The server could not comply with the request since'
                         ' it is either malformed or otherwise incorrect.')

    def test_create_transfer_with_body_KeyError(self):
        body = {"transfer": {"display_name": "transfer1"}}
        req = webob.Request.blank('/v2/fake/os-volume-transfer')
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(res.status_int, 400)
        self.assertEqual(res_dict['badRequest']['code'], 400)
        self.assertEqual(res_dict['badRequest']['message'],
                         'Incorrect request body format')

    def test_create_transfer_with_VolumeNotFound(self):
        body = {"transfer": {"display_name": "transfer1",
                             "volume_id": 1234}}

        req = webob.Request.blank('/v2/fake/os-volume-transfer')
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(res.status_int, 404)
        self.assertEqual(res_dict['itemNotFound']['code'], 404)
        self.assertEqual(res_dict['itemNotFound']['message'],
                         'Volume 1234 could not be found.')

    def test_create_transfer_with_InvalidVolume(self):
        volume_id = self._create_volume(status='attached')
        body = {"transfer": {"display_name": "transfer1",
                             "volume_id": volume_id}}
        req = webob.Request.blank('/v2/fake/os-volume-transfer')
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(res.status_int, 400)
        self.assertEqual(res_dict['badRequest']['code'], 400)
        self.assertEqual(res_dict['badRequest']['message'],
                         'Invalid volume: status must be available')

        db.volume_destroy(context.get_admin_context(), volume_id)

    def test_delete_transfer_awaiting_transfer(self):
        volume_id = self._create_volume()
        transfer = self._create_transfer(volume_id)
        req = webob.Request.blank('/v2/fake/os-volume-transfer/%s' %
                                  transfer['id'])
        req.method = 'DELETE'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app())

        self.assertEqual(res.status_int, 202)

        # verify transfer has been deleted
        req = webob.Request.blank('/v2/fake/os-volume-transfer/%s' %
                                  transfer['id'])
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(res.status_int, 404)
        self.assertEqual(res_dict['itemNotFound']['code'], 404)
        self.assertEqual(res_dict['itemNotFound']['message'],
                         'Transfer %s could not be found.' % transfer['id'])
        self.assertEqual(db.volume_get(context.get_admin_context(),
                         volume_id)['status'], 'available')

        db.volume_destroy(context.get_admin_context(), volume_id)

    def test_delete_transfer_with_transfer_NotFound(self):
        req = webob.Request.blank('/v2/fake/os-volume-transfer/9999')
        req.method = 'DELETE'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(res.status_int, 404)
        self.assertEqual(res_dict['itemNotFound']['code'], 404)
        self.assertEqual(res_dict['itemNotFound']['message'],
                         'Transfer 9999 could not be found.')

    def test_accept_transfer_volume_id_specified_json(self):
        volume_id = self._create_volume()
        transfer = self._create_transfer(volume_id)

        svc = self.start_service('volume', host='fake_host')
        body = {"accept": {"id": transfer['id'],
                           "auth_key": transfer['auth_key']}}
        req = webob.Request.blank('/v2/fake/os-volume-transfer/%s/accept' %
                                  transfer['id'])
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(res.status_int, 202)
        self.assertEqual(res_dict['transfer']['id'], transfer['id'])
        self.assertEqual(res_dict['transfer']['volume_id'], volume_id)
        # cleanup
        svc.stop()

    def test_accept_transfer_volume_id_specified_xml(self):
        volume_id = self._create_volume(size=5)
        transfer = self._create_transfer(volume_id)
        svc = self.start_service('volume', host='fake_host')

        req = webob.Request.blank('/v2/fake/os-volume-transfer/%s/accept' %
                                  transfer['id'])
        req.body = '<accept auth_key="%s"/>' % transfer['auth_key']
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/xml'
        req.headers['Accept'] = 'application/xml'
        res = req.get_response(fakes.wsgi_app())

        self.assertEqual(res.status_int, 202)
        dom = minidom.parseString(res.body)
        accept = dom.getElementsByTagName('transfer')
        self.assertEqual(accept.item(0).getAttribute('id'),
                         transfer['id'])
        self.assertEqual(accept.item(0).getAttribute('volume_id'), volume_id)

        db.volume_destroy(context.get_admin_context(), volume_id)
        # cleanup
        svc.stop()

    def test_accept_transfer_with_no_body(self):
        volume_id = self._create_volume(size=5)
        transfer = self._create_transfer(volume_id)

        req = webob.Request.blank('/v2/fake/os-volume-transfer/%s/accept' %
                                  transfer['id'])
        req.body = json.dumps(None)
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.headers['Accept'] = 'application/json'
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(res.status_int, 400)
        self.assertEqual(res_dict['badRequest']['code'], 400)
        self.assertEqual(res_dict['badRequest']['message'],
                         'The server could not comply with the request since'
                         ' it is either malformed or otherwise incorrect.')

        db.volume_destroy(context.get_admin_context(), volume_id)

    def test_accept_transfer_with_body_KeyError(self):
        volume_id = self._create_volume(size=5)
        transfer = self._create_transfer(volume_id)

        req = webob.Request.blank('/v2/fake/os-volume-transfer/%s/accept' %
                                  transfer['id'])
        body = {"": {}}
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.headers['Accept'] = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())

        res_dict = json.loads(res.body)

        self.assertEqual(res.status_int, 400)
        self.assertEqual(res_dict['badRequest']['code'], 400)
        self.assertEqual(res_dict['badRequest']['message'],
                         'The server could not comply with the request since'
                         ' it is either malformed or otherwise incorrect.')

    def test_accept_transfer_invalid_id_auth_key(self):
        volume_id = self._create_volume()
        transfer = self._create_transfer(volume_id)

        body = {"accept": {"id": transfer['id'],
                           "auth_key": 1}}
        req = webob.Request.blank('/v2/fake/os-volume-transfer/%s/accept' %
                                  transfer['id'])
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(res.status_int, 400)
        self.assertEqual(res_dict['badRequest']['code'], 400)
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
        req = webob.Request.blank('/v2/fake/os-volume-transfer/1/accept')
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(res.status_int, 404)
        self.assertEqual(res_dict['itemNotFound']['code'], 404)
        self.assertEqual(res_dict['itemNotFound']['message'],
                         'TransferNotFound: Transfer 1 could not be found.')

        db.transfer_destroy(context.get_admin_context(), transfer['id'])
        db.volume_destroy(context.get_admin_context(), volume_id)

    def test_accept_transfer_with_VolumeSizeExceedsAvailableQuota(self):

        def fake_transfer_api_accept_throwing_VolumeSizeExceedsAvailableQuota(
                cls, context, transfer, volume_id):
            raise exception.VolumeSizeExceedsAvailableQuota(requested='2',
                                                            consumed='2',
                                                            quota='3')

        self.stubs.Set(
            cinder.transfer.API,
            'accept',
            fake_transfer_api_accept_throwing_VolumeSizeExceedsAvailableQuota)

        volume_id = self._create_volume()
        transfer = self._create_transfer(volume_id)

        body = {"accept": {"id": transfer['id'],
                           "auth_key": transfer['auth_key']}}
        req = webob.Request.blank('/v2/fake/os-volume-transfer/%s/accept' %
                                  transfer['id'])

        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(res.status_int, 413)
        self.assertEqual(res_dict['overLimit']['code'], 413)
        self.assertEqual(res_dict['overLimit']['message'],
                         'Requested volume or snapshot exceeds allowed '
                         'gigabytes quota. Requested 2G, quota is 3G and '
                         '2G has been consumed.')

    def test_accept_transfer_with_VolumeLimitExceeded(self):

        def fake_transfer_api_accept_throwing_VolumeLimitExceeded(cls,
                                                                  context,
                                                                  transfer,
                                                                  volume_id):
            raise exception.VolumeLimitExceeded(allowed=1)

        self.stubs.Set(cinder.transfer.API, 'accept',
                       fake_transfer_api_accept_throwing_VolumeLimitExceeded)

        volume_id = self._create_volume()
        transfer = self._create_transfer(volume_id)

        body = {"accept": {"id": transfer['id'],
                           "auth_key": transfer['auth_key']}}
        req = webob.Request.blank('/v2/fake/os-volume-transfer/%s/accept' %
                                  transfer['id'])

        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(res.status_int, 413)
        self.assertEqual(res_dict['overLimit']['code'], 413)
        self.assertEqual(res_dict['overLimit']['message'],
                         'VolumeLimitExceeded: Maximum number of volumes '
                         'allowed (1) exceeded')
