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
import functools
import os

import ddt
import mock
from oslo_utils import fileutils

from cinder import context
from cinder import exception
from cinder.image import image_utils
from cinder import test
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume
from cinder.volume.drivers import remotefs
from cinder.volume.drivers import smbfs


def requires_allocation_data_update(expected_size):
    def wrapper(func):
        @functools.wraps(func)
        def inner(inst, *args, **kwargs):
            with mock.patch.object(
                    inst._smbfs_driver,
                    'update_disk_allocation_data') as fake_update:
                func(inst, *args, **kwargs)
                fake_update.assert_called_once_with(inst.volume,
                                                    expected_size)
        return inner
    return wrapper


@ddt.ddt
class SmbFsTestCase(test.TestCase):

    _FAKE_SHARE = '//1.2.3.4/share1'
    _FAKE_SHARE_HASH = 'db0bf952c1734092b83e8990bd321131'
    _FAKE_MNT_BASE = '/mnt'
    _FAKE_VOLUME_NAME = 'volume-4f711859-4928-4cb7-801a-a50c37ceaccc'
    _FAKE_TOTAL_SIZE = '2048'
    _FAKE_TOTAL_AVAILABLE = '1024'
    _FAKE_TOTAL_ALLOCATED = 1024
    _FAKE_MNT_POINT = os.path.join(_FAKE_MNT_BASE, _FAKE_SHARE_HASH)
    _FAKE_VOLUME_PATH = os.path.join(_FAKE_MNT_POINT, _FAKE_VOLUME_NAME)
    _FAKE_VOLUME_SIZE = 1
    _FAKE_SNAPSHOT_ID = '50811859-4928-4cb7-801a-a50c37ceacba'
    _FAKE_SNAPSHOT_PATH = (
        _FAKE_VOLUME_PATH + '-snapshot' + _FAKE_SNAPSHOT_ID)
    _FAKE_SHARE_OPTS = '-o username=Administrator,password=12345'
    _FAKE_OPTIONS_DICT = {'username': 'Administrator',
                          'password': '12345'}
    _FAKE_ALLOCATION_DATA_PATH = os.path.join('fake_dir',
                                              'fake_allocation_data')

    def setUp(self):
        super(SmbFsTestCase, self).setUp()

        self._FAKE_SMBFS_CONFIG = mock.MagicMock(
            smbfs_oversub_ratio = 2,
            smbfs_used_ratio = 0.5,
            smbfs_shares_config = '/fake/config/path',
            smbfs_default_volume_format = 'raw',
            smbfs_sparsed_volumes = False)

        self._smbfs_driver = smbfs.SmbfsDriver(configuration=mock.Mock())
        self._smbfs_driver._remotefsclient = mock.Mock()
        self._smbfs_driver._local_volume_dir = mock.Mock(
            return_value=self._FAKE_MNT_POINT)
        self._smbfs_driver._execute = mock.Mock()
        self._smbfs_driver.base = self._FAKE_MNT_BASE
        self._smbfs_driver._alloc_info_file_path = (
            self._FAKE_ALLOCATION_DATA_PATH)
        self.context = context.get_admin_context()

        self.volume = fake_volume.fake_volume_obj(
            self.context,
            id='4f711859-4928-4cb7-801a-a50c37ceaccc',
            size=self._FAKE_VOLUME_SIZE,
            provider_location=self._FAKE_SHARE,
            display_name=self._FAKE_VOLUME_NAME,
            status='available')

        self.snapshot = fake_snapshot.fake_snapshot_obj(
            self.context,
            id=self._FAKE_SNAPSHOT_ID,
            status='available',
            volume_size=1)
        self.snapshot.volume = self.volume

    def _get_fake_allocation_data(self):
        return {self._FAKE_SHARE_HASH: {
                'total_allocated': self._FAKE_TOTAL_ALLOCATED}}

    @mock.patch.object(smbfs, 'open', create=True)
    @mock.patch('os.path.exists')
    @mock.patch.object(fileutils, 'ensure_tree')
    @mock.patch('json.load')
    def _test_setup_allocation_data(self, mock_json_load, mock_ensure_tree,
                                    mock_exists, mock_open,
                                    allocation_data_exists=False):
        mock_exists.return_value = allocation_data_exists
        self._smbfs_driver._update_allocation_data_file = mock.Mock()

        self._smbfs_driver._setup_allocation_data()

        if allocation_data_exists:
            fd = mock_open.return_value.__enter__.return_value
            mock_json_load.assert_called_once_with(fd)
            self.assertEqual(mock_json_load.return_value,
                             self._smbfs_driver._allocation_data)
        else:
            mock_ensure_tree.assert_called_once_with(
                os.path.dirname(self._FAKE_ALLOCATION_DATA_PATH))
            update_func = self._smbfs_driver._update_allocation_data_file
            update_func.assert_called_once_with()

    def test_setup_allocation_data_file_unexisting(self):
        self._test_setup_allocation_data()

    def test_setup_allocation_data_file_existing(self):
        self._test_setup_allocation_data(allocation_data_exists=True)

    def _test_update_allocation_data(self, virtual_size_gb=None,
                                     volume_exists=True):
        self._smbfs_driver._update_allocation_data_file = mock.Mock()
        update_func = self._smbfs_driver._update_allocation_data_file

        fake_alloc_data = self._get_fake_allocation_data()
        if volume_exists:
            fake_alloc_data[self._FAKE_SHARE_HASH][
                self._FAKE_VOLUME_NAME] = self.volume.size

        self._smbfs_driver._allocation_data = fake_alloc_data

        self._smbfs_driver.update_disk_allocation_data(self.volume,
                                                       virtual_size_gb)

        vol_allocated_size = fake_alloc_data[self._FAKE_SHARE_HASH].get(
            self._FAKE_VOLUME_NAME, None)
        if not virtual_size_gb:
            expected_total_allocated = (self._FAKE_TOTAL_ALLOCATED -
                                        self.volume.size)

            self.assertIsNone(vol_allocated_size)
        else:
            expected_total_allocated = (self._FAKE_TOTAL_ALLOCATED +
                                        virtual_size_gb -
                                        self.volume.size)
            self.assertEqual(virtual_size_gb, vol_allocated_size)

        update_func.assert_called_once_with()

        self.assertEqual(
            expected_total_allocated,
            fake_alloc_data[self._FAKE_SHARE_HASH]['total_allocated'])

    def test_update_allocation_data_volume_deleted(self):
        self._test_update_allocation_data()

    def test_update_allocation_data_volume_extended(self):
        self._test_update_allocation_data(
            virtual_size_gb=self.volume.size + 1)

    def test_update_allocation_data_volume_created(self):
        self._test_update_allocation_data(
            virtual_size_gb=self.volume.size)

    @requires_allocation_data_update(expected_size=None)
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
            drv.delete_volume(self.volume)

            fake_ensure_mounted.assert_called_once_with(self._FAKE_SHARE)
            drv._delete.assert_any_call(
                self._FAKE_VOLUME_PATH)
            drv._delete.assert_any_call(fake_vol_info)

    @mock.patch('os.path.exists')
    @mock.patch.object(image_utils, 'check_qemu_img_version')
    def _test_setup(self, mock_check_qemu_img_version,
                    mock_exists, config, share_config_exists=True):
        mock_exists.return_value = share_config_exists
        fake_ensure_mounted = mock.MagicMock()
        self._smbfs_driver._ensure_shares_mounted = fake_ensure_mounted
        self._smbfs_driver.configuration = config

        if not (config.smbfs_shares_config and share_config_exists and
                config.smbfs_oversub_ratio > 0 and
                0 <= config.smbfs_used_ratio <= 1):
            self.assertRaises(exception.SmbfsException,
                              self._smbfs_driver.do_setup,
                              None)
        else:
            self._smbfs_driver.do_setup(mock.sentinel.context)
            mock_check_qemu_img_version.assert_called_once_with()
            self.assertEqual({}, self._smbfs_driver.shares)
            fake_ensure_mounted.assert_called_once_with()

    def test_setup_missing_shares_config_option(self):
        fake_config = copy.copy(self._FAKE_SMBFS_CONFIG)
        fake_config.smbfs_shares_config = None
        self._test_setup(config=fake_config,
                         share_config_exists=False)

    def test_setup_missing_shares_config_file(self):
        self._test_setup(config=self._FAKE_SMBFS_CONFIG,
                         share_config_exists=False)

    def test_setup_invlid_oversub_ratio(self):
        fake_config = copy.copy(self._FAKE_SMBFS_CONFIG)
        fake_config.smbfs_oversub_ratio = -1
        self._test_setup(config=fake_config)

    def test_setup_invalid_used_ratio(self):
        fake_config = copy.copy(self._FAKE_SMBFS_CONFIG)
        fake_config.smbfs_used_ratio = -1
        self._test_setup(config=fake_config)

    def test_setup_invalid_used_ratio2(self):
        fake_config = copy.copy(self._FAKE_SMBFS_CONFIG)
        fake_config.smbfs_used_ratio = 1.1
        self._test_setup(config=fake_config)

    @mock.patch('os.path.exists')
    @mock.patch.multiple(smbfs.SmbfsDriver,
                         _create_windows_image=mock.DEFAULT,
                         _create_regular_file=mock.DEFAULT,
                         _create_qcow2_file=mock.DEFAULT,
                         _create_sparsed_file=mock.DEFAULT,
                         get_volume_format=mock.DEFAULT,
                         local_path=mock.DEFAULT,
                         _set_rw_permissions_for_all=mock.DEFAULT)
    def _test_create_volume(self, mock_exists, volume_exists=False,
                            volume_format=None, use_sparsed_file=False,
                            **mocks):
        self._smbfs_driver.configuration = copy.copy(self._FAKE_SMBFS_CONFIG)
        self._smbfs_driver.configuration.smbfs_sparsed_volumes = (
            use_sparsed_file)

        self._smbfs_driver.get_volume_format.return_value = volume_format
        self._smbfs_driver.local_path.return_value = mock.sentinel.vol_path
        mock_exists.return_value = volume_exists

        if volume_exists:
            self.assertRaises(exception.InvalidVolume,
                              self._smbfs_driver._do_create_volume,
                              self.volume)
            return

        self._smbfs_driver._do_create_volume(self.volume)
        expected_create_args = [mock.sentinel.vol_path,
                                self.volume.size]
        if volume_format in [self._smbfs_driver._DISK_FORMAT_VHDX,
                             self._smbfs_driver._DISK_FORMAT_VHD]:
            expected_create_args.append(volume_format)
            exp_create_method = self._smbfs_driver._create_windows_image
        else:
            if volume_format == self._smbfs_driver._DISK_FORMAT_QCOW2:
                exp_create_method = self._smbfs_driver._create_qcow2_file
            elif use_sparsed_file:
                exp_create_method = self._smbfs_driver._create_sparsed_file
            else:
                exp_create_method = self._smbfs_driver._create_regular_file

        exp_create_method.assert_called_once_with(*expected_create_args)
        mock_set_permissions = self._smbfs_driver._set_rw_permissions_for_all
        mock_set_permissions.assert_called_once_with(mock.sentinel.vol_path)

    def test_create_existing_volume(self):
        self._test_create_volume(volume_exists=True)

    def test_create_vhdx(self):
        self._test_create_volume(volume_format='vhdx')

    def test_create_qcow2(self):
        self._test_create_volume(volume_format='qcow2')

    def test_create_sparsed(self):
        self._test_create_volume(volume_format='raw',
                                 use_sparsed_file=True)

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
        self._smbfs_driver._get_total_allocated = mock.Mock(
            side_effect=[3, 2, 1])

        if not mounted_shares:
            self.assertRaises(exception.SmbfsNoSharesMounted,
                              self._smbfs_driver._find_share,
                              self.volume.size)
        elif not eligible_shares:
            self.assertRaises(exception.SmbfsNoSuitableShareFound,
                              self._smbfs_driver._find_share,
                              self.volume.size)
        else:
            ret_value = self._smbfs_driver._find_share(
                self.volume.size)
            # The eligible share with the minimum allocated space
            # will be selected
            self.assertEqual('fake_share3', ret_value)

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
                              mock_get_path_template, volume_exists=True):
        drv = self._smbfs_driver
        mock_get_path_template.return_value = self._FAKE_VOLUME_PATH
        volume_format = 'raw'

        expected_vol_path = self._FAKE_VOLUME_PATH + '.' + volume_format

        mock_lookup_volume.return_value = (
            expected_vol_path if volume_exists else None)
        mock_get_volume_format.return_value = volume_format

        ret_val = drv.local_path(self.volume)

        if volume_exists:
            self.assertFalse(mock_get_volume_format.called)
        else:
            mock_get_volume_format.assert_called_once_with(self.volume)
        self.assertEqual(expected_vol_path, ret_val)

    def test_get_existing_volume_path(self):
        self._test_get_volume_path()

    def test_get_new_volume_path(self):
        self._test_get_volume_path(volume_exists=False)

    @mock.patch.object(smbfs.SmbfsDriver, '_local_volume_dir')
    def test_get_local_volume_path_template(self, mock_get_local_dir):
        mock_get_local_dir.return_value = self._FAKE_MNT_POINT
        ret_val = self._smbfs_driver._get_local_volume_path_template(
            self.volume)
        self.assertEqual(self._FAKE_VOLUME_PATH, ret_val)

    @mock.patch('os.path.exists')
    def test_lookup_local_volume_path(self, mock_exists):
        expected_path = self._FAKE_VOLUME_PATH + '.vhdx'
        mock_exists.side_effect = lambda x: x == expected_path

        ret_val = self._smbfs_driver._lookup_local_volume_path(
            self._FAKE_VOLUME_PATH)

        extensions = [''] + [
            ".%s" % ext
            for ext in self._smbfs_driver._SUPPORTED_IMAGE_FORMATS]
        possible_paths = [self._FAKE_VOLUME_PATH + ext
                          for ext in extensions]
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

        ret_val = self._smbfs_driver.get_volume_format(self.volume,
                                                       qemu_format)

        if volume_exists:
            mock_qemu_img_info.assert_called_once_with(self._FAKE_VOLUME_PATH,
                                                       self._FAKE_VOLUME_NAME)
            self.assertFalse(mock_get_format_spec.called)
        else:
            mock_get_format_spec.assert_called_once_with(self.volume)
            self.assertFalse(mock_qemu_img_info.called)

        return ret_val

    def test_get_existing_raw_volume_format(self):
        fmt = self._mock_get_volume_format()
        self.assertEqual('raw', fmt)

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
        self._smbfs_driver.get_volume_format = mock.Mock(
            return_value=mock.sentinel.format)

        fake_data = {'export': self._FAKE_SHARE,
                     'format': mock.sentinel.format,
                     'name': self._FAKE_VOLUME_NAME,
                     'options': self._FAKE_SHARE_OPTS}
        expected = {
            'driver_volume_type': 'smbfs',
            'data': fake_data,
            'mount_point_base': self._FAKE_MNT_BASE}
        ret_val = self._smbfs_driver.initialize_connection(
            self.volume, None)

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
                                  drv.extend_volume,
                                  self.volume, mock.sentinel.new_size)
            else:
                drv.extend_volume(self.volume, mock.sentinel.new_size)

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

    @requires_allocation_data_update(expected_size=mock.sentinel.new_size)
    def test_extend_volume(self):
        self._test_extend_volume()

    def test_extend_volume_failed(self):
        self._test_extend_volume(extend_failed=True)

    @requires_allocation_data_update(expected_size=mock.sentinel.new_size)
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
                              self.volume, 2)
        elif not is_eligible:
            self.assertRaises(exception.ExtendVolumeError,
                              self._smbfs_driver._check_extend_volume_support,
                              self.volume, 2)
        else:
            self._smbfs_driver._check_extend_volume_support(
                self.volume, 2)
            self._smbfs_driver._is_share_eligible.assert_called_once_with(
                self._FAKE_SHARE, 1)

    def test_check_extend_support(self):
        self._test_check_extend_support()

    def test_check_extend_volume_with_snapshots(self):
        self._test_check_extend_support(has_snapshots=True)

    def test_check_extend_volume_uneligible_share(self):
        self._test_check_extend_support(is_eligible=False)

    @requires_allocation_data_update(expected_size=_FAKE_VOLUME_SIZE)
    @mock.patch.object(remotefs.RemoteFSSnapDriver, 'create_volume')
    def test_create_volume_base(self, mock_create_volume):
        self._smbfs_driver.create_volume(self.volume)
        mock_create_volume.assert_called_once_with(self.volume)

    @requires_allocation_data_update(expected_size=_FAKE_VOLUME_SIZE)
    @mock.patch.object(smbfs.SmbfsDriver,
                       '_create_volume_from_snapshot')
    def test_create_volume_from_snapshot(self, mock_create_volume):
        self._smbfs_driver.create_volume_from_snapshot(self.volume,
                                                       self.snapshot)
        mock_create_volume.assert_called_once_with(self.volume,
                                                   self.snapshot)

    @requires_allocation_data_update(expected_size=_FAKE_VOLUME_SIZE)
    @mock.patch.object(smbfs.SmbfsDriver, '_create_cloned_volume')
    def test_create_cloned_volume(self, mock_create_volume):
        self._smbfs_driver.create_cloned_volume(self.volume,
                                                mock.sentinel.src_vol)
        mock_create_volume.assert_called_once_with(self.volume,
                                                   mock.sentinel.src_vol)

    def test_create_volume_from_unavailable_snapshot(self):
        self.snapshot.status = 'error'
        self.assertRaises(
            exception.InvalidSnapshot,
            self._smbfs_driver.create_volume_from_snapshot,
            self.volume, self.snapshot)

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
                self.snapshot, self.volume,
                self.volume.size)
            drv._extend_volume.assert_called_once_with(
                self.volume, self.volume.size)
            fake_convert_image.assert_called_once_with(
                self._FAKE_VOLUME_PATH, self._FAKE_VOLUME_PATH[:-1], 'raw')

    def test_ensure_mounted(self):
        self._smbfs_driver.shares = {self._FAKE_SHARE: self._FAKE_SHARE_OPTS}

        self._smbfs_driver._ensure_share_mounted(self._FAKE_SHARE)
        self._smbfs_driver._remotefsclient.mount.assert_called_once_with(
            self._FAKE_SHARE, self._FAKE_SHARE_OPTS.split())

    def _test_copy_image_to_volume(self, wrong_size_after_fetch=False):
        drv = self._smbfs_driver

        vol_size_bytes = self.volume.size << 30

        fake_img_info = mock.MagicMock()

        if wrong_size_after_fetch:
            fake_img_info.virtual_size = 2 * vol_size_bytes
        else:
            fake_img_info.virtual_size = vol_size_bytes

        drv.get_volume_format = mock.Mock(
            return_value=drv._DISK_FORMAT_VHDX)
        drv.local_path = mock.Mock(
            return_value=self._FAKE_VOLUME_PATH)
        drv._do_extend_volume = mock.Mock()
        drv.configuration = mock.MagicMock()
        drv.configuration.volume_dd_blocksize = (
            mock.sentinel.block_size)

        with mock.patch.object(image_utils, 'fetch_to_volume_format') as \
                fake_fetch, mock.patch.object(image_utils, 'qemu_img_info') as \
                fake_qemu_img_info:

            fake_qemu_img_info.return_value = fake_img_info

            if wrong_size_after_fetch:
                self.assertRaises(
                    exception.ImageUnacceptable,
                    drv.copy_image_to_volume,
                    mock.sentinel.context, self.volume,
                    mock.sentinel.image_service,
                    mock.sentinel.image_id)
            else:
                drv.copy_image_to_volume(
                    mock.sentinel.context, self.volume,
                    mock.sentinel.image_service,
                    mock.sentinel.image_id)
                fake_fetch.assert_called_once_with(
                    mock.sentinel.context, mock.sentinel.image_service,
                    mock.sentinel.image_id, self._FAKE_VOLUME_PATH,
                    drv._DISK_FORMAT_VHDX,
                    mock.sentinel.block_size)
                drv._do_extend_volume.assert_called_once_with(
                    self._FAKE_VOLUME_PATH,
                    self.volume.size,
                    self.volume.name)

    def test_copy_image_to_volume(self):
        self._test_copy_image_to_volume()

    def test_copy_image_to_volume_wrong_size_after_fetch(self):
        self._test_copy_image_to_volume(wrong_size_after_fetch=True)

    def test_get_capacity_info(self):
        fake_block_size = 4096.0
        fake_total_blocks = 1024
        fake_avail_blocks = 512

        fake_df = ('%s %s %s' % (fake_block_size, fake_total_blocks,
                                 fake_avail_blocks), None)

        self._smbfs_driver._get_mount_point_for_share = mock.Mock(
            return_value=self._FAKE_MNT_POINT)
        self._smbfs_driver._get_total_allocated = mock.Mock(
            return_value=self._FAKE_TOTAL_ALLOCATED)
        self._smbfs_driver._execute.return_value = fake_df

        ret_val = self._smbfs_driver._get_capacity_info(self._FAKE_SHARE)
        expected = (fake_block_size * fake_total_blocks,
                    fake_block_size * fake_avail_blocks,
                    self._FAKE_TOTAL_ALLOCATED)
        self.assertEqual(expected, ret_val)

    @ddt.data([False, False],
              [True, True],
              [False, True])
    @ddt.unpack
    def test_get_volume_format_spec(self,
                                    volume_meta_contains_fmt,
                                    volume_type_contains_fmt):
        self._smbfs_driver.configuration = copy.copy(self._FAKE_SMBFS_CONFIG)

        fake_vol_meta_fmt = 'vhd'
        fake_vol_type_fmt = 'vhdx'

        volume_metadata = {}
        volume_type_extra_specs = {}

        if volume_meta_contains_fmt:
            volume_metadata['volume_format'] = fake_vol_meta_fmt
        elif volume_type_contains_fmt:
            volume_type_extra_specs['volume_format'] = fake_vol_type_fmt

        volume_type = fake_volume.fake_volume_type_obj(self.context)
        volume = fake_volume.fake_volume_obj(self.context)
        # Optional arguments are not set in _from_db_object,
        # so have to set explicitly here
        volume.volume_type = volume_type
        volume.metadata = volume_metadata
        # Same for extra_specs and VolumeType
        volume_type.extra_specs = volume_type_extra_specs

        resulted_fmt = self._smbfs_driver._get_volume_format_spec(volume)

        if volume_meta_contains_fmt:
            expected_fmt = fake_vol_meta_fmt
        elif volume_type_contains_fmt:
            expected_fmt = fake_vol_type_fmt
        else:
            expected_fmt = self._FAKE_SMBFS_CONFIG.smbfs_default_volume_format

        self.assertEqual(expected_fmt, resulted_fmt)
