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

import contextlib
import errno
import mock
import os
import tempfile

import mox as mox_lib
from mox import IgnoreArg
from mox import IsA
from mox import stubout

from cinder import brick
from cinder import context
from cinder import db
from cinder import exception
from cinder.image import image_utils
from cinder.openstack.common import imageutils
from cinder.openstack.common import processutils as putils
from cinder import test
from cinder import units
from cinder import utils
from cinder.volume import configuration as conf
from cinder.volume import driver as base_driver
from cinder.volume.drivers import glusterfs


class DumbVolume(object):
    fields = {}

    def __setitem__(self, key, value):
        self.fields[key] = value

    def __getitem__(self, item):
        return self.fields[item]


class FakeDb(object):
    msg = "Tests are broken: mock this out."

    def volume_get(self, *a, **kw):
        raise Exception(self.msg)

    def snapshot_get_all_for_volume(self, *a, **kw):
        """Mock this if you want results from it."""
        return []


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
    VOLUME_UUID = 'abcdefab-cdef-abcd-efab-cdefabcdefab'
    VOLUME_NAME = 'volume-%s' % VOLUME_UUID
    SNAP_UUID = 'bacadaca-baca-daca-baca-dacadacadaca'
    SNAP_UUID_2 = 'bebedede-bebe-dede-bebe-dedebebedede'

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
        self._configuration.glusterfs_qcow2_volumes = False

        self.stubs = stubout.StubOutForTesting()
        self._driver =\
            glusterfs.GlusterfsDriver(configuration=self._configuration,
                                      db=FakeDb())
        self._driver.shares = {}

    def tearDown(self):
        self._mox.UnsetStubs()
        self.stubs.UnsetAll()
        super(GlusterFsDriverTestCase, self).tearDown()

    def stub_out_not_replaying(self, obj, attr_name):
        attr_to_replace = getattr(obj, attr_name)
        stub = mox_lib.MockObject(attr_to_replace)
        self.stubs.Set(obj, attr_name, stub)

    def test_set_execute(self):
        mox = self._mox
        drv = self._driver

        rfsclient = brick.remotefs.remotefs.RemoteFsClient

        mox.StubOutWithMock(rfsclient, 'set_execute')

        def my_execute(*a, **k):
            pass

        rfsclient.set_execute(my_execute)

        mox.ReplayAll()

        drv.set_execute(my_execute)

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
            AndRaise(putils.ProcessExecutionError(
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
            AndRaise(putils.ProcessExecutionError(stderr='is busy or '
                                                         'already mounted'))

        mox.ReplayAll()

        self.assertRaises(putils.ProcessExecutionError, drv._mount_glusterfs,
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
        """_get_mount_point_for_share should call RemoteFsClient."""
        mox = self._mox
        drv = self._driver
        hashed_path = '/mnt/test/abcdefabcdef'

        mox.StubOutWithMock(brick.remotefs.remotefs.RemoteFsClient,
                            'get_mount_point')

        glusterfs.CONF.glusterfs_mount_point_base = self.TEST_MNT_POINT_BASE

        brick.remotefs.remotefs.RemoteFsClient.\
            get_mount_point(self.TEST_EXPORT1).AndReturn(hashed_path)

        mox.ReplayAll()

        drv._get_mount_point_for_share(self.TEST_EXPORT1)

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

        self.assertEqual((df_avail, df_total_size),
                         drv._get_available_capacity(self.TEST_EXPORT1))

        mox.VerifyAll()

        delattr(glusterfs.CONF, 'glusterfs_disk_util')

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
        config_data.append('broken:share_format')
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

        mox.StubOutWithMock(utils, 'get_file_mode')
        mox.StubOutWithMock(utils, 'get_file_gid')
        mox.StubOutWithMock(drv, '_execute')
        mox.StubOutWithMock(drv, '_ensure_share_writable')

        mox.StubOutWithMock(drv, '_get_mount_point_for_share')
        drv._get_mount_point_for_share(self.TEST_EXPORT1).\
            AndReturn(self.TEST_MNT_POINT)

        mox.StubOutWithMock(drv, '_mount_glusterfs')
        drv._mount_glusterfs(self.TEST_EXPORT1, self.TEST_MNT_POINT,
                             ensure=True)

        utils.get_file_gid(self.TEST_MNT_POINT).AndReturn(333333)

        utils.get_file_mode(self.TEST_MNT_POINT).AndReturn(0o777)

        drv._ensure_share_writable(self.TEST_MNT_POINT)

        drv._execute('chgrp', IgnoreArg(), self.TEST_MNT_POINT,
                     run_as_root=True)

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

    def _fake_load_shares_config(self, conf):
        self._driver.shares = {'127.7.7.7:/gluster1': None}

    def _fake_NamedTemporaryFile(self, prefix=None, dir=None):
        raise OSError('Permission denied!')

    def test_setup_set_share_permissions(self):
        mox = self._mox
        drv = self._driver

        glusterfs.CONF.glusterfs_shares_config = self.TEST_SHARES_CONFIG_FILE

        self.stubs.Set(drv, '_load_shares_config',
                       self._fake_load_shares_config)
        self.stubs.Set(tempfile, 'NamedTemporaryFile',
                       self._fake_NamedTemporaryFile)
        mox.StubOutWithMock(os.path, 'exists')
        mox.StubOutWithMock(drv, '_execute')
        mox.StubOutWithMock(utils, 'get_file_gid')
        mox.StubOutWithMock(utils, 'get_file_mode')
        mox.StubOutWithMock(os, 'getegid')

        drv._execute('mount.glusterfs', check_exit_code=False)

        drv._execute('mkdir', '-p', mox_lib.IgnoreArg())

        os.path.exists(self.TEST_SHARES_CONFIG_FILE).AndReturn(True)

        drv._execute('mount', '-t', 'glusterfs', '127.7.7.7:/gluster1',
                     mox_lib.IgnoreArg(), run_as_root=True)

        utils.get_file_gid(mox_lib.IgnoreArg()).AndReturn(33333)
        # perms not writable
        utils.get_file_mode(mox_lib.IgnoreArg()).AndReturn(0o000)

        os.getegid().AndReturn(888)

        drv._execute('chgrp', 888, mox_lib.IgnoreArg(), run_as_root=True)
        drv._execute('chmod', 'g+w', mox_lib.IgnoreArg(), run_as_root=True)

        mox.ReplayAll()

        drv.do_setup(IsA(context.RequestContext))

        mox.VerifyAll()

    def test_find_share_should_throw_error_if_there_is_no_mounted_shares(self):
        """_find_share should throw error if there is no mounted shares."""
        drv = self._driver

        drv._mounted_shares = []

        self.assertRaises(exception.GlusterfsNoSharesMounted,
                          drv._find_share,
                          self.TEST_SIZE_IN_GB)

    def test_find_share(self):
        """_find_share simple use case."""
        mox = self._mox
        drv = self._driver

        drv._mounted_shares = [self.TEST_EXPORT1, self.TEST_EXPORT2]

        mox.StubOutWithMock(drv, '_get_available_capacity')
        drv._get_available_capacity(self.TEST_EXPORT1).\
            AndReturn((2 * units.GiB, 5 * units.GiB))
        drv._get_available_capacity(self.TEST_EXPORT2).\
            AndReturn((3 * units.GiB, 10 * units.GiB))

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
            AndReturn((0, 5 * units.GiB))
        drv._get_available_capacity(self.TEST_EXPORT2).\
            AndReturn((0, 10 * units.GiB))

        mox.ReplayAll()

        self.assertRaises(exception.GlusterfsNoSuitableShareFound,
                          drv._find_share,
                          self.TEST_SIZE_IN_GB)

        mox.VerifyAll()

    def _simple_volume(self, id=None):
        volume = DumbVolume()
        volume['provider_location'] = self.TEST_EXPORT1
        if id is None:
            volume['id'] = self.VOLUME_UUID
        else:
            volume['id'] = id
        # volume['name'] mirrors format from db/sqlalchemy/models.py
        volume['name'] = 'volume-%s' % volume['id']
        volume['size'] = 10
        volume['status'] = 'available'

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

    def test_create_qcow2_volume(self):
        (mox, drv) = self._mox, self._driver

        volume = self._simple_volume()
        old_value = self._configuration.glusterfs_qcow2_volumes
        self._configuration.glusterfs_qcow2_volumes = True

        mox.StubOutWithMock(drv, '_execute')

        hashed = drv._get_hash_str(volume['provider_location'])
        path = '%s/%s/volume-%s' % (self.TEST_MNT_POINT_BASE,
                                    hashed,
                                    self.VOLUME_UUID)

        drv._execute('qemu-img', 'create', '-f', 'qcow2',
                     '-o', 'preallocation=metadata', path,
                     str(volume['size'] * units.GiB),
                     run_as_root=True)

        drv._execute('chmod', 'ugo+rw', path, run_as_root=True)

        mox.ReplayAll()

        drv._do_create_volume(volume)

        mox.VerifyAll()

        self._configuration.glusterfs_qcow2_volumes = old_value

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

    def test_create_cloned_volume(self):
        (mox, drv) = self._mox, self._driver

        mox.StubOutWithMock(drv, '_create_snapshot')
        mox.StubOutWithMock(drv, '_delete_snapshot')
        mox.StubOutWithMock(drv, '_read_info_file')
        mox.StubOutWithMock(image_utils, 'convert_image')
        mox.StubOutWithMock(drv, '_copy_volume_from_snapshot')

        volume_file = 'volume-%s' % self.VOLUME_UUID
        volume_path = '%s/%s/%s' % (self.TEST_MNT_POINT_BASE,
                                    drv._get_hash_str(self.TEST_EXPORT1),
                                    volume_file)

        volume = self._simple_volume()
        src_vref = self._simple_volume()
        src_vref['id'] = '375e32b2-804a-49f2-b282-85d1d5a5b9e1'
        src_vref['name'] = 'volume-%s' % src_vref['id']
        volume_file = 'volume-%s' % src_vref['id']
        volume_path = '%s/%s/%s' % (self.TEST_MNT_POINT_BASE,
                                    drv._get_hash_str(self.TEST_EXPORT1),
                                    volume_file)
        src_info_path = '%s.info' % volume_path
        volume_ref = {'id': volume['id'],
                      'name': volume['name'],
                      'status': volume['status'],
                      'provider_location': volume['provider_location'],
                      'size': volume['size']}

        snap_ref = {'volume_name': src_vref['name'],
                    'name': 'clone-snap-%s' % src_vref['id'],
                    'size': src_vref['size'],
                    'volume_size': src_vref['size'],
                    'volume_id': src_vref['id'],
                    'id': 'tmp-snap-%s' % src_vref['id'],
                    'volume': src_vref}

        drv._create_snapshot(snap_ref)

        snap_info = {'active': volume_file,
                     snap_ref['id']: volume_path + '-clone'}

        drv._read_info_file(src_info_path).AndReturn(snap_info)

        drv._copy_volume_from_snapshot(snap_ref, volume_ref, volume['size'])

        drv._delete_snapshot(mox_lib.IgnoreArg())

        mox.ReplayAll()

        drv.create_cloned_volume(volume, src_vref)

    @mock.patch('cinder.openstack.common.fileutils.delete_if_exists')
    def test_delete_volume(self, mock_delete_if_exists):
        volume = self._simple_volume()
        volume_filename = 'volume-%s' % self.VOLUME_UUID
        volume_path = '%s/%s' % (self.TEST_MNT_POINT, volume_filename)
        info_file = volume_path + '.info'

        with contextlib.nested(
                mock.patch.object(self._driver, '_ensure_share_mounted'),
                mock.patch.object(self._driver, '_local_volume_dir'),
                mock.patch.object(self._driver, 'get_active_image_from_info'),
                mock.patch.object(self._driver, '_execute'),
                mock.patch.object(self._driver, '_local_path_volume_info')
        ) as (mock_ensure_share_mounted, mock_local_volume_dir,
              mock_active_image_from_info, mock_execute,
              mock_local_path_volume_info):
            mock_local_volume_dir.return_value = self.TEST_MNT_POINT
            mock_active_image_from_info.return_value = volume_filename
            mock_local_path_volume_info.return_value = info_file

            self._driver.delete_volume(volume)

            mock_ensure_share_mounted.assert_called_once_with(
                volume['provider_location'])
            mock_local_volume_dir.assert_called_once_with(volume)
            mock_active_image_from_info.assert_called_once_with(volume)
            mock_execute.assert_called_once_with('rm', '-f', volume_path,
                                                 run_as_root=True)
            mock_local_path_volume_info.assert_called_once_with(volume)
            mock_delete_if_exists.assert_called_once_with(info_file)

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

    def test_create_snapshot(self):
        (mox, drv) = self._mox, self._driver

        self.stub_out_not_replaying(drv, '_ensure_share_mounted')
        mox.StubOutWithMock(drv, '_create_qcow2_snap_file')
        mox.StubOutWithMock(drv, '_read_info_file')
        mox.StubOutWithMock(drv, '_write_info_file')

        volume = self._simple_volume()
        snap_ref = {'name': 'test snap',
                    'volume_id': self.VOLUME_UUID,
                    'volume': volume,
                    'id': self.SNAP_UUID}

        mox.StubOutWithMock(drv, '_execute')

        vol_filename = 'volume-%s' % self.VOLUME_UUID
        snap_filename = '%s.%s' % (vol_filename, self.SNAP_UUID)

        hashed = drv._get_hash_str(self.TEST_EXPORT1)
        vol_path = '%s/%s/%s' % (self.TEST_MNT_POINT_BASE,
                                 hashed,
                                 vol_filename)
        snap_path = '%s.%s' % (vol_path, self.SNAP_UUID)
        info_path = '%s%s' % (vol_path, '.info')

        info_dict = {'active': vol_filename}
        drv._read_info_file(info_path, empty_if_missing=True).\
            AndReturn(info_dict)

        drv._create_qcow2_snap_file(snap_ref, vol_filename, snap_path)

        qemu_img_info_output = ("""image: volume-%s
        file format: raw
        virtual size: 1.0G (1073741824 bytes)
        disk size: 152K
        """ % self.VOLUME_UUID, '')

        drv._read_info_file(info_path, empty_if_missing=True).\
            AndReturn(info_dict)

        # SNAP_UUID_2 has been removed from dict.
        info_file_dict = {'active': 'volume-%s.%s' %
                          (self.VOLUME_UUID, self.SNAP_UUID),
                          self.SNAP_UUID: 'volume-%s.%s' %
                          (self.VOLUME_UUID, self.SNAP_UUID)}

        drv._write_info_file(info_path, info_file_dict)

        mox.ReplayAll()

        drv.create_snapshot(snap_ref)

        mox.VerifyAll()

    def test_delete_snapshot_bottom(self):
        """Multiple snapshots exist.

           In this test, path (volume-<uuid>) is backed by
            snap_path (volume-<uuid>.<snap_uuid>) which is backed by
            snap_path_2 (volume-<uuid>.<snap_uuid_2>).

           Delete the snapshot identified by SNAP_UUID_2.

           Chain goes from
                               (SNAP_UUID)      (SNAP_UUID_2)
             volume-abc -> volume-abc.baca -> volume-abc.bebe
           to
                               (SNAP_UUID)
             volume-abc -> volume-abc.baca
        """
        (mox, drv) = self._mox, self._driver

        hashed = drv._get_hash_str(self.TEST_EXPORT1)
        volume_dir = os.path.join(self.TEST_MNT_POINT_BASE, hashed)
        volume_path = '%s/%s/volume-%s' % (self.TEST_MNT_POINT_BASE,
                                           hashed,
                                           self.VOLUME_UUID)
        volume_filename = 'volume-%s' % self.VOLUME_UUID

        snap_path = '%s.%s' % (volume_path, self.SNAP_UUID)
        snap_path_2 = '%s.%s' % (volume_path, self.SNAP_UUID_2)
        snap_file = '%s.%s' % (volume_filename, self.SNAP_UUID)
        snap_file_2 = '%s.%s' % (volume_filename, self.SNAP_UUID_2)
        info_path = '%s%s' % (volume_path, '.info')

        qemu_img_info_output = """image: volume-%s.%s
        file format: qcow2
        virtual size: 1.0G (1073741824 bytes)
        disk size: 173K
        backing file: %s
        """ % (self.VOLUME_UUID, self.SNAP_UUID, volume_filename)

        mox.StubOutWithMock(drv, '_execute')
        mox.StubOutWithMock(drv, '_read_file')
        mox.StubOutWithMock(drv, '_read_info_file')
        mox.StubOutWithMock(drv, '_get_backing_chain_for_path')
        mox.StubOutWithMock(drv, '_get_matching_backing_file')
        mox.StubOutWithMock(drv, '_write_info_file')
        mox.StubOutWithMock(drv, '_ensure_share_writable')
        mox.StubOutWithMock(image_utils, 'qemu_img_info')

        drv._ensure_share_writable(volume_dir)

        img_info = imageutils.QemuImgInfo(qemu_img_info_output)
        image_utils.qemu_img_info(snap_path_2).AndReturn(img_info)

        info_file_dict = {'active': snap_file_2,
                          self.SNAP_UUID_2: snap_file_2,
                          self.SNAP_UUID: snap_file}

        snap_ref = {'name': 'test snap',
                    'volume_id': self.VOLUME_UUID,
                    'volume': self._simple_volume(),
                    'id': self.SNAP_UUID_2}

        snap_path_2_chain = [{self.SNAP_UUID_2: snap_file_2},
                             {self.SNAP_UUID: snap_file},
                             {'active': snap_file_2}]

        snap_path_chain = [{self.SNAP_UUID: snap_file},
                           {'active': snap_file}]

        drv._read_info_file(info_path, empty_if_missing=True).\
            AndReturn(info_file_dict)

        drv._execute('qemu-img', 'commit', snap_path_2, run_as_root=True)

        drv._execute('rm', '-f', snap_path_2, run_as_root=True)

        drv._read_info_file(info_path, empty_if_missing=True).\
            AndReturn(info_file_dict)

        drv._read_info_file(info_path).AndReturn(info_file_dict)

        drv._write_info_file(info_path, info_file_dict)

        mox.ReplayAll()

        drv.delete_snapshot(snap_ref)

        mox.VerifyAll()

    def test_delete_snapshot_middle(self):
        """Multiple snapshots exist.

           In this test, path (volume-<uuid>) is backed by
            snap_path (volume-<uuid>.<snap_uuid>) which is backed by
            snap_path_2 (volume-<uuid>.<snap_uuid_2>).

           Delete the snapshot identified with SNAP_UUID.

           Chain goes from
                               (SNAP_UUID)      (SNAP_UUID_2)
             volume-abc -> volume-abc.baca -> volume-abc.bebe
           to                (SNAP_UUID_2)
             volume-abc -> volume-abc.bebe
        """
        (mox, drv) = self._mox, self._driver

        volume = self._simple_volume()

        hashed = drv._get_hash_str(self.TEST_EXPORT1)
        volume_file = 'volume-%s' % self.VOLUME_UUID
        volume_dir = os.path.join(self.TEST_MNT_POINT_BASE, hashed)
        volume_path = '%s/%s/%s' % (self.TEST_MNT_POINT_BASE,
                                    hashed,
                                    volume_file)

        info_path = '%s%s' % (volume_path, '.info')
        snap_path = '%s.%s' % (volume_path, self.SNAP_UUID)
        snap_file = 'volume-%s.%s' % (self.VOLUME_UUID, self.SNAP_UUID)
        snap_path_2 = '%s.%s' % (volume_path, self.SNAP_UUID_2)
        snap_file_2 = 'volume-%s.%s' % (self.VOLUME_UUID, self.SNAP_UUID_2)

        qemu_img_info_output_snap_2 = """image: volume-%s.%s
        file format: qcow2
        virtual size: 1.0G (1073741824 bytes)
        disk size: 173K
        backing file: %s
        """ % (self.VOLUME_UUID, self.SNAP_UUID_2,
               'volume-%s.%s' % (self.VOLUME_UUID, self.SNAP_UUID_2))

        qemu_img_info_output_snap_1 = """image: volume-%s.%s
        file format: qcow2
        virtual size: 1.0G (1073741824 bytes)
        disk size: 122K
        backing file: %s
        """ % (self.VOLUME_UUID, self.SNAP_UUID,
               'volume-%s.%s' % (self.VOLUME_UUID, self.SNAP_UUID))

        qemu_img_info_output = """image: volume-%s
        file format: qcow2
        virtual size: 1.0G (1073741824 bytes)
        disk size: 175K
        """ % self.VOLUME_UUID

        mox.StubOutWithMock(drv, '_execute')
        mox.StubOutWithMock(drv, '_read_info_file')
        mox.StubOutWithMock(drv, '_write_info_file')
        mox.StubOutWithMock(drv, '_get_backing_chain_for_path')
        mox.StubOutWithMock(drv, 'get_active_image_from_info')
        mox.StubOutWithMock(drv, '_ensure_share_writable')
        mox.StubOutWithMock(image_utils, 'qemu_img_info')

        info_file_dict = {self.SNAP_UUID_2: 'volume-%s.%s' %
                          (self.VOLUME_UUID, self.SNAP_UUID_2),
                          self.SNAP_UUID: 'volume-%s.%s' %
                          (self.VOLUME_UUID, self.SNAP_UUID)}

        drv._ensure_share_writable(volume_dir)

        info_path = drv._local_path_volume(volume) + '.info'
        drv._read_info_file(info_path, empty_if_missing=True).\
            AndReturn(info_file_dict)

        img_info = imageutils.QemuImgInfo(qemu_img_info_output_snap_1)
        image_utils.qemu_img_info(snap_path).AndReturn(img_info)

        snap_ref = {'name': 'test snap',
                    'volume_id': self.VOLUME_UUID,
                    'volume': volume,
                    'id': self.SNAP_UUID}

        snap_path_chain = [{'filename': snap_file_2,
                            'backing-filename': snap_file},
                           {'filename': snap_file,
                            'backing-filename': volume_file}]

        drv.get_active_image_from_info(volume).AndReturn(snap_file_2)
        drv._get_backing_chain_for_path(volume, snap_path_2).\
            AndReturn(snap_path_chain)

        drv._read_info_file(info_path).AndReturn(info_file_dict)

        drv._execute('qemu-img', 'commit', snap_path_2, run_as_root=True)

        drv._execute('rm', '-f', snap_path_2, run_as_root=True)

        drv._read_info_file(info_path).AndReturn(info_file_dict)

        drv._write_info_file(info_path, info_file_dict)

        mox.ReplayAll()

        drv.delete_snapshot(snap_ref)

        mox.VerifyAll()

    def test_delete_snapshot_not_in_info(self):
        """Snapshot not in info file / info file doesn't exist.

        Snapshot creation failed so nothing is on-disk.  Driver
        should allow operation to succeed so the manager can
        remove the snapshot record.

        (Scenario: Snapshot object created in Cinder db but not
         on backing storage.)

        """
        (mox, drv) = self._mox, self._driver

        hashed = drv._get_hash_str(self.TEST_EXPORT1)
        volume_dir = os.path.join(self.TEST_MNT_POINT_BASE, hashed)
        volume_filename = 'volume-%s' % self.VOLUME_UUID
        volume_path = os.path.join(volume_dir, volume_filename)
        info_path = '%s%s' % (volume_path, '.info')

        mox.StubOutWithMock(drv, '_read_file')
        mox.StubOutWithMock(drv, '_read_info_file')
        mox.StubOutWithMock(drv, '_ensure_share_writable')

        snap_ref = {'name': 'test snap',
                    'volume_id': self.VOLUME_UUID,
                    'volume': self._simple_volume(),
                    'id': self.SNAP_UUID_2}

        drv._ensure_share_writable(volume_dir)

        drv._read_info_file(info_path, empty_if_missing=True).AndReturn({})

        mox.ReplayAll()

        drv.delete_snapshot(snap_ref)

        mox.VerifyAll()

    def test_read_info_file(self):
        (mox, drv) = self._mox, self._driver

        mox.StubOutWithMock(drv, '_read_file')
        hashed = drv._get_hash_str(self.TEST_EXPORT1)
        volume_path = '%s/%s/volume-%s' % (self.TEST_MNT_POINT_BASE,
                                           hashed,
                                           self.VOLUME_UUID)
        info_path = '%s%s' % (volume_path, '.info')

        drv._read_file(info_path).AndReturn('{"%(id)s": "volume-%(id)s"}' %
                                            {'id': self.VOLUME_UUID})

        mox.ReplayAll()

        volume = DumbVolume()
        volume['id'] = self.VOLUME_UUID
        volume['name'] = 'volume-%s' % self.VOLUME_UUID

        info = drv._read_info_file(info_path)

        self.assertEqual(info[self.VOLUME_UUID],
                         'volume-%s' % self.VOLUME_UUID)

        mox.VerifyAll()

    def test_extend_volume(self):
        (mox, drv) = self._mox, self._driver

        volume = self._simple_volume()

        volume_path = '%s/%s/volume-%s' % (self.TEST_MNT_POINT_BASE,
                                           drv._get_hash_str(
                                               self.TEST_EXPORT1),
                                           self.VOLUME_UUID)

        qemu_img_info_output = """image: volume-%s
        file format: qcow2
        virtual size: 1.0G (1073741824 bytes)
        disk size: 473K
        """ % self.VOLUME_UUID

        img_info = imageutils.QemuImgInfo(qemu_img_info_output)

        mox.StubOutWithMock(drv, '_execute')
        mox.StubOutWithMock(drv, 'get_active_image_from_info')
        mox.StubOutWithMock(image_utils, 'qemu_img_info')
        mox.StubOutWithMock(image_utils, 'resize_image')

        drv.get_active_image_from_info(volume).AndReturn(volume['name'])

        image_utils.qemu_img_info(volume_path).AndReturn(img_info)

        image_utils.resize_image(volume_path, 3)

        mox.ReplayAll()

        drv.extend_volume(volume, 3)

        mox.VerifyAll()

    def test_create_snapshot_online(self):
        (mox, drv) = self._mox, self._driver

        volume = self._simple_volume()
        volume['status'] = 'in-use'

        hashed = drv._get_hash_str(self.TEST_EXPORT1)
        volume_file = 'volume-%s' % self.VOLUME_UUID
        volume_path = '%s/%s/%s' % (self.TEST_MNT_POINT_BASE,
                                    hashed,
                                    volume_file)
        info_path = '%s.info' % volume_path

        ctxt = context.RequestContext('fake_user', 'fake_project')

        snap_ref = {'name': 'test snap (online)',
                    'volume_id': self.VOLUME_UUID,
                    'volume': volume,
                    'id': self.SNAP_UUID,
                    'context': ctxt,
                    'status': 'asdf',
                    'progress': 'asdf'}

        snap_path = '%s.%s' % (volume_path, self.SNAP_UUID)
        snap_file = '%s.%s' % (volume_file, self.SNAP_UUID)

        mox.StubOutWithMock(drv, '_execute')
        mox.StubOutWithMock(drv, '_create_qcow2_snap_file')
        mox.StubOutWithMock(db, 'snapshot_get')
        mox.StubOutWithMock(drv, '_write_info_file')
        mox.StubOutWithMock(drv, '_nova')

        drv._create_qcow2_snap_file(snap_ref, volume_file, snap_path)

        create_info = {'snapshot_id': snap_ref['id'],
                       'type': 'qcow2',
                       'new_file': snap_file}

        drv._nova.create_volume_snapshot(ctxt, self.VOLUME_UUID, create_info)

        snap_ref['status'] = 'creating'
        snap_ref['progress'] = '0%'
        db.snapshot_get(ctxt, self.SNAP_UUID).AndReturn(snap_ref)

        snap_ref['progress'] = '50%'
        db.snapshot_get(ctxt, self.SNAP_UUID).AndReturn(snap_ref)

        snap_ref['progress'] = '90%'
        db.snapshot_get(ctxt, self.SNAP_UUID).AndReturn(snap_ref)

        snap_info = {'active': snap_file,
                     self.SNAP_UUID: snap_file}

        drv._write_info_file(info_path, snap_info)

        mox.ReplayAll()

        drv.create_snapshot(snap_ref)

    def test_create_snapshot_online_novafailure(self):
        (mox, drv) = self._mox, self._driver

        volume = self._simple_volume()
        volume['status'] = 'in-use'

        hashed = drv._get_hash_str(self.TEST_EXPORT1)
        volume_file = 'volume-%s' % self.VOLUME_UUID
        volume_path = '%s/%s/%s' % (self.TEST_MNT_POINT_BASE,
                                    hashed,
                                    volume_file)
        info_path = '%s.info' % volume_path

        ctxt = context.RequestContext('fake_user', 'fake_project')

        snap_ref = {'name': 'test snap (online)',
                    'volume_id': self.VOLUME_UUID,
                    'volume': volume,
                    'id': self.SNAP_UUID,
                    'context': ctxt}

        snap_path = '%s.%s' % (volume_path, self.SNAP_UUID)
        snap_file = '%s.%s' % (volume_file, self.SNAP_UUID)

        mox.StubOutWithMock(drv, '_execute')
        mox.StubOutWithMock(drv, '_create_qcow2_snap_file')
        mox.StubOutWithMock(drv, '_nova')
        mox.StubOutWithMock(db, 'snapshot_get')
        mox.StubOutWithMock(drv, '_write_info_file')

        drv._create_qcow2_snap_file(snap_ref, volume_file, snap_path)

        create_info = {'snapshot_id': snap_ref['id'],
                       'type': 'qcow2',
                       'new_file': snap_file}

        drv._nova.create_volume_snapshot(ctxt, self.VOLUME_UUID, create_info)

        snap_ref['status'] = 'creating'
        snap_ref['progress'] = '0%'

        db.snapshot_get(ctxt, self.SNAP_UUID).AndReturn(snap_ref)

        snap_ref['progress'] = '50%'
        db.snapshot_get(ctxt, self.SNAP_UUID).AndReturn(snap_ref)

        snap_ref['progress'] = '99%'
        snap_ref['status'] = 'error'
        db.snapshot_get(ctxt, self.SNAP_UUID).AndReturn(snap_ref)

        snap_info = {'active': snap_file,
                     self.SNAP_UUID: snap_file}

        drv._write_info_file(info_path, snap_info)

        mox.ReplayAll()

        self.assertRaises(exception.GlusterfsException,
                          drv.create_snapshot,
                          snap_ref)

    def test_delete_snapshot_online_1(self):
        """Delete the newest snapshot, with only one snap present."""
        (mox, drv) = self._mox, self._driver

        volume = self._simple_volume()
        volume['status'] = 'in-use'

        ctxt = context.RequestContext('fake_user', 'fake_project')

        snap_ref = {'name': 'test snap to delete (online)',
                    'volume_id': self.VOLUME_UUID,
                    'volume': volume,
                    'id': self.SNAP_UUID,
                    'context': ctxt}

        hashed = drv._get_hash_str(self.TEST_EXPORT1)
        volume_file = 'volume-%s' % self.VOLUME_UUID
        volume_dir = os.path.join(self.TEST_MNT_POINT_BASE, hashed)
        volume_path = '%s/%s/%s' % (self.TEST_MNT_POINT_BASE,
                                    hashed,
                                    volume_file)
        info_path = '%s.info' % volume_path

        snap_path = '%s.%s' % (volume_path, self.SNAP_UUID)
        snap_file = '%s.%s' % (volume_file, self.SNAP_UUID)

        mox.StubOutWithMock(drv, '_execute')
        mox.StubOutWithMock(drv, '_nova')
        mox.StubOutWithMock(drv, '_read_info_file')
        mox.StubOutWithMock(drv, '_write_info_file')
        mox.StubOutWithMock(os.path, 'exists')
        mox.StubOutWithMock(db, 'snapshot_get')
        mox.StubOutWithMock(image_utils, 'qemu_img_info')
        mox.StubOutWithMock(drv, '_ensure_share_writable')

        snap_info = {'active': snap_file,
                     self.SNAP_UUID: snap_file}

        drv._ensure_share_writable(volume_dir)

        drv._read_info_file(info_path, empty_if_missing=True).\
            AndReturn(snap_info)

        os.path.exists(snap_path).AndReturn(True)

        qemu_img_info_output = """image: %s
        file format: qcow2
        virtual size: 1.0G (1073741824 bytes)
        disk size: 173K
        backing file: %s
        """ % (snap_file, volume_file)
        img_info = imageutils.QemuImgInfo(qemu_img_info_output)

        vol_qemu_img_info_output = """image: %s
        file format: raw
        virtual size: 1.0G (1073741824 bytes)
        disk size: 173K
        """ % volume_file
        volume_img_info = imageutils.QemuImgInfo(vol_qemu_img_info_output)

        image_utils.qemu_img_info(snap_path).AndReturn(img_info)

        image_utils.qemu_img_info(volume_path).AndReturn(volume_img_info)

        drv._read_info_file(info_path, empty_if_missing=True).\
            AndReturn(snap_info)

        delete_info = {
            'type': 'qcow2',
            'merge_target_file': None,
            'file_to_merge': None,
            'volume_id': self.VOLUME_UUID
        }

        drv._nova.delete_volume_snapshot(ctxt, self.SNAP_UUID, delete_info)

        drv._read_info_file(info_path).AndReturn(snap_info)

        drv._read_info_file(info_path).AndReturn(snap_info)

        snap_ref['status'] = 'deleting'
        snap_ref['progress'] = '0%'
        db.snapshot_get(ctxt, self.SNAP_UUID).AndReturn(snap_ref)

        snap_ref['progress'] = '50%'
        db.snapshot_get(ctxt, self.SNAP_UUID).AndReturn(snap_ref)

        snap_ref['progress'] = '90%'
        db.snapshot_get(ctxt, self.SNAP_UUID).AndReturn(snap_ref)

        db.snapshot_get(ctxt, self.SNAP_UUID).AndReturn(snap_ref)

        drv._write_info_file(info_path, snap_info)

        drv._execute('rm', '-f', volume_path, run_as_root=True)

        mox.ReplayAll()

        drv.delete_snapshot(snap_ref)

    def test_delete_snapshot_online_2(self):
        """Delete the middle of 3 snapshots."""
        (mox, drv) = self._mox, self._driver

        volume = self._simple_volume()
        volume['status'] = 'in-use'

        ctxt = context.RequestContext('fake_user', 'fake_project')

        snap_ref = {'name': 'test snap to delete (online)',
                    'volume_id': self.VOLUME_UUID,
                    'volume': volume,
                    'id': self.SNAP_UUID,
                    'context': ctxt}

        hashed = drv._get_hash_str(self.TEST_EXPORT1)
        volume_file = 'volume-%s' % self.VOLUME_UUID
        volume_dir = os.path.join(self.TEST_MNT_POINT_BASE, hashed)
        volume_path = '%s/%s/%s' % (self.TEST_MNT_POINT_BASE,
                                    hashed,
                                    volume_file)
        info_path = '%s.info' % volume_path

        snap_path = '%s.%s' % (volume_path, self.SNAP_UUID)
        snap_path_2 = '%s.%s' % (volume_path, self.SNAP_UUID_2)
        snap_file = '%s.%s' % (volume_file, self.SNAP_UUID)
        snap_file_2 = '%s.%s' % (volume_file, self.SNAP_UUID_2)

        mox.StubOutWithMock(drv, '_execute')
        mox.StubOutWithMock(drv, '_nova')
        mox.StubOutWithMock(drv, '_read_info_file')
        mox.StubOutWithMock(drv, '_write_info_file')
        mox.StubOutWithMock(os.path, 'exists')
        mox.StubOutWithMock(db, 'snapshot_get')
        mox.StubOutWithMock(image_utils, 'qemu_img_info')
        mox.StubOutWithMock(drv, '_ensure_share_writable')

        snap_info = {'active': snap_file_2,
                     self.SNAP_UUID: snap_file,
                     self.SNAP_UUID_2: snap_file_2}

        drv._ensure_share_writable(volume_dir)

        drv._read_info_file(info_path, empty_if_missing=True).\
            AndReturn(snap_info)

        os.path.exists(snap_path).AndReturn(True)

        qemu_img_info_output = """image: %s
        file format: qcow2
        virtual size: 1.0G (1073741824 bytes)
        disk size: 173K
        backing file: %s
        """ % (snap_file, volume_file)
        img_info = imageutils.QemuImgInfo(qemu_img_info_output)

        vol_qemu_img_info_output = """image: %s
        file format: raw
        virtual size: 1.0G (1073741824 bytes)
        disk size: 173K
        """ % volume_file
        volume_img_info = imageutils.QemuImgInfo(vol_qemu_img_info_output)

        image_utils.qemu_img_info(snap_path).AndReturn(img_info)

        image_utils.qemu_img_info(volume_path).AndReturn(volume_img_info)

        drv._read_info_file(info_path, empty_if_missing=True).\
            AndReturn(snap_info)

        delete_info = {'type': 'qcow2',
                       'merge_target_file': volume_file,
                       'file_to_merge': snap_file,
                       'volume_id': self.VOLUME_UUID}
        drv._nova.delete_volume_snapshot(ctxt, self.SNAP_UUID, delete_info)

        drv._read_info_file(info_path).AndReturn(snap_info)

        drv._read_info_file(info_path).AndReturn(snap_info)

        snap_ref['status'] = 'deleting'
        snap_ref['progress'] = '0%'
        db.snapshot_get(ctxt, self.SNAP_UUID).AndReturn(snap_ref)

        snap_ref['progress'] = '50%'
        db.snapshot_get(ctxt, self.SNAP_UUID).AndReturn(snap_ref)

        snap_ref['progress'] = '90%'
        db.snapshot_get(ctxt, self.SNAP_UUID).AndReturn(snap_ref)

        db.snapshot_get(ctxt, self.SNAP_UUID).AndReturn(snap_ref)

        drv._write_info_file(info_path, snap_info)

        drv._execute('rm', '-f', snap_path, run_as_root=True)

        mox.ReplayAll()

        drv.delete_snapshot(snap_ref)

    def test_delete_snapshot_online_novafailure(self):
        """Delete the newest snapshot."""
        (mox, drv) = self._mox, self._driver

        volume = self._simple_volume()
        volume['status'] = 'in-use'

        ctxt = context.RequestContext('fake_user', 'fake_project')

        snap_ref = {'name': 'test snap to delete (online)',
                    'volume_id': self.VOLUME_UUID,
                    'volume': volume,
                    'id': self.SNAP_UUID,
                    'context': ctxt}

        hashed = drv._get_hash_str(self.TEST_EXPORT1)
        volume_file = 'volume-%s' % self.VOLUME_UUID
        volume_path = '%s/%s/%s' % (self.TEST_MNT_POINT_BASE,
                                    hashed,
                                    volume_file)
        info_path = '%s.info' % volume_path

        snap_path = '%s.%s' % (volume_path, self.SNAP_UUID)
        snap_file = '%s.%s' % (volume_file, self.SNAP_UUID)

        mox.StubOutWithMock(drv, '_execute')
        mox.StubOutWithMock(drv, '_nova')
        mox.StubOutWithMock(drv, '_read_info_file')
        mox.StubOutWithMock(drv, '_write_info_file')
        mox.StubOutWithMock(os.path, 'exists')
        mox.StubOutWithMock(db, 'snapshot_get')
        mox.StubOutWithMock(image_utils, 'qemu_img_info')

        snap_info = {'active': snap_file,
                     self.SNAP_UUID: snap_file}

        drv._read_info_file(info_path, empty_if_missing=True).\
            AndReturn(snap_info)

        os.path.exists(snap_path).AndReturn(True)

        qemu_img_info_output = """image: %s
        file format: qcow2
        virtual size: 1.0G (1073741824 bytes)
        disk size: 173K
        backing file: %s
        """ % (snap_file, volume_file)
        img_info = imageutils.QemuImgInfo(qemu_img_info_output)

        image_utils.qemu_img_info(snap_path).AndReturn(img_info)

        drv._read_info_file(info_path, empty_if_missing=True).\
            AndReturn(snap_info)

        delete_info = {
            'type': 'qcow2',
            'merge_target_file': None,
            'file_to_merge': volume_file,
            'volume_id': self.VOLUME_UUID
        }

        drv._nova.delete_volume_snapshot(ctxt, self.SNAP_UUID, delete_info)

        drv._read_info_file(info_path).AndReturn(snap_info)

        drv._read_info_file(info_path).AndReturn(snap_info)

        snap_ref['status'] = 'deleting'
        snap_ref['progress'] = '0%'
        db.snapshot_get(ctxt, self.SNAP_UUID).AndReturn(snap_ref)

        snap_ref['progress'] = '50%'
        db.snapshot_get(ctxt, self.SNAP_UUID).AndReturn(snap_ref)

        snap_ref['status'] = 'error_deleting'
        snap_ref['progress'] = '90%'
        db.snapshot_get(ctxt, self.SNAP_UUID).AndReturn(snap_ref)

        db.snapshot_get(ctxt, self.SNAP_UUID).AndReturn(snap_ref)

        drv._write_info_file(info_path, snap_info)

        drv._execute('rm', '-f', volume_path, run_as_root=True)

        mox.ReplayAll()

        self.assertRaises(exception.GlusterfsException,
                          drv.delete_snapshot,
                          snap_ref)

    def test_get_backing_chain_for_path(self):
        (mox, drv) = self._mox, self._driver

        glusterfs.CONF.glusterfs_mount_point_base = self.TEST_MNT_POINT_BASE

        volume = self._simple_volume()
        vol_filename = volume['name']
        vol_filename_2 = volume['name'] + '.abcd'
        vol_filename_3 = volume['name'] + '.efef'
        hashed = drv._get_hash_str(self.TEST_EXPORT1)
        vol_dir = '%s/%s' % (self.TEST_MNT_POINT_BASE, hashed)
        vol_path = '%s/%s' % (vol_dir, vol_filename)
        vol_path_2 = '%s/%s' % (vol_dir, vol_filename_2)
        vol_path_3 = '%s/%s' % (vol_dir, vol_filename_3)

        mox.StubOutWithMock(drv, '_execute')
        mox.StubOutWithMock(drv, '_local_volume_dir')
        mox.StubOutWithMock(image_utils, 'qemu_img_info')

        qemu_img_output_base = """image: %(image_name)s
        file format: qcow2
        virtual size: 1.0G (1073741824 bytes)
        disk size: 173K
        """
        qemu_img_output = """image: %(image_name)s
        file format: qcow2
        virtual size: 1.0G (1073741824 bytes)
        disk size: 173K
        backing file: %(backing_file)s
        """

        qemu_img_output_1 = qemu_img_output_base % {'image_name': vol_filename}
        qemu_img_output_2 = qemu_img_output % {'image_name': vol_filename_2,
                                               'backing_file': vol_filename}
        qemu_img_output_3 = qemu_img_output % {'image_name': vol_filename_3,
                                               'backing_file': vol_filename_2}

        info_1 = imageutils.QemuImgInfo(qemu_img_output_1)
        info_2 = imageutils.QemuImgInfo(qemu_img_output_2)
        info_3 = imageutils.QemuImgInfo(qemu_img_output_3)

        drv._local_volume_dir(volume).AndReturn(vol_dir)
        image_utils.qemu_img_info(vol_path_3).\
            AndReturn(info_3)
        drv._local_volume_dir(volume).AndReturn(vol_dir)
        image_utils.qemu_img_info(vol_path_2).\
            AndReturn(info_2)
        drv._local_volume_dir(volume).AndReturn(vol_dir)
        image_utils.qemu_img_info(vol_path).\
            AndReturn(info_1)

        mox.ReplayAll()

        chain = drv._get_backing_chain_for_path(volume, vol_path_3)

        # Verify chain contains all expected data
        item_1 = drv._get_matching_backing_file(chain, vol_filename)
        self.assertEqual(item_1['filename'], vol_filename_2)
        chain.remove(item_1)
        item_2 = drv._get_matching_backing_file(chain, vol_filename_2)
        self.assertEqual(item_2['filename'], vol_filename_3)
        chain.remove(item_2)
        self.assertEqual(len(chain), 1)
        self.assertEqual(chain[0]['filename'], vol_filename)

    def test_copy_volume_from_snapshot(self):
        (mox, drv) = self._mox, self._driver

        mox.StubOutWithMock(image_utils, 'convert_image')
        mox.StubOutWithMock(drv, '_read_info_file')
        mox.StubOutWithMock(image_utils, 'qemu_img_info')
        mox.StubOutWithMock(drv, '_set_rw_permissions_for_all')

        dest_volume = self._simple_volume(
            'c1073000-0000-0000-0000-0000000c1073')
        src_volume = self._simple_volume()

        vol_dir = os.path.join(self.TEST_MNT_POINT_BASE,
                               drv._get_hash_str(self.TEST_EXPORT1))
        src_vol_path = os.path.join(vol_dir, src_volume['name'])
        dest_vol_path = os.path.join(vol_dir, dest_volume['name'])
        info_path = os.path.join(vol_dir, src_volume['name']) + '.info'

        snapshot = {'volume_name': src_volume['name'],
                    'name': 'clone-snap-%s' % src_volume['id'],
                    'size': src_volume['size'],
                    'volume_size': src_volume['size'],
                    'volume_id': src_volume['id'],
                    'id': 'tmp-snap-%s' % src_volume['id'],
                    'volume': src_volume}

        snap_file = dest_volume['name'] + '.' + snapshot['id']
        snap_path = os.path.join(vol_dir, snap_file)

        size = dest_volume['size']

        drv._read_info_file(info_path).AndReturn(
            {'active': snap_file,
             snapshot['id']: snap_file}
        )

        qemu_img_output = """image: %s
        file format: raw
        virtual size: 1.0G (1073741824 bytes)
        disk size: 173K
        backing file: %s
        """ % (snap_file, src_volume['name'])
        img_info = imageutils.QemuImgInfo(qemu_img_output)

        image_utils.qemu_img_info(snap_path).AndReturn(img_info)

        image_utils.convert_image(src_vol_path, dest_vol_path, 'raw')

        drv._set_rw_permissions_for_all(dest_vol_path)

        mox.ReplayAll()

        drv._copy_volume_from_snapshot(snapshot, dest_volume, size)

    def test_create_volume_from_snapshot(self):
        (mox, drv) = self._mox, self._driver

        volume = self._simple_volume('c1073000-0000-0000-0000-0000000c1073')
        src_volume = self._simple_volume()

        mox.StubOutWithMock(drv, '_create_snapshot')
        mox.StubOutWithMock(drv, '_copy_volume_from_snapshot')
        mox.StubOutWithMock(drv, '_delete_snapshot')

        snap_ref = {'volume_name': src_volume['name'],
                    'name': 'clone-snap-%s' % src_volume['id'],
                    'size': src_volume['size'],
                    'volume_size': src_volume['size'],
                    'volume_id': src_volume['id'],
                    'id': 'tmp-snap-%s' % src_volume['id'],
                    'volume': src_volume}

        volume_ref = {'id': volume['id'],
                      'size': volume['size'],
                      'status': volume['status'],
                      'provider_location': volume['provider_location'],
                      'name': 'volume-' + volume['id']}

        drv._create_snapshot(snap_ref)
        drv._copy_volume_from_snapshot(snap_ref,
                                       volume_ref,
                                       src_volume['size'])
        drv._delete_snapshot(snap_ref)

        mox.ReplayAll()

        drv.create_cloned_volume(volume, src_volume)

    def test_initialize_connection(self):
        (mox, drv) = self._mox, self._driver

        volume = self._simple_volume()
        vol_dir = os.path.join(self.TEST_MNT_POINT_BASE,
                               drv._get_hash_str(self.TEST_EXPORT1))
        vol_path = os.path.join(vol_dir, volume['name'])

        qemu_img_output = """image: %s
        file format: raw
        virtual size: 1.0G (1073741824 bytes)
        disk size: 173K
        """ % volume['name']
        img_info = imageutils.QemuImgInfo(qemu_img_output)

        mox.StubOutWithMock(drv, 'get_active_image_from_info')
        mox.StubOutWithMock(image_utils, 'qemu_img_info')

        drv.get_active_image_from_info(volume).AndReturn(volume['name'])
        image_utils.qemu_img_info(vol_path).AndReturn(img_info)

        mox.ReplayAll()

        conn_info = drv.initialize_connection(volume, None)

        self.assertEqual(conn_info['data']['format'], 'raw')
        self.assertEqual(conn_info['driver_volume_type'], 'glusterfs')
        self.assertEqual(conn_info['data']['name'], volume['name'])
        self.assertEqual(conn_info['mount_point_base'],
                         self.TEST_MNT_POINT_BASE)

    def test_get_mount_point_base(self):
        (mox, drv) = self._mox, self._driver

        self.assertEqual(drv._get_mount_point_base(),
                         self.TEST_MNT_POINT_BASE)

    def test_backup_volume(self):
        """Backup a volume with no snapshots."""

        (mox, drv) = self._mox, self._driver

        mox.StubOutWithMock(drv, '_qemu_img_info')
        mox.StubOutWithMock(drv.db, 'volume_get')
        mox.StubOutWithMock(base_driver.VolumeDriver, 'backup_volume')
        mox.StubOutWithMock(drv, '_read_info_file')
        mox.StubOutWithMock(drv, 'get_active_image_from_info')

        ctxt = context.RequestContext('fake_user', 'fake_project')
        volume = self._simple_volume()
        backup = {'volume_id': volume['id']}

        drv._read_info_file(IgnoreArg(), empty_if_missing=True).AndReturn({})
        drv.get_active_image_from_info(IgnoreArg()).AndReturn('/some/path')

        info = imageutils.QemuImgInfo()
        info.file_format = 'raw'

        drv.db.volume_get(ctxt, volume['id']).AndReturn(volume)
        drv._qemu_img_info(IgnoreArg(), IgnoreArg()).AndReturn(info)

        base_driver.VolumeDriver.backup_volume(IgnoreArg(),
                                               IgnoreArg(),
                                               IgnoreArg())

        mox.ReplayAll()

        drv.backup_volume(ctxt, backup, IgnoreArg())

    def test_backup_volume_previous_snap(self):
        """Backup a volume that previously had a snapshot.

           Snapshot was deleted, snap_info is different from above.
        """

        (mox, drv) = self._mox, self._driver

        mox.StubOutWithMock(drv, '_qemu_img_info')
        mox.StubOutWithMock(drv.db, 'volume_get')
        mox.StubOutWithMock(drv, '_read_info_file')
        mox.StubOutWithMock(drv, 'get_active_image_from_info')
        mox.StubOutWithMock(base_driver.VolumeDriver, 'backup_volume')

        ctxt = context.RequestContext('fake_user', 'fake_project')
        volume = self._simple_volume()
        backup = {'volume_id': volume['id']}

        drv._read_info_file(IgnoreArg(), empty_if_missing=True).AndReturn(
            {'active': 'file2'})
        drv.get_active_image_from_info(IgnoreArg()).AndReturn('/some/file2')

        info = imageutils.QemuImgInfo()
        info.file_format = 'raw'

        drv.db.volume_get(ctxt, volume['id']).AndReturn(volume)
        drv._qemu_img_info(IgnoreArg(), IgnoreArg()).AndReturn(info)

        base_driver.VolumeDriver.backup_volume(IgnoreArg(),
                                               IgnoreArg(),
                                               IgnoreArg())

        mox.ReplayAll()

        drv.backup_volume(ctxt, backup, IgnoreArg())

    def test_backup_snap_failure_1(self):
        """Backup fails if snapshot exists (database)."""

        (mox, drv) = self._mox, self._driver
        mox.StubOutWithMock(drv.db, 'snapshot_get_all_for_volume')
        mox.StubOutWithMock(base_driver.VolumeDriver, 'backup_volume')

        ctxt = context.RequestContext('fake_user', 'fake_project')
        volume = self._simple_volume()
        backup = {'volume_id': volume['id']}

        drv.db.snapshot_get_all_for_volume(ctxt, volume['id']).AndReturn(
            [{'snap1': 'a'}, {'snap2': 'b'}])

        base_driver.VolumeDriver.backup_volume(IgnoreArg(),
                                               IgnoreArg(),
                                               IgnoreArg())

        mox.ReplayAll()

        self.assertRaises(exception.InvalidVolume,
                          drv.backup_volume,
                          ctxt, backup, IgnoreArg())

    def test_backup_snap_failure_2(self):
        """Backup fails if snapshot exists (on-disk)."""

        (mox, drv) = self._mox, self._driver
        mox.StubOutWithMock(drv, '_read_info_file')
        mox.StubOutWithMock(drv.db, 'volume_get')
        mox.StubOutWithMock(drv, 'get_active_image_from_info')
        mox.StubOutWithMock(drv, '_qemu_img_info')
        mox.StubOutWithMock(base_driver.VolumeDriver, 'backup_volume')

        ctxt = context.RequestContext('fake_user', 'fake_project')
        volume = self._simple_volume()
        backup = {'volume_id': volume['id']}

        drv.db.volume_get(ctxt, volume['id']).AndReturn(volume)

        drv._read_info_file(IgnoreArg(), empty_if_missing=True).AndReturn(
            {'id1': 'file1',
             'id2': 'file2',
             'active': 'file2'})

        drv.get_active_image_from_info(IgnoreArg()).\
            AndReturn('/some/path/file2')

        info = imageutils.QemuImgInfo()
        info.file_format = 'raw'
        info.backing_file = 'file1'

        drv._qemu_img_info(IgnoreArg(), IgnoreArg()).AndReturn(info)

        base_driver.VolumeDriver.backup_volume(IgnoreArg(),
                                               IgnoreArg(),
                                               IgnoreArg())

        mox.ReplayAll()

        self.assertRaises(exception.InvalidVolume,
                          drv.backup_volume,
                          ctxt, backup, IgnoreArg())

    def test_backup_failure_unsupported_format(self):
        """Attempt to backup a volume with a qcow2 base."""

        (mox, drv) = self._mox, self._driver

        mox.StubOutWithMock(drv, '_qemu_img_info')
        mox.StubOutWithMock(drv.db, 'volume_get')
        mox.StubOutWithMock(base_driver.VolumeDriver, 'backup_volume')
        mox.StubOutWithMock(drv, '_read_info_file')
        mox.StubOutWithMock(drv, 'get_active_image_from_info')

        ctxt = context.RequestContext('fake_user', 'fake_project')
        volume = self._simple_volume()
        backup = {'volume_id': volume['id']}

        drv._read_info_file(IgnoreArg(), empty_if_missing=True).AndReturn({})
        drv.get_active_image_from_info(IgnoreArg()).AndReturn('/some/path')

        info = imageutils.QemuImgInfo()
        info.file_format = 'qcow2'

        drv.db.volume_get(ctxt, volume['id']).AndReturn(volume)
        drv._qemu_img_info(IgnoreArg(), IgnoreArg()).AndReturn(info)

        base_driver.VolumeDriver.backup_volume(IgnoreArg(),
                                               IgnoreArg(),
                                               IgnoreArg())

        mox.ReplayAll()

        self.assertRaises(exception.InvalidVolume,
                          drv.backup_volume,
                          ctxt, backup, IgnoreArg())
