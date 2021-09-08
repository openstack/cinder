# Copyright 2021 Red Hat, Inc.
# All Rights Reserved.
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

from cinder.api.contrib import quota_classes
from cinder.api import microversions as mv
from cinder.policies import quota_class as policy
from cinder.tests.unit.api import fakes as fake_api
from cinder.tests.unit.policies import base


@ddt.ddt
class QuotaClassPolicyTest(base.BasePolicyTest):
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
        self.controller = quota_classes.QuotaClassSetsController()
        self.api_path = '/v3/os-quota-class-sets'
        self.api_version = mv.BASE_VERSION

    @ddt.data(*base.all_users)
    def test_get_policy(self, user_id):
        rule_name = policy.GET_POLICY
        req = fake_api.HTTPRequest.blank(self.api_path,
                                         version=self.api_version)

        self.common_policy_check(user_id, self.authorized_admins,
                                 self.unauthorized_admins,
                                 self.unauthorized_exceptions,
                                 rule_name, self.controller.show,
                                 req, id='my_class')

    @ddt.data(*base.all_users)
    def test_update_policy(self, user_id):
        rule_name = policy.UPDATE_POLICY
        req = fake_api.HTTPRequest.blank(self.api_path,
                                         version=self.api_version)
        req.method = 'PUT'
        body = {
            "quota_class_set": {
                "groups": 11,
                "volumes": 5,
                "backups": 4
            }
        }

        self.common_policy_check(user_id, self.authorized_admins,
                                 self.unauthorized_admins,
                                 self.unauthorized_exceptions,
                                 rule_name, self.controller.update,
                                 req, id='my_class', body=body)


class QuotaClassPolicySecureRbacTest(QuotaClassPolicyTest):
    # NOTE(Xena): The authorized_admins and unauthorized_admins are the same
    # as the QuotasPolicyTest's. This is because in Xena the "admin only"
    # rules are the legacy RULE_ADMIN_API. This will change in Yoga, when
    # RULE_ADMIN_API will be deprecated in favor of the SYSTEM_ADMIN rule that
    # is scope based.

    def setUp(self, *args, **kwargs):
        # Test secure RBAC by disabling deprecated policy rules (scope
        # is still not enabled).
        super().setUp(enforce_scope=False, enforce_new_defaults=True,
                      *args, **kwargs)
