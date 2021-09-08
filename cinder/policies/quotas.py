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


SHOW_POLICY = 'volume_extension:quotas:show'
UPDATE_POLICY = 'volume_extension:quotas:update'
DELETE_POLICY = 'volume_extension:quotas:delete'

deprecated_show_policy = policy.DeprecatedRule(
    name=SHOW_POLICY,
    check_str=base.RULE_ADMIN_OR_OWNER
)

quota_policies = [
    policy.DocumentedRuleDefault(
        name=SHOW_POLICY,
        check_str=base.SYSTEM_READER_OR_PROJECT_READER,
        description="Show project quota (including usage and default).",
        operations=[
            {
                'method': 'GET',
                'path': '/os-quota-sets/{project_id}'
            },
            {
                'method': 'GET',
                'path': '/os-quota-sets/{project_id}/default'
            },
            {
                'method': 'GET',
                'path': '/os-quota-sets/{project_id}?usage=True'
            }
        ],
        deprecated_rule=deprecated_show_policy,
    ),
    policy.DocumentedRuleDefault(
        name=UPDATE_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="Update project quota.",
        operations=[
            {
                'method': 'PUT',
                'path': '/os-quota-sets/{project_id}'
            }
        ]
    ),
    policy.DocumentedRuleDefault(
        name=DELETE_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="Delete project quota.",
        operations=[
            {
                'method': 'DELETE',
                'path': '/os-quota-sets/{project_id}'
            }
        ]
    ),
]


def list_rules():
    return quota_policies
