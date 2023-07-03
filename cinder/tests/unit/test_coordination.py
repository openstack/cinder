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

import errno
import inspect
from unittest import mock

import tooz.coordination
import tooz.locking

from cinder import coordination
from cinder.tests.unit import test


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


class CoordinatorTestCase(test.TestCase):
    MOCK_TOOZ = False

    @mock.patch('cinder.coordination.cfg.CONF.coordination.backend_url')
    @mock.patch('cinder.coordination.Coordinator._get_file_path')
    @mock.patch('tooz.coordination.get_coordinator')
    def test_coordinator_start(self, get_coordinator, mock_get_file_path,
                               mock_backend_url):
        crd = get_coordinator.return_value

        agent = coordination.Coordinator()
        self.assertIsNone(agent._file_path)
        agent.start()
        self.assertTrue(get_coordinator.called)
        self.assertTrue(crd.start.called)

        agent.start()
        crd.start.assert_called_once_with(start_heart=True)

        mock_get_file_path.assert_called_once_with(mock_backend_url)
        self.assertEqual(mock_get_file_path.return_value, agent._file_path)

    @mock.patch('tooz.coordination.get_coordinator')
    def test_coordinator_stop(self, get_coordinator):
        crd = get_coordinator.return_value

        agent = coordination.Coordinator()
        agent.start()
        self.assertIsNotNone(agent.coordinator)
        agent.stop()
        self.assertTrue(crd.stop.called)
        self.assertIsNone(agent.coordinator)

        agent.stop()
        crd.stop.assert_called_once_with()

    @mock.patch('tooz.coordination.get_coordinator')
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

    @mock.patch('tooz.coordination.get_coordinator')
    def test_coordinator_offline(self, get_coordinator):
        crd = get_coordinator.return_value
        crd.start.side_effect = tooz.coordination.ToozConnectionError('err')

        agent = coordination.Coordinator()
        self.assertRaises(tooz.coordination.ToozError, agent.start)
        self.assertFalse(agent.started)

    def test_get_file_path(self):
        backend_url = 'file:///opt/stack/data/cinder'
        res = coordination.COORDINATOR._get_file_path(backend_url)
        self.assertEqual('/opt/stack/data/cinder/cinder-', res)

    def test_get_file_path_non_file(self):
        backend_url = 'etcd3+http://192.168.1.95:2379'
        res = coordination.COORDINATOR._get_file_path(backend_url)
        self.assertIsNone(res)

    @mock.patch('cinder.coordination.COORDINATOR._file_path', None)
    @mock.patch('glob.glob')
    @mock.patch('os.remove')
    def test_remove_lock_non_file_lock(self, mock_remove, mock_glob):
        coordination.COORDINATOR.remove_lock('lock-file')
        mock_glob.assert_not_called()
        mock_remove.assert_not_called()

    @mock.patch('cinder.coordination.COORDINATOR._file_path', '/data/cinder-')
    @mock.patch('glob.glob')
    @mock.patch('os.remove')
    def test_remove_lock(self, mock_remove, mock_glob):
        mock_glob.return_value = ['/data/cinder-attachment_update-UUID-1',
                                  '/data/cinder-attachment_update-UUID-2']

        coordination.COORDINATOR.remove_lock('attachment_update-UUID-*')

        mock_glob.assert_called_once_with(
            '/data/cinder-attachment_update-UUID-*')
        self.assertEqual(2, mock_remove.call_count)
        mock_remove.assert_has_calls(
            [mock.call('/data/cinder-attachment_update-UUID-1'),
             mock.call('/data/cinder-attachment_update-UUID-2')])

    @mock.patch('cinder.coordination.COORDINATOR._file_path', '/data/cinder-')
    @mock.patch('cinder.coordination.LOG.warning')
    @mock.patch('glob.glob')
    @mock.patch('os.remove')
    def test_remove_lock_missing_file(self, mock_remove, mock_glob, mock_log):
        mock_glob.return_value = ['/data/cinder-attachment_update-UUID-1',
                                  '/data/cinder-attachment_update-UUID-2']
        mock_remove.side_effect = [OSError(errno.ENOENT, ''), None]

        coordination.COORDINATOR.remove_lock('attachment_update-UUID-*')

        mock_glob.assert_called_once_with(
            '/data/cinder-attachment_update-UUID-*')
        self.assertEqual(2, mock_remove.call_count)
        mock_remove.assert_has_calls(
            [mock.call('/data/cinder-attachment_update-UUID-1'),
             mock.call('/data/cinder-attachment_update-UUID-2')])
        mock_log.assert_not_called()

    @mock.patch('cinder.coordination.COORDINATOR._file_path', '/data/cinder-')
    @mock.patch('cinder.coordination.LOG.warning')
    @mock.patch('glob.glob')
    @mock.patch('os.remove')
    def test_remove_lock_unknown_failure(self, mock_remove, mock_glob,
                                         mock_log):
        mock_glob.return_value = ['/data/cinder-attachment_update-UUID-1',
                                  '/data/cinder-attachment_update-UUID-2']
        mock_remove.side_effect = [ValueError(), None]

        coordination.COORDINATOR.remove_lock('attachment_update-UUID-*')

        mock_glob.assert_called_once_with(
            '/data/cinder-attachment_update-UUID-*')
        self.assertEqual(2, mock_remove.call_count)
        mock_remove.assert_has_calls(
            [mock.call('/data/cinder-attachment_update-UUID-1'),
             mock.call('/data/cinder-attachment_update-UUID-2')])
        self.assertEqual(1, mock_log.call_count)


