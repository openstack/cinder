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


RESET_STATUS_POLICY = 'volume_extension:snapshot_admin_actions:reset_status'
FORCE_DELETE_POLICY = 'volume_extension:snapshot_admin_actions:force_delete'
UPDATE_STATUS_POLICY = \
    'snapshot_extension:snapshot_actions:update_snapshot_status'

deprecated_update_status = base.CinderDeprecatedRule(
    name=UPDATE_STATUS_POLICY,
    check_str=""
)


snapshot_actions_policies = [
    policy.DocumentedRuleDefault(
        name=RESET_STATUS_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="Reset status of a snapshot.",
        operations=[
            {
                'method': 'POST',
                'path': '/snapshots/{snapshot_id}/action (os-reset_status)'
            }
        ],
    ),
    policy.DocumentedRuleDefault(
        name=UPDATE_STATUS_POLICY,
        check_str=base.SYSTEM_ADMIN_OR_PROJECT_MEMBER,
        description="Update database fields of snapshot.",
        operations=[
            {
                'method': 'POST',
                'path': '/snapshots/{snapshot_id}/action '
                        '(update_snapshot_status)'
            }
        ],
        deprecated_rule=deprecated_update_status,
    ),
    policy.DocumentedRuleDefault(
        name=FORCE_DELETE_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="Force delete a snapshot.",
        operations=[
            {
                'method': 'POST',
                'path': '/snapshots/{snapshot_id}/action (os-force_delete)'
            }
        ],
    )
]


def list_rules():
    return snapshot_actions_policies
