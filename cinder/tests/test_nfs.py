# Copyright (c) 2012 NetApp, Inc.
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
"""Unit tests for the NFS driver module."""

import errno
import os

import mock
import mox as mox_lib
from mox import stubout
from oslo_utils import units

from cinder import context
from cinder import exception
from cinder.image import image_utils
from cinder import test
from cinder.volume import configuration as conf
from cinder.volume.drivers import nfs
from cinder.volume.drivers import remotefs


class DumbVolume(object):
    fields = {}

    def __setitem__(self, key, value):
        self.fields[key] = value

    def __getitem__(self, item):
        return self.fields[item]


class RemoteFsDriverTestCase(test.TestCase):
    TEST_FILE_NAME = 'test.txt'
    TEST_EXPORT = 'nas-host1:/export'
    TEST_MNT_POINT = '/mnt/nas'

    def setUp(self):
        super(RemoteFsDriverTestCase, self).setUp()
        self._driver = remotefs.RemoteFSDriver()
        self._mox = mox_lib.Mox()
        self.configuration = mox_lib.MockObject(conf.Configuration)
        self.configuration.append_config_values(mox_lib.IgnoreArg())
        self.configuration.nas_secure_file_permissions = 'false'
        self.configuration.nas_secure_file_operations = 'false'
        self._driver = remotefs.RemoteFSDriver(
            configuration=self.configuration)
        self.addCleanup(self._mox.UnsetStubs)

    def test_create_sparsed_file(self):
        (mox, drv) = self._mox, self._driver

        mox.StubOutWithMock(drv, '_execute')
        drv._execute('truncate', '-s', '1G', '/path', run_as_root=True).\
            AndReturn("")

        mox.ReplayAll()

        drv._create_sparsed_file('/path', 1)

        mox.VerifyAll()

    def test_create_regular_file(self):
        (mox, drv) = self._mox, self._driver

        mox.StubOutWithMock(drv, '_execute')
        drv._execute('dd', 'if=/dev/zero', 'of=/path', 'bs=1M', 'count=1024',
                     run_as_root=True)

        mox.ReplayAll()

        drv._create_regular_file('/path', 1)

        mox.VerifyAll()

    def test_create_qcow2_file(self):
        (mox, drv) = self._mox, self._driver

        file_size = 1

        mox.StubOutWithMock(drv, '_execute')
        drv._execute('qemu-img', 'create', '-f', 'qcow2',
                     '-o', 'preallocation=metadata', '/path',
                     '%s' % str(file_size * units.Gi), run_as_root=True)

        mox.ReplayAll()

        drv._create_qcow2_file('/path', file_size)

        mox.VerifyAll()

    def test_set_rw_permissions_for_all(self):
        (mox, drv) = self._mox, self._driver

        mox.StubOutWithMock(drv, '_execute')
        drv._execute('chmod', 'ugo+rw', '/path', run_as_root=True)

        mox.ReplayAll()

        drv._set_rw_permissions_for_all('/path')

        mox.VerifyAll()

    @mock.patch.object(remotefs, 'LOG')
    def test_set_rw_permissions_with_secure_file_permissions(self, LOG):
        drv = self._driver
        drv._mounted_shares = [self.TEST_EXPORT]
        drv.configuration.nas_secure_file_permissions = 'true'
        self.stubs.Set(drv, '_execute', mock.Mock())

        drv._set_rw_permissions(self.TEST_FILE_NAME)

        self.assertFalse(LOG.warn.called)

    @mock.patch.object(remotefs, 'LOG')
    def test_set_rw_permissions_without_secure_file_permissions(self, LOG):
        drv = self._driver
        self.configuration.nas_secure_file_permissions = 'false'
        self.stubs.Set(drv, '_execute', mock.Mock())

        drv._set_rw_permissions(self.TEST_FILE_NAME)

        self.assertTrue(LOG.warn.called)
        warn_msg = "%s is being set with open permissions: ugo+rw" % \
                   self.TEST_FILE_NAME
        LOG.warn.assert_called_once_with(warn_msg)

    @mock.patch('os.path.join')
    @mock.patch('os.path.isfile', return_value=False)
    def test_determine_nas_security_options_when_auto_and_new_install(
            self,
            mock_isfile,
            mock_join):
        """Test the setting of the NAS Security Option

         In this test case, we will create the marker file. No pre-exxisting
         Cinder volumes found during bootup.
         """
        drv = self._driver
        drv._mounted_shares = [self.TEST_EXPORT]
        file_path = '%s/.cinderSecureEnvIndicator' % self.TEST_MNT_POINT
        is_new_install = True

        drv._ensure_shares_mounted = mock.Mock()
        nas_mount = drv._get_mount_point_for_share = mock.Mock(
            return_value=self.TEST_MNT_POINT)
        mock_join.return_value = file_path

        secure_file_permissions = 'auto'
        nas_option = drv._determine_nas_security_option_setting(
            secure_file_permissions,
            nas_mount, is_new_install)

        self.assertEqual('true', nas_option)

        secure_file_operations = 'auto'
        nas_option = drv._determine_nas_security_option_setting(
            secure_file_operations,
            nas_mount, is_new_install)

        self.assertEqual('true', nas_option)

    @mock.patch('os.path.join')
    @mock.patch('os.path.isfile')
    def test_determine_nas_security_options_when_auto_and_new_install_exists(
            self,
            isfile,
            join):
        """Test the setting of the NAS Security Option

        In this test case, the marker file already exists. Cinder volumes
        found during bootup.
        """
        drv = self._driver
        drv._mounted_shares = [self.TEST_EXPORT]
        file_path = '%s/.cinderSecureEnvIndicator' % self.TEST_MNT_POINT
        is_new_install = False

        drv._ensure_shares_mounted = mock.Mock()
        nas_mount = drv._get_mount_point_for_share = mock.Mock(
            return_value=self.TEST_MNT_POINT)
        join.return_value = file_path
        isfile.return_value = True

        secure_file_permissions = 'auto'
        nas_option = drv._determine_nas_security_option_setting(
            secure_file_permissions,
            nas_mount, is_new_install)

        self.assertEqual('true', nas_option)

        secure_file_operations = 'auto'
        nas_option = drv._determine_nas_security_option_setting(
            secure_file_operations,
            nas_mount, is_new_install)

        self.assertEqual('true', nas_option)

    @mock.patch('os.path.join')
    @mock.patch('os.path.isfile')
    def test_determine_nas_security_options_when_auto_and_old_install(self,
                                                                      isfile,
                                                                      join):
        """Test the setting of the NAS Security Option

        In this test case, the marker file does not exist. There are also
        pre-existing Cinder volumes.
        """
        drv = self._driver
        drv._mounted_shares = [self.TEST_EXPORT]
        file_path = '%s/.cinderSecureEnvIndicator' % self.TEST_MNT_POINT
        is_new_install = False

        drv._ensure_shares_mounted = mock.Mock()
        nas_mount = drv._get_mount_point_for_share = mock.Mock(
            return_value=self.TEST_MNT_POINT)
        join.return_value = file_path
        isfile.return_value = False

        secure_file_permissions = 'auto'
        nas_option = drv._determine_nas_security_option_setting(
            secure_file_permissions,
            nas_mount, is_new_install)

        self.assertEqual('false', nas_option)

        secure_file_operations = 'auto'
        nas_option = drv._determine_nas_security_option_setting(
            secure_file_operations,
            nas_mount, is_new_install)

        self.assertEqual('false', nas_option)

    def test_determine_nas_security_options_when_admin_set_true(self):
        """Test the setting of the NAS Security Option

        In this test case, the Admin set the flag to 'true'.
        """
        drv = self._driver
        drv._mounted_shares = [self.TEST_EXPORT]
        is_new_install = False

        drv._ensure_shares_mounted = mock.Mock()
        nas_mount = drv._get_mount_point_for_share = mock.Mock(
            return_value=self.TEST_MNT_POINT)

        secure_file_permissions = 'true'
        nas_option = drv._determine_nas_security_option_setting(
            secure_file_permissions,
            nas_mount, is_new_install)

        self.assertEqual('true', nas_option)

        secure_file_operations = 'true'
        nas_option = drv._determine_nas_security_option_setting(
            secure_file_operations,
            nas_mount, is_new_install)

        self.assertEqual('true', nas_option)

    def test_determine_nas_security_options_when_admin_set_false(self):
        """Test the setting of the NAS Security Option

        In this test case, the Admin set the flag to 'true'.
        """
        drv = self._driver
        drv._mounted_shares = [self.TEST_EXPORT]
        is_new_install = False

        drv._ensure_shares_mounted = mock.Mock()
        nas_mount = drv._get_mount_point_for_share = mock.Mock(
            return_value=self.TEST_MNT_POINT)

        secure_file_permissions = 'false'
        nas_option = drv._determine_nas_security_option_setting(
            secure_file_permissions,
            nas_mount, is_new_install)

        self.assertEqual('false', nas_option)

        secure_file_operations = 'false'
        nas_option = drv._determine_nas_security_option_setting(
            secure_file_operations,
            nas_mount, is_new_install)

        self.assertEqual('false', nas_option)

    @mock.patch.object(remotefs, 'LOG')
    def test_set_nas_security_options(self, LOG):
        """Test setting of NAS Security options.

        The RemoteFS driver will force set options to false. The derived
        objects will provide an inherited interface to properly set options.
        """
        drv = self._driver
        is_new_install = False

        drv.set_nas_security_options(is_new_install)

        self.assertEqual('false', drv.configuration.nas_secure_file_operations)
        self.assertEqual('false',
                         drv.configuration.nas_secure_file_permissions)
        self.assertTrue(LOG.warn.called)

    def test_secure_file_operations_enabled_true(self):
        """Test nas_secure_file_operations = 'true'

        Networked file system based drivers may support secure file
        operations. This test verifies the settings when secure.
        """
        drv = self._driver
        self.configuration.nas_secure_file_operations = 'true'
        ret_flag = drv.secure_file_operations_enabled()
        self.assertTrue(ret_flag)

    def test_secure_file_operations_enabled_false(self):
        """Test nas_secure_file_operations = 'false'

        Networked file system based drivers may support secure file
        operations. This test verifies the settings when not secure.
        """
        drv = self._driver
        self.configuration.nas_secure_file_operations = 'false'
        ret_flag = drv.secure_file_operations_enabled()
        self.assertFalse(ret_flag)


