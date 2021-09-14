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
TYPE_ACCESS_WHO_POLICY = "volume_extension:volume_type_access:get_all_for_type"


deprecated_volume_type_access = base.CinderDeprecatedRule(
    name=TYPE_ACCESS_POLICY,
    check_str=base.RULE_ADMIN_OR_OWNER
)
deprecated_type_access_who_policy = base.CinderDeprecatedRule(
    name=TYPE_ACCESS_WHO_POLICY,
    # TODO: revise check_str and dep_reason in Yoga
    check_str=TYPE_ACCESS_POLICY,
    deprecated_reason=(
        f"Reason: '{TYPE_ACCESS_WHO_POLICY}' is a new policy that protects "
        f"an API call formerly governed by '{TYPE_ACCESS_POLICY}', but which "
        'has been separated for finer-grained policy control.'),
)


volume_access_policies = [
    policy.DocumentedRuleDefault(
        name=TYPE_ACCESS_POLICY,
        check_str=base.SYSTEM_ADMIN_OR_PROJECT_MEMBER,
        description=(
            "Adds the boolean field 'os-volume-type-access:is_public' to "
            'the responses for these API calls.  The ability to make these '
            'calls is governed by other policies.'),
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
                'method': 'POST',
                'path': '/types'
            }
        ],
        deprecated_rule=deprecated_volume_type_access,
    ),
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
    policy.DocumentedRuleDefault(
        name=TYPE_ACCESS_WHO_POLICY,
        check_str=base.RULE_ADMIN_API,
        description=(
            'List private volume type access detail, that is, list the '
            'projects that have access to this volume type.'),
        operations=[
            {
                'method': 'GET',
                'path': '/types/{type_id}/os-volume-type-access'
            }
        ],
        deprecated_rule=deprecated_type_access_who_policy,
    ),
]


def list_rules():
    return volume_access_policies
