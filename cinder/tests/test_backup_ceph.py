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
import time
import uuid

import eventlet

from cinder.backup.drivers import ceph
from cinder import context
from cinder import db
from cinder import exception
from cinder.openstack.common import log as logging
from cinder.openstack.common import processutils
from cinder import test
from cinder.tests.backup.fake_rados import mock_rados
from cinder.tests.backup.fake_rados import mock_rbd
from cinder import units
from cinder.volume.drivers import rbd as rbddriver

LOG = logging.getLogger(__name__)


class BackupCephTestCase(test.TestCase):
    """Test Case for backup to Ceph object store"""

    def _create_volume_db_entry(self, id, size):
        vol = {'id': id, 'size': size, 'status': 'available'}
        return db.volume_create(self.ctxt, vol)['id']

    def _create_backup_db_entry(self, backupid, volid, size):
        backup = {'id': backupid, 'size': size, 'volume_id': volid}
        return db.backup_create(self.ctxt, backup)['id']

    def fake_execute_w_exception(*args, **kwargs):
        raise processutils.ProcessExecutionError()

    def time_inc(self):
        self.counter += 1
        return self.counter

    def _get_wrapped_rbd_io(self, rbd_image):
        rbd_meta = rbddriver.RBDImageMetadata(rbd_image, 'pool_foo',
                                              'user_foo', 'conf_foo')
        return rbddriver.RBDImageIOWrapper(rbd_meta)

    def setUp(self):
        super(BackupCephTestCase, self).setUp()
        self.ctxt = context.get_admin_context()

        self.volume_id = str(uuid.uuid4())
        self.backup_id = str(uuid.uuid4())

        # Setup librbd stubs
        self.stubs.Set(ceph, 'rados', mock_rados)
        self.stubs.Set(ceph, 'rbd', mock_rbd)

        self._create_backup_db_entry(self.backup_id, self.volume_id, 1)

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

        # Always trigger an exception if a command is executed since it should
        # always be dealt with gracefully. At time of writing on rbd
        # export/import-diff is executed and if they fail we expect to find
        # alternative means of backing up.
        fake_exec = self.fake_execute_w_exception
        self.service = ceph.CephBackupDriver(self.ctxt, execute=fake_exec)

        # Ensure that time.time() always returns more than the last time it was
        # called to avoid div by zero errors.
        self.counter = float(0)
        self.stubs.Set(time, 'time', self.time_inc)
        self.stubs.Set(eventlet, 'sleep', lambda *args: None)

    def test_get_rbd_support(self):
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

    def _set_common_backup_stubs(self, service):
        self.stubs.Set(self.service, '_get_rbd_support', lambda: (True, 3))
        self.stubs.Set(self.service, 'get_backup_snaps',
                       lambda *args, **kwargs: None)

        def rbd_size(inst):
            return self.chunk_size * self.num_chunks

        self.stubs.Set(self.service.rbd.Image, 'size', rbd_size)

    def _set_common_restore_stubs(self, service):
        self._set_common_backup_stubs(self.service)

        def rbd_size(inst):
            return self.chunk_size * self.num_chunks

        self.stubs.Set(self.service.rbd.Image, 'size', rbd_size)

    def test_get_most_recent_snap(self):
        last = 'backup.%s.snap.9824923.1212' % (uuid.uuid4())

        def list_snaps(inst, *args):
            return [{'name': 'backup.%s.snap.6423868.2342' % (uuid.uuid4())},
                    {'name': 'backup.%s.snap.1321319.3235' % (uuid.uuid4())},
                    {'name': last},
                    {'name': 'backup.%s.snap.3824923.1412' % (uuid.uuid4())}]

        self.stubs.Set(self.service.rbd.Image, 'list_snaps', list_snaps)

        snap = self.service._get_most_recent_snap(self.service.rbd.Image())

        self.assertEqual(last, snap)

    def test_get_backup_snap_name(self):
        snap_name = 'backup.%s.snap.3824923.1412' % (uuid.uuid4())

        def mock_get_backup_snaps(inst, *args):
            return [{'name': 'backup.%s.snap.6423868.2342' % (uuid.uuid4()),
                     'backup_id': str(uuid.uuid4())},
                    {'name': snap_name,
                     'backup_id': self.backup_id}]

        self.stubs.Set(self.service, 'get_backup_snaps', lambda *args: None)
        name = self.service._get_backup_snap_name(self.service.rbd.Image(),
                                                  'base_foo',
                                                  self.backup_id)
        self.assertIsNone(name)

        self.stubs.Set(self.service, 'get_backup_snaps', mock_get_backup_snaps)
        name = self.service._get_backup_snap_name(self.service.rbd.Image(),
                                                  'base_foo',
                                                  self.backup_id)
        self.assertEqual(name, snap_name)

    def test_get_backup_snaps(self):

        def list_snaps(inst, *args):
            return [{'name': 'backup.%s.snap.6423868.2342' % (uuid.uuid4())},
                    {'name': 'backup.%s.wambam.6423868.2342' % (uuid.uuid4())},
                    {'name': 'backup.%s.snap.1321319.3235' % (uuid.uuid4())},
                    {'name': 'bbbackup.%s.snap.1321319.3235' % (uuid.uuid4())},
                    {'name': 'backup.%s.snap.3824923.1412' % (uuid.uuid4())}]

        self.stubs.Set(self.service.rbd.Image, 'list_snaps', list_snaps)
        snaps = self.service.get_backup_snaps(self.service.rbd.Image())
        self.assertTrue(len(snaps) == 3)

    def test_transfer_data_from_rbd_to_file(self):
        self._set_common_backup_stubs(self.service)

        with tempfile.NamedTemporaryFile() as test_file:
            self.volume_file.seek(0)

            def read_data(inst, offset, length):
                return self.volume_file.read(self.length)

            self.stubs.Set(self.service.rbd.Image, 'read', read_data)

            rbd_io = self._get_wrapped_rbd_io(self.service.rbd.Image())
            self.service._transfer_data(rbd_io, 'src_foo', test_file,
                                        'dest_foo', self.length)

            checksum = hashlib.sha256()
            test_file.seek(0)
            for c in xrange(0, self.num_chunks):
                checksum.update(test_file.read(self.chunk_size))

            # Ensure the files are equal
            self.assertEqual(checksum.digest(), self.checksum.digest())

    def test_transfer_data_from_rbd_to_rbd(self):
        def rbd_size(inst):
            return self.chunk_size * self.num_chunks

        with tempfile.NamedTemporaryFile() as test_file:
            self.volume_file.seek(0)
            checksum = hashlib.sha256()

            def read_data(inst, offset, length):
                return self.volume_file.read(self.length)

            def write_data(inst, data, offset):
                checksum.update(data)
                test_file.write(data)

            self.stubs.Set(self.service.rbd.Image, 'read', read_data)
            self.stubs.Set(self.service.rbd.Image, 'size', rbd_size)
            self.stubs.Set(self.service.rbd.Image, 'write', write_data)

            rbd1 = self.service.rbd.Image()
            rbd2 = self.service.rbd.Image()

            src_rbd_io = self._get_wrapped_rbd_io(rbd1)
            dest_rbd_io = self._get_wrapped_rbd_io(rbd2)
            self.service._transfer_data(src_rbd_io, 'src_foo', dest_rbd_io,
                                        'dest_foo', self.length)

            # Ensure the files are equal
            self.assertEqual(checksum.digest(), self.checksum.digest())

    def test_transfer_data_from_file_to_rbd(self):
        self._set_common_backup_stubs(self.service)

        with tempfile.NamedTemporaryFile() as test_file:
            self.volume_file.seek(0)
            checksum = hashlib.sha256()

            def write_data(inst, data, offset):
                checksum.update(data)
                test_file.write(data)

            self.stubs.Set(self.service.rbd.Image, 'write', write_data)

            rbd_io = self._get_wrapped_rbd_io(self.service.rbd.Image())
            self.service._transfer_data(self.volume_file, 'src_foo',
                                        rbd_io, 'dest_foo', self.length)

            # Ensure the files are equal
            self.assertEqual(checksum.digest(), self.checksum.digest())

    def test_transfer_data_from_file_to_file(self):
        self._set_common_backup_stubs(self.service)

        with tempfile.NamedTemporaryFile() as test_file:
            self.volume_file.seek(0)
            checksum = hashlib.sha256()

            self.service._transfer_data(self.volume_file, 'src_foo', test_file,
                                        'dest_foo', self.length)

            checksum = hashlib.sha256()
            test_file.seek(0)
            for c in xrange(0, self.num_chunks):
                checksum.update(test_file.read(self.chunk_size))

            # Ensure the files are equal
            self.assertEqual(checksum.digest(), self.checksum.digest())

    def test_backup_volume_from_file(self):
        self._create_volume_db_entry(self.volume_id, 1)
        backup = db.backup_get(self.ctxt, self.backup_id)

        self._set_common_backup_stubs(self.service)

        with tempfile.NamedTemporaryFile() as test_file:
            checksum = hashlib.sha256()

            def write_data(inst, data, offset):
                checksum.update(data)
                test_file.write(data)

            self.stubs.Set(self.service.rbd.Image, 'write', write_data)

            self.stubs.Set(self.service, '_discard_bytes',
                           lambda *args: None)

            self.service.backup(backup, self.volume_file)

            # Ensure the files are equal
            self.assertEqual(checksum.digest(), self.checksum.digest())

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

    def test_backup_volume_from_rbd(self):
        self._create_volume_db_entry(self.volume_id, 1)
        backup = db.backup_get(self.ctxt, self.backup_id)

        self._set_common_backup_stubs(self.service)

        backup_name = self.service._get_backup_base_name(self.backup_id,
                                                         diff_format=True)

        self.stubs.Set(self.service, '_try_delete_base_image',
                       lambda *args, **kwargs: None)

        with tempfile.NamedTemporaryFile() as test_file:
            checksum = hashlib.sha256()

            def write_data(inst, data, offset):
                checksum.update(data)
                test_file.write(data)

            def read_data(inst, offset, length):
                return self.volume_file.read(self.length)

            def rbd_list(inst, ioctx):
                return [backup_name]

            self.stubs.Set(self.service.rbd.Image, 'read', read_data)
            self.stubs.Set(self.service.rbd.Image, 'write', write_data)
            self.stubs.Set(self.service.rbd.RBD, 'list', rbd_list)

            self.stubs.Set(self.service, '_discard_bytes',
                           lambda *args: None)

            meta = rbddriver.RBDImageMetadata(self.service.rbd.Image(),
                                              'pool_foo', 'user_foo',
                                              'conf_foo')
            rbd_io = rbddriver.RBDImageIOWrapper(meta)

            self.service.backup(backup, rbd_io)

            # Ensure the files are equal
            self.assertEqual(checksum.digest(), self.checksum.digest())

    def test_backup_vol_length_0(self):
        self._set_common_backup_stubs(self.service)

        backup = db.backup_get(self.ctxt, self.backup_id)
        self._create_volume_db_entry(self.volume_id, 0)
        self.assertRaises(exception.InvalidParameterValue, self.service.backup,
                          backup, self.volume_file)

    def test_restore(self):
        self._create_volume_db_entry(self.volume_id, 1)
        backup = db.backup_get(self.ctxt, self.backup_id)

        self._set_common_restore_stubs(self.service)

        backup_name = self.service._get_backup_base_name(self.backup_id,
                                                         diff_format=True)

        def rbd_list(inst, ioctx):
            return [backup_name]

        self.stubs.Set(self.service.rbd.RBD, 'list', rbd_list)

        self.stubs.Set(self.service, '_discard_bytes', lambda *args: None)

        with tempfile.NamedTemporaryFile() as test_file:
            self.volume_file.seek(0)

            def read_data(inst, offset, length):
                return self.volume_file.read(self.length)

            self.stubs.Set(self.service.rbd.Image, 'read', read_data)

            self.service.restore(backup, self.volume_id, test_file)

            checksum = hashlib.sha256()
            test_file.seek(0)
            for c in xrange(0, self.num_chunks):
                checksum.update(test_file.read(self.chunk_size))

            # Ensure the files are equal
            self.assertEqual(checksum.digest(), self.checksum.digest())

    def test_discard_bytes(self):
        self.service._discard_bytes(mock_rbd(), 123456, 0)
        calls = []

        def _setter(*args, **kwargs):
            calls.append(True)

        self.stubs.Set(self.service.rbd.Image, 'discard', _setter)

        self.service._discard_bytes(mock_rbd(), 123456, 0)
        self.assertTrue(len(calls) == 0)

        image = mock_rbd().Image()
        wrapped_rbd = self._get_wrapped_rbd_io(image)
        self.service._discard_bytes(wrapped_rbd, 123456, 1234)
        self.assertTrue(len(calls) == 1)

        self.stubs.Set(image, 'write', _setter)
        wrapped_rbd = self._get_wrapped_rbd_io(image)
        self.stubs.Set(self.service, '_file_is_rbd',
                       lambda *args: False)
        self.service._discard_bytes(wrapped_rbd, 0,
                                    self.service.chunk_size * 2)
        self.assertTrue(len(calls) == 3)

    def test_delete_backup_snapshot(self):
        snap_name = 'backup.%s.snap.3824923.1412' % (uuid.uuid4())
        base_name = self.service._get_backup_base_name(self.volume_id,
                                                       diff_format=True)

        self.stubs.Set(self.service, '_get_backup_snap_name',
                       lambda *args: snap_name)

        self.stubs.Set(self.service, 'get_backup_snaps',
                       lambda *args: None)

        rem = self.service._delete_backup_snapshot(mock_rados(), base_name,
                                                   self.backup_id)

        self.assertEqual(rem, (snap_name, 0))

    def test_try_delete_base_image_diff_format(self):
        # don't create volume db entry since it should not be required
        backup = db.backup_get(self.ctxt, self.backup_id)

        backup_name = self.service._get_backup_base_name(self.volume_id,
                                                         diff_format=True)

        snap_name = self.service._get_new_snap_name(self.backup_id)
        snaps = [{'name': snap_name}]

        def rbd_list(*args):
            return [backup_name]

        def list_snaps(*args):
            return snaps

        def remove_snap(*args):
            snaps.pop()

        self.stubs.Set(self.service.rbd.Image, 'remove_snap', remove_snap)
        self.stubs.Set(self.service.rbd.Image, 'list_snaps', list_snaps)
        self.stubs.Set(self.service.rbd.RBD, 'list', rbd_list)

        # Must be something mutable
        remove_called = []

        def remove(inst, ioctx, name):
            remove_called.append(True)

        self.stubs.Set(self.service.rbd.RBD, 'remove', remove)
        self.service.delete(backup)
        self.assertTrue(remove_called[0])

    def test_try_delete_base_image(self):
        # don't create volume db entry since it should not be required
        self._create_volume_db_entry(self.volume_id, 1)
        backup = db.backup_get(self.ctxt, self.backup_id)

        backup_name = self.service._get_backup_base_name(self.volume_id,
                                                         self.backup_id)

        def rbd_list(inst, ioctx):
            return [backup_name]

        self.stubs.Set(self.service.rbd.RBD, 'list', rbd_list)

        # Must be something mutable
        remove_called = []

        self.stubs.Set(self.service, 'get_backup_snaps',
                       lambda *args, **kwargs: None)

        def remove(inst, ioctx, name):
            remove_called.append(True)

        self.stubs.Set(self.service.rbd.RBD, 'remove', remove)
        self.service.delete(backup)
        self.assertTrue(remove_called[0])

    def test_try_delete_base_image_busy(self):
        """This should induce retries then raise rbd.ImageBusy."""
        # don't create volume db entry since it should not be required
        self._create_volume_db_entry(self.volume_id, 1)
        backup = db.backup_get(self.ctxt, self.backup_id)

        backup_name = self.service._get_backup_base_name(self.volume_id,
                                                         self.backup_id)

        def rbd_list(inst, ioctx):
            return [backup_name]

        self.stubs.Set(self.service.rbd.RBD, 'list', rbd_list)

        # Must be something mutable
        remove_called = []

        self.stubs.Set(self.service, 'get_backup_snaps',
                       lambda *args, **kwargs: None)

        def remove(inst, ioctx, name):
            raise self.service.rbd.ImageBusy("image busy")

        self.stubs.Set(self.service.rbd.RBD, 'remove', remove)

        self.assertRaises(self.service.rbd.ImageBusy,
                          self.service._try_delete_base_image,
                          backup['id'], backup['volume_id'])

    def test_delete(self):
        backup = db.backup_get(self.ctxt, self.backup_id)

        def del_base_image(*args):
            pass

        self.stubs.Set(self.service, '_try_delete_base_image',
                       lambda *args: None)

        self.service.delete(backup)

    def test_delete_image_not_found(self):
        backup = db.backup_get(self.ctxt, self.backup_id)

        def del_base_image(*args):
            raise self.service.rbd.ImageNotFound

        self.stubs.Set(self.service, '_try_delete_base_image',
                       lambda *args: None)

        # ImageNotFound exception is caught so that db entry can be cleared
        self.service.delete(backup)

    def test_diff_restore_allowed_true(self):
        restore_point = 'restore.foo'
        is_allowed = (True, restore_point)
        backup = db.backup_get(self.ctxt, self.backup_id)
        alt_volume_id = str(uuid.uuid4())
        volume_size = 1
        self._create_volume_db_entry(alt_volume_id, volume_size)
        alt_volume = db.volume_get(self.ctxt, alt_volume_id)
        rbd_io = self._get_wrapped_rbd_io(self.service.rbd.Image())

        self.stubs.Set(self.service, '_get_restore_point',
                       lambda *args: restore_point)
        self.stubs.Set(self.service, '_rbd_has_extents',
                       lambda *args: False)
        self.stubs.Set(self.service, '_rbd_image_exists',
                       lambda *args: (True, 'foo'))
        self.stubs.Set(self.service, '_file_is_rbd',
                       lambda *args: True)
        self.stubs.Set(self.service.rbd.Image, 'size',
                       lambda *args: volume_size * units.GiB)

        resp = self.service._diff_restore_allowed('foo', backup, alt_volume,
                                                  rbd_io, mock_rados())
        self.assertEqual(resp, is_allowed)

    def _set_service_stub(self, method, retval):
        self.stubs.Set(self.service, method, lambda *args, **kwargs: retval)

    def test_diff_restore_allowed_false(self):
        volume_size = 1
        not_allowed = (False, None)
        backup = db.backup_get(self.ctxt, self.backup_id)
        self._create_volume_db_entry(self.volume_id, volume_size)
        original_volume = db.volume_get(self.ctxt, self.volume_id)
        rbd_io = self._get_wrapped_rbd_io(self.service.rbd.Image())

        test_args = 'foo', backup, original_volume, rbd_io, mock_rados()

        self._set_service_stub('_get_restore_point', None)
        resp = self.service._diff_restore_allowed(*test_args)
        self.assertEqual(resp, not_allowed)
        self._set_service_stub('_get_restore_point', 'restore.foo')

        self._set_service_stub('_rbd_has_extents', True)
        resp = self.service._diff_restore_allowed(*test_args)
        self.assertEqual(resp, not_allowed)
        self._set_service_stub('_rbd_has_extents', False)

        self._set_service_stub('_rbd_image_exists', (False, 'foo'))
        resp = self.service._diff_restore_allowed(*test_args)
        self.assertEqual(resp, not_allowed)
        self._set_service_stub('_rbd_image_exists', None)

        self.stubs.Set(self.service.rbd.Image, 'size',
                       lambda *args, **kwargs: volume_size * units.GiB * 2)
        resp = self.service._diff_restore_allowed(*test_args)
        self.assertEqual(resp, not_allowed)
        self.stubs.Set(self.service.rbd.Image, 'size',
                       lambda *args, **kwargs: volume_size * units.GiB)

        self._set_service_stub('_file_is_rbd', False)
        resp = self.service._diff_restore_allowed(*test_args)
        self.assertEqual(resp, not_allowed)
        self._set_service_stub('_file_is_rbd', True)

    def tearDown(self):
        self.volume_file.close()
        self.stubs.UnsetAll()
        super(BackupCephTestCase, self).tearDown()
