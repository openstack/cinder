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

SYSTEM_ADMIN = 'role:admin and system_scope:all'

SYSTEM_OR_DOMAIN_OR_PROJECT_ADMIN = 'rule:system_or_domain_or_project_admin'

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
