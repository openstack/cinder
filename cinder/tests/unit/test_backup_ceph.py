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
""" Tests for Ceph backup service."""

import hashlib
import os
import tempfile
import uuid

import mock
from oslo_concurrency import processutils
from oslo_log import log as logging
from oslo_serialization import jsonutils
import six

from cinder.backup import driver
from cinder.backup.drivers import ceph
from cinder import context
from cinder import db
from cinder import exception
from cinder.i18n import _
from cinder import test
from cinder.volume.drivers import rbd as rbddriver

LOG = logging.getLogger(__name__)

# This is used to collect raised exceptions so that tests may check what was
# raised.
# NOTE: this must be initialised in test setUp().
RAISED_EXCEPTIONS = []


class MockException(Exception):

    def __init__(self, *args, **kwargs):
        RAISED_EXCEPTIONS.append(self.__class__)


class MockImageNotFoundException(MockException):
    """Used as mock for rbd.ImageNotFound."""


class MockImageBusyException(MockException):
    """Used as mock for rbd.ImageBusy."""


class MockObjectNotFoundException(MockException):
    """Used as mock for rados.MockObjectNotFoundException."""


def common_mocks(f):
    """Decorator to set mocks common to all tests.

    The point of doing these mocks here is so that we don't accidentally set
    mocks that can't/don't get unset.
    """
    def _common_inner_inner1(inst, *args, **kwargs):
        # NOTE(dosaboy): mock Popen to, by default, raise Exception in order to
        #                ensure that any test ending up in a subprocess fails
        #                if not properly mocked.
        @mock.patch('subprocess.Popen', spec=True)
        # NOTE(dosaboy): mock out eventlet.sleep() so that it does nothing.
        @mock.patch('eventlet.sleep', spec=True)
        @mock.patch('time.time', spec=True)
        # NOTE(dosaboy): set spec to empty object so that hasattr calls return
        #                False by default.
        @mock.patch('cinder.backup.drivers.ceph.rbd')
        @mock.patch('cinder.backup.drivers.ceph.rados')
        def _common_inner_inner2(mock_rados, mock_rbd, mock_time, mock_sleep,
                                 mock_popen):
            mock_time.side_effect = inst.time_inc
            mock_popen.side_effect = Exception

            inst.mock_rados = mock_rados
            inst.mock_rbd = mock_rbd
            inst.mock_rbd.ImageBusy = MockImageBusyException
            inst.mock_rbd.ImageNotFound = MockImageNotFoundException

            inst.service.rbd = inst.mock_rbd
            inst.service.rados = inst.mock_rados
            return f(inst, *args, **kwargs)

        return _common_inner_inner2()

    return _common_inner_inner1


