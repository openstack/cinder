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

"""Unit tests for cinder.db.api.Worker"""

from datetime import datetime
import time
from unittest import mock
import uuid

from oslo_db import exception as db_exception

from cinder import context
from cinder import db
from cinder import exception
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import test


class DBAPIWorkerTestCase(test.TestCase, test.ModelsObjectComparatorMixin):
    worker_fields = {'resource_type': 'Volume',
                     'resource_id': fake.VOLUME_ID,
                     'status': 'creating'}

    def _uuid(self):
        return str(uuid.uuid4())

    def setUp(self):
        super(DBAPIWorkerTestCase, self).setUp()
        self.ctxt = context.get_admin_context()

    def tearDown(self):
        db.sqlalchemy.api.DB_SUPPORTS_SUBSECOND_RESOLUTION = True
        super(DBAPIWorkerTestCase, self).tearDown()

    def test_workers_init(self):
        # SQLite supports subsecond resolution so result is True
        db.sqlalchemy.api.DB_SUPPORTS_SUBSECOND_RESOLUTION = None
        db.workers_init()
        self.assertTrue(db.sqlalchemy.api.DB_SUPPORTS_SUBSECOND_RESOLUTION)

    def test_workers_init_not_supported(self):
        # Fake a Db that doesn't support sub-second resolution in datetimes
        db.worker_update(
            self.ctxt, None,
            {'resource_type': 'SENTINEL', 'ignore_sentinel': False},
            updated_at=datetime.utcnow().replace(microsecond=0))
        db.workers_init()
        self.assertFalse(db.sqlalchemy.api.DB_SUPPORTS_SUBSECOND_RESOLUTION)

    def test_worker_create_and_get(self):
        """Test basic creation of a worker record."""
        worker = db.worker_create(self.ctxt, **self.worker_fields)
        db_worker = db.worker_get(self.ctxt, id=worker.id)
        self._assertEqualObjects(worker, db_worker)

    @mock.patch('oslo_utils.timeutils.utcnow',
                return_value=datetime.utcnow().replace(microsecond=123))
    def test_worker_create_no_subsecond(self, mock_utcnow):
        """Test basic creation of a worker record."""
        db.sqlalchemy.api.DB_SUPPORTS_SUBSECOND_RESOLUTION = False
        worker = db.worker_create(self.ctxt, **self.worker_fields)
        db_worker = db.worker_get(self.ctxt, id=worker.id)
        self._assertEqualObjects(worker, db_worker)
        self.assertEqual(0, db_worker.updated_at.microsecond)

    def test_worker_create_unique_constrains(self):
        """Test when we use an already existing resource type and id."""
        db.worker_create(self.ctxt, **self.worker_fields)
        self.assertRaises(exception.WorkerExists, db.worker_create,
                          self.ctxt,
                          resource_type=self.worker_fields['resource_type'],
                          resource_id=self.worker_fields['resource_id'],
                          status='not_' + self.worker_fields['status'])

    def test_worker_create_missing_required_field(self):
        """Try creating a worker with a missing required field."""
        for field in self.worker_fields:
            params = self.worker_fields.copy()
            del params[field]
            self.assertRaises(db_exception.DBError, db.worker_create,
                              self.ctxt, **params)

    def test_worker_create_invalid_field(self):
        """Try creating a worker with a non existent db field."""
        self.assertRaises(TypeError, db.worker_create, self.ctxt,
                          myfield='123', **self.worker_fields)

    def test_worker_get_non_existent(self):
        """Check basic non existent worker record get method."""
        db.worker_create(self.ctxt, **self.worker_fields)
        self.assertRaises(exception.WorkerNotFound, db.worker_get,
                          self.ctxt, service_id='1', **self.worker_fields)

    def _create_workers(self, num, read_back=False, **fields):
        workers = []
        base_params = self.worker_fields.copy()
        base_params.update(fields)

        for i in range(num):
            params = base_params.copy()
            params['resource_id'] = self._uuid()
            workers.append(db.worker_create(self.ctxt, **params))

        if read_back:
            for i in range(len(workers)):
                workers[i] = db.worker_get(self.ctxt, id=workers[i].id)

        return workers

    def test_worker_get_all(self):
        """Test basic get_all method."""
        self._create_workers(1)
        service = db.service_create(self.ctxt, {})
        workers = self._create_workers(3, service_id=service.id)

        db_workers = db.worker_get_all(self.ctxt, service_id=service.id)
        self._assertEqualListsOfObjects(workers, db_workers)

    def test_worker_get_all_until(self):
        """Test get_all until a specific time."""
        workers = self._create_workers(3, read_back=True)
        timestamp = workers[-1].updated_at
        time.sleep(0.1)
        self._create_workers(3)

        db_workers = db.worker_get_all(self.ctxt, until=timestamp)
        self._assertEqualListsOfObjects(workers, db_workers)

    def test_worker_get_all_returns_empty(self):
        """Test that get_all returns an empty list when there's no results."""
        self._create_workers(3, deleted=True)
        db_workers = db.worker_get_all(self.ctxt)
        self.assertListEqual([], db_workers)

    def test_worker_update_not_exists(self):
        """Test worker update when the worker doesn't exist."""
        self.assertRaises(exception.WorkerNotFound, db.worker_update,
                          self.ctxt, 1)

    def test_worker_update(self):
        """Test basic worker update."""
        worker = self._create_workers(1)[0]
        worker = db.worker_get(self.ctxt, id=worker.id)
        res = db.worker_update(self.ctxt, worker.id, service_id=1)
        self.assertEqual(1, res)
        worker.service_id = 1

        db_worker = db.worker_get(self.ctxt, id=worker.id)
        self._assertEqualObjects(worker, db_worker,
                                 ['updated_at', 'race_preventer'])
        self.assertEqual(worker.race_preventer + 1, db_worker.race_preventer)

    def test_worker_update_no_subsecond(self):
        """Test basic worker update."""
        db.sqlalchemy.api.DB_SUPPORTS_SUBSECOND_RESOLUTION = False
        worker = self._create_workers(1)[0]
        worker = db.worker_get(self.ctxt, id=worker.id)
        now = datetime.utcnow().replace(microsecond=123)
        with mock.patch('oslo_utils.timeutils.utcnow', return_value=now):
            res = db.worker_update(self.ctxt, worker.id, service_id=1)
        self.assertEqual(1, res)
        worker.service_id = 1

        db_worker = db.worker_get(self.ctxt, id=worker.id)
        self._assertEqualObjects(worker, db_worker,
                                 ['updated_at', 'race_preventer'])
        self.assertEqual(0, db_worker.updated_at.microsecond)
        self.assertEqual(worker.race_preventer + 1, db_worker.race_preventer)

    def test_worker_update_update_orm(self):
        """Test worker update updating the worker orm object."""
        worker = self._create_workers(1)[0]
        res = db.worker_update(self.ctxt, worker.id, orm_worker=worker,
                               service_id=1)
        self.assertEqual(1, res)

        db_worker = db.worker_get(self.ctxt, id=worker.id)
        # If we are updating the ORM object we don't ignore the update_at field
        # because it will get updated in the ORM instance.
        self._assertEqualObjects(worker, db_worker)

    def test_worker_destroy(self):
        """Test that worker destroy really deletes the DB entry."""
        worker = self._create_workers(1)[0]
        res = db.worker_destroy(self.ctxt, id=worker.id)
        self.assertEqual(1, res)

        db_workers = db.worker_get_all(self.ctxt, read_deleted='yes')
        self.assertListEqual([], db_workers)

    def test_worker_destroy_non_existent(self):
        """Test that worker destroy returns 0 when entry doesn't exist."""
        res = db.worker_destroy(self.ctxt, id=100)
        self.assertEqual(0, res)

    def test_worker_claim(self):
        """Test worker claim of normal DB entry."""
        service_id = 1
        worker = db.worker_create(self.ctxt, resource_type='Volume',
                                  resource_id=fake.VOLUME_ID,
                                  status='deleting')

        res = db.worker_claim_for_cleanup(self.ctxt, service_id, worker)
        self.assertEqual(1, res)

        db_worker = db.worker_get(self.ctxt, id=worker.id)

        self._assertEqualObjects(worker, db_worker, ['updated_at'])
        self.assertEqual(service_id, db_worker.service_id)
        self.assertEqual(worker.service_id, db_worker.service_id)

    def test_worker_claim_fails_status_change(self):
        """Test that claim fails if the work entry has changed its status."""
        worker = db.worker_create(self.ctxt, resource_type='Volume',
                                  resource_id=fake.VOLUME_ID,
                                  status='deleting')
        worker.status = 'creating'

        res = db.worker_claim_for_cleanup(self.ctxt, 1, worker)
        self.assertEqual(0, res)

        db_worker = db.worker_get(self.ctxt, id=worker.id)
        self._assertEqualObjects(worker, db_worker, ['status'])
        self.assertIsNone(db_worker.service_id)

    def test_worker_claim_fails_service_change(self):
        """Test that claim fails on worker service change."""
        failed_service = 1
        working_service = 2
        this_service = 3
        worker = db.worker_create(self.ctxt, resource_type='Volume',
                                  resource_id=fake.VOLUME_ID,
                                  status='deleting',
                                  service_id=working_service)

        worker.service_id = failed_service
        res = db.worker_claim_for_cleanup(self.ctxt, this_service, worker)
        self.assertEqual(0, res)
        db_worker = db.worker_get(self.ctxt, id=worker.id)
        self.assertEqual(working_service, db_worker.service_id)

    def test_worker_claim_same_service(self):
        """Test worker claim of a DB entry that has our service_id."""
        service_id = 1
        worker = db.worker_create(self.ctxt, resource_type='Volume',
                                  resource_id=fake.VOLUME_ID,
                                  status='deleting', service_id=service_id)
        # Read from DB to get updated_at field
        worker = db.worker_get(self.ctxt, id=worker.id)
        claimed_worker = db.worker_get(self.ctxt, id=worker.id)

        res = db.worker_claim_for_cleanup(self.ctxt,
                                          service_id,
                                          claimed_worker)
        self.assertEqual(1, res)

        db_worker = db.worker_get(self.ctxt, id=worker.id)

        self._assertEqualObjects(claimed_worker, db_worker)
        self._assertEqualObjects(worker, db_worker,
                                 ['updated_at', 'race_preventer'])
        self.assertNotEqual(worker.updated_at, db_worker.updated_at)
        self.assertEqual(worker.race_preventer + 1, db_worker.race_preventer)

    def test_worker_claim_fails_this_service_claimed(self):
        """Test claim fails when worker was already claimed by this service."""
        service_id = 1
        worker = db.worker_create(self.ctxt, resource_type='Volume',
                                  resource_id=fake.VOLUME_ID,
                                  status='creating',
                                  service_id=service_id)

        # Read it back to have the updated_at value
        worker = db.worker_get(self.ctxt, id=worker.id)
        claimed_worker = db.worker_get(self.ctxt, id=worker.id)

        time.sleep(0.1)
        # Simulate that this service starts processing this entry
        res = db.worker_claim_for_cleanup(self.ctxt,
                                          service_id,
                                          claimed_worker)
        self.assertEqual(1, res)

        res = db.worker_claim_for_cleanup(self.ctxt, service_id, worker)
        self.assertEqual(0, res)
        db_worker = db.worker_get(self.ctxt, id=worker.id)
        self._assertEqualObjects(claimed_worker, db_worker)
        self._assertEqualObjects(worker, db_worker,
                                 ['updated_at', 'race_preventer'])
        self.assertNotEqual(worker.updated_at, db_worker.updated_at)
        self.assertEqual(worker.race_preventer + 1, db_worker.race_preventer)
