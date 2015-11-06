#  Copyright 2014 Cloudbase Solutions Srl
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

import os
import sys

import mock

from cinder import exception
from cinder.image import image_utils
from cinder import test
from cinder.volume.drivers.windows import smbfs


class WindowsSmbFsTestCase(test.TestCase):

    _FAKE_SHARE = '//1.2.3.4/share1'
    _FAKE_MNT_BASE = 'c:\openstack\mnt'
    _FAKE_MNT_POINT = os.path.join(_FAKE_MNT_BASE, 'fake_hash')
    _FAKE_VOLUME_NAME = 'volume-4f711859-4928-4cb7-801a-a50c37ceaccc'
    _FAKE_SNAPSHOT_NAME = _FAKE_VOLUME_NAME + '-snapshot.vhdx'
    _FAKE_SNAPSHOT_PATH = os.path.join(_FAKE_MNT_POINT,
                                       _FAKE_SNAPSHOT_NAME)
    _FAKE_TOTAL_SIZE = '2048'
    _FAKE_TOTAL_AVAILABLE = '1024'
    _FAKE_TOTAL_ALLOCATED = 1024
    _FAKE_VOLUME = {'id': 'e8d76af4-cbb9-4b70-8e9e-5a133f1a1a66',
                    'size': 1,
                    'provider_location': _FAKE_SHARE}
    _FAKE_SNAPSHOT = {'id': '35a23942-7625-4683-ad84-144b76e87a80',
                      'volume': _FAKE_VOLUME,
                      'volume_size': _FAKE_VOLUME['size']}
    _FAKE_SHARE_OPTS = '-o username=Administrator,password=12345'
    _FAKE_VOLUME_PATH = os.path.join(_FAKE_MNT_POINT,
                                     _FAKE_VOLUME_NAME + '.vhdx')

    def setUp(self):
        super(WindowsSmbFsTestCase, self).setUp()
        self._mock_wmi = mock.MagicMock()

        mock.patch('sys.platform', 'win32').start()
        mock.patch.dict(sys.modules, ctypes=mock.DEFAULT).start()
        mock.patch('six.moves.builtins.wmi', create=True).start()

        self.addCleanup(mock.patch.stopall)

        self._smbfs_driver = smbfs.WindowsSmbfsDriver(
            configuration=mock.Mock())
        self._smbfs_driver._remotefsclient = mock.Mock()
        self._smbfs_driver._delete = mock.Mock()
        self._smbfs_driver.local_path = mock.Mock(
            return_value=self._FAKE_VOLUME_PATH)
        self._smbfs_driver.vhdutils = mock.Mock()

    def _test_create_volume(self, volume_exists=False, volume_format='vhdx'):
        self._smbfs_driver.create_dynamic_vhd = mock.MagicMock()
        fake_create = self._smbfs_driver.vhdutils.create_dynamic_vhd
        self._smbfs_driver.get_volume_format = mock.Mock(
            return_value=volume_format)

        with mock.patch('os.path.exists', new=lambda x: volume_exists):
            if volume_exists or volume_format not in ('vhd', 'vhdx'):
                self.assertRaises(exception.InvalidVolume,
                                  self._smbfs_driver._do_create_volume,
                                  self._FAKE_VOLUME)
            else:
                fake_vol_path = self._FAKE_VOLUME_PATH
                self._smbfs_driver._do_create_volume(self._FAKE_VOLUME)
                fake_create.assert_called_once_with(
                    fake_vol_path, self._FAKE_VOLUME['size'] << 30)

    def test_create_volume(self):
        self._test_create_volume()

    def test_create_existing_volume(self):
        self._test_create_volume(True)

    def test_create_volume_invalid_volume(self):
        self._test_create_volume(volume_format="qcow")

    def test_get_capacity_info(self):
        self._smbfs_driver._remotefsclient.get_capacity_info = mock.Mock(
            return_value=(self._FAKE_TOTAL_SIZE, self._FAKE_TOTAL_AVAILABLE))
        self._smbfs_driver._get_total_allocated = mock.Mock(
            return_value=self._FAKE_TOTAL_ALLOCATED)

        ret_val = self._smbfs_driver._get_capacity_info(self._FAKE_SHARE)
        expected_ret_val = [int(x) for x in [self._FAKE_TOTAL_SIZE,
                            self._FAKE_TOTAL_AVAILABLE,
                            self._FAKE_TOTAL_ALLOCATED]]
        self.assertEqual(expected_ret_val, ret_val)

    def _test_get_img_info(self, backing_file=None):
        self._smbfs_driver.vhdutils.get_vhd_parent_path.return_value = (
            backing_file)

        image_info = self._smbfs_driver._qemu_img_info(self._FAKE_VOLUME_PATH)
        self.assertEqual(self._FAKE_VOLUME_NAME + '.vhdx',
                         image_info.image)
        backing_file_name = backing_file and os.path.basename(backing_file)
        self.assertEqual(backing_file_name, image_info.backing_file)

    def test_get_img_info_without_backing_file(self):
        self._test_get_img_info()

    def test_get_snapshot_info(self):
        self._test_get_img_info(self._FAKE_VOLUME_PATH)

    def test_create_snapshot(self):
        self._smbfs_driver.vhdutils.create_differencing_vhd = (
            mock.Mock())
        self._smbfs_driver._local_volume_dir = mock.Mock(
            return_value=self._FAKE_MNT_POINT)

        fake_create_diff = (
            self._smbfs_driver.vhdutils.create_differencing_vhd)

        self._smbfs_driver._do_create_snapshot(
            self._FAKE_SNAPSHOT,
            os.path.basename(self._FAKE_VOLUME_PATH),
            self._FAKE_SNAPSHOT_PATH)

        fake_create_diff.assert_called_once_with(self._FAKE_SNAPSHOT_PATH,
                                                 self._FAKE_VOLUME_PATH)

    def _test_copy_volume_to_image(self, has_parent=False,
                                   volume_format='vhd'):
        drv = self._smbfs_driver

        fake_image_meta = {'id': 'fake-image-id'}

        if has_parent:
            fake_volume_path = self._FAKE_SNAPSHOT_PATH
            fake_parent_path = self._FAKE_VOLUME_PATH
        else:
            fake_volume_path = self._FAKE_VOLUME_PATH
            fake_parent_path = None

        if volume_format == drv._DISK_FORMAT_VHD:
            fake_volume_path = fake_volume_path[:-1]

        fake_active_image = os.path.basename(fake_volume_path)

        drv.get_active_image_from_info = mock.Mock(
            return_value=fake_active_image)
        drv._local_volume_dir = mock.Mock(
            return_value=self._FAKE_MNT_POINT)
        drv.get_volume_format = mock.Mock(
            return_value=volume_format)
        drv.vhdutils.get_vhd_parent_path.return_value = (
            fake_parent_path)

        with mock.patch.object(image_utils, 'upload_volume') as (
                fake_upload_volume):
            drv.copy_volume_to_image(
                mock.sentinel.context, self._FAKE_VOLUME,
                mock.sentinel.image_service, fake_image_meta)

            expected_conversion = (
                has_parent or volume_format == drv._DISK_FORMAT_VHDX)

            if expected_conversion:
                fake_temp_image_name = '%s.temp_image.%s.%s' % (
                    self._FAKE_VOLUME['id'],
                    fake_image_meta['id'],
                    drv._DISK_FORMAT_VHD)
                fake_temp_image_path = os.path.join(
                    self._FAKE_MNT_POINT,
                    fake_temp_image_name)
                fake_active_image_path = os.path.join(
                    self._FAKE_MNT_POINT,
                    fake_active_image)
                upload_path = fake_temp_image_path

                drv.vhdutils.convert_vhd.assert_called_once_with(
                    fake_active_image_path,
                    fake_temp_image_path)
                drv._delete.assert_called_once_with(
                    fake_temp_image_path)
            else:
                upload_path = fake_volume_path

            fake_upload_volume.assert_called_once_with(
                mock.sentinel.context, mock.sentinel.image_service,
                fake_image_meta, upload_path, drv._DISK_FORMAT_VHD)

    def test_copy_volume_to_image_having_snapshot(self):
        self._test_copy_volume_to_image(has_parent=True)

    def test_copy_vhdx_volume_to_image(self):
        self._test_copy_volume_to_image(volume_format='vhdx')

    def test_copy_vhd_volume_to_image(self):
        self._test_copy_volume_to_image(volume_format='vhd')

    def test_copy_image_to_volume(self):
        drv = self._smbfs_driver

        drv.get_volume_format = mock.Mock(
            return_value=mock.sentinel.volume_format)
        drv.local_path = mock.Mock(
            return_value=self._FAKE_VOLUME_PATH)
        drv.configuration = mock.MagicMock()
        drv.configuration.volume_dd_blocksize = mock.sentinel.block_size
        drv._extend_vhd_if_needed = mock.Mock()

        with mock.patch.object(image_utils,
                               'fetch_to_volume_format') as fake_fetch:
            drv.copy_image_to_volume(
                mock.sentinel.context, self._FAKE_VOLUME,
                mock.sentinel.image_service,
                mock.sentinel.image_id)
            fake_fetch.assert_called_once_with(
                mock.sentinel.context,
                mock.sentinel.image_service,
                mock.sentinel.image_id,
                self._FAKE_VOLUME_PATH, mock.sentinel.volume_format,
                mock.sentinel.block_size)
            drv._extend_vhd_if_needed.assert_called_once_with(
                self._FAKE_VOLUME_PATH, self._FAKE_VOLUME['size'])

    def test_copy_volume_from_snapshot(self):
        drv = self._smbfs_driver
        fake_volume_info = {
            self._FAKE_SNAPSHOT['id']: 'fake_snapshot_file_name'}
        fake_img_info = mock.MagicMock()
        fake_img_info.backing_file = self._FAKE_VOLUME_NAME + '.vhdx'

        drv._local_path_volume_info = mock.Mock(
            return_value=self._FAKE_VOLUME_PATH + '.info')
        drv._local_volume_dir = mock.Mock(
            return_value=self._FAKE_MNT_POINT)
        drv._read_info_file = mock.Mock(
            return_value=fake_volume_info)
        drv._qemu_img_info = mock.Mock(
            return_value=fake_img_info)
        drv.local_path = mock.Mock(
            return_value=mock.sentinel.new_volume_path)
        drv._extend_vhd_if_needed = mock.Mock()

        drv._copy_volume_from_snapshot(
            self._FAKE_SNAPSHOT, self._FAKE_VOLUME,
            self._FAKE_VOLUME['size'])

        drv._delete.assert_called_once_with(mock.sentinel.new_volume_path)
        drv.vhdutils.convert_vhd.assert_called_once_with(
            self._FAKE_VOLUME_PATH,
            mock.sentinel.new_volume_path)
        drv._extend_vhd_if_needed.assert_called_once_with(
            mock.sentinel.new_volume_path, self._FAKE_VOLUME['size'])

    def test_rebase_img(self):
        self._smbfs_driver._rebase_img(
            self._FAKE_SNAPSHOT_PATH,
            self._FAKE_VOLUME_NAME + '.vhdx', 'vhdx')
        self._smbfs_driver.vhdutils.reconnect_parent.assert_called_once_with(
            self._FAKE_SNAPSHOT_PATH, self._FAKE_VOLUME_PATH)

    def _test_extend_vhd_if_needed(self, virtual_size_gb, requested_size_gb):
        drv = self._smbfs_driver
        virtual_size_bytes = virtual_size_gb << 30
        requested_size_bytes = requested_size_gb << 30

        virtual_size_dict = {'VirtualSize': virtual_size_bytes}
        drv.vhdutils.get_vhd_size = mock.Mock(return_value=virtual_size_dict)

        if virtual_size_gb > requested_size_gb:
            self.assertRaises(exception.VolumeBackendAPIException,
                              drv._extend_vhd_if_needed,
                              mock.sentinel.vhd_path,
                              requested_size_gb)
        else:
            drv._extend_vhd_if_needed(mock.sentinel.vhd_path,
                                      requested_size_gb)

            if virtual_size_gb < requested_size_gb:
                drv.vhdutils.resize_vhd.assert_called_once_with(
                    mock.sentinel.vhd_path, requested_size_bytes)
            else:
                self.assertFalse(drv.vhdutils.resize_vhd.called)

        drv.vhdutils.get_vhd_size.assert_called_once_with(
            mock.sentinel.vhd_path)

    def test_extend_vhd_if_needed_bigger_size(self):
        self._test_extend_vhd_if_needed(virtual_size_gb=1,
                                        requested_size_gb=2)

    def test_extend_vhd_if_needed_equal_size(self):
        self._test_extend_vhd_if_needed(virtual_size_gb=1,
                                        requested_size_gb=1)

    def test_extend_vhd_if_needed_smaller_size(self):
        self._test_extend_vhd_if_needed(virtual_size_gb=2,
                                        requested_size_gb=1)
