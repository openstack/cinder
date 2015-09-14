# Copyright (C) 2012 Hewlett-Packard Development Company, L.P.
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
"""Tests for Backup code."""

import ddt
import tempfile
import uuid

import mock
from oslo_config import cfg
from oslo_utils import importutils
from oslo_utils import timeutils

from cinder.backup import api
from cinder.backup import manager
from cinder import context
from cinder import db
from cinder import exception
from cinder import objects
from cinder import test
from cinder.tests.unit.backup import fake_service_with_verify as fake_service
from cinder.volume.drivers import lvm


CONF = cfg.CONF


class FakeBackupException(Exception):
    pass


class BaseBackupTest(test.TestCase):
    def setUp(self):
        super(BaseBackupTest, self).setUp()
        vol_tmpdir = tempfile.mkdtemp()
        self.flags(volumes_dir=vol_tmpdir)
        self.backup_mgr = importutils.import_object(CONF.backup_manager)
        self.backup_mgr.host = 'testhost'
        self.ctxt = context.get_admin_context()
        self.backup_mgr.driver.set_initialized()

    def _create_backup_db_entry(self, volume_id=1, display_name='test_backup',
                                display_description='this is a test backup',
                                container='volumebackups',
                                status='creating',
                                size=1,
                                object_count=0,
                                project_id='fake',
                                service=None,
                                temp_volume_id=None,
                                temp_snapshot_id=None):
        """Create a backup entry in the DB.

        Return the entry ID
        """
        kwargs = {}
        kwargs['volume_id'] = volume_id
        kwargs['user_id'] = 'fake'
        kwargs['project_id'] = project_id
        kwargs['host'] = 'testhost'
        kwargs['availability_zone'] = '1'
        kwargs['display_name'] = display_name
        kwargs['display_description'] = display_description
        kwargs['container'] = container
        kwargs['status'] = status
        kwargs['fail_reason'] = ''
        kwargs['service'] = service or CONF.backup_driver
        kwargs['snapshot'] = False
        kwargs['parent_id'] = None
        kwargs['size'] = size
        kwargs['object_count'] = object_count
        kwargs['temp_volume_id'] = temp_volume_id
        kwargs['temp_snapshot_id'] = temp_snapshot_id
        backup = objects.Backup(context=self.ctxt, **kwargs)
        backup.create()
        return backup

    def _create_volume_db_entry(self, display_name='test_volume',
                                display_description='this is a test volume',
                                status='backing-up',
                                previous_status='available',
                                size=1):
        """Create a volume entry in the DB.

        Return the entry ID
        """
        vol = {}
        vol['size'] = size
        vol['host'] = 'testhost'
        vol['user_id'] = 'fake'
        vol['project_id'] = 'fake'
        vol['status'] = status
        vol['display_name'] = display_name
        vol['display_description'] = display_description
        vol['attach_status'] = 'detached'
        vol['availability_zone'] = '1'
        vol['previous_status'] = previous_status
        return db.volume_create(self.ctxt, vol)['id']

    def _create_snapshot_db_entry(self, display_name='test_snapshot',
                                  display_description='test snapshot',
                                  status='available',
                                  size=1,
                                  volume_id='1',
                                  provider_location=None):
        """Create a snapshot entry in the DB.

        Return the entry ID.
        """
        kwargs = {}
        kwargs['size'] = size
        kwargs['host'] = 'testhost'
        kwargs['user_id'] = 'fake'
        kwargs['project_id'] = 'fake'
        kwargs['status'] = status
        kwargs['display_name'] = display_name
        kwargs['display_description'] = display_description
        kwargs['volume_id'] = volume_id
        kwargs['cgsnapshot_id'] = None
        kwargs['volume_size'] = size
        kwargs['provider_location'] = provider_location
        snapshot_obj = objects.Snapshot(context=self.ctxt, **kwargs)
        snapshot_obj.create()
        return snapshot_obj

    def _create_volume_attach(self, volume_id):
        values = {'volume_id': volume_id,
                  'attach_status': 'attached', }
        attachment = db.volume_attach(self.ctxt, values)
        db.volume_attached(self.ctxt, attachment['id'], None, 'testhost',
                           '/dev/vd0')

    def _create_exported_record_entry(self, vol_size=1, exported_id=None):
        """Create backup metadata export entry."""
        vol_id = self._create_volume_db_entry(status='available',
                                              size=vol_size)
        backup = self._create_backup_db_entry(status='available',
                                              volume_id=vol_id)

        if exported_id is not None:
            backup.id = exported_id

        export = self.backup_mgr.export_record(self.ctxt, backup)
        return export

    def _create_export_record_db_entry(self,
                                       volume_id='0000',
                                       status='creating',
                                       project_id='fake',
                                       backup_id=None):
        """Create a backup entry in the DB.

        Return the entry ID
        """
        kwargs = {}
        kwargs['volume_id'] = volume_id
        kwargs['user_id'] = 'fake'
        kwargs['project_id'] = project_id
        kwargs['status'] = status
        if backup_id:
            kwargs['id'] = backup_id
        backup = objects.BackupImport(context=self.ctxt, **kwargs)
        backup.create()
        return backup


