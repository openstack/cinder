# vim: tabstop=4 shiftwidth=4 softtabstop=4

#    Copyright (C) 2013 Yahoo! Inc. All Rights Reserved.
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

# For more information please visit: https://wiki.openstack.org/wiki/TaskFlow
from cinder.taskflow import task


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

    def __init__(self, addons=None):
        super(CinderTask, self).__init__(_make_task_name(self.__class__,
                                                         addons))


class InjectTask(CinderTask):
    """This injects a dict into the flow.

    This injection is done so that the keys (and values) provided can be
    dependended on by tasks further down the line. Since taskflow is dependency
    based this can be considered the bootstrapping task that provides an
    initial set of values for other tasks to get started with. If this did not
    exist then tasks would fail locating there dependent tasks and the values
    said dependent tasks produce.

    Reversion strategy: N/A
    """

    def __init__(self, inject_what, addons=None):
        super(InjectTask, self).__init__(addons=addons)
        self.provides.update(inject_what.keys())
        self._inject = inject_what

    def __call__(self, context):
        return dict(self._inject)