class NfsDriverTestCase(test.TestCase):
    """Test case for NFS driver."""

    TEST_NFS_HOST = 'nfs-host1'
    TEST_NFS_SHARE_PATH = '/export'
    TEST_NFS_EXPORT1 = '%s:%s' % (TEST_NFS_HOST, TEST_NFS_SHARE_PATH)
    TEST_NFS_EXPORT2 = 'nfs-host2:/export'
    TEST_NFS_EXPORT2_OPTIONS = '-o intr'
    TEST_SIZE_IN_GB = 1
    TEST_MNT_POINT = '/mnt/nfs'
    TEST_MNT_POINT_BASE_EXTRA_SLASH = '/opt/stack/data/cinder//mnt'
    TEST_MNT_POINT_BASE = '/mnt/test'
    TEST_LOCAL_PATH = '/mnt/nfs/volume-123'
    TEST_FILE_NAME = 'test.txt'
    TEST_SHARES_CONFIG_FILE = '/etc/cinder/test-shares.conf'
    TEST_NFS_EXPORT_SPACES = 'nfs-host3:/export this'
    TEST_MNT_POINT_SPACES = '/ 0 0 0 /foo'

    def setUp(self):
        super(NfsDriverTestCase, self).setUp()
        self._mox = mox_lib.Mox()
        self.stubs = stubout.StubOutForTesting()
        self.configuration = mox_lib.MockObject(conf.Configuration)
        self.configuration.append_config_values(mox_lib.IgnoreArg())
        self.configuration.nfs_shares_config = None
        self.configuration.nfs_sparsed_volumes = True
        self.configuration.nfs_used_ratio = 0.95
        self.configuration.nfs_oversub_ratio = 1.0
        self.configuration.nfs_mount_point_base = self.TEST_MNT_POINT_BASE
        self.configuration.nfs_mount_options = None
        self.configuration.nfs_mount_attempts = 3
        self.configuration.nfs_qcow2_volumes = False
        self.configuration.nas_secure_file_permissions = 'false'
        self.configuration.nas_secure_file_operations = 'false'
        self.configuration.nas_ip = None
        self.configuration.nas_share_path = None
        self.configuration.nas_mount_options = None
        self.configuration.volume_dd_blocksize = '1M'
        self._driver = nfs.NfsDriver(configuration=self.configuration)
        self._driver.shares = {}
        self.addCleanup(self.stubs.UnsetAll)
        self.addCleanup(self._mox.UnsetStubs)

    def stub_out_not_replaying(self, obj, attr_name):
        attr_to_replace = getattr(obj, attr_name)
        stub = mox_lib.MockObject(attr_to_replace)
        self.stubs.Set(obj, attr_name, stub)

    def test_local_path(self):
        """local_path common use case."""
        self.configuration.nfs_mount_point_base = self.TEST_MNT_POINT_BASE
        drv = self._driver

        volume = DumbVolume()
        volume['provider_location'] = self.TEST_NFS_EXPORT1
        volume['name'] = 'volume-123'

        self.assertEqual(
            '/mnt/test/2f4f60214cf43c595666dd815f0360a4/volume-123',
            drv.local_path(volume))

    def test_copy_image_to_volume(self):
        """resize_image common case usage."""
        mox = self._mox
        drv = self._driver

        TEST_IMG_SOURCE = 'foo.img'

        volume = {'size': self.TEST_SIZE_IN_GB, 'name': TEST_IMG_SOURCE}

        def fake_local_path(volume):
            return volume['name']

        self.stubs.Set(drv, 'local_path', fake_local_path)

        mox.StubOutWithMock(image_utils, 'fetch_to_raw')
        image_utils.fetch_to_raw(None, None, None, TEST_IMG_SOURCE,
                                 mox_lib.IgnoreArg(),
                                 size=self.TEST_SIZE_IN_GB,
                                 run_as_root=True)

        mox.StubOutWithMock(image_utils, 'resize_image')
        image_utils.resize_image(TEST_IMG_SOURCE, self.TEST_SIZE_IN_GB,
                                 run_as_root=True)

        mox.StubOutWithMock(image_utils, 'qemu_img_info')
        data = mox_lib.MockAnything()
        data.virtual_size = 1 * units.Gi
        image_utils.qemu_img_info(TEST_IMG_SOURCE,
                                  run_as_root=True).AndReturn(data)

        mox.ReplayAll()

        drv.copy_image_to_volume(None, volume, None, None)

        mox.VerifyAll()

    def test_get_mount_point_for_share(self):
        """_get_mount_point_for_share should calculate correct value."""
        drv = self._driver

        self.configuration.nfs_mount_point_base = self.TEST_MNT_POINT_BASE

        self.assertEqual('/mnt/test/2f4f60214cf43c595666dd815f0360a4',
                         drv._get_mount_point_for_share(self.TEST_NFS_EXPORT1))

    def test_get_mount_point_for_share_given_extra_slash_in_state_path(self):
        """_get_mount_point_for_share should calculate correct value."""
        # This test gets called with the extra slash
        self.configuration.nfs_mount_point_base = (
            self.TEST_MNT_POINT_BASE_EXTRA_SLASH)

        # The driver gets called with the correct configuration and removes
        # the extra slash
        drv = nfs.NfsDriver(configuration=self.configuration)

        self.assertEqual('/opt/stack/data/cinder/mnt', drv.base)

        self.assertEqual(
            '/opt/stack/data/cinder/mnt/2f4f60214cf43c595666dd815f0360a4',
            drv._get_mount_point_for_share(self.TEST_NFS_EXPORT1))

    def test_get_capacity_info(self):
        """_get_capacity_info should calculate correct value."""
        mox = self._mox
        drv = self._driver

        stat_total_size = 2620544
        stat_avail = 2129984
        stat_output = '1 %d %d' % (stat_total_size, stat_avail)

        du_used = 490560
        du_output = '%d /mnt' % du_used

        mox.StubOutWithMock(drv, '_get_mount_point_for_share')
        drv._get_mount_point_for_share(self.TEST_NFS_EXPORT1).\
            AndReturn(self.TEST_MNT_POINT)

        mox.StubOutWithMock(drv, '_execute')
        drv._execute('stat', '-f', '-c', '%S %b %a',
                     self.TEST_MNT_POINT,
                     run_as_root=True).AndReturn((stat_output, None))

        drv._execute('du', '-sb', '--apparent-size',
                     '--exclude', '*snapshot*',
                     self.TEST_MNT_POINT,
                     run_as_root=True).AndReturn((du_output, None))

        mox.ReplayAll()

        self.assertEqual((stat_total_size, stat_avail, du_used),
                         drv._get_capacity_info(self.TEST_NFS_EXPORT1))

        mox.VerifyAll()

    def test_get_capacity_info_for_share_and_mount_point_with_spaces(self):
        """_get_capacity_info should calculate correct value."""
        mox = self._mox
        drv = self._driver

        stat_total_size = 2620544
        stat_avail = 2129984
        stat_output = '1 %d %d' % (stat_total_size, stat_avail)

        du_used = 490560
        du_output = '%d /mnt' % du_used

        mox.StubOutWithMock(drv, '_get_mount_point_for_share')
        drv._get_mount_point_for_share(self.TEST_NFS_EXPORT_SPACES).\
            AndReturn(self.TEST_MNT_POINT_SPACES)

        mox.StubOutWithMock(drv, '_execute')
        drv._execute('stat', '-f', '-c', '%S %b %a',
                     self.TEST_MNT_POINT_SPACES,
                     run_as_root=True).AndReturn((stat_output, None))

        drv._execute('du', '-sb', '--apparent-size',
                     '--exclude', '*snapshot*',
                     self.TEST_MNT_POINT_SPACES,
                     run_as_root=True).AndReturn((du_output, None))

        mox.ReplayAll()

        self.assertEqual((stat_total_size, stat_avail, du_used),
                         drv._get_capacity_info(self.TEST_NFS_EXPORT_SPACES))

        mox.VerifyAll()

    def test_load_shares_config(self):
        mox = self._mox
        drv = self._driver

        drv.configuration.nfs_shares_config = self.TEST_SHARES_CONFIG_FILE

        mox.StubOutWithMock(drv, '_read_config_file')
        config_data = []
        config_data.append(self.TEST_NFS_EXPORT1)
        config_data.append('#' + self.TEST_NFS_EXPORT2)
        config_data.append('')
        config_data.append(self.TEST_NFS_EXPORT2 + ' ' +
                           self.TEST_NFS_EXPORT2_OPTIONS)
        config_data.append('broken:share_format')
        drv._read_config_file(self.TEST_SHARES_CONFIG_FILE).\
            AndReturn(config_data)
        mox.ReplayAll()

        drv._load_shares_config(drv.configuration.nfs_shares_config)

        self.assertIn(self.TEST_NFS_EXPORT1, drv.shares)
        self.assertIn(self.TEST_NFS_EXPORT2, drv.shares)
        self.assertEqual(2, len(drv.shares))

        self.assertEqual(self.TEST_NFS_EXPORT2_OPTIONS,
                         drv.shares[self.TEST_NFS_EXPORT2])

        mox.VerifyAll()

    def test_load_shares_config_nas_opts(self):
        mox = self._mox
        drv = self._driver

        mox.StubOutWithMock(drv, '_read_config_file')  # ensure not called

        drv.configuration.nas_ip = self.TEST_NFS_HOST
        drv.configuration.nas_share_path = self.TEST_NFS_SHARE_PATH
        drv.configuration.nfs_shares_config = self.TEST_SHARES_CONFIG_FILE

        mox.ReplayAll()

        drv._load_shares_config(drv.configuration.nfs_shares_config)

        self.assertIn(self.TEST_NFS_EXPORT1, drv.shares)
        self.assertEqual(len(drv.shares), 1)

        mox.VerifyAll()

    def test_ensure_shares_mounted_should_save_mounting_successfully(self):
        """_ensure_shares_mounted should save share if mounted with success."""
        mox = self._mox
        drv = self._driver

        mox.StubOutWithMock(drv, '_read_config_file')
        config_data = []
        config_data.append(self.TEST_NFS_EXPORT1)
        drv._read_config_file(self.TEST_SHARES_CONFIG_FILE).\
            AndReturn(config_data)

        mox.StubOutWithMock(drv, '_ensure_share_mounted')
        drv.configuration.nfs_shares_config = self.TEST_SHARES_CONFIG_FILE
        drv._ensure_share_mounted(self.TEST_NFS_EXPORT1)

        mox.ReplayAll()

        drv._ensure_shares_mounted()

        self.assertEqual(1, len(drv._mounted_shares))
        self.assertEqual(self.TEST_NFS_EXPORT1, drv._mounted_shares[0])

        mox.VerifyAll()

    def test_ensure_shares_mounted_should_not_save_mounting_with_error(self):
        """_ensure_shares_mounted should not save share if failed to mount."""

        config_data = []
        config_data.append(self.TEST_NFS_EXPORT1)
        self._driver.configuration.nfs_shares_config =\
            self.TEST_SHARES_CONFIG_FILE

        self.mock_object(self._driver, '_read_config_file',
                         mock.Mock(return_value=config_data))
        self.mock_object(self._driver, '_ensure_share_mounted',
                         mock.Mock(side_effect=Exception()))
        self.mock_object(remotefs, 'LOG')

        self._driver._ensure_shares_mounted()

        self.assertEqual(0, len(self._driver._mounted_shares))
        self._driver._read_config_file.assert_called_once_with(
            self.TEST_SHARES_CONFIG_FILE)

        self._driver._ensure_share_mounted.assert_called_once_with(
            self.TEST_NFS_EXPORT1)

        self.assertEqual(1, remotefs.LOG.error.call_count)

    def test_setup_should_throw_error_if_shares_config_not_configured(self):
        """do_setup should throw error if shares config is not configured."""
        drv = self._driver
        self.configuration.nfs_shares_config = self.TEST_SHARES_CONFIG_FILE

        self.assertRaises(exception.NfsException,
                          drv.do_setup, mox_lib.IsA(context.RequestContext))

    def test_setup_should_throw_error_if_oversub_ratio_less_than_zero(self):
        """do_setup should throw error if nfs_oversub_ratio is less than 0."""
        drv = self._driver
        self.configuration.nfs_oversub_ratio = -1
        self.assertRaises(exception.NfsException,
                          drv.do_setup,
                          mox_lib.IsA(context.RequestContext))

    def test_setup_should_throw_error_if_used_ratio_less_than_zero(self):
        """do_setup should throw error if nfs_used_ratio is less than 0."""
        drv = self._driver
        self.configuration.nfs_used_ratio = -1
        self.assertRaises(exception.NfsException,
                          drv.do_setup,
                          mox_lib.IsA(context.RequestContext))

    def test_setup_should_throw_error_if_used_ratio_greater_than_one(self):
        """do_setup should throw error if nfs_used_ratio is greater than 1."""
        drv = self._driver
        self.configuration.nfs_used_ratio = 2
        self.assertRaises(exception.NfsException,
                          drv.do_setup,
                          mox_lib.IsA(context.RequestContext))

    def test_setup_should_throw_exception_if_nfs_client_is_not_installed(self):
        """do_setup should throw error if nfs client is not installed."""
        mox = self._mox
        drv = self._driver
        self.configuration.nfs_shares_config = self.TEST_SHARES_CONFIG_FILE
        mox.StubOutWithMock(os.path, 'exists')
        os.path.exists(self.TEST_SHARES_CONFIG_FILE).AndReturn(True)
        mox.StubOutWithMock(drv, '_execute')
        drv._execute('mount.nfs', check_exit_code=False, run_as_root=False).\
            AndRaise(OSError(errno.ENOENT, 'No such file or directory'))

        mox.ReplayAll()

        self.assertRaises(exception.NfsException,
                          drv.do_setup, mox_lib.IsA(context.RequestContext))

        mox.VerifyAll()

    def test_find_share_should_throw_error_if_there_is_no_mounted_shares(self):
        """_find_share should throw error if there is no mounted shares."""
        drv = self._driver

        drv._mounted_shares = []

        self.assertRaises(exception.NfsNoSharesMounted, drv._find_share,
                          self.TEST_SIZE_IN_GB)

    def test_find_share(self):
        """_find_share simple use case."""
        mox = self._mox
        drv = self._driver

        drv._mounted_shares = [self.TEST_NFS_EXPORT1, self.TEST_NFS_EXPORT2]

        mox.StubOutWithMock(drv, '_get_capacity_info')
        drv._get_capacity_info(self.TEST_NFS_EXPORT1).\
            AndReturn((5 * units.Gi, 2 * units.Gi,
                       2 * units.Gi))
        drv._get_capacity_info(self.TEST_NFS_EXPORT1).\
            AndReturn((5 * units.Gi, 2 * units.Gi,
                       2 * units.Gi))
        drv._get_capacity_info(self.TEST_NFS_EXPORT2).\
            AndReturn((10 * units.Gi, 3 * units.Gi,
                       1 * units.Gi))
        drv._get_capacity_info(self.TEST_NFS_EXPORT2).\
            AndReturn((10 * units.Gi, 3 * units.Gi,
                       1 * units.Gi))

        mox.ReplayAll()

        self.assertEqual(self.TEST_NFS_EXPORT2,
                         drv._find_share(self.TEST_SIZE_IN_GB))

        mox.VerifyAll()

    def test_find_share_should_throw_error_if_there_is_no_enough_place(self):
        """_find_share should throw error if there is no share to host vol."""
        mox = self._mox
        drv = self._driver

        drv._mounted_shares = [self.TEST_NFS_EXPORT1, self.TEST_NFS_EXPORT2]

        mox.StubOutWithMock(drv, '_get_capacity_info')
        drv._get_capacity_info(self.TEST_NFS_EXPORT1).\
            AndReturn((5 * units.Gi, 0, 5 * units.Gi))
        drv._get_capacity_info(self.TEST_NFS_EXPORT2).\
            AndReturn((10 * units.Gi, 0,
                       10 * units.Gi))

        mox.ReplayAll()

        self.assertRaises(exception.NfsNoSuitableShareFound, drv._find_share,
                          self.TEST_SIZE_IN_GB)

        mox.VerifyAll()

    def _simple_volume(self):
        volume = DumbVolume()
        volume['provider_location'] = '127.0.0.1:/mnt'
        volume['name'] = 'volume_name'
        volume['size'] = 10

        return volume

    def test_create_sparsed_volume(self):
        mox = self._mox
        drv = self._driver
        volume = self._simple_volume()

        self.override_config('nfs_sparsed_volumes', True)

        mox.StubOutWithMock(drv, '_create_sparsed_file')
        mox.StubOutWithMock(drv, '_set_rw_permissions')

        drv._create_sparsed_file(mox_lib.IgnoreArg(), mox_lib.IgnoreArg())
        drv._set_rw_permissions(mox_lib.IgnoreArg())

        mox.ReplayAll()

        drv._do_create_volume(volume)

        mox.VerifyAll()

    def test_create_nonsparsed_volume(self):
        mox = self._mox
        drv = self._driver
        self.configuration.nfs_sparsed_volumes = False
        volume = self._simple_volume()

        self.override_config('nfs_sparsed_volumes', False)

        mox.StubOutWithMock(drv, '_create_regular_file')
        mox.StubOutWithMock(drv, '_set_rw_permissions')

        drv._create_regular_file(mox_lib.IgnoreArg(), mox_lib.IgnoreArg())
        drv._set_rw_permissions(mox_lib.IgnoreArg())

        mox.ReplayAll()

        drv._do_create_volume(volume)

        mox.VerifyAll()

    def test_create_volume_should_ensure_nfs_mounted(self):
        """create_volume ensures shares provided in config are mounted."""
        mox = self._mox
        drv = self._driver

        self.stub_out_not_replaying(nfs, 'LOG')
        self.stub_out_not_replaying(drv, '_find_share')
        self.stub_out_not_replaying(drv, '_do_create_volume')

        mox.StubOutWithMock(drv, '_ensure_shares_mounted')
        drv._ensure_shares_mounted()

        mox.ReplayAll()

        volume = DumbVolume()
        volume['size'] = self.TEST_SIZE_IN_GB
        drv.create_volume(volume)

        mox.VerifyAll()

    def test_create_volume_should_return_provider_location(self):
        """create_volume should return provider_location with found share."""
        mox = self._mox
        drv = self._driver

        self.stub_out_not_replaying(nfs, 'LOG')
        self.stub_out_not_replaying(drv, '_ensure_shares_mounted')
        self.stub_out_not_replaying(drv, '_do_create_volume')

        mox.StubOutWithMock(drv, '_find_share')
        drv._find_share(self.TEST_SIZE_IN_GB).AndReturn(self.TEST_NFS_EXPORT1)

        mox.ReplayAll()

        volume = DumbVolume()
        volume['size'] = self.TEST_SIZE_IN_GB
        result = drv.create_volume(volume)
        self.assertEqual(self.TEST_NFS_EXPORT1, result['provider_location'])

        mox.VerifyAll()

    def test_delete_volume(self):
        """delete_volume simple test case."""
        mox = self._mox
        drv = self._driver

        self.stub_out_not_replaying(drv, '_ensure_share_mounted')

        volume = DumbVolume()
        volume['name'] = 'volume-123'
        volume['provider_location'] = self.TEST_NFS_EXPORT1

        mox.StubOutWithMock(drv, 'local_path')
        drv.local_path(volume).AndReturn(self.TEST_LOCAL_PATH)

        mox.StubOutWithMock(drv, '_execute')
        drv._execute('rm', '-f', self.TEST_LOCAL_PATH, run_as_root=True)

        mox.ReplayAll()

        drv.delete_volume(volume)

        mox.VerifyAll()

    def test_delete_should_ensure_share_mounted(self):
        """delete_volume should ensure that corresponding share is mounted."""
        mox = self._mox
        drv = self._driver

        self.stub_out_not_replaying(drv, '_execute')

        volume = DumbVolume()
        volume['name'] = 'volume-123'
        volume['provider_location'] = self.TEST_NFS_EXPORT1

        mox.StubOutWithMock(drv, '_ensure_share_mounted')
        drv._ensure_share_mounted(self.TEST_NFS_EXPORT1)

        mox.ReplayAll()

        drv.delete_volume(volume)

        mox.VerifyAll()

    def test_delete_should_not_delete_if_provider_location_not_provided(self):
        """delete_volume shouldn't delete if provider_location missed."""
        drv = self._driver

        self.stubs.Set(drv, '_ensure_share_mounted', mock.Mock())
        self.stubs.Set(drv, 'local_path', mock.Mock())

        volume = DumbVolume()
        volume['name'] = 'volume-123'
        volume['provider_location'] = None

        with mock.patch.object(drv, '_execute') as mock_execute:
            drv.delete_volume(volume)

            self.assertEqual(0, mock_execute.call_count)

    def test_get_volume_stats(self):
        """get_volume_stats must fill the correct values."""
        mox = self._mox
        drv = self._driver

        drv._mounted_shares = [self.TEST_NFS_EXPORT1, self.TEST_NFS_EXPORT2]

        mox.StubOutWithMock(drv, '_ensure_shares_mounted')
        mox.StubOutWithMock(drv, '_get_capacity_info')

        drv._ensure_shares_mounted()

        drv._get_capacity_info(self.TEST_NFS_EXPORT1).\
            AndReturn((10 * units.Gi, 2 * units.Gi,
                       2 * units.Gi))
        drv._get_capacity_info(self.TEST_NFS_EXPORT2).\
            AndReturn((20 * units.Gi, 3 * units.Gi,
                       3 * units.Gi))

        mox.ReplayAll()

        drv.get_volume_stats()
        self.assertEqual(30.0, drv._stats['total_capacity_gb'])
        self.assertEqual(5.0, drv._stats['free_capacity_gb'])

        mox.VerifyAll()

    def _check_is_share_eligible(self, total_size, total_available,
                                 total_allocated, requested_volume_size):
        with mock.patch.object(self._driver, '_get_capacity_info')\
                as mock_get_capacity_info:
            mock_get_capacity_info.return_value = (total_size,
                                                   total_available,
                                                   total_allocated)
            return self._driver._is_share_eligible('fake_share',
                                                   requested_volume_size)

    def test_is_share_eligible(self):
        total_size = 100.0 * units.Gi
        total_available = 90.0 * units.Gi
        total_allocated = 10.0 * units.Gi
        requested_volume_size = 1  # GiB

        self.assertTrue(self._check_is_share_eligible(total_size,
                                                      total_available,
                                                      total_allocated,
                                                      requested_volume_size))

    def test_is_share_eligible_above_used_ratio(self):
        total_size = 100.0 * units.Gi
        total_available = 4.0 * units.Gi
        total_allocated = 96.0 * units.Gi
        requested_volume_size = 1  # GiB

        # Check used > used_ratio statement entered
        self.assertFalse(self._check_is_share_eligible(total_size,
                                                       total_available,
                                                       total_allocated,
                                                       requested_volume_size))

    def test_is_share_eligible_above_oversub_ratio(self):
        total_size = 100.0 * units.Gi
        total_available = 10.0 * units.Gi
        total_allocated = 90.0 * units.Gi
        requested_volume_size = 10  # GiB

        # Check apparent_available <= requested_volume_size statement entered
        self.assertFalse(self._check_is_share_eligible(total_size,
                                                       total_available,
                                                       total_allocated,
                                                       requested_volume_size))

    def test_is_share_eligible_reserved_space_above_oversub_ratio(self):
        total_size = 100.0 * units.Gi
        total_available = 10.0 * units.Gi
        total_allocated = 100.0 * units.Gi
        requested_volume_size = 1  # GiB

        # Check total_allocated / total_size >= oversub_ratio
        # statement entered
        self.assertFalse(self._check_is_share_eligible(total_size,
                                                       total_available,
                                                       total_allocated,
                                                       requested_volume_size))

    def test_extend_volume(self):
        """Extend a volume by 1."""
        drv = self._driver
        volume = {'id': '80ee16b6-75d2-4d54-9539-ffc1b4b0fb10', 'size': 1,
                  'provider_location': 'nfs_share'}
        path = 'path'
        newSize = volume['size'] + 1

        with mock.patch.object(image_utils, 'resize_image') as resize:
            with mock.patch.object(drv, 'local_path', return_value=path):
                with mock.patch.object(drv, '_is_share_eligible',
                                       return_value=True):
                    with mock.patch.object(drv, '_is_file_size_equal',
                                           return_value=True):
                        drv.extend_volume(volume, newSize)

                        resize.assert_called_once_with(path, newSize,
                                                       run_as_root=True)

    def test_extend_volume_failure(self):
        """Error during extend operation."""
        drv = self._driver
        volume = {'id': '80ee16b6-75d2-4d54-9539-ffc1b4b0fb10', 'size': 1,
                  'provider_location': 'nfs_share'}

        with mock.patch.object(image_utils, 'resize_image'):
            with mock.patch.object(drv, 'local_path', return_value='path'):
                with mock.patch.object(drv, '_is_share_eligible',
                                       return_value=True):
                    with mock.patch.object(drv, '_is_file_size_equal',
                                           return_value=False):
                        self.assertRaises(exception.ExtendVolumeError,
                                          drv.extend_volume, volume, 2)

    def test_extend_volume_insufficient_space(self):
        """Insufficient space on nfs_share during extend operation."""
        drv = self._driver
        volume = {'id': '80ee16b6-75d2-4d54-9539-ffc1b4b0fb10', 'size': 1,
                  'provider_location': 'nfs_share'}

        with mock.patch.object(image_utils, 'resize_image'):
            with mock.patch.object(drv, 'local_path', return_value='path'):
                with mock.patch.object(drv, '_is_share_eligible',
                                       return_value=False):
                    with mock.patch.object(drv, '_is_file_size_equal',
                                           return_value=False):
                        self.assertRaises(exception.ExtendVolumeError,
                                          drv.extend_volume, volume, 2)

    def test_is_file_size_equal(self):
        """File sizes are equal."""
        drv = self._driver
        path = 'fake/path'
        size = 2
        data = mock.MagicMock()
        data.virtual_size = size * units.Gi

        with mock.patch.object(image_utils, 'qemu_img_info',
                               return_value=data):
            self.assertTrue(drv._is_file_size_equal(path, size))

    def test_is_file_size_equal_false(self):
        """File sizes are not equal."""
        drv = self._driver
        path = 'fake/path'
        size = 2
        data = mock.MagicMock()
        data.virtual_size = (size + 1) * units.Gi

        with mock.patch.object(image_utils, 'qemu_img_info',
                               return_value=data):
            self.assertFalse(drv._is_file_size_equal(path, size))

    @mock.patch.object(nfs, 'LOG')
    def test_set_nas_security_options_when_true(self, LOG):
        """Test higher level setting of NAS Security options.

        The NFS driver overrides the base method with a driver specific
        version.
        """
        drv = self._driver
        drv._mounted_shares = [self.TEST_NFS_EXPORT1]
        is_new_install = True

        drv._ensure_shares_mounted = mock.Mock()
        drv._get_mount_point_for_share = mock.Mock(
            return_value=self.TEST_MNT_POINT)
        drv._determine_nas_security_option_setting = mock.Mock(
            return_value='true')

        drv.set_nas_security_options(is_new_install)

        self.assertEqual('true', drv.configuration.nas_secure_file_operations)
        self.assertEqual('true', drv.configuration.nas_secure_file_permissions)
        self.assertFalse(LOG.warn.called)

    @mock.patch.object(nfs, 'LOG')
    def test_set_nas_security_options_when_false(self, LOG):
        """Test higher level setting of NAS Security options.

        The NFS driver overrides the base method with a driver specific
        version.
        """
        drv = self._driver
        drv._mounted_shares = [self.TEST_NFS_EXPORT1]
        is_new_install = False

        drv._ensure_shares_mounted = mock.Mock()
        drv._get_mount_point_for_share = mock.Mock(
            return_value=self.TEST_MNT_POINT)
        drv._determine_nas_security_option_setting = mock.Mock(
            return_value='false')

        drv.set_nas_security_options(is_new_install)

        self.assertEqual('false', drv.configuration.nas_secure_file_operations)
        self.assertEqual('false',
                         drv.configuration.nas_secure_file_permissions)
        self.assertTrue(LOG.warn.called)

    def test_set_nas_security_options_exception_if_no_mounted_shares(self):
        """Ensure proper exception is raised if there are no mounted shares."""

        drv = self._driver
        drv._ensure_shares_mounted = mock.Mock()
        drv._mounted_shares = []
        is_new_cinder_install = 'does not matter'

        self.assertRaises(exception.NfsNoSharesMounted,
                          drv.set_nas_security_options,
                          is_new_cinder_install)

    def test_ensure_share_mounted(self):
        """Case where the mount works the first time."""

        self.mock_object(self._driver._remotefsclient, 'mount')
        drv = self._driver
        drv.configuration.nfs_mount_attempts = 3
        drv.shares = {self.TEST_NFS_EXPORT1: ''}

        drv._ensure_share_mounted(self.TEST_NFS_EXPORT1)

        drv._remotefsclient.mount.called_once()

    def test_ensure_share_mounted_exception(self):
        """Make the configured number of attempts when mounts fail."""

        num_attempts = 3

        self.mock_object(self._driver._remotefsclient, 'mount',
                         mock.Mock(side_effect=Exception))
        drv = self._driver
        drv.configuration.nfs_mount_attempts = num_attempts
        drv.shares = {self.TEST_NFS_EXPORT1: ''}

        self.assertRaises(exception.NfsException, drv._ensure_share_mounted,
                          self.TEST_NFS_EXPORT1)

        self.assertEqual(num_attempts, drv._remotefsclient.mount.call_count)

    def test_ensure_share_mounted_at_least_one_attempt(self):
        """Make at least one mount attempt even if configured for less."""

        min_num_attempts = 1
        num_attempts = 0
        self.mock_object(self._driver._remotefsclient, 'mount',
                         mock.Mock(side_effect=Exception))
        drv = self._driver
        drv.configuration.nfs_mount_attempts = num_attempts
        drv.shares = {self.TEST_NFS_EXPORT1: ''}

        self.assertRaises(exception.NfsException, drv._ensure_share_mounted,
                          self.TEST_NFS_EXPORT1)

        self.assertEqual(min_num_attempts,
                         drv._remotefsclient.mount.call_count)
