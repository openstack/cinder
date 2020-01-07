# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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
from unittest import mock

from oslo_config import cfg

from cinder import context
from cinder import db
from cinder import exception
from cinder import objects
from cinder.objects import fields
from cinder import service
from cinder.tests.unit.api import fakes
from cinder.tests.unit import utils as tests_utils
from cinder.tests.unit import volume as base


CONF = cfg.CONF


class VolumeCleanupTestCase(base.BaseVolumeTestCase):
    MOCK_WORKER = False

    def setUp(self):
        super(VolumeCleanupTestCase, self).setUp()
        self.service_id = 1
        self.mock_object(service.Service, 'service_id', self.service_id)
        self.patch('cinder.volume.volume_utils.clear_volume', autospec=True)

    def _assert_workers_are_removed(self):
        workers = db.worker_get_all(self.context, read_deleted='yes')
        self.assertListEqual([], workers)

    def test_init_host_clears_uploads_available_volume(self):
        """init_host will clean an available volume stuck in uploading."""
        volume = tests_utils.create_volume(self.context, status='uploading',
                                           size=0, host=CONF.host)

        db.worker_create(self.context, resource_type='Volume',
                         resource_id=volume.id, status=volume.status,
                         service_id=self.service_id)

        self.volume.init_host(service_id=service.Service.service_id)
        volume.refresh()
        self.assertEqual("available", volume.status)
        self._assert_workers_are_removed()

    @mock.patch('cinder.manager.CleanableManager.init_host')
    def test_init_host_clears_uploads_in_use_volume(self, init_host_mock):
        """init_host will clean an in-use volume stuck in uploading."""
        volume = tests_utils.create_volume(self.context, status='uploading',
                                           size=0, host=CONF.host)

        db.worker_create(self.context, resource_type='Volume',
                         resource_id=volume.id, status=volume.status,
                         service_id=self.service_id)

        fake_uuid = fakes.get_fake_uuid()
        tests_utils.attach_volume(self.context, volume.id, fake_uuid,
                                  'fake_host', '/dev/vda')
        self.volume.init_host(service_id=mock.sentinel.service_id)
        init_host_mock.assert_called_once_with(
            service_id=mock.sentinel.service_id, added_to_cluster=None)
        volume.refresh()
        self.assertEqual("in-use", volume.status)
        self._assert_workers_are_removed()

    @mock.patch('cinder.image.image_utils.cleanup_temporary_file')
    def test_init_host_clears_downloads(self, mock_cleanup_tmp_file):
        """Test that init_host will unwedge a volume stuck in downloading."""
        volume = tests_utils.create_volume(self.context, status='downloading',
                                           size=0, host=CONF.host)
        db.worker_create(self.context, resource_type='Volume',
                         resource_id=volume.id, status=volume.status,
                         service_id=self.service_id)
        mock_clear = self.mock_object(self.volume.driver, 'clear_download')

        self.volume.init_host(service_id=service.Service.service_id)
        self.assertEqual(1, mock_clear.call_count)
        self.assertEqual(volume.id, mock_clear.call_args[0][1].id)
        volume.refresh()
        self.assertEqual("error", volume['status'])
        mock_cleanup_tmp_file.assert_called_once_with(CONF.host)

        self.volume.delete_volume(self.context, volume=volume)
        self._assert_workers_are_removed()

    @mock.patch('cinder.image.image_utils.cleanup_temporary_file')
    def test_init_host_resumes_deletes(self, mock_cleanup_tmp_file):
        """init_host will resume deleting volume in deleting status."""
        volume = tests_utils.create_volume(self.context, status='deleting',
                                           size=0, host=CONF.host)

        db.worker_create(self.context, resource_type='Volume',
                         resource_id=volume.id, status=volume.status,
                         service_id=self.service_id)

        self.volume.init_host(service_id=service.Service.service_id)

        self.assertRaises(exception.VolumeNotFound, db.volume_get,
                          context.get_admin_context(), volume.id)
        mock_cleanup_tmp_file.assert_called_once_with(CONF.host)
        self._assert_workers_are_removed()

    @mock.patch('cinder.image.image_utils.cleanup_temporary_file')
    def test_create_volume_fails_with_creating_and_downloading_status(
            self, mock_cleanup_tmp_file):
        """Test init_host_with_service in case of volume.

        While the status of volume is 'creating' or 'downloading',
        volume process down.
        After process restarting this 'creating' status is changed to 'error'.
        """
        for status in ('creating', 'downloading'):
            volume = tests_utils.create_volume(self.context, status=status,
                                               size=0, host=CONF.host)

            db.worker_create(self.context, resource_type='Volume',
                             resource_id=volume.id, status=volume.status,
                             service_id=self.service_id)

            self.volume.init_host(service_id=service.Service.service_id)
            volume.refresh()

            self.assertEqual('error', volume['status'])
            self.volume.delete_volume(self.context, volume)
            self.assertTrue(mock_cleanup_tmp_file.called)
            self._assert_workers_are_removed()

    def test_create_snapshot_fails_with_creating_status(self):
        """Test init_host_with_service in case of snapshot.

        While the status of snapshot is 'creating', volume process
        down. After process restarting this 'creating' status is
        changed to 'error'.
        """
        volume = tests_utils.create_volume(self.context,
                                           **self.volume_params)
        snapshot = tests_utils.create_snapshot(
            self.context,
            volume.id,
            status=fields.SnapshotStatus.CREATING)
        db.worker_create(self.context, resource_type='Snapshot',
                         resource_id=snapshot.id, status=snapshot.status,
                         service_id=self.service_id)

        self.volume.init_host(service_id=service.Service.service_id)

        snapshot_obj = objects.Snapshot.get_by_id(self.context, snapshot.id)

        self.assertEqual(fields.SnapshotStatus.ERROR, snapshot_obj.status)
        self.assertEqual(service.Service.service_id,
                         self.volume.service_id)
        self._assert_workers_are_removed()

        self.volume.delete_snapshot(self.context, snapshot_obj)
        self.volume.delete_volume(self.context, volume)

    def test_init_host_clears_deleting_snapshots(self):
        """Test that init_host will delete a snapshot stuck in deleting."""
        volume = tests_utils.create_volume(self.context, status='deleting',
                                           size=1, host=CONF.host)
        snapshot = tests_utils.create_snapshot(self.context,
                                               volume.id, status='deleting')

        db.worker_create(self.context, resource_type='Volume',
                         resource_id=volume.id, status=volume.status,
                         service_id=self.service_id)

        self.volume.init_host(service_id=self.service_id)
        self.assertRaises(exception.VolumeNotFound, volume.refresh)
        self.assertRaises(exception.SnapshotNotFound, snapshot.refresh)
