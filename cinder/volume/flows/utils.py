# -*- coding: utf-8 -*-

# vim: tabstop=4 shiftwidth=4 softtabstop=4

#    Copyright (C) 2013 Yahoo! Inc. All Rights Reserved.
#    Copyright (c) 2013 OpenStack, LLC.
#    Copyright 2010 United States Government as represented by the
#    Administrator of the National Aeronautics and Space Administration.
#    All Rights Reserved.
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

from cinder.openstack.common import log as logging

LOG = logging.getLogger(__name__)


def attach_debug_listeners(flow):
    """Sets up a nice set of debug listeners for the flow.

    These listeners will log when tasks/flows are transitioning from state to
    state so that said states can be seen in the debug log output which is very
    useful for figuring out where problems are occuring.
    """

    def flow_log_change(state, details):
        # TODO(harlowja): the bug 1214083 is causing problems
        LOG.debug(_("%(flow)s has moved into state %(state)s from state"
                    " %(old_state)s") % {'state': state,
                                         'old_state': details.get('old_state'),
                                         'flow': str(details['flow'])})

    def task_log_change(state, details):
        # TODO(harlowja): the bug 1214083 is causing problems
        LOG.debug(_("%(flow)s has moved %(runner)s into state %(state)s with"
                    " result: %(result)s") % {'state': state,
                                              'flow': str(details['flow']),
                                              'runner': str(details['runner']),
                                              'result': details.get('result')})

    # Register * for all state changes (and not selective state changes to be
    # called upon) since all the changes is more useful.
    flow.notifier.register('*', flow_log_change)
    flow.task_notifier.register('*', task_log_change)
    return flow
