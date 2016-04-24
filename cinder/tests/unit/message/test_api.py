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

from cinder import context
from cinder.message import api as message_api
from cinder.message import defined_messages
from cinder import test

CONF = cfg.CONF


class MessageApiTest(test.TestCase):
    def setUp(self):
        super(MessageApiTest, self).setUp()
        self.message_api = message_api.API()
        self.mock_object(self.message_api, 'db')
        self.ctxt = context.RequestContext('admin', 'fakeproject', True)
        self.ctxt.request_id = 'fakerequestid'

    def test_create(self):
        CONF.set_override('message_ttl', 300)
        timeutils.set_time_override()
        self.addCleanup(timeutils.clear_time_override)
        expected_expires_at = timeutils.utcnow() + datetime.timedelta(
            seconds=300)
        expected_message_record = {
            'project_id': 'fakeproject',
            'request_id': 'fakerequestid',
            'resource_type': 'fake_resource_type',
            'resource_uuid': None,
            'event_id': defined_messages.UNABLE_TO_ALLOCATE,
            'message_level': 'ERROR',
            'expires_at': expected_expires_at,
        }
        self.message_api.create(self.ctxt,
                                defined_messages.UNABLE_TO_ALLOCATE,
                                "fakeproject",
                                resource_type="fake_resource_type")

        self.message_api.db.message_create.assert_called_once_with(
            self.ctxt, expected_message_record)

    def test_create_swallows_exception(self):
        self.mock_object(self.message_api.db, 'create',
                         mock.Mock(side_effect=Exception()))
        self.message_api.create(self.ctxt,
                                defined_messages.UNABLE_TO_ALLOCATE,
                                "fakeproject",
                                "fake_resource")

        self.message_api.db.message_create.assert_called_once_with(
            self.ctxt, mock.ANY)

    def test_create_does_not_allow_undefined_messages(self):
        self.assertRaises(KeyError, self.message_api.create,
                          self.ctxt,
                          "FAKE_EVENT_ID",
                          "fakeproject",
                          "fake_resource")

    def test_get(self):
        self.message_api.get(self.ctxt, 'fake_id')

        self.message_api.db.message_get.assert_called_once_with(self.ctxt,
                                                                'fake_id')

    def test_get_all(self):
        self.message_api.get_all(self.ctxt)

        self.message_api.db.message_get_all.assert_called_once_with(self.ctxt)

    def test_delete(self):
        admin_context = mock.Mock()
        self.mock_object(self.ctxt, 'elevated',
                         mock.Mock(return_value=admin_context))

        self.message_api.delete(self.ctxt, 'fake_id')

        self.message_api.db.message_destroy.assert_called_once_with(
            admin_context, 'fake_id')
