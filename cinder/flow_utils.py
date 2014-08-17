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

import logging as base_logging

# For more information please visit: https://wiki.openstack.org/wiki/TaskFlow
from taskflow.listeners import base as base_listener
from taskflow import states
from taskflow import task
from taskflow.utils import misc

from cinder.i18n import _
from cinder.openstack.common import log as logging

LOG = logging.getLogger(__name__)


def _make_task_name(cls, addons=None):
    """Makes a pretty name for a task class."""
    base_name = ".".join([cls.__module__, cls.__name__])
    extra = ''
    if addons:
        extra = ';%s' % (", ".join([str(a) for a in addons]))
    return base_name + extra


class CinderTask(task.Task):
    """The root task class for all cinder tasks.

    It automatically names the given task using the module and class that
    implement the given task as the task name.
    """

    def __init__(self, addons=None, **kwargs):
        super(CinderTask, self).__init__(_make_task_name(self.__class__,
                                                         addons),
                                         **kwargs)


class DynamicLogListener(base_listener.ListenerBase):
    """This is used to attach to taskflow engines while they are running.

    It provides a bunch of useful features that expose the actions happening
    inside a taskflow engine, which can be useful for developers for debugging,
    for operations folks for monitoring and tracking of the resource actions
    and more...
    """

    def __init__(self, engine,
                 task_listen_for=(misc.Notifier.ANY,),
                 flow_listen_for=(misc.Notifier.ANY,),
                 logger=None):
        super(DynamicLogListener, self).__init__(
            engine,
            task_listen_for=task_listen_for,
            flow_listen_for=flow_listen_for)
        if logger is None:
            self._logger = LOG
        else:
            self._logger = logger

    def _flow_receiver(self, state, details):
        # Gets called on flow state changes.
        level = base_logging.DEBUG
        if state in (states.FAILURE, states.REVERTED):
            level = base_logging.WARNING
        self._logger.log(level,
                         _("Flow '%(flow_name)s' (%(flow_uuid)s) transitioned"
                           " into state '%(state)s' from state"
                           " '%(old_state)s'") %
                         {'flow_name': details['flow_name'],
                          'flow_uuid': details['flow_uuid'],
                          'state': state,
                          'old_state': details.get('old_state')})

    def _task_receiver(self, state, details):
        # Gets called on task state changes.
        if 'result' in details and state in base_listener.FINISH_STATES:
            # If the task failed, it's useful to show the exception traceback
            # and any other available exception information.
            result = details.get('result')
            if isinstance(result, misc.Failure):
                self._logger.warn(_("Task '%(task_name)s' (%(task_uuid)s)"
                                    " transitioned into state '%(state)s'") %
                                  {'task_name': details['task_name'],
                                   'task_uuid': details['task_uuid'],
                                   'state': state},
                                  exc_info=tuple(result.exc_info))
            else:
                # Otherwise, depending on the enabled logging level/state we
                # will show or hide results that the task may have produced
                # during execution.
                level = base_logging.DEBUG
                if state == states.FAILURE:
                    level = base_logging.WARNING
                if (self._logger.isEnabledFor(base_logging.DEBUG) or
                        state == states.FAILURE):
                    self._logger.log(level,
                                     _("Task '%(task_name)s' (%(task_uuid)s)"
                                       " transitioned into state '%(state)s'"
                                       " with result '%(result)s'") %
                                     {'task_name': details['task_name'],
                                      'task_uuid': details['task_uuid'],
                                      'state': state, 'result': result})
                else:
                    self._logger.log(level,
                                     _("Task '%(task_name)s' (%(task_uuid)s)"
                                       " transitioned into state"
                                       " '%(state)s'") %
                                     {'task_name': details['task_name'],
                                      'task_uuid': details['task_uuid'],
                                      'state': state})
        else:
            level = base_logging.DEBUG
            if state in (states.REVERTING, states.RETRYING):
                level = base_logging.WARNING
            self._logger.log(level,
                             _("Task '%(task_name)s' (%(task_uuid)s)"
                               " transitioned into state '%(state)s'") %
                             {'task_name': details['task_name'],
                              'task_uuid': details['task_uuid'],
                              'state': state})
