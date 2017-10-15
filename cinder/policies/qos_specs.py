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


CREATE_POLICY = 'volume_extension:qos_specs_manage:create'
GET_POLICY = 'volume_extension:qos_specs_manage:get'
GET_ALL_POLICY = 'volume_extension:qos_specs_manage:get_all'
UPDATE_POLICY = 'volume_extension:qos_specs_manage:update'
DELETE_POLICY = 'volume_extension:qos_specs_manage:delete'


qos_specs_policies = [
    policy.DocumentedRuleDefault(
        name=GET_ALL_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="List qos specs or list all associations.",
        operations=[
            {
                'method': 'GET',
                'path': '/qos-specs'
            },
            {
                'method': 'GET',
                'path': '/qos-specs/{qos_id}/associations'
            }
        ]),
    policy.DocumentedRuleDefault(
        name=GET_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="Show qos specs.",
        operations=[
            {
                'method': 'GET',
                'path': '/qos-specs/{qos_id}'
            }
        ]),
    policy.DocumentedRuleDefault(
        name=CREATE_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="Create qos specs.",
        operations=[
            {
                'method': 'POST',
                'path': '/qos-specs'
            }
        ]),
    policy.DocumentedRuleDefault(
        name=UPDATE_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="Update qos specs (including updating association).",
        operations=[
            {
                'method': 'PUT',
                'path': '/qos-specs/{qos_id}'
            },
            {
                'method': 'GET',
                'path': '/qos-specs/{qos_id}/disassociate_all'
            },
            {
                'method': 'GET',
                'path': '/qos-specs/{qos_id}/associate'
            },
            {
                'method': 'GET',
                'path': '/qos-specs/{qos_id}/disassociate'
            }
        ]),
    policy.DocumentedRuleDefault(
        name=DELETE_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="delete qos specs or unset one specified qos key.",
        operations=[
            {
                'method': 'DELETE',
                'path': '/qos-specs/{qos_id}'
            },
            {
                'method': 'PUT',
                'path': '/qos-specs/{qos_id}/delete_keys'
            }
        ])
]


def list_rules():
    return qos_specs_policies
