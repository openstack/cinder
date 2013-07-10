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
"""
Tests for Backup code.

"""

import tempfile

from oslo.config import cfg

from cinder import context
from cinder import db
from cinder import exception
from cinder.openstack.common import importutils
from cinder.openstack.common import log as logging
from cinder.openstack.common import timeutils
from cinder import test


CONF = cfg.CONF

LOG = logging.getLogger(__name__)


class FakeBackupException(Exception):
        pass


class BackupTestCase(test.TestCase):
    """Test Case for backups."""

    def setUp(self):
        super(BackupTestCase, self).setUp()
        vol_tmpdir = tempfile.mkdtemp()
        self.flags(connection_type='fake',
                   volumes_dir=vol_tmpdir)
        self.backup_mgr = \
            importutils.import_object(CONF.backup_manager)
        self.backup_mgr.host = 'testhost'
        self.ctxt = context.get_admin_context()

    def tearDown(self):
        super(BackupTestCase, self).tearDown()

    def _create_backup_db_entry(self, volume_id=1, display_name='test_backup',
                                display_description='this is a test backup',
                                container='volumebackups',
                                status='creating',
                                size=0,
                                object_count=0,
                                project_id='fake'):
        """
        Create a backup entry in the DB.
        Return the entry ID
        """
        backup = {}
        backup['volume_id'] = volume_id
        backup['user_id'] = 'fake'
        backup['project_id'] = project_id
        backup['host'] = 'testhost'
        backup['availability_zone'] = '1'
        backup['display_name'] = display_name
        backup['display_description'] = display_description
        backup['container'] = container
        backup['status'] = status
        backup['fail_reason'] = ''
        backup['service'] = CONF.backup_driver
        backup['size'] = size
        backup['object_count'] = object_count
        return db.backup_create(self.ctxt, backup)['id']

    def _create_volume_db_entry(self, display_name='test_volume',
                                display_description='this is a test volume',
                                status='backing-up',
                                size=1):
        """
        Create a volume entry in the DB.
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
        return db.volume_create(self.ctxt, vol)['id']

    def test_init_host(self):
        """Make sure stuck volumes and backups are reset to correct
        states when backup_manager.init_host() is called
        """
        vol1_id = self._create_volume_db_entry(status='backing-up')
        vol2_id = self._create_volume_db_entry(status='restoring-backup')
        backup1_id = self._create_backup_db_entry(status='creating')
        backup2_id = self._create_backup_db_entry(status='restoring')
        backup3_id = self._create_backup_db_entry(status='deleting')

        self.backup_mgr.init_host()
        vol1 = db.volume_get(self.ctxt, vol1_id)
        self.assertEquals(vol1['status'], 'available')
        vol2 = db.volume_get(self.ctxt, vol2_id)
        self.assertEquals(vol2['status'], 'error_restoring')

        backup1 = db.backup_get(self.ctxt, backup1_id)
        self.assertEquals(backup1['status'], 'error')
        backup2 = db.backup_get(self.ctxt, backup2_id)
        self.assertEquals(backup2['status'], 'available')
        self.assertRaises(exception.BackupNotFound,
                          db.backup_get,
                          self.ctxt,
                          backup3_id)

    def test_create_backup_with_bad_volume_status(self):
        """Test error handling when creating a backup from a volume
        with a bad status
        """
        vol_id = self._create_volume_db_entry(status='available', size=1)
        backup_id = self._create_backup_db_entry(volume_id=vol_id)
        self.assertRaises(exception.InvalidVolume,
                          self.backup_mgr.create_backup,
                          self.ctxt,
                          backup_id)

    def test_create_backup_with_bad_backup_status(self):
        """Test error handling when creating a backup with a backup
        with a bad status
        """
        vol_id = self._create_volume_db_entry(size=1)
        backup_id = self._create_backup_db_entry(status='available',
                                                 volume_id=vol_id)
        self.assertRaises(exception.InvalidBackup,
                          self.backup_mgr.create_backup,
                          self.ctxt,
                          backup_id)

    def test_create_backup_with_error(self):
        """Test error handling when an error occurs during backup creation"""
        vol_id = self._create_volume_db_entry(size=1)
        backup_id = self._create_backup_db_entry(volume_id=vol_id)

        def fake_backup_volume(context, backup, backup_service):
            raise FakeBackupException('fake')

        self.stubs.Set(self.backup_mgr.driver, 'backup_volume',
                       fake_backup_volume)

        self.assertRaises(FakeBackupException,
                          self.backup_mgr.create_backup,
                          self.ctxt,
                          backup_id)
        vol = db.volume_get(self.ctxt, vol_id)
        self.assertEquals(vol['status'], 'available')
        backup = db.backup_get(self.ctxt, backup_id)
        self.assertEquals(backup['status'], 'error')

    def test_create_backup(self):
        """Test normal backup creation"""
        vol_size = 1
        vol_id = self._create_volume_db_entry(size=vol_size)
        backup_id = self._create_backup_db_entry(volume_id=vol_id)

        def fake_backup_volume(context, backup, backup_service):
            pass

        self.stubs.Set(self.backup_mgr.driver, 'backup_volume',
                       fake_backup_volume)

        self.backup_mgr.create_backup(self.ctxt, backup_id)
        vol = db.volume_get(self.ctxt, vol_id)
        self.assertEquals(vol['status'], 'available')
        backup = db.backup_get(self.ctxt, backup_id)
        self.assertEquals(backup['status'], 'available')
        self.assertEqual(backup['size'], vol_size)

    def test_restore_backup_with_bad_volume_status(self):
        """Test error handling when restoring a backup to a volume
        with a bad status
        """
        vol_id = self._create_volume_db_entry(status='available', size=1)
        backup_id = self._create_backup_db_entry(volume_id=vol_id)
        self.assertRaises(exception.InvalidVolume,
                          self.backup_mgr.restore_backup,
                          self.ctxt,
                          backup_id,
                          vol_id)
        backup = db.backup_get(self.ctxt, backup_id)
        self.assertEquals(backup['status'], 'available')

    def test_restore_backup_with_bad_backup_status(self):
        """Test error handling when restoring a backup with a backup
        with a bad status
        """
        vol_id = self._create_volume_db_entry(status='restoring-backup',
                                              size=1)
        backup_id = self._create_backup_db_entry(status='available',
                                                 volume_id=vol_id)
        self.assertRaises(exception.InvalidBackup,
                          self.backup_mgr.restore_backup,
                          self.ctxt,
                          backup_id,
                          vol_id)
        vol = db.volume_get(self.ctxt, vol_id)
        self.assertEquals(vol['status'], 'error')
        backup = db.backup_get(self.ctxt, backup_id)
        self.assertEquals(backup['status'], 'error')

    def test_restore_backup_with_driver_error(self):
        """Test error handling when an error occurs during backup restore"""
        vol_id = self._create_volume_db_entry(status='restoring-backup',
                                              size=1)
        backup_id = self._create_backup_db_entry(status='restoring',
                                                 volume_id=vol_id)

        def fake_restore_backup(context, backup, volume, backup_service):
            raise FakeBackupException('fake')

        self.stubs.Set(self.backup_mgr.driver, 'restore_backup',
                       fake_restore_backup)

        self.assertRaises(FakeBackupException,
                          self.backup_mgr.restore_backup,
                          self.ctxt,
                          backup_id,
                          vol_id)
        vol = db.volume_get(self.ctxt, vol_id)
        self.assertEquals(vol['status'], 'error_restoring')
        backup = db.backup_get(self.ctxt, backup_id)
        self.assertEquals(backup['status'], 'available')

    def test_restore_backup_with_bad_service(self):
        """Test error handling when attempting a restore of a backup
        with a different service to that used to create the backup
        """
        vol_id = self._create_volume_db_entry(status='restoring-backup',
                                              size=1)
        backup_id = self._create_backup_db_entry(status='restoring',
                                                 volume_id=vol_id)

        def fake_restore_backup(context, backup, volume, backup_service):
            pass

        self.stubs.Set(self.backup_mgr.driver, 'restore_backup',
                       fake_restore_backup)

        service = 'cinder.tests.backup.bad_service'
        db.backup_update(self.ctxt, backup_id, {'service': service})
        self.assertRaises(exception.InvalidBackup,
                          self.backup_mgr.restore_backup,
                          self.ctxt,
                          backup_id,
                          vol_id)
        vol = db.volume_get(self.ctxt, vol_id)
        self.assertEquals(vol['status'], 'error')
        backup = db.backup_get(self.ctxt, backup_id)
        self.assertEquals(backup['status'], 'available')

    def test_restore_backup(self):
        """Test normal backup restoration"""
        vol_size = 1
        vol_id = self._create_volume_db_entry(status='restoring-backup',
                                              size=vol_size)
        backup_id = self._create_backup_db_entry(status='restoring',
                                                 volume_id=vol_id)

        def fake_restore_backup(context, backup, volume, backup_service):
            pass

        self.stubs.Set(self.backup_mgr.driver, 'restore_backup',
                       fake_restore_backup)

        self.backup_mgr.restore_backup(self.ctxt, backup_id, vol_id)
        vol = db.volume_get(self.ctxt, vol_id)
        self.assertEquals(vol['status'], 'available')
        backup = db.backup_get(self.ctxt, backup_id)
        self.assertEquals(backup['status'], 'available')

    def test_delete_backup_with_bad_backup_status(self):
        """Test error handling when deleting a backup with a backup
        with a bad status
        """
        vol_id = self._create_volume_db_entry(size=1)
        backup_id = self._create_backup_db_entry(status='available',
                                                 volume_id=vol_id)
        self.assertRaises(exception.InvalidBackup,
                          self.backup_mgr.delete_backup,
                          self.ctxt,
                          backup_id)
        backup = db.backup_get(self.ctxt, backup_id)
        self.assertEquals(backup['status'], 'error')

    def test_delete_backup_with_error(self):
        """Test error handling when an error occurs during backup deletion."""
        vol_id = self._create_volume_db_entry(size=1)
        backup_id = self._create_backup_db_entry(status='deleting',
                                                 display_name='fail_on_delete',
                                                 volume_id=vol_id)
        self.assertRaises(IOError,
                          self.backup_mgr.delete_backup,
                          self.ctxt,
                          backup_id)
        backup = db.backup_get(self.ctxt, backup_id)
        self.assertEquals(backup['status'], 'error')

    def test_delete_backup_with_bad_service(self):
        """Test error handling when attempting a delete of a backup
        with a different service to that used to create the backup
        """
        vol_id = self._create_volume_db_entry(size=1)
        backup_id = self._create_backup_db_entry(status='deleting',
                                                 volume_id=vol_id)
        service = 'cinder.tests.backup.bad_service'
        db.backup_update(self.ctxt, backup_id, {'service': service})
        self.assertRaises(exception.InvalidBackup,
                          self.backup_mgr.delete_backup,
                          self.ctxt,
                          backup_id)
        backup = db.backup_get(self.ctxt, backup_id)
        self.assertEquals(backup['status'], 'error')

    def test_delete_backup_with_no_service(self):
        """Test error handling when attempting a delete of a backup
        with no service defined for that backup, relates to bug #1162908
        """
        vol_id = self._create_volume_db_entry(size=1)
        backup_id = self._create_backup_db_entry(status='deleting',
                                                 volume_id=vol_id)
        db.backup_update(self.ctxt, backup_id, {'service': None})
        self.backup_mgr.delete_backup(self.ctxt, backup_id)

    def test_delete_backup(self):
        """Test normal backup deletion"""
        vol_id = self._create_volume_db_entry(size=1)
        backup_id = self._create_backup_db_entry(status='deleting',
                                                 volume_id=vol_id)
        self.backup_mgr.delete_backup(self.ctxt, backup_id)
        self.assertRaises(exception.BackupNotFound,
                          db.backup_get,
                          self.ctxt,
                          backup_id)

        ctxt_read_deleted = context.get_admin_context('yes')
        backup = db.backup_get(ctxt_read_deleted, backup_id)
        self.assertEqual(backup.deleted, True)
        self.assertTrue(timeutils.utcnow() > backup.deleted_at)
        self.assertEqual(backup.status, 'deleted')

    def test_list_backup(self):
        backups = db.backup_get_all_by_project(self.ctxt, 'project1')
        self.assertEqual(len(backups), 0)

        b1 = self._create_backup_db_entry()
        b2 = self._create_backup_db_entry(project_id='project1')
        backups = db.backup_get_all_by_project(self.ctxt, 'project1')
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].id, b2)

    def test_backup_get_all_by_project_with_deleted(self):
        """Test deleted backups don't show up in backup_get_all_by_project.
           Unless context.read_deleted is 'yes'
        """
        backups = db.backup_get_all_by_project(self.ctxt, 'fake')
        self.assertEqual(len(backups), 0)

        backup_id_keep = self._create_backup_db_entry()
        backup_id = self._create_backup_db_entry()
        db.backup_destroy(self.ctxt, backup_id)

        backups = db.backup_get_all_by_project(self.ctxt, 'fake')
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].id, backup_id_keep)

        ctxt_read_deleted = context.get_admin_context('yes')
        backups = db.backup_get_all_by_project(ctxt_read_deleted, 'fake')
        self.assertEqual(len(backups), 2)

    def test_backup_get_all_by_host_with_deleted(self):
        """Test deleted backups don't show up in backup_get_all_by_project.
           Unless context.read_deleted is 'yes'
        """
        backups = db.backup_get_all_by_host(self.ctxt, 'testhost')
        self.assertEqual(len(backups), 0)

        backup_id_keep = self._create_backup_db_entry()
        backup_id = self._create_backup_db_entry()
        db.backup_destroy(self.ctxt, backup_id)

        backups = db.backup_get_all_by_host(self.ctxt, 'testhost')
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].id, backup_id_keep)

        ctxt_read_deleted = context.get_admin_context('yes')
        backups = db.backup_get_all_by_host(ctxt_read_deleted, 'testhost')
        self.assertEqual(len(backups), 2)

    def test_backup_manager_driver_name(self):
        """"Test mapping between backup services and backup drivers."""

        old_setting = CONF.backup_driver
        setattr(cfg.CONF, 'backup_driver', "cinder.backup.services.swift")
        backup_mgr = \
            importutils.import_object(CONF.backup_manager)
        self.assertEqual('cinder.backup.drivers.swift',
                         backup_mgr.driver_name)
        setattr(cfg.CONF, 'backup_driver', old_setting)
