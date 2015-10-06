# Copyright (C) 2015 Tom Barron <tpb@dyncloud.net>
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
Tests for Backup NFS driver.

"""
import bz2
import filecmp
import hashlib
import os
import shutil
import tempfile
import zlib

import mock
from os_brick.remotefs import remotefs as remotefs_brick
from oslo_config import cfg

from cinder.backup.drivers import nfs
from cinder import context
from cinder import db
from cinder import exception
from cinder.i18n import _
from cinder import objects
from cinder import test
from cinder import utils

CONF = cfg.CONF

FAKE_BACKUP_MOUNT_POINT_BASE = '/fake/mount-point-base'
FAKE_HOST = 'fake_host'
FAKE_EXPORT_PATH = 'fake/export/path'
FAKE_BACKUP_SHARE = '%s:/%s' % (FAKE_HOST, FAKE_EXPORT_PATH)
FAKE_BACKUP_PATH = os.path.join(FAKE_BACKUP_MOUNT_POINT_BASE,
                                FAKE_EXPORT_PATH)

FAKE_BACKUP_ID_PART1 = 'de'
FAKE_BACKUP_ID_PART2 = 'ad'
FAKE_BACKUP_ID_REST = 'beef-whatever'
FAKE_BACKUP_ID = (FAKE_BACKUP_ID_PART1 + FAKE_BACKUP_ID_PART2 +
                  FAKE_BACKUP_ID_REST)
UPDATED_CONTAINER_NAME = os.path.join(FAKE_BACKUP_ID_PART1,
                                      FAKE_BACKUP_ID_PART2,
                                      FAKE_BACKUP_ID)


class BackupNFSShareTestCase(test.TestCase):

    def setUp(self):
        super(BackupNFSShareTestCase, self).setUp()
        self.ctxt = context.get_admin_context()
        self.mock_object(nfs, 'LOG')

    def test_check_configuration_no_backup_share(self):
        self.override_config('backup_share', None)
        self.mock_object(nfs.NFSBackupDriver, '_init_backup_repo_path',
                         mock.Mock(return_value=FAKE_BACKUP_PATH))

        with mock.patch.object(nfs.NFSBackupDriver, '_check_configuration'):
            driver = nfs.NFSBackupDriver(self.ctxt)
        self.assertRaises(exception.ConfigNotFound,
                          driver._check_configuration)

    def test_init_backup_repo_path(self):
        self.override_config('backup_share', FAKE_BACKUP_SHARE)
        self.override_config('backup_mount_point_base',
                             FAKE_BACKUP_MOUNT_POINT_BASE)
        mock_remotefsclient = mock.Mock()
        mock_remotefsclient.get_mount_point = mock.Mock(
            return_value=FAKE_BACKUP_PATH)
        self.mock_object(nfs.NFSBackupDriver, '_check_configuration')
        self.mock_object(remotefs_brick, 'RemoteFsClient',
                         mock.Mock(return_value=mock_remotefsclient))
        self.mock_object(utils, 'get_root_helper')
        with mock.patch.object(nfs.NFSBackupDriver, '_init_backup_repo_path'):
            driver = nfs.NFSBackupDriver(self.ctxt)

        path = driver._init_backup_repo_path()

        self.assertEqual(FAKE_BACKUP_PATH, path)
        utils.get_root_helper.called_once()
        mock_remotefsclient.mount.assert_called_once_with(FAKE_BACKUP_SHARE)
        mock_remotefsclient.get_mount_point.assert_called_once_with(
            FAKE_BACKUP_SHARE)


def fake_md5(arg):
    class result(object):
        def hexdigest(self):
            return 'fake-md5-sum'

    ret = result()
    return ret


class BackupNFSSwiftBasedTestCase(test.TestCase):
    """Test Cases for based on Swift tempest backup tests."""

    _DEFAULT_VOLUME_ID = '8d31c3aa-c5fa-467d-8819-8888887225b6'

    def _create_volume_db_entry(self, volume_id=_DEFAULT_VOLUME_ID):
        vol = {'id': volume_id,
               'size': 1,
               'status': 'available'}
        return db.volume_create(self.ctxt, vol)['id']

    def _create_backup_db_entry(self,
                                volume_id=_DEFAULT_VOLUME_ID,
                                container='test-container',
                                backup_id=123,
                                parent_id=None):

        try:
            db.volume_get(self.ctxt, volume_id)
        except exception.NotFound:
            self._create_volume_db_entry(volume_id=volume_id)

        backup = {'id': backup_id,
                  'size': 1,
                  'container': container,
                  'volume_id': volume_id,
                  'parent_id': parent_id,
                  'user_id': 'user-id',
                  'project_id': 'project-id',
                  }
        return db.backup_create(self.ctxt, backup)['id']

    def setUp(self):
        super(BackupNFSSwiftBasedTestCase, self).setUp()

        self.ctxt = context.get_admin_context()
        self.stubs.Set(hashlib, 'md5', fake_md5)
        self.volume_file = tempfile.NamedTemporaryFile()
        self.temp_dir = tempfile.mkdtemp()
        self.addCleanup(self.volume_file.close)
        self.override_config('backup_share', FAKE_BACKUP_SHARE)
        self.override_config('backup_mount_point_base',
                             '/tmp')
        self.override_config('backup_file_size', 52428800)
        mock_remotefsclient = mock.Mock()
        mock_remotefsclient.get_mount_point = mock.Mock(
            return_value=self.temp_dir)
        self.mock_object(remotefs_brick, 'RemoteFsClient',
                         mock.Mock(return_value=mock_remotefsclient))
        # Remove tempdir.
        self.addCleanup(shutil.rmtree, self.temp_dir)
        for _i in range(0, 32):
            self.volume_file.write(os.urandom(1024))

    def test_backup_uncompressed(self):
        volume_id = '0adffe69-ce32-4bb0-b5e6-0000002d748d'
        self._create_backup_db_entry(volume_id=volume_id)
        self.flags(backup_compression_algorithm='none')
        service = nfs.NFSBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        backup = objects.Backup.get_by_id(self.ctxt, 123)
        service.backup(backup, self.volume_file)

    def test_backup_bz2(self):
        volume_id = '057a035f-2584-4cfd-bf23-000000e39288'
        self._create_backup_db_entry(volume_id=volume_id)
        self.flags(backup_compression_algorithm='bz2')
        service = nfs.NFSBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        backup = objects.Backup.get_by_id(self.ctxt, 123)
        service.backup(backup, self.volume_file)

    def test_backup_zlib(self):
        volume_id = '3701a9f8-effd-44b9-bf2e-000000bb99ca'
        self._create_backup_db_entry(volume_id=volume_id)
        self.flags(backup_compression_algorithm='zlib')
        service = nfs.NFSBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        backup = objects.Backup.get_by_id(self.ctxt, 123)
        service.backup(backup, self.volume_file)

    def test_backup_default_container(self):
        volume_id = 'caffdc68-ef65-48af-928d-000000289076'
        self._create_backup_db_entry(volume_id=volume_id,
                                     container=None,
                                     backup_id=FAKE_BACKUP_ID)
        service = nfs.NFSBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        backup = objects.Backup.get_by_id(self.ctxt, FAKE_BACKUP_ID)
        service.backup(backup, self.volume_file)
        backup = objects.Backup.get_by_id(self.ctxt, FAKE_BACKUP_ID)
        self.assertEqual(backup['container'], UPDATED_CONTAINER_NAME)

    @mock.patch('cinder.backup.drivers.nfs.NFSBackupDriver.'
                '_send_progress_end')
    @mock.patch('cinder.backup.drivers.nfs.NFSBackupDriver.'
                '_send_progress_notification')
    def test_backup_default_container_notify(self, _send_progress,
                                             _send_progress_end):
        volume_id = '170a1081-9fe2-4add-9094-000000b48877'
        self._create_backup_db_entry(volume_id=volume_id,
                                     container=None)
        # If the backup_object_number_per_notification is set to 1,
        # the _send_progress method will be called for sure.
        CONF.set_override("backup_object_number_per_notification", 1)
        CONF.set_override("backup_enable_progress_timer", False)
        service = nfs.NFSBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        backup = objects.Backup.get_by_id(self.ctxt, 123)
        service.backup(backup, self.volume_file)
        self.assertTrue(_send_progress.called)
        self.assertTrue(_send_progress_end.called)

        # If the backup_object_number_per_notification is increased to
        # another value, the _send_progress method will not be called.
        _send_progress.reset_mock()
        _send_progress_end.reset_mock()
        CONF.set_override("backup_object_number_per_notification", 10)
        service = nfs.NFSBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        backup = objects.Backup.get_by_id(self.ctxt, 123)
        service.backup(backup, self.volume_file)
        self.assertFalse(_send_progress.called)
        self.assertTrue(_send_progress_end.called)

        # If the timer is enabled, the _send_progress will be called,
        # since the timer can trigger the progress notification.
        _send_progress.reset_mock()
        _send_progress_end.reset_mock()
        CONF.set_override("backup_object_number_per_notification", 10)
        CONF.set_override("backup_enable_progress_timer", True)
        service = nfs.NFSBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        backup = objects.Backup.get_by_id(self.ctxt, 123)
        service.backup(backup, self.volume_file)
        self.assertTrue(_send_progress.called)
        self.assertTrue(_send_progress_end.called)

    def test_backup_custom_container(self):
        volume_id = '449b8140-85b6-465e-bdf6-0000002b29c4'
        container_name = 'fake99'
        self._create_backup_db_entry(volume_id=volume_id,
                                     container=container_name)
        service = nfs.NFSBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        backup = objects.Backup.get_by_id(self.ctxt, 123)
        service.backup(backup, self.volume_file)
        backup = objects.Backup.get_by_id(self.ctxt, 123)
        self.assertEqual(backup['container'], container_name)

    def test_backup_shafile(self):
        volume_id = '1eb6325f-6666-43a2-bcdd-0000001d8dac'

        def _fake_generate_object_name_prefix(self, backup):
            az = 'az_fake'
            backup_name = '%s_backup_%s' % (az, backup['id'])
            volume = 'volume_%s' % (backup['volume_id'])
            prefix = volume + '_' + backup_name
            return prefix

        # Raise a pseudo exception.BackupDriverException.
        self.stubs.Set(nfs.NFSBackupDriver,
                       '_generate_object_name_prefix',
                       _fake_generate_object_name_prefix)

        container_name = self.temp_dir.replace(tempfile.gettempdir() + '/',
                                               '', 1)
        self._create_backup_db_entry(volume_id=volume_id,
                                     container=container_name)
        service = nfs.NFSBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        backup = objects.Backup.get_by_id(self.ctxt, 123)
        service.backup(backup, self.volume_file)
        backup = objects.Backup.get_by_id(self.ctxt, 123)
        self.assertEqual(backup['container'], container_name)

        # Verify sha contents
        content1 = service._read_sha256file(backup)
        self.assertEqual(32 * 1024 / content1['chunk_size'],
                         len(content1['sha256s']))

    def test_backup_cmp_shafiles(self):
        volume_id = '261e8c1a-0c07-41d7-923f-000000d3efb8'

        def _fake_generate_object_name_prefix(self, backup):
            az = 'az_fake'
            backup_name = '%s_backup_%s' % (az, backup['id'])
            volume = 'volume_%s' % (backup['volume_id'])
            prefix = volume + '_' + backup_name
            return prefix

        # Raise a pseudo exception.BackupDriverException.
        self.stubs.Set(nfs.NFSBackupDriver,
                       '_generate_object_name_prefix',
                       _fake_generate_object_name_prefix)

        container_name = self.temp_dir.replace(tempfile.gettempdir() + '/',
                                               '', 1)
        self._create_backup_db_entry(volume_id=volume_id,
                                     container=container_name,
                                     backup_id=123)
        service = nfs.NFSBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        backup = objects.Backup.get_by_id(self.ctxt, 123)
        service.backup(backup, self.volume_file)
        backup = objects.Backup.get_by_id(self.ctxt, 123)
        self.assertEqual(backup['container'], container_name)

        # Create incremental backup with no change to contents
        self._create_backup_db_entry(volume_id=volume_id,
                                     container=container_name,
                                     backup_id=124,
                                     parent_id=123)
        service = nfs.NFSBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        deltabackup = objects.Backup.get_by_id(self.ctxt, 124)
        service.backup(deltabackup, self.volume_file)
        deltabackup = objects.Backup.get_by_id(self.ctxt, 124)
        self.assertEqual(deltabackup['container'], container_name)

        # Compare shas from both files
        content1 = service._read_sha256file(backup)
        content2 = service._read_sha256file(deltabackup)

        self.assertEqual(len(content1['sha256s']), len(content2['sha256s']))
        self.assertEqual(set(content1['sha256s']), set(content2['sha256s']))

    def test_backup_delta_two_objects_change(self):
        volume_id = '3f400215-e346-406c-83b0-0000009ac4fa'

        def _fake_generate_object_name_prefix(self, backup):
            az = 'az_fake'
            backup_name = '%s_backup_%s' % (az, backup['id'])
            volume = 'volume_%s' % (backup['volume_id'])
            prefix = volume + '_' + backup_name
            return prefix

        # Raise a pseudo exception.BackupDriverException.
        self.stubs.Set(nfs.NFSBackupDriver,
                       '_generate_object_name_prefix',
                       _fake_generate_object_name_prefix)

        self.flags(backup_file_size=(8 * 1024))
        self.flags(backup_sha_block_size_bytes=1024)

        container_name = self.temp_dir.replace(tempfile.gettempdir() + '/',
                                               '', 1)
        self._create_backup_db_entry(volume_id=volume_id,
                                     container=container_name,
                                     backup_id=123)
        service = nfs.NFSBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        backup = objects.Backup.get_by_id(self.ctxt, 123)
        service.backup(backup, self.volume_file)
        backup = objects.Backup.get_by_id(self.ctxt, 123)
        self.assertEqual(backup['container'], container_name)

        # Create incremental backup with no change to contents
        self.volume_file.seek(16 * 1024)
        self.volume_file.write(os.urandom(1024))
        self.volume_file.seek(20 * 1024)
        self.volume_file.write(os.urandom(1024))

        self._create_backup_db_entry(volume_id=volume_id,
                                     container=container_name,
                                     backup_id=124,
                                     parent_id=123)
        service = nfs.NFSBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        deltabackup = objects.Backup.get_by_id(self.ctxt, 124)
        service.backup(deltabackup, self.volume_file)
        deltabackup = objects.Backup.get_by_id(self.ctxt, 124)
        self.assertEqual(deltabackup['container'], container_name)

        content1 = service._read_sha256file(backup)
        content2 = service._read_sha256file(deltabackup)

        # Verify that two shas are changed at index 16 and 20
        self.assertNotEqual(content1['sha256s'][16], content2['sha256s'][16])
        self.assertNotEqual(content1['sha256s'][20], content2['sha256s'][20])

    def test_backup_delta_two_blocks_in_object_change(self):
        volume_id = '5f3f810a-2ff3-4905-aaa3-0000005814ab'

        def _fake_generate_object_name_prefix(self, backup):
            az = 'az_fake'
            backup_name = '%s_backup_%s' % (az, backup['id'])
            volume = 'volume_%s' % (backup['volume_id'])
            prefix = volume + '_' + backup_name
            return prefix

        # Raise a pseudo exception.BackupDriverException.
        self.stubs.Set(nfs.NFSBackupDriver,
                       '_generate_object_name_prefix',
                       _fake_generate_object_name_prefix)

        self.flags(backup_file_size=(8 * 1024))
        self.flags(backup_sha_block_size_bytes=1024)

        container_name = self.temp_dir.replace(tempfile.gettempdir() + '/',
                                               '', 1)
        self._create_backup_db_entry(volume_id=volume_id,
                                     container=container_name,
                                     backup_id=123)
        service = nfs.NFSBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        backup = objects.Backup.get_by_id(self.ctxt, 123)
        service.backup(backup, self.volume_file)
        backup = objects.Backup.get_by_id(self.ctxt, 123)
        self.assertEqual(backup['container'], container_name)

        # Create incremental backup with no change to contents
        self.volume_file.seek(16 * 1024)
        self.volume_file.write(os.urandom(1024))
        self.volume_file.seek(20 * 1024)
        self.volume_file.write(os.urandom(1024))

        self._create_backup_db_entry(volume_id=volume_id,
                                     container=container_name,
                                     backup_id=124,
                                     parent_id=123)
        service = nfs.NFSBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        deltabackup = objects.Backup.get_by_id(self.ctxt, 124)
        service.backup(deltabackup, self.volume_file)
        deltabackup = objects.Backup.get_by_id(self.ctxt, 124)
        self.assertEqual(deltabackup['container'], container_name)

        # Verify that two shas are changed at index 16 and 20
        content1 = service._read_sha256file(backup)
        content2 = service._read_sha256file(deltabackup)
        self.assertNotEqual(content1['sha256s'][16], content2['sha256s'][16])
        self.assertNotEqual(content1['sha256s'][20], content2['sha256s'][20])

    def test_backup_backup_metadata_fail(self):
        """Test of when an exception occurs in backup().

        In backup(), after an exception occurs in
        self._backup_metadata(), we want to check the process of an
        exception handler.
        """
        volume_id = '26481bc2-fc85-40ae-8a4a-0000000b24e5'

        self._create_backup_db_entry(volume_id=volume_id)
        self.flags(backup_compression_algorithm='none')
        service = nfs.NFSBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        backup = objects.Backup.get_by_id(self.ctxt, 123)

        def fake_backup_metadata(self, backup, object_meta):
            raise exception.BackupDriverException(message=_('fake'))

        # Raise a pseudo exception.BackupDriverException.
        self.stubs.Set(nfs.NFSBackupDriver, '_backup_metadata',
                       fake_backup_metadata)

        # We expect that an exception be notified directly.
        self.assertRaises(exception.BackupDriverException,
                          service.backup,
                          backup, self.volume_file)

    def test_backup_backup_metadata_fail2(self):
        """Test of when an exception occurs in an exception handler.

        In backup(), after an exception occurs in
        self._backup_metadata(), we want to check the process when the
        second exception occurs in self.delete().
        """
        volume_id = 'ce18dbc6-65d6-49ca-8866-000000b1c05b'

        self._create_backup_db_entry(volume_id=volume_id)
        self.flags(backup_compression_algorithm='none')
        service = nfs.NFSBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        backup = objects.Backup.get_by_id(self.ctxt, 123)

        def fake_backup_metadata(self, backup, object_meta):
            raise exception.BackupDriverException(message=_('fake'))

        # Raise a pseudo exception.BackupDriverException.
        self.stubs.Set(nfs.NFSBackupDriver, '_backup_metadata',
                       fake_backup_metadata)

        def fake_delete(self, backup):
            raise exception.BackupOperationError()

        # Raise a pseudo exception.BackupOperationError.
        self.stubs.Set(nfs.NFSBackupDriver, 'delete', fake_delete)

        # We expect that the second exception is notified.
        self.assertRaises(exception.BackupOperationError,
                          service.backup,
                          backup, self.volume_file)

    def test_restore_uncompressed(self):
        volume_id = 'b6f39bd5-ad93-474b-8ee4-000000a0d11e'

        self._create_backup_db_entry(volume_id=volume_id)
        self.flags(backup_compression_algorithm='none')
        self.flags(backup_sha_block_size_bytes=32)
        service = nfs.NFSBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        backup = objects.Backup.get_by_id(self.ctxt, 123)

        service.backup(backup, self.volume_file)

        with tempfile.NamedTemporaryFile() as restored_file:
            backup = objects.Backup.get_by_id(self.ctxt, 123)
            service.restore(backup, volume_id, restored_file)
            self.assertTrue(filecmp.cmp(self.volume_file.name,
                            restored_file.name))

    def test_restore_bz2(self):
        volume_id = '3d4f044e-dc78-49e1-891e-000000549431'

        self._create_backup_db_entry(volume_id=volume_id)
        self.flags(backup_compression_algorithm='bz2')
        self.flags(backup_file_size=(1024 * 3))
        self.flags(backup_sha_block_size_bytes=1024)
        service = nfs.NFSBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        backup = objects.Backup.get_by_id(self.ctxt, 123)
        service.backup(backup, self.volume_file)

        with tempfile.NamedTemporaryFile() as restored_file:
            backup = objects.Backup.get_by_id(self.ctxt, 123)
            service.restore(backup, volume_id, restored_file)
            self.assertTrue(filecmp.cmp(self.volume_file.name,
                            restored_file.name))

    def test_restore_zlib(self):
        volume_id = 'ab84fe59-19a8-4c7d-9103-00000061488b'

        self._create_backup_db_entry(volume_id=volume_id)
        self.flags(backup_compression_algorithm='zlib')
        self.flags(backup_file_size=(1024 * 3))
        self.flags(backup_sha_block_size_bytes = 1024)
        service = nfs.NFSBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        backup = objects.Backup.get_by_id(self.ctxt, 123)
        service.backup(backup, self.volume_file)

        with tempfile.NamedTemporaryFile() as restored_file:
            backup = objects.Backup.get_by_id(self.ctxt, 123)
            service.restore(backup, volume_id, restored_file)
            self.assertTrue(filecmp.cmp(self.volume_file.name,
                            restored_file.name))

    def test_restore_delta(self):
        volume_id = '486249dc-83c6-4a02-8d65-000000d819e7'

        def _fake_generate_object_name_prefix(self, backup):
            az = 'az_fake'
            backup_name = '%s_backup_%s' % (az, backup['id'])
            volume = 'volume_%s' % (backup['volume_id'])
            prefix = volume + '_' + backup_name
            return prefix

        # Raise a pseudo exception.BackupDriverException.
        self.stubs.Set(nfs.NFSBackupDriver,
                       '_generate_object_name_prefix',
                       _fake_generate_object_name_prefix)

        self.flags(backup_file_size =(1024 * 8))
        self.flags(backup_sha_block_size_bytes=1024)

        container_name = self.temp_dir.replace(tempfile.gettempdir() + '/',
                                               '', 1)
        self._create_backup_db_entry(volume_id=volume_id,
                                     container=container_name,
                                     backup_id=123)
        service = nfs.NFSBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        backup = objects.Backup.get_by_id(self.ctxt, 123)
        service.backup(backup, self.volume_file)

        # Create incremental backup with no change to contents
        self.volume_file.seek(16 * 1024)
        self.volume_file.write(os.urandom(1024))
        self.volume_file.seek(20 * 1024)
        self.volume_file.write(os.urandom(1024))

        self._create_backup_db_entry(volume_id=volume_id,
                                     container=container_name,
                                     backup_id=124,
                                     parent_id=123)
        self.volume_file.seek(0)
        deltabackup = objects.Backup.get_by_id(self.ctxt, 124)
        service.backup(deltabackup, self.volume_file, True)
        deltabackup = objects.Backup.get_by_id(self.ctxt, 124)

        with tempfile.NamedTemporaryFile() as restored_file:
            backup = objects.Backup.get_by_id(self.ctxt, 124)
            service.restore(backup, volume_id,
                            restored_file)
            self.assertTrue(filecmp.cmp(self.volume_file.name,
                            restored_file.name))

    def test_delete(self):
        volume_id = '4b5c39f2-4428-473c-b85a-000000477eca'
        self._create_backup_db_entry(volume_id=volume_id)
        service = nfs.NFSBackupDriver(self.ctxt)
        backup = objects.Backup.get_by_id(self.ctxt, 123)
        service.delete(backup)

    def test_get_compressor(self):
        service = nfs.NFSBackupDriver(self.ctxt)
        compressor = service._get_compressor('None')
        self.assertIsNone(compressor)
        compressor = service._get_compressor('zlib')
        self.assertEqual(compressor, zlib)
        compressor = service._get_compressor('bz2')
        self.assertEqual(compressor, bz2)
        self.assertRaises(ValueError, service._get_compressor, 'fake')

    def test_prepare_output_data_effective_compression(self):
        service = nfs.NFSBackupDriver(self.ctxt)
        # Set up buffer of 128 zeroed bytes
        fake_data = buffer(bytearray(128))

        result = service._prepare_output_data(fake_data)

        self.assertEqual('zlib', result[0])
        self.assertTrue(len(result) < len(fake_data))

    def test_prepare_output_data_no_compresssion(self):
        self.flags(backup_compression_algorithm='none')
        service = nfs.NFSBackupDriver(self.ctxt)
        # Set up buffer of 128 zeroed bytes
        fake_data = buffer(bytearray(128))

        result = service._prepare_output_data(fake_data)

        self.assertEqual('none', result[0])
        self.assertEqual(fake_data, result[1])

    def test_prepare_output_data_ineffective_compression(self):
        service = nfs.NFSBackupDriver(self.ctxt)
        # Set up buffer of 128 zeroed bytes
        fake_data = buffer(bytearray(128))
        # Pre-compress so that compression in the driver will be ineffective.
        already_compressed_data = service.compressor.compress(fake_data)

        result = service._prepare_output_data(already_compressed_data)

        self.assertEqual('none', result[0])
        self.assertEqual(already_compressed_data, result[1])