@ddt.ddt
class BackupTestCase(BaseBackupTest):
    """Test Case for backups."""

    @mock.patch.object(lvm.LVMVolumeDriver, 'delete_snapshot')
    @mock.patch.object(lvm.LVMVolumeDriver, 'delete_volume')
    def test_init_host(self, mock_delete_volume, mock_delete_snapshot):
        """Test stuck volumes and backups.

        Make sure stuck volumes and backups are reset to correct
        states when backup_manager.init_host() is called
        """
        vol1_id = self._create_volume_db_entry()
        self._create_volume_attach(vol1_id)
        db.volume_update(self.ctxt, vol1_id, {'status': 'backing-up'})
        vol2_id = self._create_volume_db_entry()
        self._create_volume_attach(vol2_id)
        db.volume_update(self.ctxt, vol2_id, {'status': 'restoring-backup'})
        vol3_id = self._create_volume_db_entry()
        db.volume_update(self.ctxt, vol3_id, {'status': 'available'})
        vol4_id = self._create_volume_db_entry()
        db.volume_update(self.ctxt, vol4_id, {'status': 'backing-up'})
        temp_vol_id = self._create_volume_db_entry()
        db.volume_update(self.ctxt, temp_vol_id, {'status': 'available'})
        vol5_id = self._create_volume_db_entry()
        db.volume_update(self.ctxt, vol5_id, {'status': 'backing-up'})
        temp_snap = self._create_snapshot_db_entry()
        temp_snap.status = 'available'
        temp_snap.save()
        vol6_id = self._create_volume_db_entry()
        db.volume_update(self.ctxt, vol6_id, {'status': 'restoring-backup'})

        backup1 = self._create_backup_db_entry(status='creating',
                                               volume_id=vol1_id)
        backup2 = self._create_backup_db_entry(status='restoring',
                                               volume_id=vol2_id)
        backup3 = self._create_backup_db_entry(status='deleting',
                                               volume_id=vol3_id)
        self._create_backup_db_entry(status='creating',
                                     volume_id=vol4_id,
                                     temp_volume_id=temp_vol_id)
        self._create_backup_db_entry(status='creating',
                                     volume_id=vol5_id,
                                     temp_snapshot_id=temp_snap.id)

        self.backup_mgr.init_host()

        vol1 = db.volume_get(self.ctxt, vol1_id)
        self.assertEqual('available', vol1['status'])
        vol2 = db.volume_get(self.ctxt, vol2_id)
        self.assertEqual('error_restoring', vol2['status'])
        vol3 = db.volume_get(self.ctxt, vol3_id)
        self.assertEqual('available', vol3['status'])
        vol4 = db.volume_get(self.ctxt, vol4_id)
        self.assertEqual('available', vol4['status'])
        vol5 = db.volume_get(self.ctxt, vol5_id)
        self.assertEqual('available', vol5['status'])
        vol6 = db.volume_get(self.ctxt, vol6_id)
        self.assertEqual('error_restoring', vol6['status'])

        backup1 = db.backup_get(self.ctxt, backup1.id)
        self.assertEqual('error', backup1['status'])
        backup2 = db.backup_get(self.ctxt, backup2.id)
        self.assertEqual('available', backup2['status'])
        self.assertRaises(exception.BackupNotFound,
                          db.backup_get,
                          self.ctxt,
                          backup3.id)

        self.assertTrue(mock_delete_volume.called)
        self.assertTrue(mock_delete_snapshot.called)

    @mock.patch('cinder.objects.backup.BackupList.get_all_by_host')
    @mock.patch('cinder.manager.SchedulerDependentManager._add_to_threadpool')
    def test_init_host_with_service_inithost_offload(self,
                                                     mock_add_threadpool,
                                                     mock_get_all_by_host):
        self.override_config('backup_service_inithost_offload', True)
        vol1_id = self._create_volume_db_entry()
        db.volume_update(self.ctxt, vol1_id, {'status': 'available'})
        backup1 = self._create_backup_db_entry(status='deleting',
                                               volume_id=vol1_id)

        vol2_id = self._create_volume_db_entry()
        db.volume_update(self.ctxt, vol2_id, {'status': 'available'})
        backup2 = self._create_backup_db_entry(status='deleting',
                                               volume_id=vol2_id)
        mock_get_all_by_host.return_value = [backup1, backup2]
        self.backup_mgr.init_host()
        calls = [mock.call(self.backup_mgr.delete_backup, mock.ANY, backup1),
                 mock.call(self.backup_mgr.delete_backup, mock.ANY, backup2)]
        mock_add_threadpool.assert_has_calls(calls, any_order=True)
        self.assertEqual(2, mock_add_threadpool.call_count)

    def test_init_host_handles_exception(self):
        """Test that exception in cleanup is handled."""

        self.mock_object(self.backup_mgr, '_init_volume_driver')
        mock_cleanup = self.mock_object(
            self.backup_mgr,
            '_cleanup_incomplete_backup_operations')
        mock_cleanup.side_effect = [Exception]

        self.assertIsNone(self.backup_mgr.init_host())

    def test_cleanup_incomplete_backup_operations_with_exceptions(self):
        """Test cleanup resilience in the face of exceptions."""

        fake_volume_list = [{'id': 'vol1'}, {'id': 'vol2'}]
        mock_volume_get_by_host = self.mock_object(
            db, 'volume_get_all_by_host')
        mock_volume_get_by_host.return_value = fake_volume_list

        mock_volume_cleanup = self.mock_object(
            self.backup_mgr, '_cleanup_one_volume')
        mock_volume_cleanup.side_effect = [Exception]

        fake_backup_list = [{'id': 'bkup1'}, {'id': 'bkup2'}, {'id': 'bkup3'}]
        mock_backup_get_by_host = self.mock_object(
            objects.BackupList, 'get_all_by_host')
        mock_backup_get_by_host.return_value = fake_backup_list

        mock_backup_cleanup = self.mock_object(
            self.backup_mgr, '_cleanup_one_backup')
        mock_backup_cleanup.side_effect = [Exception]

        mock_temp_cleanup = self.mock_object(
            self.backup_mgr, '_cleanup_temp_volumes_snapshots_for_one_backup')
        mock_temp_cleanup.side_effect = [Exception]

        self.assertIsNone(
            self.backup_mgr._cleanup_incomplete_backup_operations(
                self.ctxt))

        self.assertEqual(len(fake_volume_list), mock_volume_cleanup.call_count)
        self.assertEqual(len(fake_backup_list), mock_backup_cleanup.call_count)
        self.assertEqual(len(fake_backup_list), mock_temp_cleanup.call_count)

    def test_cleanup_one_backing_up_volume(self):
        """Test cleanup_one_volume for volume status 'backing-up'."""

        mock_get_manager = self.mock_object(
            self.backup_mgr, '_get_manager')
        mock_get_manager.return_value = 'fake_manager'

        volume_id = self._create_volume_db_entry(status='backing-up',
                                                 previous_status='available')
        volume = db.volume_get(self.ctxt, volume_id)

        self.backup_mgr._cleanup_one_volume(self.ctxt, volume)

        volume = db.volume_get(self.ctxt, volume_id)
        self.assertEqual('available', volume['status'])

    def test_cleanup_one_restoring_backup_volume(self):
        """Test cleanup_one_volume for volume status 'restoring-backup'."""

        mock_get_manager = self.mock_object(
            self.backup_mgr, '_get_manager')
        mock_get_manager.return_value = 'fake_manager'

        volume_id = self._create_volume_db_entry(status='restoring-backup')
        volume = db.volume_get(self.ctxt, volume_id)

        self.backup_mgr._cleanup_one_volume(self.ctxt, volume)

        volume = db.volume_get(self.ctxt, volume_id)
        self.assertEqual('error_restoring', volume['status'])

    def test_cleanup_one_creating_backup(self):
        """Test cleanup_one_backup for volume status 'creating'."""

        backup = self._create_backup_db_entry(status='creating')

        self.backup_mgr._cleanup_one_backup(self.ctxt, backup)

        self.assertEqual('error', backup.status)

    def test_cleanup_one_restoring_backup(self):
        """Test cleanup_one_backup for volume status 'restoring'."""

        backup = self._create_backup_db_entry(status='restoring')

        self.backup_mgr._cleanup_one_backup(self.ctxt, backup)

        self.assertEqual('available', backup.status)

    def test_cleanup_one_deleting_backup(self):
        """Test cleanup_one_backup for volume status 'deleting'."""

        backup = self._create_backup_db_entry(status='deleting')

        self.backup_mgr._cleanup_one_backup(self.ctxt, backup)

        self.assertRaises(exception.BackupNotFound,
                          db.backup_get,
                          self.ctxt,
                          backup.id)

    def test_detach_all_attachments_handles_exceptions(self):
        """Test detach_all_attachments with exceptions."""

        mock_log = self.mock_object(manager, 'LOG')
        mock_volume_mgr = mock.Mock()
        mock_detach_volume = mock_volume_mgr.detach_volume
        mock_detach_volume.side_effect = [Exception]

        fake_attachments = [
            {
                'id': 'attachment1',
                'attached_host': 'testhost',
                'instance_uuid': None,
            },
            {
                'id': 'attachment2',
                'attached_host': 'testhost',
                'instance_uuid': None,
            }
        ]
        fake_volume = {
            'id': 'fake_volume_id',
            'volume_attachment': fake_attachments
        }

        self.backup_mgr._detach_all_attachments(self.ctxt,
                                                mock_volume_mgr,
                                                fake_volume)

        self.assertEqual(len(fake_attachments), mock_log.exception.call_count)

    @ddt.data(KeyError, exception.VolumeNotFound)
    def test_cleanup_temp_volumes_snapshots_for_one_backup_volume_not_found(
            self, err):
        """Ensure we handle missing volume for a backup."""

        mock_volume_get = self.mock_object(db, 'volume_get')
        mock_volume_get.side_effect = [err]

        backup = self._create_backup_db_entry(status='creating')

        self.assertIsNone(
            self.backup_mgr._cleanup_temp_volumes_snapshots_for_one_backup(
                self.ctxt,
                backup))

    def test_cleanup_temp_snapshot_for_one_backup_not_found(self):
        """Ensure we handle missing temp snapshot for a backup."""
        mock_delete_snapshot = self.mock_object(
            lvm.LVMVolumeDriver, 'delete_snapshot')

        vol1_id = self._create_volume_db_entry()
        self._create_volume_attach(vol1_id)
        db.volume_update(self.ctxt, vol1_id, {'status': 'backing-up'})
        backup = self._create_backup_db_entry(status='error',
                                              volume_id=vol1_id,
                                              temp_snapshot_id='fake')

        self.assertIsNone(
            self.backup_mgr._cleanup_temp_volumes_snapshots_for_one_backup(
                self.ctxt,
                backup))

        self.assertFalse(mock_delete_snapshot.called)
        self.assertIsNone(backup.temp_snapshot_id)

        backup.destroy()
        db.volume_destroy(self.ctxt, vol1_id)

    def test_cleanup_temp_volume_for_one_backup_not_found(self):
        """Ensure we handle missing temp volume for a backup."""
        mock_delete_volume = self.mock_object(
            lvm.LVMVolumeDriver, 'delete_volume')

        vol1_id = self._create_volume_db_entry()
        self._create_volume_attach(vol1_id)
        db.volume_update(self.ctxt, vol1_id, {'status': 'backing-up'})
        backup = self._create_backup_db_entry(status='error',
                                              volume_id=vol1_id,
                                              temp_volume_id='fake')

        self.assertIsNone(
            self.backup_mgr._cleanup_temp_volumes_snapshots_for_one_backup(
                self.ctxt,
                backup))

        self.assertFalse(mock_delete_volume.called)
        self.assertIsNone(backup.temp_volume_id)

        backup.destroy()
        db.volume_destroy(self.ctxt, vol1_id)

    def test_create_backup_with_bad_volume_status(self):
        """Test creating a backup from a volume with a bad status."""
        vol_id = self._create_volume_db_entry(status='restoring', size=1)
        backup = self._create_backup_db_entry(volume_id=vol_id)
        self.assertRaises(exception.InvalidVolume,
                          self.backup_mgr.create_backup,
                          self.ctxt,
                          backup)

    def test_create_backup_with_bad_backup_status(self):
        """Test creating a backup with a backup with a bad status."""
        vol_id = self._create_volume_db_entry(size=1)
        backup = self._create_backup_db_entry(status='available',
                                              volume_id=vol_id)
        self.assertRaises(exception.InvalidBackup,
                          self.backup_mgr.create_backup,
                          self.ctxt,
                          backup)

    @mock.patch('%s.%s' % (CONF.volume_driver, 'backup_volume'))
    def test_create_backup_with_error(self, _mock_volume_backup):
        """Test error handling when error occurs during backup creation."""
        vol_id = self._create_volume_db_entry(size=1)
        backup = self._create_backup_db_entry(volume_id=vol_id)

        _mock_volume_backup.side_effect = FakeBackupException('fake')
        self.assertRaises(FakeBackupException,
                          self.backup_mgr.create_backup,
                          self.ctxt,
                          backup)
        vol = db.volume_get(self.ctxt, vol_id)
        self.assertEqual('available', vol['status'])
        self.assertEqual('error_backing-up', vol['previous_status'])
        backup = db.backup_get(self.ctxt, backup.id)
        self.assertEqual('error', backup['status'])
        self.assertTrue(_mock_volume_backup.called)

    @mock.patch('%s.%s' % (CONF.volume_driver, 'backup_volume'))
    def test_create_backup(self, _mock_volume_backup):
        """Test normal backup creation."""
        vol_size = 1
        vol_id = self._create_volume_db_entry(size=vol_size)
        backup = self._create_backup_db_entry(volume_id=vol_id)

        self.backup_mgr.create_backup(self.ctxt, backup)
        vol = db.volume_get(self.ctxt, vol_id)
        self.assertEqual('available', vol['status'])
        self.assertEqual('backing-up', vol['previous_status'])
        backup = db.backup_get(self.ctxt, backup.id)
        self.assertEqual('available', backup['status'])
        self.assertEqual(vol_size, backup['size'])
        self.assertTrue(_mock_volume_backup.called)

    @mock.patch('cinder.volume.utils.notify_about_backup_usage')
    @mock.patch('%s.%s' % (CONF.volume_driver, 'backup_volume'))
    def test_create_backup_with_notify(self, _mock_volume_backup, notify):
        """Test normal backup creation with notifications."""
        vol_size = 1
        vol_id = self._create_volume_db_entry(size=vol_size)
        backup = self._create_backup_db_entry(volume_id=vol_id)

        self.backup_mgr.create_backup(self.ctxt, backup)
        self.assertEqual(2, notify.call_count)

    def test_restore_backup_with_bad_volume_status(self):
        """Test error handling.

        Test error handling when restoring a backup to a volume
        with a bad status.
        """
        vol_id = self._create_volume_db_entry(status='available', size=1)
        backup = self._create_backup_db_entry(volume_id=vol_id)
        self.assertRaises(exception.InvalidVolume,
                          self.backup_mgr.restore_backup,
                          self.ctxt,
                          backup,
                          vol_id)
        backup = db.backup_get(self.ctxt, backup.id)
        self.assertEqual('available', backup['status'])

    def test_restore_backup_with_bad_backup_status(self):
        """Test error handling.

        Test error handling when restoring a backup with a backup
        with a bad status.
        """
        vol_id = self._create_volume_db_entry(status='restoring-backup',
                                              size=1)
        backup = self._create_backup_db_entry(status='available',
                                              volume_id=vol_id)
        self.assertRaises(exception.InvalidBackup,
                          self.backup_mgr.restore_backup,
                          self.ctxt,
                          backup,
                          vol_id)
        vol = db.volume_get(self.ctxt, vol_id)
        self.assertEqual('error', vol['status'])
        backup = db.backup_get(self.ctxt, backup.id)
        self.assertEqual('error', backup['status'])

    @mock.patch('%s.%s' % (CONF.volume_driver, 'restore_backup'))
    def test_restore_backup_with_driver_error(self, _mock_volume_restore):
        """Test error handling when an error occurs during backup restore."""
        vol_id = self._create_volume_db_entry(status='restoring-backup',
                                              size=1)
        backup = self._create_backup_db_entry(status='restoring',
                                              volume_id=vol_id)

        _mock_volume_restore.side_effect = FakeBackupException('fake')
        self.assertRaises(FakeBackupException,
                          self.backup_mgr.restore_backup,
                          self.ctxt,
                          backup,
                          vol_id)
        vol = db.volume_get(self.ctxt, vol_id)
        self.assertEqual('error_restoring', vol['status'])
        backup = db.backup_get(self.ctxt, backup.id)
        self.assertEqual('available', backup['status'])
        self.assertTrue(_mock_volume_restore.called)

    def test_restore_backup_with_bad_service(self):
        """Test error handling.

        Test error handling when attempting a restore of a backup
        with a different service to that used to create the backup.
        """
        vol_id = self._create_volume_db_entry(status='restoring-backup',
                                              size=1)
        service = 'cinder.tests.backup.bad_service'
        backup = self._create_backup_db_entry(status='restoring',
                                              volume_id=vol_id,
                                              service=service)

        self.assertRaises(exception.InvalidBackup,
                          self.backup_mgr.restore_backup,
                          self.ctxt,
                          backup,
                          vol_id)
        vol = db.volume_get(self.ctxt, vol_id)
        self.assertEqual('error', vol['status'])
        backup = db.backup_get(self.ctxt, backup.id)
        self.assertEqual('available', backup['status'])

    @mock.patch('%s.%s' % (CONF.volume_driver, 'restore_backup'))
    def test_restore_backup(self, _mock_volume_restore):
        """Test normal backup restoration."""
        vol_size = 1
        vol_id = self._create_volume_db_entry(status='restoring-backup',
                                              size=vol_size)
        backup = self._create_backup_db_entry(status='restoring',
                                              volume_id=vol_id)

        self.backup_mgr.restore_backup(self.ctxt, backup, vol_id)
        vol = db.volume_get(self.ctxt, vol_id)
        self.assertEqual('available', vol['status'])
        backup = db.backup_get(self.ctxt, backup.id)
        self.assertEqual('available', backup['status'])
        self.assertTrue(_mock_volume_restore.called)

    @mock.patch('cinder.volume.utils.notify_about_backup_usage')
    @mock.patch('%s.%s' % (CONF.volume_driver, 'restore_backup'))
    def test_restore_backup_with_notify(self, _mock_volume_restore, notify):
        """Test normal backup restoration with notifications."""
        vol_size = 1
        vol_id = self._create_volume_db_entry(status='restoring-backup',
                                              size=vol_size)
        backup = self._create_backup_db_entry(status='restoring',
                                              volume_id=vol_id)

        self.backup_mgr.restore_backup(self.ctxt, backup, vol_id)
        self.assertEqual(2, notify.call_count)

    def test_delete_backup_with_bad_backup_status(self):
        """Test error handling.

        Test error handling when deleting a backup with a backup
        with a bad status.
        """
        vol_id = self._create_volume_db_entry(size=1)
        backup = self._create_backup_db_entry(status='available',
                                              volume_id=vol_id)
        self.assertRaises(exception.InvalidBackup,
                          self.backup_mgr.delete_backup,
                          self.ctxt,
                          backup)
        backup = db.backup_get(self.ctxt, backup.id)
        self.assertEqual('error', backup['status'])

    def test_delete_backup_with_error(self):
        """Test error handling when an error occurs during backup deletion."""
        vol_id = self._create_volume_db_entry(size=1)
        backup = self._create_backup_db_entry(status='deleting',
                                              display_name='fail_on_delete',
                                              volume_id=vol_id)
        self.assertRaises(IOError,
                          self.backup_mgr.delete_backup,
                          self.ctxt,
                          backup)
        backup = db.backup_get(self.ctxt, backup.id)
        self.assertEqual('error', backup['status'])

    def test_delete_backup_with_bad_service(self):
        """Test error handling.

        Test error handling when attempting a delete of a backup
        with a different service to that used to create the backup.
        """
        vol_id = self._create_volume_db_entry(size=1)
        service = 'cinder.tests.backup.bad_service'
        backup = self._create_backup_db_entry(status='deleting',
                                              volume_id=vol_id,
                                              service=service)
        self.assertRaises(exception.InvalidBackup,
                          self.backup_mgr.delete_backup,
                          self.ctxt,
                          backup)
        backup = db.backup_get(self.ctxt, backup.id)
        self.assertEqual('error', backup['status'])

    def test_delete_backup_with_no_service(self):
        """Test error handling.

        Test error handling when attempting a delete of a backup
        with no service defined for that backup, relates to bug #1162908
        """
        vol_id = self._create_volume_db_entry(size=1)
        backup = self._create_backup_db_entry(status='deleting',
                                              volume_id=vol_id)
        backup.service = None
        backup.save()
        self.backup_mgr.delete_backup(self.ctxt, backup)

    def test_delete_backup(self):
        """Test normal backup deletion."""
        vol_id = self._create_volume_db_entry(size=1)
        backup = self._create_backup_db_entry(status='deleting',
                                              volume_id=vol_id)
        self.backup_mgr.delete_backup(self.ctxt, backup)
        self.assertRaises(exception.BackupNotFound,
                          db.backup_get,
                          self.ctxt,
                          backup.id)

        ctxt_read_deleted = context.get_admin_context('yes')
        backup = db.backup_get(ctxt_read_deleted, backup.id)
        self.assertEqual(True, backup.deleted)
        self.assertGreaterEqual(timeutils.utcnow(), backup.deleted_at)
        self.assertEqual('deleted', backup.status)

    @mock.patch('cinder.volume.utils.notify_about_backup_usage')
    def test_delete_backup_with_notify(self, notify):
        """Test normal backup deletion with notifications."""
        vol_id = self._create_volume_db_entry(size=1)
        backup = self._create_backup_db_entry(status='deleting',
                                              volume_id=vol_id)
        self.backup_mgr.delete_backup(self.ctxt, backup)
        self.assertEqual(2, notify.call_count)

    def test_list_backup(self):
        backups = db.backup_get_all_by_project(self.ctxt, 'project1')
        self.assertEqual(0, len(backups))

        self._create_backup_db_entry()
        b2 = self._create_backup_db_entry(project_id='project1')
        backups = db.backup_get_all_by_project(self.ctxt, 'project1')
        self.assertEqual(1, len(backups))
        self.assertEqual(b2.id, backups[0].id)

    def test_backup_get_all_by_project_with_deleted(self):
        """Test deleted backups.

        Test deleted backups don't show up in backup_get_all_by_project.
        Unless context.read_deleted is 'yes'.
        """
        backups = db.backup_get_all_by_project(self.ctxt, 'fake')
        self.assertEqual(0, len(backups))

        backup_keep = self._create_backup_db_entry()
        backup = self._create_backup_db_entry()
        db.backup_destroy(self.ctxt, backup.id)

        backups = db.backup_get_all_by_project(self.ctxt, 'fake')
        self.assertEqual(1, len(backups))
        self.assertEqual(backup_keep.id, backups[0].id)

        ctxt_read_deleted = context.get_admin_context('yes')
        backups = db.backup_get_all_by_project(ctxt_read_deleted, 'fake')
        self.assertEqual(2, len(backups))

    def test_backup_get_all_by_host_with_deleted(self):
        """Test deleted backups.

        Test deleted backups don't show up in backup_get_all_by_project.
        Unless context.read_deleted is 'yes'
        """
        backups = db.backup_get_all_by_host(self.ctxt, 'testhost')
        self.assertEqual(0, len(backups))

        backup_keep = self._create_backup_db_entry()
        backup = self._create_backup_db_entry()
        db.backup_destroy(self.ctxt, backup.id)

        backups = db.backup_get_all_by_host(self.ctxt, 'testhost')
        self.assertEqual(1, len(backups))
        self.assertEqual(backup_keep.id, backups[0].id)

        ctxt_read_deleted = context.get_admin_context('yes')
        backups = db.backup_get_all_by_host(ctxt_read_deleted, 'testhost')
        self.assertEqual(2, len(backups))

    def test_backup_manager_driver_name(self):
        """Test mapping between backup services and backup drivers."""
        self.override_config('backup_driver', "cinder.backup.services.swift")
        backup_mgr = \
            importutils.import_object(CONF.backup_manager)
        self.assertEqual('cinder.backup.drivers.swift',
                         backup_mgr.driver_name)

    def test_export_record_with_bad_service(self):
        """Test error handling.

        Test error handling when attempting an export of a backup
        record with a different service to that used to create the backup.
        """
        vol_id = self._create_volume_db_entry(size=1)
        service = 'cinder.tests.backup.bad_service'
        backup = self._create_backup_db_entry(status='available',
                                              volume_id=vol_id,
                                              service=service)

        self.assertRaises(exception.InvalidBackup,
                          self.backup_mgr.export_record,
                          self.ctxt,
                          backup)

    def test_export_record_with_bad_backup_status(self):
        """Test error handling.

        Test error handling when exporting a backup record with a backup
        with a bad status.
        """
        vol_id = self._create_volume_db_entry(status='available',
                                              size=1)
        backup = self._create_backup_db_entry(status='error',
                                              volume_id=vol_id)
        self.assertRaises(exception.InvalidBackup,
                          self.backup_mgr.export_record,
                          self.ctxt,
                          backup)

    def test_export_record(self):
        """Test normal backup record export."""
        vol_size = 1
        vol_id = self._create_volume_db_entry(status='available',
                                              size=vol_size)
        backup = self._create_backup_db_entry(status='available',
                                              volume_id=vol_id)

        export = self.backup_mgr.export_record(self.ctxt, backup)
        self.assertEqual(CONF.backup_driver, export['backup_service'])
        self.assertTrue('backup_url' in export)

    def test_import_record_with_verify_not_implemented(self):
        """Test normal backup record import.

        Test the case when import succeeds for the case that the
        driver does not support verify.
        """
        vol_size = 1
        backup_id = uuid.uuid4()
        export = self._create_exported_record_entry(vol_size=vol_size,
                                                    exported_id=backup_id)
        imported_record = self._create_export_record_db_entry(
            backup_id=backup_id)
        backup_hosts = []
        self.backup_mgr.import_record(self.ctxt,
                                      imported_record,
                                      export['backup_service'],
                                      export['backup_url'],
                                      backup_hosts)
        backup = db.backup_get(self.ctxt, imported_record.id)
        self.assertEqual('available', backup['status'])
        self.assertEqual(vol_size, backup['size'])

    def test_import_record_with_wrong_id(self):
        """Test normal backup record import.

        Test the case when import succeeds for the case that the
        driver does not support verify.
        """
        vol_size = 1
        export = self._create_exported_record_entry(vol_size=vol_size)
        imported_record = self._create_export_record_db_entry()
        backup_hosts = []
        self.assertRaises(exception.InvalidBackup,
                          self.backup_mgr.import_record,
                          self.ctxt,
                          imported_record,
                          export['backup_service'],
                          export['backup_url'],
                          backup_hosts)

    def test_import_record_with_bad_service(self):
        """Test error handling.

        Test error handling when attempting an import of a backup
        record with a different service to that used to create the backup.
        """
        export = self._create_exported_record_entry()
        export['backup_service'] = 'cinder.tests.unit.backup.bad_service'
        imported_record = self._create_export_record_db_entry()

        # Test the case where the additional hosts list is empty
        backup_hosts = []
        self.assertRaises(exception.ServiceNotFound,
                          self.backup_mgr.import_record,
                          self.ctxt,
                          imported_record,
                          export['backup_service'],
                          export['backup_url'],
                          backup_hosts)

        # Test that the import backup keeps calling other hosts to find a
        # suitable host for the backup service
        backup_hosts = ['fake1', 'fake2']
        backup_hosts_expect = list(backup_hosts)
        BackupAPI_import = 'cinder.backup.rpcapi.BackupAPI.import_record'
        with mock.patch(BackupAPI_import) as _mock_backup_import:
            self.backup_mgr.import_record(self.ctxt,
                                          imported_record,
                                          export['backup_service'],
                                          export['backup_url'],
                                          backup_hosts)

            next_host = backup_hosts_expect.pop()
            _mock_backup_import.assert_called_once_with(
                self.ctxt,
                next_host,
                imported_record,
                export['backup_service'],
                export['backup_url'],
                backup_hosts_expect)

    def test_import_record_with_invalid_backup(self):
        """Test error handling.

        Test error handling when attempting an import of a backup
        record where the backup driver returns an exception.
        """
        export = self._create_exported_record_entry()
        backup_driver = self.backup_mgr.service.get_backup_driver(self.ctxt)
        _mock_record_import_class = ('%s.%s.%s' %
                                     (backup_driver.__module__,
                                      backup_driver.__class__.__name__,
                                      'import_record'))
        imported_record = self._create_export_record_db_entry()
        backup_hosts = []
        with mock.patch(_mock_record_import_class) as _mock_record_import:
            _mock_record_import.side_effect = FakeBackupException('fake')
            self.assertRaises(exception.InvalidBackup,
                              self.backup_mgr.import_record,
                              self.ctxt,
                              imported_record,
                              export['backup_service'],
                              export['backup_url'],
                              backup_hosts)
            self.assertTrue(_mock_record_import.called)
        backup = db.backup_get(self.ctxt, imported_record.id)
        self.assertEqual('error', backup['status'])

    def test_not_supported_driver_to_force_delete(self):
        """Test force delete check method for not supported drivers."""
        self.override_config('backup_driver', 'cinder.backup.drivers.ceph')
        self.backup_mgr = importutils.import_object(CONF.backup_manager)
        result = self.backup_mgr.check_support_to_force_delete(self.ctxt)
        self.assertFalse(result)

    @mock.patch('cinder.backup.drivers.nfs.NFSBackupDriver.'
                '_init_backup_repo_path', return_value=None)
    @mock.patch('cinder.backup.drivers.nfs.NFSBackupDriver.'
                '_check_configuration', return_value=None)
    def test_check_support_to_force_delete(self, mock_check_configuration,
                                           mock_init_backup_repo_path):
        """Test force delete check method for supported drivers."""
        self.override_config('backup_driver', 'cinder.backup.drivers.nfs')
        self.backup_mgr = importutils.import_object(CONF.backup_manager)
        result = self.backup_mgr.check_support_to_force_delete(self.ctxt)
        self.assertTrue(result)

    def test_backup_has_dependent_backups(self):
        """Test backup has dependent backups.

        Test the query of has_dependent_backups in backup object is correct.
        """
        vol_size = 1
        vol_id = self._create_volume_db_entry(size=vol_size)
        backup = self._create_backup_db_entry(volume_id=vol_id)
        self.assertFalse(backup.has_dependent_backups)


