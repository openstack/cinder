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


RESET_STATUS = 'group:reset_status'
ENABLE_REP = 'group:enable_replication'
DISABLE_REP = 'group:disable_replication'
FAILOVER_REP = 'group:failover_replication'
LIST_REP = 'group:list_replication_targets'
DELETE_POLICY = 'group:delete'


deprecated_delete_group = base.CinderDeprecatedRule(
    name=DELETE_POLICY,
    check_str=base.RULE_ADMIN_OR_OWNER
)
deprecated_enable_replication = base.CinderDeprecatedRule(
    name=ENABLE_REP,
    check_str=base.RULE_ADMIN_OR_OWNER
)
deprecated_disable_replication = base.CinderDeprecatedRule(
    name=DISABLE_REP,
    check_str=base.RULE_ADMIN_OR_OWNER
)
deprecated_failover_replication = base.CinderDeprecatedRule(
    name=FAILOVER_REP,
    check_str=base.RULE_ADMIN_OR_OWNER
)
deprecated_list_replication = base.CinderDeprecatedRule(
    name=LIST_REP,
    check_str=base.RULE_ADMIN_OR_OWNER
)
# TODO(enriquetaso): update the following in Yoga.
# We're not deprecating the reset rule in Xena.
# deprecated_reset_status = base.CinderDeprecatedRule(
#     name=RESET_STATUS,
#     check_str=base.RULE_ADMIN_API
# )


group_actions_policies = [
    policy.DocumentedRuleDefault(
        name=DELETE_POLICY,
        check_str=base.SYSTEM_ADMIN_OR_PROJECT_MEMBER,
        description="Delete group.",
        operations=[
            {
                'method': 'POST',
                'path': '/groups/{group_id}/action (delete)'
            }
        ],
        deprecated_rule=deprecated_delete_group,
    ),
    policy.DocumentedRuleDefault(
        name=RESET_STATUS,
        check_str=base.RULE_ADMIN_API,
        description="Reset status of group.",
        operations=[
            {
                'method': 'POST',
                'path': '/groups/{group_id}/action (reset_status)'
            }
        ]
    ),
    policy.DocumentedRuleDefault(
        name=ENABLE_REP,
        check_str=base.SYSTEM_ADMIN_OR_PROJECT_MEMBER,
        description="Enable replication.",
        operations=[
            {
                'method': 'POST',
                'path': '/groups/{group_id}/action (enable_replication)'
            }
        ],
        deprecated_rule=deprecated_enable_replication,
    ),
    policy.DocumentedRuleDefault(
        name=DISABLE_REP,
        check_str=base.SYSTEM_ADMIN_OR_PROJECT_MEMBER,
        description="Disable replication.",
        operations=[
            {
                'method': 'POST',
                'path': '/groups/{group_id}/action (disable_replication)'
            }
        ],
        deprecated_rule=deprecated_disable_replication,
    ),
    policy.DocumentedRuleDefault(
        name=FAILOVER_REP,
        check_str=base.SYSTEM_ADMIN_OR_PROJECT_MEMBER,
        description="Fail over replication.",
        operations=[
            {
                'method': 'POST',
                'path': '/groups/{group_id}/action (failover_replication)'
            }
        ],
        deprecated_rule=deprecated_failover_replication,
    ),
    policy.DocumentedRuleDefault(
        name=LIST_REP,
        check_str=base.SYSTEM_ADMIN_OR_PROJECT_MEMBER,
        description="List failover replication.",
        operations=[
            {
                'method': 'POST',
                'path': '/groups/{group_id}/action (list_replication_targets)'
            }
        ],
        deprecated_rule=deprecated_list_replication,
    ),
]


def list_rules():
    return group_actions_policies
