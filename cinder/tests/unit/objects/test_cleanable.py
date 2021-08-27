# Copyright (c) 2016 Red Hat, Inc.
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
from unittest import mock

from cinder import context
from cinder import exception
from cinder.objects import cleanable
from cinder import service
from cinder.tests.unit import objects as test_objects
from cinder.volume import rpcapi


# NOTE(geguileo): We use Backup because we have version changes from 1.0 to 1.3

class Backup(cleanable.CinderCleanableObject):
    def __init__(self, *args, **kwargs):
        super(Backup, self).__init__(*args)
        for attr, value in kwargs.items():
            setattr(self, attr, value)

    @staticmethod
    def _is_cleanable(status, obj_version):
        if obj_version and obj_version < 1003:
            return False
        return status == 'cleanable'


class TestCleanable(test_objects.BaseObjectsTestCase):
    MOCK_WORKER = False

    def setUp(self):
        super(TestCleanable, self).setUp()
        self.context = context.RequestContext(self.user_id, self.project_id,
                                              is_admin=True)

    def test_get_rpc_api(self):
        """Test get_rpc_api."""
        vol_rpcapi = cleanable.CinderCleanableObject.get_rpc_api()
        self.assertEqual(rpcapi.VolumeAPI, vol_rpcapi)

    def set_version(self, version):
        self.patch('cinder.volume.rpcapi.VolumeAPI.determine_obj_version_cap',
                   mock.Mock(return_value='1.0'))
        self.patch('cinder.objects.base.OBJ_VERSIONS',
                   {'1.0': {'Backup': version}})

    def test_get_pinned_version(self):
        """Test that we get the pinned version for this specific object."""
        self.set_version('1.3')
        version = Backup.get_pinned_version()
        self.assertEqual(1003, version)

    def test_is_cleanable_pinned_pinned_too_old(self):
        """Test is_cleanable with pinned version with uncleanable version."""
        self.set_version('1.0')
        backup = Backup(status='cleanable')
        self.assertFalse(backup.is_cleanable(pinned=True))

    def test_is_cleanable_pinned_result_true(self):
        """Test with pinned version with cleanable version and status."""
        self.set_version('1.3')
        backup = Backup(status='cleanable')
        self.assertTrue(backup.is_cleanable(pinned=True))

    def test_is_cleanable_pinned_result_false(self):
        """Test with pinned version with cleanable version but not status."""
        self.set_version('1.0')
        backup = Backup(status='not_cleanable')
        self.assertFalse(backup.is_cleanable(pinned=True))

    def test_is_cleanable_unpinned_result_false(self):
        """Test unpinned version with old version and non cleanable status."""
        self.set_version('1.0')
        backup = Backup(status='not_cleanable')
        self.assertFalse(backup.is_cleanable(pinned=False))

    def test_is_cleanable_unpinned_result_true(self):
        """Test unpinned version with old version and cleanable status."""
        self.set_version('1.0')
        backup = Backup(status='cleanable')
        self.assertTrue(backup.is_cleanable(pinned=False))

    @mock.patch('cinder.db.worker_create', autospec=True)
    def test_create_worker(self, mock_create):
        """Test worker creation as if it were from an rpc call."""
        self.set_version('1.3')
        mock_create.return_value = mock.sentinel.worker
        backup = Backup(_context=self.context, status='cleanable',
                        id=mock.sentinel.id)
        res = backup.create_worker()
        self.assertTrue(res)
        mock_create.assert_called_once_with(self.context,
                                            status='cleanable',
                                            resource_type='Backup',
                                            resource_id=mock.sentinel.id)

    @mock.patch('cinder.db.worker_create', autospec=True)
    def test_create_worker_pinned_too_old(self, mock_create):
        """Test worker creation when we are pinnned with an old version."""
        self.set_version('1.0')
        mock_create.return_value = mock.sentinel.worker
        backup = Backup(_context=self.context, status='cleanable',
                        id=mock.sentinel.id)
        res = backup.create_worker()
        self.assertFalse(res)
        self.assertFalse(mock_create.called)

    @mock.patch('cinder.db.worker_create', autospec=True)
    def test_create_worker_non_cleanable(self, mock_create):
        """Test worker creation when status is non cleanable."""
        self.set_version('1.3')
        mock_create.return_value = mock.sentinel.worker
        backup = Backup(_context=self.context, status='non_cleanable',
                        id=mock.sentinel.id)
        res = backup.create_worker()
        self.assertFalse(res)
        self.assertFalse(mock_create.called)

    @mock.patch('cinder.db.worker_update', autospec=True)
    @mock.patch('cinder.db.worker_create', autospec=True)
    def test_create_worker_already_exists(self, mock_create, mock_update):
        """Test worker creation when a worker for the resource exists."""
        self.set_version('1.3')
        mock_create.side_effect = exception.WorkerExists(type='type', id='id')

        backup = Backup(_context=self.context, status='cleanable',
                        id=mock.sentinel.id)
        res = backup.create_worker()
        self.assertTrue(res)
        self.assertTrue(mock_create.called)
        mock_update.assert_called_once_with(
            self.context, None,
            filters={'resource_type': 'Backup',
                     'resource_id': mock.sentinel.id},
            service_id=None, status='cleanable')

    @mock.patch('cinder.db.worker_update', autospec=True)
    @mock.patch('cinder.db.worker_create', autospec=True)
    def test_create_worker_cleaning(self, mock_create, mock_update):
        """Test worker creation on race condition.

        Test that we still create an entry if there is a rare race condition
        that the entry gets removed from the DB between our failure to create
        it and our try to update the entry.
        """
        self.set_version('1.3')
        mock_create.side_effect = [
            exception.WorkerExists(type='type', id='id'), mock.sentinel.worker]
        mock_update.side_effect = exception.WorkerNotFound

        backup = Backup(_context=self.context, status='cleanable',
                        id=mock.sentinel.id)
        self.assertTrue(backup.create_worker())
        self.assertEqual(2, mock_create.call_count)
        self.assertTrue(mock_update.called)

    @mock.patch('cinder.db.worker_update', autospec=True)
    @mock.patch('cinder.db.worker_get', autospec=True)
    def test_set_worker(self, mock_get, mock_update):
        """Test set worker for a normal job received from an rpc call."""
        service.Service.service_id = mock.sentinel.service_id
        mock_get.return_value.cleaning = False
        backup = Backup(_context=self.context, status=mock.sentinel.status,
                        id=mock.sentinel.id)

        backup.set_worker()
        mock_get.assert_called_once_with(self.context, resource_type='Backup',
                                         resource_id=mock.sentinel.id)
        worker = mock_get.return_value
        mock_update.assert_called_once_with(
            self.context, worker.id,
            filters={'service_id': worker.service_id,
                     'status': worker.status,
                     'race_preventer': worker.race_preventer,
                     'updated_at': worker.updated_at},
            service_id=mock.sentinel.service_id,
            status=mock.sentinel.status,
            orm_worker=worker)
        self.assertEqual(worker, backup.worker)

    @mock.patch('cinder.db.worker_create', autospec=True)
    @mock.patch('cinder.db.worker_get', autospec=True)
    def test_set_worker_direct(self, mock_get, mock_create):
        """Test set worker for direct call (non rpc call)."""
        mock_get.side_effect = exception.WorkerNotFound
        service_id = mock.sentinel.service_id
        service.Service.service_id = service_id
        mock_create.return_value = mock.Mock(service_id=service_id,
                                             status=mock.sentinel.status,
                                             deleted=False, cleaning=False)

        backup = Backup(_context=self.context, status=mock.sentinel.status,
                        id=mock.sentinel.id)

        backup.set_worker()
        mock_get.assert_called_once_with(self.context, resource_type='Backup',
                                         resource_id=mock.sentinel.id)
        mock_create.assert_called_once_with(self.context,
                                            status=mock.sentinel.status,
                                            resource_type='Backup',
                                            resource_id=mock.sentinel.id,
                                            service_id=service_id)
        self.assertEqual(mock_create.return_value, backup.worker)

    @mock.patch('cinder.db.worker_update', autospec=True)
    @mock.patch('cinder.db.worker_get', autospec=True)
    def test_set_worker_claim_from_another_host(self, mock_get, mock_update):
        """Test set worker when the job was started on another failed host."""
        service_id = mock.sentinel.service_id
        service.Service.service_id = service_id
        worker = mock.Mock(service_id=mock.sentinel.service_id2,
                           status=mock.sentinel.status, cleaning=False,
                           updated_at=mock.sentinel.updated_at)
        mock_get.return_value = worker

        backup = Backup(_context=self.context, status=mock.sentinel.status,
                        id=mock.sentinel.id)

        backup.set_worker()

        mock_update.assert_called_once_with(
            self.context, worker.id,
            filters={'service_id': mock.sentinel.service_id2,
                     'status': mock.sentinel.status,
                     'race_preventer': worker.race_preventer,
                     'updated_at': mock.sentinel.updated_at},
            service_id=service_id, status=mock.sentinel.status,
            orm_worker=worker)
        self.assertEqual(worker, backup.worker)

    @mock.patch('cinder.db.worker_create', autospec=True)
    @mock.patch('cinder.db.worker_get', autospec=True)
    def test_set_worker_race_condition_fail(self, mock_get, mock_create):
        """Test we cannot claim a work if we lose race condition."""
        service.Service.service_id = mock.sentinel.service_id
        mock_get.side_effect = exception.WorkerNotFound
        mock_create.side_effect = exception.WorkerExists(type='type', id='id')

        backup = Backup(_context=self.context, status=mock.sentinel.status,
                        id=mock.sentinel.id)

        self.assertRaises(exception.CleanableInUse, backup.set_worker)
        self.assertTrue(mock_get.called)
        self.assertTrue(mock_create.called)

    @mock.patch('cinder.db.worker_update', autospec=True)
    @mock.patch('cinder.db.worker_get', autospec=True)
    def test_set_worker_claim_fail_after_get(self, mock_get, mock_update):
        """Test we don't have race condition if worker changes after get."""
        service.Service.service_id = mock.sentinel.service_id
        worker = mock.Mock(service_id=mock.sentinel.service_id2,
                           status=mock.sentinel.status, deleted=False,
                           cleaning=False)
        mock_get.return_value = worker
        mock_update.side_effect = exception.WorkerNotFound

        backup = Backup(_context=self.context, status=mock.sentinel.status,
                        id=mock.sentinel.id)

        self.assertRaises(exception.CleanableInUse, backup.set_worker)
        self.assertTrue(mock_get.called)
        self.assertTrue(mock_update.called)

    @mock.patch('cinder.db.worker_destroy')
    def test_unset_worker(self, destroy_mock):
        backup = Backup(_context=self.context, status=mock.sentinel.status,
                        id=mock.sentinel.id)
        worker = mock.Mock()
        backup.worker = worker
        backup.unset_worker()
        destroy_mock.assert_called_once_with(self.context, id=worker.id,
                                             status=worker.status,
                                             service_id=worker.service_id)
        self.assertIsNone(backup.worker)

    @mock.patch('cinder.db.worker_destroy')
    def test_unset_worker_not_set(self, destroy_mock):
        backup = Backup(_context=self.context, status=mock.sentinel.status,
                        id=mock.sentinel.id)
        backup.unset_worker()
        self.assertFalse(destroy_mock.called)

    @mock.patch('cinder.db.worker_update', autospec=True)
    @mock.patch('cinder.db.worker_get', autospec=True)
    def test_set_workers_no_arguments(self, mock_get, mock_update):
        """Test set workers decorator without arguments."""
        @Backup.set_workers
        def my_function(arg1, arg2, kwarg1=None, kwarg2=True):
            return arg1, arg2, kwarg1, kwarg2

        # Decorator with no args must preserve the method's signature
        self.assertEqual('my_function', my_function.__name__)
        call_args = inspect.getcallargs(
            my_function, mock.sentinel.arg1, mock.sentinel.arg2,
            mock.sentinel.kwargs1, kwarg2=mock.sentinel.kwarg2)
        expected = {'arg1': mock.sentinel.arg1,
                    'arg2': mock.sentinel.arg2,
                    'kwarg1': mock.sentinel.kwargs1,
                    'kwarg2': mock.sentinel.kwarg2}
        self.assertDictEqual(expected, call_args)

        service.Service.service_id = mock.sentinel.service_id
        mock_get.return_value.cleaning = False
        backup = Backup(_context=self.context, status='cleanable',
                        id=mock.sentinel.id)
        backup2 = Backup(_context=self.context, status='non-cleanable',
                         id=mock.sentinel.id2)

        res = my_function(backup, backup2)
        self.assertEqual((backup, backup2, None, True), res)

        mock_get.assert_called_once_with(self.context, resource_type='Backup',
                                         resource_id=mock.sentinel.id)
        worker = mock_get.return_value
        mock_update.assert_called_once_with(
            self.context, worker.id,
            filters={'service_id': worker.service_id,
                     'status': worker.status,
                     'race_preventer': worker.race_preventer,
                     'updated_at': worker.updated_at},
            service_id=mock.sentinel.service_id,
            status='cleanable',
            orm_worker=worker)
        self.assertEqual(worker, backup.worker)

    @mock.patch('cinder.db.worker_update', autospec=True)
    @mock.patch('cinder.db.worker_get', autospec=True)
    def test_set_workers_with_arguments(self, mock_get, mock_update):
        """Test set workers decorator with an argument."""
        @Backup.set_workers('arg2', 'kwarg1')
        def my_function(arg1, arg2, kwarg1=None, kwarg2=True):
            return arg1, arg2, kwarg1, kwarg2

        # Decorator with args must preserve the method's signature
        self.assertEqual('my_function', my_function.__name__)
        call_args = inspect.getcallargs(
            my_function, mock.sentinel.arg1, mock.sentinel.arg2,
            mock.sentinel.kwargs1, kwarg2=mock.sentinel.kwarg2)
        expected = {'arg1': mock.sentinel.arg1,
                    'arg2': mock.sentinel.arg2,
                    'kwarg1': mock.sentinel.kwargs1,
                    'kwarg2': mock.sentinel.kwarg2}
        self.assertDictEqual(expected, call_args)

        service.Service.service_id = mock.sentinel.service_id
        mock_get.return_value.cleaning = False
        backup = Backup(_context=self.context, status='cleanable',
                        id=mock.sentinel.id)
        backup2 = Backup(_context=self.context, status='non-cleanable',
                         id=mock.sentinel.id2)
        backup3 = Backup(_context=self.context, status='cleanable',
                         id=mock.sentinel.id3)

        res = my_function(backup, backup2, backup3)
        self.assertEqual((backup, backup2, backup3, True), res)

        mock_get.assert_called_once_with(self.context, resource_type='Backup',
                                         resource_id=mock.sentinel.id3)
        worker = mock_get.return_value
        mock_update.assert_called_once_with(
            self.context, worker.id,
            filters={'service_id': worker.service_id,
                     'status': worker.status,
                     'race_preventer': worker.race_preventer,
                     'updated_at': worker.updated_at},
            service_id=mock.sentinel.service_id,
            status='cleanable',
            orm_worker=worker)
        self.assertEqual(worker, backup3.worker)
