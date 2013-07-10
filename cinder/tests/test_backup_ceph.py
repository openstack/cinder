# Copyright 2013 Canonical Ltd.
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
""" Tests for Ceph backup service """

import hashlib
import os
import tempfile
import uuid

from cinder.backup.drivers.ceph import CephBackupDriver
from cinder.tests.backup.fake_rados import mock_rados
from cinder.tests.backup.fake_rados import mock_rbd

from cinder.backup.drivers import ceph
from cinder import context
from cinder import db
from cinder import exception
from cinder.openstack.common import log as logging
from cinder import test

LOG = logging.getLogger(__name__)


class BackupCephTestCase(test.TestCase):
    """Test Case for backup to Ceph object store"""

    def _create_volume_db_entry(self, id, size):
        vol = {'id': id, 'size': size, 'status': 'available'}
        return db.volume_create(self.ctxt, vol)['id']

    def _create_backup_db_entry(self, backupid, volid, size):
        backup = {'id': backupid, 'size': size, 'volume_id': volid}
        return db.backup_create(self.ctxt, backup)['id']

    def setUp(self):
        super(BackupCephTestCase, self).setUp()
        self.ctxt = context.get_admin_context()

        self.vol_id = str(uuid.uuid4())
        self.backup_id = str(uuid.uuid4())

        # Setup librbd stubs
        self.stubs.Set(ceph, 'rados', mock_rados)
        self.stubs.Set(ceph, 'rbd', mock_rbd)

        self._create_backup_db_entry(self.backup_id, self.vol_id, 1)

        self.chunk_size = 1024
        self.num_chunks = 128
        self.length = self.num_chunks * self.chunk_size

        self.checksum = hashlib.sha256()

        # Create a file with some data in it
        self.volume_file = tempfile.NamedTemporaryFile()
        for i in xrange(0, self.num_chunks):
            data = os.urandom(self.chunk_size)
            self.checksum.update(data)
            self.volume_file.write(data)

        self.volume_file.seek(0)

    def test_get_rbd_support(self):
        service = CephBackupDriver(self.ctxt)

        self.assertFalse(hasattr(service.rbd, 'RBD_FEATURE_LAYERING'))
        self.assertFalse(hasattr(service.rbd, 'RBD_FEATURE_STRIPINGV2'))

        oldformat, features = service._get_rbd_support()
        self.assertTrue(oldformat)
        self.assertEquals(features, 0)

        service.rbd.RBD_FEATURE_LAYERING = 1

        oldformat, features = service._get_rbd_support()
        self.assertFalse(oldformat)
        self.assertEquals(features, 1)

        service.rbd.RBD_FEATURE_STRIPINGV2 = 2

        oldformat, features = service._get_rbd_support()
        self.assertFalse(oldformat)
        self.assertEquals(features, 1 | 2)

    def test_tranfer_data_from_rbd(self):
        service = CephBackupDriver(self.ctxt)

        with tempfile.NamedTemporaryFile() as test_file:
            self.volume_file.seek(0)

            def read_data(inst, offset, length):
                return self.volume_file.read(self.length)

            self.stubs.Set(service.rbd.Image, 'read', read_data)

            service._transfer_data(service.rbd.Image(), test_file, 'foo',
                                   self.length)

            checksum = hashlib.sha256()
            test_file.seek(0)
            for c in xrange(0, self.num_chunks):
                checksum.update(test_file.read(self.chunk_size))

            # Ensure the files are equal
            self.assertEquals(checksum.digest(), self.checksum.digest())

    def test_tranfer_data_to_rbd(self):
        service = CephBackupDriver(self.ctxt)

        with tempfile.NamedTemporaryFile() as test_file:
            checksum = hashlib.sha256()

            def write_data(inst, data, offset):
                checksum.update(data)
                test_file.write(data)

            self.stubs.Set(service.rbd.Image, 'write', write_data)

            service._transfer_data(self.volume_file, service.rbd.Image(),
                                   'foo', self.length, dest_is_rbd=True)

            # Ensure the files are equal
            self.assertEquals(checksum.digest(), self.checksum.digest())

    def test_backup_volume_from_file(self):
        service = CephBackupDriver(self.ctxt)

        with tempfile.NamedTemporaryFile() as test_file:
            checksum = hashlib.sha256()

            def write_data(inst, data, offset):
                checksum.update(data)
                test_file.write(data)

            self.stubs.Set(service.rbd.Image, 'write', write_data)

            service._backup_volume_from_file('foo', self.length,
                                             self.volume_file)

            # Ensure the files are equal
            self.assertEquals(checksum.digest(), self.checksum.digest())

    def tearDown(self):
        self.volume_file.close()
        super(BackupCephTestCase, self).tearDown()

    def test_backup_error1(self):
        service = CephBackupDriver(self.ctxt)
        backup = db.backup_get(self.ctxt, self.backup_id)
        self._create_volume_db_entry(self.vol_id, 0)
        self.assertRaises(exception.InvalidParameterValue, service.backup,
                          backup, self.volume_file)

    def test_backup_error2(self):
        service = CephBackupDriver(self.ctxt)
        backup = db.backup_get(self.ctxt, self.backup_id)
        self._create_volume_db_entry(self.vol_id, 1)
        self.assertRaises(exception.BackupVolumeInvalidType, service.backup,
                          backup, None)

    def test_backup_good(self):
        service = CephBackupDriver(self.ctxt)
        backup = db.backup_get(self.ctxt, self.backup_id)
        self._create_volume_db_entry(self.vol_id, 1)

        with tempfile.NamedTemporaryFile() as test_file:
            checksum = hashlib.sha256()

            def write_data(inst, data, offset):
                checksum.update(data)
                test_file.write(data)

            self.stubs.Set(service.rbd.Image, 'write', write_data)

            service.backup(backup, self.volume_file)

            # Ensure the files are equal
            self.assertEquals(checksum.digest(), self.checksum.digest())

    def test_restore(self):
        service = CephBackupDriver(self.ctxt)
        self._create_volume_db_entry(self.vol_id, 1)
        backup = db.backup_get(self.ctxt, self.backup_id)

        with tempfile.NamedTemporaryFile() as test_file:
            self.volume_file.seek(0)

            def read_data(inst, offset, length):
                return self.volume_file.read(self.length)

            self.stubs.Set(service.rbd.Image, 'read', read_data)

            service.restore(backup, self.vol_id, test_file)

            checksum = hashlib.sha256()
            test_file.seek(0)
            for c in xrange(0, self.num_chunks):
                checksum.update(test_file.read(self.chunk_size))

            # Ensure the files are equal
            self.assertEquals(checksum.digest(), self.checksum.digest())

    def test_delete(self):
        service = CephBackupDriver(self.ctxt)
        self._create_volume_db_entry(self.vol_id, 1)
        backup = db.backup_get(self.ctxt, self.backup_id)

        # Must be something mutable
        remove_called = []

        def remove(inst, ioctx, name):
            remove_called.append(True)

        self.stubs.Set(service.rbd.RBD, 'remove', remove)
        service.delete(backup)
        self.assertTrue(remove_called[0])
