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


EXTEND_POLICY = "volume:extend"
EXTEND_ATTACHED_POLICY = "volume:extend_attached_volume"
REVERT_POLICY = "volume:revert_to_snapshot"
RESET_STATUS = "volume_extension:volume_admin_actions:reset_status"
RETYPE_POLICY = "volume:retype"
UPDATE_READONLY_POLICY = "volume:update_readonly_flag"
FORCE_DELETE_POLICY = "volume_extension:volume_admin_actions:force_delete"
FORCE_DETACH_POLICY = "volume_extension:volume_admin_actions:force_detach"
UPLOAD_PUBLIC_POLICY = "volume_extension:volume_actions:upload_public"
UPLOAD_IMAGE_POLICY = "volume_extension:volume_actions:upload_image"
MIGRATE_POLICY = "volume_extension:volume_admin_actions:migrate_volume"
MIGRATE_COMPLETE_POLICY = \
    "volume_extension:volume_admin_actions:migrate_volume_completion"
DETACH_POLICY = "volume_extension:volume_actions:detach"
ATTACH_POLICY = "volume_extension:volume_actions:attach"
BEGIN_DETACHING_POLICY = "volume_extension:volume_actions:begin_detaching"
UNRESERVE_POLICY = "volume_extension:volume_actions:unreserve"
RESERVE_POLICY = "volume_extension:volume_actions:reserve"
ROLL_DETACHING_POLICY = "volume_extension:volume_actions:roll_detaching"
TERMINATE_POLICY = "volume_extension:volume_actions:terminate_connection"
INITIALIZE_POLICY = "volume_extension:volume_actions:initialize_connection"

deprecated_extend_policy = base.CinderDeprecatedRule(
    name=EXTEND_POLICY,
    check_str=base.RULE_ADMIN_OR_OWNER
)
deprecated_extend_attached_policy = base.CinderDeprecatedRule(
    name=EXTEND_ATTACHED_POLICY,
    check_str=base.RULE_ADMIN_OR_OWNER
)
deprecated_revert_policy = base.CinderDeprecatedRule(
    name=REVERT_POLICY,
    check_str=base.RULE_ADMIN_OR_OWNER
)
deprecated_retype_policy = base.CinderDeprecatedRule(
    name=RETYPE_POLICY,
    check_str=base.RULE_ADMIN_OR_OWNER
)
deprecated_update_only_policy = base.CinderDeprecatedRule(
    name=UPDATE_READONLY_POLICY,
    check_str=base.RULE_ADMIN_OR_OWNER
)
deprecated_upload_image_policy = base.CinderDeprecatedRule(
    name=UPLOAD_IMAGE_POLICY,
    check_str=base.RULE_ADMIN_OR_OWNER
)
deprecated_initialize_policy = base.CinderDeprecatedRule(
    name=INITIALIZE_POLICY,
    check_str=base.RULE_ADMIN_OR_OWNER
)
deprecated_terminate_policy = base.CinderDeprecatedRule(
    name=TERMINATE_POLICY,
    check_str=base.RULE_ADMIN_OR_OWNER
)
deprecated_roll_detaching_policy = base.CinderDeprecatedRule(
    name=ROLL_DETACHING_POLICY,
    check_str=base.RULE_ADMIN_OR_OWNER
)
deprecated_reserve_policy = base.CinderDeprecatedRule(
    name=RESERVE_POLICY,
    check_str=base.RULE_ADMIN_OR_OWNER
)
deprecated_unreserve_policy = base.CinderDeprecatedRule(
    name=UNRESERVE_POLICY,
    check_str=base.RULE_ADMIN_OR_OWNER
)
deprecated_begin_detaching_policy = base.CinderDeprecatedRule(
    name=BEGIN_DETACHING_POLICY,
    check_str=base.RULE_ADMIN_OR_OWNER
)
deprecated_attach_policy = base.CinderDeprecatedRule(
    name=ATTACH_POLICY,
    check_str=base.RULE_ADMIN_OR_OWNER
)
deprecated_detach_policy = base.CinderDeprecatedRule(
    name=DETACH_POLICY,
    check_str=base.RULE_ADMIN_OR_OWNER
)

