# vim: tabstop=4 shiftwidth=4 softtabstop=4

#   Copyright 2012 OpenStack Foundation
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
import uuid
import webob

from cinder.api.contrib import volume_actions
from cinder import exception
from cinder.openstack.common import jsonutils
from cinder.openstack.common.rpc import common as rpc_common
from cinder import test
from cinder.tests.api import fakes
from cinder.tests.api.v2 import stubs
from cinder import volume
from cinder.volume import api as volume_api


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
        self.UUID = uuid.uuid4()
        for _method in self._methods:
            self.stubs.Set(volume.API, _method, fake_volume_api)

        self.stubs.Set(volume.API, 'get', fake_volume_get)

    def test_simple_api_actions(self):
        app = fakes.wsgi_app()
        for _action in self._actions:
            req = webob.Request.blank('/v2/fake/volumes/%s/action' %
                                      self.UUID)
            req.method = 'POST'
            req.body = jsonutils.dumps({_action: None})
            req.content_type = 'application/json'
            res = req.get_response(app)
            self.assertEqual(res.status_int, 202)

    def test_initialize_connection(self):
        def fake_initialize_connection(*args, **kwargs):
            return {}
        self.stubs.Set(volume.API, 'initialize_connection',
                       fake_initialize_connection)

        body = {'os-initialize_connection': {'connector': 'fake'}}
        req = webob.Request.blank('/v2/fake/volumes/1/action')
        req.method = "POST"
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"

        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)

    def test_terminate_connection(self):
        def fake_terminate_connection(*args, **kwargs):
            return {}
        self.stubs.Set(volume.API, 'terminate_connection',
                       fake_terminate_connection)

        body = {'os-terminate_connection': {'connector': 'fake'}}
        req = webob.Request.blank('/v2/fake/volumes/1/action')
        req.method = "POST"
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"

        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 202)

    def test_attach_to_instance(self):
        body = {'os-attach': {'instance_uuid': 'fake',
                              'mountpoint': '/dev/vdc',
                              'mode': 'rw'}}
        req = webob.Request.blank('/v2/fake/volumes/1/action')
        req.method = "POST"
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"

        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 202)

    def test_attach_to_host(self):
        # using 'read-write' mode attach volume by default
        body = {'os-attach': {'host_name': 'fake_host',
                              'mountpoint': '/dev/vdc'}}
        req = webob.Request.blank('/v2/fake/volumes/1/action')
        req.method = "POST"
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"

        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 202)

    def test_attach_with_invalid_arguments(self):
        # Invalid request to attach volume an invalid target
        body = {'os-attach': {'mountpoint': '/dev/vdc'}}
        req = webob.Request.blank('/v2/fake/volumes/1/action')
        req.method = "POST"
        req.headers["content-type"] = "application/json"
        req.body = jsonutils.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 400)

        # Invalid request to attach volume to an instance and a host
        body = {'os-attach': {'instance_uuid': 'fake',
                              'host_name': 'fake_host',
                              'mountpoint': '/dev/vdc'}}
        req = webob.Request.blank('/v2/fake/volumes/1/action')
        req.method = "POST"
        req.headers["content-type"] = "application/json"
        req.body = jsonutils.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 400)

        # Invalid request to attach volume with an invalid mode
        body = {'os-attach': {'instance_uuid': 'fake',
                              'mountpoint': '/dev/vdc',
                              'mode': 'rr'}}
        req = webob.Request.blank('/v2/fake/volumes/1/action')
        req.method = "POST"
        req.headers["content-type"] = "application/json"
        req.body = jsonutils.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 400)
        body = {'os-attach': {'host_name': 'fake_host',
                              'mountpoint': '/dev/vdc',
                              'mode': 'ww'}}
        req = webob.Request.blank('/v2/fake/volumes/1/action')
        req.method = "POST"
        req.headers["content-type"] = "application/json"
        req.body = jsonutils.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 400)

    def test_begin_detaching(self):
        def fake_begin_detaching(*args, **kwargs):
            return {}
        self.stubs.Set(volume.API, 'begin_detaching',
                       fake_begin_detaching)

        body = {'os-begin_detaching': {'fake': 'fake'}}
        req = webob.Request.blank('/v2/fake/volumes/1/action')
        req.method = "POST"
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"

        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 202)

    def test_roll_detaching(self):
        def fake_roll_detaching(*args, **kwargs):
            return {}
        self.stubs.Set(volume.API, 'roll_detaching',
                       fake_roll_detaching)

        body = {'os-roll_detaching': {'fake': 'fake'}}
        req = webob.Request.blank('/v2/fake/volumes/1/action')
        req.method = "POST"
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"

        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 202)

    def test_extend_volume(self):
        def fake_extend_volume(*args, **kwargs):
            return {}
        self.stubs.Set(volume.API, 'extend',
                       fake_extend_volume)

        body = {'os-extend': {'new_size': 5}}
        req = webob.Request.blank('/v2/fake/volumes/1/action')
        req.method = "POST"
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"

        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 202)

    def test_update_readonly_flag(self):
        def fake_update_readonly_flag(*args, **kwargs):
            return {}
        self.stubs.Set(volume.API, 'update_readonly_flag',
                       fake_update_readonly_flag)

        body = {'os-update_readonly_flag': {'readonly': True}}
        req = webob.Request.blank('/v2/fake/volumes/1/action')
        req.method = "POST"
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"

        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 202)


