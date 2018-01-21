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


CREATE_POLICY = 'volume:attachment_create'
UPDATE_POLICY = 'volume:attachment_update'
DELETE_POLICY = 'volume:attachment_delete'
COMPLETE_POLICY = 'volume:attachment_complete'
MULTIATTACH_BOOTABLE_VOLUME_POLICY = 'volume:multiattach_bootable_volume'

attachments_policies = [
    policy.DocumentedRuleDefault(
        name=CREATE_POLICY,
        check_str="",
        description="Create attachment.",
        operations=[
            {
                'method': 'POST',
                'path': '/attachments'
            }
        ]),
    policy.DocumentedRuleDefault(
        name=UPDATE_POLICY,
        check_str=base.RULE_ADMIN_OR_OWNER,
        description="Update attachment.",
        operations=[
            {
                'method': 'PUT',
                'path': '/attachments/{attachment_id}'
            }
        ]),
    policy.DocumentedRuleDefault(
        name=DELETE_POLICY,
        check_str=base.RULE_ADMIN_OR_OWNER,
        description="Delete attachment.",
        operations=[
            {
                'method': 'DELETE',
                'path': '/attachments/{attachment_id}'
            }
        ]),
    policy.DocumentedRuleDefault(
        name=COMPLETE_POLICY,
        check_str=base.RULE_ADMIN_OR_OWNER,
        description="Mark a volume attachment process as completed (in-use)",
        operations=[
            {
                'method': 'POST',
                'path': '/attachments/{attachment_id}/action (os-complete)'
            }
        ]),
    policy.DocumentedRuleDefault(
        name=MULTIATTACH_BOOTABLE_VOLUME_POLICY,
        check_str=base.RULE_ADMIN_OR_OWNER,
        description="Allow multiattach of bootable volumes.",
        operations=[
            {
                'method': 'POST',
                'path': '/attachments'
            }
        ]),
]


def list_rules():
    return attachments_policies
