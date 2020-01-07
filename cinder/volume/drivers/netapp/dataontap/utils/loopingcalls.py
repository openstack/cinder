# Copyright (c) 2016 Chuck Fouts.  All rights reserved.
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
"""Collects and starts tasks created from oslo_service.loopingcall."""

from collections import namedtuple

from oslo_service import loopingcall

LoopingTask = namedtuple('LoopingTask',
                         ['looping_call', 'interval', 'initial_delay'])

# Time intervals in seconds
ONE_MINUTE = 60
TEN_MINUTES = 600
ONE_HOUR = 3600


class LoopingCalls(object):

    def __init__(self):
        self.tasks = []

    def add_task(self, call_function, interval, initial_delay=0):
        looping_call = loopingcall.FixedIntervalLoopingCall(call_function)
        task = LoopingTask(looping_call, interval, initial_delay)
        self.tasks.append(task)

    def start_tasks(self):
        for task in self.tasks:
            task.looping_call.start(task.interval, task.initial_delay)
