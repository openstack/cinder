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

import copy
import os

import mock

from cinder import exception
from cinder.image import image_utils
from cinder import test
from cinder.volume.drivers import smbfs


class SmbFsTestCase(test.TestCase):

    _FAKE_SHARE = '//1.2.3.4/share1'
    _FAKE_MNT_BASE = '/mnt'
    _FAKE_VOLUME_NAME = 'volume-4f711859-4928-4cb7-801a-a50c37ceaccc'
    _FAKE_TOTAL_SIZE = '2048'
    _FAKE_TOTAL_AVAILABLE = '1024'
    _FAKE_TOTAL_ALLOCATED = 1024
    _FAKE_VOLUME = {'id': '4f711859-4928-4cb7-801a-a50c37ceaccc',
                    'size': 1,
                    'provider_location': _FAKE_SHARE,
                    'name': _FAKE_VOLUME_NAME,
                    'status': 'available'}
    _FAKE_MNT_POINT = os.path.join(_FAKE_MNT_BASE, 'fake_hash')
    _FAKE_VOLUME_PATH = os.path.join(_FAKE_MNT_POINT, _FAKE_VOLUME_NAME)
    _FAKE_SNAPSHOT_ID = '5g811859-4928-4cb7-801a-a50c37ceacba'
    _FAKE_SNAPSHOT = {'id': _FAKE_SNAPSHOT_ID,
                      'volume': _FAKE_VOLUME,
                      'status': 'available',
                      'volume_size': 1}
    _FAKE_SNAPSHOT_PATH = (
        _FAKE_VOLUME_PATH + '-snapshot' + _FAKE_SNAPSHOT_ID)
    _FAKE_SHARE_OPTS = '-o username=Administrator,password=12345'
    _FAKE_OPTIONS_DICT = {'username': 'Administrator',
                          'password': '12345'}

    _FAKE_LISTDIR = [_FAKE_VOLUME_NAME, _FAKE_VOLUME_NAME + '.vhd',
                     _FAKE_VOLUME_NAME + '.vhdx', 'fake_folder']
    _FAKE_SMBFS_CONFIG = mock.MagicMock()
    _FAKE_SMBFS_CONFIG.smbfs_oversub_ratio = 2
    _FAKE_SMBFS_CONFIG.smbfs_used_ratio = 0.5
    _FAKE_SMBFS_CONFIG.smbfs_shares_config = '/fake/config/path'
    _FAKE_SMBFS_CONFIG.smbfs_default_volume_format = 'raw'
    _FAKE_SMBFS_CONFIG.smbfs_sparsed_volumes = False

    def setUp(self):
        super(SmbFsTestCase, self).setUp()
        smbfs.SmbfsDriver.__init__ = lambda x: None
        self._smbfs_driver = smbfs.SmbfsDriver()
        self._smbfs_driver._remotefsclient = mock.Mock()
        self._smbfs_driver._local_volume_dir = mock.Mock(
            return_value=self._FAKE_MNT_POINT)
        self._smbfs_driver._execute = mock.Mock()
        self._smbfs_driver.base = self._FAKE_MNT_BASE

    def test_delete_volume(self):
        drv = self._smbfs_driver
        fake_vol_info = self._FAKE_VOLUME_PATH + '.info'

        drv._ensure_share_mounted = mock.MagicMock()
        fake_ensure_mounted = drv._ensure_share_mounted

        drv._local_volume_dir = mock.Mock(
            return_value=self._FAKE_MNT_POINT)
        drv.get_active_image_from_info = mock.Mock(
            return_value=self._FAKE_VOLUME_NAME)
        drv._delete = mock.Mock()
        drv._local_path_volume_info = mock.Mock(
            return_value=fake_vol_info)

        with mock.patch('os.path.exists', lambda x: True):
            drv.delete_volume(self._FAKE_VOLUME)

            fake_ensure_mounted.assert_called_once_with(self._FAKE_SHARE)
            drv._delete.assert_any_call(
                self._FAKE_VOLUME_PATH)
            drv._delete.assert_any_call(fake_vol_info)

    def _test_setup(self, config, share_config_exists=True):
        fake_exists = mock.Mock(return_value=share_config_exists)
        fake_ensure_mounted = mock.MagicMock()
        self._smbfs_driver._ensure_shares_mounted = fake_ensure_mounted
        self._smbfs_driver.configuration = config

        with mock.patch('os.path.exists', fake_exists):
            if not (config.smbfs_shares_config and share_config_exists and
                    config.smbfs_oversub_ratio > 0 and
                    0 <= config.smbfs_used_ratio <= 1):
                self.assertRaises(exception.SmbfsException,
                                  self._smbfs_driver.do_setup,
                                  None)
            else:
                self._smbfs_driver.do_setup(None)
                self.assertEqual(self._smbfs_driver.shares, {})
                fake_ensure_mounted.assert_called_once_with()

    def test_setup_missing_shares_config_option(self):
        fake_config = copy.copy(self._FAKE_SMBFS_CONFIG)
        fake_config.smbfs_shares_config = None
        self._test_setup(fake_config, None)

    def test_setup_missing_shares_config_file(self):
        self._test_setup(self._FAKE_SMBFS_CONFIG, False)

    def test_setup_invlid_oversub_ratio(self):
        fake_config = copy.copy(self._FAKE_SMBFS_CONFIG)
        fake_config.smbfs_oversub_ratio = -1
        self._test_setup(fake_config)

    def test_setup_invalid_used_ratio(self):
        fake_config = copy.copy(self._FAKE_SMBFS_CONFIG)
        fake_config.smbfs_used_ratio = -1
        self._test_setup(fake_config)

    def _test_create_volume(self, volume_exists=False, volume_format=None):
        fake_method = mock.MagicMock()
        self._smbfs_driver.configuration = copy.copy(self._FAKE_SMBFS_CONFIG)
        self._smbfs_driver._set_rw_permissions_for_all = mock.MagicMock()
        fake_set_permissions = self._smbfs_driver._set_rw_permissions_for_all
        self._smbfs_driver.get_volume_format = mock.MagicMock()

        windows_image_format = False
        fake_vol_path = self._FAKE_VOLUME_PATH
        self._smbfs_driver.get_volume_format.return_value = volume_format

        if volume_format:
            if volume_format in ('vhd', 'vhdx'):
                windows_image_format = volume_format
                if volume_format == 'vhd':
                    windows_image_format = 'vpc'
                method = '_create_windows_image'
                fake_vol_path += '.' + volume_format
            else:
                method = '_create_%s_file' % volume_format
                if volume_format == 'sparsed':
                    self._smbfs_driver.configuration.smbfs_sparsed_volumes = (
                        True)
        else:
            method = '_create_regular_file'

        setattr(self._smbfs_driver, method, fake_method)

        with mock.patch('os.path.exists', new=lambda x: volume_exists):
            if volume_exists:
                self.assertRaises(exception.InvalidVolume,
                                  self._smbfs_driver._do_create_volume,
                                  self._FAKE_VOLUME)
                return

            self._smbfs_driver._do_create_volume(self._FAKE_VOLUME)
            if windows_image_format:
                fake_method.assert_called_once_with(
                    fake_vol_path,
                    self._FAKE_VOLUME['size'],
                    windows_image_format)
            else:
                fake_method.assert_called_once_with(
                    fake_vol_path, self._FAKE_VOLUME['size'])
            fake_set_permissions.assert_called_once_with(fake_vol_path)

    def test_create_existing_volume(self):
        self._test_create_volume(volume_exists=True)

    def test_create_vhdx(self):
        self._test_create_volume(volume_format='vhdx')

    def test_create_qcow2(self):
        self._test_create_volume(volume_format='qcow2')

    def test_create_sparsed(self):
        self._test_create_volume(volume_format='sparsed')

    def test_create_regular(self):
        self._test_create_volume()

    def _test_find_share(self, existing_mounted_shares=True,
                         eligible_shares=True):
        if existing_mounted_shares:
            mounted_shares = ('fake_share1', 'fake_share2', 'fake_share3')
        else:
            mounted_shares = None

        self._smbfs_driver._mounted_shares = mounted_shares
        self._smbfs_driver._is_share_eligible = mock.Mock(
            return_value=eligible_shares)
        fake_capacity_info = ((2, 1, 5), (2, 1, 4), (2, 1, 1))
        self._smbfs_driver._get_capacity_info = mock.Mock(
            side_effect=fake_capacity_info)

        if not mounted_shares:
            self.assertRaises(exception.SmbfsNoSharesMounted,
                              self._smbfs_driver._find_share,
                              self._FAKE_VOLUME['size'])
        elif not eligible_shares:
            self.assertRaises(exception.SmbfsNoSuitableShareFound,
                              self._smbfs_driver._find_share,
                              self._FAKE_VOLUME['size'])
        else:
            ret_value = self._smbfs_driver._find_share(
                self._FAKE_VOLUME['size'])
            # The eligible share with the minimum allocated space
            # will be selected
            self.assertEqual(ret_value, 'fake_share3')

    def test_find_share(self):
        self._test_find_share()

    def test_find_share_missing_mounted_shares(self):
        self._test_find_share(existing_mounted_shares=False)

    def test_find_share_missing_eligible_shares(self):
        self._test_find_share(eligible_shares=False)

    def _test_is_share_eligible(self, capacity_info, volume_size):
        self._smbfs_driver._get_capacity_info = mock.Mock(
            return_value=[float(x << 30) for x in capacity_info])
        self._smbfs_driver.configuration = self._FAKE_SMBFS_CONFIG
        return self._smbfs_driver._is_share_eligible(self._FAKE_SHARE,
                                                     volume_size)

    def test_share_volume_above_used_ratio(self):
        fake_capacity_info = (4, 1, 1)
        fake_volume_size = 2
        ret_value = self._test_is_share_eligible(fake_capacity_info,
                                                 fake_volume_size)
        self.assertFalse(ret_value)

    def test_eligible_share(self):
        fake_capacity_info = (4, 4, 0)
        fake_volume_size = 1
        ret_value = self._test_is_share_eligible(fake_capacity_info,
                                                 fake_volume_size)
        self.assertTrue(ret_value)

    def test_share_volume_above_oversub_ratio(self):
        fake_capacity_info = (4, 4, 7)
        fake_volume_size = 2
        ret_value = self._test_is_share_eligible(fake_capacity_info,
                                                 fake_volume_size)
        self.assertFalse(ret_value)

    def test_share_reserved_above_oversub_ratio(self):
        fake_capacity_info = (4, 4, 10)
        fake_volume_size = 1
        ret_value = self._test_is_share_eligible(fake_capacity_info,
                                                 fake_volume_size)
        self.assertFalse(ret_value)

    def test_parse_options(self):
        (opt_list,
         opt_dict) = self._smbfs_driver.parse_options(
            self._FAKE_SHARE_OPTS)
        expected_ret = ([], self._FAKE_OPTIONS_DICT)
        self.assertEqual(expected_ret, (opt_list, opt_dict))

    def test_parse_credentials(self):
        fake_smb_options = r'-o user=MyDomain\Administrator,noperm'
        expected_flags = '-o username=Administrator,noperm'
        flags = self._smbfs_driver.parse_credentials(fake_smb_options)
        self.assertEqual(expected_flags, flags)

    @mock.patch.object(smbfs.SmbfsDriver, '_get_local_volume_path_template')
    @mock.patch.object(smbfs.SmbfsDriver, '_lookup_local_volume_path')
    @mock.patch.object(smbfs.SmbfsDriver, 'get_volume_format')
    def _test_get_volume_path(self, mock_get_volume_format, mock_lookup_volume,
                              mock_get_path_template, volume_exists=True,
                              volume_format='raw'):
        drv = self._smbfs_driver
        mock_get_path_template.return_value = self._FAKE_VOLUME_PATH

        expected_vol_path = self._FAKE_VOLUME_PATH
        if volume_format in (drv._DISK_FORMAT_VHD, drv._DISK_FORMAT_VHDX):
            expected_vol_path += '.' + volume_format

        mock_lookup_volume.return_value = (
            expected_vol_path if volume_exists else None)
        mock_get_volume_format.return_value = volume_format

        ret_val = drv.local_path(self._FAKE_VOLUME)

        if volume_exists:
            self.assertFalse(mock_get_volume_format.called)
        else:
            mock_get_volume_format.assert_called_once_with(self._FAKE_VOLUME)
        self.assertEqual(expected_vol_path, ret_val)

    def test_get_existing_volume_path(self):
        self._test_get_volume_path()

    def test_get_new_raw_volume_path(self):
        self._test_get_volume_path(volume_exists=False)

    def test_get_new_vhd_volume_path(self):
        self._test_get_volume_path(volume_exists=False, volume_format='vhd')

    @mock.patch.object(smbfs.SmbfsDriver, '_local_volume_dir')
    def test_get_local_volume_path_template(self, mock_get_local_dir):
        mock_get_local_dir.return_value = self._FAKE_MNT_POINT
        ret_val = self._smbfs_driver._get_local_volume_path_template(
            self._FAKE_VOLUME)
        self.assertEqual(self._FAKE_VOLUME_PATH, ret_val)

    @mock.patch('os.path.exists')
    def test_lookup_local_volume_path(self, mock_exists):
        expected_path = self._FAKE_VOLUME_PATH + '.vhdx'
        mock_exists.side_effect = lambda x: x == expected_path

        ret_val = self._smbfs_driver._lookup_local_volume_path(
            self._FAKE_VOLUME_PATH)

        possible_paths = [self._FAKE_VOLUME_PATH + ext
                          for ext in ('', '.vhd', '.vhdx')]
        mock_exists.assert_has_calls(
            [mock.call(path) for path in possible_paths])
        self.assertEqual(expected_path, ret_val)

    @mock.patch.object(smbfs.SmbfsDriver, '_get_local_volume_path_template')
    @mock.patch.object(smbfs.SmbfsDriver, '_lookup_local_volume_path')
    @mock.patch.object(smbfs.SmbfsDriver, '_qemu_img_info')
    @mock.patch.object(smbfs.SmbfsDriver, '_get_volume_format_spec')
    def _mock_get_volume_format(self, mock_get_format_spec, mock_qemu_img_info,
                                mock_lookup_volume, mock_get_path_template,
                                qemu_format=False, volume_format='raw',
                                volume_exists=True):
        mock_get_path_template.return_value = self._FAKE_VOLUME_PATH
        mock_lookup_volume.return_value = (
            self._FAKE_VOLUME_PATH if volume_exists else None)

        mock_qemu_img_info.return_value.file_format = volume_format
        mock_get_format_spec.return_value = volume_format

        ret_val = self._smbfs_driver.get_volume_format(self._FAKE_VOLUME,
                                                       qemu_format)

        if volume_exists:
            mock_qemu_img_info.assert_called_once_with(self._FAKE_VOLUME_PATH,
                                                       self._FAKE_VOLUME_NAME)
            self.assertFalse(mock_get_format_spec.called)
        else:
            mock_get_format_spec.assert_called_once_with(self._FAKE_VOLUME)
            self.assertFalse(mock_qemu_img_info.called)

        return ret_val

    def test_get_existing_raw_volume_format(self):
        fmt = self._mock_get_volume_format()
        self.assertEqual(fmt, 'raw')

    def test_get_new_vhd_volume_format(self):
        expected_fmt = 'vhd'
        fmt = self._mock_get_volume_format(volume_format=expected_fmt,
                                           volume_exists=False)
        self.assertEqual(expected_fmt, fmt)

    def test_get_new_vhd_legacy_volume_format(self):
        img_fmt = 'vhd'
        expected_fmt = 'vpc'
        ret_val = self._mock_get_volume_format(volume_format=img_fmt,
                                               volume_exists=False,
                                               qemu_format=True)
        self.assertEqual(expected_fmt, ret_val)

    def test_initialize_connection(self):
        self._smbfs_driver.get_active_image_from_info = mock.Mock(
            return_value=self._FAKE_VOLUME_NAME)
        self._smbfs_driver._get_mount_point_base = mock.Mock(
            return_value=self._FAKE_MNT_BASE)
        self._smbfs_driver.shares = {self._FAKE_SHARE: self._FAKE_SHARE_OPTS}
        self._smbfs_driver._qemu_img_info = mock.Mock(
            return_value=mock.Mock(file_format='raw'))

        fake_data = {'export': self._FAKE_SHARE,
                     'format': 'raw',
                     'name': self._FAKE_VOLUME_NAME,
                     'options': self._FAKE_SHARE_OPTS}
        expected = {
            'driver_volume_type': 'smbfs',
            'data': fake_data,
            'mount_point_base': self._FAKE_MNT_BASE}
        ret_val = self._smbfs_driver.initialize_connection(
            self._FAKE_VOLUME, None)

        self.assertEqual(expected, ret_val)

    def _test_extend_volume(self, extend_failed=False, image_format='raw'):
        drv = self._smbfs_driver

        drv.local_path = mock.Mock(
            return_value=self._FAKE_VOLUME_PATH)
        drv._check_extend_volume_support = mock.Mock(
            return_value=True)
        drv._is_file_size_equal = mock.Mock(
            return_value=not extend_failed)
        drv._qemu_img_info = mock.Mock(
            return_value=mock.Mock(file_format=image_format))
        drv._delete = mock.Mock()

        with mock.patch.object(image_utils, 'resize_image') as fake_resize, \
                mock.patch.object(image_utils, 'convert_image') as \
                fake_convert:
            if extend_failed:
                self.assertRaises(exception.ExtendVolumeError,
                                  drv._extend_volume,
                                  self._FAKE_VOLUME, mock.sentinel.new_size)
            else:
                drv._extend_volume(
                    self._FAKE_VOLUME,
                    mock.sentinel.new_size)
                if image_format in (drv._DISK_FORMAT_VHDX,
                                    drv._DISK_FORMAT_VHD_LEGACY):
                    fake_tmp_path = self._FAKE_VOLUME_PATH + '.tmp'
                    fake_convert.assert_any_call(self._FAKE_VOLUME_PATH,
                                                 fake_tmp_path, 'raw')
                    fake_resize.assert_called_once_with(
                        fake_tmp_path, mock.sentinel.new_size)
                    fake_convert.assert_any_call(fake_tmp_path,
                                                 self._FAKE_VOLUME_PATH,
                                                 image_format)
                else:
                    fake_resize.assert_called_once_with(
                        self._FAKE_VOLUME_PATH, mock.sentinel.new_size)

    def test_extend_volume(self):
        self._test_extend_volume()

    def test_extend_volume_failed(self):
        self._test_extend_volume(extend_failed=True)

    def test_extend_vhd_volume(self):
        self._test_extend_volume(image_format='vpc')

    def _test_check_extend_support(self, has_snapshots=False,
                                   is_eligible=True):
        self._smbfs_driver.local_path = mock.Mock(
            return_value=self._FAKE_VOLUME_PATH)

        if has_snapshots:
            active_file_path = self._FAKE_SNAPSHOT_PATH
        else:
            active_file_path = self._FAKE_VOLUME_PATH

        self._smbfs_driver.get_active_image_from_info = mock.Mock(
            return_value=active_file_path)
        self._smbfs_driver._is_share_eligible = mock.Mock(
            return_value=is_eligible)

        if has_snapshots:
            self.assertRaises(exception.InvalidVolume,
                              self._smbfs_driver._check_extend_volume_support,
                              self._FAKE_VOLUME, 2)
        elif not is_eligible:
            self.assertRaises(exception.ExtendVolumeError,
                              self._smbfs_driver._check_extend_volume_support,
                              self._FAKE_VOLUME, 2)
        else:
            self._smbfs_driver._check_extend_volume_support(
                self._FAKE_VOLUME, 2)
            self._smbfs_driver._is_share_eligible.assert_called_once_with(
                self._FAKE_SHARE, 1)

    def test_check_extend_support(self):
        self._test_check_extend_support()

    def test_check_extend_volume_with_snapshots(self):
        self._test_check_extend_support(has_snapshots=True)

    def test_check_extend_volume_uneligible_share(self):
        self._test_check_extend_support(is_eligible=False)

    def test_create_volume_from_in_use_snapshot(self):
        fake_snapshot = {'status': 'in-use'}
        self.assertRaises(
            exception.InvalidSnapshot,
            self._smbfs_driver.create_volume_from_snapshot,
            self._FAKE_VOLUME, fake_snapshot)

    def test_copy_volume_from_snapshot(self):
        drv = self._smbfs_driver

        fake_volume_info = {self._FAKE_SNAPSHOT_ID: 'fake_snapshot_file_name'}
        fake_img_info = mock.MagicMock()
        fake_img_info.backing_file = self._FAKE_VOLUME_NAME

        drv.get_volume_format = mock.Mock(
            return_value='raw')
        drv._local_path_volume_info = mock.Mock(
            return_value=self._FAKE_VOLUME_PATH + '.info')
        drv._local_volume_dir = mock.Mock(
            return_value=self._FAKE_MNT_POINT)
        drv._read_info_file = mock.Mock(
            return_value=fake_volume_info)
        drv._qemu_img_info = mock.Mock(
            return_value=fake_img_info)
        drv.local_path = mock.Mock(
            return_value=self._FAKE_VOLUME_PATH[:-1])
        drv._extend_volume = mock.Mock()
        drv._set_rw_permissions_for_all = mock.Mock()

        with mock.patch.object(image_utils, 'convert_image') as (
                fake_convert_image):
            drv._copy_volume_from_snapshot(
                self._FAKE_SNAPSHOT, self._FAKE_VOLUME,
                self._FAKE_VOLUME['size'])
            drv._extend_volume.assert_called_once_with(
                self._FAKE_VOLUME, self._FAKE_VOLUME['size'])
            fake_convert_image.assert_called_once_with(
                self._FAKE_VOLUME_PATH, self._FAKE_VOLUME_PATH[:-1], 'raw')

    def test_ensure_mounted(self):
        self._smbfs_driver.shares = {self._FAKE_SHARE: self._FAKE_SHARE_OPTS}

        self._smbfs_driver._ensure_share_mounted(self._FAKE_SHARE)
        self._smbfs_driver._remotefsclient.mount.assert_called_once_with(
            self._FAKE_SHARE, self._FAKE_SHARE_OPTS.split())

    def _test_copy_image_to_volume(self, unsupported_qemu_version=False,
                                   wrong_size_after_fetch=False):
        drv = self._smbfs_driver

        vol_size_bytes = self._FAKE_VOLUME['size'] << 30
        fake_image_service = mock.MagicMock()
        fake_image_service.show.return_value = (
            {'id': 'fake_image_id', 'disk_format': 'raw'})

        fake_img_info = mock.MagicMock()

        if wrong_size_after_fetch:
            fake_img_info.virtual_size = 2 * vol_size_bytes
        else:
            fake_img_info.virtual_size = vol_size_bytes

        if unsupported_qemu_version:
            qemu_version = [1, 5]
        else:
            qemu_version = [1, 7]

        drv.get_volume_format = mock.Mock(
            return_value=drv._DISK_FORMAT_VHDX)
        drv.local_path = mock.Mock(
            return_value=self._FAKE_VOLUME_PATH)
        drv.get_qemu_version = mock.Mock(
            return_value=qemu_version)
        drv._do_extend_volume = mock.Mock()
        drv.configuration = mock.MagicMock()
        drv.configuration.volume_dd_blocksize = (
            mock.sentinel.block_size)

        exc = None
        with mock.patch.object(image_utils, 'fetch_to_volume_format') as \
                fake_fetch, mock.patch.object(image_utils, 'qemu_img_info') as \
                fake_qemu_img_info:

            if wrong_size_after_fetch:
                exc = exception.ImageUnacceptable
            elif unsupported_qemu_version:
                exc = exception.InvalidVolume

            fake_qemu_img_info.return_value = fake_img_info

            if exc:
                self.assertRaises(
                    exc, drv.copy_image_to_volume,
                    mock.sentinel.context, self._FAKE_VOLUME,
                    fake_image_service,
                    mock.sentinel.image_id)
            else:
                drv.copy_image_to_volume(
                    mock.sentinel.context, self._FAKE_VOLUME,
                    fake_image_service,
                    mock.sentinel.image_id)
                fake_fetch.assert_called_once_with(
                    mock.sentinel.context, fake_image_service,
                    mock.sentinel.image_id, self._FAKE_VOLUME_PATH,
                    drv._DISK_FORMAT_VHDX,
                    mock.sentinel.block_size)
                drv._do_extend_volume.assert_called_once_with(
                    self._FAKE_VOLUME_PATH,
                    self._FAKE_VOLUME['size'],
                    self._FAKE_VOLUME['name'])

    def test_copy_image_to_volume(self):
        self._test_copy_image_to_volume()

    def test_copy_image_to_volume_wrong_size_after_fetch(self):
        self._test_copy_image_to_volume(wrong_size_after_fetch=True)

    def test_copy_image_to_volume_unsupported_qemu_version(self):
        self._test_copy_image_to_volume(unsupported_qemu_version=True)

    def test_get_capacity_info(self):
        fake_block_size = 4096.0
        fake_total_blocks = 1024
        fake_avail_blocks = 512
        fake_total_allocated = fake_total_blocks * fake_block_size

        fake_df = ('%s %s %s' % (fake_block_size, fake_total_blocks,
                                 fake_avail_blocks), None)
        fake_du = (str(fake_total_allocated), None)

        self._smbfs_driver._get_mount_point_for_share = mock.Mock(
            return_value=self._FAKE_MNT_POINT)
        self._smbfs_driver._execute = mock.Mock(
            side_effect=(fake_df, fake_du))

        ret_val = self._smbfs_driver._get_capacity_info(self._FAKE_SHARE)
        expected = (fake_block_size * fake_total_blocks,
                    fake_block_size * fake_avail_blocks,
                    fake_total_allocated)
        self.assertEqual(expected, ret_val)