class BackupCephTestCase(test.TestCase):
    """Test case for ceph backup driver."""

    def _create_volume_db_entry(self, id, size):
        vol = {'id': id, 'size': size, 'status': 'available'}
        return db.volume_create(self.ctxt, vol)['id']

    def _create_backup_db_entry(self, backupid, volid, size):
        backup = {'id': backupid, 'size': size, 'volume_id': volid}
        return db.backup_create(self.ctxt, backup)['id']

    def time_inc(self):
        self.counter += 1
        return self.counter

    def _get_wrapped_rbd_io(self, rbd_image):
        rbd_meta = rbddriver.RBDImageMetadata(rbd_image, 'pool_foo',
                                              'user_foo', 'conf_foo')
        return rbddriver.RBDImageIOWrapper(rbd_meta)

    def _setup_mock_popen(self, mock_popen, retval=None, p1hook=None,
                          p2hook=None):

        class MockPopen(object):
            hooks = [p2hook, p1hook]

            def __init__(mock_inst, cmd, *args, **kwargs):
                self.callstack.append('popen_init')
                mock_inst.stdout = mock.Mock()
                mock_inst.stdout.close = mock.Mock()
                mock_inst.stdout.close.side_effect = \
                    lambda *args: self.callstack.append('stdout_close')
                mock_inst.returncode = 0
                hook = mock_inst.__class__.hooks.pop()
                if hook is not None:
                    hook()

            def communicate(mock_inst):
                self.callstack.append('communicate')
                return retval

        mock_popen.side_effect = MockPopen

    def setUp(self):
        global RAISED_EXCEPTIONS
        RAISED_EXCEPTIONS = []
        super(BackupCephTestCase, self).setUp()
        self.ctxt = context.get_admin_context()

        # Create volume.
        self.volume_size = 1
        self.volume_id = str(uuid.uuid4())
        self._create_volume_db_entry(self.volume_id, self.volume_size)
        self.volume = db.volume_get(self.ctxt, self.volume_id)

        # Create backup of volume.
        self.backup_id = str(uuid.uuid4())
        self._create_backup_db_entry(self.backup_id, self.volume_id,
                                     self.volume_size)
        self.backup = db.backup_get(self.ctxt, self.backup_id)

        # Create alternate volume.
        self.alt_volume_id = str(uuid.uuid4())
        self._create_volume_db_entry(self.alt_volume_id, self.volume_size)
        self.alt_volume = db.volume_get(self.ctxt, self.alt_volume_id)

        self.chunk_size = 1024
        self.num_chunks = 128
        self.data_length = self.num_chunks * self.chunk_size
        self.checksum = hashlib.sha256()

        # Create a file with some data in it.
        self.volume_file = tempfile.NamedTemporaryFile()
        self.addCleanup(self.volume_file.close)
        for _i in xrange(0, self.num_chunks):
            data = os.urandom(self.chunk_size)
            self.checksum.update(data)
            self.volume_file.write(data)

        self.volume_file.seek(0)

        # Always trigger an exception if a command is executed since it should
        # always be dealt with gracefully. At time of writing on rbd
        # export/import-diff is executed and if they fail we expect to find
        # alternative means of backing up.
        mock_exec = mock.Mock()
        mock_exec.side_effect = processutils.ProcessExecutionError

        self.service = ceph.CephBackupDriver(self.ctxt, execute=mock_exec)

        # Ensure that time.time() always returns more than the last time it was
        # called to avoid div by zero errors.
        self.counter = float(0)

        self.callstack = []

    @common_mocks
    def test_get_rbd_support(self):
        del self.service.rbd.RBD_FEATURE_LAYERING
        del self.service.rbd.RBD_FEATURE_STRIPINGV2
        self.assertFalse(hasattr(self.service.rbd, 'RBD_FEATURE_LAYERING'))
        self.assertFalse(hasattr(self.service.rbd, 'RBD_FEATURE_STRIPINGV2'))

        oldformat, features = self.service._get_rbd_support()
        self.assertTrue(oldformat)
        self.assertEqual(features, 0)

        self.service.rbd.RBD_FEATURE_LAYERING = 1

        oldformat, features = self.service._get_rbd_support()
        self.assertFalse(oldformat)
        self.assertEqual(features, 1)

        self.service.rbd.RBD_FEATURE_STRIPINGV2 = 2

        oldformat, features = self.service._get_rbd_support()
        self.assertFalse(oldformat)
        self.assertEqual(features, 1 | 2)

    @common_mocks
    def test_get_most_recent_snap(self):
        last = 'backup.%s.snap.9824923.1212' % (uuid.uuid4())

        image = self.mock_rbd.Image.return_value
        image.list_snaps.return_value = \
            [{'name': 'backup.%s.snap.6423868.2342' % (uuid.uuid4())},
             {'name': 'backup.%s.snap.1321319.3235' % (uuid.uuid4())},
             {'name': last},
             {'name': 'backup.%s.snap.3824923.1412' % (uuid.uuid4())}]

        snap = self.service._get_most_recent_snap(image)
        self.assertEqual(last, snap)

    @common_mocks
    def test_get_backup_snap_name(self):
        snap_name = 'backup.%s.snap.3824923.1412' % (uuid.uuid4())

        def get_backup_snaps(inst, *args):
            return [{'name': 'backup.%s.snap.6423868.2342' % (uuid.uuid4()),
                     'backup_id': str(uuid.uuid4())},
                    {'name': snap_name,
                     'backup_id': self.backup_id}]

        with mock.patch.object(self.service, 'get_backup_snaps'):
            name = self.service._get_backup_snap_name(self.service.rbd.Image(),
                                                      'base_foo',
                                                      self.backup_id)
            self.assertIsNone(name)

        with mock.patch.object(self.service, 'get_backup_snaps') as \
                mock_get_backup_snaps:
            mock_get_backup_snaps.side_effect = get_backup_snaps
            name = self.service._get_backup_snap_name(self.service.rbd.Image(),
                                                      'base_foo',
                                                      self.backup_id)
            self.assertEqual(name, snap_name)
            self.assertTrue(mock_get_backup_snaps.called)

    @common_mocks
    def test_get_backup_snaps(self):
        image = self.mock_rbd.Image.return_value
        image.list_snaps.return_value = [
            {'name': 'backup.%s.snap.6423868.2342' % (uuid.uuid4())},
            {'name': 'backup.%s.wambam.6423868.2342' % (uuid.uuid4())},
            {'name': 'backup.%s.snap.1321319.3235' % (uuid.uuid4())},
            {'name': 'bbbackup.%s.snap.1321319.3235' % (uuid.uuid4())},
            {'name': 'backup.%s.snap.3824923.1412' % (uuid.uuid4())}]
        snaps = self.service.get_backup_snaps(image)
        self.assertEqual(len(snaps), 3)

    @common_mocks
    def test_transfer_data_from_rbd_to_file(self):
        def fake_read(offset, length):
            self.volume_file.seek(offset)
            return self.volume_file.read(length)

        self.mock_rbd.Image.return_value.read.side_effect = fake_read
        self.mock_rbd.Image.return_value.size.return_value = self.data_length

        with tempfile.NamedTemporaryFile() as test_file:
            self.volume_file.seek(0)

            rbd_io = self._get_wrapped_rbd_io(self.service.rbd.Image())
            self.service._transfer_data(rbd_io, 'src_foo', test_file,
                                        'dest_foo', self.data_length)

            checksum = hashlib.sha256()
            test_file.seek(0)
            for _c in xrange(0, self.num_chunks):
                checksum.update(test_file.read(self.chunk_size))

            # Ensure the files are equal
            self.assertEqual(checksum.digest(), self.checksum.digest())

    @common_mocks
    def test_transfer_data_from_rbd_to_rbd(self):
        def fake_read(offset, length):
            self.volume_file.seek(offset)
            return self.volume_file.read(length)

        def mock_write_data(data, offset):
            checksum.update(data)
            test_file.write(data)

        rbd1 = mock.Mock()
        rbd1.read.side_effect = fake_read

        rbd2 = mock.Mock()
        rbd2.write.side_effect = mock_write_data

        with tempfile.NamedTemporaryFile() as test_file:
            self.volume_file.seek(0)
            checksum = hashlib.sha256()

            src_rbd_io = self._get_wrapped_rbd_io(rbd1)
            dest_rbd_io = self._get_wrapped_rbd_io(rbd2)
            self.service._transfer_data(src_rbd_io, 'src_foo', dest_rbd_io,
                                        'dest_foo', self.data_length)

            # Ensure the files are equal
            self.assertEqual(checksum.digest(), self.checksum.digest())

    @common_mocks
    def test_transfer_data_from_file_to_rbd(self):

        def mock_write_data(data, offset):
            checksum.update(data)
            test_file.write(data)

        self.mock_rbd.Image.return_value.write.side_effect = mock_write_data

        with tempfile.NamedTemporaryFile() as test_file:
            self.volume_file.seek(0)
            checksum = hashlib.sha256()

            rbd_io = self._get_wrapped_rbd_io(self.service.rbd.Image())
            self.service._transfer_data(self.volume_file, 'src_foo',
                                        rbd_io, 'dest_foo', self.data_length)

            # Ensure the files are equal
            self.assertEqual(checksum.digest(), self.checksum.digest())

    @common_mocks
    def test_transfer_data_from_file_to_file(self):
        with tempfile.NamedTemporaryFile() as test_file:
            self.volume_file.seek(0)
            checksum = hashlib.sha256()

            self.service._transfer_data(self.volume_file, 'src_foo', test_file,
                                        'dest_foo', self.data_length)

            checksum = hashlib.sha256()
            test_file.seek(0)
            for _c in xrange(0, self.num_chunks):
                checksum.update(test_file.read(self.chunk_size))

            # Ensure the files are equal
            self.assertEqual(checksum.digest(), self.checksum.digest())

    @common_mocks
    def test_backup_volume_from_file(self):
        checksum = hashlib.sha256()

        def mock_write_data(data, offset):
            checksum.update(data)
            test_file.write(data)

        self.service.rbd.Image.return_value.write.side_effect = mock_write_data

        with mock.patch.object(self.service, '_backup_metadata'):
            with mock.patch.object(self.service, '_discard_bytes'):
                with tempfile.NamedTemporaryFile() as test_file:
                    self.service.backup(self.backup, self.volume_file)

                    # Ensure the files are equal
                    self.assertEqual(checksum.digest(), self.checksum.digest())

        self.assertTrue(self.service.rbd.Image.return_value.write.called)

    @common_mocks
    def test_get_backup_base_name(self):
        name = self.service._get_backup_base_name(self.volume_id,
                                                  diff_format=True)
        self.assertEqual(name, "volume-%s.backup.base" % (self.volume_id))

        self.assertRaises(exception.InvalidParameterValue,
                          self.service._get_backup_base_name,
                          self.volume_id)

        name = self.service._get_backup_base_name(self.volume_id, '1234')
        self.assertEqual(name,
                         "volume-%s.backup.%s" % (self.volume_id, '1234'))

    @common_mocks
    @mock.patch('fcntl.fcntl', spec=True)
    @mock.patch('subprocess.Popen', spec=True)
    def test_backup_volume_from_rbd(self, mock_popen, mock_fnctl):
        backup_name = self.service._get_backup_base_name(self.backup_id,
                                                         diff_format=True)

        def mock_write_data():
            self.volume_file.seek(0)
            data = self.volume_file.read(self.data_length)
            self.callstack.append('write')
            checksum.update(data)
            test_file.write(data)

        def mock_read_data():
            self.callstack.append('read')
            return self.volume_file.read(self.data_length)

        self._setup_mock_popen(mock_popen,
                               ['out', 'err'],
                               p1hook=mock_read_data,
                               p2hook=mock_write_data)

        self.mock_rbd.RBD.list = mock.Mock()
        self.mock_rbd.RBD.list.return_value = [backup_name]

        with mock.patch.object(self.service, '_backup_metadata'):
            with mock.patch.object(self.service, 'get_backup_snaps') as \
                    mock_get_backup_snaps:
                with mock.patch.object(self.service, '_full_backup') as \
                        mock_full_backup:
                    with mock.patch.object(self.service,
                                           '_try_delete_base_image'):
                        with tempfile.NamedTemporaryFile() as test_file:
                            checksum = hashlib.sha256()
                            image = self.service.rbd.Image()
                            meta = rbddriver.RBDImageMetadata(image,
                                                              'pool_foo',
                                                              'user_foo',
                                                              'conf_foo')
                            rbdio = rbddriver.RBDImageIOWrapper(meta)
                            self.service.backup(self.backup, rbdio)

                            self.assertEqual(self.callstack, ['popen_init',
                                                              'read',
                                                              'popen_init',
                                                              'write',
                                                              'stdout_close',
                                                              'communicate'])

                            self.assertFalse(mock_full_backup.called)
                            self.assertTrue(mock_get_backup_snaps.called)

                            # Ensure the files are equal
                            self.assertEqual(checksum.digest(),
                                             self.checksum.digest())

    @common_mocks
    @mock.patch('fcntl.fcntl', spec=True)
    @mock.patch('subprocess.Popen', spec=True)
    def test_backup_volume_from_rbd_fail(self, mock_popen, mock_fnctl):
        """Test of when an exception occurs in an exception handler.

        In _backup_rbd(), after an exception.BackupRBDOperationFailed
        occurs in self._rbd_diff_transfer(), we want to check the
        process when the second exception occurs in
        self._try_delete_base_image().
        """
        backup_name = self.service._get_backup_base_name(self.backup_id,
                                                         diff_format=True)

        def mock_write_data():
            self.volume_file.seek(0)
            data = self.volume_file.read(self.data_length)
            self.callstack.append('write')
            checksum.update(data)
            test_file.write(data)

        def mock_read_data():
            self.callstack.append('read')
            return self.volume_file.read(self.data_length)

        self._setup_mock_popen(mock_popen,
                               ['out', 'err'],
                               p1hook=mock_read_data,
                               p2hook=mock_write_data)

        self.mock_rbd.RBD.list = mock.Mock()
        self.mock_rbd.RBD.list.return_value = [backup_name]

        with mock.patch.object(self.service, 'get_backup_snaps'), \
                mock.patch.object(self.service, '_rbd_diff_transfer') as \
                mock_rbd_diff_transfer:
            def mock_rbd_diff_transfer_side_effect(src_name, src_pool,
                                                   dest_name, dest_pool,
                                                   src_user, src_conf,
                                                   dest_user, dest_conf,
                                                   src_snap, from_snap):
                raise exception.BackupRBDOperationFailed(_('mock'))

            # Raise a pseudo exception.BackupRBDOperationFailed.
            mock_rbd_diff_transfer.side_effect \
                = mock_rbd_diff_transfer_side_effect

            with mock.patch.object(self.service, '_full_backup'), \
                    mock.patch.object(self.service,
                                      '_try_delete_base_image') as \
                    mock_try_delete_base_image:
                def mock_try_delete_base_image_side_effect(backup_id,
                                                           volume_id,
                                                           base_name):
                    raise self.service.rbd.ImageNotFound(_('mock'))

                # Raise a pesudo exception rbd.ImageNotFound.
                mock_try_delete_base_image.side_effect \
                    = mock_try_delete_base_image_side_effect
                with mock.patch.object(self.service, '_backup_metadata'):
                    with tempfile.NamedTemporaryFile() as test_file:
                        checksum = hashlib.sha256()
                        image = self.service.rbd.Image()
                        meta = rbddriver.RBDImageMetadata(image,
                                                          'pool_foo',
                                                          'user_foo',
                                                          'conf_foo')
                        rbdio = rbddriver.RBDImageIOWrapper(meta)

                        # We expect that the second exception is
                        # notified.
                        self.assertRaises(
                            self.service.rbd.ImageNotFound,
                            self.service.backup,
                            self.backup, rbdio)

    @common_mocks
    @mock.patch('fcntl.fcntl', spec=True)
    @mock.patch('subprocess.Popen', spec=True)
    def test_backup_volume_from_rbd_fail2(self, mock_popen, mock_fnctl):
        """Test of when an exception occurs in an exception handler.

        In backup(), after an exception.BackupOperationError occurs in
        self._backup_metadata(), we want to check the process when the
        second exception occurs in self.delete().
        """
        backup_name = self.service._get_backup_base_name(self.backup_id,
                                                         diff_format=True)

        def mock_write_data():
            self.volume_file.seek(0)
            data = self.volume_file.read(self.data_length)
            self.callstack.append('write')
            checksum.update(data)
            test_file.write(data)

        def mock_read_data():
            self.callstack.append('read')
            return self.volume_file.read(self.data_length)

        self._setup_mock_popen(mock_popen,
                               ['out', 'err'],
                               p1hook=mock_read_data,
                               p2hook=mock_write_data)

        self.mock_rbd.RBD.list = mock.Mock()
        self.mock_rbd.RBD.list.return_value = [backup_name]

        with mock.patch.object(self.service, 'get_backup_snaps'), \
                mock.patch.object(self.service, '_rbd_diff_transfer'), \
                mock.patch.object(self.service, '_full_backup'), \
                mock.patch.object(self.service, '_backup_metadata') as \
                mock_backup_metadata:

            def mock_backup_metadata_side_effect(backup):
                raise exception.BackupOperationError(_('mock'))

            # Raise a pseudo exception.BackupOperationError.
            mock_backup_metadata.side_effect = mock_backup_metadata_side_effect
            with mock.patch.object(self.service, 'delete') as mock_delete:
                def mock_delete_side_effect(backup):
                    raise self.service.rbd.ImageBusy()

                # Raise a pseudo exception rbd.ImageBusy.
                mock_delete.side_effect = mock_delete_side_effect
                with tempfile.NamedTemporaryFile() as test_file:
                    checksum = hashlib.sha256()
                    image = self.service.rbd.Image()
                    meta = rbddriver.RBDImageMetadata(image,
                                                      'pool_foo',
                                                      'user_foo',
                                                      'conf_foo')
                    rbdio = rbddriver.RBDImageIOWrapper(meta)

                    # We expect that the second exception is
                    # notified.
                    self.assertRaises(
                        self.service.rbd.ImageBusy,
                        self.service.backup,
                        self.backup, rbdio)

    @common_mocks
    def test_backup_vol_length_0(self):
        volume_id = str(uuid.uuid4())
        self._create_volume_db_entry(volume_id, 0)

        backup_id = str(uuid.uuid4())
        self._create_backup_db_entry(backup_id, volume_id, 1)
        backup = db.backup_get(self.ctxt, backup_id)

        self.assertRaises(exception.InvalidParameterValue, self.service.backup,
                          backup, self.volume_file)

    @common_mocks
    def test_restore(self):
        backup_name = self.service._get_backup_base_name(self.backup_id,
                                                         diff_format=True)

        self.mock_rbd.RBD.return_value.list.return_value = [backup_name]

        def mock_read_data(offset, length):
            return self.volume_file.read(self.data_length)

        self.mock_rbd.Image.return_value.read.side_effect = mock_read_data

        self.mock_rbd.Image.return_value.size.return_value = \
            self.chunk_size * self.num_chunks

        with mock.patch.object(self.service, '_restore_metadata') as \
                mock_restore_metadata:
            with mock.patch.object(self.service, '_discard_bytes') as \
                    mock_discard_bytes:
                with tempfile.NamedTemporaryFile() as test_file:
                    self.volume_file.seek(0)

                    self.service.restore(self.backup, self.volume_id,
                                         test_file)

                    checksum = hashlib.sha256()
                    test_file.seek(0)
                    for _c in xrange(0, self.num_chunks):
                        checksum.update(test_file.read(self.chunk_size))

                    # Ensure the files are equal
                    self.assertEqual(checksum.digest(), self.checksum.digest())

                    self.assertTrue(mock_restore_metadata.called)
                    self.assertTrue(mock_discard_bytes.called)
                    self.assertTrue(mock_discard_bytes.called)

        self.assertTrue(self.service.rbd.Image.return_value.read.called)

    @common_mocks
    def test_discard_bytes(self):
        # Lower the chunksize to a memory managable number
        self.service.chunk_size = 1024
        image = self.mock_rbd.Image.return_value
        wrapped_rbd = self._get_wrapped_rbd_io(image)

        self.service._discard_bytes(wrapped_rbd, 0, 0)
        self.assertEqual(image.discard.call_count, 0)

        self.service._discard_bytes(wrapped_rbd, 0, 1234)
        self.assertEqual(image.discard.call_count, 1)
        image.reset_mock()

        # Test discard with no remainder
        with mock.patch.object(self.service, '_file_is_rbd') as \
                mock_file_is_rbd:
            mock_file_is_rbd.return_value = False

            self.service._discard_bytes(wrapped_rbd, 0,
                                        self.service.chunk_size * 2)

            self.assertEqual(image.write.call_count, 2)
            self.assertEqual(image.flush.call_count, 2)
            self.assertFalse(image.discard.called)

        image.reset_mock()

        # Now test with a remainder.
        with mock.patch.object(self.service, '_file_is_rbd') as \
                mock_file_is_rbd:
            mock_file_is_rbd.return_value = False

            self.service._discard_bytes(wrapped_rbd, 0,
                                        (self.service.chunk_size * 2) + 1)

            self.assertEqual(image.write.call_count, 3)
            self.assertEqual(image.flush.call_count, 3)
            self.assertFalse(image.discard.called)

    @common_mocks
    def test_delete_backup_snapshot(self):
        snap_name = 'backup.%s.snap.3824923.1412' % (uuid.uuid4())
        base_name = self.service._get_backup_base_name(self.volume_id,
                                                       diff_format=True)
        self.mock_rbd.RBD.remove_snap = mock.Mock()

        with mock.patch.object(self.service, '_get_backup_snap_name') as \
                mock_get_backup_snap_name:
            mock_get_backup_snap_name.return_value = snap_name
            with mock.patch.object(self.service, 'get_backup_snaps') as \
                    mock_get_backup_snaps:
                mock_get_backup_snaps.return_value = None
                rem = self.service._delete_backup_snapshot(self.mock_rados,
                                                           base_name,
                                                           self.backup_id)

                self.assertTrue(mock_get_backup_snap_name.called)
                self.assertTrue(mock_get_backup_snaps.called)
                self.assertEqual(rem, (snap_name, 0))

    @common_mocks
    @mock.patch('cinder.backup.drivers.ceph.VolumeMetadataBackup', spec=True)
    def test_try_delete_base_image_diff_format(self, mock_meta_backup):
        backup_name = self.service._get_backup_base_name(self.volume_id,
                                                         diff_format=True)

        self.mock_rbd.RBD.return_value.list.return_value = [backup_name]

        with mock.patch.object(self.service, '_delete_backup_snapshot') as \
                mock_del_backup_snap:
            snap_name = self.service._get_new_snap_name(self.backup_id)
            mock_del_backup_snap.return_value = (snap_name, 0)

            self.service.delete(self.backup)
            self.assertTrue(mock_del_backup_snap.called)

        self.assertTrue(self.mock_rbd.RBD.return_value.list.called)
        self.assertTrue(self.mock_rbd.RBD.return_value.remove.called)

    @common_mocks
    @mock.patch('cinder.backup.drivers.ceph.VolumeMetadataBackup', spec=True)
    def test_try_delete_base_image(self, mock_meta_backup):
        backup_name = self.service._get_backup_base_name(self.volume_id,
                                                         self.backup_id)

        self.mock_rbd.RBD.return_value.list.return_value = [backup_name]

        with mock.patch.object(self.service, 'get_backup_snaps'):
            self.service.delete(self.backup)
            self.assertTrue(self.mock_rbd.RBD.return_value.remove.called)

    @common_mocks
    def test_try_delete_base_image_busy(self):
        """This should induce retries then raise rbd.ImageBusy."""
        backup_name = self.service._get_backup_base_name(self.volume_id,
                                                         self.backup_id)

        rbd = self.mock_rbd.RBD.return_value
        rbd.list.return_value = [backup_name]
        rbd.remove.side_effect = self.mock_rbd.ImageBusy

        with mock.patch.object(self.service, 'get_backup_snaps') as \
                mock_get_backup_snaps:
            self.assertRaises(self.mock_rbd.ImageBusy,
                              self.service._try_delete_base_image,
                              self.backup['id'], self.backup['volume_id'])
            self.assertTrue(mock_get_backup_snaps.called)

        self.assertTrue(rbd.list.called)
        self.assertTrue(rbd.remove.called)
        self.assertTrue(MockImageBusyException in RAISED_EXCEPTIONS)

    @common_mocks
    @mock.patch('cinder.backup.drivers.ceph.VolumeMetadataBackup', spec=True)
    def test_delete(self, mock_meta_backup):
        with mock.patch.object(self.service, '_try_delete_base_image'):
            self.service.delete(self.backup)
            self.assertEqual(RAISED_EXCEPTIONS, [])

    @common_mocks
    @mock.patch('cinder.backup.drivers.ceph.VolumeMetadataBackup', spec=True)
    def test_delete_image_not_found(self, mock_meta_backup):
        with mock.patch.object(self.service, '_try_delete_base_image') as \
                mock_del_base:
            mock_del_base.side_effect = self.mock_rbd.ImageNotFound
            # ImageNotFound exception is caught so that db entry can be cleared
            self.service.delete(self.backup)
            self.assertEqual(RAISED_EXCEPTIONS, [MockImageNotFoundException])

    @common_mocks
    def test_diff_restore_allowed(self):
        not_allowed = (False, None)
        backup_base = 'backup.base'
        restore_point = 'backup.snap.1'
        rbd_io = self._get_wrapped_rbd_io(self.service.rbd.Image())
        args_vols_different = [backup_base, self.backup, self.alt_volume,
                               rbd_io, self.mock_rados]
        args_vols_same = [backup_base, self.backup, self.volume, rbd_io,
                          self.mock_rados]

        # 1. destination volume is not an rbd
        with mock.patch.object(self.service, '_file_is_rbd') as \
                mock_file_is_rbd:
            mock_file_is_rbd.return_value = False
            resp = self.service._diff_restore_allowed(*args_vols_different)
            self.assertEqual(resp, not_allowed)
            self.assertTrue(mock_file_is_rbd.called)

        # 1. destination volume is an rbd
        # 2. backup base is not diff-format
        with mock.patch.object(self.service, '_file_is_rbd') as \
                mock_file_is_rbd:
            mock_file_is_rbd.return_value = True
            with mock.patch.object(self.service, '_rbd_image_exists') as \
                    mock_rbd_image_exists:
                mock_rbd_image_exists.return_value = (False, backup_base)
                resp = self.service._diff_restore_allowed(*args_vols_different)
                self.assertEqual(resp, not_allowed)
                self.assertTrue(mock_file_is_rbd.called)
                self.assertTrue(mock_rbd_image_exists.called)

        # 1. destination volume is an rbd
        # 2. backup base is diff-format
        # 3. restore point does not exist
        # 4. source and destination volumes are different
        with mock.patch.object(self.service, '_file_is_rbd') as \
                mock_file_is_rbd:
            mock_file_is_rbd.return_value = True
            with mock.patch.object(self.service, '_rbd_image_exists') as \
                    mock_rbd_image_exists:
                mock_rbd_image_exists.return_value = (True, backup_base)
                with mock.patch.object(self.service, '_get_restore_point') as \
                        mock_get_restore_point:
                    mock_get_restore_point.return_value = None

                    args = args_vols_different
                    resp = self.service._diff_restore_allowed(*args)

                    self.assertEqual(resp, not_allowed)
                    self.assertTrue(mock_file_is_rbd.called)
                    self.assertTrue(mock_rbd_image_exists.called)
                    self.assertTrue(mock_get_restore_point.called)

        # 1. destination volume is an rbd
        # 2. backup base is diff-format
        # 3. restore point does not exist
        # 4. source and destination volumes are the same
        with mock.patch.object(self.service, '_file_is_rbd') as \
                mock_file_is_rbd:
            mock_file_is_rbd.return_value = True
            with mock.patch.object(self.service, '_rbd_image_exists') as \
                    mock_rbd_image_exists:
                mock_rbd_image_exists.return_value = (True, backup_base)
                with mock.patch.object(self.service, '_get_restore_point') as \
                        mock_get_restore_point:
                    mock_get_restore_point.return_value = None

                    resp = self.service._diff_restore_allowed(*args_vols_same)

                    self.assertEqual(resp, not_allowed)
                    self.assertTrue(mock_file_is_rbd.called)
                    self.assertTrue(mock_rbd_image_exists.called)
                    self.assertTrue(mock_get_restore_point.called)

        # 1. destination volume is an rbd
        # 2. backup base is diff-format
        # 3. restore point exists
        # 4. source and destination volumes are different
        # 5. destination volume has data on it - full copy is mandated
        with mock.patch.object(self.service, '_file_is_rbd') as \
                mock_file_is_rbd:
            mock_file_is_rbd.return_value = True
            with mock.patch.object(self.service, '_rbd_image_exists') as \
                    mock_rbd_image_exists:
                mock_rbd_image_exists.return_value = (True, backup_base)
                with mock.patch.object(self.service, '_get_restore_point') as \
                        mock_get_restore_point:
                    mock_get_restore_point.return_value = restore_point
                    with mock.patch.object(self.service, '_rbd_has_extents') \
                            as mock_rbd_has_extents:
                        mock_rbd_has_extents.return_value = True

                        args = args_vols_different
                        resp = self.service._diff_restore_allowed(*args)

                        self.assertEqual(resp, (False, restore_point))
                        self.assertTrue(mock_file_is_rbd.called)
                        self.assertTrue(mock_rbd_image_exists.called)
                        self.assertTrue(mock_get_restore_point.called)
                        self.assertTrue(mock_rbd_has_extents.called)

        # 1. destination volume is an rbd
        # 2. backup base is diff-format
        # 3. restore point exists
        # 4. source and destination volumes are different
        # 5. destination volume no data on it
        with mock.patch.object(self.service, '_file_is_rbd') as \
                mock_file_is_rbd:
            mock_file_is_rbd.return_value = True
            with mock.patch.object(self.service, '_rbd_image_exists') as \
                    mock_rbd_image_exists:
                mock_rbd_image_exists.return_value = (True, backup_base)
                with mock.patch.object(self.service, '_get_restore_point') as \
                        mock_restore_point:
                    mock_restore_point.return_value = restore_point
                    with mock.patch.object(self.service, '_rbd_has_extents') \
                            as mock_rbd_has_extents:
                        mock_rbd_has_extents.return_value = False

                        args = args_vols_different
                        resp = self.service._diff_restore_allowed(*args)

                        self.assertEqual(resp, (True, restore_point))
                        self.assertTrue(mock_restore_point.called)
                        self.assertTrue(mock_rbd_has_extents.called)
                        self.assertTrue(mock_rbd_image_exists.called)
                        self.assertTrue(mock_file_is_rbd.called)

    @common_mocks
    @mock.patch('fcntl.fcntl', spec=True)
    @mock.patch('subprocess.Popen', spec=True)
    def test_piped_execute(self, mock_popen, mock_fcntl):
        mock_fcntl.return_value = 0
        self._setup_mock_popen(mock_popen, ['out', 'err'])
        self.service._piped_execute(['foo'], ['bar'])
        self.assertEqual(self.callstack, ['popen_init', 'popen_init',
                                          'stdout_close', 'communicate'])

    @common_mocks
    def test_restore_metdata(self):
        version = 2

        def mock_read(*args):
            base_tag = driver.BackupMetadataAPI.TYPE_TAG_VOL_BASE_META
            glance_tag = driver.BackupMetadataAPI.TYPE_TAG_VOL_GLANCE_META
            return jsonutils.dumps({base_tag: {'image_name': 'image.base'},
                                    glance_tag: {'image_name': 'image.glance'},
                                    'version': version})

        self.mock_rados.Object.return_value.read.side_effect = mock_read

        self.service._restore_metadata(self.backup, self.volume_id)

        self.assertTrue(self.mock_rados.Object.return_value.stat.called)
        self.assertTrue(self.mock_rados.Object.return_value.read.called)

        version = 3
        try:
            self.service._restore_metadata(self.backup, self.volume_id)
        except exception.BackupOperationError as exc:
            msg = _("Metadata restore failed due to incompatible version")
            self.assertEqual(six.text_type(exc), msg)
        else:
            # Force a test failure
            self.assertFalse(True)

    @common_mocks
    @mock.patch('cinder.backup.drivers.ceph.VolumeMetadataBackup', spec=True)
    def test_backup_metadata_already_exists(self, mock_meta_backup):

        def mock_set(json_meta):
            msg = (_("Metadata backup object '%s' already exists") %
                   ("backup.%s.meta" % (self.backup_id)))
            raise exception.VolumeMetadataBackupExists(msg)

        mock_meta_backup.return_value.set = mock.Mock()
        mock_meta_backup.return_value.set.side_effect = mock_set

        with mock.patch.object(self.service, 'get_metadata') as \
                mock_get_metadata:
            mock_get_metadata.return_value = "some.json.metadata"
            try:
                self.service._backup_metadata(self.backup)
            except exception.BackupOperationError as e:
                msg = (_("Failed to backup volume metadata - Metadata backup "
                         "object 'backup.%s.meta' already exists") %
                       (self.backup_id))
                self.assertEqual(six.text_type(e), msg)
            else:
                # Make the test fail
                self.assertFalse(True)

        self.assertFalse(mock_meta_backup.set.called)

    @common_mocks
    def test_backup_metata_error(self):
        """Ensure that delete() is called if the metadata backup fails.

        Also ensure that the exception is propagated to the caller.
        """
        with mock.patch.object(self.service, '_backup_metadata') as \
                mock_backup_metadata:
            mock_backup_metadata.side_effect = exception.BackupOperationError
            with mock.patch.object(self.service, '_get_volume_size_gb'):
                with mock.patch.object(self.service, '_file_is_rbd',
                                       return_value=False):
                    with mock.patch.object(self.service, '_full_backup'):
                        with mock.patch.object(self.service, 'delete') as \
                                mock_delete:
                            self.assertRaises(exception.BackupOperationError,
                                              self.service.backup, self.backup,
                                              mock.Mock(),
                                              backup_metadata=True)
                            self.assertTrue(mock_delete.called)

    @common_mocks
    def test_restore_invalid_metadata_version(self):

        def mock_read(*args):
            base_tag = driver.BackupMetadataAPI.TYPE_TAG_VOL_BASE_META
            glance_tag = driver.BackupMetadataAPI.TYPE_TAG_VOL_GLANCE_META
            return jsonutils.dumps({base_tag: {'image_name': 'image.base'},
                                    glance_tag: {'image_name': 'image.glance'},
                                    'version': 3})

        self.mock_rados.Object.return_value.read.side_effect = mock_read
        with mock.patch.object(ceph.VolumeMetadataBackup, '_exists') as \
                mock_exists:
            mock_exists.return_value = True

            self.assertRaises(exception.BackupOperationError,
                              self.service._restore_metadata,
                              self.backup, self.volume_id)

            self.assertTrue(mock_exists.called)

        self.assertTrue(self.mock_rados.Object.return_value.read.called)


