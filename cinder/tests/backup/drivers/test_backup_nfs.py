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
import __builtin__
import bz2
import exceptions
import filecmp
import hashlib
import os
import shutil
import tempfile
import zlib

import mock
from oslo_config import cfg
from oslo_log import log as logging

from cinder.backup.drivers import nfs
from cinder.brick.remotefs import remotefs as remotefs_brick
from cinder import context
from cinder import db
from cinder import exception
from cinder.i18n import _
from cinder import test
from cinder import utils

LOG = logging.getLogger(__name__)

CONF = cfg.CONF

FAKE_BACKUP_ENABLE_PROGRESS_TIMER = True
FAKE_BACKUP_MOUNT_POINT_BASE = '/fake/mount-point-base'
FAKE_HOST = 'fake_host'
FAKE_EXPORT_PATH = 'fake/export/path'
FAKE_BACKUP_SHARE = '%s:/%s' % (FAKE_HOST, FAKE_EXPORT_PATH)
FAKE_BACKUP_PATH = os.path.join(FAKE_BACKUP_MOUNT_POINT_BASE,
                                FAKE_EXPORT_PATH)
FAKE_BACKUP_MOUNT_OPTIONS = 'fake_opt1=fake_value1,fake_opt2=fake_value2'

FAKE_CONTAINER = 'fake/container'
FAKE_BACKUP_ID_PART1 = 'de'
FAKE_BACKUP_ID_PART2 = 'ad'
FAKE_BACKUP_ID_REST = 'beef-whatever'
FAKE_BACKUP_ID = (FAKE_BACKUP_ID_PART1 + FAKE_BACKUP_ID_PART2 +
                  FAKE_BACKUP_ID_REST)
FAKE_BACKUP = {'id': FAKE_BACKUP_ID, 'container': None}
UPDATED_CONTAINER_NAME = os.path.join(FAKE_BACKUP_ID_PART1,
                                      FAKE_BACKUP_ID_PART2,
                                      FAKE_BACKUP_ID)
FAKE_PREFIX = 'prefix-'
FAKE_CONTAINER_ENTRIES = [FAKE_PREFIX + 'one', FAKE_PREFIX + 'two', 'three']
EXPECTED_CONTAINER_ENTRIES = [FAKE_PREFIX + 'one', FAKE_PREFIX + 'two']
FAKE_OBJECT_NAME = 'fake-object-name'
FAKE_OBJECT_PATH = os.path.join(FAKE_BACKUP_PATH, FAKE_CONTAINER,
                                FAKE_OBJECT_NAME)


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


