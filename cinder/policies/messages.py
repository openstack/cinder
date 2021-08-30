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


DELETE_POLICY = 'message:delete'
GET_POLICY = 'message:get'
GET_ALL_POLICY = 'message:get_all'


deprecated_get_policy = base.CinderDeprecatedRule(
    name=GET_POLICY,
    check_str=base.RULE_ADMIN_OR_OWNER
)
deprecated_get_all_policy = base.CinderDeprecatedRule(
    name=GET_ALL_POLICY,
    check_str=base.RULE_ADMIN_OR_OWNER
)
deprecated_delete_policy = base.CinderDeprecatedRule(
    name=DELETE_POLICY,
    check_str=base.RULE_ADMIN_OR_OWNER
)


messages_policies = [
    policy.DocumentedRuleDefault(
        name=GET_ALL_POLICY,
        check_str=base.SYSTEM_READER_OR_PROJECT_READER,
        description="List messages.",
        operations=[
            {
                'method': 'GET',
                'path': '/messages'
            }
        ],
        deprecated_rule=deprecated_get_policy,
    ),
    policy.DocumentedRuleDefault(
        name=GET_POLICY,
        check_str=base.SYSTEM_READER_OR_PROJECT_READER,
        description="Show message.",
        operations=[
            {
                'method': 'GET',
                'path': '/messages/{message_id}'
            }
        ],
        deprecated_rule=deprecated_get_all_policy,
    ),
    policy.DocumentedRuleDefault(
        name=DELETE_POLICY,
        check_str=base.SYSTEM_ADMIN_OR_PROJECT_MEMBER,
        description="Delete message.",
        operations=[
            {
                'method': 'DELETE',
                'path': '/messages/{message_id}'
            }
        ],
        deprecated_rule=deprecated_delete_policy,
    ),
]


def list_rules():
    return messages_policies
