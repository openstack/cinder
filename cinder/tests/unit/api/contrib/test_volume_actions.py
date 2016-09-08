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

import mock
from oslo_config import cfg
import oslo_messaging as messaging
from oslo_serialization import jsonutils
import webob

from cinder.api.contrib import volume_actions
from cinder.api.openstack import api_version_request as api_version
from cinder import context
from cinder import db
from cinder import exception
from cinder.image import glance
from cinder import objects
from cinder import test
from cinder.tests.unit.api import fakes
from cinder.tests.unit.api.v2 import stubs
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_volume
from cinder.tests.unit import utils
from cinder import volume
from cinder.volume import api as volume_api
from cinder.volume import rpcapi as volume_rpcapi


CONF = cfg.CONF


class VolumeActionsTest(test.TestCase):

    _actions = ('os-reserve', 'os-unreserve')

    _methods = ('attach', 'detach', 'reserve_volume', 'unreserve_volume')

    def setUp(self):
        super(VolumeActionsTest, self).setUp()
        self.context = context.RequestContext(fake.USER_ID, fake.PROJECT_ID,
                                              is_admin=False)
        self.UUID = uuid.uuid4()
        self.controller = volume_actions.VolumeActionsController()
        self.api_patchers = {}
        for _meth in self._methods:
            self.api_patchers[_meth] = mock.patch('cinder.volume.api.API.' +
                                                  _meth)
            self.api_patchers[_meth].start()
            self.addCleanup(self.api_patchers[_meth].stop)
            self.api_patchers[_meth].return_value = True

        db_vol = {'id': fake.VOLUME_ID, 'host': 'fake', 'status': 'available',
                  'size': 1, 'migration_status': None,
                  'volume_type_id': fake.VOLUME_TYPE_ID,
                  'project_id': fake.PROJECT_ID}
        vol = fake_volume.fake_volume_obj(self.context, **db_vol)
        self.get_patcher = mock.patch('cinder.volume.api.API.get')
        self.mock_volume_get = self.get_patcher.start()
        self.addCleanup(self.get_patcher.stop)
        self.mock_volume_get.return_value = vol
        self.update_patcher = mock.patch('cinder.volume.api.API.update')
        self.mock_volume_update = self.update_patcher.start()
        self.addCleanup(self.update_patcher.stop)
        self.mock_volume_update.return_value = vol
        self.db_get_patcher = mock.patch(
            'cinder.db.sqlalchemy.api._volume_get')
        self.mock_volume_db_get = self.db_get_patcher.start()
        self.addCleanup(self.db_get_patcher.stop)
        self.mock_volume_db_get.return_value = vol

        self.flags(rpc_backend='cinder.openstack.common.rpc.impl_fake')

    def test_simple_api_actions(self):
        app = fakes.wsgi_app(fake_auth_context=self.context)
        for _action in self._actions:
            req = webob.Request.blank('/v2/%s/volumes/%s/action' %
                                      (fake.PROJECT_ID, self.UUID))
            req.method = 'POST'
            req.body = jsonutils.dump_as_bytes({_action: None})
            req.content_type = 'application/json'
            res = req.get_response(app)
            self.assertEqual(202, res.status_int)

    def test_initialize_connection(self):
        with mock.patch.object(volume_api.API,
                               'initialize_connection') as init_conn:
            init_conn.return_value = {}
            body = {'os-initialize_connection': {'connector': 'fake'}}
            req = webob.Request.blank('/v2/%s/volumes/%s/action' %
                                      (fake.PROJECT_ID, fake.VOLUME_ID))
            req.method = "POST"
            req.body = jsonutils.dump_as_bytes(body)
            req.headers["content-type"] = "application/json"

            res = req.get_response(fakes.wsgi_app(
                fake_auth_context=self.context))
            self.assertEqual(200, res.status_int)

    def test_initialize_connection_without_connector(self):
        with mock.patch.object(volume_api.API,
                               'initialize_connection') as init_conn:
            init_conn.return_value = {}
            body = {'os-initialize_connection': {}}
            req = webob.Request.blank('/v2/%s/volumes/%s/action' %
                                      (fake.PROJECT_ID, fake.VOLUME_ID))
            req.method = "POST"
            req.body = jsonutils.dump_as_bytes(body)
            req.headers["content-type"] = "application/json"

            res = req.get_response(fakes.wsgi_app(
                fake_auth_context=self.context))
            self.assertEqual(400, res.status_int)

    def test_initialize_connection_exception(self):
        with mock.patch.object(volume_api.API,
                               'initialize_connection') as init_conn:
            init_conn.side_effect = \
                exception.VolumeBackendAPIException(data=None)
            body = {'os-initialize_connection': {'connector': 'fake'}}
            req = webob.Request.blank('/v2/%s/volumes/%s/action' %
                                      (fake.PROJECT_ID, fake.VOLUME_ID))
            req.method = "POST"
            req.body = jsonutils.dump_as_bytes(body)
            req.headers["content-type"] = "application/json"

            res = req.get_response(fakes.wsgi_app(
                fake_auth_context=self.context))
            self.assertEqual(500, res.status_int)

    def test_terminate_connection(self):
        with mock.patch.object(volume_api.API,
                               'terminate_connection') as terminate_conn:
            terminate_conn.return_value = {}
            body = {'os-terminate_connection': {'connector': 'fake'}}
            req = webob.Request.blank('/v2/%s/volumes/%s/action' %
                                      (fake.PROJECT_ID, fake.VOLUME_ID))
            req.method = "POST"
            req.body = jsonutils.dump_as_bytes(body)
            req.headers["content-type"] = "application/json"

            res = req.get_response(fakes.wsgi_app(
                fake_auth_context=self.context))
            self.assertEqual(202, res.status_int)

    def test_terminate_connection_without_connector(self):
        with mock.patch.object(volume_api.API,
                               'terminate_connection') as terminate_conn:
            terminate_conn.return_value = {}
            body = {'os-terminate_connection': {}}
            req = webob.Request.blank('/v2/%s/volumes/%s/action' %
                                      (fake.PROJECT_ID, fake.VOLUME_ID))
            req.method = "POST"
            req.body = jsonutils.dump_as_bytes(body)
            req.headers["content-type"] = "application/json"

            res = req.get_response(fakes.wsgi_app(
                fake_auth_context=self.context))
            self.assertEqual(400, res.status_int)

    def test_terminate_connection_with_exception(self):
        with mock.patch.object(volume_api.API,
                               'terminate_connection') as terminate_conn:
            terminate_conn.side_effect = \
                exception.VolumeBackendAPIException(data=None)
            body = {'os-terminate_connection': {'connector': 'fake'}}
            req = webob.Request.blank('/v2/%s/volumes/%s/action' %
                                      (fake.PROJECT_ID, fake.VOLUME_ID))
            req.method = "POST"
            req.body = jsonutils.dump_as_bytes(body)
            req.headers["content-type"] = "application/json"

            res = req.get_response(fakes.wsgi_app(
                fake_auth_context=self.context))
            self.assertEqual(500, res.status_int)

    def test_attach_to_instance(self):
        body = {'os-attach': {'instance_uuid': fake.INSTANCE_ID,
                              'mountpoint': '/dev/vdc',
                              'mode': 'rw'}}
        req = webob.Request.blank('/v2/%s/volumes/%s/action' %
                                  (fake.PROJECT_ID, fake.VOLUME_ID))
        req.method = "POST"
        req.body = jsonutils.dump_as_bytes(body)
        req.headers["content-type"] = "application/json"

        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.context))
        self.assertEqual(202, res.status_int)

        body = {'os-attach': {'instance_uuid': fake.INSTANCE_ID,
                              'host_name': 'fake_host',
                              'mountpoint': '/dev/vdc'}}
        req = webob.Request.blank('/v2/%s/volumes/%s/action' %
                                  (fake.PROJECT_ID, fake.VOLUME_ID))
        req.method = "POST"
        req.headers["content-type"] = "application/json"
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.context))
        self.assertEqual(202, res.status_int)

    def test_attach_to_host(self):
        # using 'read-write' mode attach volume by default
        body = {'os-attach': {'host_name': 'fake_host',
                              'mountpoint': '/dev/vdc'}}
        req = webob.Request.blank('/v2/%s/volumes/%s/action' %
                                  (fake.PROJECT_ID, fake.VOLUME_ID))
        req.method = "POST"
        req.body = jsonutils.dump_as_bytes(body)
        req.headers["content-type"] = "application/json"

        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.context))
        self.assertEqual(202, res.status_int)

    def test_volume_attach_to_instance_raises_remote_error(self):
        volume_remote_error = \
            messaging.RemoteError(exc_type='InvalidUUID')
        with mock.patch.object(volume_api.API, 'attach',
                               side_effect=volume_remote_error):
            id = fake.VOLUME_ID
            vol = {"instance_uuid": self.UUID,
                   "mountpoint": "/dev/vdc",
                   "mode": "rw"}
            body = {"os-attach": vol}
            req = fakes.HTTPRequest.blank('/v2/%s/volumes/%s/action' %
                                          (fake.PROJECT_ID, id))
            self.assertRaises(webob.exc.HTTPBadRequest,
                              self.controller._attach,
                              req,
                              id,
                              body)

    def test_volume_attach_to_instance_raises_db_error(self):
        # In case of DB error 500 error code is returned to user
        volume_remote_error = \
            messaging.RemoteError(exc_type='DBError')
        with mock.patch.object(volume_api.API, 'attach',
                               side_effect=volume_remote_error):
            id = fake.VOLUME_ID
            vol = {"instance_uuid": self.UUID,
                   "mountpoint": "/dev/vdc",
                   "mode": "rw"}
            body = {"os-attach": vol}
            req = fakes.HTTPRequest.blank('/v2/%s/volumes/%s/action' %
                                          (fake.PROJECT_ID, id))
            self.assertRaises(messaging.RemoteError,
                              self.controller._attach,
                              req,
                              id,
                              body)

    def test_detach(self):
        body = {'os-detach': {'attachment_id': fake.ATTACHMENT_ID}}
        req = webob.Request.blank('/v2/%s/volumes/%s/action' %
                                  (fake.PROJECT_ID, fake.VOLUME_ID))
        req.method = "POST"
        req.body = jsonutils.dump_as_bytes(body)
        req.headers["content-type"] = "application/json"

        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.context))
        self.assertEqual(202, res.status_int)

    def test_volume_detach_raises_remote_error(self):
        volume_remote_error = \
            messaging.RemoteError(exc_type='VolumeAttachmentNotFound')
        with mock.patch.object(volume_api.API, 'detach',
                               side_effect=volume_remote_error):
            id = fake.VOLUME_ID
            vol = {"attachment_id": self.UUID}
            body = {"os-detach": vol}
            req = fakes.HTTPRequest.blank('/v2/%s/volumes/%s/action' %
                                          (fake.PROJECT_ID, id))
            self.assertRaises(webob.exc.HTTPBadRequest,
                              self.controller._detach,
                              req,
                              id,
                              body)

    def test_volume_detach_raises_db_error(self):
        # In case of DB error 500 error code is returned to user
        volume_remote_error = \
            messaging.RemoteError(exc_type='DBError')
        with mock.patch.object(volume_api.API, 'detach',
                               side_effect=volume_remote_error):
            id = fake.VOLUME_ID
            vol = {"attachment_id": self.UUID}
            body = {"os-detach": vol}
            req = fakes.HTTPRequest.blank('/v2/%s/volumes/%s/action' %
                                          (fake.PROJECT_ID, id))
            self.assertRaises(messaging.RemoteError,
                              self.controller._detach,
                              req,
                              id,
                              body)

    def test_attach_with_invalid_arguments(self):
        # Invalid request to attach volume an invalid target
        body = {'os-attach': {'mountpoint': '/dev/vdc'}}
        req = webob.Request.blank('/v2/%s/volumes/%s/action' %
                                  (fake.PROJECT_ID, fake.VOLUME_ID))
        req.method = "POST"
        req.headers["content-type"] = "application/json"
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.context))
        self.assertEqual(400, res.status_int)

        # Invalid request to attach volume with an invalid mode
        body = {'os-attach': {'instance_uuid': 'fake',
                              'mountpoint': '/dev/vdc',
                              'mode': 'rr'}}
        req = webob.Request.blank('/v2/%s/volumes/%s/action' %
                                  (fake.PROJECT_ID, fake.VOLUME_ID))
        req.method = "POST"
        req.headers["content-type"] = "application/json"
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.context))
        self.assertEqual(400, res.status_int)
        body = {'os-attach': {'host_name': 'fake_host',
                              'mountpoint': '/dev/vdc',
                              'mode': 'ww'}}
        req = webob.Request.blank('/v2/%s/volumes/%s/action' %
                                  (fake.PROJECT_ID, fake.VOLUME_ID))
        req.method = "POST"
        req.headers["content-type"] = "application/json"
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.context))
        self.assertEqual(400, res.status_int)

    def test_begin_detaching(self):
        def fake_begin_detaching(*args, **kwargs):
            return {}
        self.mock_object(volume.api.API, 'begin_detaching',
                         fake_begin_detaching)

        body = {'os-begin_detaching': {'fake': 'fake'}}
        req = webob.Request.blank('/v2/%s/volumes/%s/action' %
                                  (fake.PROJECT_ID, fake.VOLUME_ID))
        req.method = "POST"
        req.body = jsonutils.dump_as_bytes(body)
        req.headers["content-type"] = "application/json"

        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.context))
        self.assertEqual(202, res.status_int)

    def test_roll_detaching(self):
        def fake_roll_detaching(*args, **kwargs):
            return {}
        self.mock_object(volume.api.API, 'roll_detaching',
                         fake_roll_detaching)

        body = {'os-roll_detaching': {'fake': 'fake'}}
        req = webob.Request.blank('/v2/%s/volumes/%s/action' %
                                  (fake.PROJECT_ID, fake.VOLUME_ID))
        req.method = "POST"
        req.body = jsonutils.dump_as_bytes(body)
        req.headers["content-type"] = "application/json"

        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.context))
        self.assertEqual(202, res.status_int)

    def test_extend_volume(self):
        def fake_extend_volume(*args, **kwargs):
            return {}
        self.mock_object(volume.api.API, 'extend',
                         fake_extend_volume)

        body = {'os-extend': {'new_size': 5}}
        req = webob.Request.blank('/v2/%s/volumes/%s/action' %
                                  (fake.PROJECT_ID, fake.VOLUME_ID))
        req.method = "POST"
        req.body = jsonutils.dump_as_bytes(body)
        req.headers["content-type"] = "application/json"

        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.context))
        self.assertEqual(202, res.status_int)

    def test_extend_volume_invalid_status(self):
        def fake_extend_volume(*args, **kwargs):
            msg = "Volume status must be available"
            raise exception.InvalidVolume(reason=msg)
        self.mock_object(volume.api.API, 'extend',
                         fake_extend_volume)

        body = {'os-extend': {'new_size': 5}}
        req = webob.Request.blank('/v2/%s/volumes/%s/action' %
                                  (fake.PROJECT_ID, fake.VOLUME_ID))
        req.method = "POST"
        req.body = jsonutils.dump_as_bytes(body)
        req.headers["content-type"] = "application/json"

        res = req.get_response(fakes.wsgi_app(fake_auth_context=self.context))
        self.assertEqual(400, res.status_int)

    def test_update_readonly_flag(self):
        def fake_update_readonly_flag(*args, **kwargs):
            return {}
        self.mock_object(volume.api.API, 'update_readonly_flag',
                         fake_update_readonly_flag)

        def make_update_readonly_flag_test(self, readonly, return_code):
            body = {"os-update_readonly_flag": {"readonly": readonly}}
            if readonly is None:
                body = {"os-update_readonly_flag": {}}
            req = webob.Request.blank('/v2/%s/volumes/%s/action' %
                                      (fake.PROJECT_ID, fake.VOLUME_ID))
            req.method = "POST"
            req.body = jsonutils.dump_as_bytes(body)
            req.headers["content-type"] = "application/json"
            res = req.get_response(fakes.wsgi_app(
                fake_auth_context=self.context))
            self.assertEqual(return_code, res.status_int)

        make_update_readonly_flag_test(self, True, 202)
        make_update_readonly_flag_test(self, False, 202)
        make_update_readonly_flag_test(self, '1', 202)
        make_update_readonly_flag_test(self, '0', 202)
        make_update_readonly_flag_test(self, 'true', 202)
        make_update_readonly_flag_test(self, 'false', 202)
        make_update_readonly_flag_test(self, 'tt', 400)
        make_update_readonly_flag_test(self, 11, 400)
        make_update_readonly_flag_test(self, None, 400)

    def test_set_bootable(self):

        def make_set_bootable_test(self, bootable, return_code):
            body = {"os-set_bootable": {"bootable": bootable}}
            if bootable is None:
                body = {"os-set_bootable": {}}
            req = webob.Request.blank('/v2/%s/volumes/%s/action' %
                                      (fake.PROJECT_ID, fake.VOLUME_ID))
            req.method = "POST"
            req.body = jsonutils.dump_as_bytes(body)
            req.headers["content-type"] = "application/json"
            res = req.get_response(fakes.wsgi_app(
                fake_auth_context=self.context))
            self.assertEqual(return_code, res.status_int)

        make_set_bootable_test(self, True, 200)
        make_set_bootable_test(self, False, 200)
        make_set_bootable_test(self, '1', 200)
        make_set_bootable_test(self, '0', 200)
        make_set_bootable_test(self, 'true', 200)
        make_set_bootable_test(self, 'false', 200)
        make_set_bootable_test(self, 'tt', 400)
        make_set_bootable_test(self, 11, 400)
        make_set_bootable_test(self, None, 400)


