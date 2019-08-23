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

import ddt
import errno
import os
import six
import uuid

import mock
from oslo_utils import imageutils
from oslo_utils import units

from cinder import context
from cinder import exception
from cinder.image import image_utils
from cinder import test
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume
from cinder.volume import configuration as conf
from cinder.volume.drivers import nfs
from cinder.volume.drivers import remotefs
from cinder.volume import utils as vutils


class RemoteFsDriverTestCase(test.TestCase):
    TEST_FILE_NAME = 'test.txt'
    TEST_EXPORT = 'nas-host1:/export'
    TEST_MNT_POINT = '/mnt/nas'

    def setUp(self):
        super(RemoteFsDriverTestCase, self).setUp()
        self._driver = remotefs.RemoteFSDriver()
        self.configuration = mock.Mock(conf.Configuration)
        self.configuration.append_config_values(mock.ANY)
        self.configuration.nas_secure_file_permissions = 'false'
        self.configuration.nas_secure_file_operations = 'false'
        self.configuration.nfs_snapshot_support = True
        self.configuration.max_over_subscription_ratio = 1.0
        self.configuration.reserved_percentage = 5
        self._driver = remotefs.RemoteFSDriver(
            configuration=self.configuration)
        mock_exc = mock.patch.object(self._driver, '_execute')
        self._execute = mock_exc.start()
        self.addCleanup(mock_exc.stop)

    def test_create_sparsed_file(self):
        self._driver._create_sparsed_file('/path', 1)
        self._execute.assert_called_once_with('truncate', '-s', '1G',
                                              '/path', run_as_root=True)

    def test_create_regular_file(self):
        self._driver._create_regular_file('/path', 1)
        self._execute.assert_called_once_with('dd', 'if=/dev/zero',
                                              'of=/path', 'bs=1M',
                                              'count=1024', run_as_root=True)

    def test_create_qcow2_file(self):
        file_size = 1
        self._driver._create_qcow2_file('/path', file_size)
        self._execute.assert_called_once_with('qemu-img', 'create', '-f',
                                              'qcow2', '-o',
                                              'preallocation=metadata',
                                              '/path', '%s' %
                                              str(file_size * units.Gi),
                                              run_as_root=True)

    def test_set_rw_permissions_for_all(self):
        self._driver._set_rw_permissions_for_all('/path')
        self._execute.assert_called_once_with('chmod', 'ugo+rw', '/path',
                                              run_as_root=True)

    @mock.patch.object(remotefs, 'LOG')
    def test_set_rw_permissions_with_secure_file_permissions(self, LOG):
        self._driver._mounted_shares = [self.TEST_EXPORT]
        self.configuration.nas_secure_file_permissions = 'true'
        self._driver._set_rw_permissions(self.TEST_FILE_NAME)

        self.assertFalse(LOG.warning.called)

    @mock.patch.object(remotefs, 'LOG')
    def test_set_rw_permissions_without_secure_file_permissions(self, LOG):
        self.configuration.nas_secure_file_permissions = 'false'
        self._driver._set_rw_permissions(self.TEST_FILE_NAME)

        self.assertTrue(LOG.warning.called)
        warn_msg = "%(path)s is being set with open permissions: %(perm)s"
        LOG.warning.assert_called_once_with(
            warn_msg, {'path': self.TEST_FILE_NAME, 'perm': 'ugo+rw'})

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
        self._driver._mounted_shares = [self.TEST_EXPORT]
        file_path = '%s/.cinderSecureEnvIndicator' % self.TEST_MNT_POINT
        is_new_install = True

        self._driver._ensure_shares_mounted = mock.Mock()
        nas_mount = self._driver._get_mount_point_for_share = mock.Mock(
            return_value=self.TEST_MNT_POINT)
        mock_join.return_value = file_path

        secure_file_permissions = 'auto'
        nas_option = self._driver._determine_nas_security_option_setting(
            secure_file_permissions,
            nas_mount, is_new_install)

        self.assertEqual('true', nas_option)

        secure_file_operations = 'auto'
        nas_option = self._driver._determine_nas_security_option_setting(
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

        In this test case, the Admin set the flag to 'false'.
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
        self.assertTrue(LOG.warning.called)

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

# NFS configuration scenarios
NFS_CONFIG1 = {'max_over_subscription_ratio': 1.0,
               'reserved_percentage': 0,
               'nfs_sparsed_volumes': True,
               'nfs_qcow2_volumes': False,
               'nas_secure_file_permissions': 'false',
               'nas_secure_file_operations': 'false'}

NFS_CONFIG2 = {'max_over_subscription_ratio': 10.0,
               'reserved_percentage': 5,
               'nfs_sparsed_volumes': False,
               'nfs_qcow2_volumes': True,
               'nas_secure_file_permissions': 'true',
               'nas_secure_file_operations': 'true'}

NFS_CONFIG3 = {'max_over_subscription_ratio': 15.0,
               'reserved_percentage': 10,
               'nfs_sparsed_volumes': False,
               'nfs_qcow2_volumes': False,
               'nas_secure_file_permissions': 'auto',
               'nas_secure_file_operations': 'auto'}

NFS_CONFIG4 = {'max_over_subscription_ratio': 20.0,
               'reserved_percentage': 60,
               'nfs_sparsed_volumes': True,
               'nfs_qcow2_volumes': True,
               'nas_secure_file_permissions': 'false',
               'nas_secure_file_operations': 'true'}

QEMU_IMG_INFO_OUT1 = """image: %(volid)s
        file format: raw
        virtual size: %(size_gb)sG (%(size_b)s bytes)
        disk size: 173K
        """

QEMU_IMG_INFO_OUT2 = """image: %(volid)s
file format: qcow2
virtual size: %(size_gb)sG (%(size_b)s bytes)
disk size: 196K
cluster_size: 65536
Format specific information:
    compat: 1.1
    lazy refcounts: false
    refcount bits: 16
    corrupt: false
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

QEMU_IMG_INFO_OUT4 = """image: volume-%(volid)s.%(snapid)s
file format: raw
virtual size: %(size_gb)sG (%(size_b)s bytes)
disk size: 196K
cluster_size: 65536
backing file: volume-%(volid)s
backing file format: raw
Format specific information:
    compat: 1.1
    lazy refcounts: false
    refcount bits: 16
    corrupt: false
    """


@ddt.ddt
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
    VOLUME_UUID = '69ad4ff6-b892-4215-aaaa-aaaaaaaaaaaa'

    def setUp(self):
        super(NfsDriverTestCase, self).setUp()
        self.configuration = mock.Mock(conf.Configuration)
        self.configuration.append_config_values(mock.ANY)
        self.configuration.max_over_subscription_ratio = 1.0
        self.configuration.reserved_percentage = 5
        self.configuration.nfs_shares_config = None
        self.configuration.nfs_sparsed_volumes = True
        self.configuration.nfs_reserved_percentage = 5.0
        self.configuration.nfs_mount_point_base = self.TEST_MNT_POINT_BASE
        self.configuration.nfs_mount_options = None
        self.configuration.nfs_mount_attempts = 3
        self.configuration.nfs_qcow2_volumes = False
        self.configuration.nas_secure_file_permissions = 'false'
        self.configuration.nas_secure_file_operations = 'false'
        self.configuration.nas_host = None
        self.configuration.nas_share_path = None
        self.configuration.nas_mount_options = None
        self.configuration.volume_dd_blocksize = '1M'

        self.mock_object(vutils, 'get_max_over_subscription_ratio',
                         return_value=1)

        self.context = context.get_admin_context()

    def _set_driver(self, extra_confs=None):

        # Overide the default configs
        if extra_confs:
            for config_name, config_value in extra_confs.items():
                setattr(self.configuration, config_name, config_value)

        self._driver = nfs.NfsDriver(configuration=self.configuration)
        self._driver.shares = {}
        self.mock_object(self._driver, '_execute')

    @ddt.data(NFS_CONFIG1, NFS_CONFIG2, NFS_CONFIG3, NFS_CONFIG4)
    def test_local_path(self, nfs_config):
        """local_path common use case."""
        self.configuration.nfs_mount_point_base = self.TEST_MNT_POINT_BASE
        self._set_driver(extra_confs=nfs_config)
        drv = self._driver

        volume = fake_volume.fake_volume_obj(
            self.context,
            provider_location=self.TEST_NFS_EXPORT1)

        self.assertEqual(
            '/mnt/test/2f4f60214cf43c595666dd815f0360a4/%s' % volume.name,
            drv.local_path(volume))

    @ddt.data(NFS_CONFIG1, NFS_CONFIG2, NFS_CONFIG3, NFS_CONFIG4)
    def test_copy_image_to_volume(self, nfs_config):
        """resize_image common case usage."""

        mock_resize = self.mock_object(image_utils, 'resize_image')
        mock_fetch = self.mock_object(image_utils, 'fetch_to_raw')

        self._set_driver()
        drv = self._driver
        volume = fake_volume.fake_volume_obj(self.context,
                                             size=self.TEST_SIZE_IN_GB)
        test_img_source = 'volume-%s' % volume.id

        self.mock_object(drv, 'local_path', return_value=test_img_source)

        data = mock.Mock()
        data.virtual_size = 1 * units.Gi
        self.mock_object(image_utils, 'qemu_img_info', return_value=data)
        drv.copy_image_to_volume(None, volume, None, None)

        mock_fetch.assert_called_once_with(
            None, None, None, test_img_source, mock.ANY, run_as_root=True,
            size=self.TEST_SIZE_IN_GB)
        mock_resize.assert_called_once_with(test_img_source,
                                            self.TEST_SIZE_IN_GB,
                                            run_as_root=True)

    def test_get_mount_point_for_share(self):
        """_get_mount_point_for_share should calculate correct value."""
        self._set_driver()
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
        self._set_driver()
        drv = self._driver
        stat_total_size = 2620544
        stat_avail = 2129984
        stat_output = '1 %d %d' % (stat_total_size, stat_avail)

        du_used = 490560
        du_output = '%d /mnt' % du_used

        with mock.patch.object(
                drv, '_get_mount_point_for_share') as mock_get_mount:
            mock_get_mount.return_value = self.TEST_MNT_POINT
            drv._execute.side_effect = [(stat_output, None),
                                        (du_output, None)]

            self.assertEqual((stat_total_size, stat_avail, du_used),
                             drv._get_capacity_info(self.TEST_NFS_EXPORT1))

            mock_get_mount.assert_called_once_with(self.TEST_NFS_EXPORT1)

            calls = [mock.call('stat', '-f', '-c', '%S %b %a',
                               self.TEST_MNT_POINT, run_as_root=True),
                     mock.call('du', '-sb', '--apparent-size',
                               '--exclude', '*snapshot*',
                               self.TEST_MNT_POINT, run_as_root=True)]

            drv._execute.assert_has_calls(calls)

    def test_get_capacity_info_for_share_and_mount_point_with_spaces(self):
        """_get_capacity_info should calculate correct value."""
        self._set_driver()
        drv = self._driver
        stat_total_size = 2620544
        stat_avail = 2129984
        stat_output = '1 %d %d' % (stat_total_size, stat_avail)

        du_used = 490560
        du_output = '%d /mnt' % du_used

        with mock.patch.object(
                drv, '_get_mount_point_for_share') as mock_get_mount:
            mock_get_mount.return_value = self.TEST_MNT_POINT_SPACES
            drv._execute.side_effect = [(stat_output, None),
                                        (du_output, None)]

            self.assertEqual((stat_total_size, stat_avail, du_used),
                             drv._get_capacity_info(
                                 self.TEST_NFS_EXPORT_SPACES))

            mock_get_mount.assert_called_once_with(
                self.TEST_NFS_EXPORT_SPACES)

            calls = [mock.call('stat', '-f', '-c', '%S %b %a',
                               self.TEST_MNT_POINT_SPACES, run_as_root=True),
                     mock.call('du', '-sb', '--apparent-size',
                               '--exclude', '*snapshot*',
                               self.TEST_MNT_POINT_SPACES, run_as_root=True)]

            drv._execute.assert_has_calls(calls)

    def test_load_shares_config(self):
        self._set_driver()
        drv = self._driver

        drv.configuration.nfs_shares_config = self.TEST_SHARES_CONFIG_FILE

        with mock.patch.object(
                drv, '_read_config_file') as mock_read_config:
            config_data = []
            config_data.append(self.TEST_NFS_EXPORT1)
            config_data.append('#' + self.TEST_NFS_EXPORT2)
            config_data.append('')
            config_data.append(self.TEST_NFS_EXPORT2 + ' ' +
                               self.TEST_NFS_EXPORT2_OPTIONS)
            config_data.append('broken:share_format')
            mock_read_config.return_value = config_data

            drv._load_shares_config(drv.configuration.nfs_shares_config)

            mock_read_config.assert_called_once_with(
                self.TEST_SHARES_CONFIG_FILE)
            self.assertIn(self.TEST_NFS_EXPORT1, drv.shares)
            self.assertIn(self.TEST_NFS_EXPORT2, drv.shares)
            self.assertEqual(2, len(drv.shares))

            self.assertEqual(self.TEST_NFS_EXPORT2_OPTIONS,
                             drv.shares[self.TEST_NFS_EXPORT2])

    def test_load_shares_config_nas_opts(self):
        self._set_driver()
        drv = self._driver
        drv.configuration.nas_host = self.TEST_NFS_HOST
        drv.configuration.nas_share_path = self.TEST_NFS_SHARE_PATH
        drv.configuration.nfs_shares_config = self.TEST_SHARES_CONFIG_FILE

        drv._load_shares_config(drv.configuration.nfs_shares_config)

        self.assertIn(self.TEST_NFS_EXPORT1, drv.shares)
        self.assertEqual(1, len(drv.shares))

    def test_ensure_shares_mounted_should_save_mounting_successfully(self):
        """_ensure_shares_mounted should save share if mounted with success."""
        self._set_driver()
        drv = self._driver
        config_data = []
        config_data.append(self.TEST_NFS_EXPORT1)
        drv.configuration.nfs_shares_config = self.TEST_SHARES_CONFIG_FILE

        with mock.patch.object(
                drv, '_read_config_file') as mock_read_config:
            with mock.patch.object(
                    drv, '_ensure_share_mounted') as mock_ensure:
                mock_read_config.return_value = config_data
                drv._ensure_share_mounted(self.TEST_NFS_EXPORT1)
                mock_ensure.assert_called_once_with(self.TEST_NFS_EXPORT1)

    @mock.patch.object(remotefs, 'LOG')
    def test_ensure_shares_mounted_should_not_save_mounting_with_error(self,
                                                                       LOG):
        """_ensure_shares_mounted should not save share if failed to mount."""
        self._set_driver()
        drv = self._driver
        config_data = []
        config_data.append(self.TEST_NFS_EXPORT1)
        drv.configuration.nfs_shares_config = self.TEST_SHARES_CONFIG_FILE
        with mock.patch.object(
                drv, '_read_config_file') as mock_read_config:
            with mock.patch.object(
                    drv, '_ensure_share_mounted') as mock_ensure:
                mock_read_config.return_value = config_data
                drv._ensure_share_mounted()
                self.assertEqual(0, len(drv._mounted_shares))
                mock_ensure.assert_called_once_with()

    def test_find_share_should_throw_error_if_there_is_no_mounted_share(self):
        """_find_share should throw error if there is no mounted shares."""
        self._set_driver()
        drv = self._driver

        drv._mounted_shares = []

        self.assertRaises(exception.NfsNoSharesMounted, drv._find_share,
                          self._simple_volume())

    def test_find_share(self):
        """_find_share simple use case."""
        self._set_driver()
        drv = self._driver
        drv._mounted_shares = [self.TEST_NFS_EXPORT1, self.TEST_NFS_EXPORT2]

        volume = fake_volume.fake_volume_obj(self.context,
                                             size=self.TEST_SIZE_IN_GB)

        with mock.patch.object(
                drv, '_get_capacity_info') as mock_get_capacity_info:
            mock_get_capacity_info.side_effect = [
                (5 * units.Gi, 2 * units.Gi, 2 * units.Gi),
                (10 * units.Gi, 3 * units.Gi, 1 * units.Gi)]
            self.assertEqual(self.TEST_NFS_EXPORT2,
                             drv._find_share(volume))
            calls = [mock.call(self.TEST_NFS_EXPORT1),
                     mock.call(self.TEST_NFS_EXPORT2)]
            mock_get_capacity_info.assert_has_calls(calls)
            self.assertEqual(2, mock_get_capacity_info.call_count)

    def test_find_share_should_throw_error_if_there_is_not_enough_space(self):
        """_find_share should throw error if there is no share to host vol."""
        self._set_driver()
        drv = self._driver
        drv._mounted_shares = [self.TEST_NFS_EXPORT1, self.TEST_NFS_EXPORT2]

        with mock.patch.object(
                drv, '_get_capacity_info') as mock_get_capacity_info:
            mock_get_capacity_info.side_effect = [
                (5 * units.Gi, 0, 5 * units.Gi),
                (10 * units.Gi, 0, 10 * units.Gi)]

            self.assertRaises(exception.NfsNoSuitableShareFound,
                              drv._find_share, self._simple_volume())
            calls = [mock.call(self.TEST_NFS_EXPORT1),
                     mock.call(self.TEST_NFS_EXPORT2)]
            mock_get_capacity_info.assert_has_calls(calls)
            self.assertEqual(2, mock_get_capacity_info.call_count)

    def _simple_volume(self, size=10):
        loc = self.TEST_NFS_EXPORT1
        return fake_volume.fake_volume_obj(self.context,
                                           display_name='volume_name',
                                           provider_location=loc,
                                           size=size)

    def test_get_provisioned_capacity(self):
        self._set_driver()
        drv = self._driver

        mock_execute = self.mock_object(drv, '_execute')
        mock_execute.return_value = ("148418423\t/dir", "")

        with mock.patch.object(drv, 'shares') as shares:
            shares.keys.return_value = {'192.0.2.1:/srv/nfs1'}
            shares.return_value = {'192.0.2.1:/srv/nfs1', ''}
            ret = drv._get_provisioned_capacity()

            self.assertEqual(ret, 0.14)

    def test_create_sparsed_volume(self):
        self._set_driver()
        drv = self._driver
        volume = self._simple_volume()

        self.override_config('nfs_sparsed_volumes', True)

        with mock.patch.object(
                drv, '_create_sparsed_file') as mock_create_sparsed_file:
            with mock.patch.object(
                    drv, '_set_rw_permissions') as mock_set_rw_permissions:
                drv._do_create_volume(volume)

                mock_create_sparsed_file.assert_called_once_with(mock.ANY,
                                                                 mock.ANY)
                mock_set_rw_permissions.assert_called_once_with(mock.ANY)

    def test_create_nonsparsed_volume(self):
        self._set_driver()
        drv = self._driver
        self.configuration.nfs_sparsed_volumes = False
        volume = self._simple_volume()

        self.override_config('nfs_sparsed_volumes', False)

        with mock.patch.object(
                drv, '_create_regular_file') as mock_create_regular_file:
            with mock.patch.object(
                    drv, '_set_rw_permissions') as mock_set_rw_permissions:
                drv._do_create_volume(volume)

                mock_create_regular_file.assert_called_once_with(mock.ANY,
                                                                 mock.ANY)
                mock_set_rw_permissions.assert_called_once_with(mock.ANY)

    @mock.patch.object(nfs, 'LOG')
    def test_create_volume_should_ensure_nfs_mounted(self, mock_log):
        """create_volume ensures shares provided in config are mounted."""
        self._set_driver()
        drv = self._driver
        drv._find_share = mock.Mock()
        drv._find_share.return_value = self.TEST_NFS_EXPORT1
        drv._do_create_volume = mock.Mock()

        with mock.patch.object(
                drv, '_ensure_share_mounted') as mock_ensure_share:
            drv._ensure_share_mounted()
            volume = fake_volume.fake_volume_obj(self.context,
                                                 size=self.TEST_SIZE_IN_GB)
            drv.create_volume(volume)

            mock_ensure_share.assert_called_once_with()

    @mock.patch.object(nfs, 'LOG')
    def test_create_volume_should_return_provider_location(self, mock_log):
        """create_volume should return provider_location with found share."""
        self._set_driver()
        drv = self._driver
        drv._ensure_shares_mounted = mock.Mock()
        drv._do_create_volume = mock.Mock()

        with mock.patch.object(drv, '_find_share') as mock_find_share:
            mock_find_share.return_value = self.TEST_NFS_EXPORT1
            volume = fake_volume.fake_volume_obj(self.context,
                                                 size=self.TEST_SIZE_IN_GB)
            result = drv.create_volume(volume)
            self.assertEqual(self.TEST_NFS_EXPORT1,
                             result['provider_location'])
            mock_find_share.assert_called_once_with(volume)

    def test_delete_volume(self):
        """delete_volume simple test case."""
        self._set_driver()
        drv = self._driver
        drv._ensure_share_mounted = mock.Mock()

        volume = fake_volume.fake_volume_obj(
            self.context,
            display_name='volume-123',
            provider_location=self.TEST_NFS_EXPORT1)

        with mock.patch.object(drv, 'local_path') as mock_local_path:
            mock_local_path.return_value = self.TEST_LOCAL_PATH
            drv.delete_volume(volume)
            mock_local_path.assert_called_with(volume)
            drv._execute.assert_called_once()

    def test_delete_should_ensure_share_mounted(self):
        """delete_volume should ensure that corresponding share is mounted."""
        self._set_driver()
        drv = self._driver
        volume = fake_volume.fake_volume_obj(
            self.context,
            display_name='volume-123',
            provider_location=self.TEST_NFS_EXPORT1)

        with mock.patch.object(drv, '_ensure_share_mounted'):
            drv.delete_volume(volume)

    def test_delete_should_not_delete_if_provider_location_not_provided(self):
        """delete_volume shouldn't delete if provider_location missed."""
        self._set_driver()
        drv = self._driver
        volume = fake_volume.fake_volume_obj(self.context,
                                             name='volume-123',
                                             provider_location=None)

        with mock.patch.object(drv, '_ensure_share_mounted'):
            drv.delete_volume(volume)
            self.assertFalse(drv._execute.called)

    def test_get_volume_stats(self):
        """get_volume_stats must fill the correct values."""
        self._set_driver()
        drv = self._driver
        drv._mounted_shares = [self.TEST_NFS_EXPORT1, self.TEST_NFS_EXPORT2]

        with mock.patch.object(
                drv, '_ensure_shares_mounted') as mock_ensure_share:
            with mock.patch.object(
                    drv, '_get_capacity_info') as mock_get_capacity_info:
                mock_get_capacity_info.side_effect = [
                    (10 * units.Gi, 2 * units.Gi, 2 * units.Gi),
                    (20 * units.Gi, 3 * units.Gi, 3 * units.Gi)]

                drv._ensure_shares_mounted()
                drv.get_volume_stats()

                calls = [mock.call(self.TEST_NFS_EXPORT1),
                         mock.call(self.TEST_NFS_EXPORT2)]
                mock_get_capacity_info.assert_has_calls(calls)

                self.assertTrue(mock_ensure_share.called)
                self.assertEqual(30.0, drv._stats['total_capacity_gb'])
                self.assertEqual(5.0, drv._stats['free_capacity_gb'])
                self.assertEqual(5, drv._stats['reserved_percentage'])
                self.assertTrue(drv._stats['sparse_copy_volume'])

    def test_get_volume_stats_with_non_zero_reserved_percentage(self):
        """get_volume_stats must fill the correct values."""
        self.configuration.reserved_percentage = 10.0
        drv = nfs.NfsDriver(configuration=self.configuration)

        drv._mounted_shares = [self.TEST_NFS_EXPORT1, self.TEST_NFS_EXPORT2]

        with mock.patch.object(
                drv, '_ensure_shares_mounted') as mock_ensure_share:
            with mock.patch.object(
                    drv, '_get_capacity_info') as mock_get_capacity_info:
                mock_get_capacity_info.side_effect = [
                    (10 * units.Gi, 2 * units.Gi, 2 * units.Gi),
                    (20 * units.Gi, 3 * units.Gi, 3 * units.Gi)]

                drv._ensure_shares_mounted()
                drv.get_volume_stats()

                calls = [mock.call(self.TEST_NFS_EXPORT1),
                         mock.call(self.TEST_NFS_EXPORT2)]
                mock_get_capacity_info.assert_has_calls(calls)

                self.assertTrue(mock_ensure_share.called)
                self.assertEqual(30.0, drv._stats['total_capacity_gb'])
                self.assertEqual(5.0, drv._stats['free_capacity_gb'])
                self.assertEqual(10.0, drv._stats['reserved_percentage'])

    @ddt.data(True, False)
    def test_update_volume_stats(self, thin):
        self._set_driver()
        self._driver.configuration.max_over_subscription_ratio = 20.0
        self._driver.configuration.reserved_percentage = 5.0
        self._driver.configuration.nfs_sparsed_volumes = thin

        remotefs_volume_stats = {
            'volume_backend_name': 'fake_backend_name',
            'vendor_name': 'fake_vendor',
            'driver_version': 'fake_version',
            'storage_protocol': 'NFS',
            'total_capacity_gb': 100.0,
            'free_capacity_gb': 20.0,
            'reserved_percentage': 5.0,
            'QoS_support': False,
        }
        self.mock_object(remotefs.RemoteFSDriver, '_update_volume_stats')
        self._driver._stats = remotefs_volume_stats

        mock_get_provisioned_capacity = self.mock_object(
            self._driver, '_get_provisioned_capacity', return_value=25.0)

        self._driver._update_volume_stats()

        nfs_added_volume_stats = {
            'provisioned_capacity_gb': 25.0 if thin else 80.0,
            'max_over_subscription_ratio': 20.0,
            'reserved_percentage': 5.0,
            'thin_provisioning_support': thin,
            'thick_provisioning_support': not thin,
        }
        expected = remotefs_volume_stats
        expected.update(nfs_added_volume_stats)

        self.assertEqual(expected, self._driver._stats)
        self.assertEqual(thin, mock_get_provisioned_capacity.called)

    def _check_is_share_eligible(self, total_size, total_available,
                                 total_allocated, requested_volume_size):
        self._set_driver()
        with mock.patch.object(self._driver, '_get_capacity_info')\
                as mock_get_capacity_info:
            mock_get_capacity_info.return_value = (total_size,
                                                   total_available,
                                                   total_allocated)
            return self._driver._is_share_eligible('fake_share',
                                                   requested_volume_size)

    def test_is_share_eligible(self):
        self._set_driver()
        total_size = 100.0 * units.Gi
        total_available = 90.0 * units.Gi
        total_allocated = 10.0 * units.Gi
        requested_volume_size = 1  # GiB

        self.assertTrue(self._check_is_share_eligible(total_size,
                                                      total_available,
                                                      total_allocated,
                                                      requested_volume_size))

    def test_share_eligibility_with_reserved_percentage(self):
        self._set_driver()
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
        self._set_driver()
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
        self._set_driver()
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
        self._set_driver()
        drv = self._driver
        volume = fake_volume.fake_volume_obj(
            self.context,
            id='80ee16b6-75d2-4d54-9539-ffc1b4b0fb10',
            size=1,
            provider_location='nfs_share')
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
        self._set_driver()
        drv = self._driver
        volume = fake_volume.fake_volume_obj(
            self.context,
            id='80ee16b6-75d2-4d54-9539-ffc1b4b0fb10',
            size=1,
            provider_location='nfs_share')

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
        self._set_driver()
        drv = self._driver
        volume = fake_volume.fake_volume_obj(
            self.context,
            id='80ee16b6-75d2-4d54-9539-ffc1b4b0fb10',
            size=1,
            provider_location='nfs_share')

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
        self._set_driver()
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
        self._set_driver()
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
        self._set_driver()
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
        self.assertFalse(LOG.warning.called)

    @mock.patch.object(nfs, 'LOG')
    def test_set_nas_security_options_when_false(self, LOG):
        """Test higher level setting of NAS Security options.

        The NFS driver overrides the base method with a driver specific
        version.
        """
        self._set_driver()
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
        self.assertTrue(LOG.warning.called)

    def test_set_nas_security_options_exception_if_no_mounted_shares(self):
        """Ensure proper exception is raised if there are no mounted shares."""

        self._set_driver()
        drv = self._driver
        drv._ensure_shares_mounted = mock.Mock()
        drv._mounted_shares = []
        is_new_cinder_install = 'does not matter'

        self.assertRaises(exception.NfsNoSharesMounted,
                          drv.set_nas_security_options,
                          is_new_cinder_install)

    def test_ensure_share_mounted(self):
        """Case where the mount works the first time."""

        self._set_driver()
        self.mock_object(self._driver._remotefsclient, 'mount')
        drv = self._driver
        drv.configuration.nfs_mount_attempts = 3
        drv.shares = {self.TEST_NFS_EXPORT1: ''}

        drv._ensure_share_mounted(self.TEST_NFS_EXPORT1)

        drv._remotefsclient.mount.called_once()

    @mock.patch('time.sleep')
    def test_ensure_share_mounted_exception(self, _mock_sleep):
        """Make the configured number of attempts when mounts fail."""

        num_attempts = 3

        self._set_driver()
        self.mock_object(self._driver._remotefsclient, 'mount',
                         side_effect=Exception)
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
        self._set_driver()
        self.mock_object(self._driver._remotefsclient, 'mount',
                         side_effect=Exception)
        drv = self._driver
        drv.configuration.nfs_mount_attempts = num_attempts
        drv.shares = {self.TEST_NFS_EXPORT1: ''}

        self.assertRaises(exception.NfsException, drv._ensure_share_mounted,
                          self.TEST_NFS_EXPORT1)

        self.assertEqual(min_num_attempts,
                         drv._remotefsclient.mount.call_count)

    @ddt.data([NFS_CONFIG1, QEMU_IMG_INFO_OUT3],
              [NFS_CONFIG2, QEMU_IMG_INFO_OUT4],
              [NFS_CONFIG3, QEMU_IMG_INFO_OUT3],
              [NFS_CONFIG4, QEMU_IMG_INFO_OUT4])
    @ddt.unpack
    def test_copy_volume_from_snapshot(self, nfs_conf, qemu_img_info):
        self._set_driver(extra_confs=nfs_conf)
        drv = self._driver
        dest_volume = self._simple_volume()
        src_volume = self._simple_volume()

        fake_snap = fake_snapshot.fake_snapshot_obj(self.context)
        fake_snap.volume = src_volume

        img_out = qemu_img_info % {'volid': src_volume.id,
                                   'snapid': fake_snap.id,
                                   'size_gb': src_volume.size,
                                   'size_b': src_volume.size * units.Gi}

        img_info = imageutils.QemuImgInfo(img_out)
        mock_img_info = self.mock_object(image_utils, 'qemu_img_info')
        mock_img_info.return_value = img_info
        mock_convert_image = self.mock_object(image_utils, 'convert_image')

        vol_dir = os.path.join(self.TEST_MNT_POINT_BASE,
                               drv._get_hash_str(src_volume.provider_location))
        src_vol_path = os.path.join(vol_dir, img_info.backing_file)
        dest_vol_path = os.path.join(vol_dir, dest_volume.name)
        info_path = os.path.join(vol_dir, src_volume.name) + '.info'

        snap_file = dest_volume.name + '.' + fake_snap.id
        snap_path = os.path.join(vol_dir, snap_file)
        size = dest_volume.size

        mock_read_info_file = self.mock_object(drv, '_read_info_file')
        mock_read_info_file.return_value = {'active': snap_file,
                                            fake_snap.id: snap_file}

        mock_permission = self.mock_object(drv, '_set_rw_permissions_for_all')

        drv._copy_volume_from_snapshot(fake_snap, dest_volume, size)

        mock_read_info_file.assert_called_once_with(info_path)
        mock_img_info.assert_called_once_with(snap_path,
                                              force_share=True,
                                              run_as_root=True)
        used_qcow = nfs_conf['nfs_qcow2_volumes']
        mock_convert_image.assert_called_once_with(
            src_vol_path, dest_vol_path, 'qcow2' if used_qcow else 'raw',
            run_as_root=True)
        mock_permission.assert_called_once_with(dest_vol_path)

    @ddt.data([NFS_CONFIG1, QEMU_IMG_INFO_OUT3],
              [NFS_CONFIG2, QEMU_IMG_INFO_OUT4],
              [NFS_CONFIG3, QEMU_IMG_INFO_OUT3],
              [NFS_CONFIG4, QEMU_IMG_INFO_OUT4])
    @ddt.unpack
    def test_create_volume_from_snapshot(self, nfs_conf, qemu_img_info):
        self._set_driver(extra_confs=nfs_conf)
        drv = self._driver

        # Volume source of the snapshot we are trying to clone from. We need it
        # to have a different id than the default provided.
        src_volume = self._simple_volume(size=10)
        src_volume.id = six.text_type(uuid.uuid4())
        src_volume_dir = os.path.join(self.TEST_MNT_POINT_BASE,
                                      drv._get_hash_str(
                                          src_volume.provider_location))
        src_volume_path = os.path.join(src_volume_dir, src_volume.name)
        fake_snap = fake_snapshot.fake_snapshot_obj(self.context)

        # Fake snapshot based in the previous created volume
        snap_file = src_volume.name + '.' + fake_snap.id
        fake_snap.volume = src_volume
        fake_snap.status = 'available'
        fake_snap.size = 10

        # New fake volume where the snap will be copied
        new_volume = self._simple_volume(size=10)
        new_volume_dir = os.path.join(self.TEST_MNT_POINT_BASE,
                                      drv._get_hash_str(
                                          src_volume.provider_location))
        new_volume_path = os.path.join(new_volume_dir, new_volume.name)

        # Mocks
        img_out = qemu_img_info % {'volid': src_volume.id,
                                   'snapid': fake_snap.id,
                                   'size_gb': src_volume.size,
                                   'size_b': src_volume.size * units.Gi}
        img_info = imageutils.QemuImgInfo(img_out)
        mock_img_info = self.mock_object(image_utils, 'qemu_img_info')
        mock_img_info.return_value = img_info

        mock_ensure = self.mock_object(drv, '_ensure_shares_mounted')
        mock_find_share = self.mock_object(drv, '_find_share',
                                           return_value=self.TEST_NFS_EXPORT1)
        mock_read_info_file = self.mock_object(drv, '_read_info_file')
        mock_read_info_file.return_value = {'active': snap_file,
                                            fake_snap.id: snap_file}
        mock_convert_image = self.mock_object(image_utils, 'convert_image')
        self.mock_object(drv, '_create_qcow2_file')
        self.mock_object(drv, '_create_regular_file')
        self.mock_object(drv, '_create_regular_file')
        self.mock_object(drv, '_set_rw_permissions')
        self.mock_object(drv, '_read_file')

        ret = drv.create_volume_from_snapshot(new_volume, fake_snap)

        # Test asserts
        self.assertEqual(self.TEST_NFS_EXPORT1, ret['provider_location'])
        used_qcow = nfs_conf['nfs_qcow2_volumes']
        mock_convert_image.assert_called_once_with(
            src_volume_path, new_volume_path, 'qcow2' if used_qcow else 'raw',
            run_as_root=True)
        mock_ensure.assert_called_once()
        mock_find_share.assert_called_once_with(new_volume)

    def test_create_volume_from_snapshot_status_not_available(self):
        """Expect an error when the snapshot's status is not 'available'."""
        self._set_driver()
        drv = self._driver

        src_volume = self._simple_volume()

        fake_snap = fake_snapshot.fake_snapshot_obj(self.context)
        fake_snap.volume = src_volume

        new_volume = self._simple_volume()
        new_volume['size'] = fake_snap['volume_size']

        self.assertRaises(exception.InvalidSnapshot,
                          drv.create_volume_from_snapshot,
                          new_volume,
                          fake_snap)

    @ddt.data([NFS_CONFIG1, QEMU_IMG_INFO_OUT1],
              [NFS_CONFIG2, QEMU_IMG_INFO_OUT2],
              [NFS_CONFIG3, QEMU_IMG_INFO_OUT1],
              [NFS_CONFIG4, QEMU_IMG_INFO_OUT2])
    @ddt.unpack
    def test_initialize_connection(self, nfs_confs, qemu_img_info):
        self._set_driver(extra_confs=nfs_confs)
        drv = self._driver

        volume = self._simple_volume()
        vol_dir = os.path.join(self.TEST_MNT_POINT_BASE,
                               drv._get_hash_str(volume.provider_location))
        vol_path = os.path.join(vol_dir, volume.name)

        mock_img_utils = self.mock_object(image_utils, 'qemu_img_info')
        img_out = qemu_img_info % {'volid': volume.id, 'size_gb': volume.size,
                                   'size_b': volume.size * units.Gi}
        mock_img_utils.return_value = imageutils.QemuImgInfo(img_out)
        self.mock_object(drv, '_read_info_file',
                         return_value={'active': "volume-%s" % volume.id})

        conn_info = drv.initialize_connection(volume, None)

        mock_img_utils.assert_called_once_with(vol_path,
                                               force_share=True,
                                               run_as_root=True)
        self.assertEqual('nfs', conn_info['driver_volume_type'])
        self.assertEqual(volume.name, conn_info['data']['name'])
        self.assertEqual(self.TEST_MNT_POINT_BASE,
                         conn_info['mount_point_base'])

    @mock.patch.object(image_utils, 'qemu_img_info')
    def test_initialize_connection_raise_exception(self, mock_img_info):
        self._set_driver()
        drv = self._driver
        volume = self._simple_volume()

        qemu_img_output = """image: %s
        file format: iso
        virtual size: 1.0G (1073741824 bytes)
        disk size: 173K
        """ % volume['name']
        mock_img_info.return_value = imageutils.QemuImgInfo(qemu_img_output)

        self.assertRaises(exception.InvalidVolume,
                          drv.initialize_connection,
                          volume,
                          None)

    def test_create_snapshot(self):
        self._set_driver()
        drv = self._driver
        volume = self._simple_volume()
        self.configuration.nfs_snapshot_support = True
        fake_snap = fake_snapshot.fake_snapshot_obj(self.context)
        fake_snap.volume = volume
        vol_dir = os.path.join(self.TEST_MNT_POINT_BASE,
                               drv._get_hash_str(self.TEST_NFS_EXPORT1))
        snap_file = volume['name'] + '.' + fake_snap.id
        snap_path = os.path.join(vol_dir, snap_file)
        info_path = os.path.join(vol_dir, volume['name']) + '.info'

        with mock.patch.object(drv, '_local_path_volume_info',
                               return_value=info_path), \
                mock.patch.object(drv, '_read_info_file', return_value={}), \
                mock.patch.object(drv, '_do_create_snapshot') \
                as mock_do_create_snapshot, \
                mock.patch.object(drv, '_write_info_file') \
                as mock_write_info_file, \
                mock.patch.object(drv, 'get_active_image_from_info',
                                  return_value=volume['name']), \
                mock.patch.object(drv, '_get_new_snap_path',
                                  return_value=snap_path):
            self._driver.create_snapshot(fake_snap)

        mock_do_create_snapshot.assert_called_with(fake_snap, volume['name'],
                                                   snap_path)
        mock_write_info_file.assert_called_with(
            info_path, {'active': snap_file, fake_snap.id: snap_file})

    @ddt.data({'volume_status': 'available',
               'original_provider': 'original_provider',
               'rename_side_effect': None},
              {'volume_status': 'available',
               'original_provider': 'current_provider',
               'rename_side_effect': None},
              {'volume_status': 'in-use',
               'original_provider': 'original_provider',
               'rename_side_effect': None},
              {'volume_status': 'available',
               'original_provider': 'original_provider',
               'rename_side_effect': OSError})
    @ddt.unpack
    @mock.patch('os.rename')
    def test_update_migrated_volume(self,
                                    mock_rename,
                                    rename_side_effect,
                                    original_provider,
                                    volume_status):
        drv = nfs.NfsDriver(configuration=self.configuration)
        base_dir = '/dir_base/'
        current_path = base_dir + fake.VOLUME2_NAME
        current_provider = 'current_provider'
        mock_rename.side_effect = rename_side_effect

        volume = fake_volume.fake_volume_obj(
            self.context,
            id=fake.VOLUME_ID,
            provider_location=original_provider,
            _name_id=None)

        new_volume = fake_volume.fake_volume_obj(
            self.context,
            id=fake.VOLUME2_ID,
            provider_location=current_provider,
            _name_id=None)

        with mock.patch.object(drv, 'local_path') as local_path:
            local_path.return_value = current_path
            update = drv.update_migrated_volume(self.context,
                                                volume,
                                                new_volume,
                                                volume_status)

            if (volume_status == 'available' and
                    original_provider != current_provider):
                original_path = base_dir + fake.VOLUME_NAME
                mock_rename.assert_called_once_with(current_path,
                                                    original_path)
            else:
                mock_rename.assert_not_called()

            if mock_rename.call_count > 0 and rename_side_effect is None:
                self.assertEqual({'_name_id': None,
                                  'provider_location': current_provider},
                                 update)
            else:
                self.assertEqual({'_name_id': fake.VOLUME2_ID,
                                  'provider_location': current_provider},
                                 update)


class NfsDriverDoSetupTestCase(test.TestCase):

    def setUp(self):
        super(NfsDriverDoSetupTestCase, self).setUp()
        self.context = mock.Mock()
        self.create_configuration()

    def create_configuration(self):
        config = conf.Configuration(None)
        config.append_config_values(nfs.nfs_opts)
        self.configuration = config

    def test_setup_should_throw_error_if_shares_config_not_configured(self):
        """do_setup should throw error if shares config is not configured."""

        self.override_config('nfs_shares_config', None)
        drv = nfs.NfsDriver(configuration=self.configuration)

        mock_os_path_exists = self.mock_object(os.path, 'exists')

        with self.assertRaisesRegex(exception.NfsException,
                                    ".*no NFS config file configured.*"):
            drv.do_setup(self.context)

        self.assertEqual(0, mock_os_path_exists.call_count)

    def test_setup_should_throw_error_if_shares_file_does_not_exist(self):
        """do_setup should throw error if shares file does not exist."""

        drv = nfs.NfsDriver(configuration=self.configuration)

        mock_os_path_exists = self.mock_object(os.path, 'exists')
        mock_os_path_exists.return_value = False

        with self.assertRaisesRegex(exception.NfsException,
                                    "NFS config file.*doesn't exist"):
            drv.do_setup(self.context)

        mock_os_path_exists.assert_has_calls(
            [mock.call(self.configuration.nfs_shares_config)])

    def test_setup_should_not_throw_error_if_host_and_share_set(self):
        """do_setup shouldn't throw shares file error if host and share set."""

        drv = nfs.NfsDriver(configuration=self.configuration)

        self.override_config('nas_host', 'nfs-host1')
        self.override_config('nas_share_path', '/export')
        mock_os_path_exists = self.mock_object(os.path, 'exists')
        mock_os_path_exists.return_value = False
        mock_set_nas_sec_options = self.mock_object(nfs.NfsDriver,
                                                    'set_nas_security_options')
        mock_set_nas_sec_options.return_value = True
        mock_execute = self.mock_object(drv, '_execute')
        mock_execute.return_value = True

        drv.do_setup(self.context)

        mock_os_path_exists.assert_not_called()

    def test_setup_throw_error_if_shares_file_does_not_exist_no_host(self):
        """do_setup should throw error if no shares file and no host set."""

        drv = nfs.NfsDriver(configuration=self.configuration)

        self.override_config('nas_share_path', '/export')
        mock_os_path_exists = self.mock_object(os.path, 'exists')
        mock_os_path_exists.return_value = False

        with self.assertRaisesRegex(exception.NfsException,
                                    "NFS config file.*doesn't exist"):
            drv.do_setup(self.context)

        mock_os_path_exists.assert_has_calls(
            [mock.call(self.configuration.nfs_shares_config)])

    def test_setup_throw_error_if_shares_file_does_not_exist_no_share(self):
        """do_setup should throw error if no shares file and no share set."""

        drv = nfs.NfsDriver(configuration=self.configuration)

        self.override_config('nas_host', 'nfs-host1')
        mock_os_path_exists = self.mock_object(os.path, 'exists')
        mock_os_path_exists.return_value = False

        with self.assertRaisesRegex(exception.NfsException,
                                    "NFS config file.*doesn't exist"):
            drv.do_setup(self.context)

        mock_os_path_exists.assert_has_calls(
            [mock.call(self.configuration.nfs_shares_config)])

    def test_setup_throw_error_if_shares_file_doesnt_exist_no_share_host(self):
        """do_setup should throw error if no shares file and no host/share."""

        drv = nfs.NfsDriver(configuration=self.configuration)

        mock_os_path_exists = self.mock_object(os.path, 'exists')
        mock_os_path_exists.return_value = False

        with self.assertRaisesRegex(exception.NfsException,
                                    "NFS config file.*doesn't exist"):
            drv.do_setup(self.context)

        mock_os_path_exists.assert_has_calls(
            [mock.call(self.configuration.nfs_shares_config)])

    def test_setup_should_throw_exception_if_nfs_client_is_not_installed(self):
        """do_setup should throw error if nfs client is not installed."""

        drv = nfs.NfsDriver(configuration=self.configuration)

        mock_os_path_exists = self.mock_object(os.path, 'exists')
        mock_os_path_exists.return_value = True
        mock_execute = self.mock_object(drv, '_execute')
        mock_execute.side_effect = OSError(
            errno.ENOENT, 'No such file or directory.')

        with self.assertRaisesRegex(exception.NfsException,
                                    'mount.nfs is not installed'):
            drv.do_setup(self.context)

        mock_os_path_exists.assert_has_calls(
            [mock.call(self.configuration.nfs_shares_config)])
        mock_execute.assert_has_calls(
            [mock.call('mount.nfs',
                       check_exit_code=False,
                       run_as_root=True)])

    def test_setup_should_throw_exception_if_mount_nfs_command_fails(self):
        """do_setup should throw error if mount.nfs fails with OSError

           This test covers the OSError path when mount.nfs is installed.
        """

        drv = nfs.NfsDriver(configuration=self.configuration)

        mock_os_path_exists = self.mock_object(os.path, 'exists')
        mock_os_path_exists.return_value = True
        mock_execute = self.mock_object(drv, '_execute')
        mock_execute.side_effect = OSError(
            errno.EPERM, 'Operation... BROKEN')

        with self.assertRaisesRegex(OSError, '.*Operation... BROKEN'):
            drv.do_setup(self.context)

        mock_os_path_exists.assert_has_calls(
            [mock.call(self.configuration.nfs_shares_config)])
        mock_execute.assert_has_calls(
            [mock.call('mount.nfs',
                       check_exit_code=False,
                       run_as_root=True)])

    def test_retype_is_there(self):
        "Ensure that driver.retype() is there."""

        drv = nfs.NfsDriver(configuration=self.configuration)
        v1 = fake_volume.fake_volume_obj(self.context)

        ret = drv.retype(self.context,
                         v1,
                         mock.sentinel.new_type,
                         mock.sentinel.diff,
                         mock.sentinel.host)

        self.assertEqual((False, None), ret)
