# Copyright 2021 Red Hat, Inc.
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

from cinder.api import microversions as mv
from cinder.api.v3 import group_types
from cinder.policies import group_types as group_type_policies
from cinder.tests.unit.api import fakes as fake_api
from cinder.tests.unit.policies import base


@ddt.ddt
class GroupTypesPolicyTest(base.BasePolicyTest):

    authorized_admins = [
        'system_admin',
        'legacy_admin',
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

    def setUp(self, enforce_scope=False, enforce_new_defaults=False, *args,
              **kwargs):
        super().setUp(enforce_scope, enforce_new_defaults, *args, **kwargs)
        self.controller = group_types.GroupTypesController()
        self.api_path = '/v3/%s/group_types' % (self.project_id)
        self.api_version = mv.GROUP_TYPE

    @ddt.data(*base.all_users)
    def test_create_group_type_policy(self, user_id):
        rule_name = group_type_policies.CREATE_POLICY
        url = self.api_path
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)
        req.method = 'POST'
        body = {"group_type": {"name": "test-group-type"}}
        unauthorized_exceptions = []
        self.common_policy_check(user_id, self.authorized_admins,
                                 self.unauthorized_admins,
                                 unauthorized_exceptions,
                                 rule_name, self.controller.create, req,
                                 body=body)
