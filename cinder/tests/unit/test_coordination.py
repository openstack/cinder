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


@mock.patch('time.sleep', lambda _: None)
@mock.patch('eventlet.spawn', lambda f: f())
@mock.patch('eventlet.tpool.execute', lambda f: f())
@mock.patch.object(coordination.Coordinator, 'heartbeat')
@mock.patch('tooz.coordination.get_coordinator')
@mock.patch('random.uniform', lambda _a, _b: 0)
class CoordinatorTestCase(test.TestCase):
    def test_coordinator_start(self, get_coordinator, heartbeat):
        crd = get_coordinator.return_value

        agent = coordination.Coordinator()
        agent.start()
        self.assertTrue(get_coordinator.called)
        self.assertTrue(heartbeat.called)
        self.assertTrue(crd.start.called)

    def test_coordinator_stop(self, get_coordinator, heartbeat):
        crd = get_coordinator.return_value

        agent = coordination.Coordinator()
        agent.start()
        self.assertIsNotNone(agent.coordinator)
        agent.stop()
        self.assertTrue(crd.stop.called)
        self.assertIsNone(agent.coordinator)

    def test_coordinator_lock(self, get_coordinator, heartbeat):
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

    def test_coordinator_offline(self, get_coordinator, heartbeat):
        crd = get_coordinator.return_value
        crd.start.side_effect = tooz.coordination.ToozConnectionError('err')

        agent = coordination.Coordinator()
        self.assertRaises(tooz.coordination.ToozError, agent.start)
        self.assertFalse(agent.started)
        self.assertFalse(heartbeat.called)

    def test_coordinator_reconnect(self, get_coordinator, heartbeat):
        start_online = iter([True] + [False] * 5 + [True])
        heartbeat_online = iter((False, True, True))

        def raiser(cond):
            if not cond:
                raise tooz.coordination.ToozConnectionError('err')

        crd = get_coordinator.return_value
        crd.start.side_effect = lambda *_: raiser(next(start_online))
        crd.heartbeat.side_effect = lambda *_: raiser(next(heartbeat_online))

        agent = coordination.Coordinator()
        agent.start()
        self.assertRaises(tooz.coordination.ToozConnectionError,
                          agent._heartbeat)
        self.assertEqual(1, get_coordinator.call_count)
        agent._reconnect()
        self.assertEqual(7, get_coordinator.call_count)
        agent._heartbeat()


@mock.patch.object(coordination.COORDINATOR, 'get_lock')
class CoordinationTestCase(test.TestCase):
    def test_lock(self, get_lock):
        with coordination.Lock('lock'):
            self.assertTrue(get_lock.called)

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
