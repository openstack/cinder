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


BASE_POLICY_NAME = 'volume:snapshots:%s'
GET_POLICY = 'volume:get_snapshot'
GET_ALL_POLICY = 'volume:get_all_snapshots'
CREATE_POLICY = 'volume:create_snapshot'
DELETE_POLICY = 'volume:delete_snapshot'
UPDATE_POLICY = 'volume:update_snapshot'
EXTEND_ATTRIBUTE = 'volume_extension:extended_snapshot_attributes'


snapshots_policies = [
    policy.DocumentedRuleDefault(
        name=GET_ALL_POLICY,
        check_str=base.RULE_ADMIN_OR_OWNER,
        description="List snapshots.",
        operations=[
            {
                'method': 'GET',
                'path': '/snapshots'
            },
            {
                'method': 'GET',
                'path': '/snapshots/detail'
            }
        ]),
    policy.DocumentedRuleDefault(
        name=EXTEND_ATTRIBUTE,
        check_str=base.RULE_ADMIN_OR_OWNER,
        description="List or show snapshots with extended attributes.",
        operations=[
            {
                'method': 'GET',
                'path': '/snapshots/{snapshot_id}'
            },
            {
                'method': 'GET',
                'path': '/snapshots/detail'
            }
        ]),
    policy.DocumentedRuleDefault(
        name=CREATE_POLICY,
        check_str=base.RULE_ADMIN_OR_OWNER,
        description="Create snapshot.",
        operations=[
            {
                'method': 'POST',
                'path': '/snapshots'
            }
        ]),
    policy.DocumentedRuleDefault(
        name=GET_POLICY,
        check_str=base.RULE_ADMIN_OR_OWNER,
        description="Show snapshot.",
        operations=[
            {
                'method': 'GET',
                'path': '/snapshots/{snapshot_id}'
            }
        ]),
    policy.DocumentedRuleDefault(
        name=UPDATE_POLICY,
        check_str=base.RULE_ADMIN_OR_OWNER,
        description="Update snapshot.",
        operations=[
            {
                'method': 'PUT',
                'path': '/snapshots/{snapshot_id}'
            }
        ]),
    policy.DocumentedRuleDefault(
        name=DELETE_POLICY,
        check_str=base.RULE_ADMIN_OR_OWNER,
        description="Delete snapshot.",
        operations=[
            {
                'method': 'DELETE',
                'path': '/snapshots/{snapshot_id}'
            }
        ]),
]


def list_rules():
    return snapshots_policies
