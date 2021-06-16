# Copyright (c) 2021 Dell Inc. or its subsidiaries.
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.
import errno
import os
from unittest import mock

import ddt
from oslo_concurrency import processutils as putils
from oslo_utils import imageutils
from oslo_utils import units

from cinder import context
from cinder import exception
from cinder.image import image_utils
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume
from cinder.tests.unit import test
from cinder.volume import configuration as conf
from cinder.volume.drivers.dell_emc.powerstore import nfs
from cinder.volume import volume_utils


NFS_CONFIG = {'max_over_subscription_ratio': 1.0,
              'reserved_percentage': 0,
              'nfs_sparsed_volumes': True,
              'nfs_qcow2_volumes': False,
              'nas_secure_file_permissions': 'false',
              'nas_secure_file_operations': 'false'}


QEMU_IMG_INFO_OUT1 = """image: %(volid)s
        file format: raw
        virtual size: %(size_gb)sG (%(size_b)s bytes)
        disk size: 173K
        """

QEMU_IMG_INFO_OUT2 = """image: %(volid)s
        file format: qcow2
        virtual size: %(size_gb)sG (%(size_b)s bytes)
        disk size: 173K
        """

QEMU_IMG_INFO_OUT3 = """image: volume-%(volid)s.%(snapid)s
        file format: qcow2
        virtual size: %(size_gb)sG (%(size_b)s bytes)
        disk size: 196K
        cluster_size: 65536
        backing file: volume-%(volid)s
        backing file format: qcow2
        Format specific information:
            compat: 1.1
            lazy refcounts: false
            refcount bits: 16
            corrupt: false
        """


@ddt.ddt
class PowerStoreNFSDriverInitializeTestCase(test.TestCase):
    TEST_NFS_HOST = 'nfs-host1'

    def setUp(self):
        super(PowerStoreNFSDriverInitializeTestCase, self).setUp()
        self.context = mock.Mock()
        self.create_configuration()
        self.override_config('compute_api_class', 'unittest.mock.Mock')
        self.drv = nfs.PowerStoreNFSDriverInitialization(
            configuration=self.configuration)

    def create_configuration(self):
        config = conf.Configuration(None)
        config.append_config_values(nfs.nfs_opts)
        self.configuration = config

    def test_check_multiattach_support(self):
        drv = self.drv

        self.configuration.nfs_qcow2_volumes = False

        drv._check_multiattach_support()
        self.assertEqual(not self.configuration.nfs_qcow2_volumes,
                         drv.multiattach_support)

    def test_check_multiattach_support_disable(self):
        drv = self.drv
        drv.configuration.nfs_qcow2_volumes = True

        drv._check_multiattach_support()
        self.assertEqual(not self.configuration.nfs_qcow2_volumes,
                         drv.multiattach_support)

    def test_check_snapshot_support(self):
        drv = self.drv
        drv.configuration.nfs_snapshot_support = True
        drv.configuration.nas_secure_file_operations = 'false'

        drv._check_snapshot_support()

        self.assertTrue(drv.configuration.nfs_snapshot_support)

    def test_check_snapshot_support_disable(self):
        drv = self.drv
        drv.configuration.nfs_snapshot_support = False
        drv.configuration.nas_secure_file_operations = 'false'

        self.assertRaises(exception.VolumeDriverException,
                          drv._check_snapshot_support)

    def test_check_snapshot_support_nas_true(self):
        drv = self.drv
        drv.configuration.nfs_snapshot_support = True
        drv.configuration.nas_secure_file_operations = 'true'

        self.assertRaises(exception.VolumeDriverException,
                          drv._check_snapshot_support)

    @mock.patch("cinder.volume.drivers.nfs.NfsDriver.do_setup")
    def test_do_setup(self, mock_super_do_setup):
        drv = self.drv
        drv.configuration.nas_host = self.TEST_NFS_HOST

        mock_check_multiattach_support = self.mock_object(
            drv, '_check_multiattach_support'
        )

        drv.do_setup(self.context)

        self.assertTrue(mock_check_multiattach_support.called)

    def test_check_package_is_installed(self):
        drv = self.drv
        package = 'dellfcopy'
        mock_execute = self.mock_object(drv, '_execute')
        drv._check_package_is_installed(package)
        mock_execute.assert_called_once_with(package,
                                             check_exit_code=False,
                                             run_as_root=False)

    def test_check_package_is_not_installed(self):
        drv = self.drv
        package = 'dellfcopy'
        drv._execute = mock.Mock(
            side_effect=OSError(
                errno.ENOENT, 'No such file or directory'
            )
        )
        self.assertRaises(exception.VolumeDriverException,
                          drv._check_package_is_installed, package)
        drv._execute.assert_called_once_with(package,
                                             check_exit_code=False,
                                             run_as_root=False)

    def test_check_for_setup_error(self):
        drv = self.drv
        mock_check_package_is_installed = self.mock_object(
            drv, '_check_package_is_installed')
        drv.check_for_setup_error()
        mock_check_package_is_installed.assert_called_once_with('dellfcopy')

    def test_check_for_setup_error_not_passed(self):
        drv = self.drv
        drv._execute = mock.Mock(
            side_effect=OSError(
                errno.ENOENT, 'No such file or directory'
            )
        )
        self.assertRaises(exception.VolumeDriverException,
                          drv.check_for_setup_error)
        drv._execute.assert_called_once_with('dellfcopy',
                                             check_exit_code=False,
                                             run_as_root=False)

    def test_update_volume_stats_has_multiattach(self):
        drv = self.drv

        self.mock_object(nfs.NfsDriver, '_update_volume_stats')
        drv.multiattach_support = True
        drv._stats = {}

        drv._update_volume_stats()

        self.assertIn('multiattach', drv._stats)
        self.assertTrue(drv._stats['multiattach'])