def stub_volume_get(self, context, volume_id):
    volume = stubs.stub_volume(volume_id)
    if volume_id == 5:
        volume['status'] = 'in-use'
    else:
        volume['status'] = 'available'
    return volume


def stub_upload_volume_to_image_service(self, context, volume, metadata,
                                        force):
    ret = {"id": volume['id'],
           "updated_at": datetime.datetime(1, 1, 1, 1, 1, 1),
           "status": 'uploading',
           "display_description": volume['display_description'],
           "size": volume['size'],
           "volume_type": volume['volume_type'],
           "image_id": 1,
           "container_format": 'bare',
           "disk_format": 'raw',
           "image_name": 'image_name'}
    return ret


class VolumeImageActionsTest(test.TestCase):
    def setUp(self):
        super(VolumeImageActionsTest, self).setUp()
        self.controller = volume_actions.VolumeActionsController()

        self.stubs.Set(volume_api.API, 'get', stub_volume_get)

    def test_copy_volume_to_image(self):
        self.stubs.Set(volume_api.API,
                       "copy_volume_to_image",
                       stub_upload_volume_to_image_service)

        id = 1
        vol = {"container_format": 'bare',
               "disk_format": 'raw',
               "image_name": 'image_name',
               "force": True}
        body = {"os-volume_upload_image": vol}
        req = fakes.HTTPRequest.blank('/v2/tenant1/volumes/%s/action' % id)
        res_dict = self.controller._volume_upload_image(req, id, body)
        expected = {'os-volume_upload_image': {'id': id,
                    'updated_at': datetime.datetime(1, 1, 1, 1, 1, 1),
                    'status': 'uploading',
                    'display_description': 'displaydesc',
                    'size': 1,
                    'volume_type': {'name': 'vol_type_name'},
                    'image_id': 1,
                    'container_format': 'bare',
                    'disk_format': 'raw',
                    'image_name': 'image_name'}}
        self.assertDictMatch(res_dict, expected)

    def test_copy_volume_to_image_volumenotfound(self):
        def stub_volume_get_raise_exc(self, context, volume_id):
            raise exception.VolumeNotFound(volume_id=volume_id)

        self.stubs.Set(volume_api.API, 'get', stub_volume_get_raise_exc)

        id = 1
        vol = {"container_format": 'bare',
               "disk_format": 'raw',
               "image_name": 'image_name',
               "force": True}
        body = {"os-volume_upload_image": vol}
        req = fakes.HTTPRequest.blank('/v2/tenant1/volumes/%s/action' % id)
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller._volume_upload_image,
                          req,
                          id,
                          body)

    def test_copy_volume_to_image_invalidvolume(self):
        def stub_upload_volume_to_image_service_raise(self, context, volume,
                                                      metadata, force):
            raise exception.InvalidVolume(reason='blah')
        self.stubs.Set(volume_api.API,
                       "copy_volume_to_image",
                       stub_upload_volume_to_image_service_raise)

        id = 1
        vol = {"container_format": 'bare',
               "disk_format": 'raw',
               "image_name": 'image_name',
               "force": True}
        body = {"os-volume_upload_image": vol}
        req = fakes.HTTPRequest.blank('/v2/tenant1/volumes/%s/action' % id)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._volume_upload_image,
                          req,
                          id,
                          body)

    def test_copy_volume_to_image_valueerror(self):
        def stub_upload_volume_to_image_service_raise(self, context, volume,
                                                      metadata, force):
            raise ValueError
        self.stubs.Set(volume_api.API,
                       "copy_volume_to_image",
                       stub_upload_volume_to_image_service_raise)

        id = 1
        vol = {"container_format": 'bare',
               "disk_format": 'raw',
               "image_name": 'image_name',
               "force": True}
        body = {"os-volume_upload_image": vol}
        req = fakes.HTTPRequest.blank('/v2/tenant1/volumes/%s/action' % id)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._volume_upload_image,
                          req,
                          id,
                          body)

    def test_copy_volume_to_image_remoteerror(self):
        def stub_upload_volume_to_image_service_raise(self, context, volume,
                                                      metadata, force):
            raise rpc_common.RemoteError
        self.stubs.Set(volume_api.API,
                       "copy_volume_to_image",
                       stub_upload_volume_to_image_service_raise)

        id = 1
        vol = {"container_format": 'bare',
               "disk_format": 'raw',
               "image_name": 'image_name',
               "force": True}
        body = {"os-volume_upload_image": vol}
        req = fakes.HTTPRequest.blank('/v2/tenant1/volumes/%s/action' % id)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._volume_upload_image,
                          req,
                          id,
                          body)

    def test_volume_upload_image_typeerror(self):
        body = {"os-volume_upload_image_fake": "fake"}
        req = fakes.HTTPRequest.blank('/v2/tenant1/volumes/%s/action' % id)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._volume_upload_image,
                          req,
                          id,
                          body)

    def test_extend_volume_valueerror(self):
        id = 1
        body = {'os-extend': {'new_size': 'fake'}}
        req = fakes.HTTPRequest.blank('/v2/tenant1/volumes/%s/action' % id)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._extend,
                          req,
                          id,
                          body)

    def test_copy_volume_to_image_notimagename(self):
        id = 1
        vol = {"container_format": 'bare',
               "disk_format": 'raw',
               "image_name": None,
               "force": True}
        body = {"os-volume_upload_image": vol}
        req = fakes.HTTPRequest.blank('/v2/tenant1/volumes/%s/action' % id)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._volume_upload_image,
                          req,
                          id,
                          body)
