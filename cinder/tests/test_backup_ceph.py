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

import eventlet
import fcntl
import hashlib
import mock
import os
import subprocess
import tempfile
import time
import uuid

from cinder.backup.drivers import ceph
from cinder import context
from cinder import db
from cinder import exception
from cinder.openstack.common import log as logging
from cinder.openstack.common import processutils
from cinder import test
from cinder import units
from cinder.volume.drivers import rbd as rbddriver

LOG = logging.getLogger(__name__)


class ImageNotFound(Exception):
    _called = False

    def __init__(self, *args, **kwargs):
        self.__class__._called = True

    @classmethod
    def called(cls):
        ret = cls._called
        cls._called = False
        return ret


class ImageBusy(Exception):
    _called = False

    def __init__(self, *args, **kwargs):
        self.__class__._called = True

    @classmethod
    def called(cls):
        ret = cls._called
        cls._called = False
        return ret


def common_backup_mocks(f):
    """Decorator to set mocks common to all backup tests.
    """
    def _common_backup_mocks_inner(inst, *args, **kwargs):
        inst.service.rbd.Image.size = mock.Mock()
        inst.service.rbd.Image.size.return_value = \
            inst.chunk_size * inst.num_chunks

        with mock.patch.object(inst.service, '_get_rbd_support') as \
                mock_rbd_support:
            mock_rbd_support.return_value = (True, 3)
            with mock.patch.object(inst.service, 'get_backup_snaps'):
                return f(inst, *args, **kwargs)

    return _common_backup_mocks_inner


def common_restore_mocks(f):
    """Decorator to set mocks common to all restore tests.
    """
    @common_backup_mocks
    def _common_restore_mocks_inner(inst, *args, **kwargs):
        return f(inst, *args, **kwargs)

    return _common_restore_mocks_inner