class BackupTestCaseWithVerify(BaseBackupTest):
    """Test Case for backups."""

    def setUp(self):
        self.override_config(
            "backup_driver",
            "cinder.tests.unit.backup.fake_service_with_verify")
        super(BackupTestCaseWithVerify, self).setUp()

    def test_import_record_with_verify(self):
        """Test normal backup record import.

        Test the case when import succeeds for the case that the
        driver implements verify.
        """
        vol_size = 1
        backup_id = uuid.uuid4()
        export = self._create_exported_record_entry(
            vol_size=vol_size, exported_id=backup_id)
        imported_record = self._create_export_record_db_entry(
            backup_id=backup_id)
        backup_hosts = []
        backup_driver = self.backup_mgr.service.get_backup_driver(self.ctxt)
        _mock_backup_verify_class = ('%s.%s.%s' %
                                     (backup_driver.__module__,
                                      backup_driver.__class__.__name__,
                                      'verify'))
        with mock.patch(_mock_backup_verify_class):
            self.backup_mgr.import_record(self.ctxt,
                                          imported_record,
                                          export['backup_service'],
                                          export['backup_url'],
                                          backup_hosts)
        backup = db.backup_get(self.ctxt, imported_record.id)
        self.assertEqual('available', backup['status'])
        self.assertEqual(vol_size, backup['size'])

    def test_import_record_with_verify_invalid_backup(self):
        """Test error handling.

        Test error handling when attempting an import of a backup
        record where the backup driver returns an exception.
        """
        vol_size = 1
        backup_id = uuid.uuid4()
        export = self._create_exported_record_entry(
            vol_size=vol_size, exported_id=backup_id)
        imported_record = self._create_export_record_db_entry(
            backup_id=backup_id)
        backup_hosts = []
        backup_driver = self.backup_mgr.service.get_backup_driver(self.ctxt)
        _mock_backup_verify_class = ('%s.%s.%s' %
                                     (backup_driver.__module__,
                                      backup_driver.__class__.__name__,
                                      'verify'))
        with mock.patch(_mock_backup_verify_class) as _mock_record_verify:
            _mock_record_verify.side_effect = \
                exception.InvalidBackup(reason='fake')

            self.assertRaises(exception.InvalidBackup,
                              self.backup_mgr.import_record,
                              self.ctxt,
                              imported_record,
                              export['backup_service'],
                              export['backup_url'],
                              backup_hosts)
            self.assertTrue(_mock_record_verify.called)
        backup = db.backup_get(self.ctxt, imported_record.id)
        self.assertEqual('error', backup['status'])

    def test_backup_reset_status_from_nonrestoring_to_available(
            self):
        vol_id = self._create_volume_db_entry(status='available',
                                              size=1)
        backup = self._create_backup_db_entry(status='error',
                                              volume_id=vol_id)
        with mock.patch.object(manager.BackupManager,
                               '_map_service_to_driver') as \
                mock_map_service_to_driver:
            mock_map_service_to_driver.return_value = \
                fake_service.get_backup_driver(self.ctxt)
            self.backup_mgr.reset_status(self.ctxt,
                                         backup,
                                         'available')
        backup = db.backup_get(self.ctxt, backup.id)
        self.assertEqual('available', backup['status'])

    def test_backup_reset_status_to_available_invalid_backup(self):
        volume = db.volume_create(self.ctxt, {'status': 'available',
                                              'host': 'test',
                                              'provider_location': '',
                                              'size': 1})
        backup = self._create_backup_db_entry(status='error',
                                              volume_id=volume['id'])

        backup_driver = self.backup_mgr.service.get_backup_driver(self.ctxt)
        _mock_backup_verify_class = ('%s.%s.%s' %
                                     (backup_driver.__module__,
                                      backup_driver.__class__.__name__,
                                      'verify'))
        with mock.patch(_mock_backup_verify_class) as \
                _mock_record_verify:
            _mock_record_verify.side_effect = \
                exception.BackupVerifyUnsupportedDriver(reason='fake')

            self.assertRaises(exception.BackupVerifyUnsupportedDriver,
                              self.backup_mgr.reset_status,
                              self.ctxt,
                              backup,
                              'available')
            backup = db.backup_get(self.ctxt, backup.id)
            self.assertEqual('error', backup['status'])

    def test_backup_reset_status_from_restoring_to_available(self):
        volume = db.volume_create(self.ctxt,
                                  {'status': 'available',
                                   'host': 'test',
                                   'provider_location': '',
                                   'size': 1})
        backup = self._create_backup_db_entry(status='restoring',
                                              volume_id=volume['id'])

        self.backup_mgr.reset_status(self.ctxt, backup, 'available')
        backup = db.backup_get(self.ctxt, backup.id)
        self.assertEqual('available', backup['status'])

    def test_backup_reset_status_to_error(self):
        volume = db.volume_create(self.ctxt,
                                  {'status': 'available',
                                   'host': 'test',
                                   'provider_location': '',
                                   'size': 1})
        backup = self._create_backup_db_entry(status='creating',
                                              volume_id=volume['id'])
        self.backup_mgr.reset_status(self.ctxt, backup, 'error')
        backup = db.backup_get(self.ctxt, backup['id'])
        self.assertEqual('error', backup['status'])


