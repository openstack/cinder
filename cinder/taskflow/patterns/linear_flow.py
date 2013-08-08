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

import collections
import logging

from cinder.openstack.common import excutils

from cinder.taskflow import decorators
from cinder.taskflow import exceptions as exc
from cinder.taskflow import states
from cinder.taskflow import utils

from cinder.taskflow.patterns import base

LOG = logging.getLogger(__name__)


class Flow(base.Flow):
    """"A linear chain of tasks that can be applied in order as one unit and
    rolled back as one unit using the reverse order that the tasks have
    been applied in.

    Note(harlowja): Each task in the chain must have requirements
    which are satisfied by the previous task/s in the chain.
    """

    def __init__(self, name, parents=None, uuid=None):
        super(Flow, self).__init__(name, parents, uuid)
        # The tasks which have been applied will be collected here so that they
        # can be reverted in the correct order on failure.
        self._accumulator = utils.RollbackAccumulator()
        # Tasks results are stored here. Lookup is by the uuid that was
        # returned from the add function.
        self.results = {}
        # The previously left off iterator that can be used to resume from
        # the last task (if interrupted and soft-reset).
        self._leftoff_at = None
        # All runners to run are collected here.
        self._runners = []
        self._connected = False
        # The resumption strategy to use.
        self.resumer = None

    @decorators.locked
    def add(self, task):
        """Adds a given task to this flow."""
        assert isinstance(task, collections.Callable)
        r = utils.Runner(task)
        r.runs_before = list(reversed(self._runners))
        self._runners.append(r)
        self._reset_internals()
        return r.uuid

    def _reset_internals(self):
        self._connected = False
        self._leftoff_at = None

    def _associate_providers(self, runner):
        # Ensure that some previous task provides this input.
        who_provides = {}
        task_requires = runner.requires
        for r in task_requires:
            provider = None
            for before_me in runner.runs_before:
                if r in before_me.provides:
                    provider = before_me
                    break
            if provider:
                who_provides[r] = provider
        # Ensure that the last task provides all the needed input for this
        # task to run correctly.
        missing_requires = task_requires - set(who_provides.keys())
        if missing_requires:
            raise exc.MissingDependencies(runner, sorted(missing_requires))
        runner.providers.update(who_provides)

    def __str__(self):
        lines = ["LinearFlow: %s" % (self.name)]
        lines.append("%s" % (self.uuid))
        lines.append("%s" % (len(self._runners)))
        lines.append("%s" % (len(self.parents)))
        lines.append("%s" % (self.state))
        return "; ".join(lines)

    @decorators.locked
    def remove(self, uuid):
        index_removed = -1
        for (i, r) in enumerate(self._runners):
            if r.uuid == uuid:
                index_removed = i
                break
        if index_removed == -1:
            raise ValueError("No runner found with uuid %s" % (uuid))
        else:
            removed = self._runners.pop(index_removed)
            self._reset_internals()
            # Go and remove it from any runner after the removed runner since
            # those runners may have had an attachment to it.
            for r in self._runners[index_removed:]:
                try:
                    r.runs_before.remove(removed)
                except (IndexError, ValueError):
                    pass

    def __len__(self):
        return len(self._runners)

    def _connect(self):
        if self._connected:
            return self._runners
        for r in self._runners:
            r.providers = {}
        for r in reversed(self._runners):
            self._associate_providers(r)
        self._connected = True
        return self._runners

    def _ordering(self):
        return iter(self._connect())

    @decorators.locked
    def run(self, context, *args, **kwargs):
        super(Flow, self).run(context, *args, **kwargs)

        def resume_it():
            if self._leftoff_at is not None:
                return ([], self._leftoff_at)
            if self.resumer:
                (finished, leftover) = self.resumer.resume(self,
                                                           self._ordering())
            else:
                finished = []
                leftover = self._ordering()
            return (finished, leftover)

        self._change_state(context, states.STARTED)
        try:
            those_finished, leftover = resume_it()
        except Exception:
            with excutils.save_and_reraise_exception():
                self._change_state(context, states.FAILURE)

        def run_it(runner, failed=False, result=None, simulate_run=False):
            try:
                # Add the task to be rolled back *immediately* so that even if
                # the task fails while producing results it will be given a
                # chance to rollback.
                rb = utils.RollbackTask(context, runner.task, result=None)
                self._accumulator.add(rb)
                self.task_notifier.notify(states.STARTED, details={
                    'context': context,
                    'flow': self,
                    'runner': runner,
                })
                if not simulate_run:
                    result = runner(context, *args, **kwargs)
                else:
                    if failed:
                        # TODO(harlowja): make this configurable??
                        # If we previously failed, we want to fail again at
                        # the same place.
                        if not result:
                            # If no exception or exception message was provided
                            # or captured from the previous run then we need to
                            # form one for this task.
                            result = "%s failed running." % (runner.task)
                        if isinstance(result, basestring):
                            result = exc.InvalidStateException(result)
                        if not isinstance(result, Exception):
                            LOG.warn("Can not raise a non-exception"
                                     " object: %s", result)
                            result = exc.InvalidStateException()
                        raise result
                # Adjust the task result in the accumulator before
                # notifying others that the task has finished to
                # avoid the case where a listener might throw an
                # exception.
                rb.result = result
                runner.result = result
                self.results[runner.uuid] = result
                self.task_notifier.notify(states.SUCCESS, details={
                    'context': context,
                    'flow': self,
                    'runner': runner,
                })
            except Exception as e:
                runner.result = e
                cause = utils.FlowFailure(runner, self, e)
                with excutils.save_and_reraise_exception():
                    # Notify any listeners that the task has errored.
                    self.task_notifier.notify(states.FAILURE, details={
                        'context': context,
                        'flow': self,
                        'runner': runner,
                    })
                    self.rollback(context, cause)

        if len(those_finished):
            self._change_state(context, states.RESUMING)
            for (r, details) in those_finished:
                # Fake running the task so that we trigger the same
                # notifications and state changes (and rollback that
                # would have happened in a normal flow).
                failed = states.FAILURE in details.get('states', [])
                result = details.get('result')
                run_it(r, failed=failed, result=result, simulate_run=True)

        self._leftoff_at = leftover
        self._change_state(context, states.RUNNING)
        if self.state == states.INTERRUPTED:
            return

        was_interrupted = False
        for r in leftover:
            r.reset()
            run_it(r)
            if self.state == states.INTERRUPTED:
                was_interrupted = True
                break

        if not was_interrupted:
            # Only gets here if everything went successfully.
            self._change_state(context, states.SUCCESS)
            self._leftoff_at = None

    @decorators.locked
    def reset(self):
        super(Flow, self).reset()
        self.results = {}
        self.resumer = None
        self._accumulator.reset()
        self._reset_internals()

    @decorators.locked
    def rollback(self, context, cause):
        # Performs basic task by task rollback by going through the reverse
        # order that tasks have finished and asking said task to undo whatever
        # it has done. If this flow has any parent flows then they will
        # also be called to rollback any tasks said parents contain.
        #
        # Note(harlowja): if a flow can more simply revert a whole set of
        # tasks via a simpler command then it can override this method to
        # accomplish that.
        #
        # For example, if each task was creating a file in a directory, then
        # it's easier to just remove the directory than to ask each task to
        # delete its file individually.
        self._change_state(context, states.REVERTING)
        try:
            self._accumulator.rollback(cause)
        finally:
            self._change_state(context, states.FAILURE)
        # Rollback any parents flows if they exist...
        for p in self.parents:
            p.rollback(context, cause)
