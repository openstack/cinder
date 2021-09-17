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

from typing import Optional

from oslo_log import versionutils
from oslo_policy import policy

# General observations
# --------------------
# - This file uses the three "default roles" provided by Keystone during
#   the ``keystone-manage bootstrap`` operation.  These are 'admin', 'member',
#   and 'reader'.
#
# - The default Keystone installation implements an inheritance relation
#   between the roles:
#       'admin' is-a 'member' is-a 'reader'
#   More importantly, however, Keystone will actually populate the roles
#   appropriately.  Thus, someone with the 'admin' role on project X will also
#   have the 'member' and 'reader' roles on project X.  What this means for
#   us is that if we have a policy we want satisfied by someone with any of
#   the 'admin', 'member', or 'reader' roles, we do NOT need to do this:
#       "get-foo-policy": "role:admin or role:member or role:reader"
#   Instead we can simply say:
#       "get-foo-policy": "role:reader"
#   because we know that anyone who has been assigned the 'admin' role in
#   Keystone also has the 'member' and 'reader' roles, and anyone assigned
#   the 'member' role *also* has the 'reader' role.
#
# - How do I know what string to use?
#   Cinder maintains a policy matrix correlating REST API calls, policy
#   names, and what "personas" can perform them.  The "personas" are
#   abstract entities whose powers are supposed to be consistent across
#   OpenStack services.  The "personas" are implemented by each service
#   using the default Keystone roles and scopes ... but you have to be
#   careful, because for example, a "system-reader" persona is NOT simply
#   a read-only administrator (it's actually less).  See the policy matrix
#   for details.
#
# - This is probably obvious, but I'll say it anyway.  There is nothing
#   magic about the 'reader' role that guarantees that someone with *only*
#   that role can only do read-only kind of stuff in a service.  We (as the
#   Cinder service team) give it meaning by the way we define our policy
#   rules.  So if as a joke, we were to write rules that allowed someone
#   with only the 'reader' role to delete volumes in any project, there is
#   nothing Keystone could do about it.  So be careful.


# Private policy checkstrings
# ---------------------------
# "Private" strings should not be used outside of this file.  Add a new
# public string in the appropriate place if you need one.

# Generic policy check string for the persona we are calling 'system-admin'.
# Note: we aren't recognizing system scope in Xena, so we aren't actually
# using this check string yet.
_SYSTEM_ADMIN = 'role:admin and system_scope:all'
_LEGACY_SYSTEM_ADMIN = 'role:admin'

# Cinder doesn't plan to use this one.  It doesn't map to any of our
# supported personas.  It's only here in case you were wondering ...
# _SYSTEM_MEMBER = 'role:member and system_scope:all'

# Generic policy check string for the persona we are calling 'system-reader'.
_SYSTEM_READER = 'role:reader and system_scope:all'
# Note: In Xena, there isn't really a system-reader persona so make sure
# the system-admin can do this
_LEGACY_SYSTEM_READER = _LEGACY_SYSTEM_ADMIN

# Generic policy check string for the persona we are calling 'project-admin'.
# Note: We are not implementing this persona in Xena.  (Compare it to the
# _LEGACY_SYSTEM_ADMIN string above and you'll see why.)
_PROJECT_ADMIN = 'role:admin and project_id:%(project_id)s'

# Generic policy check string for the persona we are calling 'project-member'.
# Note: The 'and project_id:%(project_id)s' part makes this a project-scoped
# checkstring.
_PROJECT_MEMBER = 'role:member and project_id:%(project_id)s'

# Generic policy check string for the persona we are calling 'project-reader'.
_PROJECT_READER = 'role:reader and project_id:%(project_id)s'

# rule names
_YOGA_SYSTEM_READER_OR_PROJECT_READER = 'rule:system_reader_or_project_reader'

_YOGA_SYSTEM_ADMIN_OR_PROJECT_MEMBER = 'rule:system_admin_or_project_member'

_YOGA_SYSTEM_ADMIN_OR_PROJECT_ADMIN = 'rule:system_admin_or_project_admin'

_YOGA_SYSTEM_ADMIN_ONLY = 'rule:system_admin_only'

# rules
yoga_rule_defaults = [
    policy.RuleDefault('system_reader_or_project_reader',
                       f'({_SYSTEM_READER}) or ({_PROJECT_READER})',
                       description=("Grants permission for the following "
                                    "Cinder personas: system-admin, system-"
                                    "reader, project-admin, project-member, "
                                    "and project-reader")),
    policy.RuleDefault('system_admin_or_project_member',
                       f'({_SYSTEM_ADMIN}) or ({_PROJECT_MEMBER})',
                       description=("Grants permission for the following "
                                    "Cinder personas: system-admin, project-"
                                    "admin, and project-member")),
    policy.RuleDefault('system_admin_or_project_admin',
                       f'({_SYSTEM_ADMIN}) or ({_PROJECT_ADMIN})',
                       description=("Grants permission for the following "
                                    "Cinder personas: system-admin and "
                                    "project-admin")),
    policy.RuleDefault('system_admin_only',
                       f'({_SYSTEM_ADMIN})',
                       description=("Grants permission only to the system-"
                                    "admin persona.")),
]


