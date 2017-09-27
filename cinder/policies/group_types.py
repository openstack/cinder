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


MANAGE_POLICY = 'group:group_types_manage'
SHOW_ACCESS_POLICY = 'group:access_group_types_specs'
SPEC_POLICY = 'group:group_types_specs'


group_types_policies = [
    policy.DocumentedRuleDefault(
        name=MANAGE_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="Create, update or delete a group type.",
        operations=[
            {
                'method': 'POST',
                'path': '/group_types/'
            },
            {
                'method': 'PUT',
                'path': '/group_types/{group_type_id}'
            },
            {
                'method': 'DELETE',
                'path': '/group_types/{group_type_id}'
            }

        ]),
    policy.DocumentedRuleDefault(
        name=SHOW_ACCESS_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="Show group type with type specs attributes.",
        operations=[
            {
                'method': 'GET',
                'path': '/group_types/{group_type_id}'
            }
        ]),
    policy.DocumentedRuleDefault(
        name=SPEC_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="Create, show, update and delete group type spec.",
        operations=[
            {
                'method': 'GET',
                'path': '/group_types/{group_type_id}/group_specs/{g_spec_id}'
            },
            {
                'method': 'GET',
                'path': '/group_types/{group_type_id}/group_specs'
            },
            {
                'method': 'POST',
                'path': '/group_types/{group_type_id}/group_specs'
            },
            {
                'method': 'PUT',
                'path': '/group_types/{group_type_id}/group_specs/{g_spec_id}'
            },
            {
                'method': 'DELETE',
                'path': '/group_types/{group_type_id}/group_specs/{g_spec_id}'
            }
        ]),
]


def list_rules():
    return group_types_policies