def common_meta_backup_mocks(f):
    """Decorator to set mocks common to all metadata backup tests.

    The point of doing these mocks here is so that we don't accidentally set
    mocks that can't/don't get unset.
    """
    def _common_inner_inner1(inst, *args, **kwargs):
        @mock.patch('cinder.backup.drivers.ceph.rbd')
        @mock.patch('cinder.backup.drivers.ceph.rados')
        def _common_inner_inner2(mock_rados, mock_rbd):
            inst.mock_rados = mock_rados
            inst.mock_rbd = mock_rbd
            inst.mock_rados.ObjectNotFound = MockObjectNotFoundException
            return f(inst, *args, **kwargs)

        return _common_inner_inner2()
    return _common_inner_inner1


class VolumeMetadataBackupTestCase(test.TestCase):

    def setUp(self):
        global RAISED_EXCEPTIONS
        RAISED_EXCEPTIONS = []
        super(VolumeMetadataBackupTestCase, self).setUp()
        self.backup_id = str(uuid.uuid4())
        self.mb = ceph.VolumeMetadataBackup(mock.Mock(), self.backup_id)

    @common_meta_backup_mocks
    def test_name(self):
        self.assertEqual(self.mb.name, 'backup.%s.meta' % (self.backup_id))

    @common_meta_backup_mocks
    def test_exists(self):
        # True
        self.assertTrue(self.mb.exists)
        self.assertTrue(self.mock_rados.Object.return_value.stat.called)
        self.mock_rados.Object.return_value.reset_mock()

        # False
        self.mock_rados.Object.return_value.stat.side_effect = (
            self.mock_rados.ObjectNotFound)
        self.assertFalse(self.mb.exists)
        self.assertTrue(self.mock_rados.Object.return_value.stat.called)
        self.assertEqual(RAISED_EXCEPTIONS, [MockObjectNotFoundException])

    @common_meta_backup_mocks
    def test_set(self):
        obj_data = []
        called = []

        def mock_read(*args):
            called.append('read')
            self.assertTrue(len(obj_data) == 1)
            return obj_data[0]

        def _mock_write(data):
            obj_data.append(data)
            called.append('write')

        self.mb.get = mock.Mock()
        self.mb.get.side_effect = mock_read

        with mock.patch.object(ceph.VolumeMetadataBackup, 'set') as mock_write:
            mock_write.side_effect = _mock_write

            self.mb.set({'foo': 'bar'})
            self.assertEqual(self.mb.get(), {'foo': 'bar'})
            self.assertTrue(self.mb.get.called)

            self.mb._exists = mock.Mock()
            self.mb._exists.return_value = True

        # use the unmocked set() method.
        self.assertRaises(exception.VolumeMetadataBackupExists, self.mb.set,
                          {'doo': 'dah'})

        # check the meta obj state has not changed.
        self.assertEqual(self.mb.get(), {'foo': 'bar'})

        self.assertEqual(called, ['write', 'read', 'read'])

    @common_meta_backup_mocks
    def test_get(self):
        self.mock_rados.Object.return_value.stat.side_effect = (
            self.mock_rados.ObjectNotFound)
        self.mock_rados.Object.return_value.read.return_value = 'meta'
        self.assertIsNone(self.mb.get())
        self.mock_rados.Object.return_value.stat.side_effect = None
        self.assertEqual(self.mb.get(), 'meta')

    @common_meta_backup_mocks
    def remove_if_exists(self):
        with mock.patch.object(self.mock_rados.Object, 'remove') as \
                mock_remove:
            mock_remove.side_effect = self.mock_rados.ObjectNotFound
            self.mb.remove_if_exists()
            self.assertEqual(RAISED_EXCEPTIONS, [MockObjectNotFoundException])

            self.mock_rados.Object.remove.side_effect = None
            self.mb.remove_if_exists()
            self.assertEqual(RAISED_EXCEPTIONS, [])