class VolumeRetypeActionsTest(test.TestCase):
    def setUp(self):
        super(VolumeRetypeActionsTest, self).setUp()

        self.context = context.RequestContext(fake.USER_ID, fake.PROJECT_ID,
                                              is_admin=False)
        self.flags(rpc_backend='cinder.openstack.common.rpc.impl_fake')

        self.retype_mocks = {}
        paths = ('cinder.quota.QUOTAS.add_volume_type_opts',
                 'cinder.quota.QUOTAS.reserve')
        for path in paths:
            name = path.split('.')[-1]
            patcher = mock.patch(path, return_value=None)
            self.retype_mocks[name] = patcher.start()
            self.addCleanup(patcher.stop)

    @mock.patch('cinder.db.sqlalchemy.api.resource_exists', return_value=True)
    def _retype_volume_exec(self, expected_status,
                            new_type=fake.VOLUME_TYPE2_ID, vol_id=None,
                            exists_mock=None):
        vol_id = vol_id or fake.VOLUME_ID
        req = webob.Request.blank('/v2/%s/volumes/%s/action' %
                                  (fake.PROJECT_ID, vol_id))
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'
        retype_body = {'new_type': new_type, 'migration_policy': 'never'}
        req.body = jsonutils.dump_as_bytes({'os-retype': retype_body})
        res = req.get_response(fakes.wsgi_app(fake_auth_context=self.context))
        self.assertEqual(expected_status, res.status_int)

    def test_retype_volume_no_body(self):
        # Request with no body should fail
        vol = utils.create_volume(self.context,
                                  status='available',
                                  testcase_instance=self)
        req = webob.Request.blank('/v2/%s/volumes/%s/action' %
                                  (fake.PROJECT_ID, vol.id))
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'
        req.body = jsonutils.dump_as_bytes({'os-retype': None})
        res = req.get_response(fakes.wsgi_app(fake_auth_context=self.context))
        self.assertEqual(400, res.status_int)

    def test_retype_volume_bad_policy(self):
        # Request with invalid migration policy should fail
        vol = utils.create_volume(self.context,
                                  status='available',
                                  testcase_instance=self)
        req = webob.Request.blank('/v2/%s/volumes/%s/action' %
                                  (fake.PROJECT_ID, vol.id))
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'
        retype_body = {'new_type': 'foo', 'migration_policy': 'invalid'}
        req.body = jsonutils.dump_as_bytes({'os-retype': retype_body})
        res = req.get_response(fakes.wsgi_app(fake_auth_context=self.context))
        self.assertEqual(400, res.status_int)

    def test_retype_volume_bad_status(self):
        # Should fail if volume does not have proper status
        vol_type_old = utils.create_volume_type(context.get_admin_context(),
                                                self, name='old')
        vol_type_new = utils.create_volume_type(context.get_admin_context(),
                                                self, name='new')
        vol = utils.create_volume(self.context,
                                  status='error',
                                  volume_type_id=vol_type_old.id,
                                  testcase_instance=self)

        self._retype_volume_exec(400, vol_type_new.id, vol.id)

    def test_retype_type_no_exist(self):
        # Should fail if new type does not exist
        vol_type_old = utils.create_volume_type(context.get_admin_context(),
                                                self, name='old')
        vol = utils.create_volume(self.context,
                                  status='available',
                                  volume_type_id=vol_type_old.id,
                                  testcase_instance=self)
        self._retype_volume_exec(404, 'fake_vol_type', vol.id)

    def test_retype_same_type(self):
        # Should fail if new type and old type are the same
        vol_type_old = utils.create_volume_type(context.get_admin_context(),
                                                self, name='old')
        vol = utils.create_volume(self.context,
                                  status='available',
                                  volume_type_id=vol_type_old.id,
                                  testcase_instance=self)
        self._retype_volume_exec(400, vol_type_old.id, vol.id)

    def test_retype_over_quota(self):
        # Should fail if going over quota for new type
        vol_type_new = utils.create_volume_type(context.get_admin_context(),
                                                self, name='old')
        vol = utils.create_volume(self.context,
                                  status='available',
                                  testcase_instance=self)

        exc = exception.OverQuota(overs=['gigabytes'],
                                  quotas={'gigabytes': 20},
                                  usages={'gigabytes': {'reserved': 5,
                                                        'in_use': 15}})
        self.retype_mocks['reserve'].side_effect = exc
        self._retype_volume_exec(413, vol_type_new.id, vol.id)

    def _retype_volume_qos(self, vol_status, consumer_pass, expected_status,
                           same_qos=False, has_qos=True, has_type=True):
        admin_ctxt = context.get_admin_context()
        if has_qos:
            qos_old = utils.create_qos(admin_ctxt, self,
                                       name='old',
                                       consumer=consumer_pass)['id']
        else:
            qos_old = None

        if same_qos:
            qos_new = qos_old
        else:
            qos_new = utils.create_qos(admin_ctxt, self,
                                       name='new',
                                       consumer=consumer_pass)['id']

        if has_type:
            vol_type_old = utils.create_volume_type(admin_ctxt, self,
                                                    name='old',
                                                    qos_specs_id=qos_old).id
        else:
            vol_type_old = None

        vol_type_new = utils.create_volume_type(admin_ctxt, self,
                                                name='new',
                                                qos_specs_id=qos_new).id

        vol = utils.create_volume(self.context,
                                  status=vol_status,
                                  volume_type_id=vol_type_old,
                                  testcase_instance=self)

        self._retype_volume_exec(expected_status, vol_type_new, vol.id)

    def test_retype_volume_diff_qos_fe_in_use(self):
        # should fail if changing qos enforced by front-end for in-use volume
        self._retype_volume_qos('in-use', 'front-end', 400)

    def test_retype_volume_diff_qos_be_in_use(self):
        # should NOT fail for in-use if changing qos enforced by back-end
        self._retype_volume_qos('in-use', 'back-end', 202)

    def test_retype_volume_diff_qos_fe_available(self):
        # should NOT fail if changing qos enforced by FE for available volumes
        self._retype_volume_qos('available', 'front-end', 202)

    def test_retype_volume_diff_qos_be_available(self):
        # should NOT fail if changing qos enforced by back-end for available
        # volumes
        self._retype_volume_qos('available', 'back-end', 202)

    def test_retype_volume_same_qos_fe_in_use(self):
        # should NOT fail if changing qos enforced by front-end for in-use
        # volumes if the qos is the same
        self._retype_volume_qos('in-use', 'front-end', 202, True)

    def test_retype_volume_same_qos_be_in_use(self):
        # should NOT fail if changing qos enforced by back-end for in-use
        # volumes if the qos is the same
        self._retype_volume_qos('in-use', 'back-end', 202, True)

    def test_retype_volume_same_qos_fe_available(self):
        # should NOT fail if changing qos enforced by front-end for available
        # volumes if the qos is the same
        self._retype_volume_qos('available', 'front-end', 202, True)

    def test_retype_volume_same_qos_be_available(self):
        # should NOT fail if changing qos enforced by back-end for available
        # volumes if the qos is the same
        self._retype_volume_qos('available', 'back-end', 202, True)

    def test_retype_volume_orig_no_qos_dest_fe_in_use(self):
        # should fail if changing qos enforced by front-end on the new type
        # and volume originally had no qos and was in-use
        self._retype_volume_qos('in-use', 'front-end', 400, False, False)

    def test_retype_volume_orig_no_qos_dest_be_in_use(self):
        # should NOT fail if changing qos enforced by back-end on the new type
        # and volume originally had no qos and was in-use
        self._retype_volume_qos('in-use', 'back-end', 202, False, False)

    def test_retype_volume_same_no_qos_in_use(self):
        # should NOT fail if original and destinal types had no qos for in-use
        # volumes
        self._retype_volume_qos('in-use', '', 202, True, False)

    def test_retype_volume_orig_no_qos_dest_fe_available(self):
        # should NOT fail if changing qos enforced by front-end on the new type
        # and volume originally had no qos and was available
        self._retype_volume_qos('available', 'front-end', 202, False, False)

    def test_retype_volume_orig_no_qos_dest_be_available(self):
        # should NOT fail if changing qos enforced by back-end on the new type
        # and volume originally had no qos and was available
        self._retype_volume_qos('available', 'back-end', 202, False, False)

    def test_retype_volume_same_no_qos_vailable(self):
        # should NOT fail if original and destinal types had no qos for
        # available volumes
        self._retype_volume_qos('available', '', 202, True, False)

    def test_retype_volume_orig_no_type_dest_fe_in_use(self):
        # should fail if changing volume had no type, was in-use and
        # destination type qos was enforced by front-end
        self._retype_volume_qos('in-use', 'front-end', 400, False, False,
                                False)

    def test_retype_volume_orig_no_type_dest_no_qos_in_use(self):
        # should NOT fail if changing volume had no type, was in-use and
        # destination type had no qos
        # and volume originally had no type and was in-use
        self._retype_volume_qos('in-use', '', 202, True, False, False)

    def test_retype_volume_orig_no_type_dest_be_in_use(self):
        # should NOT fail if changing volume had no type, was in-use and
        # destination type qos was enforced by back-end
        self._retype_volume_qos('in-use', 'back-end', 202, False, False,
                                False)

    def test_retype_volume_orig_no_type_dest_fe_available(self):
        # should NOT fail if changing volume had no type, was in-use and
        # destination type qos was enforced by front-end
        self._retype_volume_qos('available', 'front-end', 202, False, False,
                                False)

    def test_retype_volume_orig_no_type_dest_no_qos_available(self):
        # should NOT fail if changing volume had no type, was available and
        # destination type had no qos
        # and volume originally had no type and was in-use
        self._retype_volume_qos('in-use', '', 202, True, False, False)

    def test_retype_volume_orig_no_type_dest_be_available(self):
        # should NOT fail if changing volume had no type, was available and
        # destination type qos was enforced by back-end
        self._retype_volume_qos('in-use', 'back-end', 202, False, False,
                                False)

    def _retype_volume_encryption(self, vol_status, expected_status,
                                  has_type=True, enc_orig=True, enc_dest=True):
        enc_orig = None
        admin_ctxt = context.get_admin_context()
        if has_type:
            vol_type_old = utils.create_volume_type(admin_ctxt, self,
                                                    name='old').id
            if enc_orig:
                utils.create_encryption(admin_ctxt, vol_type_old, self)
        else:
            vol_type_old = None

        vol_type_new = utils.create_volume_type(admin_ctxt, self,
                                                name='new').id
        if enc_dest:
            utils.create_encryption(admin_ctxt, vol_type_new, self)

        vol = utils.create_volume(self.context,
                                  status=vol_status,
                                  volume_type_id=vol_type_old,
                                  testcase_instance=self)

        self._retype_volume_exec(expected_status, vol_type_new, vol.id)

    def test_retype_volume_orig_no_type_dest_no_enc(self):
        self._retype_volume_encryption('available', 202, False, False, False)

    def test_retype_volume_orig_no_type_dest_enc(self):
        self._retype_volume_encryption('available', 202, False, False)

    def test_retype_volume_orig_type_no_enc_dest_no_enc(self):
        self._retype_volume_encryption('available', 202, True, False, False)

    def test_retype_volume_orig_type_no_enc_dest_enc(self):
        self._retype_volume_encryption('available', 202, True, False)

    def test_retype_volume_orig_type_enc_dest_enc(self):
        self._retype_volume_encryption('available', 202)


