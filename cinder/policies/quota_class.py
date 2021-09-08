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


# MANAGE_POLICY is deprecated
MANAGE_POLICY = 'volume_extension:quota_classes'
GET_POLICY = 'volume_extension:quota_classes:get'
UPDATE_POLICY = 'volume_extension:quota_classes:update'


deprecated_manage_policy = base.CinderDeprecatedRule(
    name=MANAGE_POLICY,
    check_str=base.RULE_ADMIN_API,
    deprecated_reason=(f'{MANAGE_POLICY} has been replaced by more granular '
                       'policies that separately govern GET and PUT '
                       'operations.'),
)

quota_class_policies = [
    policy.DocumentedRuleDefault(
        name=GET_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="Show project quota class.",
        operations=[
            {
                'method': 'GET',
                'path': '/os-quota-class-sets/{project_id}'
            }
        ],
        deprecated_rule=deprecated_manage_policy,
    ),
    policy.DocumentedRuleDefault(
        name=UPDATE_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="Update project quota class.",
        operations=[
            {
                'method': 'PUT',
                'path': '/os-quota-class-sets/{project_id}'
            }
        ],
        deprecated_rule=deprecated_manage_policy,
    ),
]


def list_rules():
    return quota_class_policies
