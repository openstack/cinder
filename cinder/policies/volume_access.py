# Copyright (c) 2017 Huawei Technologies Co., Ltd.
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

from oslo_policy import policy

from cinder.policies import base


ADD_PROJECT_POLICY = "volume_extension:volume_type_access:addProjectAccess"
REMOVE_PROJECT_POLICY = \
    "volume_extension:volume_type_access:removeProjectAccess"
TYPE_ACCESS_POLICY = "volume_extension:volume_type_access"

volume_access_policies = [
    policy.DocumentedRuleDefault(
        name=TYPE_ACCESS_POLICY,
        check_str=base.RULE_ADMIN_OR_OWNER,
        description="Volume type access related APIs.",
        operations=[
            {
                'method': 'GET',
                'path': '/types'
            },
            {
                'method': 'GET',
                'path': '/types/detail'
            },
            {
                'method': 'GET',
                'path': '/types/{type_id}'
            },
            {
                'method': 'POST',
                'path': '/types'
            }
        ]),
    policy.DocumentedRuleDefault(
        name=ADD_PROJECT_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="Add volume type access for project.",
        operations=[
            {
                'method': 'POST',
                'path': '/types/{type_id}/action (addProjectAccess)'
            }
        ]),
    policy.DocumentedRuleDefault(
        name=REMOVE_PROJECT_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="Remove volume type access for project.",
        operations=[
            {
                'method': 'POST',
                'path': '/types/{type_id}/action (removeProjectAccess)'
            }
        ]),
]


def list_rules():
    return volume_access_policies