def fake_volume_get(self, context, volume_id):
    volume = stubs.stub_volume(volume_id)
    if volume_id == fake.VOLUME3_ID:
        volume['status'] = 'in-use'
    else:
        volume['status'] = 'available'
    return volume


def fake_upload_volume_to_image_service(self, context, volume, metadata,
                                        force):
    ret = {"id": volume['id'],
           "updated_at": datetime.datetime(1, 1, 1, 1, 1, 1),
           "status": 'uploading',
           "display_description": volume['display_description'],
           "size": volume['size'],
           "volume_type": volume['volume_type'],
           "image_id": fake.IMAGE_ID,
           "container_format": 'bare',
           "disk_format": 'raw',
           "image_name": 'image_name'}
    return ret


class VolumeImageActionsTest(test.TestCase):
    def setUp(self):
        super(VolumeImageActionsTest, self).setUp()
        self.controller = volume_actions.VolumeActionsController()
        self.context = context.RequestContext(fake.USER_ID, fake.PROJECT_ID,
                                              is_admin=False)

    def _get_os_volume_upload_image(self):
        vol = {
            "container_format": 'bare',
            "disk_format": 'raw',
            "updated_at": datetime.datetime(1, 1, 1, 1, 1, 1),
            "image_name": 'image_name',
            "force": True}
        body = {"os-volume_upload_image": vol}

        return body

    def fake_image_service_create(self, *args):
        ret = {
            'status': u'queued',
            'name': u'image_name',
            'deleted': False,
            'container_format': u'bare',
            'created_at': datetime.datetime(1, 1, 1, 1, 1, 1),
            'disk_format': u'raw',
            'updated_at': datetime.datetime(1, 1, 1, 1, 1, 1),
            'id': fake.IMAGE_ID,
            'min_ram': 0,
            'checksum': None,
            'min_disk': 0,
            'deleted_at': None,
            'properties': {u'x_billing_code_license': u'246254365'},
            'size': 0}
        return ret

    def fake_image_service_create_3_1(self, *args):
        ret = {
            'status': u'queued',
            'name': u'image_name',
            'deleted': False,
            'container_format': u'bare',
            'created_at': datetime.datetime(1, 1, 1, 1, 1, 1),
            'disk_format': u'raw',
            'updated_at': datetime.datetime(1, 1, 1, 1, 1, 1),
            'id': fake.IMAGE_ID,
            'min_ram': 0,
            'checksum': None,
            'min_disk': 0,
            'visibility': 'public',
            'protected': True,
            'deleted_at': None,
            'properties': {u'x_billing_code_license': u'246254365'},
            'size': 0}
        return ret

    def fake_rpc_copy_volume_to_image(self, *args):
        pass

    @mock.patch.object(volume_api.API, 'get', fake_volume_get)
    @mock.patch.object(volume_api.API, "copy_volume_to_image",
                       fake_upload_volume_to_image_service)
    def test_copy_volume_to_image(self):
        id = fake.VOLUME_ID
        vol = {"container_format": 'bare',
               "disk_format": 'raw',
               "image_name": 'image_name',
               "force": True}
        body = {"os-volume_upload_image": vol}
        req = fakes.HTTPRequest.blank('/v2/%s/volumes/%s/action' %
                                      (fake.PROJECT_ID, id))
        res_dict = self.controller._volume_upload_image(req, id, body)
        expected = {'os-volume_upload_image':
                    {'id': id,
                     'updated_at': datetime.datetime(1, 1, 1, 1, 1, 1),
                     'status': 'uploading',
                     'display_description': 'displaydesc',
                     'size': 1,
                     'volume_type': fake_volume.fake_db_volume_type(
                         name='vol_type_name'),
                     'image_id': fake.IMAGE_ID,
                     'container_format': 'bare',
                     'disk_format': 'raw',
                     'image_name': 'image_name'}}
        self.assertDictMatch(expected, res_dict)

    def test_copy_volume_to_image_volumenotfound(self):
        def fake_volume_get_raise_exc(self, context, volume_id):
            raise exception.VolumeNotFound(volume_id=volume_id)

        self.mock_object(volume_api.API, 'get', fake_volume_get_raise_exc)

        id = fake.WILL_NOT_BE_FOUND_ID
        vol = {"container_format": 'bare',
               "disk_format": 'raw',
               "image_name": 'image_name',
               "force": True}
        body = {"os-volume_upload_image": vol}
        req = fakes.HTTPRequest.blank('/v2/%s/volumes/%s/action' %
                                      (fake.PROJECT_ID, id))
        self.assertRaises(exception.VolumeNotFound,
                          self.controller._volume_upload_image,
                          req,
                          id,
                          body)

    @mock.patch.object(volume_api.API, 'get', fake_volume_get)
    @mock.patch.object(volume_api.API, 'copy_volume_to_image',
                       side_effect=exception.InvalidVolume(reason='blah'))
    def test_copy_volume_to_image_invalidvolume(self, mock_copy):
        id = fake.VOLUME2_ID
        vol = {"container_format": 'bare',
               "disk_format": 'raw',
               "image_name": 'image_name',
               "force": True}
        body = {"os-volume_upload_image": vol}
        req = fakes.HTTPRequest.blank('/v2/%s/volumes/%s/action' %
                                      (fake.PROJECT_ID, fake.VOLUME_ID))
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._volume_upload_image,
                          req,
                          id,
                          body)

    @mock.patch.object(volume_api.API, 'get', fake_volume_get)
    def test_copy_volume_to_image_invalid_disk_format(self):
        id = fake.IMAGE_ID
        vol = {"container_format": 'bare',
               "disk_format": 'iso',
               "image_name": 'image_name',
               "force": True}
        body = {"os-volume_upload_image": vol}
        req = fakes.HTTPRequest.blank('/v2/%s/volumes/%s/action'
                                      % (fake.PROJECT_ID, id))
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._volume_upload_image,
                          req,
                          id,
                          body)

    @mock.patch.object(volume_api.API, 'get', fake_volume_get)
    @mock.patch.object(volume_api.API, 'copy_volume_to_image',
                       side_effect=ValueError)
    def test_copy_volume_to_image_valueerror(self, mock_copy):
        id = fake.VOLUME2_ID
        vol = {"container_format": 'bare',
               "disk_format": 'raw',
               "image_name": 'image_name',
               "force": True}
        body = {"os-volume_upload_image": vol}
        req = fakes.HTTPRequest.blank('/v2/%s/volumes/%s/action' %
                                      (fake.PROJECT_ID, fake.VOLUME_ID))
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._volume_upload_image,
                          req,
                          id,
                          body)

    @mock.patch.object(volume_api.API, 'get', fake_volume_get)
    @mock.patch.object(volume_api.API, 'copy_volume_to_image',
                       side_effect=messaging.RemoteError)
    def test_copy_volume_to_image_remoteerror(self, mock_copy):
        id = fake.VOLUME2_ID
        vol = {"container_format": 'bare',
               "disk_format": 'raw',
               "image_name": 'image_name',
               "force": True}
        body = {"os-volume_upload_image": vol}
        req = fakes.HTTPRequest.blank('/v2/%s/volumes/%s/action' %
                                      (fake.PROJECT_ID, id))
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._volume_upload_image,
                          req,
                          id,
                          body)

    def test_volume_upload_image_typeerror(self):
        id = fake.VOLUME2_ID
        body = {"os-volume_upload_image_fake": "fake"}
        req = webob.Request.blank('/v2/%s/volumes/%s/action' %
                                  (fake.PROJECT_ID, id))
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(fakes.wsgi_app(fake_auth_context=self.context))
        self.assertEqual(400, res.status_int)

    def test_volume_upload_image_without_type(self):
        id = fake.VOLUME2_ID
        vol = {"container_format": 'bare',
               "disk_format": 'raw',
               "image_name": None,
               "force": True}
        body = {"": vol}
        req = webob.Request.blank('/v2/%s/volumes/%s/action' %
                                  (fake.PROJECT_ID, id))
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(fakes.wsgi_app(fake_auth_context=self.context))
        self.assertEqual(400, res.status_int)

    @mock.patch.object(volume_api.API, 'get', fake_volume_get)
    def test_extend_volume_valueerror(self):
        id = fake.VOLUME2_ID
        body = {'os-extend': {'new_size': 'fake'}}
        req = fakes.HTTPRequest.blank('/v2/%s/volumes/%s/action' %
                                      (fake.PROJECT_ID, id))
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._extend,
                          req,
                          id,
                          body)

    def test_copy_volume_to_image_notimagename(self):
        id = fake.VOLUME2_ID
        vol = {"container_format": 'bare',
               "disk_format": 'raw',
               "image_name": None,
               "force": True}
        body = {"os-volume_upload_image": vol}
        req = fakes.HTTPRequest.blank('/v2/%s/volumes/%s/action' %
                                      (fake.PROJECT_ID, id))
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._volume_upload_image,
                          req,
                          id,
                          body)

    def _create_volume_with_type(self, status='available',
                                 display_description='displaydesc', **kwargs):
        admin_ctxt = context.get_admin_context()
        vol_type = db.volume_type_create(admin_ctxt, {'name': 'vol_name'})
        self.addCleanup(db.volume_type_destroy, admin_ctxt, vol_type.id)

        volume = utils.create_volume(self.context, volume_type_id=vol_type.id,
                                     status=status,
                                     display_description=display_description,
                                     **kwargs)
        self.addCleanup(db.volume_destroy, admin_ctxt, volume.id)

        expected = {
            'os-volume_upload_image': {
                'id': volume.id,
                'updated_at': 'DONTCARE',
                'status': 'uploading',
                'display_description': 'displaydesc',
                'size': 1,
                'volume_type': 'DONTCARE',
                'image_id': fake.IMAGE_ID,
                'container_format': 'bare',
                'disk_format': 'raw',
                'image_name': 'image_name'
            }
        }
        return volume, expected

    @mock.patch.object(volume_api.API, "get_volume_image_metadata")
    @mock.patch.object(glance.GlanceImageService, "create")
    @mock.patch.object(volume_rpcapi.VolumeAPI, "copy_volume_to_image")
    def test_copy_volume_to_image_with_protected_prop(
            self, mock_copy_to_image, mock_create, mock_get_image_metadata):
        """Test create image from volume with protected properties."""
        volume, expected = self._create_volume_with_type()
        mock_get_image_metadata.return_value = {"volume_id": volume.id,
                                                "key": "x_billing_license",
                                                "value": "246254365"}
        mock_create.side_effect = self.fake_image_service_create

        req = fakes.HTTPRequest.blank(
            '/v2/%s/volumes/%s/action' % (fake.PROJECT_ID, volume.id),
            use_admin_context=self.context.is_admin)
        body = self._get_os_volume_upload_image()

        res_dict = self.controller._volume_upload_image(req, volume.id, body)

        self.assertDictMatch(expected, res_dict)
        vol_db = objects.Volume.get_by_id(self.context, volume.id)
        self.assertEqual('uploading', vol_db.status)
        self.assertEqual('available', vol_db.previous_status)

    @mock.patch.object(volume_api.API, 'get', fake_volume_get)
    def test_copy_volume_to_image_public_not_authorized(self):
        """Test unauthorized create public image from volume."""
        id = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        req = fakes.HTTPRequest.blank('/v3/tenant1/volumes/%s/action' % id)
        req.environ['cinder.context'].is_admin = False
        req.headers = {'OpenStack-API-Version': 'volume 3.1'}
        req.api_version_request = api_version.APIVersionRequest('3.1')
        body = self._get_os_volume_upload_image()
        body['os-volume_upload_image']['visibility'] = 'public'
        self.assertRaises(exception.PolicyNotAuthorized,
                          self.controller._volume_upload_image,
                          req, id, body)

    @mock.patch.object(volume_api.API, "get_volume_image_metadata")
    @mock.patch.object(glance.GlanceImageService, "create")
    @mock.patch.object(volume_rpcapi.VolumeAPI, "copy_volume_to_image")
    def test_copy_volume_to_image_without_glance_metadata(
            self, mock_copy_to_image, mock_create, mock_get_image_metadata):
        """Test create image from volume if volume is created without image.

        In this case volume glance metadata will not be available for this
        volume.
        """
        volume, expected = self._create_volume_with_type()

        mock_get_image_metadata.side_effect = \
            exception.GlanceMetadataNotFound(id=volume.id)
        mock_create.side_effect = self.fake_image_service_create

        req = fakes.HTTPRequest.blank(
            '/v2/%s/volumes/%s/action' % (fake.PROJECT_ID, volume.id),
            use_admin_context=self.context.is_admin)
        body = self._get_os_volume_upload_image()
        res_dict = self.controller._volume_upload_image(req, volume.id, body)

        self.assertDictMatch(expected, res_dict)
        vol_db = objects.Volume.get_by_id(self.context, volume.id)
        self.assertEqual('uploading', vol_db.status)
        self.assertEqual('available', vol_db.previous_status)

    @mock.patch.object(volume_api.API, "get_volume_image_metadata")
    @mock.patch.object(glance.GlanceImageService, "create")
    @mock.patch.object(volume_rpcapi.VolumeAPI, "copy_volume_to_image")
    def test_copy_volume_to_image_fail_image_create(
            self, mock_copy_to_image, mock_create, mock_get_image_metadata):
        """Test create image from volume if create image fails.

        In this case API will rollback to previous status.
        """
        volume = utils.create_volume(self.context)

        mock_get_image_metadata.return_value = {}
        mock_create.side_effect = Exception()

        req = fakes.HTTPRequest.blank(
            '/v2/fakeproject/volumes/%s/action' % volume.id)
        body = self._get_os_volume_upload_image()
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._volume_upload_image, req, volume.id,
                          body)

        self.assertFalse(mock_copy_to_image.called)
        vol_db = objects.Volume.get_by_id(self.context, volume.id)
        self.assertEqual('available', vol_db.status)
        self.assertIsNone(vol_db.previous_status)
        db.volume_destroy(context.get_admin_context(), volume.id)

    @mock.patch.object(volume_api.API, "get_volume_image_metadata")
    @mock.patch.object(glance.GlanceImageService, "create")
    @mock.patch.object(volume_rpcapi.VolumeAPI, "copy_volume_to_image")
    def test_copy_volume_to_image_in_use_no_force(
            self, mock_copy_to_image, mock_create, mock_get_image_metadata):
        """Test create image from in-use volume.

        In this case API will fail because we are not passing force.
        """
        volume = utils.create_volume(self.context, status='in-use')

        mock_get_image_metadata.return_value = {}
        mock_create.side_effect = self.fake_image_service_create

        req = fakes.HTTPRequest.blank(
            '/v2/fakeproject/volumes/%s/action' % volume.id)
        body = self._get_os_volume_upload_image()
        body['os-volume_upload_image']['force'] = False
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._volume_upload_image, req, volume.id,
                          body)

        self.assertFalse(mock_copy_to_image.called)
        vol_db = objects.Volume.get_by_id(self.context, volume.id)
        self.assertEqual('in-use', vol_db.status)
        self.assertIsNone(vol_db.previous_status)
        db.volume_destroy(context.get_admin_context(), volume.id)

    @mock.patch.object(volume_api.API, "get_volume_image_metadata")
    @mock.patch.object(glance.GlanceImageService, "create")
    @mock.patch.object(volume_rpcapi.VolumeAPI, "copy_volume_to_image")
    def test_copy_volume_to_image_in_use_with_force(
            self, mock_copy_to_image, mock_create, mock_get_image_metadata):
        """Test create image from in-use volume.

        In this case API will succeed only when CON.enable_force_upload is
        enabled.
        """
        volume, expected = self._create_volume_with_type(status='in-use')
        mock_get_image_metadata.return_value = {}
        mock_create.side_effect = self.fake_image_service_create

        req = fakes.HTTPRequest.blank(
            '/v2/fakeproject/volumes/%s/action' % volume.id,
            use_admin_context=self.context.is_admin)
        body = self._get_os_volume_upload_image()
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._volume_upload_image, req, volume.id,
                          body)

        self.assertFalse(mock_copy_to_image.called)
        vol_db = objects.Volume.get_by_id(self.context, volume.id)
        self.assertEqual('in-use', vol_db.status)
        self.assertIsNone(vol_db.previous_status)

        CONF.set_default('enable_force_upload', True)
        res_dict = self.controller._volume_upload_image(req, volume.id, body)

        self.assertDictMatch(expected, res_dict)

        vol_db = objects.Volume.get_by_id(self.context, volume.id)
        self.assertEqual('uploading', vol_db.status)
        self.assertEqual('in-use', vol_db.previous_status)

    @mock.patch.object(volume_api.API, "get_volume_image_metadata")
    @mock.patch.object(glance.GlanceImageService, "create")
    @mock.patch.object(volume_rpcapi.VolumeAPI, "copy_volume_to_image")
    def test_copy_volume_to_image_without_protected_prop(
            self, mock_volume_to_image, mock_create, mock_get_image_metadata):
        """Test protected property is not defined with the root image."""
        volume, expected = self._create_volume_with_type()

        mock_get_image_metadata.return_value = {}
        mock_create.side_effect = self.fake_image_service_create

        req = fakes.HTTPRequest.blank(
            '/v2/fakeproject/volumes/%s/action' % volume.id,
            use_admin_context=self.context.is_admin)

        body = self._get_os_volume_upload_image()
        res_dict = self.controller._volume_upload_image(req, volume.id, body)

        self.assertDictMatch(expected, res_dict)
        vol_db = objects.Volume.get_by_id(self.context, volume.id)
        self.assertEqual('uploading', vol_db.status)
        self.assertEqual('available', vol_db.previous_status)

    @mock.patch.object(glance.GlanceImageService, "create")
    @mock.patch.object(volume_rpcapi.VolumeAPI, "copy_volume_to_image")
    def test_copy_volume_to_image_without_core_prop(
            self, mock_copy_to_image, mock_create):
        """Test glance_core_properties defined in cinder.conf is empty."""
        volume, expected = self._create_volume_with_type()
        mock_create.side_effect = self.fake_image_service_create

        self.override_config('glance_core_properties', [])

        req = fakes.HTTPRequest.blank(
            '/v2/fakeproject/volumes/%s/action' % volume.id,
            use_admin_context=self.context.is_admin)

        body = self._get_os_volume_upload_image()
        res_dict = self.controller._volume_upload_image(req, volume.id, body)

        self.assertDictMatch(expected, res_dict)
        vol_db = objects.Volume.get_by_id(self.context, volume.id)
        self.assertEqual('uploading', vol_db.status)
        self.assertEqual('available', vol_db.previous_status)

    @mock.patch.object(volume_api.API, "get_volume_image_metadata")
    @mock.patch.object(glance.GlanceImageService, "create")
    @mock.patch.object(volume_rpcapi.VolumeAPI, "copy_volume_to_image")
    def test_copy_volume_to_image_volume_type_none(
            self,
            mock_copy_volume_to_image,
            mock_create,
            mock_get_volume_image_metadata):
        """Test create image from volume with none type volume."""
        volume, expected = self._create_volume_with_type()

        mock_create.side_effect = self.fake_image_service_create

        req = fakes.HTTPRequest.blank(
            '/v2/%s/volumes/%s/action' % (fake.PROJECT_ID, volume.id),
            use_admin_context=self.context.is_admin)
        body = self._get_os_volume_upload_image()
        res_dict = self.controller._volume_upload_image(req, volume.id, body)
        self.assertDictMatch(expected, res_dict)

    @mock.patch.object(volume_api.API, "get_volume_image_metadata")
    @mock.patch.object(glance.GlanceImageService, "create")
    @mock.patch.object(volume_rpcapi.VolumeAPI, "copy_volume_to_image")
    def test_copy_volume_to_image_version_3_1(
            self,
            mock_copy_volume_to_image,
            mock_create,
            mock_get_volume_image_metadata):
        """Test create image from volume with protected properties."""
        volume, expected = self._create_volume_with_type()

        mock_get_volume_image_metadata.return_value = {
            "volume_id": volume.id,
            "key": "x_billing_code_license",
            "value": "246254365"}
        mock_create.side_effect = self.fake_image_service_create_3_1
        mock_copy_volume_to_image.side_effect = \
            self.fake_rpc_copy_volume_to_image

        self.override_config('glance_api_version', 2)

        req = fakes.HTTPRequest.blank(
            '/v3/%s/volumes/%s/action' % (fake.PROJECT_ID, volume.id),
            use_admin_context=self.context.is_admin)
        req.environ['cinder.context'].is_admin = True
        req.headers = {'OpenStack-API-Version': 'volume 3.1'}
        req.api_version_request = api_version.APIVersionRequest('3.1')
        body = self._get_os_volume_upload_image()
        body['os-volume_upload_image']['visibility'] = 'public'
        body['os-volume_upload_image']['protected'] = True
        res_dict = self.controller._volume_upload_image(req,
                                                        volume.id,
                                                        body)

        expected['os-volume_upload_image'].update(visibility='public',
                                                  protected=True)
        self.assertDictMatch(expected, res_dict)

    @mock.patch.object(volume_api.API, "get_volume_image_metadata")
    @mock.patch.object(glance.GlanceImageService, "create")
    @mock.patch.object(volume_rpcapi.VolumeAPI, "copy_volume_to_image")
    def test_copy_volume_to_image_vhd(
            self, mock_copy_to_image, mock_create, mock_get_image_metadata):
        """Test create image from volume with vhd disk format"""
        volume, expected = self._create_volume_with_type()
        mock_get_image_metadata.return_value = {}
        mock_create.side_effect = self.fake_image_service_create
        req = fakes.HTTPRequest.blank(
            '/v2/fakeproject/volumes/%s/action' % volume.id)
        body = self._get_os_volume_upload_image()
        body['os-volume_upload_image']['force'] = True
        body['os-volume_upload_image']['container_format'] = 'bare'
        body['os-volume_upload_image']['disk_format'] = 'vhd'

        res_dict = self.controller._volume_upload_image(req, volume.id, body)

        self.assertDictMatch(expected, res_dict)
        vol_db = objects.Volume.get_by_id(self.context, volume.id)
        self.assertEqual('uploading', vol_db.status)
        self.assertEqual('available', vol_db.previous_status)

    @mock.patch.object(volume_api.API, "get_volume_image_metadata")
    @mock.patch.object(glance.GlanceImageService, "create")
    @mock.patch.object(volume_rpcapi.VolumeAPI, "copy_volume_to_image")
    def test_copy_volume_to_image_vhdx(
            self, mock_copy_to_image, mock_create, mock_get_image_metadata):
        """Test create image from volume with vhdx disk format"""
        volume, expected = self._create_volume_with_type()
        mock_get_image_metadata.return_value = {}
        mock_create.side_effect = self.fake_image_service_create
        req = fakes.HTTPRequest.blank(
            '/v2/fakeproject/volumes/%s/action' % volume.id)
        body = self._get_os_volume_upload_image()
        body['os-volume_upload_image']['force'] = True
        body['os-volume_upload_image']['container_format'] = 'bare'
        body['os-volume_upload_image']['disk_format'] = 'vhdx'

        res_dict = self.controller._volume_upload_image(req, volume.id, body)

        self.assertDictMatch(expected, res_dict)
        vol_db = objects.Volume.get_by_id(self.context, volume.id)
        self.assertEqual('uploading', vol_db.status)
        self.assertEqual('available', vol_db.previous_status)
