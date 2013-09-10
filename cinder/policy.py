# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2011 OpenStack Foundation
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

"""Policy Engine For Cinder"""


from oslo.config import cfg

from cinder import exception
from cinder.openstack.common import policy
from cinder import utils


policy_opts = [
    cfg.StrOpt('policy_file',
               default='policy.json',
               help=_('JSON file representing policy')),
    cfg.StrOpt('policy_default_rule',
               default='default',
               help=_('Rule checked when requested rule is not found')), ]

CONF = cfg.CONF
CONF.register_opts(policy_opts)

_POLICY_PATH = None
_POLICY_CACHE = {}


def reset():
    global _POLICY_PATH
    global _POLICY_CACHE
    _POLICY_PATH = None
    _POLICY_CACHE = {}
    policy.reset()


def init():
    global _POLICY_PATH
    global _POLICY_CACHE
    if not _POLICY_PATH:
        _POLICY_PATH = utils.find_config(CONF.policy_file)
    utils.read_cached_file(_POLICY_PATH, _POLICY_CACHE,
                           reload_func=_set_brain)


def _set_brain(data):
    default_rule = CONF.policy_default_rule
    policy.set_brain(policy.Brain.load_json(data, default_rule))


def enforce_action(context, action):
    """Checks that the action can be done by the given context.

    Applies a check to ensure the context's project_id and user_id can be
    applied to the given action using the policy enforcement api.
    """

    target = {
        'project_id': context.project_id,
        'user_id': context.user_id,
    }
    enforce(context, action, target)


def enforce(context, action, target):
    """Verifies that the action is valid on the target in this context.

       :param context: cinder context
       :param action: string representing the action to be checked
           this should be colon separated for clarity.
           i.e. ``compute:create_instance``,
           ``compute:attach_volume``,
           ``volume:attach_volume``

       :param object: dictionary representing the object of the action
           for object creation this should be a dictionary representing the
           location of the object e.g. ``{'project_id': context.project_id}``

       :raises cinder.exception.PolicyNotAuthorized: if verification fails.

    """
    init()

    match_list = ('rule:%s' % action,)
    credentials = context.to_dict()

    policy.enforce(match_list, target, credentials,
                   exception.PolicyNotAuthorized, action=action)


def check_is_admin(roles):
    """Whether or not roles contains 'admin' role according to policy setting.

    """
    init()

    action = 'context_is_admin'
    match_list = ('rule:%s' % action,)
    # include project_id on target to avoid KeyError if context_is_admin
    # policy definition is missing, and default admin_or_owner rule
    # attempts to apply.  Since our credentials dict does not include a
    # project_id, this target can never match as a generic rule.
    target = {'project_id': ''}
    credentials = {'roles': roles}

    return policy.enforce(match_list, target, credentials)