class BackupNFSTestCase(test.TestCase):
    def setUp(self):
        super(BackupNFSTestCase, self).setUp()
        self.ctxt = context.get_admin_context()
        self.override_config('backup_enable_progress_timer',
                             FAKE_BACKUP_ENABLE_PROGRESS_TIMER)
        self.override_config('backup_mount_point_base',
                             FAKE_BACKUP_MOUNT_POINT_BASE)
        self.override_config('backup_share', FAKE_BACKUP_SHARE)
        self.override_config('backup_mount_options', FAKE_BACKUP_MOUNT_OPTIONS)

        self.mock_object(nfs.NFSBackupDriver, '_check_configuration')
        self.mock_object(nfs.NFSBackupDriver, '_init_backup_repo_path',
                         mock.Mock(return_value=FAKE_BACKUP_PATH))
        self.mock_object(nfs, 'LOG')

        self.driver = nfs.NFSBackupDriver(self.ctxt)

    def test_init(self):
        self.assertEqual(FAKE_BACKUP_ENABLE_PROGRESS_TIMER,
                         self.driver.enable_progress_timer)
        self.assertEqual(FAKE_BACKUP_MOUNT_POINT_BASE,
                         self.driver.backup_mount_point_base)
        self.assertEqual(FAKE_BACKUP_SHARE,
                         self.driver.backup_share)
        self.assertEqual(FAKE_BACKUP_MOUNT_OPTIONS,
                         self.driver.mount_options)
        self.assertTrue(self.driver._check_configuration.called)
        self.assertTrue(self.driver._init_backup_repo_path.called)
        self.assertTrue(nfs.LOG.debug.called)

    def test_update_container_name_container_passed(self):
        result = self.driver.update_container_name(FAKE_BACKUP, FAKE_CONTAINER)

        self.assertEqual(FAKE_CONTAINER, result)

    def test_update_container_na_container_passed(self):
        result = self.driver.update_container_name(FAKE_BACKUP, None)

        self.assertEqual(UPDATED_CONTAINER_NAME, result)

    def test_put_container(self):
        self.mock_object(os.path, 'exists', mock.Mock(return_value=False))
        self.mock_object(os, 'makedirs')
        self.mock_object(os, 'chmod')
        path = os.path.join(self.driver.backup_path, FAKE_CONTAINER)

        self.driver.put_container(FAKE_CONTAINER)

        os.path.exists.assert_called_once_with(path)
        os.makedirs.assert_called_once_with(path)
        os.chmod.assert_called_once_with(path, 0o770)

    def test_put_container_already_exists(self):
        self.mock_object(os.path, 'exists', mock.Mock(return_value=True))
        self.mock_object(os, 'makedirs')
        self.mock_object(os, 'chmod')
        path = os.path.join(self.driver.backup_path, FAKE_CONTAINER)

        self.driver.put_container(FAKE_CONTAINER)

        os.path.exists.assert_called_once_with(path)
        self.assertEqual(0, os.makedirs.call_count)
        self.assertEqual(0, os.chmod.call_count)

    def test_put_container_exception(self):
        self.mock_object(os.path, 'exists', mock.Mock(return_value=False))
        self.mock_object(os, 'makedirs', mock.Mock(
            side_effect=exceptions.OSError))
        self.mock_object(os, 'chmod')
        path = os.path.join(self.driver.backup_path, FAKE_CONTAINER)

        self.assertRaises(exceptions.OSError, self.driver.put_container,
                          FAKE_CONTAINER)
        os.path.exists.assert_called_once_with(path)
        os.makedirs.called_once_with(path)
        self.assertEqual(0, os.chmod.call_count)

    def test_get_container_entries(self):
        self.mock_object(os, 'listdir', mock.Mock(
            return_value=FAKE_CONTAINER_ENTRIES))

        result = self.driver.get_container_entries(FAKE_CONTAINER, FAKE_PREFIX)

        self.assertEqual(EXPECTED_CONTAINER_ENTRIES, result)

    def test_get_container_entries_no_list(self):
        self.mock_object(os, 'listdir', mock.Mock(
            return_value=[]))

        result = self.driver.get_container_entries(FAKE_CONTAINER, FAKE_PREFIX)

        self.assertEqual([], result)

    def test_get_container_entries_no_match(self):
        self.mock_object(os, 'listdir', mock.Mock(
            return_value=FAKE_CONTAINER_ENTRIES))

        result = self.driver.get_container_entries(FAKE_CONTAINER,
                                                   FAKE_PREFIX + 'garbage')

        self.assertEqual([], result)

    def test_get_object_writer(self):
        self.mock_object(__builtin__, 'open', mock.mock_open())
        self.mock_object(os, 'chmod')

        self.driver.get_object_writer(FAKE_CONTAINER, FAKE_OBJECT_NAME)

        os.chmod.assert_called_once_with(FAKE_OBJECT_PATH, 0o660)
        __builtin__.open.assert_called_once_with(FAKE_OBJECT_PATH, 'w')

    def test_get_object_reader(self):
        self.mock_object(__builtin__, 'open', mock.mock_open())

        self.driver.get_object_reader(FAKE_CONTAINER, FAKE_OBJECT_NAME)

        __builtin__.open.assert_called_once_with(FAKE_OBJECT_PATH, 'r')

    def test_delete_object(self):
        self.mock_object(os, 'remove')

        self.driver.delete_object(FAKE_CONTAINER, FAKE_OBJECT_NAME)

    def test_delete_nonexistent_object(self):
        self.mock_object(os, 'remove', mock.Mock(
            side_effect=exceptions.OSError))

        self.assertRaises(exceptions.OSError,
                          self.driver.delete_object, FAKE_CONTAINER,
                          FAKE_OBJECT_NAME)


def fake_md5(arg):
    class result(object):
        def hexdigest(self):
            return 'fake-md5-sum'

    ret = result()
    return ret


