# Copyright (c) 2013 Scality
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
Unit tests for the Scality SOFS Volume Driver.
"""

import errno
import os
import shutil
import tempfile

import mox as mox_lib
from oslo_utils import units

from cinder import context
from cinder import exception
from cinder.image import image_utils
from cinder.openstack.common import fileutils
from cinder.openstack.common import imageutils
from cinder import test
from cinder import utils
from cinder.volume import configuration as conf
from cinder.volume.drivers import scality


class ScalityDriverTestCase(test.TestCase):
    """Test case for the Scality driver."""

    TEST_MOUNT = '/tmp/fake_mount'
    TEST_CONFIG = '/tmp/fake_config'
    TEST_VOLDIR = 'volumes'

    TEST_VOLNAME = 'volume_name'
    TEST_VOLSIZE = '1'
    TEST_VOLUME = {
        'name': TEST_VOLNAME,
        'size': TEST_VOLSIZE
    }
    TEST_VOLPATH = os.path.join(TEST_MOUNT,
                                TEST_VOLDIR,
                                TEST_VOLNAME)

    TEST_SNAPNAME = 'snapshot_name'
    TEST_SNAPSHOT = {
        'name': TEST_SNAPNAME,
        'volume_name': TEST_VOLNAME,
        'volume_size': TEST_VOLSIZE
    }
    TEST_SNAPPATH = os.path.join(TEST_MOUNT,
                                 TEST_VOLDIR,
                                 TEST_SNAPNAME)

    TEST_CLONENAME = 'clone_name'
    TEST_CLONE = {
        'name': TEST_CLONENAME,
        'size': TEST_VOLSIZE
    }

    TEST_NEWSIZE = '2'

    TEST_IMAGE_SERVICE = 'image_service'
    TEST_IMAGE_ID = 'image_id'
    TEST_IMAGE_META = 'image_meta'

    def _makedirs(self, path):
        try:
            os.makedirs(path)
        except OSError as e:
            if e.errno != errno.EEXIST:
                raise

    def _create_fake_config(self):
        open(self.TEST_CONFIG, "w+").close()

    def _create_fake_mount(self):
        self._makedirs(os.path.join(self.TEST_MOUNT, 'sys'))
        self._makedirs(os.path.join(self.TEST_MOUNT, self.TEST_VOLDIR))

    def _remove_fake_config(self):
        try:
            os.unlink(self.TEST_CONFIG)
        except OSError as e:
            if e.errno != errno.ENOENT:
                raise

    def _configure_driver(self):
        self.configuration.scality_sofs_config = self.TEST_CONFIG
        self.configuration.scality_sofs_mount_point = self.TEST_MOUNT
        self.configuration.scality_sofs_volume_dir = self.TEST_VOLDIR
        self.configuration.volume_dd_blocksize = '1M'

    def _execute_wrapper(self, cmd, *args, **kwargs):
        try:
            kwargs.pop('run_as_root')
        except KeyError:
            pass
        utils.execute(cmd, *args, **kwargs)

    def _set_access_wrapper(self, is_visible):

        def _access_wrapper(path, flags):
            if path == '/sbin/mount.sofs':
                return is_visible
            else:
                return os.access(path, flags)

        self.stubs.Set(os, 'access', _access_wrapper)

    def setUp(self):
        self.tempdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tempdir)

        self.TEST_MOUNT = self.tempdir
        self.TEST_VOLPATH = os.path.join(self.TEST_MOUNT,
                                         self.TEST_VOLDIR,
                                         self.TEST_VOLNAME)
        self.TEST_SNAPPATH = os.path.join(self.TEST_MOUNT,
                                          self.TEST_VOLDIR,
                                          self.TEST_SNAPNAME)
        self.TEST_CLONEPATH = os.path.join(self.TEST_MOUNT,
                                           self.TEST_VOLDIR,
                                           self.TEST_CLONENAME)

        self._mox = mox_lib.Mox()
        self.configuration = mox_lib.MockObject(conf.Configuration)
        self._configure_driver()
        super(ScalityDriverTestCase, self).setUp()

        self._driver = scality.ScalityDriver(configuration=self.configuration)
        self._driver.set_execute(self._execute_wrapper)
        self._create_fake_mount()
        self._create_fake_config()
        self.addCleanup(self._remove_fake_config)

    def test_setup_no_config(self):
        """Missing SOFS configuration shall raise an error."""
        self.configuration.scality_sofs_config = None
        self.assertRaises(exception.VolumeBackendAPIException,
                          self._driver.do_setup, None)

    def test_setup_missing_config(self):
        """Non-existent SOFS configuration file shall raise an error."""
        self.configuration.scality_sofs_config = 'nonexistent.conf'
        self.assertRaises(exception.VolumeBackendAPIException,
                          self._driver.do_setup, None)

    def test_setup_no_mount_helper(self):
        """SOFS must be installed to use the driver."""
        self._set_access_wrapper(False)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self._driver.do_setup, None)

    def test_setup_make_voldir(self):
        """The directory for volumes shall be created automatically."""
        self._set_access_wrapper(True)
        voldir_path = os.path.join(self.TEST_MOUNT, self.TEST_VOLDIR)
        os.rmdir(voldir_path)
        self._driver.do_setup(None)
        self.assertTrue(os.path.isdir(voldir_path))

    def test_local_path(self):
        """Expected behaviour for local_path."""
        self.assertEqual(self._driver.local_path(self.TEST_VOLUME),
                         self.TEST_VOLPATH)

    def test_create_volume(self):
        """Expected behaviour for create_volume."""
        ret = self._driver.create_volume(self.TEST_VOLUME)
        self.assertEqual(ret['provider_location'],
                         os.path.join(self.TEST_VOLDIR,
                                      self.TEST_VOLNAME))
        self.assertTrue(os.path.isfile(self.TEST_VOLPATH))
        self.assertEqual(os.stat(self.TEST_VOLPATH).st_size,
                         1 * units.Gi)

    def test_delete_volume(self):
        """Expected behaviour for delete_volume."""
        self._driver.create_volume(self.TEST_VOLUME)
        self._driver.delete_volume(self.TEST_VOLUME)
        self.assertFalse(os.path.isfile(self.TEST_VOLPATH))

    def test_create_snapshot(self):
        """Expected behaviour for create_snapshot."""
        mox = self._mox

        vol_size = self._driver._size_bytes(self.TEST_VOLSIZE)

        mox.StubOutWithMock(self._driver, '_create_file')
        self._driver._create_file(self.TEST_SNAPPATH, vol_size)
        mox.StubOutWithMock(self._driver, '_copy_file')
        self._driver._copy_file(self.TEST_VOLPATH, self.TEST_SNAPPATH)

        mox.ReplayAll()

        self._driver.create_snapshot(self.TEST_SNAPSHOT)

        mox.UnsetStubs()
        mox.VerifyAll()

    def test_delete_snapshot(self):
        """Expected behaviour for delete_snapshot."""
        mox = self._mox

        mox.StubOutWithMock(os, 'remove')
        os.remove(self.TEST_SNAPPATH)

        mox.ReplayAll()

        self._driver.delete_snapshot(self.TEST_SNAPSHOT)

        mox.UnsetStubs()
        mox.VerifyAll()

    def test_initialize_connection(self):
        """Expected behaviour for initialize_connection."""
        ret = self._driver.initialize_connection(self.TEST_VOLUME, None)
        self.assertEqual(ret['driver_volume_type'], 'scality')
        self.assertEqual(ret['data']['sofs_path'],
                         os.path.join(self.TEST_VOLDIR,
                                      self.TEST_VOLNAME))

    def test_copy_image_to_volume(self):
        """Expected behaviour for copy_image_to_volume."""
        self.mox.StubOutWithMock(image_utils, 'fetch_to_raw')

        image_utils.fetch_to_raw(context,
                                 self.TEST_IMAGE_SERVICE,
                                 self.TEST_IMAGE_ID,
                                 self.TEST_VOLPATH,
                                 mox_lib.IgnoreArg(),
                                 size=self.TEST_VOLSIZE)

        self.mox.ReplayAll()

        self._driver.copy_image_to_volume(context,
                                          self.TEST_VOLUME,
                                          self.TEST_IMAGE_SERVICE,
                                          self.TEST_IMAGE_ID)

    def test_copy_volume_to_image(self):
        """Expected behaviour for copy_volume_to_image."""
        self.mox.StubOutWithMock(image_utils, 'upload_volume')

        image_utils.upload_volume(context,
                                  self.TEST_IMAGE_SERVICE,
                                  self.TEST_IMAGE_META,
                                  self.TEST_VOLPATH)

        self.mox.ReplayAll()

        self._driver.copy_volume_to_image(context,
                                          self.TEST_VOLUME,
                                          self.TEST_IMAGE_SERVICE,
                                          self.TEST_IMAGE_META)

    def test_create_cloned_volume(self):
        """Expected behaviour for create_cloned_volume."""
        self.mox.StubOutWithMock(self._driver, '_create_file')
        self.mox.StubOutWithMock(self._driver, '_copy_file')

        vol_size = self._driver._size_bytes(self.TEST_VOLSIZE)
        self._driver._create_file(self.TEST_CLONEPATH, vol_size)
        self._driver._copy_file(self.TEST_VOLPATH, self.TEST_CLONEPATH)

        self.mox.ReplayAll()

        self._driver.create_cloned_volume(self.TEST_CLONE, self.TEST_VOLUME)

    def test_extend_volume(self):
        """Expected behaviour for extend_volume."""
        self.mox.StubOutWithMock(self._driver, '_create_file')

        new_size = self._driver._size_bytes(self.TEST_NEWSIZE)
        self._driver._create_file(self.TEST_VOLPATH, new_size)

        self.mox.ReplayAll()

        self._driver.extend_volume(self.TEST_VOLUME, self.TEST_NEWSIZE)

    def test_backup_volume(self):
        self.mox.StubOutWithMock(self._driver, 'db')
        self.mox.StubOutWithMock(self._driver.db, 'volume_get')

        volume = {'id': '2', 'name': self.TEST_VOLNAME}
        self._driver.db.volume_get(context, volume['id']).AndReturn(volume)

        info = imageutils.QemuImgInfo()
        info.file_format = 'raw'
        self.mox.StubOutWithMock(image_utils, 'qemu_img_info')
        image_utils.qemu_img_info(self.TEST_VOLPATH).AndReturn(info)

        self.mox.StubOutWithMock(utils, 'temporary_chown')
        mock_tempchown = self.mox.CreateMockAnything()
        utils.temporary_chown(self.TEST_VOLPATH).AndReturn(mock_tempchown)
        mock_tempchown.__enter__()
        mock_tempchown.__exit__(None, None, None)

        self.mox.StubOutWithMock(fileutils, 'file_open')
        mock_fileopen = self.mox.CreateMockAnything()
        fileutils.file_open(self.TEST_VOLPATH).AndReturn(mock_fileopen)
        mock_fileopen.__enter__()
        mock_fileopen.__exit__(None, None, None)

        backup = {'volume_id': volume['id']}
        mock_servicebackup = self.mox.CreateMockAnything()
        mock_servicebackup.backup(backup, mox_lib.IgnoreArg())

        self.mox.ReplayAll()
        self._driver.backup_volume(context, backup, mock_servicebackup)
        self.mox.VerifyAll()

    def test_restore_backup(self):
        volume = {'id': '2', 'name': self.TEST_VOLNAME}

        self.mox.StubOutWithMock(utils, 'temporary_chown')
        mock_tempchown = self.mox.CreateMockAnything()
        utils.temporary_chown(self.TEST_VOLPATH).AndReturn(mock_tempchown)
        mock_tempchown.__enter__()
        mock_tempchown.__exit__(None, None, None)

        self.mox.StubOutWithMock(fileutils, 'file_open')
        mock_fileopen = self.mox.CreateMockAnything()
        fileutils.file_open(self.TEST_VOLPATH, 'wb').AndReturn(mock_fileopen)
        mock_fileopen.__enter__()
        mock_fileopen.__exit__(None, None, None)

        backup = {'id': 123, 'volume_id': volume['id']}
        mock_servicebackup = self.mox.CreateMockAnything()
        mock_servicebackup.restore(backup, volume['id'], mox_lib.IgnoreArg())

        self.mox.ReplayAll()
        self._driver.restore_backup(context, backup, volume,
                                    mock_servicebackup)
        self.mox.VerifyAll()
