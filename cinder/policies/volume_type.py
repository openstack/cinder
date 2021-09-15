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


MANAGE_POLICY = "volume_extension:types_manage"
CREATE_POLICY = "volume_extension:type_create"
UPDATE_POLICY = "volume_extension:type_update"
DELETE_POLICY = "volume_extension:type_delete"
GET_POLICY = "volume_extension:type_get"
GET_ALL_POLICY = "volume_extension:type_get_all"
QOS_POLICY = "volume_extension:access_types_qos_specs_id"
EXTRA_SPEC_POLICY = "volume_extension:access_types_extra_specs"
# TODO: remove the next 2 in Yoga
ENCRYPTION_POLICY = "volume_extension:volume_type_encryption"
ENCRYPTION_BASE_POLICY_RULE = 'rule:%s' % ENCRYPTION_POLICY
CREATE_ENCRYPTION_POLICY = "volume_extension:volume_type_encryption:create"
GET_ENCRYPTION_POLICY = "volume_extension:volume_type_encryption:get"
UPDATE_ENCRYPTION_POLICY = "volume_extension:volume_type_encryption:update"
DELETE_ENCRYPTION_POLICY = "volume_extension:volume_type_encryption:delete"

GENERAL_ENCRYPTION_POLICY_REASON = (
    f"Reason: '{ENCRYPTION_POLICY}' was a convenience policy that allowed you "
    'to set all volume encryption type policies to the same value.  We are '
    'deprecating this rule to prepare for a future release in which the '
    'default values for policies that read, create/update, and delete '
    'encryption types will be different from each other.')


# TODO: remove in Yoga
deprecated_manage_policy = base.CinderDeprecatedRule(
    name=MANAGE_POLICY,
    check_str=base.RULE_ADMIN_API,
    deprecated_reason=(f'{MANAGE_POLICY} has been replaced by more granular '
                       'policies that separately govern POST, PUT, and DELETE '
                       'operations.'),
)
deprecated_extra_spec_policy = base.CinderDeprecatedRule(
    name=EXTRA_SPEC_POLICY,
    check_str=base.RULE_ADMIN_API
)
deprecated_encryption_create_policy = base.CinderDeprecatedRule(
    name=CREATE_ENCRYPTION_POLICY,
    # TODO: change to base.RULE_ADMIN_API in Yoga & remove dep_reason
    check_str=ENCRYPTION_BASE_POLICY_RULE,
    deprecated_reason=GENERAL_ENCRYPTION_POLICY_REASON,
)
deprecated_encryption_get_policy = base.CinderDeprecatedRule(
    name=GET_ENCRYPTION_POLICY,
    # TODO: change to base.RULE_ADMIN_API in Yoga & remove dep_reason
    check_str=ENCRYPTION_BASE_POLICY_RULE,
    deprecated_reason=GENERAL_ENCRYPTION_POLICY_REASON,
)
deprecated_encryption_update_policy = base.CinderDeprecatedRule(
    name=UPDATE_ENCRYPTION_POLICY,
    # TODO: change to base.RULE_ADMIN_API in Yoga & remove dep_reason
    check_str=ENCRYPTION_BASE_POLICY_RULE,
    deprecated_reason=GENERAL_ENCRYPTION_POLICY_REASON,
)
deprecated_encryption_delete_policy = base.CinderDeprecatedRule(
    name=DELETE_ENCRYPTION_POLICY,
    # TODO: change to base.RULE_ADMIN_API in Yoga & remove dep_reason
    check_str=ENCRYPTION_BASE_POLICY_RULE,
    deprecated_reason=GENERAL_ENCRYPTION_POLICY_REASON,
)
deprecated_get_volume_type = base.CinderDeprecatedRule(
    name=GET_POLICY,
    check_str=""
)
deprecated_get_all_volume_type = base.CinderDeprecatedRule(
    name=GET_ALL_POLICY,
    check_str=""
)


