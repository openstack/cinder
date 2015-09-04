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
Tests for Backup swift code.

"""

import bz2
import filecmp
import hashlib
import os
import shutil
import tempfile
import zlib

import mock
from oslo_config import cfg
from oslo_log import log as logging
from swiftclient import client as swift

from cinder.backup.drivers import swift as swift_dr
from cinder import context
from cinder import db
from cinder import exception
from cinder.i18n import _
from cinder import test
from cinder.tests.backup import fake_swift_client
from cinder.tests.backup import fake_swift_client2


LOG = logging.getLogger(__name__)

CONF = cfg.CONF


def fake_md5(arg):
    class result(object):
        def hexdigest(self):
            return 'fake-md5-sum'

    ret = result()
    return ret


class BackupSwiftTestCase(test.TestCase):
    """Test Case for swift."""

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
        super(BackupSwiftTestCase, self).setUp()
        service_catalog = [{u'type': u'object-store', u'name': u'swift',
                            u'endpoints': [{
                                u'publicURL': u'http://example.com'}]}]
        self.ctxt = context.get_admin_context()
        self.ctxt.service_catalog = service_catalog

        self.stubs.Set(swift, 'Connection',
                       fake_swift_client.FakeSwiftClient.Connection)
        self.stubs.Set(hashlib, 'md5', fake_md5)

        self._create_volume_db_entry()
        self.volume_file = tempfile.NamedTemporaryFile()
        self.temp_dir = tempfile.mkdtemp()
        self.addCleanup(self.volume_file.close)
        # Remove tempdir.
        self.addCleanup(shutil.rmtree, self.temp_dir)
        for _i in xrange(0, 64):
            self.volume_file.write(os.urandom(1024))

    def test_backup_swift_url(self):
        self.ctxt.service_catalog = [{u'type': u'object-store',
                                      u'name': u'swift',
                                      u'endpoints': [{
                                          u'adminURL': u'http://example.com'}]
                                      }]
        self.assertRaises(exception.BackupDriverException,
                          swift_dr.SwiftBackupDriver,
                          self.ctxt)

    def test_backup_swift_url_conf(self):
        self.ctxt.service_catalog = [{u'type': u'object-store',
                                      u'name': u'swift',
                                      u'endpoints': [{
                                          u'adminURL': u'http://example.com'}]
                                      }]
        self.ctxt.project_id = "12345678"
        self.override_config("backup_swift_url", "http://public.example.com/")
        backup = swift_dr.SwiftBackupDriver(self.ctxt)
        self.assertEqual("%s%s" % (CONF.backup_swift_url,
                                   self.ctxt.project_id),
                         backup.swift_url)

    def test_backup_swift_info(self):
        self.override_config("swift_catalog_info", "dummy")
        self.assertRaises(exception.BackupDriverException,
                          swift_dr.SwiftBackupDriver,
                          self.ctxt)

    def test_backup_uncompressed(self):
        self._create_backup_db_entry()
        self.flags(backup_compression_algorithm='none')
        service = swift_dr.SwiftBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        backup = db.backup_get(self.ctxt, 123)
        service.backup(backup, self.volume_file)

    def test_backup_bz2(self):
        self._create_backup_db_entry()
        self.flags(backup_compression_algorithm='bz2')
        service = swift_dr.SwiftBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        backup = db.backup_get(self.ctxt, 123)
        service.backup(backup, self.volume_file)

    def test_backup_zlib(self):
        self._create_backup_db_entry()
        self.flags(backup_compression_algorithm='zlib')
        service = swift_dr.SwiftBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        backup = db.backup_get(self.ctxt, 123)
        service.backup(backup, self.volume_file)

    def test_backup_default_container(self):
        self._create_backup_db_entry(container=None)
        service = swift_dr.SwiftBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        backup = db.backup_get(self.ctxt, 123)
        service.backup(backup, self.volume_file)
        backup = db.backup_get(self.ctxt, 123)
        self.assertEqual(backup['container'], 'volumebackups')

    @mock.patch('cinder.backup.drivers.swift.SwiftBackupDriver.'
                '_send_progress_end')
    @mock.patch('cinder.backup.drivers.swift.SwiftBackupDriver.'
                '_send_progress_notification')
    def test_backup_default_container_notify(self, _send_progress,
                                             _send_progress_end):
        self._create_backup_db_entry(container=None)
        # If the backup_object_number_per_notification is set to 1,
        # the _send_progress method will be called for sure.
        CONF.set_override("backup_object_number_per_notification", 1)
        CONF.set_override("backup_swift_enable_progress_timer", False)
        service = swift_dr.SwiftBackupDriver(self.ctxt)
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
        service = swift_dr.SwiftBackupDriver(self.ctxt)
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
        CONF.set_override("backup_swift_enable_progress_timer", True)
        service = swift_dr.SwiftBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        backup = db.backup_get(self.ctxt, 123)
        service.backup(backup, self.volume_file)
        self.assertTrue(_send_progress.called)
        self.assertTrue(_send_progress_end.called)

    def test_backup_custom_container(self):
        container_name = 'fake99'
        self._create_backup_db_entry(container=container_name)
        service = swift_dr.SwiftBackupDriver(self.ctxt)
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
        self.stubs.Set(swift_dr.SwiftBackupDriver,
                       '_generate_object_name_prefix',
                       _fake_generate_object_name_prefix)

        container_name = self.temp_dir.replace(tempfile.gettempdir() + '/',
                                               '', 1)
        self._create_backup_db_entry(container=container_name)
        self.stubs.Set(swift, 'Connection',
                       fake_swift_client2.FakeSwiftClient2.Connection)
        service = swift_dr.SwiftBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        backup = db.backup_get(self.ctxt, 123)
        service.backup(backup, self.volume_file)
        backup = db.backup_get(self.ctxt, 123)
        self.assertEqual(backup['container'], container_name)

        # Verify sha contents
        content1 = service._read_sha256file(backup)
        self.assertEqual(64 * 1024 / content1['chunk_size'],
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
        self.stubs.Set(swift_dr.SwiftBackupDriver,
                       '_generate_object_name_prefix',
                       _fake_generate_object_name_prefix)

        container_name = self.temp_dir.replace(tempfile.gettempdir() + '/',
                                               '', 1)
        self._create_backup_db_entry(container=container_name, backup_id=123)
        self.stubs.Set(swift, 'Connection',
                       fake_swift_client2.FakeSwiftClient2.Connection)
        service = swift_dr.SwiftBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        backup = db.backup_get(self.ctxt, 123)
        service.backup(backup, self.volume_file)
        backup = db.backup_get(self.ctxt, 123)
        self.assertEqual(backup['container'], container_name)

        # Create incremental backup with no change to contents
        self._create_backup_db_entry(container=container_name, backup_id=124,
                                     parent_id=123)
        self.stubs.Set(swift, 'Connection',
                       fake_swift_client2.FakeSwiftClient2.Connection)
        service = swift_dr.SwiftBackupDriver(self.ctxt)
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
        self.stubs.Set(swift_dr.SwiftBackupDriver,
                       '_generate_object_name_prefix',
                       _fake_generate_object_name_prefix)

        self.flags(backup_swift_object_size=8 * 1024)
        self.flags(backup_swift_block_size=1024)

        container_name = self.temp_dir.replace(tempfile.gettempdir() + '/',
                                               '', 1)
        self._create_backup_db_entry(container=container_name, backup_id=123)
        self.stubs.Set(swift, 'Connection',
                       fake_swift_client2.FakeSwiftClient2.Connection)
        service = swift_dr.SwiftBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        backup = db.backup_get(self.ctxt, 123)
        service.backup(backup, self.volume_file)
        backup = db.backup_get(self.ctxt, 123)
        self.assertEqual(backup['container'], container_name)

        # Create incremental backup with no change to contents
        self.volume_file.seek(2 * 8 * 1024)
        self.volume_file.write(os.urandom(1024))
        self.volume_file.seek(4 * 8 * 1024)
        self.volume_file.write(os.urandom(1024))

        self._create_backup_db_entry(container=container_name, backup_id=124,
                                     parent_id=123)
        self.stubs.Set(swift, 'Connection',
                       fake_swift_client2.FakeSwiftClient2.Connection)
        service = swift_dr.SwiftBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        deltabackup = db.backup_get(self.ctxt, 124)
        service.backup(deltabackup, self.volume_file)
        deltabackup = db.backup_get(self.ctxt, 124)
        self.assertEqual(deltabackup['container'], container_name)

        content1 = service._read_sha256file(backup)
        content2 = service._read_sha256file(deltabackup)

        # Verify that two shas are changed at index 16 and 32
        self.assertNotEqual(content1['sha256s'][16], content2['sha256s'][16])
        self.assertNotEqual(content1['sha256s'][32], content2['sha256s'][32])

    def test_backup_delta_two_blocks_in_object_change(self):

        def _fake_generate_object_name_prefix(self, backup):
            az = 'az_fake'
            backup_name = '%s_backup_%s' % (az, backup['id'])
            volume = 'volume_%s' % (backup['volume_id'])
            prefix = volume + '_' + backup_name
            LOG.debug('_generate_object_name_prefix: %s', prefix)
            return prefix

        # Raise a pseudo exception.BackupDriverException.
        self.stubs.Set(swift_dr.SwiftBackupDriver,
                       '_generate_object_name_prefix',
                       _fake_generate_object_name_prefix)

        self.flags(backup_swift_object_size=8 * 1024)
        self.flags(backup_swift_block_size=1024)

        container_name = self.temp_dir.replace(tempfile.gettempdir() + '/',
                                               '', 1)
        self._create_backup_db_entry(container=container_name, backup_id=123)
        self.stubs.Set(swift, 'Connection',
                       fake_swift_client2.FakeSwiftClient2.Connection)
        service = swift_dr.SwiftBackupDriver(self.ctxt)
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
        self.stubs.Set(swift, 'Connection',
                       fake_swift_client2.FakeSwiftClient2.Connection)
        service = swift_dr.SwiftBackupDriver(self.ctxt)
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

    def test_create_backup_put_object_wraps_socket_error(self):
        container_name = 'socket_error_on_put'
        self._create_backup_db_entry(container=container_name)
        service = swift_dr.SwiftBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        backup = db.backup_get(self.ctxt, 123)
        self.assertRaises(exception.SwiftConnectionFailed,
                          service.backup,
                          backup, self.volume_file)

    def test_backup_backup_metadata_fail(self):
        """Test of when an exception occurs in backup().

        In backup(), after an exception occurs in
        self._backup_metadata(), we want to check the process of an
        exception handler.
        """
        self._create_backup_db_entry()
        self.flags(backup_compression_algorithm='none')
        service = swift_dr.SwiftBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        backup = db.backup_get(self.ctxt, 123)

        def fake_backup_metadata(self, backup, object_meta):
            raise exception.BackupDriverException(message=_('fake'))

        # Raise a pseudo exception.BackupDriverException.
        self.stubs.Set(swift_dr.SwiftBackupDriver, '_backup_metadata',
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
        service = swift_dr.SwiftBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        backup = db.backup_get(self.ctxt, 123)

        def fake_backup_metadata(self, backup, object_meta):
            raise exception.BackupDriverException(message=_('fake'))

        # Raise a pseudo exception.BackupDriverException.
        self.stubs.Set(swift_dr.SwiftBackupDriver, '_backup_metadata',
                       fake_backup_metadata)

        def fake_delete(self, backup):
            raise exception.BackupOperationError()

        # Raise a pseudo exception.BackupOperationError.
        self.stubs.Set(swift_dr.SwiftBackupDriver, 'delete', fake_delete)

        # We expect that the second exception is notified.
        self.assertRaises(exception.BackupOperationError,
                          service.backup,
                          backup, self.volume_file)

    def test_restore(self):
        self._create_backup_db_entry()
        service = swift_dr.SwiftBackupDriver(self.ctxt)

        with tempfile.NamedTemporaryFile() as volume_file:
            backup = db.backup_get(self.ctxt, 123)
            service.restore(backup, '1234-5678-1234-8888', volume_file)

    def test_restore_delta(self):

        def _fake_generate_object_name_prefix(self, backup):
            az = 'az_fake'
            backup_name = '%s_backup_%s' % (az, backup['id'])
            volume = 'volume_%s' % (backup['volume_id'])
            prefix = volume + '_' + backup_name
            LOG.debug('_generate_object_name_prefix: %s', prefix)
            return prefix

        # Raise a pseudo exception.BackupDriverException.
        self.stubs.Set(swift_dr.SwiftBackupDriver,
                       '_generate_object_name_prefix',
                       _fake_generate_object_name_prefix)

        self.flags(backup_swift_object_size=8 * 1024)
        self.flags(backup_swift_block_size=1024)

        container_name = self.temp_dir.replace(tempfile.gettempdir() + '/',
                                               '', 1)
        self._create_backup_db_entry(container=container_name, backup_id=123)
        self.stubs.Set(swift, 'Connection',
                       fake_swift_client2.FakeSwiftClient2.Connection)
        service = swift_dr.SwiftBackupDriver(self.ctxt)
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

    def test_restore_wraps_socket_error(self):
        container_name = 'socket_error_on_get'
        self._create_backup_db_entry(container=container_name)
        service = swift_dr.SwiftBackupDriver(self.ctxt)

        with tempfile.NamedTemporaryFile() as volume_file:
            backup = db.backup_get(self.ctxt, 123)
            self.assertRaises(exception.SwiftConnectionFailed,
                              service.restore,
                              backup, '1234-5678-1234-8888', volume_file)

    def test_restore_unsupported_version(self):
        container_name = 'unsupported_version'
        self._create_backup_db_entry(container=container_name)
        service = swift_dr.SwiftBackupDriver(self.ctxt)

        with tempfile.NamedTemporaryFile() as volume_file:
            backup = db.backup_get(self.ctxt, 123)
            self.assertRaises(exception.InvalidBackup,
                              service.restore,
                              backup, '1234-5678-1234-8888', volume_file)

    def test_delete(self):
        self._create_backup_db_entry()
        service = swift_dr.SwiftBackupDriver(self.ctxt)
        backup = db.backup_get(self.ctxt, 123)
        service.delete(backup)

    def test_delete_wraps_socket_error(self):
        container_name = 'socket_error_on_delete'
        self._create_backup_db_entry(container=container_name)
        service = swift_dr.SwiftBackupDriver(self.ctxt)
        backup = db.backup_get(self.ctxt, 123)
        self.assertRaises(exception.SwiftConnectionFailed,
                          service.delete,
                          backup)

    def test_get_compressor(self):
        service = swift_dr.SwiftBackupDriver(self.ctxt)
        compressor = service._get_compressor('None')
        self.assertIsNone(compressor)
        compressor = service._get_compressor('zlib')
        self.assertEqual(compressor, zlib)
        compressor = service._get_compressor('bz2')
        self.assertEqual(compressor, bz2)
        self.assertRaises(ValueError, service._get_compressor, 'fake')
