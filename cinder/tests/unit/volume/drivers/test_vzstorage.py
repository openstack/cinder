#  Copyright 2015 Odin
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
import errno
import os

import mock

from os_brick.remotefs import remotefs
from oslo_utils import units

from cinder import context
from cinder import exception
from cinder.image import image_utils
from cinder import test
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume
from cinder.volume.drivers import vzstorage


_orig_path_exists = os.path.exists


class VZStorageTestCase(test.TestCase):

    _FAKE_SHARE = "10.0.0.1,10.0.0.2:/cluster123:123123"
    _FAKE_MNT_BASE = '/mnt'
    _FAKE_MNT_POINT = os.path.join(_FAKE_MNT_BASE, 'fake_hash')
    _FAKE_VOLUME_NAME = 'volume-4f711859-4928-4cb7-801a-a50c37ceaccc'
    _FAKE_VOLUME_PATH = os.path.join(_FAKE_MNT_POINT, _FAKE_VOLUME_NAME)
    _FAKE_SNAPSHOT_ID = '50811859-4928-4cb7-801a-a50c37ceacba'
    _FAKE_SNAPSHOT_PATH = (
        _FAKE_VOLUME_PATH + '-snapshot' + _FAKE_SNAPSHOT_ID)

    _FAKE_VZ_CONFIG = mock.MagicMock()
    _FAKE_VZ_CONFIG.vzstorage_shares_config = '/fake/config/path'
    _FAKE_VZ_CONFIG.vzstorage_sparsed_volumes = False
    _FAKE_VZ_CONFIG.vzstorage_used_ratio = 0.7
    _FAKE_VZ_CONFIG.vzstorage_mount_point_base = _FAKE_MNT_BASE
    _FAKE_VZ_CONFIG.vzstorage_default_volume_format = 'raw'
    _FAKE_VZ_CONFIG.nas_secure_file_operations = 'auto'
    _FAKE_VZ_CONFIG.nas_secure_file_permissions = 'auto'

    def setUp(self):
        super(VZStorageTestCase, self).setUp()

        self._remotefsclient = mock.patch.object(
            remotefs, 'VZStorageRemoteFSClient').start()
        get_mount_point = mock.Mock(return_value=self._FAKE_MNT_POINT)
        self._remotefsclient.get_mount_point = get_mount_point
        cfg = copy.copy(self._FAKE_VZ_CONFIG)
        self._vz_driver = vzstorage.VZStorageDriver(configuration=cfg)
        self._vz_driver._local_volume_dir = mock.Mock(
            return_value=self._FAKE_MNT_POINT)
        self._vz_driver._execute = mock.Mock()
        self._vz_driver.base = self._FAKE_MNT_BASE

        self.context = context.get_admin_context()
        vol_type = fake_volume.fake_volume_type_obj(self.context)
        vol_type.extra_specs = {}
        _FAKE_VOLUME = {'id': '4f711859-4928-4cb7-801a-a50c37ceaccc',
                        'size': 1,
                        'provider_location': self._FAKE_SHARE,
                        'name': self._FAKE_VOLUME_NAME,
                        'status': 'available'}
        self.vol = fake_volume.fake_volume_obj(self.context,
                                               volume_type_id=vol_type.id,
                                               **_FAKE_VOLUME)
        self.vol.volume_type = vol_type

        _FAKE_SNAPSHOT = {'id': self._FAKE_SNAPSHOT_ID,
                          'status': 'available',
                          'volume_size': 1}
        self.snap = fake_snapshot.fake_snapshot_obj(self.context,
                                                    **_FAKE_SNAPSHOT)
        self.snap.volume = self.vol

    def _path_exists(self, path):
        if path.startswith(self._FAKE_VZ_CONFIG.vzstorage_shares_config):
            return True
        return _orig_path_exists(path)

    def _path_dont_exists(self, path):
        if path.startswith('/fake'):
            return False
        return _orig_path_exists(path)

    @mock.patch('os.path.exists')
    def test_setup_ok(self, mock_exists):
        mock_exists.side_effect = self._path_exists
        self._vz_driver.do_setup(mock.sentinel.context)

    @mock.patch('os.path.exists')
    def test_setup_missing_shares_conf(self, mock_exists):
        mock_exists.side_effect = self._path_dont_exists
        self.assertRaises(exception.VzStorageException,
                          self._vz_driver.do_setup,
                          mock.sentinel.context)

    @mock.patch('os.path.exists')
    def test_setup_invalid_usage_ratio(self, mock_exists):
        mock_exists.side_effect = self._path_exists
        self._vz_driver.configuration.vzstorage_used_ratio = 1.2
        self.assertRaises(exception.VzStorageException,
                          self._vz_driver.do_setup,
                          mock.sentinel.context)

    @mock.patch('os.path.exists')
    def test_setup_invalid_usage_ratio2(self, mock_exists):
        mock_exists.side_effect = self._path_exists
        self._vz_driver.configuration.vzstorage_used_ratio = 0
        self.assertRaises(exception.VzStorageException,
                          self._vz_driver.do_setup,
                          mock.sentinel.context)

    @mock.patch('os.path.exists')
    def test_setup_invalid_mount_point_base(self, mock_exists):
        mock_exists.side_effect = self._path_exists
        conf = copy.copy(self._FAKE_VZ_CONFIG)
        conf.vzstorage_mount_point_base = './tmp'
        vz_driver = vzstorage.VZStorageDriver(configuration=conf)
        self.assertRaises(exception.VzStorageException,
                          vz_driver.do_setup,
                          mock.sentinel.context)

    @mock.patch('os.path.exists')
    def test_setup_no_vzstorage(self, mock_exists):
        mock_exists.side_effect = self._path_exists
        exc = OSError()
        exc.errno = errno.ENOENT
        self._vz_driver._execute.side_effect = exc
        self.assertRaises(exception.VzStorageException,
                          self._vz_driver.do_setup,
                          mock.sentinel.context)

    def test_initialize_connection(self):
        drv = self._vz_driver
        file_format = 'raw'
        info = mock.Mock()
        info.file_format = file_format
        snap_info = """{"volume_format": "raw",
                        "active": "%s"}""" % self.vol.id
        with mock.patch.object(drv, '_qemu_img_info', return_value=info):
            with mock.patch.object(drv, '_read_file',
                                   return_value=snap_info):
                ret = drv.initialize_connection(self.vol, None)
        name = drv.get_active_image_from_info(self.vol)
        expected = {'driver_volume_type': 'vzstorage',
                    'data': {'export': self._FAKE_SHARE,
                             'format': file_format,
                             'name': name},
                    'mount_point_base': self._FAKE_MNT_BASE}
        self.assertEqual(expected, ret)

    def test_ensure_share_mounted_invalid_share(self):
        self.assertRaises(exception.VzStorageException,
                          self._vz_driver._ensure_share_mounted, ':')

    def test_ensure_share_mounted(self):
        drv = self._vz_driver
        share = self._FAKE_SHARE
        drv.shares = {'1': '["1", "2", "3"]', share: '["some", "options"]'}
        drv._ensure_share_mounted(share)

    def test_find_share(self):
        drv = self._vz_driver
        drv._mounted_shares = [self._FAKE_SHARE]
        with mock.patch.object(drv, '_is_share_eligible', return_value=True):
            ret = drv._find_share(self.vol)
            self.assertEqual(self._FAKE_SHARE, ret)

    def test_find_share_no_shares_mounted(self):
        drv = self._vz_driver
        with mock.patch.object(drv, '_is_share_eligible', return_value=True):
            self.assertRaises(exception.VzStorageNoSharesMounted,
                              drv._find_share, self.vol)

    def test_find_share_no_shares_suitable(self):
        drv = self._vz_driver
        drv._mounted_shares = [self._FAKE_SHARE]
        with mock.patch.object(drv, '_is_share_eligible', return_value=False):
            self.assertRaises(exception.VzStorageNoSuitableShareFound,
                              drv._find_share, self.vol)

    def test_is_share_eligible_false(self):
        drv = self._vz_driver
        cap_info = (100 * units.Gi, 40 * units.Gi, 60 * units.Gi)
        with mock.patch.object(drv, '_get_capacity_info',
                               return_value=cap_info):
            ret = drv._is_share_eligible(self._FAKE_SHARE, 50)
            self.assertFalse(ret)

    def test_is_share_eligible_true(self):
        drv = self._vz_driver
        cap_info = (100 * units.Gi, 40 * units.Gi, 60 * units.Gi)
        with mock.patch.object(drv, '_get_capacity_info',
                               return_value=cap_info):
            ret = drv._is_share_eligible(self._FAKE_SHARE, 30)
            self.assertTrue(ret)

    @mock.patch.object(image_utils, 'resize_image')
    def test_extend_volume(self, mock_resize_image):
        drv = self._vz_driver
        drv._check_extend_volume_support = mock.Mock(return_value=True)
        drv._is_file_size_equal = mock.Mock(return_value=True)

        snap_info = '{"active": "%s"}' % self.vol.id
        with mock.patch.object(drv, 'get_volume_format',
                               return_value="raw"):
            with mock.patch.object(drv, 'local_path',
                                   return_value=self._FAKE_VOLUME_PATH):
                with mock.patch.object(drv, '_read_file',
                                       return_value=snap_info):
                    drv.extend_volume(self.vol, 10)

        mock_resize_image.assert_called_once_with(self._FAKE_VOLUME_PATH, 10)

    def _test_check_extend_support(self, has_snapshots=False,
                                   is_eligible=True):
        drv = self._vz_driver
        drv.local_path = mock.Mock(return_value=self._FAKE_VOLUME_PATH)
        drv._is_share_eligible = mock.Mock(return_value=is_eligible)

        if has_snapshots:
            active = self._FAKE_SNAPSHOT_PATH
        else:
            active = self._FAKE_VOLUME_PATH

        drv.get_active_image_from_info = mock.Mock(return_value=active)
        if has_snapshots:
            self.assertRaises(exception.InvalidVolume,
                              drv._check_extend_volume_support,
                              self.vol, 2)
        elif not is_eligible:
            self.assertRaises(exception.ExtendVolumeError,
                              drv._check_extend_volume_support,
                              self.vol, 2)
        else:
            drv._check_extend_volume_support(self.vol, 2)
            drv._is_share_eligible.assert_called_once_with(self._FAKE_SHARE, 1)

    def test_check_extend_support(self):
        self._test_check_extend_support()

    def test_check_extend_volume_with_snapshots(self):
        self._test_check_extend_support(has_snapshots=True)

    def test_check_extend_volume_uneligible_share(self):
        self._test_check_extend_support(is_eligible=False)

    @mock.patch.object(image_utils, 'convert_image')
    def test_copy_volume_from_snapshot(self, mock_convert_image):
        drv = self._vz_driver

        fake_volume_info = {self._FAKE_SNAPSHOT_ID: 'fake_snapshot_file_name',
                            'backing-files':
                            {self._FAKE_SNAPSHOT_ID:
                             self._FAKE_VOLUME_NAME}}
        fake_img_info = mock.MagicMock()
        fake_img_info.backing_file = self._FAKE_VOLUME_NAME

        drv.get_volume_format = mock.Mock(return_value='raw')
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

        drv._copy_volume_from_snapshot(
            self.snap, self.vol,
            self.vol['size'])
        drv._extend_volume.assert_called_once_with(
            self.vol, self.vol['size'], 'raw')
        mock_convert_image.assert_called_once_with(
            self._FAKE_VOLUME_PATH, self._FAKE_VOLUME_PATH[:-1], 'raw')

    def test_delete_volume(self):
        drv = self._vz_driver
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
            drv.delete_volume(self.vol)

            fake_ensure_mounted.assert_called_once_with(self._FAKE_SHARE)
            drv._delete.assert_any_call(
                self._FAKE_VOLUME_PATH)
            drv._delete.assert_any_call(fake_vol_info)

    @mock.patch('cinder.volume.drivers.remotefs.RemoteFSSnapDriverBase.'
                '_write_info_file')
    def test_delete_snapshot_ploop(self, _mock_write_info_file):
        fake_snap_info = {
            'active': self._FAKE_VOLUME_NAME,
            self._FAKE_SNAPSHOT_ID: self._FAKE_SNAPSHOT_PATH,
        }
        self._vz_driver.get_volume_format = mock.Mock(
            return_value=vzstorage.DISK_FORMAT_PLOOP)
        self._vz_driver._read_info_file = mock.Mock(
            return_value=fake_snap_info
        )
        self._vz_driver._get_desc_path = mock.Mock(
            return_value='%s/DiskDescriptor.xml' % self._FAKE_VOLUME_PATH
        )
        self._vz_driver.delete_snapshot(self.snap)
        self._vz_driver._execute.assert_called_once_with(
            'ploop', 'snapshot-delete', '-u',
            '{%s}' % self._FAKE_SNAPSHOT_ID,
            '%s/DiskDescriptor.xml' % self._FAKE_VOLUME_PATH,
            run_as_root=True
        )

    @mock.patch('cinder.volume.drivers.remotefs.RemoteFSSnapDriverBase.'
                '_delete_snapshot')
    def test_delete_snapshot_qcow2_invalid_snap_info(self,
                                                     mock_delete_snapshot):
        fake_snap_info = {
            'active': self._FAKE_VOLUME_NAME,
        }
        self._vz_driver.get_volume_format = mock.Mock(
            return_value=vzstorage.DISK_FORMAT_QCOW2)
        self._vz_driver._read_info_file = mock.Mock(
            return_value=fake_snap_info
        )
        self._vz_driver.delete_snapshot(self.snap)
        self.assertFalse(mock_delete_snapshot.called)

    def test_extend_volume_ploop(self):
        drv = self._vz_driver
        drv.local_path = mock.Mock(
            return_value=self._FAKE_VOLUME_PATH)
        drv.get_volume_format = mock.Mock(
            return_value=vzstorage.DISK_FORMAT_PLOOP)
        drv._is_share_eligible = mock.Mock(
            return_value=True)
        drv.extend_volume(self.vol, 100)
        drv._execute.assert_called_once_with(
            'ploop', 'resize', '-s', '100G',
            '%s/DiskDescriptor.xml' % self._FAKE_VOLUME_PATH,
            run_as_root=True)