volume_type_policies = [
    policy.DocumentedRuleDefault(
        name=CREATE_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="Create volume type.",
        operations=[
            {
                'method': 'POST',
                'path': '/types'
            },
        ],
        # TODO: will need its own deprecated rule in Yoga
        deprecated_rule=deprecated_manage_policy,
    ),
    policy.DocumentedRuleDefault(
        name=UPDATE_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="Update volume type.",
        operations=[
            {
                'method': 'PUT',
                'path': '/types'
            },
        ],
        # TODO: will need its own deprecated rule in Yoga
        deprecated_rule=deprecated_manage_policy,
    ),
    policy.DocumentedRuleDefault(
        name=DELETE_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="Delete volume type.",
        operations=[
            {
                'method': 'DELETE',
                'path': '/types'
            }
        ],
        # TODO: will need its own deprecated rule in Yoga
        deprecated_rule=deprecated_manage_policy,
    ),
    policy.DocumentedRuleDefault(
        name=GET_POLICY,
        check_str=base.SYSTEM_READER_OR_PROJECT_READER,
        description="Get one specific volume type.",
        operations=[
            {
                'method': 'GET',
                'path': '/types/{type_id}'
            }
        ],
        deprecated_rule=deprecated_get_volume_type,
    ),
    policy.DocumentedRuleDefault(
        name=GET_ALL_POLICY,
        check_str=base.SYSTEM_READER_OR_PROJECT_READER,
        description="List volume types.",
        operations=[
            {
                'method': 'GET',
                'path': '/types/'
            }
        ],
        deprecated_rule=deprecated_get_all_volume_type,
    ),
    policy.DocumentedRuleDefault(
        name=EXTRA_SPEC_POLICY,
        check_str=base.SYSTEM_READER_OR_PROJECT_READER,
        description=(
            "Include the volume type's extra_specs attribute in the volume "
            "type list or show requests.  The ability to make these calls "
            "is governed by other policies."),
        operations=[
            {
                'method': 'GET',
                'path': '/types/{type_id}'
            },
            {
                'method': 'GET',
                'path': '/types'
            }
        ],
        deprecated_rule=deprecated_extra_spec_policy,
    ),
    policy.DocumentedRuleDefault(
        name=QOS_POLICY,
        check_str=base.RULE_ADMIN_API,
        description=(
            "Include the volume type's QoS specifications ID attribute in "
            "the volume type list or show requests.  The ability to make "
            "these calls is governed by other policies."),
        operations=[
            {
                'method': 'GET',
                'path': '/types/{type_id}'
            },
            {
                'method': 'GET',
                'path': '/types'
            }
        ]),
    # TODO: remove in Yoga
    policy.RuleDefault(
        name=ENCRYPTION_POLICY,
        check_str=base.RULE_ADMIN_API,
        description=('DEPRECATED: This rule will be removed in the Yoga '
                     'release.')
    ),
    policy.DocumentedRuleDefault(
        name=CREATE_ENCRYPTION_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="Create volume type encryption.",
        operations=[
            {
                'method': 'POST',
                'path': '/types/{type_id}/encryption'
            }
        ],
        deprecated_rule=deprecated_encryption_create_policy,
    ),
    policy.DocumentedRuleDefault(
        name=GET_ENCRYPTION_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="Show a volume type's encryption type, "
                    "show an encryption specs item.",
        operations=[
            {
                'method': 'GET',
                'path': '/types/{type_id}/encryption'
            },
            {
                'method': 'GET',
                'path': '/types/{type_id}/encryption/{key}'
            }
        ],
        deprecated_rule=deprecated_encryption_get_policy,
    ),
    policy.DocumentedRuleDefault(
        name=UPDATE_ENCRYPTION_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="Update volume type encryption.",
        operations=[
            {
                'method': 'PUT',
                'path': '/types/{type_id}/encryption/{encryption_id}'
            }
        ],
        deprecated_rule=deprecated_encryption_update_policy,
    ),
    policy.DocumentedRuleDefault(
        name=DELETE_ENCRYPTION_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="Delete volume type encryption.",
        operations=[
            {
                'method': 'DELETE',
                'path': '/types/{type_id}/encryption/{encryption_id}'
            }
        ],
        deprecated_rule=deprecated_encryption_delete_policy,
    ),
]


def list_rules():
    return volume_type_policies
