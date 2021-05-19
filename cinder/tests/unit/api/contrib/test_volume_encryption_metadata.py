# Copyright (c) 2013 The Johns Hopkins University/Applied Physics Laboratory
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

from http import HTTPStatus

from oslo_serialization import jsonutils
import webob

from cinder.api.contrib import volume_encryption_metadata
from cinder import context
from cinder import db
from cinder.objects import fields
from cinder.tests.unit.api import fakes
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import test


def return_volume_type_encryption_metadata(context, volume_type_id):
    return fake_volume_type_encryption()


def fake_volume_type_encryption():
    values = {
        'cipher': 'cipher',
        'key_size': 256,
        'provider': 'nova.volume.encryptors.base.VolumeEncryptor',
        'volume_type_id': fake.VOLUME_TYPE_ID,
        'control_location': 'front-end',
    }
    return values


class VolumeEncryptionMetadataTest(test.TestCase):
    @staticmethod
    def _create_volume(context,
                       display_name='test_volume',
                       display_description='this is a test volume',
                       status='creating',
                       availability_zone='fake_az',
                       host='fake_host',
                       size=1,
                       encryption_key_id=fake.ENCRYPTION_KEY_ID):
        """Create a volume object."""
        volume = {
            'size': size,
            'user_id': fake.USER_ID,
            'project_id': fake.PROJECT_ID,
            'status': status,
            'display_name': display_name,
            'display_description': display_description,
            'attach_status': fields.VolumeAttachStatus.DETACHED,
            'availability_zone': availability_zone,
            'host': host,
            'encryption_key_id': encryption_key_id,
            'volume_type_id': fake.VOLUME_TYPE_ID
        }
        return db.volume_create(context, volume)['id']

    def setUp(self):
        super(VolumeEncryptionMetadataTest, self).setUp()
        self.controller = (volume_encryption_metadata.
                           VolumeEncryptionMetadataController())
        self.mock_object(db.sqlalchemy.api, 'volume_type_encryption_get',
                         return_volume_type_encryption_metadata)

        self.ctxt = context.RequestContext(fake.USER_ID, fake.PROJECT_ID)
        self.volume_id = self._create_volume(self.ctxt)
        self.addCleanup(db.volume_destroy, self.ctxt.elevated(),
                        self.volume_id)

    def test_index(self):
        req = webob.Request.blank('/v3/%s/volumes/%s/encryption' % (
                                  fake.PROJECT_ID, self.volume_id))
        res = req.get_response(fakes.wsgi_app(fake_auth_context=self.ctxt))
        self.assertEqual(HTTPStatus.OK, res.status_code)
        res_dict = jsonutils.loads(res.body)

        expected = {
            "encryption_key_id": fake.ENCRYPTION_KEY_ID,
            "control_location": "front-end",
            "cipher": "cipher",
            "provider": "nova.volume.encryptors.base.VolumeEncryptor",
            "key_size": 256,
        }
        self.assertEqual(expected, res_dict)

    def test_index_bad_tenant_id(self):
        req = webob.Request.blank('/v3/%s/volumes/%s/encryption' % (
                                  fake.WILL_NOT_BE_FOUND_ID, self.volume_id))
        res = req.get_response(fakes.wsgi_app(fake_auth_context=self.ctxt))
        self.assertEqual(HTTPStatus.BAD_REQUEST, res.status_code)

        res_dict = jsonutils.loads(res.body)
        expected = {'badRequest': {'code': HTTPStatus.BAD_REQUEST,
                                   'message': 'Malformed request url'}}
        self.assertEqual(expected, res_dict)

    def test_index_bad_volume_id(self):
        bad_volume_id = fake.WILL_NOT_BE_FOUND_ID
        req = webob.Request.blank('/v3/%s/volumes/%s/encryption' % (
                                  fake.PROJECT_ID, bad_volume_id))
        res = req.get_response(fakes.wsgi_app(fake_auth_context=self.ctxt))
        self.assertEqual(HTTPStatus.NOT_FOUND, res.status_code)

        res_dict = jsonutils.loads(res.body)
        expected = {'itemNotFound': {'code': HTTPStatus.NOT_FOUND,
                                     'message': 'Volume %s could not be found.'
                                                % bad_volume_id}}
        self.assertEqual(expected, res_dict)

    def test_show_key(self):
        req = webob.Request.blank('/v3/%s/volumes/%s/encryption/'
                                  'encryption_key_id' % (
                                      fake.PROJECT_ID, self.volume_id))
        res = req.get_response(fakes.wsgi_app(fake_auth_context=self.ctxt))
        self.assertEqual(HTTPStatus.OK, res.status_code)

        self.assertEqual(fake.ENCRYPTION_KEY_ID, res.body.decode())

    def test_show_control(self):
        req = webob.Request.blank('/v3/%s/volumes/%s/encryption/'
                                  'control_location' % (
                                      fake.PROJECT_ID, self.volume_id))
        res = req.get_response(fakes.wsgi_app(fake_auth_context=self.ctxt))
        self.assertEqual(HTTPStatus.OK, res.status_code)

        self.assertEqual(b'front-end', res.body)

    def test_show_provider(self):
        req = webob.Request.blank('/v3/%s/volumes/%s/encryption/'
                                  'provider' % (
                                      fake.PROJECT_ID, self.volume_id))
        res = req.get_response(fakes.wsgi_app(fake_auth_context=self.ctxt))
        self.assertEqual(HTTPStatus.OK, res.status_code)

        self.assertEqual(b'nova.volume.encryptors.base.VolumeEncryptor',
                         res.body)

    def test_show_bad_tenant_id(self):
        req = webob.Request.blank('/v3/%s/volumes/%s/encryption/'
                                  'encryption_key_id' %
                                  (fake.WILL_NOT_BE_FOUND_ID,
                                   self.volume_id))
        res = req.get_response(fakes.wsgi_app(fake_auth_context=self.ctxt))
        self.assertEqual(HTTPStatus.BAD_REQUEST, res.status_code)

        res_dict = jsonutils.loads(res.body)
        expected = {'badRequest': {'code': HTTPStatus.BAD_REQUEST,
                                   'message': 'Malformed request url'}}
        self.assertEqual(expected, res_dict)

    def test_show_bad_volume_id(self):
        bad_volume_id = fake.WILL_NOT_BE_FOUND_ID
        req = webob.Request.blank('/v3/%s/volumes/%s/encryption/'
                                  'encryption_key_id' % (
                                      fake.PROJECT_ID, bad_volume_id))
        res = req.get_response(fakes.wsgi_app(fake_auth_context=self.ctxt))
        self.assertEqual(HTTPStatus.NOT_FOUND, res.status_code)

        res_dict = jsonutils.loads(res.body)
        expected = {'itemNotFound': {'code': HTTPStatus.NOT_FOUND,
                                     'message': 'Volume %s could not be found.'
                                                % bad_volume_id}}
        self.assertEqual(expected, res_dict)

    def test_retrieve_key_admin(self):
        ctxt = context.RequestContext(fake.USER_ID, fake.PROJECT_ID,
                                      is_admin=True)

        req = webob.Request.blank('/v3/%s/volumes/%s/encryption/'
                                  'encryption_key_id' % (
                                      fake.PROJECT_ID, self.volume_id))
        res = req.get_response(fakes.wsgi_app(fake_auth_context=ctxt))
        self.assertEqual(HTTPStatus.OK, res.status_code)

        self.assertEqual(fake.ENCRYPTION_KEY_ID, res.body.decode())

    def test_show_volume_not_encrypted_type(self):
        self.mock_object(db.sqlalchemy.api, 'volume_type_encryption_get',
                         return_value=None)

        volume_id = self._create_volume(self.ctxt, encryption_key_id=None)
        self.addCleanup(db.volume_destroy, self.ctxt.elevated(), volume_id)

        req = webob.Request.blank('/v3/%s/volumes/%s/encryption/'
                                  'encryption_key_id' % (
                                      fake.PROJECT_ID, volume_id))
        res = req.get_response(fakes.wsgi_app(fake_auth_context=self.ctxt))
        self.assertEqual(HTTPStatus.OK, res.status_code)
        self.assertEqual(0, len(res.body))

    def test_index_volume_not_encrypted_type(self):
        self.mock_object(db.sqlalchemy.api, 'volume_type_encryption_get',
                         return_value=None)

        volume_id = self._create_volume(self.ctxt, encryption_key_id=None)
        self.addCleanup(db.volume_destroy, self.ctxt.elevated(), volume_id)

        req = webob.Request.blank('/v3/%s/volumes/%s/encryption' % (
            fake.PROJECT_ID, volume_id))
        res = req.get_response(fakes.wsgi_app(fake_auth_context=self.ctxt))

        self.assertEqual(HTTPStatus.OK, res.status_code)
        res_dict = jsonutils.loads(res.body)

        expected = {
            'encryption_key_id': None
        }
        self.assertEqual(expected, res_dict)
