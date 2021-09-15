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

import ddt

from cinder.api.contrib import volume_type_encryption as vol_type_enc
from cinder.api import microversions as mv
from cinder.api.v3 import types
from cinder import db
from cinder.policies import volume_type as type_policy
from cinder.tests.unit.api import fakes as fake_api
from cinder.tests.unit import fake_constants
from cinder.tests.unit.policies import base
from cinder.tests.unit.policies import test_base
from cinder.tests.unit import utils as test_utils


@ddt.ddt
class VolumeTypePolicyTest(base.BasePolicyTest):
    """Verify default policy settings for the types API"""

    # legacy: everyone can make these calls
    authorized_readers = [
        'legacy_admin',
        'legacy_owner',
        'system_admin',
        'project_admin',
        'project_member',
        'project_reader',
        'project_foo',
        'system_member',
        'system_reader',
        'system_foo',
        'other_project_member',
        'other_project_reader',
    ]

    unauthorized_readers = []

    unauthorized_exceptions = []

    # Basic policy test is without enforcing scope (which cinder doesn't
    # yet support) and deprecated rules enabled.
    def setUp(self, enforce_scope=False, enforce_new_defaults=False,
              *args, **kwargs):
        super().setUp(enforce_scope, enforce_new_defaults, *args, **kwargs)
        self.controller = types.VolumeTypesController()
        self.api_path = '/v3/%s/types' % (self.project_id)
        self.api_version = mv.BASE_VERSION

    @ddt.data(*base.all_users)
    def test_type_get_all_policy(self, user_id):
        rule_name = type_policy.GET_ALL_POLICY
        url = self.api_path
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)
        self.common_policy_check(user_id,
                                 self.authorized_readers,
                                 self.unauthorized_readers,
                                 self.unauthorized_exceptions,
                                 rule_name,
                                 self.controller.index,
                                 req)

    @ddt.data(*base.all_users)
    def test_type_get_policy(self, user_id):
        vol_type = test_utils.create_volume_type(self.project_admin_context,
                                                 testcase_instance=self,
                                                 name='fake_vol_type')
        rule_name = type_policy.GET_POLICY
        url = '%s/%s' % (self.api_path, vol_type.id)
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)
        self.common_policy_check(user_id,
                                 self.authorized_readers,
                                 self.unauthorized_readers,
                                 self.unauthorized_exceptions,
                                 rule_name,
                                 self.controller.show,
                                 req,
                                 id=vol_type.id)

    @ddt.data(*base.all_users)
    def test_extra_spec_policy(self, user_id):
        vol_type = test_utils.create_volume_type(
            self.project_admin_context,
            testcase_instance=self,
            name='fake_vol_type',
            extra_specs={'multiattach': '<is> True'})
        rule_name = type_policy.EXTRA_SPEC_POLICY
        url = '%s/%s' % (self.api_path, vol_type.id)
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)

        # Relax the GET_POLICY in order to get past that check.
        self.policy.set_rules({type_policy.GET_POLICY: ""},
                              overwrite=False)

        # With the relaxed GET_POLICY, all users are authorized because
        # failing the policy check is not fatal.
        authorized_readers = [user_id]
        unauthorized_readers = []

        response = self.common_policy_check(user_id,
                                            authorized_readers,
                                            unauthorized_readers,
                                            self.unauthorized_exceptions,
                                            rule_name,
                                            self.controller.show,
                                            req,
                                            id=vol_type.id)

        # Check whether the response should contain extra_specs. The logic
        # is a little unusual:
        #   - The new rule is SYSTEM_READER_OR_PROJECT_READER (i.e. users
        #     with the 'reader' role)
        #   - The deprecated rule is RULE_ADMIN_API (i.e. users with the
        #     'admin' role)
        context = self.create_context(user_id)
        if 'reader' in context.roles or 'admin' in context.roles:
            self.assertIn('extra_specs', response['volume_type'])
        else:
            self.assertNotIn('extra_specs', response['volume_type'])


class VolumeTypePolicySecureRbacTest(VolumeTypePolicyTest):

    authorized_readers = [
        'legacy_admin',
        'system_admin',
        'project_admin',
        'project_member',
        'project_reader',
        'system_member',
        'system_reader',
        'other_project_member',
        'other_project_reader',
    ]

    unauthorized_readers = [
        'legacy_owner',
        'project_foo',
        'system_foo',
    ]

    unauthorized_exceptions = []

    def setUp(self, *args, **kwargs):
        # Test secure RBAC by disabling deprecated policy rules (scope
        # is still not enabled).
        super().setUp(enforce_scope=False, enforce_new_defaults=True,
                      *args, **kwargs)


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
