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

import collections
import copy
import ddt
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


@ddt.ddt
class VZStorageTestCase(test.TestCase):

    _FAKE_SHARE = "10.0.0.1,10.0.0.2:/cluster123:123123"
    _FAKE_MNT_BASE = '/mnt'
    _FAKE_MNT_POINT = os.path.join(_FAKE_MNT_BASE, 'fake_hash')
    _FAKE_VOLUME_NAME = 'volume-4f711859-4928-4cb7-801a-a50c37ceaccc'
    _FAKE_VOLUME_PATH = os.path.join(_FAKE_MNT_POINT, _FAKE_VOLUME_NAME)
    _FAKE_SNAPSHOT_ID = '50811859-4928-4cb7-801a-a50c37ceacba'
    _FAKE_SNAPSHOT_PATH = (
        _FAKE_VOLUME_PATH + '-snapshot' + _FAKE_SNAPSHOT_ID)

    def setUp(self):
        super(VZStorageTestCase, self).setUp()

        self._cfg = mock.MagicMock()
        self._cfg.vzstorage_shares_config = '/fake/config/path'
        self._cfg.vzstorage_sparsed_volumes = False
        self._cfg.vzstorage_used_ratio = 0.7
        self._cfg.vzstorage_mount_point_base = self._FAKE_MNT_BASE
        self._cfg.vzstorage_default_volume_format = 'raw'
        self._cfg.nas_secure_file_operations = 'auto'
        self._cfg.nas_secure_file_permissions = 'auto'

        self._vz_driver = vzstorage.VZStorageDriver(configuration=self._cfg)
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
        if path.startswith(self._cfg.vzstorage_shares_config):
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
        self._cfg.vzstorage_mount_point_base = './tmp'
        vz_driver = vzstorage.VZStorageDriver(configuration=self._cfg)
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

    @ddt.data({'qemu_fmt': 'parallels', 'glance_fmt': 'ploop'},
              {'qemu_fmt': 'qcow2', 'glance_fmt': 'qcow2'})
    @ddt.unpack
    def test_initialize_connection(self, qemu_fmt, glance_fmt):
        drv = self._vz_driver
        info = mock.Mock()
        info.file_format = qemu_fmt
        snap_info = """{"volume_format": "%s",
                        "active": "%s"}""" % (qemu_fmt, self.vol.id)
        with mock.patch.object(drv, '_qemu_img_info', return_value=info):
            with mock.patch.object(drv, '_read_file',
                                   return_value=snap_info):
                ret = drv.initialize_connection(self.vol, None)
        name = drv.get_active_image_from_info(self.vol)
        expected = {'driver_volume_type': 'vzstorage',
                    'data': {'export': self._FAKE_SHARE,
                             'format': glance_fmt,
                             'name': name},
                    'mount_point_base': self._FAKE_MNT_BASE}
        self.assertEqual(expected, ret)

    def test_ensure_share_mounted_invalid_share(self):
        self.assertRaises(exception.VzStorageException,
                          self._vz_driver._ensure_share_mounted, ':')

    @mock.patch.object(remotefs.RemoteFsClient, 'mount')
    def test_ensure_share_mounted(self, mock_mount):
        drv = self._vz_driver
        share = 'test'
        expected_calls = [
            mock.call(share, ['-u', 'cinder', '-g', 'root', '-l',
                              '/var/log/vstorage/%s/cinder.log.gz' % share]),
            mock.call(share, ['-l', '/var/log/dummy.log'])
        ]

        share_flags = '["-u", "cinder", "-g", "root"]'
        drv.shares[share] = share_flags
        drv._ensure_share_mounted(share)

        share_flags = '["-l", "/var/log/dummy.log"]'
        drv.shares[share] = share_flags
        drv._ensure_share_mounted(share)

        mock_mount.assert_has_calls(expected_calls)

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
            with mock.patch.object(drv, 'get_active_image_from_info',
                                   return_value=self._FAKE_VOLUME_PATH):
                with mock.patch.object(drv, '_read_file',
                                       return_value=snap_info):
                    drv.extend_volume(self.vol, 10)

        mock_resize_image.assert_called_once_with(self._FAKE_VOLUME_PATH, 10)

    def _test_check_extend_support(self, is_eligible=True):
        drv = self._vz_driver
        drv.local_path = mock.Mock(return_value=self._FAKE_VOLUME_PATH)
        drv._is_share_eligible = mock.Mock(return_value=is_eligible)

        active = self._FAKE_VOLUME_PATH

        drv.get_active_image_from_info = mock.Mock(return_value=active)
        if not is_eligible:
            self.assertRaises(exception.ExtendVolumeError,
                              drv._check_extend_volume_support,
                              self.vol, 2)
        else:
            drv._check_extend_volume_support(self.vol, 2)
            drv._is_share_eligible.assert_called_once_with(self._FAKE_SHARE, 1)

    def test_check_extend_support(self):
        self._test_check_extend_support()

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
        drv.get_active_image_from_info = mock.Mock(
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

    @mock.patch.object(os.path, 'exists', return_value=False)
    def test_do_create_volume_with_volume_type(self, mock_exists):
        drv = self._vz_driver
        drv.local_path = mock.Mock(
            return_value=self._FAKE_VOLUME_PATH)
        drv._write_info_file = mock.Mock()
        drv._qemu_img_info = mock.Mock()
        drv._create_qcow2_file = mock.Mock()
        drv._create_ploop = mock.Mock()

        volume_type = fake_volume.fake_volume_type_obj(self.context)
        volume_type.extra_specs = {
            'vz:volume_format': 'qcow2'
        }
        volume1 = fake_volume.fake_volume_obj(self.context)
        volume1.size = 1024
        volume1.volume_type = volume_type
        volume2 = copy.deepcopy(volume1)
        volume2.metadata = {
            'volume_format': 'ploop'
        }

        drv._do_create_volume(volume1)
        drv._create_qcow2_file.assert_called_once_with(
            self._FAKE_VOLUME_PATH, 1024)

        drv._do_create_volume(volume2)
        drv._create_ploop.assert_called_once_with(
            self._FAKE_VOLUME_PATH, 1024)

    @mock.patch('cinder.volume.drivers.remotefs.RemoteFSSnapDriver.'
                '_create_cloned_volume')
    @mock.patch.object(vzstorage.VZStorageDriver, 'get_volume_format',
                       return_value='qcow2')
    def test_create_cloned_volume_qcow2(self,
                                        mock_get_volume_format,
                                        mock_remotefs_create_cloned_volume,
                                        ):
        drv = self._vz_driver
        volume = fake_volume.fake_volume_obj(self.context)
        src_vref_id = '375e32b2-804a-49f2-b282-85d1d5a5b9e1'
        src_vref = fake_volume.fake_volume_obj(
            self.context,
            id=src_vref_id,
            name='volume-%s' % src_vref_id,
            provider_location=self._FAKE_SHARE)
        src_vref.context = self.context

        mock_remotefs_create_cloned_volume.return_value = {
            'provider_location': self._FAKE_SHARE}
        ret = drv.create_cloned_volume(volume, src_vref)
        mock_remotefs_create_cloned_volume.assert_called_once_with(
            volume, src_vref)
        self.assertEqual(ret, {'provider_location': self._FAKE_SHARE})

    @mock.patch.object(vzstorage.VZStorageDriver, '_local_path_volume_info')
    @mock.patch.object(vzstorage.VZStorageDriver, '_create_snapshot_ploop')
    @mock.patch.object(vzstorage.VZStorageDriver, 'delete_snapshot')
    @mock.patch.object(vzstorage.VZStorageDriver, '_write_info_file')
    @mock.patch.object(vzstorage.VZStorageDriver, '_copy_volume_from_snapshot')
    @mock.patch.object(vzstorage.VZStorageDriver, 'get_volume_format',
                       return_value='ploop')
    def test_create_cloned_volume_ploop(self,
                                        mock_get_volume_format,
                                        mock_copy_volume_from_snapshot,
                                        mock_write_info_file,
                                        mock_delete_snapshot,
                                        mock_create_snapshot_ploop,
                                        mock_local_path_volume_info,
                                        ):
        drv = self._vz_driver
        volume = fake_volume.fake_volume_obj(self.context)
        src_vref_id = '375e32b2-804a-49f2-b282-85d1d5a5b9e1'
        src_vref = fake_volume.fake_volume_obj(
            self.context,
            id=src_vref_id,
            name='volume-%s' % src_vref_id,
            provider_location=self._FAKE_SHARE)
        src_vref.context = self.context

        snap_attrs = ['volume_name', 'size', 'volume_size', 'name',
                      'volume_id', 'id', 'volume']
        Snapshot = collections.namedtuple('Snapshot', snap_attrs)

        snap_ref = Snapshot(volume_name=volume.name,
                            name='clone-snap-%s' % src_vref.id,
                            size=src_vref.size,
                            volume_size=src_vref.size,
                            volume_id=src_vref.id,
                            id=src_vref.id,
                            volume=src_vref)

        def _check_provider_location(volume):
            self.assertEqual(volume.provider_location, self._FAKE_SHARE)
            return mock.sentinel.fake_info_path
        mock_local_path_volume_info.side_effect = _check_provider_location

        ret = drv.create_cloned_volume(volume, src_vref)
        self.assertEqual(ret, {'provider_location': self._FAKE_SHARE})

        mock_write_info_file.assert_called_once_with(
            mock.sentinel.fake_info_path, {'active': 'volume-%s' % volume.id})
        mock_create_snapshot_ploop.assert_called_once_with(snap_ref)
        mock_copy_volume_from_snapshot.assert_called_once_with(
            snap_ref, volume, volume.size)
        mock_delete_snapshot.assert_called_once_with(snap_ref)
