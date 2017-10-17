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


GET_ALL_POLICY = "volume_extension:services:index"
UPDATE_POLICY = "volume_extension:services:update"
FAILOVER_POLICY = "volume:failover_host"
FREEZE_POLICY = "volume:freeze_host"
THAW_POLICY = "volume:thaw_host"

services_policies = [
    policy.DocumentedRuleDefault(
        name=GET_ALL_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="List all services.",
        operations=[
            {
                'method': 'GET',
                'path': '/os-services'
            }
        ]),
    policy.DocumentedRuleDefault(
        name=UPDATE_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="Update service, including failover_host, thaw, freeze, "
                    "disable, enable, set-log and get-log actions.",
        operations=[
            {
                'method': 'PUT',
                'path': '/os-services/{action}'
            }
        ]),
    policy.DocumentedRuleDefault(
        name=FREEZE_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="Freeze a backend host.",
        operations=[
            {
                'method': 'PUT',
                'path': '/os-services/freeze'
            }
        ]),
    policy.DocumentedRuleDefault(
        name=THAW_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="Thaw a backend host.",
        operations=[
            {
                'method': 'PUT',
                'path': '/os-services/thaw'
            }
        ]),
    policy.DocumentedRuleDefault(
        name=FAILOVER_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="Failover a backend host.",
        operations=[
            {
                'method': 'PUT',
                'path': '/os-services/failover_host'
            }
        ]),
]


def list_rules():
    return services_policies
