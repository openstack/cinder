# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

import __builtin__
import errno
import os

import mox as mox_lib
from mox import IgnoreArg
from mox import IsA
from mox import stubout
from oslo.config import cfg

from cinder import context
from cinder import exception
from cinder.image import image_utils
from cinder.openstack.common import processutils as putils
from cinder import test
from cinder import units
from cinder.volume import configuration as conf
from cinder.volume.drivers import nfs


class DumbVolume(object):
    fields = {}

    def __setitem__(self, key, value):
        self.fields[key] = value

    def __getitem__(self, item):
        return self.fields[item]


class RemoteFsDriverTestCase(test.TestCase):
    TEST_FILE_NAME = 'test.txt'

    def setUp(self):
        super(RemoteFsDriverTestCase, self).setUp()
        self._driver = nfs.RemoteFsDriver()
        self._mox = mox_lib.Mox()
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
                     '%s' % str(file_size * units.GiB), run_as_root=True)

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


class NfsDriverTestCase(test.TestCase):
    """Test case for NFS driver."""

    TEST_NFS_EXPORT1 = 'nfs-host1:/export'
    TEST_NFS_EXPORT2 = 'nfs-host2:/export'
    TEST_NFS_EXPORT2_OPTIONS = '-o intr'
    TEST_SIZE_IN_GB = 1
    TEST_MNT_POINT = '/mnt/nfs'
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
                                 size=self.TEST_SIZE_IN_GB)

        mox.StubOutWithMock(image_utils, 'resize_image')
        image_utils.resize_image(TEST_IMG_SOURCE, self.TEST_SIZE_IN_GB)

        mox.StubOutWithMock(image_utils, 'qemu_img_info')
        data = mox_lib.MockAnything()
        data.virtual_size = 1 * units.GiB
        image_utils.qemu_img_info(TEST_IMG_SOURCE).AndReturn(data)

        mox.ReplayAll()

        drv.copy_image_to_volume(None, volume, None, None)

        mox.VerifyAll()

    def test_get_mount_point_for_share(self):
        """_get_mount_point_for_share should calculate correct value."""
        drv = self._driver

        self.configuration.nfs_mount_point_base = self.TEST_MNT_POINT_BASE

        self.assertEqual('/mnt/test/2f4f60214cf43c595666dd815f0360a4',
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
        drv._read_config_file(self.TEST_SHARES_CONFIG_FILE).\
            AndReturn(config_data)
        mox.ReplayAll()

        drv._load_shares_config(drv.configuration.nfs_shares_config)

        self.assertIn(self.TEST_NFS_EXPORT1, drv.shares)
        self.assertIn(self.TEST_NFS_EXPORT2, drv.shares)
        self.assertEqual(len(drv.shares), 2)

        self.assertEqual(drv.shares[self.TEST_NFS_EXPORT2],
                         self.TEST_NFS_EXPORT2_OPTIONS)

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
        mox = self._mox
        drv = self._driver

        mox.StubOutWithMock(drv, '_read_config_file')
        config_data = []
        config_data.append(self.TEST_NFS_EXPORT1)
        drv._read_config_file(self.TEST_SHARES_CONFIG_FILE).\
            AndReturn(config_data)

        mox.StubOutWithMock(drv, '_ensure_share_mounted')
        drv.configuration.nfs_shares_config = self.TEST_SHARES_CONFIG_FILE
        drv._ensure_share_mounted(self.TEST_NFS_EXPORT1).AndRaise(Exception())

        mox.ReplayAll()

        drv._ensure_shares_mounted()

        self.assertEqual(0, len(drv._mounted_shares))

        mox.VerifyAll()

    def test_setup_should_throw_error_if_shares_config_not_configured(self):
        """do_setup should throw error if shares config is not configured."""
        drv = self._driver
        self.configuration.nfs_shares_config = self.TEST_SHARES_CONFIG_FILE

        self.assertRaises(exception.NfsException,
                          drv.do_setup, IsA(context.RequestContext))

    def test_setup_should_throw_error_if_oversub_ratio_less_than_zero(self):
        """do_setup should throw error if nfs_oversub_ratio is less than 0."""
        drv = self._driver
        self.configuration.nfs_oversub_ratio = -1
        self.assertRaises(exception.NfsException,
                          drv.do_setup,
                          IsA(context.RequestContext))

    def test_setup_should_throw_error_if_used_ratio_less_than_zero(self):
        """do_setup should throw error if nfs_used_ratio is less than 0."""
        drv = self._driver
        self.configuration.nfs_used_ratio = -1
        self.assertRaises(exception.NfsException,
                          drv.do_setup,
                          IsA(context.RequestContext))

    def test_setup_should_throw_error_if_used_ratio_greater_than_one(self):
        """do_setup should throw error if nfs_used_ratio is greater than 1."""
        drv = self._driver
        self.configuration.nfs_used_ratio = 2
        self.assertRaises(exception.NfsException,
                          drv.do_setup,
                          IsA(context.RequestContext))

    def test_setup_should_throw_exception_if_nfs_client_is_not_installed(self):
        """do_setup should throw error if nfs client is not installed."""
        mox = self._mox
        drv = self._driver
        self.configuration.nfs_shares_config = self.TEST_SHARES_CONFIG_FILE

        mox.StubOutWithMock(os.path, 'exists')
        os.path.exists(self.TEST_SHARES_CONFIG_FILE).AndReturn(True)
        mox.StubOutWithMock(drv, '_execute')
        drv._execute('mount.nfs', check_exit_code=False, run_as_root=True).\
            AndRaise(OSError(errno.ENOENT, 'No such file or directory'))

        mox.ReplayAll()

        self.assertRaises(exception.NfsException,
                          drv.do_setup, IsA(context.RequestContext))

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
            AndReturn((5 * units.GiB, 2 * units.GiB,
                       2 * units.GiB))
        drv._get_capacity_info(self.TEST_NFS_EXPORT1).\
            AndReturn((5 * units.GiB, 2 * units.GiB,
                       2 * units.GiB))
        drv._get_capacity_info(self.TEST_NFS_EXPORT2).\
            AndReturn((10 * units.GiB, 3 * units.GiB,
                       1 * units.GiB))
        drv._get_capacity_info(self.TEST_NFS_EXPORT2).\
            AndReturn((10 * units.GiB, 3 * units.GiB,
                       1 * units.GiB))

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
            AndReturn((5 * units.GiB, 0, 5 * units.GiB))
        drv._get_capacity_info(self.TEST_NFS_EXPORT2).\
            AndReturn((10 * units.GiB, 0,
                       10 * units.GiB))

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

        setattr(cfg.CONF, 'nfs_sparsed_volumes', True)

        mox.StubOutWithMock(drv, '_create_sparsed_file')
        mox.StubOutWithMock(drv, '_set_rw_permissions_for_all')

        drv._create_sparsed_file(IgnoreArg(), IgnoreArg())
        drv._set_rw_permissions_for_all(IgnoreArg())

        mox.ReplayAll()

        drv._do_create_volume(volume)

        mox.VerifyAll()

        delattr(cfg.CONF, 'nfs_sparsed_volumes')

    def test_create_nonsparsed_volume(self):
        mox = self._mox
        drv = self._driver
        self.configuration.nfs_sparsed_volumes = False
        volume = self._simple_volume()

        setattr(cfg.CONF, 'nfs_sparsed_volumes', False)

        mox.StubOutWithMock(drv, '_create_regular_file')
        mox.StubOutWithMock(drv, '_set_rw_permissions_for_all')

        drv._create_regular_file(IgnoreArg(), IgnoreArg())
        drv._set_rw_permissions_for_all(IgnoreArg())

        mox.ReplayAll()

        drv._do_create_volume(volume)

        mox.VerifyAll()

        delattr(cfg.CONF, 'nfs_sparsed_volumes')

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
        mox = self._mox
        drv = self._driver

        self.stub_out_not_replaying(drv, '_ensure_share_mounted')

        volume = DumbVolume()
        volume['name'] = 'volume-123'
        volume['provider_location'] = None

        mox.StubOutWithMock(drv, '_execute')

        mox.ReplayAll()

        drv.delete_volume(volume)

        mox.VerifyAll()

    def test_get_volume_stats(self):
        """get_volume_stats must fill the correct values"""
        mox = self._mox
        drv = self._driver

        drv._mounted_shares = [self.TEST_NFS_EXPORT1, self.TEST_NFS_EXPORT2]

        mox.StubOutWithMock(drv, '_ensure_shares_mounted')
        mox.StubOutWithMock(drv, '_get_capacity_info')

        drv._ensure_shares_mounted()

        drv._get_capacity_info(self.TEST_NFS_EXPORT1).\
            AndReturn((10 * units.GiB, 2 * units.GiB,
                       2 * units.GiB))
        drv._get_capacity_info(self.TEST_NFS_EXPORT2).\
            AndReturn((20 * units.GiB, 3 * units.GiB,
                       3 * units.GiB))

        mox.ReplayAll()

        drv.get_volume_stats()
        self.assertEqual(drv._stats['total_capacity_gb'], 30.0)
        self.assertEqual(drv._stats['free_capacity_gb'], 5.0)

        mox.VerifyAll()
