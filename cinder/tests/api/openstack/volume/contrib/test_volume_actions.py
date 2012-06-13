#   Copyright 2012 OpenStack LLC.
#
#   Licensed under the Apache License, Version 2.0 (the "License"); you may
#   not use this file except in compliance with the License. You may obtain
#   a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#   WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#   License for the specific language governing permissions and limitations
#   under the License.

import datetime
import json

import webob

from cinder.api.openstack import volume as volume_api
from cinder import volume
from cinder import context
from cinder import exception
from cinder import flags
from cinder import test
from cinder.tests.api.openstack import fakes
from cinder import utils


FLAGS = flags.FLAGS


def fake_volume_api(*args, **kwargs):
    return True


def fake_volume_get(*args, **kwargs):
    return {'id': 'fake', 'host': 'fake'}


class VolumeActionsTest(test.TestCase):

    _actions = ('os-detach', 'os-reserve', 'os-unreserve')

    _methods = ('attach', 'detach', 'reserve_volume', 'unreserve_volume')

    def setUp(self):
        super(VolumeActionsTest, self).setUp()
        self.stubs.Set(volume.API, 'get', fake_volume_api)
        self.UUID = utils.gen_uuid()
        for _method in self._methods:
            self.stubs.Set(volume.API, _method, fake_volume_api)

        self.stubs.Set(volume.API, 'get', fake_volume_get)

    def test_simple_api_actions(self):
        app = fakes.wsgi_app()
        for _action in self._actions:
            req = webob.Request.blank('/v1/fake/volumes/%s/action' %
                    self.UUID)
            req.method = 'POST'
            req.body = json.dumps({_action: None})
            req.content_type = 'application/json'
            res = req.get_response(app)
            self.assertEqual(res.status_int, 202)

    def test_initialize_connection(self):
        def fake_initialize_connection(*args, **kwargs):
            return {}
        self.stubs.Set(volume.API, 'initialize_connection',
                       fake_initialize_connection)

        body = {'os-initialize_connection': {'connector': 'fake'}}
        req = webob.Request.blank('/v1/fake/volumes/1/action')
        req.method = "POST"
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"

        res = req.get_response(fakes.wsgi_app())
        output = json.loads(res.body)
        self.assertEqual(res.status_int, 200)

    def test_terminate_connection(self):
        def fake_terminate_connection(*args, **kwargs):
            return {}
        self.stubs.Set(volume.API, 'terminate_connection',
                       fake_terminate_connection)

        body = {'os-terminate_connection': {'connector': 'fake'}}
        req = webob.Request.blank('/v1/fake/volumes/1/action')
        req.method = "POST"
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"

        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 202)

    def test_attach(self):
        body = {'os-attach': {'instance_uuid': 'fake',
                              'mountpoint': '/dev/vdc'}}
        req = webob.Request.blank('/v1/fake/volumes/1/action')
        req.method = "POST"
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"

        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 202)
