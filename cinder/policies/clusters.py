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


GET_POLICY = 'clusters:get'
GET_ALL_POLICY = 'clusters:get_all'
UPDATE_POLICY = 'clusters:update'


clusters_policies = [
    policy.DocumentedRuleDefault(
        name=GET_ALL_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="List clusters.",
        operations=[
            {
                'method': 'GET',
                'path': '/clusters'
            },
            {
                'method': 'GET',
                'path': '/clusters/detail'
            }
        ]),
    policy.DocumentedRuleDefault(
        name=GET_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="Show cluster.",
        operations=[
            {
                'method': 'GET',
                'path': '/clusters/{cluster_id}'
            }
        ]),
    policy.DocumentedRuleDefault(
        name=UPDATE_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="Update cluster.",
        operations=[
            {
                'method': 'PUT',
                'path': '/clusters/{cluster_id}'
            }
        ]),
]


def list_rules():
    return clusters_policies
