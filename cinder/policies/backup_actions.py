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


BASE_POLICY_NAME = 'volume_extension:backup_admin_actions:%s'


backup_actions_policies = [
    policy.DocumentedRuleDefault(
        name=BASE_POLICY_NAME % 'reset_status',
        check_str=base.RULE_ADMIN_API,
        description="Reset status of a backup.",
        operations=[
            {
                'method': 'POST',
                'path': '/backups/{backup_id}/action (os-reset_status)'
            }
        ]),
    policy.DocumentedRuleDefault(
        name=BASE_POLICY_NAME % 'force_delete',
        check_str=base.RULE_ADMIN_API,
        description="Force delete a backup.",
        operations=[
            {
                'method': 'POST',
                'path': '/backups/{backup_id}/action (os-force_delete)'
            }
        ]),
]


def list_rules():
    return backup_actions_policies
