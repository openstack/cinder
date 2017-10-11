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


CREATE_POLICY = "volume_extension:types_extra_specs:create"
DELETE_POLICY = "volume_extension:types_extra_specs:delete"
GET_ALL_POLICY = "volume_extension:types_extra_specs:index"
GET_POLICY = "volume_extension:types_extra_specs:show"
UPDATE_POLICY = "volume_extension:types_extra_specs:update"


type_extra_specs_policies = [
    policy.DocumentedRuleDefault(
        name=GET_ALL_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="List type extra specs.",
        operations=[
            {
                'method': 'GET',
                'path': '/types/{type_id}/extra_specs'
            }
        ]),
    policy.DocumentedRuleDefault(
        name=CREATE_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="Create type extra specs.",
        operations=[
            {
                'method': 'POST',
                'path': '/types/{type_id}/extra_specs'
            }
        ]),
    policy.DocumentedRuleDefault(
        name=GET_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="Show one specified type extra specs.",
        operations=[
            {
                'method': 'GET',
                'path': '/types/{type_id}/extra_specs/{extra_spec_key}'
            }
        ]),
    policy.DocumentedRuleDefault(
        name=UPDATE_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="Update type extra specs.",
        operations=[
            {
                'method': 'PUT',
                'path': '/types/{type_id}/extra_specs/{extra_spec_key}'
            }
        ]),
    policy.DocumentedRuleDefault(
        name=DELETE_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="Delete type extra specs.",
        operations=[
            {
                'method': 'DELETE',
                'path': '/types/{type_id}/extra_specs/{extra_spec_key}'
            }
        ]),
]


def list_rules():
    return type_extra_specs_policies
