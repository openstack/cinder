# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 Red Hat, Inc.
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
"""Unit tests for the GlusterFS driver module."""


import errno
import os

import mox as mox_lib
from mox import IgnoreArg
from mox import IsA
from mox import stubout

from cinder import context
from cinder import exception
from cinder.exception import ProcessExecutionError
from cinder import test
from cinder.volume import configuration as conf
from cinder.volume.drivers import glusterfs


class DumbVolume(object):
    fields = {}

    def __setitem__(self, key, value):
        self.fields[key] = value

    def __getitem__(self, item):
        return self.fields[item]


class GlusterFsDriverTestCase(test.TestCase):
    """Test case for GlusterFS driver."""

    TEST_EXPORT1 = 'glusterfs-host1:/export'
    TEST_EXPORT2 = 'glusterfs-host2:/export'
    TEST_EXPORT2_OPTIONS = '-o backupvolfile-server=glusterfs-backup1'
    TEST_SIZE_IN_GB = 1
    TEST_MNT_POINT = '/mnt/glusterfs'
    TEST_MNT_POINT_BASE = '/mnt/test'
    TEST_LOCAL_PATH = '/mnt/glusterfs/volume-123'
    TEST_FILE_NAME = 'test.txt'
    TEST_SHARES_CONFIG_FILE = '/etc/cinder/test-shares.conf'
    ONE_GB_IN_BYTES = 1024 * 1024 * 1024

    def setUp(self):
        super(GlusterFsDriverTestCase, self).setUp()
        self._mox = mox_lib.Mox()
        self._configuration = mox_lib.MockObject(conf.Configuration)
        self._configuration.append_config_values(mox_lib.IgnoreArg())
        self._configuration.glusterfs_shares_config = \
            self.TEST_SHARES_CONFIG_FILE
        self._configuration.glusterfs_mount_point_base = \
            self.TEST_MNT_POINT_BASE
        self._configuration.glusterfs_disk_util = 'df'
        self._configuration.glusterfs_sparsed_volumes = True

        self.stubs = stubout.StubOutForTesting()
        self._driver =\
            glusterfs.GlusterfsDriver(configuration=self._configuration)
        self._driver.shares = {}

    def tearDown(self):
        self._mox.UnsetStubs()
        self.stubs.UnsetAll()
        super(GlusterFsDriverTestCase, self).tearDown()

    def stub_out_not_replaying(self, obj, attr_name):
        attr_to_replace = getattr(obj, attr_name)
        stub = mox_lib.MockObject(attr_to_replace)
        self.stubs.Set(obj, attr_name, stub)

    def test_local_path(self):
        """local_path common use case."""
        glusterfs.CONF.glusterfs_mount_point_base = self.TEST_MNT_POINT_BASE
        drv = self._driver

        volume = DumbVolume()
        volume['provider_location'] = self.TEST_EXPORT1
        volume['name'] = 'volume-123'

        self.assertEqual(
            '/mnt/test/ab03ab34eaca46a5fb81878f7e9b91fc/volume-123',
            drv.local_path(volume))

    def test_mount_glusterfs_should_mount_correctly(self):
        """_mount_glusterfs common case usage."""
        mox = self._mox
        drv = self._driver

        mox.StubOutWithMock(drv, '_execute')
        drv._execute('mkdir', '-p', self.TEST_MNT_POINT)
        drv._execute('mount', '-t', 'glusterfs', self.TEST_EXPORT1,
                     self.TEST_MNT_POINT, run_as_root=True)

        mox.ReplayAll()

        drv._mount_glusterfs(self.TEST_EXPORT1, self.TEST_MNT_POINT)

        mox.VerifyAll()

    def test_mount_glusterfs_should_suppress_already_mounted_error(self):
        """_mount_glusterfs should suppress already mounted error if
           ensure=True
        """
        mox = self._mox
        drv = self._driver

        mox.StubOutWithMock(drv, '_execute')
        drv._execute('mkdir', '-p', self.TEST_MNT_POINT)
        drv._execute('mount', '-t', 'glusterfs', self.TEST_EXPORT1,
                     self.TEST_MNT_POINT, run_as_root=True).\
            AndRaise(ProcessExecutionError(
                     stderr='is busy or already mounted'))

        mox.ReplayAll()

        drv._mount_glusterfs(self.TEST_EXPORT1, self.TEST_MNT_POINT,
                             ensure=True)

        mox.VerifyAll()

    def test_mount_glusterfs_should_reraise_already_mounted_error(self):
        """_mount_glusterfs should not suppress already mounted error
           if ensure=False
        """
        mox = self._mox
        drv = self._driver

        mox.StubOutWithMock(drv, '_execute')
        drv._execute('mkdir', '-p', self.TEST_MNT_POINT)
        drv._execute(
            'mount',
            '-t',
            'glusterfs',
            self.TEST_EXPORT1,
            self.TEST_MNT_POINT,
            run_as_root=True). \
            AndRaise(ProcessExecutionError(stderr='is busy or '
                                                  'already mounted'))

        mox.ReplayAll()

        self.assertRaises(ProcessExecutionError, drv._mount_glusterfs,
                          self.TEST_EXPORT1, self.TEST_MNT_POINT,
                          ensure=False)

        mox.VerifyAll()

    def test_mount_glusterfs_should_create_mountpoint_if_not_yet(self):
        """_mount_glusterfs should create mountpoint if it doesn't exist."""
        mox = self._mox
        drv = self._driver

        mox.StubOutWithMock(drv, '_execute')
        drv._execute('mkdir', '-p', self.TEST_MNT_POINT)
        drv._execute(*([IgnoreArg()] * 5), run_as_root=IgnoreArg())

        mox.ReplayAll()

        drv._mount_glusterfs(self.TEST_EXPORT1, self.TEST_MNT_POINT)

        mox.VerifyAll()

    def test_get_hash_str(self):
        """_get_hash_str should calculation correct value."""
        drv = self._driver

        self.assertEqual('ab03ab34eaca46a5fb81878f7e9b91fc',
                         drv._get_hash_str(self.TEST_EXPORT1))

    def test_get_mount_point_for_share(self):
        """_get_mount_point_for_share should calculate correct value."""
        drv = self._driver

        glusterfs.CONF.glusterfs_mount_point_base = self.TEST_MNT_POINT_BASE

        self.assertEqual('/mnt/test/ab03ab34eaca46a5fb81878f7e9b91fc',
                         drv._get_mount_point_for_share(
                             self.TEST_EXPORT1))

    def test_get_available_capacity_with_df(self):
        """_get_available_capacity should calculate correct value."""
        mox = self._mox
        drv = self._driver

        df_total_size = 2620544
        df_avail = 1490560
        df_head = 'Filesystem 1K-blocks Used Available Use% Mounted on\n'
        df_data = 'glusterfs-host:/export %d 996864 %d 41%% /mnt' % \
                  (df_total_size, df_avail)
        df_output = df_head + df_data

        setattr(glusterfs.CONF, 'glusterfs_disk_util', 'df')

        mox.StubOutWithMock(drv, '_get_mount_point_for_share')
        drv._get_mount_point_for_share(self.TEST_EXPORT1).\
            AndReturn(self.TEST_MNT_POINT)

        mox.StubOutWithMock(drv, '_execute')
        drv._execute('df', '--portability', '--block-size', '1',
                     self.TEST_MNT_POINT,
                     run_as_root=True).AndReturn((df_output, None))

        mox.ReplayAll()

        self.assertEquals((df_avail, df_total_size),
                          drv._get_available_capacity(
                              self.TEST_EXPORT1))

        mox.VerifyAll()

        delattr(glusterfs.CONF, 'glusterfs_disk_util')

    def test_get_available_capacity_with_du(self):
        """_get_available_capacity should calculate correct value."""
        mox = self._mox
        drv = self._driver

        old_value = self._configuration.glusterfs_disk_util
        self._configuration.glusterfs_disk_util = 'du'

        df_total_size = 2620544
        df_used_size = 996864
        df_avail_size = 1490560
        df_title = 'Filesystem 1-blocks Used Available Use% Mounted on\n'
        df_mnt_data = 'glusterfs-host:/export %d %d %d 41%% /mnt' % \
                      (df_total_size,
                       df_used_size,
                       df_avail_size)
        df_output = df_title + df_mnt_data

        du_used = 490560
        du_output = '%d /mnt' % du_used

        mox.StubOutWithMock(drv, '_get_mount_point_for_share')
        drv._get_mount_point_for_share(self.TEST_EXPORT1).\
            AndReturn(self.TEST_MNT_POINT)

        mox.StubOutWithMock(drv, '_execute')
        drv._execute('df', '--portability', '--block-size', '1',
                     self.TEST_MNT_POINT,
                     run_as_root=True).\
            AndReturn((df_output, None))
        drv._execute('du', '-sb', '--apparent-size',
                     '--exclude', '*snapshot*',
                     self.TEST_MNT_POINT,
                     run_as_root=True).AndReturn((du_output, None))

        mox.ReplayAll()

        self.assertEquals((df_total_size - du_used, df_total_size),
                          drv._get_available_capacity(
                              self.TEST_EXPORT1))

        mox.VerifyAll()

        self._configuration.glusterfs_disk_util = old_value

    def test_load_shares_config(self):
        mox = self._mox
        drv = self._driver

        drv.configuration.glusterfs_shares_config = (
            self.TEST_SHARES_CONFIG_FILE)

        mox.StubOutWithMock(drv, '_read_config_file')
        config_data = []
        config_data.append(self.TEST_EXPORT1)
        config_data.append('#' + self.TEST_EXPORT2)
        config_data.append(self.TEST_EXPORT2 + ' ' + self.TEST_EXPORT2_OPTIONS)
        config_data.append('')
        drv._read_config_file(self.TEST_SHARES_CONFIG_FILE).\
            AndReturn(config_data)
        mox.ReplayAll()

        drv._load_shares_config(drv.configuration.glusterfs_shares_config)

        self.assertIn(self.TEST_EXPORT1, drv.shares)
        self.assertIn(self.TEST_EXPORT2, drv.shares)
        self.assertEqual(len(drv.shares), 2)

        self.assertEqual(drv.shares[self.TEST_EXPORT2],
                         self.TEST_EXPORT2_OPTIONS)

        mox.VerifyAll()

    def test_ensure_share_mounted(self):
        """_ensure_share_mounted simple use case."""
        mox = self._mox
        drv = self._driver

        mox.StubOutWithMock(drv, '_get_mount_point_for_share')
        drv._get_mount_point_for_share(self.TEST_EXPORT1).\
            AndReturn(self.TEST_MNT_POINT)

        mox.StubOutWithMock(drv, '_mount_glusterfs')
        drv._mount_glusterfs(self.TEST_EXPORT1, self.TEST_MNT_POINT,
                             ensure=True)

        mox.ReplayAll()

        drv._ensure_share_mounted(self.TEST_EXPORT1)

        mox.VerifyAll()

    def test_ensure_shares_mounted_should_save_mounting_successfully(self):
        """_ensure_shares_mounted should save share if mounted with success."""
        mox = self._mox
        drv = self._driver

        mox.StubOutWithMock(drv, '_read_config_file')
        config_data = []
        config_data.append(self.TEST_EXPORT1)
        drv._read_config_file(self.TEST_SHARES_CONFIG_FILE).\
            AndReturn(config_data)

        mox.StubOutWithMock(drv, '_ensure_share_mounted')
        drv._ensure_share_mounted(self.TEST_EXPORT1)

        mox.ReplayAll()

        drv._ensure_shares_mounted()

        self.assertEqual(1, len(drv._mounted_shares))
        self.assertEqual(self.TEST_EXPORT1, drv._mounted_shares[0])

        mox.VerifyAll()

    def test_ensure_shares_mounted_should_not_save_mounting_with_error(self):
        """_ensure_shares_mounted should not save share if failed to mount."""
        mox = self._mox
        drv = self._driver

        mox.StubOutWithMock(drv, '_read_config_file')
        config_data = []
        config_data.append(self.TEST_EXPORT1)
        drv._read_config_file(self.TEST_SHARES_CONFIG_FILE).\
            AndReturn(config_data)

        mox.StubOutWithMock(drv, '_ensure_share_mounted')
        drv._ensure_share_mounted(self.TEST_EXPORT1).AndRaise(Exception())

        mox.ReplayAll()

        drv._ensure_shares_mounted()

        self.assertEqual(0, len(drv._mounted_shares))

        mox.VerifyAll()

    def test_setup_should_throw_error_if_shares_config_not_configured(self):
        """do_setup should throw error if shares config is not configured."""
        drv = self._driver

        glusterfs.CONF.glusterfs_shares_config = self.TEST_SHARES_CONFIG_FILE

        self.assertRaises(exception.GlusterfsException,
                          drv.do_setup, IsA(context.RequestContext))

    def test_setup_should_throw_exception_if_client_is_not_installed(self):
        """do_setup should throw exception if client is not installed."""
        mox = self._mox
        drv = self._driver

        glusterfs.CONF.glusterfs_shares_config = self.TEST_SHARES_CONFIG_FILE

        mox.StubOutWithMock(os.path, 'exists')
        os.path.exists(self.TEST_SHARES_CONFIG_FILE).AndReturn(True)
        mox.StubOutWithMock(drv, '_execute')
        drv._execute('mount.glusterfs', check_exit_code=False).\
            AndRaise(OSError(errno.ENOENT, 'No such file or directory'))

        mox.ReplayAll()

        self.assertRaises(exception.GlusterfsException,
                          drv.do_setup, IsA(context.RequestContext))

        mox.VerifyAll()

    def test_find_share_should_throw_error_if_there_is_no_mounted_shares(self):
        """_find_share should throw error if there is no mounted shares."""
        drv = self._driver

        drv._mounted_shares = []

        self.assertRaises(exception.NotFound, drv._find_share,
                          self.TEST_SIZE_IN_GB)

    def test_find_share(self):
        """_find_share simple use case."""
        mox = self._mox
        drv = self._driver

        drv._mounted_shares = [self.TEST_EXPORT1, self.TEST_EXPORT2]

        mox.StubOutWithMock(drv, '_get_available_capacity')
        drv._get_available_capacity(self.TEST_EXPORT1).\
            AndReturn((2 * self.ONE_GB_IN_BYTES, 5 * self.ONE_GB_IN_BYTES))
        drv._get_available_capacity(self.TEST_EXPORT2).\
            AndReturn((3 * self.ONE_GB_IN_BYTES, 10 * self.ONE_GB_IN_BYTES))

        mox.ReplayAll()

        self.assertEqual(self.TEST_EXPORT2,
                         drv._find_share(self.TEST_SIZE_IN_GB))

        mox.VerifyAll()

    def test_find_share_should_throw_error_if_there_is_no_enough_place(self):
        """_find_share should throw error if there is no share to host vol."""
        mox = self._mox
        drv = self._driver

        drv._mounted_shares = [self.TEST_EXPORT1,
                               self.TEST_EXPORT2]

        mox.StubOutWithMock(drv, '_get_available_capacity')
        drv._get_available_capacity(self.TEST_EXPORT1).\
            AndReturn((0, 5 * self.ONE_GB_IN_BYTES))
        drv._get_available_capacity(self.TEST_EXPORT2).\
            AndReturn((0, 10 * self.ONE_GB_IN_BYTES))

        mox.ReplayAll()

        self.assertRaises(exception.GlusterfsNoSuitableShareFound,
                          drv._find_share,
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

        setattr(glusterfs.CONF, 'glusterfs_sparsed_volumes', True)

        mox.StubOutWithMock(drv, '_create_sparsed_file')
        mox.StubOutWithMock(drv, '_set_rw_permissions_for_all')

        drv._create_sparsed_file(IgnoreArg(), IgnoreArg())
        drv._set_rw_permissions_for_all(IgnoreArg())

        mox.ReplayAll()

        drv._do_create_volume(volume)

        mox.VerifyAll()

        delattr(glusterfs.CONF, 'glusterfs_sparsed_volumes')

    def test_create_nonsparsed_volume(self):
        mox = self._mox
        drv = self._driver
        volume = self._simple_volume()

        old_value = self._configuration.glusterfs_sparsed_volumes
        self._configuration.glusterfs_sparsed_volumes = False

        mox.StubOutWithMock(drv, '_create_regular_file')
        mox.StubOutWithMock(drv, '_set_rw_permissions_for_all')

        drv._create_regular_file(IgnoreArg(), IgnoreArg())
        drv._set_rw_permissions_for_all(IgnoreArg())

        mox.ReplayAll()

        drv._do_create_volume(volume)

        mox.VerifyAll()

        self._configuration.glusterfs_sparsed_volumes = old_value

    def test_create_volume_should_ensure_glusterfs_mounted(self):
        """create_volume ensures shares provided in config are mounted."""
        mox = self._mox
        drv = self._driver

        self.stub_out_not_replaying(glusterfs, 'LOG')
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

        self.stub_out_not_replaying(glusterfs, 'LOG')
        self.stub_out_not_replaying(drv, '_ensure_shares_mounted')
        self.stub_out_not_replaying(drv, '_do_create_volume')

        mox.StubOutWithMock(drv, '_find_share')
        drv._find_share(self.TEST_SIZE_IN_GB).AndReturn(self.TEST_EXPORT1)

        mox.ReplayAll()

        volume = DumbVolume()
        volume['size'] = self.TEST_SIZE_IN_GB
        result = drv.create_volume(volume)
        self.assertEqual(self.TEST_EXPORT1, result['provider_location'])

        mox.VerifyAll()

    def test_delete_volume(self):
        """delete_volume simple test case."""
        mox = self._mox
        drv = self._driver

        self.stub_out_not_replaying(drv, '_ensure_share_mounted')

        volume = DumbVolume()
        volume['name'] = 'volume-123'
        volume['provider_location'] = self.TEST_EXPORT1

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
        volume['provider_location'] = self.TEST_EXPORT1

        mox.StubOutWithMock(drv, '_ensure_share_mounted')
        drv._ensure_share_mounted(self.TEST_EXPORT1)

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
