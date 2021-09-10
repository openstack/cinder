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

from unittest import mock

import ddt

from cinder.api.contrib import used_limits
from cinder.api import microversions as mv
from cinder.api.v3 import limits
from cinder.policies import limits as policy
from cinder.tests.unit.api import fakes as fake_api
from cinder.tests.unit.policies import base


@ddt.ddt
class LimitsPolicyTest(base.BasePolicyTest):
    authorized_readers = [
        'legacy_admin',
        'legacy_owner',
        'system_admin',
        'project_admin',
        'project_member',
        'project_reader',
        'project_foo',
        # The other_* users are allowed because we don't have any check
        # mechanism in the code to validate the project_id, which is
        # validated at the WSGI layer.
        'other_project_member',
        'other_project_reader',
    ]

    unauthorized_readers = [
        'system_member',
        'system_reader',
        'system_foo',
    ]

    unauthorized_exceptions = []

    # Basic policy test is without enforcing scope (which cinder doesn't
    # yet support) and deprecated rules enabled.
    def setUp(self, enforce_scope=False, enforce_new_defaults=False,
              *args, **kwargs):
        super().setUp(enforce_scope, enforce_new_defaults, *args, **kwargs)
        self.limits_controller = limits.LimitsController()
        self.used_limits_controller = used_limits.UsedLimitsController()
        self.api_path = '/v3/%s/limits' % (self.project_id)
        self.api_version = mv.BASE_VERSION

    @ddt.data(*base.all_users)
    def test_extend_limit_attribute_policy(self, user_id):
        rule_name = policy.EXTEND_LIMIT_ATTRIBUTE_POLICY
        url = self.api_path

        # Create a resp_obj (necessary for the UsedLimitsController) by
        # requesting the limits via the LimitsController, which actually
        # generates the response.
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)
        req.environ['cinder.context'] = self.project_admin_context
        limits = self.limits_controller.index(req)['limits']
        resp_obj = mock.MagicMock(obj={'limits': limits})

        # This proves the LimitsController's response doesn't include any
        # "used" entries (e.g. totalVolumesUsed).
        self.assertNotIn('totalVolumesUsed', limits['absolute'].keys())

        # Now hit the UsedLimitsController and see if it adds "used"
        # limits to the resp_obj.
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)
        self.common_policy_check(user_id, self.authorized_readers,
                                 self.unauthorized_readers,
                                 self.unauthorized_exceptions,
                                 rule_name,
                                 self.used_limits_controller.index,
                                 req, resp_obj=resp_obj, fatal=False)

        if user_id in self.authorized_readers:
            self.assertIn('totalVolumesUsed', limits['absolute'].keys())
        else:
            self.assertNotIn('totalVolumesUsed', limits['absolute'].keys())


class LimitsPolicySecureRbacTest(LimitsPolicyTest):
    authorized_readers = [
        'legacy_admin',
        'system_admin',
        'project_admin',
        'project_member',
        'project_reader',
        'other_project_member',
        'other_project_reader',
    ]

    unauthorized_readers = [
        'legacy_owner',
        'system_member',
        'system_reader',
        'system_foo',
        'project_foo',
    ]

    def setUp(self, *args, **kwargs):
        # Test secure RBAC by disabling deprecated policy rules (scope
        # is still not enabled).
        super().setUp(enforce_scope=False, enforce_new_defaults=True,
                      *args, **kwargs)
