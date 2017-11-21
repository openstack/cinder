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

GET_POLICY = "volume:get_volume_metadata"
CREATE_POLICY = "volume:create_volume_metadata"
DELETE_POLICY = "volume:delete_volume_metadata"
UPDATE_POLICY = "volume:update_volume_metadata"
IMAGE_METADATA_POLICY = "volume_extension:volume_image_metadata"
UPDATE_ADMIN_METADATA_POLICY = "volume:update_volume_admin_metadata"


BASE_POLICY_NAME = 'volume:volume_metadata:%s'


volume_metadata_policies = [
    policy.DocumentedRuleDefault(
        name=GET_POLICY,
        check_str=base.RULE_ADMIN_OR_OWNER,
        description="Show volume's metadata or one specified metadata "
                    "with a given key.",
        operations=[
            {
                'method': 'GET',
                'path': '/volumes/{volume_id}/metadata'
            },
            {
                'method': 'GET',
                'path': '/volumes/{volume_id}/metadata/{key}'
            }
        ]),
    policy.DocumentedRuleDefault(
        name=CREATE_POLICY,
        check_str=base.RULE_ADMIN_OR_OWNER,
        description="Create volume metadata.",
        operations=[
            {
                'method': 'POST',
                'path': '/volumes/{volume_id}/metadata'
            }
        ]),
    policy.DocumentedRuleDefault(
        name=UPDATE_POLICY,
        check_str=base.RULE_ADMIN_OR_OWNER,
        description="Update volume's metadata or one specified "
                    "metadata with a given key.",
        operations=[
            {
                'method': 'PUT',
                'path': '/volumes/{volume_id}/metadata'
            },
            {
                'method': 'PUT',
                'path': '/volumes/{volume_id}/metadata/{key}'
            }
        ]),
    policy.DocumentedRuleDefault(
        name=DELETE_POLICY,
        check_str=base.RULE_ADMIN_OR_OWNER,
        description="Delete volume's specified metadata with a given key.",
        operations=[
            {
                'method': 'DELETE',
                'path': '/volumes/{volume_id}/metadata/{key}'
            }
        ]),
    policy.DocumentedRuleDefault(
        name=IMAGE_METADATA_POLICY,
        check_str=base.RULE_ADMIN_OR_OWNER,
        description="Volume's image metadata related operation, create, "
                    "delete, show and list.",
        operations=[
            {
                'method': 'GET',
                'path': '/volumes/detail'
            },
            {
                'method': 'GET',
                'path': '/volumes/{volume_id}'
            },
            {
                'method': 'POST',
                'path': '/volumes/{volume_id}/action (os-set_image_metadata)'
            },
            {
                'method': 'POST',
                'path': '/volumes/{volume_id}/action (os-unset_image_metadata)'
            }
        ]),
    policy.DocumentedRuleDefault(
        name=UPDATE_ADMIN_METADATA_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="Update volume admin metadata. It's used in `attach` "
                    "and `os-update_readonly_flag` APIs",
        operations=[
            {
                'method': 'POST',
                'path': '/volumes/{volume_id}/action (os-update_readonly_flag)'
            },
            {
                'method': 'POST',
                'path': '/volumes/{volume_id}/action (os-attach)'
            }
        ]),
]


def list_rules():
    return volume_metadata_policies
