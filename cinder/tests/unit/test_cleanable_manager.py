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

import mock

from oslo_utils import timeutils

from cinder import context
from cinder import db
from cinder import manager
from cinder import objects
from cinder import test
from cinder.tests.unit import fake_constants
from cinder.tests.unit import utils


class FakeManager(manager.CleanableManager):
    def __init__(self, service_id=None, keep_after_clean=False):
        if service_id:
            self.service_id = service_id
        self.keep_after_clean = keep_after_clean

    def _do_cleanup(self, ctxt, vo_resource):
        vo_resource.status += '_cleaned'
        vo_resource.save()
        return self.keep_after_clean


class TestCleanableManager(test.TestCase):
    def setUp(self):
        super(TestCleanableManager, self).setUp()
        self.user_id = fake_constants.USER_ID
        self.project_id = fake_constants.PROJECT_ID
        self.context = context.RequestContext(self.user_id, self.project_id,
                                              is_admin=True)
        self.service = db.service_create(self.context, {})

    @mock.patch('cinder.db.workers_init', autospec=True)
    @mock.patch('cinder.manager.CleanableManager.do_cleanup', autospec=True)
    def test_init_host_with_service(self, mock_cleanup, mock_workers_init):
        mngr = FakeManager()
        self.assertFalse(hasattr(mngr, 'service_id'))
        mngr.init_host(service_id=self.service.id)

        self.assertEqual(self.service.id, mngr.service_id)
        mock_cleanup.assert_called_once_with(mngr, mock.ANY, mock.ANY)
        clean_req = mock_cleanup.call_args[0][2]
        self.assertIsInstance(clean_req, objects.CleanupRequest)
        self.assertEqual(self.service.id, clean_req.service_id)
        mock_workers_init.assert_called_once_with()

    def test_do_cleanup(self):
        """Basic successful cleanup."""
        vol = utils.create_volume(self.context, status='creating')
        db.worker_create(self.context, status='creating',
                         resource_type='Volume', resource_id=vol.id,
                         service_id=self.service.id)

        clean_req = objects.CleanupRequest(service_id=self.service.id)
        mngr = FakeManager(self.service.id)
        mngr.do_cleanup(self.context, clean_req)

        self.assertListEqual([], db.worker_get_all(self.context))
        vol.refresh()
        self.assertEqual('creating_cleaned', vol.status)

    def test_do_cleanup_not_cleaning_already_claimed(self):
        """Basic cleanup that doesn't touch already cleaning works."""
        vol = utils.create_volume(self.context, status='creating')
        worker1 = db.worker_create(self.context, status='creating',
                                   resource_type='Volume', resource_id=vol.id,
                                   service_id=self.service.id)
        worker1 = db.worker_get(self.context, id=worker1.id)
        vol2 = utils.create_volume(self.context, status='deleting')
        worker2 = db.worker_create(self.context, status='deleting',
                                   resource_type='Volume', resource_id=vol2.id,
                                   service_id=self.service.id + 1)
        worker2 = db.worker_get(self.context, id=worker2.id)

        # Simulate that the change to vol2 worker happened between
        # worker_get_all and trying to claim a work for cleanup
        worker2.service_id = self.service.id

        clean_req = objects.CleanupRequest(service_id=self.service.id)
        mngr = FakeManager(self.service.id)
        with mock.patch('cinder.db.worker_get_all') as get_all_mock:
            get_all_mock.return_value = [worker1, worker2]
            mngr.do_cleanup(self.context, clean_req)

        workers = db.worker_get_all(self.context)
        self.assertEqual(1, len(workers))
        self.assertEqual(worker2.id, workers[0].id)

        vol.refresh()
        self.assertEqual('creating_cleaned', vol.status)
        vol2.refresh()
        self.assertEqual('deleting', vol2.status)

    def test_do_cleanup_not_cleaning_already_claimed_by_us(self):
        """Basic cleanup that doesn't touch other thread's claimed works."""
        original_time = timeutils.utcnow()
        other_thread_claimed_time = timeutils.utcnow()
        vol = utils.create_volume(self.context, status='creating')
        worker1 = db.worker_create(self.context, status='creating',
                                   resource_type='Volume', resource_id=vol.id,
                                   service_id=self.service.id,
                                   updated_at=original_time)
        worker1 = db.worker_get(self.context, id=worker1.id)
        vol2 = utils.create_volume(self.context, status='deleting')
        worker2 = db.worker_create(self.context, status='deleting',
                                   resource_type='Volume', resource_id=vol2.id,
                                   service_id=self.service.id,
                                   updated_at=other_thread_claimed_time)
        worker2 = db.worker_get(self.context, id=worker2.id)

        # Simulate that the change to vol2 worker happened between
        # worker_get_all and trying to claim a work for cleanup
        worker2.updated_at = original_time

        clean_req = objects.CleanupRequest(service_id=self.service.id)
        mngr = FakeManager(self.service.id)
        with mock.patch('cinder.db.worker_get_all') as get_all_mock:
            get_all_mock.return_value = [worker1, worker2]
            mngr.do_cleanup(self.context, clean_req)

        workers = db.worker_get_all(self.context)
        self.assertEqual(1, len(workers))
        self.assertEqual(worker2.id, workers[0].id)

        vol.refresh()
        self.assertEqual('creating_cleaned', vol.status)
        vol2.refresh()
        self.assertEqual('deleting', vol2.status)

    def test_do_cleanup_resource_deleted(self):
        """Cleanup on a resource that's been already deleted."""
        vol = utils.create_volume(self.context, status='creating')
        db.worker_create(self.context, status='creating',
                         resource_type='Volume', resource_id=vol.id,
                         service_id=self.service.id)
        vol.destroy()

        clean_req = objects.CleanupRequest(service_id=self.service.id)
        mngr = FakeManager(self.service.id)
        mngr.do_cleanup(self.context, clean_req)

        workers = db.worker_get_all(self.context)
        self.assertListEqual([], workers)

    def test_do_cleanup_resource_on_another_service(self):
        """Cleanup on a resource that's been claimed by other service."""
        vol = utils.create_volume(self.context, status='deleting')
        db.worker_create(self.context, status='deleting',
                         resource_type='Volume', resource_id=vol.id,
                         service_id=self.service.id + 1)

        clean_req = objects.CleanupRequest(service_id=self.service.id)
        mngr = FakeManager(self.service.id)
        mngr.do_cleanup(self.context, clean_req)

        workers = db.worker_get_all(self.context)
        self.assertEqual(1, len(workers))

        vol.refresh()
        self.assertEqual('deleting', vol.status)

    def test_do_cleanup_resource_changed_status(self):
        """Cleanup on a resource that's changed status."""
        vol = utils.create_volume(self.context, status='available')
        db.worker_create(self.context, status='creating',
                         resource_type='Volume', resource_id=vol.id,
                         service_id=self.service.id)

        clean_req = objects.CleanupRequest(service_id=self.service.id)
        mngr = FakeManager(self.service.id)
        mngr.do_cleanup(self.context, clean_req)

        workers = db.worker_get_all(self.context)
        self.assertListEqual([], workers)

        vol.refresh()
        self.assertEqual('available', vol.status)

    def test_do_cleanup_keep_worker(self):
        """Cleanup on a resource that will remove worker when cleaning up."""
        vol = utils.create_volume(self.context, status='deleting')
        db.worker_create(self.context, status='deleting',
                         resource_type='Volume', resource_id=vol.id,
                         service_id=self.service.id)

        clean_req = objects.CleanupRequest(service_id=self.service.id)
        mngr = FakeManager(self.service.id, keep_after_clean=True)
        mngr.do_cleanup(self.context, clean_req)

        workers = db.worker_get_all(self.context)
        self.assertEqual(1, len(workers))
        vol.refresh()
        self.assertEqual('deleting_cleaned', vol.status)

    @mock.patch.object(FakeManager, '_do_cleanup', side_effect=Exception)
    def test_do_cleanup_revive_on_cleanup_fail(self, mock_clean):
        """Cleanup will revive a worker if cleanup fails."""
        vol = utils.create_volume(self.context, status='creating')
        db.worker_create(self.context, status='creating',
                         resource_type='Volume', resource_id=vol.id,
                         service_id=self.service.id)

        clean_req = objects.CleanupRequest(service_id=self.service.id)
        mngr = FakeManager(self.service.id)
        mngr.do_cleanup(self.context, clean_req)

        workers = db.worker_get_all(self.context)
        self.assertEqual(1, len(workers))
        vol.refresh()
        self.assertEqual('creating', vol.status)
