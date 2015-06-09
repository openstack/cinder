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

import json

import webob

from cinder.api.contrib import volume_encryption_metadata
from cinder import context
from cinder import db
from cinder import test
from cinder.tests.unit.api import fakes


def return_volume_type_encryption_metadata(context, volume_type_id):
    return stub_volume_type_encryption()


def stub_volume_type_encryption():
    values = {
        'cipher': 'cipher',
        'key_size': 256,
        'provider': 'nova.volume.encryptors.base.VolumeEncryptor',
        'volume_type_id': 'volume_type',
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
                       encryption_key_id='fake_key'):
        """Create a volume object."""
        volume = {
            'size': size,
            'user_id': 'fake',
            'project_id': 'fake',
            'status': status,
            'display_name': display_name,
            'display_description': display_description,
            'attach_status': 'detached',
            'availability_zone': availability_zone,
            'host': host,
            'encryption_key_id': encryption_key_id,
        }
        return db.volume_create(context, volume)['id']

    def setUp(self):
        super(VolumeEncryptionMetadataTest, self).setUp()
        self.controller = (volume_encryption_metadata.
                           VolumeEncryptionMetadataController())
        self.stubs.Set(db.sqlalchemy.api, 'volume_type_encryption_get',
                       return_volume_type_encryption_metadata)

        self.ctxt = context.RequestContext('fake', 'fake')
        self.volume_id = self._create_volume(self.ctxt)
        self.addCleanup(db.volume_destroy, self.ctxt.elevated(),
                        self.volume_id)

    def test_index(self):
        req = webob.Request.blank('/v2/fake/volumes/%s/encryption'
                                  % self.volume_id)
        res = req.get_response(fakes.wsgi_app(fake_auth_context=self.ctxt))
        self.assertEqual(200, res.status_code)
        res_dict = json.loads(res.body)

        expected = {
            "encryption_key_id": "fake_key",
            "control_location": "front-end",
            "cipher": "cipher",
            "provider": "nova.volume.encryptors.base.VolumeEncryptor",
            "key_size": 256,
        }
        self.assertEqual(expected, res_dict)

    def test_index_bad_tenant_id(self):
        req = webob.Request.blank('/v2/%s/volumes/%s/encryption'
                                  % ('bad-tenant-id', self.volume_id))
        res = req.get_response(fakes.wsgi_app(fake_auth_context=self.ctxt))
        self.assertEqual(400, res.status_code)

        res_dict = json.loads(res.body)
        expected = {'badRequest': {'code': 400,
                                   'message': 'Malformed request url'}}
        self.assertEqual(expected, res_dict)

    def test_index_bad_volume_id(self):
        bad_volume_id = 'bad_volume_id'
        req = webob.Request.blank('/v2/fake/volumes/%s/encryption'
                                  % bad_volume_id)
        res = req.get_response(fakes.wsgi_app(fake_auth_context=self.ctxt))
        self.assertEqual(404, res.status_code)

        res_dict = json.loads(res.body)
        expected = {'itemNotFound': {'code': 404,
                                     'message': 'VolumeNotFound: Volume '
                                                '%s could not be found.'
                                                % bad_volume_id}}
        self.assertEqual(expected, res_dict)

    def test_show_key(self):
        req = webob.Request.blank('/v2/fake/volumes/%s/encryption/'
                                  'encryption_key_id' % self.volume_id)
        res = req.get_response(fakes.wsgi_app(fake_auth_context=self.ctxt))
        self.assertEqual(200, res.status_code)

        self.assertEqual('fake_key', res.body)

    def test_show_control(self):
        req = webob.Request.blank('/v2/fake/volumes/%s/encryption/'
                                  'control_location' % self.volume_id)
        res = req.get_response(fakes.wsgi_app(fake_auth_context=self.ctxt))
        self.assertEqual(200, res.status_code)

        self.assertEqual('front-end', res.body)

    def test_show_provider(self):
        req = webob.Request.blank('/v2/fake/volumes/%s/encryption/'
                                  'provider' % self.volume_id)
        res = req.get_response(fakes.wsgi_app(fake_auth_context=self.ctxt))
        self.assertEqual(200, res.status_code)

        self.assertEqual('nova.volume.encryptors.base.VolumeEncryptor',
                         res.body)

    def test_show_bad_tenant_id(self):
        req = webob.Request.blank('/v2/%s/volumes/%s/encryption/'
                                  'encryption_key_id' % ('bad-tenant-id',
                                                         self.volume_id))
        res = req.get_response(fakes.wsgi_app(fake_auth_context=self.ctxt))
        self.assertEqual(400, res.status_code)

        res_dict = json.loads(res.body)
        expected = {'badRequest': {'code': 400,
                                   'message': 'Malformed request url'}}
        self.assertEqual(expected, res_dict)

    def test_show_bad_volume_id(self):
        bad_volume_id = 'bad_volume_id'
        req = webob.Request.blank('/v2/fake/volumes/%s/encryption/'
                                  'encryption_key_id' % bad_volume_id)
        res = req.get_response(fakes.wsgi_app(fake_auth_context=self.ctxt))
        self.assertEqual(404, res.status_code)

        res_dict = json.loads(res.body)
        expected = {'itemNotFound': {'code': 404,
                                     'message': 'VolumeNotFound: Volume '
                                                '%s could not be found.'
                                                % bad_volume_id}}
        self.assertEqual(expected, res_dict)

    def test_retrieve_key_admin(self):
        ctxt = context.RequestContext('fake', 'fake', is_admin=True)

        req = webob.Request.blank('/v2/fake/volumes/%s/encryption/'
                                  'encryption_key_id' % self.volume_id)
        res = req.get_response(fakes.wsgi_app(fake_auth_context=ctxt))
        self.assertEqual(200, res.status_code)

        self.assertEqual('fake_key', res.body)

    def test_show_volume_not_encrypted_type(self):
        self.stubs.Set(db.sqlalchemy.api, 'volume_type_encryption_get',
                       lambda *args, **kwargs: None)

        volume_id = self._create_volume(self.ctxt, encryption_key_id=None)
        self.addCleanup(db.volume_destroy, self.ctxt.elevated(), volume_id)

        req = webob.Request.blank('/v2/fake/volumes/%s/encryption/'
                                  'encryption_key_id' % volume_id)
        res = req.get_response(fakes.wsgi_app(fake_auth_context=self.ctxt))
        self.assertEqual(200, res.status_code)
        self.assertEqual(0, len(res.body))

    def test_index_volume_not_encrypted_type(self):
        self.stubs.Set(db.sqlalchemy.api, 'volume_type_encryption_get',
                       lambda *args, **kwargs: None)

        volume_id = self._create_volume(self.ctxt, encryption_key_id=None)
        self.addCleanup(db.volume_destroy, self.ctxt.elevated(), volume_id)

        req = webob.Request.blank('/v2/fake/volumes/%s/encryption'
                                  % volume_id)
        res = req.get_response(fakes.wsgi_app(fake_auth_context=self.ctxt))

        self.assertEqual(200, res.status_code)
        res_dict = json.loads(res.body)

        expected = {
            'encryption_key_id': None
        }
        self.assertEqual(expected, res_dict)