class BackupNFSSwiftBasedTestCase(test.TestCase):
    """Test Cases for based on Swift tempest backup tests."""
    def _create_volume_db_entry(self):
        vol = {'id': '1234-5678-1234-8888',
               'size': 1,
               'status': 'available'}
        return db.volume_create(self.ctxt, vol)['id']

    def _create_backup_db_entry(self, container='test-container',
                                backup_id=123, parent_id=None):
        backup = {'id': backup_id,
                  'size': 1,
                  'container': container,
                  'volume_id': '1234-5678-1234-8888',
                  'parent_id': parent_id}
        return db.backup_create(self.ctxt, backup)['id']

    def setUp(self):
        super(BackupNFSSwiftBasedTestCase, self).setUp()

        self.ctxt = context.get_admin_context()
        self.stubs.Set(hashlib, 'md5', fake_md5)
        self._create_volume_db_entry()
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
        for _i in xrange(0, 32):
            self.volume_file.write(os.urandom(1024))

    def test_backup_uncompressed(self):
        self._create_backup_db_entry()
        self.flags(backup_compression_algorithm='none')
        service = nfs.NFSBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        backup = db.backup_get(self.ctxt, 123)
        service.backup(backup, self.volume_file)

    def test_backup_bz2(self):
        self._create_backup_db_entry()
        self.flags(backup_compression_algorithm='bz2')
        service = nfs.NFSBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        backup = db.backup_get(self.ctxt, 123)
        service.backup(backup, self.volume_file)

    def test_backup_zlib(self):
        self._create_backup_db_entry()
        self.flags(backup_compression_algorithm='zlib')
        service = nfs.NFSBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        backup = db.backup_get(self.ctxt, 123)
        service.backup(backup, self.volume_file)

    def test_backup_default_container(self):
        self._create_backup_db_entry(container=None,
                                     backup_id=FAKE_BACKUP_ID)
        service = nfs.NFSBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        backup = db.backup_get(self.ctxt, FAKE_BACKUP_ID)
        service.backup(backup, self.volume_file)
        backup = db.backup_get(self.ctxt, FAKE_BACKUP_ID)
        self.assertEqual(backup['container'], UPDATED_CONTAINER_NAME)

    @mock.patch('cinder.backup.drivers.nfs.NFSBackupDriver.'
                '_send_progress_end')
    @mock.patch('cinder.backup.drivers.nfs.NFSBackupDriver.'
                '_send_progress_notification')
    def test_backup_default_container_notify(self, _send_progress,
                                             _send_progress_end):
        self._create_backup_db_entry(container=None)
        # If the backup_object_number_per_notification is set to 1,
        # the _send_progress method will be called for sure.
        CONF.set_override("backup_object_number_per_notification", 1)
        CONF.set_override("backup_enable_progress_timer", False)
        service = nfs.NFSBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        backup = db.backup_get(self.ctxt, 123)
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
        backup = db.backup_get(self.ctxt, 123)
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
        backup = db.backup_get(self.ctxt, 123)
        service.backup(backup, self.volume_file)
        self.assertTrue(_send_progress.called)
        self.assertTrue(_send_progress_end.called)

    def test_backup_custom_container(self):
        container_name = 'fake99'
        self._create_backup_db_entry(container=container_name)
        service = nfs.NFSBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        backup = db.backup_get(self.ctxt, 123)
        service.backup(backup, self.volume_file)
        backup = db.backup_get(self.ctxt, 123)
        self.assertEqual(backup['container'], container_name)

    def test_backup_shafile(self):

        def _fake_generate_object_name_prefix(self, backup):
            az = 'az_fake'
            backup_name = '%s_backup_%s' % (az, backup['id'])
            volume = 'volume_%s' % (backup['volume_id'])
            prefix = volume + '_' + backup_name
            LOG.debug('_generate_object_name_prefix: %s', prefix)
            return prefix

        # Raise a pseudo exception.BackupDriverException.
        self.stubs.Set(nfs.NFSBackupDriver,
                       '_generate_object_name_prefix',
                       _fake_generate_object_name_prefix)

        container_name = self.temp_dir.replace(tempfile.gettempdir() + '/',
                                               '', 1)
        self._create_backup_db_entry(container=container_name)
        service = nfs.NFSBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        backup = db.backup_get(self.ctxt, 123)
        service.backup(backup, self.volume_file)
        backup = db.backup_get(self.ctxt, 123)
        self.assertEqual(backup['container'], container_name)

        # Verify sha contents
        content1 = service._read_sha256file(backup)
        self.assertEqual(32 * 1024 / content1['chunk_size'],
                         len(content1['sha256s']))

    def test_backup_cmp_shafiles(self):

        def _fake_generate_object_name_prefix(self, backup):
            az = 'az_fake'
            backup_name = '%s_backup_%s' % (az, backup['id'])
            volume = 'volume_%s' % (backup['volume_id'])
            prefix = volume + '_' + backup_name
            LOG.debug('_generate_object_name_prefix: %s', prefix)
            return prefix

        # Raise a pseudo exception.BackupDriverException.
        self.stubs.Set(nfs.NFSBackupDriver,
                       '_generate_object_name_prefix',
                       _fake_generate_object_name_prefix)

        container_name = self.temp_dir.replace(tempfile.gettempdir() + '/',
                                               '', 1)
        self._create_backup_db_entry(container=container_name,
                                     backup_id=123)
        service = nfs.NFSBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        backup = db.backup_get(self.ctxt, 123)
        service.backup(backup, self.volume_file)
        backup = db.backup_get(self.ctxt, 123)
        self.assertEqual(backup['container'], container_name)

        # Create incremental backup with no change to contents
        self._create_backup_db_entry(container=container_name, backup_id=124,
                                     parent_id=123)
        service = nfs.NFSBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        deltabackup = db.backup_get(self.ctxt, 124)
        service.backup(deltabackup, self.volume_file)
        deltabackup = db.backup_get(self.ctxt, 124)
        self.assertEqual(deltabackup['container'], container_name)

        # Compare shas from both files
        content1 = service._read_sha256file(backup)
        content2 = service._read_sha256file(deltabackup)

        self.assertEqual(len(content1['sha256s']), len(content2['sha256s']))
        self.assertEqual(set(content1['sha256s']), set(content2['sha256s']))

    def test_backup_delta_two_objects_change(self):

        def _fake_generate_object_name_prefix(self, backup):
            az = 'az_fake'
            backup_name = '%s_backup_%s' % (az, backup['id'])
            volume = 'volume_%s' % (backup['volume_id'])
            prefix = volume + '_' + backup_name
            LOG.debug('_generate_object_name_prefix: %s', prefix)
            return prefix

        # Raise a pseudo exception.BackupDriverException.
        self.stubs.Set(nfs.NFSBackupDriver,
                       '_generate_object_name_prefix',
                       _fake_generate_object_name_prefix)

        self.flags(backup_file_size=(8 * 1024))
        self.flags(backup_sha_block_size_bytes=1024)

        container_name = self.temp_dir.replace(tempfile.gettempdir() + '/',
                                               '', 1)
        self._create_backup_db_entry(container=container_name, backup_id=123)
        service = nfs.NFSBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        backup = db.backup_get(self.ctxt, 123)
        service.backup(backup, self.volume_file)
        backup = db.backup_get(self.ctxt, 123)
        self.assertEqual(backup['container'], container_name)

        # Create incremental backup with no change to contents
        self.volume_file.seek(16 * 1024)
        self.volume_file.write(os.urandom(1024))
        self.volume_file.seek(20 * 1024)
        self.volume_file.write(os.urandom(1024))

        self._create_backup_db_entry(container=container_name, backup_id=124,
                                     parent_id=123)
        service = nfs.NFSBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        deltabackup = db.backup_get(self.ctxt, 124)
        service.backup(deltabackup, self.volume_file)
        deltabackup = db.backup_get(self.ctxt, 124)
        self.assertEqual(deltabackup['container'], container_name)

        content1 = service._read_sha256file(backup)
        content2 = service._read_sha256file(deltabackup)

        # Verify that two shas are changed at index 16 and 20
        self.assertNotEqual(content1['sha256s'][16], content2['sha256s'][16])
        self.assertNotEqual(content1['sha256s'][20], content2['sha256s'][20])

    def test_backup_delta_two_blocks_in_object_change(self):

        def _fake_generate_object_name_prefix(self, backup):
            az = 'az_fake'
            backup_name = '%s_backup_%s' % (az, backup['id'])
            volume = 'volume_%s' % (backup['volume_id'])
            prefix = volume + '_' + backup_name
            LOG.debug('_generate_object_name_prefix: %s', prefix)
            return prefix

        # Raise a pseudo exception.BackupDriverException.
        self.stubs.Set(nfs.NFSBackupDriver,
                       '_generate_object_name_prefix',
                       _fake_generate_object_name_prefix)

        self.flags(backup_file_size=(8 * 1024))
        self.flags(backup_sha_block_size_bytes=1024)

        container_name = self.temp_dir.replace(tempfile.gettempdir() + '/',
                                               '', 1)
        self._create_backup_db_entry(container=container_name, backup_id=123)
        service = nfs.NFSBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        backup = db.backup_get(self.ctxt, 123)
        service.backup(backup, self.volume_file)
        backup = db.backup_get(self.ctxt, 123)
        self.assertEqual(backup['container'], container_name)

        # Create incremental backup with no change to contents
        self.volume_file.seek(16 * 1024)
        self.volume_file.write(os.urandom(1024))
        self.volume_file.seek(20 * 1024)
        self.volume_file.write(os.urandom(1024))

        self._create_backup_db_entry(container=container_name, backup_id=124,
                                     parent_id=123)
        service = nfs.NFSBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        deltabackup = db.backup_get(self.ctxt, 124)
        service.backup(deltabackup, self.volume_file)
        deltabackup = db.backup_get(self.ctxt, 124)
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
        self._create_backup_db_entry()
        self.flags(backup_compression_algorithm='none')
        service = nfs.NFSBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        backup = db.backup_get(self.ctxt, 123)

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
        self._create_backup_db_entry()
        self.flags(backup_compression_algorithm='none')
        service = nfs.NFSBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        backup = db.backup_get(self.ctxt, 123)

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
        self._create_backup_db_entry()
        self.flags(backup_compression_algorithm='none')
        self.flags(backup_file_size=(1024 * 1024 * 1024))
        self.flags(backup_sha_block_size_bytes=32)
        service = nfs.NFSBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        backup = db.backup_get(self.ctxt, 123)
        service.backup(backup, self.volume_file)

        with tempfile.NamedTemporaryFile() as restored_file:
            backup = db.backup_get(self.ctxt, 123)
            service.restore(backup, '1234-5678-1234-8888', restored_file)
            self.assertTrue(filecmp.cmp(self.volume_file.name,
                            restored_file.name))

    def test_restore_bz2(self):
        self._create_backup_db_entry()
        self.flags(backup_compression_algorithm='bz2')
        self.flags(backup_file_size=(1024 * 3))
        self.flags(backup_sha_block_size_bytes=1024)
        service = nfs.NFSBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        backup = db.backup_get(self.ctxt, 123)
        service.backup(backup, self.volume_file)

        with tempfile.NamedTemporaryFile() as restored_file:
            backup = db.backup_get(self.ctxt, 123)
            service.restore(backup, '1234-5678-1234-8888', restored_file)
            self.assertTrue(filecmp.cmp(self.volume_file.name,
                            restored_file.name))

    def test_restore_zlib(self):
        self._create_backup_db_entry()
        self.flags(backup_compression_algorithm='zlib')
        self.flags(backup_file_size=(1024 * 3))
        self.flags(backup_sha_block_size_bytes = 1024)
        service = nfs.NFSBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        backup = db.backup_get(self.ctxt, 123)
        service.backup(backup, self.volume_file)

        with tempfile.NamedTemporaryFile() as restored_file:
            backup = db.backup_get(self.ctxt, 123)
            service.restore(backup, '1234-5678-1234-8888', restored_file)
            self.assertTrue(filecmp.cmp(self.volume_file.name,
                            restored_file.name))

    def test_restore_delta(self):

        def _fake_generate_object_name_prefix(self, backup):
            az = 'az_fake'
            backup_name = '%s_backup_%s' % (az, backup['id'])
            volume = 'volume_%s' % (backup['volume_id'])
            prefix = volume + '_' + backup_name
            LOG.debug('_generate_object_name_prefix: %s', prefix)
            return prefix

        # Raise a pseudo exception.BackupDriverException.
        self.stubs.Set(nfs.NFSBackupDriver,
                       '_generate_object_name_prefix',
                       _fake_generate_object_name_prefix)

        self.flags(backup_file_size =(1024 * 8))
        self.flags(backup_sha_block_size_bytes=1024)

        container_name = self.temp_dir.replace(tempfile.gettempdir() + '/',
                                               '', 1)
        self._create_backup_db_entry(container=container_name, backup_id=123)
        service = nfs.NFSBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        backup = db.backup_get(self.ctxt, 123)
        service.backup(backup, self.volume_file)

        # Create incremental backup with no change to contents
        self.volume_file.seek(16 * 1024)
        self.volume_file.write(os.urandom(1024))
        self.volume_file.seek(20 * 1024)
        self.volume_file.write(os.urandom(1024))

        self._create_backup_db_entry(container=container_name, backup_id=124,
                                     parent_id=123)
        self.volume_file.seek(0)
        deltabackup = db.backup_get(self.ctxt, 124)
        service.backup(deltabackup, self.volume_file, True)
        deltabackup = db.backup_get(self.ctxt, 124)

        with tempfile.NamedTemporaryFile() as restored_file:
            backup = db.backup_get(self.ctxt, 124)
            service.restore(backup, '1234-5678-1234-8888',
                            restored_file)
            self.assertTrue(filecmp.cmp(self.volume_file.name,
                            restored_file.name))

    def test_delete(self):
        self._create_backup_db_entry()
        service = nfs.NFSBackupDriver(self.ctxt)
        backup = db.backup_get(self.ctxt, 123)
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