@ddt.ddt
class BackupAPITestCase(BaseBackupTest):
    def setUp(self):
        super(BackupAPITestCase, self).setUp()
        self.api = api.API()

    def test_get_all_wrong_all_tenants_value(self):
        self.assertRaises(exception.InvalidParameterValue,
                          self.api.get_all, self.ctxt, {'all_tenants': 'bad'})

    @mock.patch.object(objects, 'BackupList')
    def test_get_all_no_all_tenants_value(self, mock_backuplist):
        result = self.api.get_all(self.ctxt, {'key': 'value'})
        self.assertFalse(mock_backuplist.get_all.called)
        self.assertEqual(mock_backuplist.get_all_by_project.return_value,
                         result)
        mock_backuplist.get_all_by_project.assert_called_once_with(
            self.ctxt, self.ctxt.project_id, {'key': 'value'}, None, None,
            None, None, None)

    @mock.patch.object(objects, 'BackupList')
    @ddt.data(False, 'false', '0', 0, 'no')
    def test_get_all_false_value_all_tenants(
            self, false_value, mock_backuplist):
        result = self.api.get_all(self.ctxt, {'all_tenants': false_value,
                                              'key': 'value'})
        self.assertFalse(mock_backuplist.get_all.called)
        self.assertEqual(mock_backuplist.get_all_by_project.return_value,
                         result)
        mock_backuplist.get_all_by_project.assert_called_once_with(
            self.ctxt, self.ctxt.project_id, {'key': 'value'}, None, None,
            None, None, None)

    @mock.patch.object(objects, 'BackupList')
    @ddt.data(True, 'true', '1', 1, 'yes')
    def test_get_all_true_value_all_tenants(
            self, true_value, mock_backuplist):
        result = self.api.get_all(self.ctxt, {'all_tenants': true_value,
                                              'key': 'value'})
        self.assertFalse(mock_backuplist.get_all_by_project.called)
        self.assertEqual(mock_backuplist.get_all.return_value,
                         result)
        mock_backuplist.get_all.assert_called_once_with(
            self.ctxt, {'key': 'value'}, None, None, None, None, None)

    @mock.patch.object(objects, 'BackupList')
    def test_get_all_true_value_all_tenants_non_admin(self, mock_backuplist):
        ctxt = context.RequestContext('fake', 'fake')
        result = self.api.get_all(ctxt, {'all_tenants': '1',
                                         'key': 'value'})
        self.assertFalse(mock_backuplist.get_all.called)
        self.assertEqual(mock_backuplist.get_all_by_project.return_value,
                         result)
        mock_backuplist.get_all_by_project.assert_called_once_with(
            ctxt, ctxt.project_id, {'key': 'value'}, None, None, None, None,
            None)
