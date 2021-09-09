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
IMAGE_METADATA_SHOW_POLICY = "volume_extension:volume_image_metadata:show"
IMAGE_METADATA_SET_POLICY = "volume_extension:volume_image_metadata:set"
IMAGE_METADATA_REMOVE_POLICY = "volume_extension:volume_image_metadata:remove"
UPDATE_ADMIN_METADATA_POLICY = "volume:update_volume_admin_metadata"


BASE_POLICY_NAME = 'volume:volume_metadata:%s'


deprecated_get_volume_metadata = base.CinderDeprecatedRule(
    name=GET_POLICY,
    check_str=base.RULE_ADMIN_OR_OWNER
)
deprecated_create_volume_metadata = base.CinderDeprecatedRule(
    name=CREATE_POLICY,
    check_str=base.RULE_ADMIN_OR_OWNER
)
deprecated_update_volume_metadata = base.CinderDeprecatedRule(
    name=UPDATE_POLICY,
    check_str=base.RULE_ADMIN_OR_OWNER
)
deprecated_delete_volume_metadata = base.CinderDeprecatedRule(
    name=DELETE_POLICY,
    check_str=base.RULE_ADMIN_OR_OWNER
)
# this is being replaced in Xena by 3 more granular policies
deprecated_image_metadata = base.CinderDeprecatedRule(
    name=IMAGE_METADATA_POLICY,
    check_str=base.RULE_ADMIN_OR_OWNER,
    deprecated_reason=(
        f'{IMAGE_METADATA_POLICY} has been replaced by more granular '
        'policies that separately govern show, set, and remove operations.')
)


volume_metadata_policies = [
    policy.DocumentedRuleDefault(
        name=GET_POLICY,
        check_str=base.SYSTEM_READER_OR_PROJECT_READER,
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
            },
            {
                'method': 'POST',
                'path': '/volumes/{volume_id}/action  (os-show_image_metadata)'
            }
        ],
        deprecated_rule=deprecated_get_volume_metadata,
    ),
    policy.DocumentedRuleDefault(
        name=CREATE_POLICY,
        check_str=base.SYSTEM_ADMIN_OR_PROJECT_MEMBER,
        description="Create volume metadata.",
        operations=[
            {
                'method': 'POST',
                'path': '/volumes/{volume_id}/metadata'
            }
        ],
        deprecated_rule=deprecated_create_volume_metadata,
    ),
    policy.DocumentedRuleDefault(
        name=UPDATE_POLICY,
        check_str=base.SYSTEM_ADMIN_OR_PROJECT_MEMBER,
        description=(
            "Replace a volume's metadata dictionary or update a single "
            "metadatum with a given key."),
        operations=[
            {
                'method': 'PUT',
                'path': '/volumes/{volume_id}/metadata'
            },
            {
                'method': 'PUT',
                'path': '/volumes/{volume_id}/metadata/{key}'
            }
        ],
        deprecated_rule=deprecated_update_volume_metadata,
    ),
    policy.DocumentedRuleDefault(
        name=DELETE_POLICY,
        check_str=base.SYSTEM_ADMIN_OR_PROJECT_MEMBER,
        description="Delete a volume's metadatum with the given key.",
        operations=[
            {
                'method': 'DELETE',
                'path': '/volumes/{volume_id}/metadata/{key}'
            }
        ],
        deprecated_rule=deprecated_delete_volume_metadata,
    ),
    policy.DocumentedRuleDefault(
        name=IMAGE_METADATA_SHOW_POLICY,
        check_str=base.SYSTEM_READER_OR_PROJECT_READER,
        description=(
            "Include a volume's image metadata in volume detail responses.  "
            "The ability to make these calls is governed by other policies."),
        operations=[
            {
                'method': 'GET',
                'path': '/volumes/detail'
            },
            {
                'method': 'GET',
                'path': '/volumes/{volume_id}'
            }
        ],
        # TODO: will need its own deprecated rule in Yoga
        deprecated_rule=deprecated_image_metadata,
    ),
    policy.DocumentedRuleDefault(
        name=IMAGE_METADATA_SET_POLICY,
        check_str=base.SYSTEM_ADMIN_OR_PROJECT_MEMBER,
        description="Set image metadata for a volume",
        operations=[
            {
                'method': 'POST',
                'path': '/volumes/{volume_id}/action (os-set_image_metadata)'
            }
        ],
        # TODO: will need its own deprecated rule in Yoga
        deprecated_rule=deprecated_image_metadata,
    ),
    policy.DocumentedRuleDefault(
        name=IMAGE_METADATA_REMOVE_POLICY,
        check_str=base.SYSTEM_ADMIN_OR_PROJECT_MEMBER,
        description="Remove specific image metadata from a volume",
        operations=[
            {
                'method': 'POST',
                'path': '/volumes/{volume_id}/action (os-unset_image_metadata)'
            }
        ],
        # TODO: will need its own deprecated rule in Yoga
        deprecated_rule=deprecated_image_metadata,
    ),
    policy.DocumentedRuleDefault(
        name=UPDATE_ADMIN_METADATA_POLICY,
        # TODO: deprecate checkstring in Yoga
        check_str=base.RULE_ADMIN_API,
        description=(
            "Update volume admin metadata. This permission is required "
            "to complete these API calls, though the ability to make these "
            "calls is governed by other policies."),
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
