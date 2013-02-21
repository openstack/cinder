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

from cinder import context
from cinder import db
from cinder import exception
from cinder import flags
from cinder.openstack.common import importutils
from cinder.openstack.common import log as logging
from cinder import test

FLAGS = flags.FLAGS
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
            importutils.import_object(FLAGS.backup_manager)
        self.backup_mgr.host = 'testhost'
        self.ctxt = context.get_admin_context()

    def tearDown(self):
        super(BackupTestCase, self).tearDown()

    def _create_backup_db_entry(self, volume_id=1, display_name='test_backup',
                                display_description='this is a test backup',
                                container='volumebackups',
                                status='creating',
                                size=0,
                                object_count=0):
        """
        Create a backup entry in the DB.
        Return the entry ID
        """
        backup = {}
        backup['volume_id'] = volume_id
        backup['user_id'] = 'fake'
        backup['project_id'] = 'fake'
        backup['host'] = 'testhost'
        backup['availability_zone'] = '1'
        backup['display_name'] = display_name
        backup['display_description'] = display_description
        backup['container'] = container
        backup['status'] = status
        backup['fail_reason'] = ''
        backup['service'] = FLAGS.backup_service
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
        states when backup_manager.init_host() is called"""
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
        with a bad status"""
        vol_id = self._create_volume_db_entry(status='available', size=1)
        backup_id = self._create_backup_db_entry(volume_id=vol_id)
        self.assertRaises(exception.InvalidVolume,
                          self.backup_mgr.create_backup,
                          self.ctxt,
                          backup_id)

    def test_create_backup_with_bad_backup_status(self):
        """Test error handling when creating a backup with a backup
        with a bad status"""
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
        with a bad status"""
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
        with a bad status"""
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
        with a different service to that used to create the backup"""
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
        with a bad status"""
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
        with a different service to that used to create the backup"""
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
        self.assertEquals(backup['status'], 'available')

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
