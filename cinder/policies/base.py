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

RULE_ADMIN_OR_OWNER = 'rule:admin_or_owner'
RULE_ADMIN_API = 'rule:admin_api'

# Generic policy check string for system administrators. These are the people
# who need the highest level of authorization to operate the deployment.
# They're allowed to create, read, update, or delete any system-specific
# resource. They can also operate on project-specific resources where
# applicable (e.g., cleaning up volumes or backups)
SYSTEM_ADMIN = 'role:admin and system_scope:all'

# Generic policy check string for system users who don't require all the
# authorization that system administrators typically have. This persona, or
# check string, typically isn't used by default, but it's existence it useful
# in the event a deployment wants to offload some administrative action from
# system administrator to system members
SYSTEM_MEMBER = 'role:member and system_scope:all'

# Generic policy check string for read-only access to system-level resources.
# This persona is useful for someone who needs access for auditing or even
# support. These uses are also able to view project-specific resources where
# applicable (e.g., listing all volumes in the deployment, regardless of the
# project they belong to).
SYSTEM_READER = 'role:reader and system_scope:all'

# This check string is reserved for actions that require the highest level of
# authorization on a project or resources within the project (e.g., setting the
# default volume type for a project)
PROJECT_ADMIN = 'role:admin and project_id:%(project_id)s'

# This check string is the primary use case for typical end-users, who are
# working with resources that belong to a project (e.g., creating volumes and
# backups).
PROJECT_MEMBER = 'role:member and project_id:%(project_id)s'

# This check string should only be used to protect read-only project-specific
# resources. It should not be used to protect APIs that make writable changes
# (e.g., updating a volume or deleting a backup).
PROJECT_READER = 'role:reader and project_id:%(project_id)s'

# The following are common composite check strings that are useful for
# protecting APIs designed to operate with multiple scopes (e.g., a system
# administrator should be able to delete any volume in the deployment, a
# project member should only be able to delete volumes in their project).
SYSTEM_OR_DOMAIN_OR_PROJECT_ADMIN = 'rule:system_or_domain_or_project_admin'
SYSTEM_ADMIN_OR_PROJECT_MEMBER = (
    '(' + SYSTEM_ADMIN + ') or (' + PROJECT_MEMBER + ')'
)
SYSTEM_OR_PROJECT_MEMBER = (
    '(' + SYSTEM_MEMBER + ') or (' + PROJECT_MEMBER + ')'
)
SYSTEM_OR_PROJECT_READER = (
    '(' + SYSTEM_READER + ') or (' + PROJECT_READER + ')'
)
LEGACY_ADMIN_OR_PROJECT_MEMBER = (
    'role:admin or (role:member and project_id:%(project_id)s)'
)
LEGACY_ADMIN_OR_PROJECT_READER = (
    'role:admin or (role:reader and project_id:%(project_id)s)'
)

rules = [
    policy.RuleDefault('context_is_admin', 'role:admin',
                       description="Decides what is required for the "
                                   "'is_admin:True' check to succeed."),
    policy.RuleDefault('admin_or_owner',
                       'is_admin:True or (role:admin and '
                       'is_admin_project:True) or project_id:%(project_id)s',
                       description="Default rule for most non-Admin APIs."),
    policy.RuleDefault('admin_api',
                       'is_admin:True or (role:admin and '
                       'is_admin_project:True)',
                       description="Default rule for most Admin APIs."),
    policy.RuleDefault('system_or_domain_or_project_admin',
                       '(role:admin and system_scope:all) or '
                       '(role:admin and domain_id:%(domain_id)s) or '
                       '(role:admin and project_id:%(project_id)s)',
                       description="Default rule for admins of cloud, domain "
                                   "or a project."),
]


def list_rules():
    return rules
