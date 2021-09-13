# Copyright 2020 Red Hat, Inc.
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

CREATE_UPDATE_POLICY = "volume_extension:default_set_or_update"
GET_POLICY = "volume_extension:default_get"
GET_ALL_POLICY = "volume_extension:default_get_all"
DELETE_POLICY = "volume_extension:default_unset"

deprecated_create_update_policy = base.CinderDeprecatedRule(
    name=CREATE_UPDATE_POLICY,
    check_str=base.SYSTEM_OR_DOMAIN_OR_PROJECT_ADMIN
)
deprecated_get_policy = base.CinderDeprecatedRule(
    name=GET_POLICY,
    check_str=base.SYSTEM_OR_DOMAIN_OR_PROJECT_ADMIN
)
deprecated_get_all_policy = base.CinderDeprecatedRule(
    name=GET_ALL_POLICY,
    check_str=base.SYSTEM_ADMIN
)
deprecated_delete_policy = base.CinderDeprecatedRule(
    name=DELETE_POLICY,
    check_str=base.SYSTEM_OR_DOMAIN_OR_PROJECT_ADMIN
)

default_type_policies = [
    policy.DocumentedRuleDefault(
        name=CREATE_UPDATE_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="Set or update default volume type.",
        operations=[
            {
                'method': 'PUT',
                'path': '/default-types'
            }
        ],
        deprecated_rule=deprecated_create_update_policy,
    ),
    policy.DocumentedRuleDefault(
        name=GET_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="Get default types.",
        operations=[
            {
                'method': 'GET',
                'path': '/default-types/{project-id}'
            }
        ],
        deprecated_rule=deprecated_get_policy,
    ),
    policy.DocumentedRuleDefault(
        name=GET_ALL_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="Get all default types. "
                    "WARNING: Changing this might open up too much "
                    "information regarding cloud deployment.",
        operations=[
            {
                'method': 'GET',
                'path': '/default-types/'
            }
        ],
        deprecated_rule=deprecated_get_all_policy,
    ),
    policy.DocumentedRuleDefault(
        name=DELETE_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="Unset default type.",
        operations=[
            {
                'method': 'DELETE',
                'path': '/default-types/{project-id}'
            }
        ],
        deprecated_rule=deprecated_delete_policy,
    ),
]


def list_rules():
    return default_type_policies
