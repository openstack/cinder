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

from cinder.api import extensions
from cinder.api.v3 import messages
from cinder import context
from cinder import exception
from cinder.message import api as message_api
from cinder.message import defined_messages
from cinder import test
from cinder.tests.unit.api import fakes
from cinder.tests.unit.api.v3 import fakes as v3_fakes


NS = '{http://docs.openstack.org/api/openstack-block-storage/3.0/content}'


class MessageApiTest(test.TestCase):
    def setUp(self):
        super(MessageApiTest, self).setUp()
        self.ext_mgr = extensions.ExtensionManager()
        self.ext_mgr.extensions = {}
        self.controller = messages.MessagesController(self.ext_mgr)

        self.maxDiff = None
        self.ctxt = context.RequestContext('admin', 'fakeproject', True)

    def _expected_message_from_controller(self, id):
        message = v3_fakes.fake_message(id)
        links = [
            {'href': 'http://localhost/v3/fakeproject/messages/%s' % id,
             'rel': 'self'},
            {'href': 'http://localhost/fakeproject/messages/%s' % id,
             'rel': 'bookmark'},
        ]
        return {
            'message': {
                'id': message.get('id'),
                'user_message': defined_messages.get_message_text(
                    message.get('event_id')),
                'request_id': message.get('request_id'),
                'event_id': message.get('event_id'),
                'created_at': message.get('created_at'),
                'message_level': message.get('message_level'),
                'guaranteed_until': message.get('expires_at'),
                'links': links,
            }
        }

    def test_show(self):
        self.mock_object(message_api.API, 'get', v3_fakes.fake_message_get)

        req = fakes.HTTPRequest.blank(
            '/v3/messages/%s' % fakes.FAKE_UUID,
            version=messages.MESSAGES_BASE_MICRO_VERSION)
        req.environ['cinder.context'] = self.ctxt

        res_dict = self.controller.show(req, fakes.FAKE_UUID)

        ex = self._expected_message_from_controller(fakes.FAKE_UUID)
        self.assertEqual(ex, res_dict)

    def test_show_not_found(self):
        self.mock_object(message_api.API, 'get',
                         side_effect=exception.MessageNotFound(
                             message_id=fakes.FAKE_UUID))

        req = fakes.HTTPRequest.blank(
            '/v3/messages/%s' % fakes.FAKE_UUID,
            version=messages.MESSAGES_BASE_MICRO_VERSION)
        req.environ['cinder.context'] = self.ctxt

        self.assertRaises(exception.MessageNotFound, self.controller.show,
                          req, fakes.FAKE_UUID)

    def test_show_pre_microversion(self):
        self.mock_object(message_api.API, 'get', v3_fakes.fake_message_get)

        req = fakes.HTTPRequest.blank('/v3/messages/%s' % fakes.FAKE_UUID,
                                      version='3.0')
        req.environ['cinder.context'] = self.ctxt

        self.assertRaises(exception.VersionNotFoundForAPIMethod,
                          self.controller.show, req, fakes.FAKE_UUID)

    def test_delete(self):
        self.mock_object(message_api.API, 'get', v3_fakes.fake_message_get)
        self.mock_object(message_api.API, 'delete')

        req = fakes.HTTPRequest.blank(
            '/v3/messages/%s' % fakes.FAKE_UUID,
            version=messages.MESSAGES_BASE_MICRO_VERSION)
        req.environ['cinder.context'] = self.ctxt

        resp = self.controller.delete(req, fakes.FAKE_UUID)

        self.assertEqual(204, resp.status_int)
        self.assertTrue(message_api.API.delete.called)

    def test_delete_not_found(self):
        self.mock_object(message_api.API, 'get',
                         side_effect=exception.MessageNotFound(
                             message_id=fakes.FAKE_UUID))

        req = fakes.HTTPRequest.blank(
            '/v3/messages/%s' % fakes.FAKE_UUID,
            version=messages.MESSAGES_BASE_MICRO_VERSION)

        self.assertRaises(exception.MessageNotFound, self.controller.delete,
                          req, fakes.FAKE_UUID)

    def test_index(self):
        self.mock_object(message_api.API, 'get_all',
                         return_value=[v3_fakes.fake_message(fakes.FAKE_UUID)])
        req = fakes.HTTPRequest.blank(
            '/v3/messages/%s' % fakes.FAKE_UUID,
            version=messages.MESSAGES_BASE_MICRO_VERSION)
        req.environ['cinder.context'] = self.ctxt

        res_dict = self.controller.index(req)

        ex = self._expected_message_from_controller(fakes.FAKE_UUID)
        expected = {
            'messages': [ex['message']]
        }
        self.assertDictEqual(expected, res_dict)
