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


CREATE_POLICY = "volume:create"
CREATE_FROM_IMAGE_POLICY = "volume:create_from_image"
GET_POLICY = "volume:get"
GET_ALL_POLICY = "volume:get_all"
UPDATE_POLICY = "volume:update"
DELETE_POLICY = "volume:delete"
FORCE_DELETE_POLICY = "volume:force_delete"
HOST_ATTRIBUTE_POLICY = "volume_extension:volume_host_attribute"
TENANT_ATTRIBUTE_POLICY = "volume_extension:volume_tenant_attribute"
MIG_ATTRIBUTE_POLICY = "volume_extension:volume_mig_status_attribute"
ENCRYPTION_METADATA_POLICY = "volume_extension:volume_encryption_metadata"
MULTIATTACH_POLICY = "volume:multiattach"

deprecated_create_volume = base.CinderDeprecatedRule(
    name=CREATE_POLICY,
    check_str=""
)
deprecated_create_volume_from_image = base.CinderDeprecatedRule(
    name=CREATE_FROM_IMAGE_POLICY,
    check_str=""
)
deprecated_get_volume = base.CinderDeprecatedRule(
    name=GET_POLICY,
    check_str=base.RULE_ADMIN_OR_OWNER
)
deprecated_get_all_volumes = base.CinderDeprecatedRule(
    name=GET_ALL_POLICY,
    check_str=base.RULE_ADMIN_OR_OWNER
)
deprecated_update_volume = base.CinderDeprecatedRule(
    name=UPDATE_POLICY,
    check_str=base.RULE_ADMIN_OR_OWNER
)
deprecated_delete_volume = base.CinderDeprecatedRule(
    name=DELETE_POLICY,
    check_str=base.RULE_ADMIN_OR_OWNER
)
deprecated_get_tenant_attributes = base.CinderDeprecatedRule(
    name=TENANT_ATTRIBUTE_POLICY,
    check_str=base.RULE_ADMIN_OR_OWNER
)
deprecated_get_encryption_metadata = base.CinderDeprecatedRule(
    name=ENCRYPTION_METADATA_POLICY,
    check_str=base.RULE_ADMIN_OR_OWNER
)
deprecated_create_multiattach_volume = base.CinderDeprecatedRule(
    name=MULTIATTACH_POLICY,
    check_str=base.RULE_ADMIN_OR_OWNER
)


volumes_policies = [
    policy.DocumentedRuleDefault(
        name=CREATE_POLICY,
        check_str=base.SYSTEM_ADMIN_OR_PROJECT_MEMBER,
        description="Create volume.",
        operations=[
            {
                'method': 'POST',
                'path': '/volumes'
            }
        ],
        deprecated_rule=deprecated_create_volume
    ),
    policy.DocumentedRuleDefault(
        name=CREATE_FROM_IMAGE_POLICY,
        check_str=base.SYSTEM_ADMIN_OR_PROJECT_MEMBER,
        description="Create volume from image.",
        operations=[
            {
                'method': 'POST',
                'path': '/volumes'
            }
        ],
        deprecated_rule=deprecated_create_volume_from_image
    ),
    policy.DocumentedRuleDefault(
        name=GET_POLICY,
        check_str=base.SYSTEM_READER_OR_PROJECT_READER,
        description="Show volume.",
        operations=[
            {
                'method': 'GET',
                'path': '/volumes/{volume_id}'
            }
        ],
        deprecated_rule=deprecated_get_volume
    ),
    policy.DocumentedRuleDefault(
        name=GET_ALL_POLICY,
        check_str=base.SYSTEM_READER_OR_PROJECT_READER,
        description="List volumes or get summary of volumes.",
        operations=[
            {
                'method': 'GET',
                'path': '/volumes'
            },
            {
                'method': 'GET',
                'path': '/volumes/detail'
            },
            {
                'method': 'GET',
                'path': '/volumes/summary'
            }
        ],
        deprecated_rule=deprecated_get_all_volumes
    ),
    policy.DocumentedRuleDefault(
        name=UPDATE_POLICY,
        check_str=base.SYSTEM_ADMIN_OR_PROJECT_MEMBER,
        description="Update volume or update a volume's bootable status.",
        operations=[
            {
                'method': 'PUT',
                'path': '/volumes'
            },
            # The API below calls the volume update API internally, which in
            # turn enforces the update policy.
            {
                'method': 'POST',
                'path': '/volumes/{volume_id}/action (os-set_bootable)'
            }
        ],
        deprecated_rule=deprecated_update_volume
    ),
    policy.DocumentedRuleDefault(
        name=DELETE_POLICY,
        check_str=base.SYSTEM_ADMIN_OR_PROJECT_MEMBER,
        description="Delete volume.",
        operations=[
            {
                'method': 'DELETE',
                'path': '/volumes/{volume_id}'
            }
        ],
        deprecated_rule=deprecated_delete_volume
    ),
    policy.DocumentedRuleDefault(
        name=FORCE_DELETE_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="Force Delete a volume.",
        operations=[
            {
                'method': 'DELETE',
                'path': '/volumes/{volume_id}'
            }
        ],
    ),
    policy.DocumentedRuleDefault(
        name=HOST_ATTRIBUTE_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="List or show volume with host attribute.",
        operations=[
            {
                'method': 'GET',
                'path': '/volumes/{volume_id}'
            },
            {
                'method': 'GET',
                'path': '/volumes/detail'
            }
        ]),
    policy.DocumentedRuleDefault(
        name=TENANT_ATTRIBUTE_POLICY,
        check_str=base.SYSTEM_READER_OR_PROJECT_READER,
        description="List or show volume with tenant attribute.",
        operations=[
            {
                'method': 'GET',
                'path': '/volumes/{volume_id}'
            },
            {
                'method': 'GET',
                'path': '/volumes/detail'
            }
        ],
        deprecated_rule=deprecated_get_tenant_attributes
    ),
    policy.DocumentedRuleDefault(
        name=MIG_ATTRIBUTE_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="List or show volume with migration status attribute.",
        operations=[
            {
                'method': 'GET',
                'path': '/volumes/{volume_id}'
            },
            {
                'method': 'GET',
                'path': '/volumes/detail'
            }
        ]),
    policy.DocumentedRuleDefault(
        name=ENCRYPTION_METADATA_POLICY,
        check_str=base.SYSTEM_READER_OR_PROJECT_READER,
        description="Show volume's encryption metadata.",
        operations=[
            {
                'method': 'GET',
                'path': '/volumes/{volume_id}/encryption'
            },
            {
                'method': 'GET',
                'path': '/volumes/{volume_id}/encryption/{encryption_key}'
            }
        ],
        deprecated_rule=deprecated_get_encryption_metadata
    ),
    policy.DocumentedRuleDefault(
        name=MULTIATTACH_POLICY,
        check_str=base.SYSTEM_ADMIN_OR_PROJECT_MEMBER,
        description="Create multiattach capable volume.",
        operations=[
            {
                'method': 'POST',
                'path': '/volumes'
            }
        ],
        deprecated_rule=deprecated_create_multiattach_volume
    ),
]


def list_rules():
    return volumes_policies
