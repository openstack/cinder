# -*- coding: utf-8 -*-

# vim: tabstop=4 shiftwidth=4 softtabstop=4

#    Copyright (C) 2012 Yahoo! Inc. All Rights Reserved.
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

import abc

import six

from cinder.taskflow import utils


@six.add_metaclass(abc.ABCMeta)
class Task(object):
    """An abstraction that defines a potential piece of work that can be
    applied and can be reverted to undo the work as a single unit.
    """
    def __init__(self, name):
        self.name = name
        # An *immutable* input 'resource' name set this task depends
        # on existing before this task can be applied.
        self.requires = set()
        # An *immutable* input 'resource' name set this task would like to
        # depends on existing before this task can be applied (but does not
        # strongly depend on existing).
        self.optional = set()
        # An *immutable* output 'resource' name set this task
        # produces that other tasks may depend on this task providing.
        self.provides = set()
        # This identifies the version of the task to be ran which
        # can be useful in resuming older versions of tasks. Standard
        # major, minor version semantics apply.
        self.version = (1, 0)

    def __str__(self):
        return "%s==%s" % (self.name, utils.join(self.version, with_what="."))

    @abc.abstractmethod
    def __call__(self, context, *args, **kwargs):
        """Activate a given task which will perform some operation and return.

           This method can be used to apply some given context and given set
           of args and kwargs to accomplish some goal. Note that the result
           that is returned needs to be serializable so that it can be passed
           back into this task if reverting is triggered.
        """
        raise NotImplementedError()

    def revert(self, context, result, cause):
        """Revert this task using the given context, result that the apply
           provided as well as any information which may have caused
           said reversion.
        """
        pass
