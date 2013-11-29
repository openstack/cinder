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


class TaskFlowException(Exception):
    """Base class for exceptions emitted from this library."""
    pass


class Duplicate(TaskFlowException):
    """Raised when a duplicate entry is found."""
    pass


class NotFound(TaskFlowException):
    """Raised when some entry in some object doesn't exist."""
    pass


class AlreadyExists(TaskFlowException):
    """Raised when some entry in some object already exists."""
    pass


class ClosedException(TaskFlowException):
    """Raised when an access on a closed object occurs."""
    pass


class InvalidStateException(TaskFlowException):
    """Raised when a task/job/workflow is in an invalid state when an
    operation is attempting to apply to said task/job/workflow.
    """
    pass


class UnclaimableJobException(TaskFlowException):
    """Raised when a job can not be claimed."""
    pass


class JobNotFound(TaskFlowException):
    """Raised when a job entry can not be found."""
    pass


class MissingDependencies(InvalidStateException):
    """Raised when a task has dependencies that can not be satisfied."""
    message = ("%(task)s requires %(requirements)s but no other task produces"
               " said requirements")

    def __init__(self, task, requirements):
        message = self.message % {'task': task, 'requirements': requirements}
        super(MissingDependencies, self).__init__(message)