# Public policy checkstrings for deprecations
# -------------------------------------------

# The XENA_* need to be public because we'll use them in CinderDeprecatedRules
# in the individual policy files when these are updated in Yoga.  They
# should *not* appear in any DocumentedRuleDefaults.

# we *call* it system reader for consistency with Yoga, but in Xena
# there isn't a system reader persona
XENA_SYSTEM_READER_OR_PROJECT_READER = (
    "rule:xena_system_admin_or_project_reader")

XENA_SYSTEM_ADMIN_OR_PROJECT_MEMBER = (
    "rule:xena_system_admin_or_project_member")

# This will not be used.  Rules appropriate for this checkstring will remain
# as RULE_ADMIN_API in Xena and won't be deprecated until Yoga development.
# XENA_SYSTEM_ADMIN_ONLY = "rule:xena_system_admin_only"
RULE_ADMIN_API = "rule:admin_api"

# TODO: xena rules to be removed in AA
xena_rule_defaults = [
    # these legacy rules are still used in Xena and will be used as the
    # checkstrings for CinderDeprecatedRules in Yoga and Z
    policy.RuleDefault('context_is_admin', 'role:admin',
                       description="Decides what is required for the "
                                   "'is_admin:True' check to succeed."),
    policy.RuleDefault('admin_api',
                       'is_admin:True or (role:admin and '
                       'is_admin_project:True)',
                       # FIXME: In Yoga, point out that is_admin_project
                       # is deprecated and operators should use system
                       # scope instead
                       description="Default rule for most Admin APIs."),
    # "pure" Xena rules
    policy.RuleDefault(
        'xena_system_admin_or_project_reader',
        f'({_LEGACY_SYSTEM_ADMIN}) or ({_PROJECT_READER})',
        description=("NOTE: this purely role-based rule recognizes only "
                     "project scope")),
    policy.RuleDefault(
        'xena_system_admin_or_project_member',
        f'({_LEGACY_SYSTEM_ADMIN}) or ({_PROJECT_MEMBER})',
        description=("NOTE: this purely role-based rule recognizes only "
                     "project scope")),
]


# Public policy checkstrings expressed as personas
# ------------------------------------------------

# TODO: update the following in Yoga
SYSTEM_READER_OR_PROJECT_READER = XENA_SYSTEM_READER_OR_PROJECT_READER
# SYSTEM_READER_OR_PROJECT_READER = _YOGA_SYSTEM_READER_OR_PROJECT_READER

SYSTEM_ADMIN_OR_PROJECT_MEMBER = XENA_SYSTEM_ADMIN_OR_PROJECT_MEMBER
# SYSTEM_ADMIN_OR_PROJECT_MEMBER = _YOGA_SYSTEM_ADMIN_OR_PROJECT_MEMBER

# We won't be using this one in Xena.  System-admin-only rules will NOT be
# modified during Xena development.
# SYSTEM_ADMIN_ONLY = XENA_SYSTEM_ADMIN_ONLY
# SYSTEM_ADMIN_ONLY = _YOGA_SYSTEM_ADMIN_ONLY


