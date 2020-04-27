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

from unittest import mock

from oslo_service import loopingcall

from cinder.tests.unit import test
from cinder.volume.drivers.netapp.dataontap.utils import loopingcalls


class LoopingCallsTestCase(test.TestCase):

    def setUp(self):
        super(LoopingCallsTestCase, self).setUp()
        self.mock_first_looping_task = mock.Mock()
        self.mock_second_looping_task = mock.Mock()

        self.mock_loopingcall = self.mock_object(
            loopingcall,
            'FixedIntervalLoopingCall',
            side_effect=[self.mock_first_looping_task,
                         self.mock_second_looping_task]
        )
        self.loopingcalls = loopingcalls.LoopingCalls()

    def test_add_task(self):
        interval = 3600
        initial_delay = 5

        self.loopingcalls.add_task(self.mock_first_looping_task, interval)
        self.loopingcalls.add_task(
            self.mock_second_looping_task, interval, initial_delay)

        self.assertEqual(2, len(self.loopingcalls.tasks))
        self.assertEqual(interval, self.loopingcalls.tasks[0].interval)
        self.assertEqual(initial_delay,
                         self.loopingcalls.tasks[1].initial_delay)

    def test_start_tasks(self):
        interval = 3600
        initial_delay = 5

        self.loopingcalls.add_task(self.mock_first_looping_task, interval)
        self.loopingcalls.add_task(
            self.mock_second_looping_task, interval, initial_delay)

        self.loopingcalls.start_tasks()

        self.mock_first_looping_task.start.assert_called_once_with(
            interval, 0)
        self.mock_second_looping_task.start.assert_called_once_with(
            interval, initial_delay)
