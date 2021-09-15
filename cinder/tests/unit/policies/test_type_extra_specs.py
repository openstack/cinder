# Copyright (c) 2021 Red Hat, Inc.
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

import ddt

from cinder.api.contrib import types_extra_specs
from cinder.api import microversions as mv
from cinder.api.v3 import types
from cinder.policies import type_extra_specs as policy
from cinder.policies import volume_type as type_policy
from cinder.tests.unit.api import fakes as fake_api
from cinder.tests.unit.policies import base
from cinder.tests.unit import utils as test_utils


@ddt.ddt
class TypeExtraSpecsPolicyTest(base.BasePolicyTest):
    """Verify extra specs policy settings for the types API"""

    # Deprecated check_str="" allows anyone to read extra specs
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

    unauthorized_readers = [
    ]

    authorized_admins = [
        'legacy_admin',
        'system_admin',
        'project_admin',
    ]

    unauthorized_admins = [
        'legacy_owner',
        'system_member',
        'system_reader',
        'system_foo',
        'project_member',
        'project_reader',
        'project_foo',
        'other_project_member',
        'other_project_reader',
    ]

    unauthorized_exceptions = []

    # Basic policy test is without enforcing scope (which cinder doesn't
    # yet support) and deprecated rules enabled.
    def setUp(self, enforce_scope=False, enforce_new_defaults=False,
              *args, **kwargs):
        super().setUp(enforce_scope, enforce_new_defaults, *args, **kwargs)
        self.controller = types_extra_specs.VolumeTypeExtraSpecsController()
        self.api_path = '/v3/%s/types' % (self.project_id)
        self.api_version = mv.BASE_VERSION

    @ddt.data(*base.all_users)
    def test_get_all_policy(self, user_id):
        vol_type = test_utils.create_volume_type(self.project_admin_context,
                                                 testcase_instance=self,
                                                 name='fake_vol_type',
                                                 extra_specs={'foo': 'bar'})
        rule_name = policy.GET_ALL_POLICY
        url = '%s/%s/extra_specs' % (self.api_path, vol_type.id)
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)
        self.common_policy_check(user_id,
                                 self.authorized_readers,
                                 self.unauthorized_readers,
                                 self.unauthorized_exceptions,
                                 rule_name,
                                 self.controller.index,
                                 req,
                                 type_id=vol_type.id)

    @ddt.data(*base.all_users)
    def test_get_policy(self, user_id):
        vol_type = test_utils.create_volume_type(self.project_admin_context,
                                                 testcase_instance=self,
                                                 name='fake_vol_type',
                                                 extra_specs={'foo': 'bar'})
        rule_name = policy.GET_POLICY
        url = '%s/%s/extra_specs/foo' % (self.api_path, vol_type.id)
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)

        # Relax the READ_SENSITIVE_POLICY policy so that any user is able
        # to "see" the spec.
        self.policy.set_rules({policy.READ_SENSITIVE_POLICY: ""},
                              overwrite=False)

        self.common_policy_check(user_id,
                                 self.authorized_readers,
                                 self.unauthorized_readers,
                                 self.unauthorized_exceptions,
                                 rule_name,
                                 self.controller.show,
                                 req,
                                 type_id=vol_type.id,
                                 id='foo')

    @ddt.data(*base.all_users)
    def test_create_policy(self, user_id):
        vol_type = test_utils.create_volume_type(self.project_admin_context,
                                                 testcase_instance=self,
                                                 name='fake_vol_type')
        rule_name = policy.CREATE_POLICY
        url = '%s/%s/extra_specs' % (self.api_path, vol_type.id)
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)
        req.method = 'POST'
        body = {
            "extra_specs": {
                "foo": "bar",
            }
        }

        self.common_policy_check(user_id,
                                 self.authorized_admins,
                                 self.unauthorized_admins,
                                 self.unauthorized_exceptions,
                                 rule_name,
                                 self.controller.create,
                                 req,
                                 type_id=vol_type.id,
                                 body=body)

    @ddt.data(*base.all_users)
    def test_update_policy(self, user_id):
        vol_type = test_utils.create_volume_type(self.project_admin_context,
                                                 testcase_instance=self,
                                                 name='fake_vol_type',
                                                 extra_specs={'foo': 'bar'})
        rule_name = policy.UPDATE_POLICY
        url = '%s/%s/extra_specs/foo' % (self.api_path, vol_type.id)
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)
        req.method = 'PUT'
        body = {"foo": "zap"}

        self.common_policy_check(user_id,
                                 self.authorized_admins,
                                 self.unauthorized_admins,
                                 self.unauthorized_exceptions,
                                 rule_name,
                                 self.controller.update,
                                 req,
                                 type_id=vol_type.id,
                                 id='foo',
                                 body=body)

    @ddt.data(*base.all_users)
    def test_delete_policy(self, user_id):
        vol_type = test_utils.create_volume_type(self.project_admin_context,
                                                 testcase_instance=self,
                                                 name='fake_vol_type',
                                                 extra_specs={'foo': 'bar'})
        rule_name = policy.DELETE_POLICY
        url = '%s/%s/extra_specs/foo' % (self.api_path, vol_type.id)
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)
        req.method = 'DELETE'

        self.common_policy_check(user_id,
                                 self.authorized_admins,
                                 self.unauthorized_admins,
                                 self.unauthorized_exceptions,
                                 rule_name,
                                 self.controller.delete,
                                 req,
                                 type_id=vol_type.id,
                                 id='foo')

    @ddt.data(*base.all_users)
    def test_read_sensitive_policy(self, user_id):
        # The 'multiattach' extra spec is user visible, and the
        # 'sensitive' extra spec should not be user visible.
        extra_specs = {
            'multiattach': '<is> True',
            'sensitive': 'secret',
        }
        vol_type = test_utils.create_volume_type(self.project_admin_context,
                                                 testcase_instance=self,
                                                 name='fake_vol_type',
                                                 extra_specs=extra_specs)
        rule_name = policy.READ_SENSITIVE_POLICY
        url = '%s/%s' % (self.api_path, vol_type.id)
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)

        # Relax these policies in order to get past those checks.
        self.policy.set_rules({type_policy.GET_POLICY: ""},
                              overwrite=False)
        self.policy.set_rules({type_policy.EXTRA_SPEC_POLICY: ""},
                              overwrite=False)

        # With the relaxed policies, all users are authorized because
        # failing the READ_SENSITIVE_POLICY policy check is not fatal.
        authorized_users = [user_id]
        unauthorized_users = []

        controller = types.VolumeTypesController()
        response = self.common_policy_check(user_id,
                                            authorized_users,
                                            unauthorized_users,
                                            self.unauthorized_exceptions,
                                            rule_name,
                                            controller.show,
                                            req,
                                            id=vol_type.id)

        if user_id in self.authorized_admins:
            # Admins should see all extra specs
            expected = extra_specs
        else:
            # Non-admins should only see user visible extra specs
            expected = {'multiattach': '<is> True'}
        self.assertDictEqual(expected, response['volume_type']['extra_specs'])


class TypeExtraSpecsPolicySecureRbacTest(TypeExtraSpecsPolicyTest):
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
        # These are unauthorized because they don't have the reader role
        'legacy_owner',
        'project_foo',
        'system_foo',
    ]

    # NOTE(Xena): The authorized_admins and unauthorized_admins are the same
    # as the TypeExtraSpecsPolicyTest. This is because in Xena the "admin only"
    # rules are the legacy RULE_ADMIN_API. This will change in Yoga, when
    # RULE_ADMIN_API will be deprecated in favor of the SYSTEM_ADMIN rule that
    # is scope based.
    authorized_admins = [
        'legacy_admin',
        'system_admin',
        'project_admin',
    ]

    unauthorized_admins = [
        'legacy_owner',
        'system_member',
        'system_reader',
        'system_foo',
        'project_member',
        'project_reader',
        'project_foo',
        'other_project_member',
        'other_project_reader',
    ]

    def setUp(self, *args, **kwargs):
        # Test secure RBAC by disabling deprecated policy rules (scope
        # is still not enabled).
        super().setUp(enforce_scope=False, enforce_new_defaults=True,
                      *args, **kwargs)