def common_mocks(f):
    """Decorator to set mocks common to all tests.

    The point of doing these mocks here is so that we don't accidentally set
    mocks that can't/dont't get unset.
    """
    def _common_inner_inner1(inst, *args, **kwargs):
        @mock.patch('cinder.backup.drivers.ceph.rbd')
        @mock.patch('cinder.backup.drivers.ceph.rados')
        def _common_inner_inner2(mock_rados, mock_rbd):
            inst.mock_rados = mock_rados
            inst.mock_rbd = mock_rbd
            inst.mock_rados.Rados = mock.Mock
            inst.mock_rados.Rados.ioctx = mock.Mock()
            inst.mock_rbd.RBD = mock.Mock
            inst.mock_rbd.Image = mock.Mock
            inst.mock_rbd.Image.close = mock.Mock()
            inst.mock_rbd.ImageBusy = ImageBusy
            inst.mock_rbd.ImageNotFound = ImageNotFound

            inst.service.rbd = inst.mock_rbd
            inst.service.rados = inst.mock_rados

            with mock.patch.object(time, 'time') as mock_time:
                mock_time.side_effect = inst.time_inc
                with mock.patch.object(eventlet, 'sleep'):
                    # Mock Popen to raise Exception in order to ensure that any
                    # test ending up in a subprocess fails if not properly
                    # mocked.
                    with mock.patch.object(subprocess, 'Popen') as mock_popen:
                        mock_popen.side_effect = Exception
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
        for i in xrange(0, self.num_chunks):
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

    def tearDown(self):
        self.volume_file.close()
        super(BackupCephTestCase, self).tearDown()

    @common_mocks
    def test_get_rbd_support(self):

        # We need a blank class for this one.
        class mock_rbd(object):
            pass

        self.service.rbd = mock_rbd
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

        self.mock_rbd.Image.list_snaps = mock.Mock()
        self.mock_rbd.Image.list_snaps.return_value = \
            [{'name': 'backup.%s.snap.6423868.2342' % (uuid.uuid4())},
             {'name': 'backup.%s.snap.1321319.3235' % (uuid.uuid4())},
             {'name': last},
             {'name': 'backup.%s.snap.3824923.1412' % (uuid.uuid4())}]

        snap = self.service._get_most_recent_snap(self.service.rbd.Image())
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
        self.mock_rbd.Image.list_snaps = mock.Mock()
        self.mock_rbd.Image.list_snaps.return_value = \
            [{'name': 'backup.%s.snap.6423868.2342' % (uuid.uuid4())},
             {'name': 'backup.%s.wambam.6423868.2342' % (uuid.uuid4())},
             {'name': 'backup.%s.snap.1321319.3235' % (uuid.uuid4())},
             {'name': 'bbbackup.%s.snap.1321319.3235' % (uuid.uuid4())},
             {'name': 'backup.%s.snap.3824923.1412' % (uuid.uuid4())}]
        snaps = self.service.get_backup_snaps(self.service.rbd.Image())
        self.assertEqual(len(snaps), 3)

    @common_mocks
    @common_backup_mocks
    def test_transfer_data_from_rbd_to_file(self):
        self.mock_rbd.Image.read = mock.Mock()
        self.mock_rbd.Image.read.return_value = \
            self.volume_file.read(self.data_length)

        with tempfile.NamedTemporaryFile() as test_file:
            self.volume_file.seek(0)

            rbd_io = self._get_wrapped_rbd_io(self.service.rbd.Image())
            self.service._transfer_data(rbd_io, 'src_foo', test_file,
                                        'dest_foo', self.data_length)

            checksum = hashlib.sha256()
            test_file.seek(0)
            for c in xrange(0, self.num_chunks):
                checksum.update(test_file.read(self.chunk_size))

            # Ensure the files are equal
            self.assertEqual(checksum.digest(), self.checksum.digest())

    @common_mocks
    def test_transfer_data_from_rbd_to_rbd(self):

        def mock_write_data(data, offset):
            checksum.update(data)
            test_file.write(data)

        self.mock_rbd.Image.read = mock.Mock()
        self.mock_rbd.Image.read.return_value = \
            self.volume_file.read(self.data_length)

        self.mock_rbd.Image.size = mock.Mock()
        self.mock_rbd.Image.size.return_value = \
            self.chunk_size * self.num_chunks

        self.mock_rbd.Image.write = mock.Mock()
        self.mock_rbd.Image.write.side_effect = mock_write_data

        with tempfile.NamedTemporaryFile() as test_file:
            self.volume_file.seek(0)
            checksum = hashlib.sha256()

            rbd1 = self.service.rbd.Image()
            rbd2 = self.service.rbd.Image()

            src_rbd_io = self._get_wrapped_rbd_io(rbd1)
            dest_rbd_io = self._get_wrapped_rbd_io(rbd2)
            self.service._transfer_data(src_rbd_io, 'src_foo', dest_rbd_io,
                                        'dest_foo', self.data_length)

            # Ensure the files are equal
            self.assertEqual(checksum.digest(), self.checksum.digest())

    @common_mocks
    @common_backup_mocks
    def test_transfer_data_from_file_to_rbd(self):

        def mock_write_data(data, offset):
            checksum.update(data)
            test_file.write(data)

        self.mock_rbd.Image.write = mock.Mock()
        self.mock_rbd.Image.write.side_effect = mock_write_data

        with tempfile.NamedTemporaryFile() as test_file:
            self.volume_file.seek(0)
            checksum = hashlib.sha256()

            rbd_io = self._get_wrapped_rbd_io(self.service.rbd.Image())
            self.service._transfer_data(self.volume_file, 'src_foo',
                                        rbd_io, 'dest_foo', self.data_length)

            # Ensure the files are equal
            self.assertEqual(checksum.digest(), self.checksum.digest())

    @common_mocks
    @common_backup_mocks
    def test_transfer_data_from_file_to_file(self):
        with tempfile.NamedTemporaryFile() as test_file:
            self.volume_file.seek(0)
            checksum = hashlib.sha256()

            self.service._transfer_data(self.volume_file, 'src_foo', test_file,
                                        'dest_foo', self.data_length)

            checksum = hashlib.sha256()
            test_file.seek(0)
            for c in xrange(0, self.num_chunks):
                checksum.update(test_file.read(self.chunk_size))

            # Ensure the files are equal
            self.assertEqual(checksum.digest(), self.checksum.digest())

    @common_mocks
    @common_backup_mocks
    def test_backup_volume_from_file(self):

        def mock_write_data(data, offset):
            checksum.update(data)
            test_file.write(data)

        self.service.rbd.Image.write = mock.Mock()
        self.service.rbd.Image.write.side_effect = mock_write_data

        with mock.patch.object(self.service, '_discard_bytes'):
            with tempfile.NamedTemporaryFile() as test_file:
                checksum = hashlib.sha256()

                self.service.backup(self.backup, self.volume_file)

                # Ensure the files are equal
                self.assertEqual(checksum.digest(), self.checksum.digest())

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
    @common_backup_mocks
    @mock.patch('subprocess.Popen')
    def test_backup_volume_from_rbd(self, mock_popen):
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

        with mock.patch.object(fcntl, 'fcntl'):
            with mock.patch.object(self.service, '_discard_bytes'):
                with mock.patch.object(self.service, '_try_delete_base_image'):
                    with tempfile.NamedTemporaryFile() as test_file:
                        checksum = hashlib.sha256()
                        image = self.service.rbd.Image()
                        meta = rbddriver.RBDImageMetadata(image,
                                                          'pool_foo',
                                                          'user_foo',
                                                          'conf_foo')
                        rbd_io = rbddriver.RBDImageIOWrapper(meta)

                        self.service.backup(self.backup, rbd_io)

                        self.assertEqual(self.callstack, ['popen_init',
                                                          'read',
                                                          'popen_init',
                                                          'write',
                                                          'stdout_close',
                                                          'communicate'])

                        # Ensure the files are equal
                        self.assertEqual(checksum.digest(),
                                         self.checksum.digest())

    @common_mocks
    @common_backup_mocks
    def test_backup_vol_length_0(self):
        volume_id = str(uuid.uuid4())
        self._create_volume_db_entry(volume_id, 0)
        volume = db.volume_get(self.ctxt, volume_id)

        backup_id = str(uuid.uuid4())
        self._create_backup_db_entry(backup_id, volume_id, 1)
        backup = db.backup_get(self.ctxt, backup_id)

        self.assertRaises(exception.InvalidParameterValue, self.service.backup,
                          backup, self.volume_file)

    @common_mocks
    @common_restore_mocks
    def test_restore(self):
        backup_name = self.service._get_backup_base_name(self.backup_id,
                                                         diff_format=True)

        self.mock_rbd.RBD.list = mock.Mock()
        self.mock_rbd.RBD.list.return_value = [backup_name]

        def mock_read_data(offset, length):
            return self.volume_file.read(self.data_length)

        self.mock_rbd.Image.read = mock.Mock()
        self.mock_rbd.Image.read.side_effect = mock_read_data

        with mock.patch.object(self.service, '_discard_bytes'):
            with tempfile.NamedTemporaryFile() as test_file:
                self.volume_file.seek(0)

                self.service.restore(self.backup, self.volume_id, test_file)

                checksum = hashlib.sha256()
                test_file.seek(0)
                for c in xrange(0, self.num_chunks):
                    checksum.update(test_file.read(self.chunk_size))

                # Ensure the files are equal
                self.assertEqual(checksum.digest(), self.checksum.digest())

    @common_mocks
    def test_discard_bytes(self):
        self.mock_rbd.Image.discard = mock.Mock()
        wrapped_rbd = self._get_wrapped_rbd_io(self.mock_rbd.Image())

        self.service._discard_bytes(wrapped_rbd, 0, 0)
        self.assertEqual(self.mock_rbd.Image.discard.call_count, 0)

        self.service._discard_bytes(wrapped_rbd, 0, 1234)
        self.assertEqual(self.mock_rbd.Image.discard.call_count, 1)
        self.mock_rbd.Image.discard.reset_mock()

        self.mock_rbd.Image.write = mock.Mock()
        self.mock_rbd.Image.flush = mock.Mock()

        with mock.patch.object(self.service, '_file_is_rbd') as \
                mock_file_is_rbd:
            mock_file_is_rbd.return_value = False

            self.service._discard_bytes(wrapped_rbd, 0,
                                        self.service.chunk_size * 2)

            self.assertEqual(self.mock_rbd.Image.write.call_count, 2)
            self.assertEqual(self.mock_rbd.Image.flush.call_count, 2)
            self.assertFalse(self.mock_rbd.Image.discard.called)

        self.mock_rbd.Image.write.reset_mock()
        self.mock_rbd.Image.flush.reset_mock()

        with mock.patch.object(self.service, '_file_is_rbd') as \
                mock_file_is_rbd:
            mock_file_is_rbd.return_value = False

            self.service._discard_bytes(wrapped_rbd, 0,
                                        (self.service.chunk_size * 2) + 1)

            self.assertEqual(self.mock_rbd.Image.write.call_count, 3)
            self.assertEqual(self.mock_rbd.Image.flush.call_count, 3)
            self.assertFalse(self.mock_rbd.Image.discard.called)

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
    def test_try_delete_base_image_diff_format(self):
        backup_name = self.service._get_backup_base_name(self.volume_id,
                                                         diff_format=True)

        self.mock_rbd.RBD.list = mock.Mock()
        self.mock_rbd.RBD.list.return_value = [backup_name]
        self.mock_rbd.RBD.remove = mock.Mock()

        with mock.patch.object(self.service, '_delete_backup_snapshot') as \
                mock_del_backup_snap:
            snap_name = self.service._get_new_snap_name(self.backup_id)
            mock_del_backup_snap.return_value = (snap_name, 0)

            self.service.delete(self.backup)
            self.assertTrue(mock_del_backup_snap.called)

        #self.assertFalse(self.mock_rbd.ImageNotFound.called)
        self.assertTrue(self.mock_rbd.RBD.list.called)
        self.assertTrue(self.mock_rbd.RBD.remove.called)

    @common_mocks
    def test_try_delete_base_image(self):
        backup_name = self.service._get_backup_base_name(self.volume_id,
                                                         self.backup_id)

        self.mock_rbd.RBD.list = mock.Mock()
        self.mock_rbd.RBD.list.return_value = [backup_name]
        self.mock_rbd.RBD.remove = mock.Mock()

        with mock.patch.object(self.service, 'get_backup_snaps'):
            self.service.delete(self.backup)
            self.assertTrue(self.mock_rbd.RBD.remove.called)

    @common_mocks
    def test_try_delete_base_image_busy(self):
        """This should induce retries then raise rbd.ImageBusy."""
        backup_name = self.service._get_backup_base_name(self.volume_id,
                                                         self.backup_id)

        self.mock_rbd.RBD.list = mock.Mock()
        self.mock_rbd.RBD.list.return_value = [backup_name]
        self.mock_rbd.RBD.remove = mock.Mock()
        self.mock_rbd.RBD.remove.side_effect = self.mock_rbd.ImageBusy

        with mock.patch.object(self.service, 'get_backup_snaps'):
            self.assertRaises(self.mock_rbd.ImageBusy,
                              self.service._try_delete_base_image,
                              self.backup['id'], self.backup['volume_id'])

            self.assertTrue(self.mock_rbd.RBD.list.called)
            self.assertTrue(self.mock_rbd.RBD.remove.called)
            self.assertTrue(self.mock_rbd.ImageBusy.called())

    @common_mocks
    def test_delete(self):
        with mock.patch.object(self.service, '_try_delete_base_image'):
            self.service.delete(self.backup)
            self.assertFalse(self.mock_rbd.ImageNotFound.called())

    @common_mocks
    def test_delete_image_not_found(self):
        with mock.patch.object(self.service, '_try_delete_base_image') as \
                mock_del_base:
            mock_del_base.side_effect = self.mock_rbd.ImageNotFound
            # ImageNotFound exception is caught so that db entry can be cleared
            self.service.delete(self.backup)
            self.assertTrue(self.mock_rbd.ImageNotFound.called())

    @common_mocks
    def test_diff_restore_allowed_true(self):
        restore_point = 'restore.foo'
        is_allowed = (True, restore_point)

        rbd_io = self._get_wrapped_rbd_io(self.service.rbd.Image())

        self.mock_rbd.Image.size = mock.Mock()
        self.mock_rbd.Image.size.return_value = self.volume_size * units.GiB

        mpo = mock.patch.object
        with mpo(self.service, '_get_restore_point') as mock_restore_point:
            mock_restore_point.return_value = restore_point
            with mpo(self.service, '_rbd_has_extents') as mock_rbd_has_extents:
                mock_rbd_has_extents.return_value = False
                with mpo(self.service, '_rbd_image_exists') as \
                        mock_rbd_image_exists:
                    mock_rbd_image_exists.return_value = (True, 'foo')
                    with mpo(self.service, '_file_is_rbd') as \
                            mock_file_is_rbd:
                        mock_file_is_rbd.return_value = True

                        resp = \
                            self.service._diff_restore_allowed('foo',
                                                               self.backup,
                                                               self.alt_volume,
                                                               rbd_io,
                                                               self.mock_rados)

                        self.assertEqual(resp, is_allowed)
                        self.assertTrue(mock_restore_point.called)
                        self.assertTrue(mock_rbd_has_extents.called)
                        self.assertTrue(mock_rbd_image_exists.called)
                        self.assertTrue(mock_file_is_rbd.called)

    @common_mocks
    def test_diff_restore_allowed_false(self):
        not_allowed = (False, None)
        rbd_io = self._get_wrapped_rbd_io(self.service.rbd.Image())

        test_args = ['base_foo', self.backup, self.volume, rbd_io,
                     self.mock_rados]

        resp = self.service._diff_restore_allowed(*test_args)
        self.assertEqual(resp, not_allowed)

        test_args = ['base_foo', self.backup, self.alt_volume, rbd_io,
                     self.mock_rados]

        with mock.patch.object(self.service, '_file_is_rbd') as \
                mock_file_is_rbd:
            mock_file_is_rbd.return_value = False
            resp = self.service._diff_restore_allowed(*test_args)
            self.assertEqual(resp, not_allowed)
            self.assertTrue(mock_file_is_rbd.called)

        with mock.patch.object(self.service, '_file_is_rbd') as \
                mock_file_is_rbd:
            mock_file_is_rbd.return_value = True
            with mock.patch.object(self.service, '_rbd_image_exists') as \
                    mock_rbd_image_exists:
                mock_rbd_image_exists.return_value = False, None
                resp = self.service._diff_restore_allowed(*test_args)
                self.assertEqual(resp, not_allowed)
                self.assertTrue(mock_file_is_rbd.called)
                self.assertTrue(mock_rbd_image_exists.called)

        with mock.patch.object(self.service, '_file_is_rbd') as \
                mock_file_is_rbd:
            mock_file_is_rbd.return_value = True
            with mock.patch.object(self.service, '_rbd_image_exists') as \
                    mock_rbd_image_exists:
                mock_rbd_image_exists.return_value = True, None
                with mock.patch.object(self.service, '_get_restore_point') as \
                        mock_get_restore_point:
                    mock_get_restore_point.return_value = None

                    resp = self.service._diff_restore_allowed(*test_args)

                    self.assertEqual(resp, not_allowed)
                    self.assertTrue(mock_file_is_rbd.called)
                    self.assertTrue(mock_rbd_image_exists.called)
                    self.assertTrue(mock_get_restore_point.called)

        with mock.patch.object(self.service, '_file_is_rbd') as \
                mock_file_is_rbd:
            mock_file_is_rbd.return_value = True
            with mock.patch.object(self.service, '_rbd_image_exists') as \
                    mock_rbd_image_exists:
                mock_rbd_image_exists.return_value = True, None
                with mock.patch.object(self.service, '_get_restore_point') as \
                        mock_get_restore_point:
                    mock_get_restore_point.return_value = 'foo.restore_point'
                    with mock.patch.object(self.service, '_rbd_has_extents') \
                            as mock_rbd_has_extents:
                        mock_rbd_has_extents.return_value = True

                        resp = self.service._diff_restore_allowed(*test_args)

                        self.assertEqual(resp, (False, 'foo.restore_point'))
                        self.assertTrue(mock_file_is_rbd.called)
                        self.assertTrue(mock_rbd_image_exists.called)
                        self.assertTrue(mock_get_restore_point.called)
                        self.assertTrue(mock_rbd_has_extents.called)

    @common_mocks
    @mock.patch('subprocess.Popen')
    def test_piped_execute(self, mock_popen):
        with mock.patch.object(fcntl, 'fcntl') as mock_fcntl:
            mock_fcntl.return_value = 0
            self._setup_mock_popen(mock_popen, ['out', 'err'])
            self.service._piped_execute(['foo'], ['bar'])
            self.assertEqual(self.callstack, ['popen_init', 'popen_init',
                                              'stdout_close', 'communicate'])