# Deprecation strategy
# --------------------
# We will be using the following strategy to transform Cinder policies
# from legacy Wallaby checkstrings to Keystone default-role-and-scope aware
# policies over the next few cycles:
#
# 1. In Xena, the Wallaby checkstrings are moved to CinderDeprecatedRules and
#    new checkstrings (using the three default roles but project scope only)
#    are defined in DocumentedRuleDefaults.  At this point, only the
#    three Cinder personas of system-admin, project-member, and project-reader
#    will be implemented, but to prepare for Yoga, we'll use the variables
#    defined in the "Public policy checkstrings expressed as personas" above.
#
#    EXCEPTION: any policies that are currently (i.e., during Xena development)
#    using "rule:admin_api" (which shows up in the policy files as
#    'base.RULE_ADMIN_API') will NOT be deprecated in Xena.  (They will be
#    deprecated in Yoga.)
#
# 2. In Yoga, the Xena checkstrings are moved to the CinderDeprecatedRules.
#    For example, if a DocumentedRuleDefault with
#        check_str=SYSTEM_READER_OR_PROJECT_READER
#    contains a deprecated_rule, find the definition of that
#    CinderDeprecatedRule in the file and change *its* checkstring to
#        check_str=XENA_SYSTEM_READER_OR_PROJECT_READER
#
#    The checkstrings in the DocumentedRuleDefaults will be updated
#    when we change the "Public policy checkstrings expressed as personas"
#    above to their _YOGA versions in this file--we will not have to manually
#    update the checkstrings in the individual files.
#
#    EXCEPTION: We'll need to add CinderDeprecatedRules for any policies that
#    don't currently (i.e., during Yoga development) have them.  (These will
#    be the "Admin API" calls that we didn't modify in Xena.)  Their current
#    checkstrings will be moved to the deprecated rules, and their new
#    checkstrings will be SYSTEM_ADMIN_ONLY.
#
#    OTHER UPDATES: All DocumentedRuleDefaults will need to have the
#    'scope_types' field added to them, for example,
#        scope_types=['system', 'project'],
#    or
#        scope_types['system'],
#    depending on the intended scope of the rule.
#
#    The Yoga checkstrings (using the three default roles + system scope) will
#    give us the full five Cinder personas.  After operators have made
#    appropriate adjustments to user and group role assignments in Keystone,
#    they will be able to use the new checkstrings by setting the
#    'enforce_new_defaults' and 'enforce_scope' options to appropriate
#    values in the [oslo_policy] section of their cinder configuration file.
#
# 3. In Z, we let the Yoga policy configuration bake to allow operators
#    to time to make the Keystone adjustments mentioned above before they
#    enable the Yoga rules.
#
# 4. In AA, we remove the CinderDeprecatedRules and adjust the
#    DocumentedRuleDefaults accordingly.

_XENA_DEPRECATED_REASON = (
    'Default policies now support the three Keystone default roles, namely '
    "'admin', 'member', and 'reader' to implement three Cinder "
    '"personas".  See "Policy Personas and Permissions" in the "Cinder '
    'Service Configuration" documentation (Xena release) for details.')

_YOGA_DEPRECATED_REASON = (
    'Default policies now support Keystone default roles and system scope to '
    'implement five Cinder "personas".  See "Policy Personas and Permissions" '
    'in the "Cinder Service Configuration" documentation (Yoga release) for '
    'details.')

# TODO: change these in Yoga
DEPRECATED_REASON = _XENA_DEPRECATED_REASON
DEPRECATED_SINCE = versionutils.deprecated.XENA


class CinderDeprecatedRule(policy.DeprecatedRule):
    """A DeprecatedRule subclass with pre-defined fields."""
    def __init__(self,
                 name: str,
                 check_str: str,
                 *,
                 deprecated_reason: Optional[str] = DEPRECATED_REASON,
                 deprecated_since: Optional[str] = DEPRECATED_SINCE,
                 ):
        super().__init__(
            name, check_str, deprecated_reason=deprecated_reason,
            deprecated_since=deprecated_since
        )


# This is used by the deprecated rules in the individual policy files
# in Xena.
# TODO: remove in Yoga
RULE_ADMIN_OR_OWNER = 'rule:admin_or_owner'

# FIXME: remove these when cinder.policies.default_types is updated
SYSTEM_OR_DOMAIN_OR_PROJECT_ADMIN = 'rule:system_or_domain_or_project_admin'
SYSTEM_ADMIN = _SYSTEM_ADMIN


YOGA_REMOVAL = 'DEPRECATED: This rule will be removed in the Yoga release.'
PADDING = ' ' * (70 - len(YOGA_REMOVAL))
# legacy rules to be removed in Yoga
legacy_rule_defaults = [
    policy.RuleDefault('admin_or_owner',
                       'is_admin:True or (role:admin and '
                       'is_admin_project:True) or project_id:%(project_id)s',
                       description=(f'{YOGA_REMOVAL}{PADDING}'
                                    'Default rule for most non-Admin APIs.')),
    # currently used only by cinder.policies.default_types
    policy.RuleDefault('system_or_domain_or_project_admin',
                       '(role:admin and system_scope:all) or '
                       '(role:admin and domain_id:%(domain_id)s) or '
                       '(role:admin and project_id:%(project_id)s)',
                       description=(f'{YOGA_REMOVAL}{PADDING}'
                                    "Default rule for admins of cloud, domain "
                                    "or a project.")),
]


def list_rules():
    # TODO: update in Yoga and AA
    #   xena: legacy_rule_defaults + xena_rule_defaults
    #   yoga: xena_rule_defaults + yoga_rule_defaults
    #     AA: yoga_rule_defaults only
    return legacy_rule_defaults + xena_rule_defaults
