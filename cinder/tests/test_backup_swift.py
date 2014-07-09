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
import hashlib
import os
import tempfile
import zlib

from swiftclient import client as swift

from cinder.backup.drivers.swift import SwiftBackupDriver
from cinder import context
from cinder import db
from cinder import exception
from cinder.openstack.common import log as logging
from cinder import test
from cinder.tests.backup.fake_swift_client import FakeSwiftClient


LOG = logging.getLogger(__name__)


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

    def _create_backup_db_entry(self, container='test-container'):
        backup = {'id': 123,
                  'size': 1,
                  'container': container,
                  'volume_id': '1234-5678-1234-8888'}
        return db.backup_create(self.ctxt, backup)['id']

    def setUp(self):
        super(BackupSwiftTestCase, self).setUp()
        self.ctxt = context.get_admin_context()

        self.stubs.Set(swift, 'Connection', FakeSwiftClient.Connection)
        self.stubs.Set(hashlib, 'md5', fake_md5)

        self._create_volume_db_entry()
        self.volume_file = tempfile.NamedTemporaryFile()
        self.addCleanup(self.volume_file.close)
        for i in xrange(0, 128):
            self.volume_file.write(os.urandom(1024))

    def test_backup_uncompressed(self):
        self._create_backup_db_entry()
        self.flags(backup_compression_algorithm='none')
        service = SwiftBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        backup = db.backup_get(self.ctxt, 123)
        service.backup(backup, self.volume_file)

    def test_backup_bz2(self):
        self._create_backup_db_entry()
        self.flags(backup_compression_algorithm='bz2')
        service = SwiftBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        backup = db.backup_get(self.ctxt, 123)
        service.backup(backup, self.volume_file)

    def test_backup_zlib(self):
        self._create_backup_db_entry()
        self.flags(backup_compression_algorithm='zlib')
        service = SwiftBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        backup = db.backup_get(self.ctxt, 123)
        service.backup(backup, self.volume_file)

    def test_backup_default_container(self):
        self._create_backup_db_entry(container=None)
        service = SwiftBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        backup = db.backup_get(self.ctxt, 123)
        service.backup(backup, self.volume_file)
        backup = db.backup_get(self.ctxt, 123)
        self.assertEqual(backup['container'], 'volumebackups')

    def test_backup_custom_container(self):
        container_name = 'fake99'
        self._create_backup_db_entry(container=container_name)
        service = SwiftBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        backup = db.backup_get(self.ctxt, 123)
        service.backup(backup, self.volume_file)
        backup = db.backup_get(self.ctxt, 123)
        self.assertEqual(backup['container'], container_name)

    def test_create_backup_put_object_wraps_socket_error(self):
        container_name = 'socket_error_on_put'
        self._create_backup_db_entry(container=container_name)
        service = SwiftBackupDriver(self.ctxt)
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
        service = SwiftBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        backup = db.backup_get(self.ctxt, 123)

        def fake_backup_metadata(self, backup, object_meta):
            raise exception.BackupDriverException(message=_('fake'))

        # Raise a pseudo exception.BackupDriverException.
        self.stubs.Set(SwiftBackupDriver, '_backup_metadata',
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
        service = SwiftBackupDriver(self.ctxt)
        self.volume_file.seek(0)
        backup = db.backup_get(self.ctxt, 123)

        def fake_backup_metadata(self, backup, object_meta):
            raise exception.BackupDriverException(message=_('fake'))

        # Raise a pseudo exception.BackupDriverException.
        self.stubs.Set(SwiftBackupDriver, '_backup_metadata',
                       fake_backup_metadata)

        def fake_delete(self, backup):
            raise exception.BackupOperationError()

        # Raise a pseudo exception.BackupOperationError.
        self.stubs.Set(SwiftBackupDriver, 'delete', fake_delete)

        # We expect that the second exception is notified.
        self.assertRaises(exception.BackupOperationError,
                          service.backup,
                          backup, self.volume_file)

    def test_restore(self):
        self._create_backup_db_entry()
        service = SwiftBackupDriver(self.ctxt)

        with tempfile.NamedTemporaryFile() as volume_file:
            backup = db.backup_get(self.ctxt, 123)
            service.restore(backup, '1234-5678-1234-8888', volume_file)

    def test_restore_wraps_socket_error(self):
        container_name = 'socket_error_on_get'
        self._create_backup_db_entry(container=container_name)
        service = SwiftBackupDriver(self.ctxt)

        with tempfile.NamedTemporaryFile() as volume_file:
            backup = db.backup_get(self.ctxt, 123)
            self.assertRaises(exception.SwiftConnectionFailed,
                              service.restore,
                              backup, '1234-5678-1234-8888', volume_file)

    def test_restore_unsupported_version(self):
        container_name = 'unsupported_version'
        self._create_backup_db_entry(container=container_name)
        service = SwiftBackupDriver(self.ctxt)

        with tempfile.NamedTemporaryFile() as volume_file:
            backup = db.backup_get(self.ctxt, 123)
            self.assertRaises(exception.InvalidBackup,
                              service.restore,
                              backup, '1234-5678-1234-8888', volume_file)

    def test_delete(self):
        self._create_backup_db_entry()
        service = SwiftBackupDriver(self.ctxt)
        backup = db.backup_get(self.ctxt, 123)
        service.delete(backup)

    def test_delete_wraps_socket_error(self):
        container_name = 'socket_error_on_delete'
        self._create_backup_db_entry(container=container_name)
        service = SwiftBackupDriver(self.ctxt)
        backup = db.backup_get(self.ctxt, 123)
        self.assertRaises(exception.SwiftConnectionFailed,
                          service.delete,
                          backup)

    def test_get_compressor(self):
        service = SwiftBackupDriver(self.ctxt)
        compressor = service._get_compressor('None')
        self.assertIsNone(compressor)
        compressor = service._get_compressor('zlib')
        self.assertEqual(compressor, zlib)
        compressor = service._get_compressor('bz2')
        self.assertEqual(compressor, bz2)
        self.assertRaises(ValueError, service._get_compressor, 'fake')