class CoordinationTestCase(test.TestCase):
    @mock.patch.object(coordination.COORDINATOR, 'get_lock')
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
        self.assertEqual(['foo', 'bar'], inspect.getfullargspec(func)[0])

    @mock.patch('cinder.coordination.COORDINATOR.remove_lock')
    def test_synchronized_remove(self, mock_remove):
        coordination.synchronized_remove(mock.sentinel.glob_name)
        mock_remove.assert_called_once_with(mock.sentinel.glob_name)

    @mock.patch('cinder.coordination.COORDINATOR.remove_lock')
    def test_synchronized_remove_custom_coordinator(self, mock_remove):
        coordinator = mock.Mock()
        coordination.synchronized_remove(mock.sentinel.glob_name, coordinator)
        coordinator.remove_lock.assert_called_once_with(
            mock.sentinel.glob_name)

    @mock.patch.object(coordination.COORDINATOR, 'get_lock')
    def test_synchronized_multiple_templates(self, get_lock):
        """Test locks requested in the right order and duplicates removed."""
        locks = ['lock-{f_name}-%s-{foo.val}-{bar[val]}' % i for i in range(3)]
        expect = [f'lock-func-{i}-7-8' for i in range(3)]

        @coordination.synchronized(locks[1], locks[0], locks[1], locks[2])
        def func(foo, bar):
            pass

        foo = mock.Mock(val=7)
        bar = mock.MagicMock()
        bar.__getitem__.return_value = 8
        func(foo, bar)
        self.assertEqual(len(expect), get_lock.call_count)
        get_lock.assert_has_calls([mock.call(lock) for lock in expect])

        self.assertEqual(len(expect), get_lock.return_value.acquire.call_count)
        get_lock.return_value.acquire.assert_has_calls(
            [mock.call(True)] * len(expect))

        self.assertEqual(['foo', 'bar'], inspect.getfullargspec(func)[0])

    @mock.patch('oslo_utils.timeutils.now', side_effect=[1, 2])
    def test___acquire(self, mock_now):
        lock = mock.Mock()
        # Using getattr to avoid AttributeError: module 'cinder.coordination'
        # has no attribute '_CoordinationTestCase__acquire'
        res = getattr(coordination, '__acquire')(lock, mock.sentinel.blocking,
                                                 mock.sentinel.f_name)
        self.assertEqual(2, res)
        self.assertEqual(2, mock_now.call_count)
        mock_now.assert_has_calls([mock.call(), mock.call()])
        lock.acquire.assert_called_once_with(mock.sentinel.blocking)

    @mock.patch('oslo_utils.timeutils.now')
    def test___acquire_propagates_exception(self, mock_now):
        lock = mock.Mock()
        lock.acquire.side_effect = ValueError
        # Using getattr to avoid AttributeError: module 'cinder.coordination'
        # has no attribute '_CoordinationTestCase__acquire'
        self.assertRaises(ValueError,
                          getattr(coordination, '__acquire'),
                          lock, mock.sentinel.blocking, mock.sentinel.f_name)
        mock_now.assert_called_once_with()
        lock.acquire.assert_called_once_with(mock.sentinel.blocking)

    @mock.patch('oslo_utils.timeutils.now', return_value=2)
    def test___release(self, mock_now):
        lock = mock.Mock()
        # Using getattr to avoid AttributeError: module 'cinder.coordination'
        # has no attribute '_CoordinationTestCase__release'
        getattr(coordination, '__release')(lock, 1, mock.sentinel.f_name)

        mock_now.assert_called_once_with()
        lock.release.assert_called_once_with()

    @mock.patch('oslo_utils.timeutils.now')
    def test___release_ignores_exception(self, mock_now):
        lock = mock.Mock()
        lock.release.side_effect = ValueError
        # Using getattr to avoid AttributeError: module 'cinder.coordination'
        # has no attribute '_CoordinationTestCase__release'
        getattr(coordination, '__release')(lock, 1, mock.sentinel.f_name)

        mock_now.assert_not_called()
        lock.release.assert_called_once_with()
