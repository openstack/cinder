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


GET_POLICY = 'volume:get_snapshot_metadata'
DELETE_POLICY = 'volume:delete_snapshot_metadata'
UPDATE_POLICY = 'volume:update_snapshot_metadata'


snapshot_metadata_policies = [
    policy.DocumentedRuleDefault(
        name=GET_POLICY,
        check_str=base.RULE_ADMIN_OR_OWNER,
        description="Show snapshot's metadata or one specified metadata "
                    "with a given key.",
        operations=[
            {
                'method': 'GET',
                'path': '/snapshots/{snapshot_id}/metadata'
            },
            {
                'method': 'GET',
                'path': '/snapshots/{snapshot_id}/metadata/{key}'
            }
        ]),
    policy.DocumentedRuleDefault(
        name=UPDATE_POLICY,
        check_str=base.RULE_ADMIN_OR_OWNER,
        description="Update snapshot's metadata or one specified "
                    "metadata with a given key.",
        operations=[
            {
                'method': 'PUT',
                'path': '/snapshots/{snapshot_id}/metadata'
            },
            {
                'method': 'PUT',
                'path': '/snapshots/{snapshot_id}/metadata/{key}'
            }
        ]),
    policy.DocumentedRuleDefault(
        name=DELETE_POLICY,
        check_str=base.RULE_ADMIN_OR_OWNER,
        description="Delete snapshot's specified metadata "
                    "with a given key.",
        operations=[
            {
                'method': 'DELETE',
                'path': '/snapshots/{snapshot_id}/metadata/{key}'
            }
        ]),
]


def list_rules():
    return snapshot_metadata_policies
