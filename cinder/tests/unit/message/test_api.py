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
import datetime

import mock
from oslo_config import cfg
from oslo_utils import timeutils

from cinder.api import extensions
from cinder.api import microversions as mv
from cinder.api.openstack import api_version_request as api_version
from cinder.api.v3 import messages
from cinder import context
from cinder.message import api as message_api
from cinder.message import message_field
from cinder import test
from cinder.tests.unit.api import fakes
import cinder.tests.unit.fake_constants as fake_constants
from cinder.tests.unit import utils

CONF = cfg.CONF

version_header_name = 'OpenStack-API-Version'


class MessageApiTest(test.TestCase):
    def setUp(self):
        super(MessageApiTest, self).setUp()
        self.message_api = message_api.API()
        self.mock_object(self.message_api, 'db')
        self.ctxt = context.RequestContext('admin', 'fakeproject', True)
        self.ctxt.request_id = 'fakerequestid'
        self.ext_mgr = extensions.ExtensionManager()
        self.ext_mgr.extensions = {}
        self.controller = messages.MessagesController(self.ext_mgr)

    @mock.patch('oslo_utils.timeutils.utcnow')
    def test_create(self, mock_utcnow):
        CONF.set_override('message_ttl', 300)
        mock_utcnow.return_value = datetime.datetime.utcnow()
        expected_expires_at = timeutils.utcnow() + datetime.timedelta(
            seconds=300)
        expected_message_record = {
            'project_id': 'fakeproject',
            'request_id': 'fakerequestid',
            'resource_type': 'fake_resource_type',
            'resource_uuid': None,
            'action_id':
                message_field.Action.SCHEDULE_ALLOCATE_VOLUME[0],
            'detail_id': message_field.Detail.UNKNOWN_ERROR[0],
            'message_level': 'ERROR',
            'expires_at': expected_expires_at,
            'event_id': "VOLUME_fake_resource_type_001_001",
        }
        self.message_api.create(self.ctxt,
                                message_field.Action.SCHEDULE_ALLOCATE_VOLUME,
                                detail=message_field.Detail.UNKNOWN_ERROR,
                                resource_type="fake_resource_type")

        self.message_api.db.message_create.assert_called_once_with(
            self.ctxt, expected_message_record)
        mock_utcnow.assert_called_with()

    def test_create_swallows_exception(self):
        self.mock_object(self.message_api.db, 'create',
                         side_effect=Exception())
        self.message_api.create(self.ctxt,
                                message_field.Action.ATTACH_VOLUME,
                                "fake_resource")

        self.message_api.db.message_create.assert_called_once_with(
            self.ctxt, mock.ANY)

    def test_get(self):
        self.message_api.get(self.ctxt, 'fake_id')

        self.message_api.db.message_get.assert_called_once_with(self.ctxt,
                                                                'fake_id')

    def test_get_all(self):
        self.message_api.get_all(self.ctxt)

        self.message_api.db.message_get_all.assert_called_once_with(
            self.ctxt, filters={}, limit=None, marker=None, offset=None,
            sort_dirs=None, sort_keys=None)

    def test_delete(self):
        admin_context = mock.Mock()
        self.mock_object(self.ctxt, 'elevated', return_value=admin_context)

        self.message_api.delete(self.ctxt, 'fake_id')

        self.message_api.db.message_destroy.assert_called_once_with(
            admin_context, 'fake_id')

    def test_cleanup_expired_messages(self):
        admin_context = mock.Mock()
        self.mock_object(self.ctxt, 'elevated', return_value=admin_context)
        self.message_api.cleanup_expired_messages(self.ctxt)
        self.message_api.db.cleanup_expired_messages.assert_called_once_with(
            admin_context)

    def create_message_for_tests(self):
        """Create messages to test pagination functionality"""
        utils.create_message(
            self.ctxt, action=message_field.Action.ATTACH_VOLUME)
        utils.create_message(
            self.ctxt, action=message_field.Action.SCHEDULE_ALLOCATE_VOLUME)
        utils.create_message(
            self.ctxt,
            action=message_field.Action.COPY_VOLUME_TO_IMAGE)
        utils.create_message(
            self.ctxt,
            action=message_field.Action.COPY_VOLUME_TO_IMAGE)

    def test_get_all_messages_with_limit(self):
        self.create_message_for_tests()

        url = '/v3/messages?limit=1'
        req = fakes.HTTPRequest.blank(url)
        req.method = 'GET'
        req.content_type = 'application/json'
        req.headers = mv.get_mv_header(mv.MESSAGES_PAGINATION)
        req.api_version_request = mv.get_api_version(mv.RESOURCE_FILTER)
        req.environ['cinder.context'].is_admin = True

        res = self.controller.index(req)
        self.assertEqual(1, len(res['messages']))

        url = '/v3/messages?limit=3'
        req = fakes.HTTPRequest.blank(url)
        req.method = 'GET'
        req.content_type = 'application/json'
        req.headers = mv.get_mv_header(mv.MESSAGES_PAGINATION)
        req.api_version_request = mv.get_api_version(mv.RESOURCE_FILTER)
        req.environ['cinder.context'].is_admin = True

        res = self.controller.index(req)
        self.assertEqual(3, len(res['messages']))

    def test_get_all_messages_with_limit_wrong_version(self):
        self.create_message_for_tests()

        PRE_MESSAGES_PAGINATION = mv.get_prior_version(mv.MESSAGES_PAGINATION)

        url = '/v3/messages?limit=1'
        req = fakes.HTTPRequest.blank(url)
        req.method = 'GET'
        req.content_type = 'application/json'
        req.headers = mv.get_mv_header(PRE_MESSAGES_PAGINATION)
        req.api_version_request = mv.get_api_version(PRE_MESSAGES_PAGINATION)
        req.environ['cinder.context'].is_admin = True

        res = self.controller.index(req)
        self.assertEqual(4, len(res['messages']))

    def test_get_all_messages_with_offset(self):
        self.create_message_for_tests()

        url = '/v3/messages?offset=1'
        req = fakes.HTTPRequest.blank(url)
        req.method = 'GET'
        req.content_type = 'application/json'
        req.headers = mv.get_mv_header(mv.MESSAGES_PAGINATION)
        req.api_version_request = mv.get_api_version(mv.MESSAGES_PAGINATION)
        req.environ['cinder.context'].is_admin = True

        res = self.controller.index(req)
        self.assertEqual(3, len(res['messages']))

    def test_get_all_messages_with_limit_and_offset(self):
        self.create_message_for_tests()

        url = '/v3/messages?limit=2&offset=1'
        req = fakes.HTTPRequest.blank(url)
        req.method = 'GET'
        req.content_type = 'application/json'
        req.headers = mv.get_mv_header(mv.MESSAGES_PAGINATION)
        req.api_version_request = mv.get_api_version(mv.MESSAGES_PAGINATION)
        req.environ['cinder.context'].is_admin = True

        res = self.controller.index(req)
        self.assertEqual(2, len(res['messages']))

    def test_get_all_messages_with_filter(self):
        self.create_message_for_tests()

        url = '/v3/messages?action_id=%s' % (
            message_field.Action.ATTACH_VOLUME[0])
        req = fakes.HTTPRequest.blank(url)
        req.method = 'GET'
        req.content_type = 'application/json'
        req.headers = mv.get_mv_header(mv.MESSAGES_PAGINATION)
        req.api_version_request = mv.get_api_version(mv.MESSAGES_PAGINATION)
        req.environ['cinder.context'].is_admin = True

        res = self.controller.index(req)
        self.assertEqual(1, len(res['messages']))

    def test_get_all_messages_with_sort(self):
        self.create_message_for_tests()

        url = '/v3/messages?sort=event_id:asc'
        req = fakes.HTTPRequest.blank(url)
        req.method = 'GET'
        req.content_type = 'application/json'
        req.headers = mv.get_mv_header(mv.MESSAGES_PAGINATION)
        req.api_version_request = mv.get_api_version(mv.MESSAGES_PAGINATION)
        req.environ['cinder.context'].is_admin = True

        res = self.controller.index(req)

        expect_result = [
            "VOLUME_VOLUME_001_002",
            "VOLUME_VOLUME_002_002",
            "VOLUME_VOLUME_003_002",
            "VOLUME_VOLUME_003_002",
        ]
        expect_result.sort()

        self.assertEqual(4, len(res['messages']))
        self.assertEqual(expect_result[0],
                         res['messages'][0]['event_id'])
        self.assertEqual(expect_result[1],
                         res['messages'][1]['event_id'])
        self.assertEqual(expect_result[2],
                         res['messages'][2]['event_id'])
        self.assertEqual(expect_result[3],
                         res['messages'][3]['event_id'])

    def test_get_all_messages_paging(self):
        self.create_message_for_tests()

        # first request of this test
        url = '/v3/fake/messages?limit=2'
        req = fakes.HTTPRequest.blank(url)
        req.method = 'GET'
        req.content_type = 'application/json'
        req.headers = mv.get_mv_header(mv.MESSAGES_PAGINATION)
        req.api_version_request = mv.get_api_version(mv.RESOURCE_FILTER)
        req.environ['cinder.context'].is_admin = True

        res = self.controller.index(req)
        self.assertEqual(2, len(res['messages']))

        next_link = ('http://localhost/v3/%s/messages?limit='
                     '2&marker=%s') % (fake_constants.PROJECT_ID,
                                       res['messages'][1]['id'])
        self.assertEqual(next_link,
                         res['messages_links'][0]['href'])

        # Second request in this test
        # Test for second page using marker (res['messages][0]['id'])
        # values fetched in first request with limit 2 in this test
        url = '/v3/fake/messages?limit=1&marker=%s' % (
            res['messages'][0]['id'])
        req = fakes.HTTPRequest.blank(url)
        req.method = 'GET'
        req.content_type = 'application/json'
        req.headers = mv.get_mv_header(mv.MESSAGES_PAGINATION)
        req.api_version_request = api_version.max_api_version()
        req.environ['cinder.context'].is_admin = True

        result = self.controller.index(req)
        self.assertEqual(1, len(result['messages']))

        # checking second message of first request in this test with first
        # message of second request. (to test paging mechanism)
        self.assertEqual(res['messages'][1], result['messages'][0])
