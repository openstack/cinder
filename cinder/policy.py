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

CONF = cfg.CONF

_ENFORCER = None


def init():
    global _ENFORCER
    if not _ENFORCER:
        _ENFORCER = policy.Enforcer()


def enforce_action(context, action):
    """Checks that the action can be done by the given context.

    Applies a check to ensure the context's project_id and user_id can be
    applied to the given action using the policy enforcement api.
    """

    return enforce(context, action, {'project_id': context.project_id,
                                     'user_id': context.user_id})


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

       :raises PolicyNotAuthorized: if verification fails.

    """
    init()

    return _ENFORCER.enforce(action, target, context.to_dict(),
                             do_raise=True,
                             exc=exception.PolicyNotAuthorized,
                             action=action)


def check_is_admin(roles):
    """Whether or not roles contains 'admin' role according to policy setting.

    """
    init()

    # include project_id on target to avoid KeyError if context_is_admin
    # policy definition is missing, and default admin_or_owner rule
    # attempts to apply.  Since our credentials dict does not include a
    # project_id, this target can never match as a generic rule.
    target = {'project_id': ''}
    credentials = {'roles': roles}

    return _ENFORCER.enforce('context_is_admin', target, credentials)