@ddt.ddt
class PowerStoreNFSDriverTestCase(test.TestCase):
    TEST_NFS_HOST = 'nfs-host1'
    TEST_NFS_SHARE_PATH = '/export'
    TEST_NFS_EXPORT = '%s:%s' % (TEST_NFS_HOST, TEST_NFS_SHARE_PATH)
    TEST_SIZE_IN_GB = 1
    TEST_MNT_POINT = '/mnt/nfs'
    TEST_MNT_POINT_BASE_EXTRA_SLASH = '/opt/stack/data/cinder//mnt'
    TEST_MNT_POINT_BASE = '/mnt/test'
    TEST_LOCAL_PATH = '/mnt/nfs/volume-123'
    TEST_FILE_NAME = 'test.txt'
    VOLUME_UUID = 'abcdefab-cdef-abcd-efab-cdefabcdefab'

    def setUp(self):
        super(PowerStoreNFSDriverTestCase, self).setUp()

        self.configuration = mock.Mock(conf.Configuration)
        self.configuration.append_config_values(mock.ANY)
        self.configuration.nfs_sparsed_volumes = True
        self.configuration.nas_secure_file_permissions = 'false'
        self.configuration.nas_secure_file_operations = 'false'
        self.configuration.nfs_mount_point_base = self.TEST_MNT_POINT_BASE
        self.configuration.nfs_snapshot_support = True
        self.configuration.max_over_subscription_ratio = 1.0
        self.configuration.reserved_percentage = 5
        self.configuration.nfs_mount_options = None
        self.configuration.nfs_qcow2_volumes = True
        self.configuration.nas_host = '0.0.0.0'
        self.configuration.nas_share_path = None

        self.mock_object(volume_utils, 'get_max_over_subscription_ratio',
                         return_value=1)
        self.context = context.get_admin_context()

        self._driver = nfs.PowerStoreNFSDriver(
            configuration=self.configuration)
        self._driver.shares = {}
        self.mock_object(self._driver, '_execute')

    def test_do_fast_clone_file(self):
        drv = self._driver
        volume_path = 'fake/path'
        new_volume_path = 'fake/new_path'

        drv._do_fast_clone_file(volume_path, new_volume_path)

        drv._execute.assert_called_once_with(
            'dellfcopy', '-o', 'fastclone', '-s', volume_path, '-d',
            new_volume_path, '-v', '1', run_as_root=True
        )

    def test_do_fast_clone_file_raise_error(self):
        drv = self._driver
        volume_path = 'fake/path'
        new_volume_path = 'fake/new_path'

        drv._execute = mock.Mock(
            side_effect=putils.ProcessExecutionError()
        )
        self.assertRaises(putils.ProcessExecutionError,
                          drv._do_fast_clone_file, volume_path,
                          new_volume_path)
        drv._execute.assert_called_once_with(
            'dellfcopy', '-o', 'fastclone', '-s', volume_path, '-d',
            new_volume_path, '-v', '1', run_as_root=True
        )

    def _simple_volume(self, **kwargs):
        updates = {'id': self.VOLUME_UUID,
                   'provider_location': self.TEST_NFS_EXPORT,
                   'display_name': f'volume-{self.VOLUME_UUID}',
                   'name': f'volume-{self.VOLUME_UUID}',
                   'size': 10,
                   'status': 'available'}

        updates.update(kwargs)
        if 'display_name' not in updates:
            updates['display_name'] = 'volume-%s' % updates['id']

        return fake_volume.fake_volume_obj(self.context, **updates)

    def test_delete_volume_without_info(self):
        drv = self._driver
        volume = fake_volume.fake_volume_obj(
            self.context,
            display_name='volume',
            provider_location=self.TEST_NFS_EXPORT
        )
        vol_path = '/path/to/vol'

        mock_ensure_share_mounted = self.mock_object(
            drv, '_ensure_share_mounted')
        mock_local_path_volume_info = self.mock_object(
            drv, '_local_path_volume_info'
        )
        mock_local_path_volume_info.return_value = self.TEST_LOCAL_PATH
        mock_read_info_file = self.mock_object(drv, '_read_info_file')
        mock_read_info_file.return_value = {}
        mock_local_path_volume = self.mock_object(drv, '_local_path_volume')
        mock_local_path_volume.return_value = vol_path

        drv.delete_volume(volume)

        mock_ensure_share_mounted.assert_called_once_with(
            self.TEST_NFS_EXPORT)
        mock_local_path_volume.assert_called_once_with(volume)
        mock_read_info_file.assert_called_once_with(
            self.TEST_LOCAL_PATH, empty_if_missing=True)
        mock_local_path_volume.assert_called_once_with(volume)
        drv._execute.assert_called_once_with(
            'rm', '-f', vol_path, run_as_root=True)

    def test_delete_volume_with_info(self):
        drv = self._driver
        volume = fake_volume.fake_volume_obj(
            self.context,
            display_name='volume',
            provider_location=self.TEST_NFS_EXPORT
        )
        vol_path = '/path/to/vol'
        with mock.patch.object(drv, '_ensure_share_mounted'):
            mock_local_path_volume_info = self.mock_object(
                drv, '_local_path_volume_info'
            )
            mock_local_path_volume_info.return_value = self.TEST_LOCAL_PATH
            mock_read_info_file = self.mock_object(drv, '_read_info_file')
            mock_read_info_file.return_value = {'active': '/path/to/active'}
            mock_local_path_volume = self.mock_object(
                drv, '_local_path_volume')
            mock_local_path_volume.return_value = vol_path

            drv.delete_volume(volume)

        self.assertEqual(drv._execute.call_count, 3)

    def test_delete_volume_without_provider_location(self):
        drv = self._driver
        volume = fake_volume.fake_volume_obj(
            self.context,
            display_name='volume',
            provider_location=''
        )
        drv.delete_volume(volume)

        self.assertFalse(bool(drv._execute.call_count))

    @ddt.data([None, QEMU_IMG_INFO_OUT1],
              ['raw', QEMU_IMG_INFO_OUT1],
              ['qcow2', QEMU_IMG_INFO_OUT2])
    @ddt.unpack
    @mock.patch('cinder.objects.volume.Volume.get_by_id')
    def test_extend_volume(self, file_format, qemu_img_info, mock_get):
        drv = self._driver
        volume = fake_volume.fake_volume_obj(
            self.context,
            id='80ee16b6-75d2-4d54-9539-ffc1b4b0fb10',
            size=1,
            provider_location='nfs_share')
        if file_format:
            volume.admin_metadata = {'format': file_format}
        mock_get.return_value = volume
        path = 'path'
        new_size = volume['size'] + 1

        mock_img_utils = self.mock_object(drv, '_qemu_img_info')
        img_out = qemu_img_info % {'volid': volume.id,
                                   'size_gb': volume.size,
                                   'size_b': volume.size * units.Gi}
        mock_img_utils.return_value = imageutils.QemuImgInfo(
            img_out)

        with mock.patch.object(image_utils, 'resize_image') as resize:
            with mock.patch.object(drv, 'local_path', return_value=path):
                with mock.patch.object(drv, '_is_share_eligible',
                                       return_value=True):

                    drv.extend_volume(volume, new_size)

                    resize.assert_called_once_with(path, new_size)

    def test_create_volume_from_snapshot(self):
        drv = self._driver
        src_volume = self._simple_volume(size=10)
        src_volume.id = fake.VOLUME_ID

        fake_snap = fake_snapshot.fake_snapshot_obj(self.context)
        fake_snap.volume = src_volume
        fake_snap.size = 10
        fake_snap.status = 'available'

        new_volume = self._simple_volume(size=src_volume.size)

        drv._find_share = mock.Mock(return_value=self.TEST_NFS_EXPORT)
        drv._copy_volume_from_snapshot = mock.Mock()

        drv._create_volume_from_snapshot(new_volume, fake_snap)

        drv._find_share.assert_called_once_with(new_volume)
        drv._copy_volume_from_snapshot.assert_called_once_with(
            fake_snap, new_volume, new_volume.size
        )

    @mock.patch('cinder.objects.volume.Volume.get_by_id')
    def test_create_cloned_volume(self, mock_get):
        drv = self._driver
        volume = self._simple_volume()
        mock_get.return_value = volume
        vol_dir = os.path.join(self.TEST_MNT_POINT_BASE,
                               drv._get_hash_str(volume.provider_location))
        vol_path = os.path.join(vol_dir, volume.name)

        new_volume = self._simple_volume()
        new_vol_dir = os.path.join(self.TEST_MNT_POINT_BASE,
                                   drv._get_hash_str(
                                       volume.provider_location))
        new_vol_path = os.path.join(new_vol_dir, volume.name)

        drv._create_cloned_volume(new_volume, volume, self.context)

        command = ['dellfcopy', '-o', 'fastclone', '-s', vol_path,
                   '-d', new_vol_path, '-v', '1']
        calls = [mock.call(*command, run_as_root=True)]
        drv._execute.assert_has_calls(calls)

    @ddt.data([QEMU_IMG_INFO_OUT3])
    @ddt.unpack
    @mock.patch('cinder.objects.volume.Volume.save')
    def test_copy_volume_from_snapshot(self, qemu_img_info, mock_save):
        drv = self._driver
        src_volume = self._simple_volume(size=10)
        src_volume.id = fake.VOLUME_ID

        fake_snap = fake_snapshot.fake_snapshot_obj(self.context)
        snap_file = src_volume.name + '.' + fake_snap.id
        fake_snap.volume = src_volume
        fake_snap.size = 10
        fake_source_vol_path = os.path.join(
            drv._local_volume_dir(fake_snap.volume),
            src_volume.name
        )

        new_volume = self._simple_volume(size=10)
        new_vol_dir = os.path.join(self.TEST_MNT_POINT_BASE,
                                   drv._get_hash_str(
                                       src_volume.provider_location))
        new_vol_path = os.path.join(new_vol_dir, new_volume.name)

        mock_read_info_file = self.mock_object(drv, '_read_info_file')
        mock_read_info_file.return_value = {'active': snap_file,
                                            fake_snap.id: snap_file}

        mock_img_utils = self.mock_object(drv, '_qemu_img_info')
        img_out = qemu_img_info % {'volid': src_volume.id,
                                   'snapid': fake_snap.id,
                                   'size_gb': src_volume.size,
                                   'size_b': src_volume.size * units.Gi}
        mock_img_utils.return_value = imageutils.QemuImgInfo(img_out)

        drv._copy_volume_from_snapshot(fake_snap, new_volume, new_volume.size)

        command = ['dellfcopy', '-o', 'fastclone', '-s', fake_source_vol_path,
                   '-d', new_vol_path, '-v', '1']
        calls = [mock.call(*command, run_as_root=True)]
        drv._execute.assert_has_calls(calls)
