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


CREATE_POLICY = "volume:create_transfer"
ACCEPT_POLICY = "volume:accept_transfer"
DELETE_POLICY = "volume:delete_transfer"
GET_POLICY = "volume:get_transfer"
GET_ALL_POLICY = "volume:get_all_transfers"


volume_transfer_policies = [
    policy.DocumentedRuleDefault(
        name=GET_ALL_POLICY,
        check_str=base.RULE_ADMIN_OR_OWNER,
        description="List volume transfer.",
        operations=[
            {
                'method': 'GET',
                'path': '/os-volume-transfer'
            },
            {
                'method': 'GET',
                'path': '/os-volume-transfer/detail'
            },
            {
                'method': 'GET',
                'path': '/volume_transfers'
            },
            {
                'method': 'GET',
                'path': '/volume-transfers/detail'
            }
        ]),
    policy.DocumentedRuleDefault(
        name=CREATE_POLICY,
        check_str=base.RULE_ADMIN_OR_OWNER,
        description="Create a volume transfer.",
        operations=[
            {
                'method': 'POST',
                'path': '/os-volume-transfer'
            },
            {
                'method': 'POST',
                'path': '/volume_transfers'
            }
        ]),
    policy.DocumentedRuleDefault(
        name=GET_POLICY,
        check_str=base.RULE_ADMIN_OR_OWNER,
        description="Show one specified volume transfer.",
        operations=[
            {
                'method': 'GET',
                'path': '/os-volume-transfer/{transfer_id}'
            },
            {
                'method': 'GET',
                'path': '/volume-transfers/{transfer_id}'
            }
        ]),
    policy.DocumentedRuleDefault(
        name=ACCEPT_POLICY,
        check_str="",
        description="Accept a volume transfer.",
        operations=[
            {
                'method': 'POST',
                'path': '/os-volume-transfer/{transfer_id}/accept'
            },
            {
                'method': 'POST',
                'path': '/volume-transfers/{transfer_id}/accept'
            }
        ]),
    policy.DocumentedRuleDefault(
        name=DELETE_POLICY,
        check_str=base.RULE_ADMIN_OR_OWNER,
        description="Delete volume transfer.",
        operations=[
            {
                'method': 'DELETE',
                'path': '/os-volume-transfer/{transfer_id}'
            },
            {
                'method': 'DELETE',
                'path': '/volume-transfers/{transfer_id}'
            }
        ]),
]


def list_rules():
    return volume_transfer_policies
