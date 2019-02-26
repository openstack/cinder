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


CREATE_POLICY = 'group:create_group_snapshot'
DELETE_POLICY = 'group:delete_group_snapshot'
UPDATE_POLICY = 'group:update_group_snapshot'
GET_POLICY = 'group:get_group_snapshot'
GET_ALL_POLICY = 'group:get_all_group_snapshots'
GROUP_SNAPSHOT_ATTRIBUTES_POLICY = 'group:group_snapshot_project_attribute'


group_snapshots_policies = [
    policy.DocumentedRuleDefault(
        name=GET_ALL_POLICY,
        check_str=base.RULE_ADMIN_OR_OWNER,
        description="List group snapshots.",
        operations=[
            {
                'method': 'GET',
                'path': '/group_snapshots'
            },
            {
                'method': 'GET',
                'path': '/group_snapshots/detail'
            }
        ]),
    policy.DocumentedRuleDefault(
        name=CREATE_POLICY,
        check_str="",
        description="Create group snapshot.",
        operations=[
            {
                'method': 'POST',
                'path': '/group_snapshots'
            }
        ]),
    policy.DocumentedRuleDefault(
        name=GET_POLICY,
        check_str=base.RULE_ADMIN_OR_OWNER,
        description="Show group snapshot.",
        operations=[
            {
                'method': 'GET',
                'path': '/group_snapshots/{group_snapshot_id}'
            }
        ]),
    policy.DocumentedRuleDefault(
        name=DELETE_POLICY,
        check_str=base.RULE_ADMIN_OR_OWNER,
        description="Delete group snapshot.",
        operations=[
            {
                'method': 'DELETE',
                'path': '/group_snapshots/{group_snapshot_id}'
            }
        ]),
    policy.DocumentedRuleDefault(
        name=UPDATE_POLICY,
        check_str=base.RULE_ADMIN_OR_OWNER,
        description="Update group snapshot.",
        operations=[
            {
                'method': 'PUT',
                'path': '/group_snapshots/{group_snapshot_id}'
            }
        ]),
    policy.DocumentedRuleDefault(
        name=GROUP_SNAPSHOT_ATTRIBUTES_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="List group snapshots or show group "
                    "snapshot with project attributes.",
        operations=[
            {
                'method': 'GET',
                'path': '/group_snapshots/{group_snapshot_id}'
            },
            {
                'method': 'GET',
                'path': '/group_snapshots/detail'
            }
        ]),
]


def list_rules():
    return group_snapshots_policies
