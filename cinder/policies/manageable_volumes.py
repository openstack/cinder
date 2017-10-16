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


MANAGE_POLICY = "volume_extension:volume_manage"
UNMANAGE_POLICY = "volume_extension:volume_unmanage"
LIST_MANAGEABLE_POLICY = "volume_extension:list_manageable"


manageable_volumes_policies = [
    policy.DocumentedRuleDefault(
        name=LIST_MANAGEABLE_POLICY,
        check_str=base.RULE_ADMIN_API,
        description=
        "List (in detail) of volumes which are available to manage.",
        operations=[
            {
                'method': 'GET',
                'path': '/manageable_volumes'
            },
            {
                'method': 'GET',
                'path': '/manageable_volumes/detail'
            }
        ]),
    policy.DocumentedRuleDefault(
        name=MANAGE_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="Manage existing volumes.",
        operations=[
            {
                'method': 'POST',
                'path': '/manageable_volumes'
            }
        ]),
    policy.DocumentedRuleDefault(
        name=UNMANAGE_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="Stop managing a volume.",
        operations=[
            {
                'method': 'POST',
                'path': '/volumes/{volume_id}/action (os-unmanage)'
            }
        ]),
]


def list_rules():
    return manageable_volumes_policies
