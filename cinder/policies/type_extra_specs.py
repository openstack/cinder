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


USER_VISIBLE_EXTRA_SPECS = (
    "RESKEY:availability_zones",
    "multiattach",
    "replication_enabled",
)

CREATE_POLICY = "volume_extension:types_extra_specs:create"
DELETE_POLICY = "volume_extension:types_extra_specs:delete"
GET_ALL_POLICY = "volume_extension:types_extra_specs:index"
GET_POLICY = "volume_extension:types_extra_specs:show"
READ_SENSITIVE_POLICY = "volume_extension:types_extra_specs:read_sensitive"
UPDATE_POLICY = "volume_extension:types_extra_specs:update"

deprecated_get_all_policy = base.CinderDeprecatedRule(
    name=GET_ALL_POLICY,
    check_str=""
)

deprecated_get_policy = base.CinderDeprecatedRule(
    name=GET_POLICY,
    check_str=""
)

type_extra_specs_policies = [
    policy.DocumentedRuleDefault(
        name=GET_ALL_POLICY,
        check_str=base.SYSTEM_READER_OR_PROJECT_READER,
        description="List type extra specs.",
        operations=[
            {
                'method': 'GET',
                'path': '/types/{type_id}/extra_specs'
            }
        ],
        deprecated_rule=deprecated_get_all_policy,
    ),
    policy.DocumentedRuleDefault(
        name=CREATE_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="Create type extra specs.",
        operations=[
            {
                'method': 'POST',
                'path': '/types/{type_id}/extra_specs'
            }
        ]
    ),
    policy.DocumentedRuleDefault(
        name=GET_POLICY,
        check_str=base.SYSTEM_READER_OR_PROJECT_READER,
        description="Show one specified type extra specs.",
        operations=[
            {
                'method': 'GET',
                'path': '/types/{type_id}/extra_specs/{extra_spec_key}'
            }
        ],
        deprecated_rule=deprecated_get_policy,
    ),
    policy.DocumentedRuleDefault(
        name=READ_SENSITIVE_POLICY,
        check_str=base.RULE_ADMIN_API,
        description=("Include extra_specs fields that may reveal sensitive "
                     "information about the deployment that should not be "
                     "exposed to end users in various volume-type responses "
                     "that show extra_specs. The ability to make these calls "
                     "is governed by other policies."),
        operations=[
            {
                'method': 'GET',
                'path': '/types'
            },
            {
                'method': 'GET',
                'path': '/types/{type_id}'
            },
            {
                'method': 'GET',
                'path': '/types/{type_id}/extra_specs'
            },
            {
                'method': 'GET',
                'path': '/types/{type_id}/extra_specs/{extra_spec_key}'
            }
        ]
    ),
    policy.DocumentedRuleDefault(
        name=UPDATE_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="Update type extra specs.",
        operations=[
            {
                'method': 'PUT',
                'path': '/types/{type_id}/extra_specs/{extra_spec_key}'
            }
        ]
    ),
    policy.DocumentedRuleDefault(
        name=DELETE_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="Delete type extra specs.",
        operations=[
            {
                'method': 'DELETE',
                'path': '/types/{type_id}/extra_specs/{extra_spec_key}'
            }
        ]
    ),
]


def list_rules():
    return type_extra_specs_policies
