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

volume_action_policies = [
    policy.DocumentedRuleDefault(
        name=EXTEND_POLICY,
        check_str=base.RULE_ADMIN_OR_OWNER,
        description="Extend a volume.",
        operations=[
            {
                'method': 'POST',
                'path': '/volumes/{volume_id}/action (os-extend)'
            }
        ]),
    policy.DocumentedRuleDefault(
        name=EXTEND_ATTACHED_POLICY,
        check_str=base.RULE_ADMIN_OR_OWNER,
        description="Extend a attached volume.",
        operations=[
            {
                'method': 'POST',
                'path': '/volumes/{volume_id}/action (os-extend)'
            }
        ]),
    policy.DocumentedRuleDefault(
        name=REVERT_POLICY,
        check_str=base.RULE_ADMIN_OR_OWNER,
        description="Revert a volume to a snapshot.",
        operations=[
            {
                'method': 'POST',
                'path': '/volumes/{volume_id}/action (revert)'
            }
        ]),
    policy.DocumentedRuleDefault(
        name=RESET_STATUS,
        check_str=base.RULE_ADMIN_API,
        description="Reset status of a volume.",
        operations=[
            {
                'method': 'POST',
                'path': '/volumes/{volume_id}/action (os-reset_status)'
            }
        ]),
    policy.DocumentedRuleDefault(
        name=RETYPE_POLICY,
        check_str=base.RULE_ADMIN_OR_OWNER,
        description="Retype a volume.",
        operations=[
            {
                'method': 'POST',
                'path': '/volumes/{volume_id}/action (os-retype)'
            }
        ]),
    policy.DocumentedRuleDefault(
        name=UPDATE_READONLY_POLICY,
        check_str=base.RULE_ADMIN_OR_OWNER,
        description="Update a volume's readonly flag.",
        operations=[
            {
                'method': 'POST',
                'path': '/volumes/{volume_id}/action (os-update_readonly_flag)'
            }
        ]),
    policy.DocumentedRuleDefault(
        name=FORCE_DELETE_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="Force delete a volume.",
        operations=[
            {
                'method': 'POST',
                'path': '/volumes/{volume_id}/action (os-force_delete)'
            }
        ]),
    policy.DocumentedRuleDefault(
        name=UPLOAD_PUBLIC_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="Upload a volume to image with public visibility.",
        operations=[
            {
                'method': 'POST',
                'path': '/volumes/{volume_id}/action (os-volume_upload_image)'
            }
        ]),
    policy.DocumentedRuleDefault(
        name=UPLOAD_IMAGE_POLICY,
        check_str=base.RULE_ADMIN_OR_OWNER,
        description="Upload a volume to image.",
        operations=[
            {
                'method': 'POST',
                'path': '/volumes/{volume_id}/action (os-volume_upload_image)'
            }
        ]),
    policy.DocumentedRuleDefault(
        name=FORCE_DETACH_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="Force detach a volume.",
        operations=[
            {
                'method': 'POST',
                'path': '/volumes/{volume_id}/action (os-force_detach)'
            }
        ]),
    policy.DocumentedRuleDefault(
        name=MIGRATE_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="migrate a volume to a specified host.",
        operations=[
            {
                'method': 'POST',
                'path': '/volumes/{volume_id}/action (os-migrate_volume)'
            }
        ]),
    policy.DocumentedRuleDefault(
        name=MIGRATE_COMPLETE_POLICY,
        check_str=base.RULE_ADMIN_API,
        description="Complete a volume migration.",
        operations=[{
            'method': 'POST',
            'path':
                '/volumes/{volume_id}/action (os-migrate_volume_completion)'}
        ]),
    policy.DocumentedRuleDefault(
        name=INITIALIZE_POLICY,
        check_str=base.RULE_ADMIN_OR_OWNER,
        description="Initialize volume attachment.",
        operations=[{
            'method': 'POST',
            'path':
                '/volumes/{volume_id}/action (os-initialize_connection)'}
        ]),
    policy.DocumentedRuleDefault(
        name=TERMINATE_POLICY,
        check_str=base.RULE_ADMIN_OR_OWNER,
        description="Terminate volume attachment.",
        operations=[{
            'method': 'POST',
            'path':
                '/volumes/{volume_id}/action (os-terminate_connection)'}
        ]),
    policy.DocumentedRuleDefault(
        name=ROLL_DETACHING_POLICY,
        check_str=base.RULE_ADMIN_OR_OWNER,
        description="Roll back volume status to 'in-use'.",
        operations=[{
            'method': 'POST',
            'path':
                '/volumes/{volume_id}/action (os-roll_detaching)'}
        ]),
    policy.DocumentedRuleDefault(
        name=RESERVE_POLICY,
        check_str=base.RULE_ADMIN_OR_OWNER,
        description="Mark volume as reserved.",
        operations=[{
            'method': 'POST',
            'path':
                '/volumes/{volume_id}/action (os-reserve)'}
        ]),
    policy.DocumentedRuleDefault(
        name=UNRESERVE_POLICY,
        check_str=base.RULE_ADMIN_OR_OWNER,
        description="Unmark volume as reserved.",
        operations=[{
            'method': 'POST',
            'path':
                '/volumes/{volume_id}/action (os-unreserve)'}
        ]),
    policy.DocumentedRuleDefault(
        name=BEGIN_DETACHING_POLICY,
        check_str=base.RULE_ADMIN_OR_OWNER,
        description="Begin detach volumes.",
        operations=[{
            'method': 'POST',
            'path':
                '/volumes/{volume_id}/action (os-begin_detaching)'}
        ]),
    policy.DocumentedRuleDefault(
        name=ATTACH_POLICY,
        check_str=base.RULE_ADMIN_OR_OWNER,
        description="Add attachment metadata.",
        operations=[{
            'method': 'POST',
            'path':
                '/volumes/{volume_id}/action (os-attach)'}
        ]),
    policy.DocumentedRuleDefault(
        name=DETACH_POLICY,
        check_str=base.RULE_ADMIN_OR_OWNER,
        description="Clear attachment metadata.",
        operations=[{
            'method': 'POST',
            'path':
                '/volumes/{volume_id}/action (os-detach)'}
        ]),
]


def list_rules():
    return volume_action_policies
