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


RESET_STATUS = 'group:reset_group_snapshot_status'


group_snapshot_actions_policies = [
    policy.DocumentedRuleDefault(
        name=RESET_STATUS,
        check_str=base.RULE_ADMIN_OR_OWNER,
        description="Reset status of group snapshot.",
        operations=[
            {
                'method': 'POST',
                'path':
                    '/group_snapshots/{g_snapshot_id}/action (reset_status)'
            }
        ]),
]


def list_rules():
    return group_snapshot_actions_policies