volume_action_policies = [
    policy.DocumentedRuleDefault(
        name=EXTEND_POLICY,
        check_str=base.SYSTEM_ADMIN_OR_PROJECT_MEMBER,
        description="Extend a volume.",
        operations=[
            {
                'method': 'POST',
                'path': '/volumes/{volume_id}/action (os-extend)'
            }
        ],
        deprecated_rule=deprecated_extend_policy,
    ),
    policy.DocumentedRuleDefault(
        name=EXTEND_ATTACHED_POLICY,
        check_str=base.SYSTEM_ADMIN_OR_PROJECT_MEMBER,
        description="Extend a attached volume.",
        operations=[
            {
                'method': 'POST',
                'path': '/volumes/{volume_id}/action (os-extend)'
            }
        ],
        deprecated_rule=deprecated_extend_attached_policy,
    ),
    policy.DocumentedRuleDefault(
        name=REVERT_POLICY,
        check_str=base.SYSTEM_ADMIN_OR_PROJECT_MEMBER,
        description="Revert a volume to a snapshot.",
        operations=[
            {
                'method': 'POST',
                'path': '/volumes/{volume_id}/action (revert)'
            }
        ],
        deprecated_rule=deprecated_revert_policy,
    ),
    policy.DocumentedRuleDefault(
        name=RESET_STATUS,
        check_str=base.RULE_ADMIN_API,
        description="Reset status of a volume.",
        operations=[
            {
                'method': 'POST',
                'path': '/volumes/{volume_id}/action (os-reset_status)'
            }
        ],
    ),
    policy.DocumentedRuleDefault(
        name=RETYPE_POLICY,
        check_str=base.SYSTEM_ADMIN_OR_PROJECT_MEMBER,
        description="Retype a volume.",
        operations=[
            {
                'method': 'POST',
                'path': '/volumes/{volume_id}/action (os-retype)'
            }
        ],
        deprecated_rule=deprecated_retype_policy,
    ),
    policy.DocumentedRuleDefault(
        name=UPDATE_READONLY_POLICY,
        check_str=base.SYSTEM_ADMIN_OR_PROJECT_MEMBER,
        description="Update a volume's readonly flag.",
        operations=[
            {
                'method': 'POST',
                'path': '/volumes/{volume_id}/action (os-update_readonly_flag)'
            }
        ],
        deprecated_rule=deprecated_update_only_policy,
    ),
    policy.DocumentedRuleDefault(
        name=FORCE_DELETE_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="Force delete a volume.",
        operations=[
            {
                'method': 'POST',
                'path': '/volumes/{volume_id}/action (os-force_delete)'
            }
        ],
    ),
    policy.DocumentedRuleDefault(
        name=UPLOAD_PUBLIC_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="Upload a volume to image with public visibility.",
        operations=[
            {
                'method': 'POST',
                'path': '/volumes/{volume_id}/action (os-volume_upload_image)'
            }
        ],
    ),
    policy.DocumentedRuleDefault(
        name=UPLOAD_IMAGE_POLICY,
        check_str=base.SYSTEM_ADMIN_OR_PROJECT_MEMBER,
        description="Upload a volume to image.",
        operations=[
            {
                'method': 'POST',
                'path': '/volumes/{volume_id}/action (os-volume_upload_image)'
            }
        ],
        deprecated_rule=deprecated_upload_image_policy,
    ),
    policy.DocumentedRuleDefault(
        name=FORCE_DETACH_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="Force detach a volume.",
        operations=[
            {
                'method': 'POST',
                'path': '/volumes/{volume_id}/action (os-force_detach)'
            }
        ],
    ),
    policy.DocumentedRuleDefault(
        name=MIGRATE_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="migrate a volume to a specified host.",
        operations=[
            {
                'method': 'POST',
                'path': '/volumes/{volume_id}/action (os-migrate_volume)'
            }
        ],
    ),
    policy.DocumentedRuleDefault(
        name=MIGRATE_COMPLETE_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="Complete a volume migration.",
        operations=[{
            'method': 'POST',
            'path':
                '/volumes/{volume_id}/action (os-migrate_volume_completion)'}
        ],
    ),
    policy.DocumentedRuleDefault(
        name=INITIALIZE_POLICY,
        check_str=base.SYSTEM_ADMIN_OR_PROJECT_MEMBER,
        description="Initialize volume attachment.",
        operations=[{
            'method': 'POST',
            'path':
                '/volumes/{volume_id}/action (os-initialize_connection)'}
        ],
        deprecated_rule=deprecated_initialize_policy,
    ),
    policy.DocumentedRuleDefault(
        name=TERMINATE_POLICY,
        check_str=base.SYSTEM_ADMIN_OR_PROJECT_MEMBER,
        description="Terminate volume attachment.",
        operations=[{
            'method': 'POST',
            'path':
                '/volumes/{volume_id}/action (os-terminate_connection)'}
        ],
        deprecated_rule=deprecated_terminate_policy,
    ),
    policy.DocumentedRuleDefault(
        name=ROLL_DETACHING_POLICY,
        check_str=base.SYSTEM_ADMIN_OR_PROJECT_MEMBER,
        description="Roll back volume status to 'in-use'.",
        operations=[{
            'method': 'POST',
            'path':
                '/volumes/{volume_id}/action (os-roll_detaching)'}
        ],
        deprecated_rule=deprecated_roll_detaching_policy,
    ),
    policy.DocumentedRuleDefault(
        name=RESERVE_POLICY,
        check_str=base.SYSTEM_ADMIN_OR_PROJECT_MEMBER,
        description="Mark volume as reserved.",
        operations=[{
            'method': 'POST',
            'path':
                '/volumes/{volume_id}/action (os-reserve)'}
        ],
        deprecated_rule=deprecated_reserve_policy,
    ),
    policy.DocumentedRuleDefault(
        name=UNRESERVE_POLICY,
        check_str=base.SYSTEM_ADMIN_OR_PROJECT_MEMBER,
        description="Unmark volume as reserved.",
        operations=[{
            'method': 'POST',
            'path':
                '/volumes/{volume_id}/action (os-unreserve)'}
        ],
        deprecated_rule=deprecated_unreserve_policy,
    ),
    policy.DocumentedRuleDefault(
        name=BEGIN_DETACHING_POLICY,
        check_str=base.SYSTEM_ADMIN_OR_PROJECT_MEMBER,
        description="Begin detach volumes.",
        operations=[{
            'method': 'POST',
            'path':
                '/volumes/{volume_id}/action (os-begin_detaching)'}
        ],
        deprecated_rule=deprecated_begin_detaching_policy,
    ),
    policy.DocumentedRuleDefault(
        name=ATTACH_POLICY,
        check_str=base.SYSTEM_ADMIN_OR_PROJECT_MEMBER,
        description="Add attachment metadata.",
        operations=[{
            'method': 'POST',
            'path':
                '/volumes/{volume_id}/action (os-attach)'}
        ],
        deprecated_rule=deprecated_attach_policy,
    ),
    policy.DocumentedRuleDefault(
        name=DETACH_POLICY,
        check_str=base.SYSTEM_ADMIN_OR_PROJECT_MEMBER,
        description="Clear attachment metadata.",
        operations=[{
            'method': 'POST',
            'path':
                '/volumes/{volume_id}/action (os-detach)'}
        ],
        deprecated_rule=deprecated_detach_policy,
    ),
]


def list_rules():
    return volume_action_policies
