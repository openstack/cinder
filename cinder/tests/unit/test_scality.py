# Copyright (c) 2015 Scality
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
Unit tests for the Scality SOFS Volume Driver.
"""
import errno
import os

import mock
from six.moves import urllib

from cinder import context
from cinder import exception
from cinder.openstack.common import imageutils
from cinder import test
from cinder.volume import configuration as conf
import cinder.volume.drivers.scality as driver

_FAKE_VOLUME = {'name': 'volume-a79d463e-1fd5-11e5-a6ff-5b81bfee8544',
                'id': 'a79d463e-1fd5-11e5-a6ff-5b81bfee8544',
                'provider_location': 'fake_share'}
_FAKE_SNAPSHOT = {'id': 'ae3d6da2-1fd5-11e5-967f-1b8cf3b401ab',
                  'volume': _FAKE_VOLUME,
                  'status': 'available',
                  'provider_location': None,
                  'volume_size': 1,
                  'name': 'snapshot-ae3d6da2-1fd5-11e5-967f-1b8cf3b401ab'}
_FAKE_BACKUP = {'id': '914849d2-2585-11e5-be54-d70ca0c343d6',
                'volume_id': _FAKE_VOLUME['id']}

_FAKE_MNT_POINT = '/tmp'
_FAKE_SOFS_CONFIG = '/etc/sfused.conf'
_FAKE_VOLUME_DIR = 'cinder/volumes'
_FAKE_VOL_BASEDIR = os.path.join(_FAKE_MNT_POINT, _FAKE_VOLUME_DIR, '00')
_FAKE_VOL_PATH = os.path.join(_FAKE_VOL_BASEDIR, _FAKE_VOLUME['name'])
_FAKE_SNAP_PATH = os.path.join(_FAKE_VOL_BASEDIR, _FAKE_SNAPSHOT['name'])

_FAKE_MOUNTS_TABLE = [['tmpfs /dev/shm\n'],
                      ['fuse ' + _FAKE_MNT_POINT + '\n']]


class ScalityDriverTestCase(test.TestCase):
    """Test case for the Scality driver."""

    def setUp(self):
        super(ScalityDriverTestCase, self).setUp()

        self.cfg = mock.Mock(spec=conf.Configuration)
        self.cfg.scality_sofs_mount_point = _FAKE_MNT_POINT
        self.cfg.scality_sofs_config = _FAKE_SOFS_CONFIG
        self.cfg.scality_sofs_volume_dir = _FAKE_VOLUME_DIR

        self.drv = driver.ScalityDriver(configuration=self.cfg)
        self.drv.db = mock.Mock()

    @mock.patch.object(driver.urllib.request, 'urlopen')
    @mock.patch('os.access')
    def test_check_for_setup_error(self, mock_os_access, mock_urlopen):
        self.drv.check_for_setup_error()

        mock_urlopen.assert_called_once_with('file://%s' % _FAKE_SOFS_CONFIG,
                                             timeout=5)
        mock_os_access.assert_called_once_with('/sbin/mount.sofs', os.X_OK)

    def test_check_for_setup_error_with_no_sofs_config(self):
        self.cfg.scality_sofs_config = ''

        self.drv = driver.ScalityDriver(configuration=self.cfg)

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.drv.check_for_setup_error)
        exec_patcher = mock.patch.object(self.drv, '_execute',
                                         mock.MagicMock())
        exec_patcher.start()
        self.addCleanup(exec_patcher.stop)

    @mock.patch.object(driver.urllib.request, 'urlopen')
    def test_check_for_setup_error_with_urlerror(self, mock_urlopen):
        # Add a Unicode char to be sure that the exception is properly
        # handled even if it contains Unicode chars
        mock_urlopen.side_effect = urllib.error.URLError(u'\u9535')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.drv.check_for_setup_error)

    @mock.patch.object(driver.urllib.request, 'urlopen')
    def test_check_for_setup_error_with_httperror(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.HTTPError(*[None] * 5)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.drv.check_for_setup_error)

    @mock.patch.object(driver.urllib.request, 'urlopen', mock.Mock())
    @mock.patch('os.access')
    def test_check_for_setup_error_with_no_mountsofs(self, mock_os_access):
        mock_os_access.return_value = False
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.drv.check_for_setup_error)
        mock_os_access.assert_called_once_with('/sbin/mount.sofs', os.X_OK)

    def test_load_shares_config(self):
        self.assertEqual({}, self.drv.shares)
        self.drv._load_shares_config()
        self.assertEqual({_FAKE_VOLUME_DIR: None}, self.drv.shares)

    def test_get_mount_point_for_share(self):
        self.assertEqual(_FAKE_VOL_BASEDIR,
                         self.drv._get_mount_point_for_share())

    @mock.patch("cinder.volume.utils.read_proc_mounts")
    @mock.patch("oslo_concurrency.processutils.execute")
    def test_ensure_share_mounted_when_mount_failed(self, mock_execute,
                                                    mock_read_proc_mounts):
        mock_read_proc_mounts.return_value = ['tmpfs /dev/shm\n']
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.drv._ensure_share_mounted)
        self.assertEqual(2, mock_read_proc_mounts.call_count)
        self.assertEqual(1, mock_execute.call_count)

    @mock.patch("cinder.volume.utils.read_proc_mounts")
    @mock.patch("oslo_concurrency.processutils.execute")
    @mock.patch("oslo_utils.fileutils.ensure_tree")
    @mock.patch("os.symlink")
    def test_ensure_shares_mounted(self, mock_symlink, mock_ensure_tree,
                                   mock_execute, mock_read_proc_mounts):
        self.assertEqual([], self.drv._mounted_shares)

        mock_read_proc_mounts.side_effect = _FAKE_MOUNTS_TABLE

        self.drv._ensure_shares_mounted()

        self.assertEqual([_FAKE_VOLUME_DIR], self.drv._mounted_shares)
        self.assertEqual(2, mock_read_proc_mounts.call_count)
        mock_symlink.assert_called_once_with('.', _FAKE_VOL_BASEDIR)
        self.assertEqual(2, mock_ensure_tree.call_count)
        self.assertEqual(1, mock_execute.call_count)
        expected_args = ('mount', '-t', 'sofs', _FAKE_SOFS_CONFIG,
                         _FAKE_MNT_POINT)
        self.assertEqual(expected_args, mock_execute.call_args[0])

    def test_find_share_when_no_shares_mounted(self):
        self.assertRaises(exception.RemoteFSNoSharesMounted,
                          self.drv._find_share, 'ignored')

    @mock.patch("cinder.volume.utils.read_proc_mounts")
    @mock.patch("oslo_concurrency.processutils.execute")
    @mock.patch("oslo_utils.fileutils.ensure_tree")
    @mock.patch("os.symlink")
    def test_find_share(self, mock_symlink, mock_ensure_tree, mock_execute,
                        mock_read_proc_mounts):
        mock_read_proc_mounts.side_effect = _FAKE_MOUNTS_TABLE

        self.drv._ensure_shares_mounted()

        self.assertEqual(_FAKE_VOLUME_DIR, self.drv._find_share('ignored'))
        self.assertEqual(2, mock_read_proc_mounts.call_count)
        self.assertEqual(1, mock_execute.call_count)

        expected_args = ('mount', '-t', 'sofs', _FAKE_SOFS_CONFIG,
                         _FAKE_MNT_POINT)
        self.assertEqual(expected_args, mock_execute.call_args[0])

        mock_symlink.assert_called_once_with('.', _FAKE_VOL_BASEDIR)

        self.assertEqual(mock_ensure_tree.call_args_list,
                         [mock.call(_FAKE_MNT_POINT),
                          mock.call(os.path.join(_FAKE_MNT_POINT,
                                                 _FAKE_VOLUME_DIR))])

    def test_get_volume_stats(self):
        with mock.patch.object(self.cfg, 'safe_get') as mock_safe_get:
            mock_safe_get.return_value = 'fake_backend_name'
            stats = self.drv.get_volume_stats()
        self.assertEqual(self.drv.VERSION, stats['driver_version'])
        self.assertEqual(mock_safe_get.return_value,
                         stats['volume_backend_name'])
        mock_safe_get.assert_called_once_with('volume_backend_name')

    @mock.patch("cinder.image.image_utils.qemu_img_info")
    def test_initialize_connection(self, mock_qemu_img_info):
        info = imageutils.QemuImgInfo()
        info.file_format = 'raw'
        info.image = _FAKE_VOLUME['name']
        mock_qemu_img_info.return_value = info

        with mock.patch.object(self.drv, 'get_active_image_from_info') as \
                mock_get_active_image_from_info:

            mock_get_active_image_from_info.return_value = _FAKE_VOLUME['name']
            conn_info = self.drv.initialize_connection(_FAKE_VOLUME, None)

        expected_conn_info = {
            'driver_volume_type': driver.ScalityDriver.driver_volume_type,
            'mount_point_base': _FAKE_MNT_POINT,
            'data': {
                'export': _FAKE_VOLUME['provider_location'],
                'name': _FAKE_VOLUME['name'],
                'sofs_path': 'cinder/volumes/00/' + _FAKE_VOLUME['name'],
                'format': 'raw'
            }
        }
        self.assertEqual(expected_conn_info, conn_info)
        mock_get_active_image_from_info.assert_called_once_with(_FAKE_VOLUME)
        mock_qemu_img_info.assert_called_once_with(_FAKE_VOL_PATH)

    @mock.patch("cinder.image.image_utils.resize_image")
    @mock.patch("cinder.image.image_utils.qemu_img_info")
    def test_extend_volume(self, mock_qemu_img_info, mock_resize_image):
        info = imageutils.QemuImgInfo()
        info.file_format = 'raw'
        mock_qemu_img_info.return_value = info

        self.drv.extend_volume(_FAKE_VOLUME, 2)

        mock_qemu_img_info.assert_called_once_with(_FAKE_VOL_PATH)

        mock_resize_image.assert_called_once_with(_FAKE_VOL_PATH, 2)

    @mock.patch("cinder.image.image_utils.qemu_img_info")
    def test_extend_volume_with_invalid_format(self, mock_qemu_img_info):
        info = imageutils.QemuImgInfo()
        info.file_format = 'vmdk'
        mock_qemu_img_info.return_value = info

        self.assertRaises(exception.InvalidVolume,
                          self.drv.extend_volume, _FAKE_VOLUME, 2)

    @mock.patch("cinder.image.image_utils.resize_image")
    @mock.patch("cinder.image.image_utils.convert_image")
    def test_copy_volume_from_snapshot_with_ioerror(self, mock_convert_image,
                                                    mock_resize_image):
        with mock.patch.object(self.drv, '_read_info_file') as \
                mock_read_info_file, \
                mock.patch.object(self.drv, '_set_rw_permissions_for_all') as \
                mock_set_rw_permissions:
            mock_read_info_file.side_effect = IOError(errno.ENOENT, '')
            self.drv._copy_volume_from_snapshot(_FAKE_SNAPSHOT,
                                                _FAKE_VOLUME, 1)

        mock_read_info_file.assert_called_once_with("%s.info" % _FAKE_VOL_PATH)
        mock_convert_image.assert_called_once_with(_FAKE_SNAP_PATH,
                                                   _FAKE_VOL_PATH, 'raw',
                                                   run_as_root=True)
        mock_set_rw_permissions.assert_called_once_with(_FAKE_VOL_PATH)
        mock_resize_image.assert_called_once_with(_FAKE_VOL_PATH, 1)

    @mock.patch("cinder.image.image_utils.resize_image")
    @mock.patch("cinder.image.image_utils.convert_image")
    @mock.patch("cinder.image.image_utils.qemu_img_info")
    def test_copy_volume_from_snapshot(self, mock_qemu_img_info,
                                       mock_convert_image, mock_resize_image):

        new_volume = {'name': 'volume-3fa63b02-1fe5-11e5-b492-abf97a8fb23b',
                      'id': '3fa63b02-1fe5-11e5-b492-abf97a8fb23b',
                      'provider_location': 'fake_share'}
        new_vol_path = os.path.join(_FAKE_VOL_BASEDIR, new_volume['name'])

        info = imageutils.QemuImgInfo()
        info.file_format = 'raw'
        info.backing_file = _FAKE_VOL_PATH
        mock_qemu_img_info.return_value = info

        with mock.patch.object(self.drv, '_read_info_file') as \
                mock_read_info_file, \
                mock.patch.object(self.drv, '_set_rw_permissions_for_all') as \
                mock_set_rw_permissions:
            self.drv._copy_volume_from_snapshot(_FAKE_SNAPSHOT,
                                                new_volume, 1)

        mock_read_info_file.assert_called_once_with("%s.info" % _FAKE_VOL_PATH)
        mock_convert_image.assert_called_once_with(_FAKE_VOL_PATH,
                                                   new_vol_path, 'raw',
                                                   run_as_root=True)
        mock_set_rw_permissions.assert_called_once_with(new_vol_path)
        mock_resize_image.assert_called_once_with(new_vol_path, 1)

    @mock.patch("cinder.image.image_utils.qemu_img_info")
    @mock.patch("cinder.utils.temporary_chown")
    @mock.patch("six.moves.builtins.open")
    def test_backup_volume(self, mock_open, mock_temporary_chown,
                           mock_qemu_img_info):
        """Backup a volume with no snapshots."""

        info = imageutils.QemuImgInfo()
        info.file_format = 'raw'
        mock_qemu_img_info.return_value = info

        backup = {'volume_id': _FAKE_VOLUME['id']}
        mock_backup_service = mock.MagicMock()
        self.drv.db.volume_get.return_value = _FAKE_VOLUME

        self.drv.backup_volume(context, backup, mock_backup_service)

        mock_qemu_img_info.assert_called_once_with(_FAKE_VOL_PATH)
        mock_temporary_chown.assert_called_once_with(_FAKE_VOL_PATH)
        mock_open.assert_called_once_with(_FAKE_VOL_PATH)
        mock_backup_service.backup.assert_called_once_with(
            backup, mock_open().__enter__())

    @mock.patch("cinder.image.image_utils.qemu_img_info")
    def test_backup_volume_with_non_raw_volume(self, mock_qemu_img_info):

        info = imageutils.QemuImgInfo()
        info.file_format = 'qcow2'
        mock_qemu_img_info.return_value = info

        self.drv.db.volume_get.return_value = _FAKE_VOLUME

        self.assertRaises(exception.InvalidVolume, self.drv.backup_volume,
                          context, _FAKE_BACKUP, mock.MagicMock())

        mock_qemu_img_info.assert_called_once_with(_FAKE_VOL_PATH)

    @mock.patch("cinder.image.image_utils.qemu_img_info")
    def test_backup_volume_with_backing_file(self, mock_qemu_img_info):

        info = imageutils.QemuImgInfo()
        info.file_format = 'raw'
        info.backing_file = 'fake.img'
        mock_qemu_img_info.return_value = info

        backup = {'volume_id': _FAKE_VOLUME['id']}
        self.drv.db.volume_get.return_value = _FAKE_VOLUME

        self.assertRaises(exception.InvalidVolume, self.drv.backup_volume,
                          context, backup, mock.MagicMock())

        mock_qemu_img_info.assert_called_once_with(_FAKE_VOL_PATH)

    @mock.patch("cinder.utils.temporary_chown")
    @mock.patch("six.moves.builtins.open")
    def test_restore_bakup(self, mock_open, mock_temporary_chown):
        mock_backup_service = mock.MagicMock()

        self.drv.restore_backup(context, _FAKE_BACKUP, _FAKE_VOLUME,
                                mock_backup_service)

        mock_temporary_chown.assert_called_once_with(_FAKE_VOL_PATH)
        mock_open.assert_called_once_with(_FAKE_VOL_PATH, 'wb')
        mock_backup_service.restore.assert_called_once_with(
            _FAKE_BACKUP, _FAKE_VOLUME['id'], mock_open().__enter__())
