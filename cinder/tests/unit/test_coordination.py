# Copyright 2015 Intel
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

import inspect

import mock
import tooz.coordination
import tooz.locking

from cinder import coordination
from cinder import test


class Locked(Exception):
    pass


class MockToozLock(tooz.locking.Lock):
    active_locks = set()

    def acquire(self, blocking=True):
        if self.name not in self.active_locks:
            self.active_locks.add(self.name)
            return True
        elif not blocking:
            return False
        else:
            raise Locked

    def release(self):
        self.active_locks.remove(self.name)


@mock.patch('tooz.coordination.get_coordinator')
class CoordinatorTestCase(test.TestCase):
    MOCK_TOOZ = False

    def test_coordinator_start(self, get_coordinator):
        crd = get_coordinator.return_value

        agent = coordination.Coordinator()
        agent.start()
        self.assertTrue(get_coordinator.called)
        self.assertTrue(crd.start.called)

    def test_coordinator_stop(self, get_coordinator):
        crd = get_coordinator.return_value

        agent = coordination.Coordinator()
        agent.start()
        self.assertIsNotNone(agent.coordinator)
        agent.stop()
        self.assertTrue(crd.stop.called)
        self.assertIsNone(agent.coordinator)

    def test_coordinator_lock(self, get_coordinator):
        crd = get_coordinator.return_value
        crd.get_lock.side_effect = lambda n: MockToozLock(n)

        agent1 = coordination.Coordinator()
        agent1.start()
        agent2 = coordination.Coordinator()
        agent2.start()

        lock_name = 'lock'
        expected_name = lock_name.encode('ascii')

        self.assertNotIn(expected_name, MockToozLock.active_locks)
        with agent1.get_lock(lock_name):
            self.assertIn(expected_name, MockToozLock.active_locks)
            self.assertRaises(Locked, agent1.get_lock(lock_name).acquire)
            self.assertRaises(Locked, agent2.get_lock(lock_name).acquire)
        self.assertNotIn(expected_name, MockToozLock.active_locks)

    def test_coordinator_offline(self, get_coordinator):
        crd = get_coordinator.return_value
        crd.start.side_effect = tooz.coordination.ToozConnectionError('err')

        agent = coordination.Coordinator()
        self.assertRaises(tooz.coordination.ToozError, agent.start)
        self.assertFalse(agent.started)


@mock.patch.object(coordination.COORDINATOR, 'get_lock')
class CoordinationTestCase(test.TestCase):
    def test_synchronized(self, get_lock):
        @coordination.synchronized('lock-{f_name}-{foo.val}-{bar[val]}')
        def func(foo, bar):
            pass

        foo = mock.Mock()
        foo.val = 7
        bar = mock.MagicMock()
        bar.__getitem__.return_value = 8
        func(foo, bar)
        get_lock.assert_called_with('lock-func-7-8')
        self.assertEqual(['foo', 'bar'], inspect.getargspec(func)[0])
