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


CLEAN_POLICY = 'workers:cleanup'


workers_policies = [
    policy.DocumentedRuleDefault(
        name=CLEAN_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="Clean up workers.",
        operations=[
            {
                'method': 'POST',
                'path': '/workers/cleanup'
            }
        ])
]


def list_rules():
    return workers_policies
