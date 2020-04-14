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

import http.client
from unittest import mock

from cinder.api.contrib import volume_type_encryption as vol_type_enc
from cinder import db
from cinder.tests.unit import fake_constants
from cinder.tests.unit.policies import test_base


class VolumeTypePolicyTests(test_base.CinderPolicyTests):
    """Verify default policy settings for the types API"""

    # TODO: add some tests!
    pass


class VolumeTypeEncryptionTypePolicyTests(test_base.CinderPolicyTests):
    """Verify default policy settings for encryption types in the types API"""
    def setUp(self):
        super(VolumeTypeEncryptionTypePolicyTests, self).setUp()
        self.volume_type = self._create_fake_type(self.admin_context)

    def test_admin_can_create_volume_type_encryption_type(self):
        admin_context = self.admin_context
        path = '/v3/%(project_id)s/types/%(type_id)s/encryption' % {
            'project_id': admin_context.project_id,
            'type_id': self.volume_type.id
        }
        body = {"encryption": {"key_size": 128,
                               "provider": "luks",
                               "control_location": "front-end",
                               "cipher": "aes-xts-plain64"}}
        response = self._get_request_response(admin_context, path, 'POST',
                                              body=body)
        self.assertEqual(http.client.OK, response.status_int)

    def test_nonadmin_cannot_create_volume_type_encryption_type(self):
        self.assertTrue(self.volume_type.is_public)
        path = '/v3/%(project_id)s/types/%(type_id)s/encryption' % {
            'project_id': self.user_context.project_id,
            'type_id': self.volume_type.id
        }
        body = {"encryption": {"key_size": 128,
                               "provider": "luks",
                               "control_location": "front-end",
                               "cipher": "aes-xts-plain64"}}
        response = self._get_request_response(self.user_context, path, 'POST',
                                              body=body)
        self.assertEqual(http.client.FORBIDDEN, response.status_int)

    @mock.patch.object(vol_type_enc.VolumeTypeEncryptionController,
                       '_get_volume_type_encryption')
    def test_admin_can_show_volume_type_encryption_type(self, mock_get_enc):
        mock_get_enc.return_value = {
            'cipher': 'aes-xts-plain64',
            'control_location': 'front-end',
            'encryption_id': fake_constants.ENCRYPTION_TYPE_ID,
            'key_size': 128,
            'provider': 'luks',
            'volume_type_id': self.volume_type.id}
        admin_context = self.admin_context
        path = '/v3/%(project_id)s/types/%(type_id)s/encryption' % {
            'project_id': admin_context.project_id,
            'type_id': self.volume_type.id
        }
        response = self._get_request_response(admin_context, path, 'GET')
        self.assertEqual(http.client.OK, response.status_int)

    def test_nonadmin_cannot_show_volume_type_encryption_type(self):
        self.assertTrue(self.volume_type.is_public)
        path = '/v3/%(project_id)s/types/%(type_id)s/encryption' % {
            'project_id': self.user_context.project_id,
            'type_id': self.volume_type.id
        }
        response = self._get_request_response(self.user_context, path, 'GET')
        self.assertEqual(http.client.FORBIDDEN, response.status_int)

    @mock.patch.object(vol_type_enc.VolumeTypeEncryptionController,
                       '_get_volume_type_encryption')
    def test_admin_can_show_volume_type_encryption_spec_item(
            self, mock_get_enc):
        enc_specs = {
            'cipher': 'aes-xts-plain64',
            'control_location': 'front-end',
            'encryption_id': fake_constants.ENCRYPTION_TYPE_ID,
            'key_size': 128,
            'provider': 'foobar',
            'volume_type_id': self.volume_type.id}
        mock_get_enc.return_value = enc_specs
        admin_context = self.admin_context
        path = '/v3/%(project_id)s/types/%(type_id)s/encryption/%(item)s' % {
            'project_id': admin_context.project_id,
            'type_id': self.volume_type.id,
            'item': 'provider'
        }
        response = self._get_request_response(admin_context, path, 'GET')
        self.assertEqual(http.client.OK, response.status_int)

    def test_nonadmin_cannot_show_volume_type_encryption_spec_item(self):
        self.assertTrue(self.volume_type.is_public)
        path = '/v3/%(project_id)s/types/%(type_id)s/encryption/%(item)s' % {
            'project_id': self.user_context.project_id,
            'type_id': self.volume_type.id,
            'item': 'control_location'
        }
        response = self._get_request_response(self.user_context, path, 'GET')
        self.assertEqual(http.client.FORBIDDEN, response.status_int)

    @mock.patch.object(db, 'volume_type_encryption_delete', return_value=None)
    def test_admin_can_delete_volume_type_encryption_type(
            self, mock_db_delete):
        admin_context = self.admin_context
        path = '/v3/%(project_id)s/types/%(type_id)s/encryption/%(enc_id)s' % {
            'project_id': admin_context.project_id,
            'type_id': self.volume_type.id,
            'enc_id': fake_constants.ENCRYPTION_TYPE_ID
        }
        response = self._get_request_response(admin_context, path, 'DELETE')
        self.assertEqual(http.client.ACCEPTED, response.status_int)

    def test_nonadmin_cannot_delete_volume_type_encryption_type(self):
        self.assertTrue(self.volume_type.is_public)
        path = '/v3/%(project_id)s/types/%(type_id)s/encryption/%(enc_id)s' % {
            'project_id': self.user_context.project_id,
            'type_id': self.volume_type.id,
            'enc_id': fake_constants.ENCRYPTION_TYPE_ID
        }
        response = self._get_request_response(self.user_context, path,
                                              'DELETE')
        self.assertEqual(http.client.FORBIDDEN, response.status_int)

    @mock.patch.object(db, 'volume_type_encryption_update', return_value=None)
    def test_admin_can_update_volume_type_encryption_type(
            self, mock_db_update):
        admin_context = self.admin_context
        req_body = {"encryption": {"key_size": 64,
                                   "control_location": "back-end"}}
        path = '/v3/%(project_id)s/types/%(type_id)s/encryption/%(enc_id)s' % {
            'project_id': admin_context.project_id,
            'type_id': self.volume_type.id,
            'enc_id': fake_constants.ENCRYPTION_TYPE_ID
        }
        response = self._get_request_response(admin_context, path, 'PUT',
                                              body=req_body)
        self.assertEqual(http.client.OK, response.status_int)

    def test_nonadmin_cannot_update_volume_type_encryption_type(self):
        self.assertTrue(self.volume_type.is_public)
        req_body = {"encryption": {"key_size": 64,
                                   "control_location": "back-end"}}
        path = '/v3/%(project_id)s/types/%(type_id)s/encryption/%(enc_id)s' % {
            'project_id': self.user_context.project_id,
            'type_id': self.volume_type.id,
            'enc_id': fake_constants.ENCRYPTION_TYPE_ID
        }
        response = self._get_request_response(self.user_context, path, 'PUT',
                                              body=req_body)
        self.assertEqual(http.client.FORBIDDEN, response.status_int)
