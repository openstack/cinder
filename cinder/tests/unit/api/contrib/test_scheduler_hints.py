# Copyright 2013 OpenStack Foundation
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

import datetime

import ddt
from oslo_serialization import jsonutils
from six.moves import http_client

import cinder
from cinder.api.openstack import wsgi
from cinder import context
from cinder import test
from cinder.tests.unit.api import fakes
from cinder.tests.unit.api.v2 import fakes as v2_fakes
from cinder.tests.unit import fake_constants as fake


UUID = fakes.FAKE_UUID


@ddt.ddt
class SchedulerHintsTestCase(test.TestCase):

    def setUp(self):
        super(SchedulerHintsTestCase, self).setUp()
        self.fake_instance = v2_fakes.create_fake_volume(fake.VOLUME_ID,
                                                         uuid=UUID)
        self.fake_instance['created_at'] =\
            datetime.datetime(2013, 1, 1, 1, 1, 1)
        self.fake_instance['launched_at'] =\
            datetime.datetime(2013, 1, 1, 1, 1, 1)
        self.flags(
            osapi_volume_extension=[
                'cinder.api.contrib.select_extensions'],
            osapi_volume_ext_list=['Scheduler_hints'])
        self.user_ctxt = context.RequestContext(
            fake.USER_ID, fake.PROJECT_ID, auth_token=True)
        self.app = fakes.wsgi_app(fake_auth_context=self.user_ctxt)

    def test_create_server_without_hints(self):

        @wsgi.response(http_client.ACCEPTED)
        def fake_create(*args, **kwargs):
            self.assertNotIn('scheduler_hints', kwargs['body'])
            return self.fake_instance

        self.mock_object(cinder.api.v2.volumes.VolumeController, 'create',
                         fake_create)

        req = fakes.HTTPRequest.blank('/v2/%s/volumes' % fake.PROJECT_ID)
        req.method = 'POST'
        req.content_type = 'application/json'
        body = {'id': UUID,
                'volume_type_id': fake.VOLUME_TYPE_ID,
                'volume_id': fake.VOLUME_ID, }
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(self.app)
        self.assertEqual(http_client.ACCEPTED, res.status_int)

    def test_create_server_with_hints(self):

        @wsgi.response(http_client.ACCEPTED)
        def fake_create(*args, **kwargs):
            self.assertIn('scheduler_hints', kwargs['body'])
            self.assertEqual({"a": "b"}, kwargs['body']['scheduler_hints'])
            return self.fake_instance

        self.mock_object(cinder.api.v2.volumes.VolumeController, 'create',
                         fake_create)

        req = fakes.HTTPRequest.blank('/v2/%s/volumes' % fake.PROJECT_ID)
        req.method = 'POST'
        req.content_type = 'application/json'
        body = {'id': UUID,
                'volume_type_id': fake.VOLUME_TYPE_ID,
                'volume_id': fake.VOLUME_ID,
                'scheduler_hints': {'a': 'b'}, }

        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(self.app)
        self.assertEqual(http_client.ACCEPTED, res.status_int)

    def test_create_server_bad_hints(self):
        req = fakes.HTTPRequest.blank('/v2/%s/volumes' % fake.PROJECT_ID)
        req.method = 'POST'
        req.content_type = 'application/json'
        body = {'volume': {
            'id': UUID,
            'volume_type_id': fake.VOLUME_TYPE_ID,
            'volume_id': fake.VOLUME_ID,
            'scheduler_hints': 'a', }}

        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(self.app)
        self.assertEqual(http_client.BAD_REQUEST, res.status_int)

    @ddt.data({'local_to_instance': UUID},
              {'local_to_instance': None},
              {'different_host': [fake.UUID1, fake.UUID2]},
              {'same_host': UUID},
              {'same_host': [fake.UUID1, fake.UUID2]},
              {'fake_key': 'fake_value'},
              {'query': 'query_testing'},
              {'query': {}},
              None)
    def test_scheduler_hints_with_valid_body(self, value):
        req = fakes.HTTPRequest.blank('/v2/%s/volumes' % fake.PROJECT_ID)
        req.method = 'POST'
        req.content_type = 'application/json'
        body = {'volume': {'size': 1},
                'OS-SCH-HNT:scheduler_hints': value}

        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(self.app)
        self.assertEqual(http_client.ACCEPTED, res.status_int)

    @ddt.data({'local_to_instance': 'local_to_instance'},
              {'different_host': 'different_host'},
              {'different_host': ['different_host']},
              {'different_host': [UUID, UUID]},
              {'same_host': 'same_host'},
              {'same_host': ['same_host']},
              {'same_host': [UUID, UUID]},
              {'query': None},
              {'scheduler_hints'})
    def test_scheduler_hints_with_invalid_body(self, value):
        req = fakes.HTTPRequest.blank('/v2/%s/volumes' % fake.PROJECT_ID)
        req.method = 'POST'
        req.content_type = 'application/json'
        body = {'volume': {'size': 1},
                'OS-SCH-HNT:scheduler_hints': value}

        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(self.app)

        self.assertEqual(http_client.BAD_REQUEST, res.status_int)
