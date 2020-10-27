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


deprecated_get_all_group_snapshots = base.CinderDeprecatedRule(
    name=GET_ALL_POLICY,
    check_str=base.RULE_ADMIN_OR_OWNER
)
deprecated_create_group_snapshot = base.CinderDeprecatedRule(
    name=CREATE_POLICY,
    check_str=""
)
deprecated_get_group_snapshot = base.CinderDeprecatedRule(
    name=GET_POLICY,
    check_str=base.RULE_ADMIN_OR_OWNER
)
deprecated_delete_group_snapshot = base.CinderDeprecatedRule(
    name=DELETE_POLICY,
    check_str=base.RULE_ADMIN_OR_OWNER
)
deprecated_update_group_snapshot = base.CinderDeprecatedRule(
    name=UPDATE_POLICY,
    check_str=base.RULE_ADMIN_OR_OWNER
)


group_snapshots_policies = [
    policy.DocumentedRuleDefault(
        name=GET_ALL_POLICY,
        check_str=base.SYSTEM_READER_OR_PROJECT_READER,
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
        ],
        deprecated_rule=deprecated_get_all_group_snapshots,
    ),
    policy.DocumentedRuleDefault(
        name=CREATE_POLICY,
        check_str=base.SYSTEM_ADMIN_OR_PROJECT_MEMBER,
        description="Create group snapshot.",
        operations=[
            {
                'method': 'POST',
                'path': '/group_snapshots'
            }
        ],
        deprecated_rule=deprecated_create_group_snapshot,
    ),
    policy.DocumentedRuleDefault(
        name=GET_POLICY,
        check_str=base.SYSTEM_READER_OR_PROJECT_READER,
        description="Show group snapshot.",
        operations=[
            {
                'method': 'GET',
                'path': '/group_snapshots/{group_snapshot_id}'
            }
        ],
        deprecated_rule=deprecated_get_group_snapshot,
    ),
    policy.DocumentedRuleDefault(
        name=DELETE_POLICY,
        check_str=base.SYSTEM_ADMIN_OR_PROJECT_MEMBER,
        description="Delete group snapshot.",
        operations=[
            {
                'method': 'DELETE',
                'path': '/group_snapshots/{group_snapshot_id}'
            }
        ],
        deprecated_rule=deprecated_delete_group_snapshot,
    ),
    policy.DocumentedRuleDefault(
        name=UPDATE_POLICY,
        check_str=base.SYSTEM_ADMIN_OR_PROJECT_MEMBER,
        description="Update group snapshot.",
        operations=[
            {
                'method': 'PUT',
                'path': '/group_snapshots/{group_snapshot_id}'
            }
        ],
        deprecated_rule=deprecated_update_group_snapshot,
    ),
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
