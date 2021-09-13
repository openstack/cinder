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
MANAGE_POLICY = 'group:group_types_manage'
CREATE_POLICY = 'group:group_types:create'
UPDATE_POLICY = 'group:group_types:update'
DELETE_POLICY = 'group:group_types:delete'
SHOW_ACCESS_POLICY = 'group:access_group_types_specs'
# SPEC_POLICY is deprecated
SPEC_POLICY = 'group:group_types_specs'
SPEC_GET_POLICY = 'group:group_types_specs:get'
SPEC_GET_ALL_POLICY = 'group:group_types_specs:get_all'
SPEC_CREATE_POLICY = 'group:group_types_specs:create'
SPEC_UPDATE_POLICY = 'group:group_types_specs:update'
SPEC_DELETE_POLICY = 'group:group_types_specs:delete'

deprecated_manage_policy = base.CinderDeprecatedRule(
    name=MANAGE_POLICY,
    check_str=base.RULE_ADMIN_API,
    deprecated_reason=(f'{MANAGE_POLICY} has been replaced by more granular '
                       'policies that separately govern POST, PUT, and DELETE '
                       'operations.'),
)
deprecated_spec_policy = base.CinderDeprecatedRule(
    name=SPEC_POLICY,
    check_str=base.RULE_ADMIN_API,
    deprecated_reason=(f'{SPEC_POLICY} has been replaced by more granular '
                       'policies that separately govern GET, POST, PUT, and '
                       'DELETE operations.'),
)

group_types_policies = [
    policy.DocumentedRuleDefault(
        name=CREATE_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="Create a group type.",
        operations=[
            {
                'method': 'POST',
                'path': '/group_types/'
            },
        ],
        deprecated_rule=deprecated_manage_policy,
    ),
    policy.DocumentedRuleDefault(
        name=UPDATE_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="Update a group type.",
        operations=[
            {
                'method': 'PUT',
                'path': '/group_types/{group_type_id}'
            },
        ],
        deprecated_rule=deprecated_manage_policy,
    ),
    policy.DocumentedRuleDefault(
        name=DELETE_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="Delete a group type.",
        operations=[
            {
                'method': 'DELETE',
                'path': '/group_types/{group_type_id}'
            },
        ],
        deprecated_rule=deprecated_manage_policy,
    ),
    policy.DocumentedRuleDefault(
        name=SHOW_ACCESS_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="Show group type with type specs attributes.",
        operations=[
            {
                'method': 'GET',
                'path': '/group_types/{group_type_id}'
            }
        ]
    ),
    policy.DocumentedRuleDefault(
        name=SPEC_GET_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="Show a group type spec.",
        operations=[
            {
                'method': 'GET',
                'path': '/group_types/{group_type_id}/group_specs/{g_spec_id}'
            },
        ],
        deprecated_rule=deprecated_spec_policy,
    ),
    policy.DocumentedRuleDefault(
        name=SPEC_GET_ALL_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="List group type specs.",
        operations=[
            {
                'method': 'GET',
                'path': '/group_types/{group_type_id}/group_specs'
            },
        ],
        deprecated_rule=deprecated_spec_policy,
    ),
    policy.DocumentedRuleDefault(
        name=SPEC_CREATE_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="Create a group type spec.",
        operations=[
            {
                'method': 'POST',
                'path': '/group_types/{group_type_id}/group_specs'
            },
        ],
        deprecated_rule=deprecated_spec_policy,
    ),
    policy.DocumentedRuleDefault(
        name=SPEC_UPDATE_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="Update a group type spec.",
        operations=[
            {
                'method': 'PUT',
                'path': '/group_types/{group_type_id}/group_specs/{g_spec_id}'
            },
        ],
        deprecated_rule=deprecated_spec_policy,
    ),
    policy.DocumentedRuleDefault(
        name=SPEC_DELETE_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="Delete a group type spec.",
        operations=[
            {
                'method': 'DELETE',
                'path': '/group_types/{group_type_id}/group_specs/{g_spec_id}'
            },
        ],
        deprecated_rule=deprecated_spec_policy,
    ),
]


def list_rules():
    return group_types_policies
