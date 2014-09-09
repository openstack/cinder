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
import os
import tempfile
import time
import traceback

import mock
import mox as mox_lib
from mox import IgnoreArg
from mox import IsA
from mox import stubout
from oslo.config import cfg

from cinder import brick
from cinder import compute
from cinder import context
from cinder import db
from cinder import exception
from cinder.i18n import _
from cinder.image import image_utils
from cinder.openstack.common import imageutils
from cinder.openstack.common import processutils as putils
from cinder.openstack.common import units
from cinder import test
from cinder import utils
from cinder.volume import configuration as conf
from cinder.volume import driver as base_driver
from cinder.volume.drivers import glusterfs


CONF = cfg.CONF


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
    TEST_TMP_FILE = '/tmp/tempfile'
    VOLUME_UUID = 'abcdefab-cdef-abcd-efab-cdefabcdefab'
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
        self._configuration.glusterfs_sparsed_volumes = True
        self._configuration.glusterfs_qcow2_volumes = False

        self.stubs = stubout.StubOutForTesting()
        self._driver =\
            glusterfs.GlusterfsDriver(configuration=self._configuration,
                                      db=FakeDb())
        self._driver.shares = {}
        compute.API = mock.MagicMock()
        self.addCleanup(self._mox.UnsetStubs)

    def stub_out_not_replaying(self, obj, attr_name):
        attr_to_replace = getattr(obj, attr_name)
        stub = mox_lib.MockObject(attr_to_replace)
        self.stubs.Set(obj, attr_name, stub)

    def assertRaisesAndMessageMatches(
            self, excClass, msg, callableObj, *args, **kwargs):
        """Ensure that 'excClass' was raised and its message contains 'msg'."""

        caught = False
        try:
            callableObj(*args, **kwargs)
        except Exception as exc:
            caught = True
            self.assertEqual(excClass, type(exc),
                             'Wrong exception caught: %s Stacktrace: %s' %
                             (exc, traceback.print_exc()))
            self.assertIn(msg, str(exc))

        if not caught:
            self.fail('Expected raised exception but nothing caught.')

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

        mox.VerifyAll()

    def test_local_path(self):
        """local_path common use case."""
        CONF.set_override("glusterfs_mount_point_base",
                          self.TEST_MNT_POINT_BASE)
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

        CONF.set_override("glusterfs_mount_point_base",
                          self.TEST_MNT_POINT_BASE)

        brick.remotefs.remotefs.RemoteFsClient.\
            get_mount_point(self.TEST_EXPORT1).AndReturn(hashed_path)

        mox.ReplayAll()

        drv._get_mount_point_for_share(self.TEST_EXPORT1)

        mox.VerifyAll()

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

        drv.configuration.glusterfs_shares_config = None

        self.assertRaisesAndMessageMatches(exception.GlusterfsException,
                                           'no Gluster config file configured',
                                           drv.do_setup,
                                           IsA(context.RequestContext))

    def test_setup_should_throw_exception_if_client_is_not_installed(self):
        """do_setup should throw exception if client is not installed."""
        mox = self._mox
        drv = self._driver

        CONF.set_override("glusterfs_shares_config",
                          self.TEST_SHARES_CONFIG_FILE)

        mox.StubOutWithMock(os.path, 'exists')
        os.path.exists(self.TEST_SHARES_CONFIG_FILE).AndReturn(True)
        mox.StubOutWithMock(drv, '_execute')
        drv._execute('mount.glusterfs', check_exit_code=False).\
            AndRaise(OSError(errno.ENOENT, 'No such file or directory'))

        mox.ReplayAll()

        self.assertRaisesAndMessageMatches(exception.GlusterfsException,
                                           'mount.glusterfs is not installed',
                                           drv.do_setup,
                                           IsA(context.RequestContext))

        mox.VerifyAll()

    def _fake_load_shares_config(self, conf):
        self._driver.shares = {'127.7.7.7:/gluster1': None}

    def _fake_NamedTemporaryFile(self, prefix=None, dir=None):
        raise OSError('Permission denied!')

    def test_setup_set_share_permissions(self):
        mox = self._mox
        drv = self._driver

        CONF.set_override("glusterfs_shares_config",
                          self.TEST_SHARES_CONFIG_FILE)

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

        drv._execute('umount', '/mnt/test/8f0473c9ad824b8b6a27264b9cacb005',
                     run_as_root=True)

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
            AndReturn((2 * units.Gi, 5 * units.Gi))
        drv._get_available_capacity(self.TEST_EXPORT2).\
            AndReturn((3 * units.Gi, 10 * units.Gi))

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
            AndReturn((0, 5 * units.Gi))
        drv._get_available_capacity(self.TEST_EXPORT2).\
            AndReturn((0, 10 * units.Gi))

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

        CONF.set_override('glusterfs_sparsed_volumes', True)

        mox.StubOutWithMock(drv, '_create_sparsed_file')
        mox.StubOutWithMock(drv, '_set_rw_permissions_for_all')

        drv._create_sparsed_file(IgnoreArg(), IgnoreArg())
        drv._set_rw_permissions_for_all(IgnoreArg())

        mox.ReplayAll()

        drv._do_create_volume(volume)

        mox.VerifyAll()

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
                     str(volume['size'] * units.Gi),
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

        volume = self._simple_volume()
        src_vref = self._simple_volume()
        src_vref['id'] = '375e32b2-804a-49f2-b282-85d1d5a5b9e1'
        src_vref['name'] = 'volume-%s' % src_vref['id']
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

        drv._copy_volume_from_snapshot(snap_ref, volume_ref, volume['size'])

        drv._delete_snapshot(mox_lib.IgnoreArg())

        mox.ReplayAll()

        drv.create_cloned_volume(volume, src_vref)

        mox.VerifyAll()

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
                mock.patch.object(self._driver, '_local_path_volume'),
                mock.patch.object(self._driver, '_local_path_volume_info')
        ) as (mock_ensure_share_mounted, mock_local_volume_dir,
              mock_active_image_from_info, mock_execute,
              mock_local_path_volume, mock_local_path_volume_info):
            mock_local_volume_dir.return_value = self.TEST_MNT_POINT
            mock_active_image_from_info.return_value = volume_filename
            mock_local_path_volume.return_value = volume_path
            mock_local_path_volume_info.return_value = info_file

            self._driver.delete_volume(volume)

            mock_ensure_share_mounted.assert_called_once_with(
                volume['provider_location'])
            mock_local_volume_dir.assert_called_once_with(volume)
            mock_active_image_from_info.assert_called_once_with(volume)
            mock_execute.assert_called_once_with('rm', '-f', volume_path,
                                                 run_as_root=True)
            mock_local_path_volume_info.assert_called_once_with(volume)
            mock_local_path_volume.assert_called_once_with(volume)
            mock_delete_if_exists.assert_any_call(volume_path)
            mock_delete_if_exists.assert_any_call(info_file)

    def test_refresh_mounts(self):
        with contextlib.nested(
            mock.patch.object(self._driver, '_unmount_shares'),
            mock.patch.object(self._driver, '_ensure_shares_mounted')
        ) as (mock_unmount_shares, mock_ensure_shares_mounted):
            self._driver._refresh_mounts()

            self.assertTrue(mock_unmount_shares.called)
            self.assertTrue(mock_ensure_shares_mounted.called)

    def test_refresh_mounts_with_excp(self):
        with contextlib.nested(
            mock.patch.object(self._driver, '_unmount_shares'),
            mock.patch.object(self._driver, '_ensure_shares_mounted'),
            mock.patch.object(glusterfs, 'LOG')
        ) as (mock_unmount_shares, mock_ensure_shares_mounted,
              mock_logger):
            mock_stderr = _("umount: <mnt_path>: target is busy")
            mock_unmount_shares.side_effect = \
                putils.ProcessExecutionError(stderr=mock_stderr)

            self._driver._refresh_mounts()

            self.assertTrue(mock_unmount_shares.called)
            self.assertTrue(mock_logger.warn.called)
            self.assertTrue(mock_ensure_shares_mounted.called)

            mock_unmount_shares.reset_mock()
            mock_ensure_shares_mounted.reset_mock()
            mock_logger.reset_mock()
            mock_logger.warn.reset_mock()

            mock_stderr = _("umount: <mnt_path>: some other error")
            mock_unmount_shares.side_effect = \
                putils.ProcessExecutionError(stderr=mock_stderr)

            self.assertRaises(putils.ProcessExecutionError,
                              self._driver._refresh_mounts)

            self.assertTrue(mock_unmount_shares.called)
            self.assertFalse(mock_ensure_shares_mounted.called)

    def test_unmount_shares_with_excp(self):
        self._driver.shares = {'127.7.7.7:/gluster1': None}

        with contextlib.nested(
            mock.patch.object(self._driver, '_load_shares_config'),
            mock.patch.object(self._driver, '_do_umount'),
            mock.patch.object(glusterfs, 'LOG')
        ) as (mock_load_shares_config, mock_do_umount, mock_logger):
            mock_do_umount.side_effect = Exception()

            self._driver._unmount_shares()

            self.assertTrue(mock_do_umount.called)
            self.assertTrue(mock_logger.warning.called)
            self.assertFalse(mock_logger.debug.called)

    def test_unmount_shares_1share(self):
        self._driver.shares = {'127.7.7.7:/gluster1': None}

        with contextlib.nested(
            mock.patch.object(self._driver, '_load_shares_config'),
            mock.patch.object(self._driver, '_do_umount')
        ) as (mock_load_shares_config, mock_do_umount):
            self._driver._unmount_shares()

            self.assertTrue(mock_do_umount.called)
            mock_do_umount.assert_called_once_with(True,
                                                   '127.7.7.7:/gluster1')

    def test_unmount_shares_2share(self):
        self._driver.shares = {'127.7.7.7:/gluster1': None,
                               '127.7.7.8:/gluster2': None}

        with contextlib.nested(
            mock.patch.object(self._driver, '_load_shares_config'),
            mock.patch.object(self._driver, '_do_umount')
        ) as (mock_load_shares_config, mock_do_umount):
            self._driver._unmount_shares()

            mock_do_umount.assert_any_call(True,
                                           '127.7.7.7:/gluster1')
            mock_do_umount.assert_any_call(True,
                                           '127.7.7.8:/gluster2')

    def test_do_umount(self):
        test_share = '127.7.7.7:/gluster1'
        test_hashpath = '/hashed/mnt/path'

        with contextlib.nested(
            mock.patch.object(self._driver, '_get_mount_point_for_share'),
            mock.patch.object(putils, 'execute')
        ) as (mock_get_mntp_share, mock_execute):
            mock_get_mntp_share.return_value = test_hashpath

            self._driver._do_umount(True, test_share)

            self.assertTrue(mock_get_mntp_share.called)
            self.assertTrue(mock_execute.called)
            mock_get_mntp_share.assert_called_once_with(test_share)

            cmd = ['umount', test_hashpath]
            self.assertEqual(cmd[0], mock_execute.call_args[0][0])
            self.assertEqual(cmd[1], mock_execute.call_args[0][1])
            self.assertEqual(True,
                             mock_execute.call_args[1]['run_as_root'])

            mock_get_mntp_share.reset_mock()
            mock_get_mntp_share.return_value = test_hashpath
            mock_execute.reset_mock()

            self._driver._do_umount(False, test_share)

            self.assertTrue(mock_get_mntp_share.called)
            self.assertTrue(mock_execute.called)
            mock_get_mntp_share.assert_called_once_with(test_share)
            cmd = ['umount', test_hashpath]
            self.assertEqual(cmd[0], mock_execute.call_args[0][0])
            self.assertEqual(cmd[1], mock_execute.call_args[0][1])
            self.assertEqual(True,
                             mock_execute.call_args[1]['run_as_root'])

    def test_do_umount_with_excp1(self):
        test_share = '127.7.7.7:/gluster1'
        test_hashpath = '/hashed/mnt/path'

        with contextlib.nested(
            mock.patch.object(self._driver, '_get_mount_point_for_share'),
            mock.patch.object(putils, 'execute'),
            mock.patch.object(glusterfs, 'LOG')
        ) as (mock_get_mntp_share, mock_execute, mock_logger):
            mock_get_mntp_share.return_value = test_hashpath
            mock_execute.side_effect = putils.ProcessExecutionError
            self.assertRaises(putils.ProcessExecutionError,
                              self._driver._do_umount, False,
                              test_share)

            mock_logger.reset_mock()
            mock_logger.info.reset_mock()
            mock_logger.error.reset_mock()
            mock_execute.side_effect = putils.ProcessExecutionError
            try:
                self._driver._do_umount(False, test_share)
            except putils.ProcessExecutionError:
                self.assertFalse(mock_logger.info.called)
                self.assertTrue(mock_logger.error.called)
            except Exception as e:
                self.fail('Unexpected exception thrown:', e)
            else:
                self.fail('putils.ProcessExecutionError not thrown')

    def test_do_umount_with_excp2(self):
        test_share = '127.7.7.7:/gluster1'
        test_hashpath = '/hashed/mnt/path'

        with contextlib.nested(
            mock.patch.object(self._driver, '_get_mount_point_for_share'),
            mock.patch.object(putils, 'execute'),
            mock.patch.object(glusterfs, 'LOG')
        ) as (mock_get_mntp_share, mock_execute, mock_logger):
            mock_get_mntp_share.return_value = test_hashpath

            mock_stderr = _("umount: %s: not mounted") % test_hashpath
            mock_execute.side_effect = putils.ProcessExecutionError(
                stderr=mock_stderr)

            self._driver._do_umount(True, test_share)

            self.assertTrue(mock_logger.info.called)
            self.assertFalse(mock_logger.error.called)

            mock_logger.reset_mock()
            mock_logger.info.reset_mock()
            mock_logger.error.reset_mock()
            mock_stderr = _("umount: %s: target is busy") %\
                           (test_hashpath)
            mock_execute.side_effect = putils.ProcessExecutionError(
                stderr=mock_stderr)

            self.assertRaises(putils.ProcessExecutionError,
                              self._driver._do_umount, True,
                              test_share)

            mock_logger.reset_mock()
            mock_logger.info.reset_mock()
            mock_logger.error.reset_mock()
            mock_stderr = _('umount: %s: target is busy') %\
                           (test_hashpath)
            mock_execute.side_effect = putils.ProcessExecutionError(
                stderr=mock_stderr)

            try:
                self._driver._do_umount(True, test_share)
            except putils.ProcessExecutionError:
                self.assertFalse(mock_logger.info.called)
                self.assertTrue(mock_logger.error.called)
            except Exception as e:
                self.fail('Unexpected exception thrown:', e)
            else:
                self.fail('putils.ProcessExecutionError not thrown')

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
        mox.StubOutWithMock(drv, '_do_create_snapshot')
        mox.StubOutWithMock(db, 'snapshot_get')
        mox.StubOutWithMock(drv, '_nova')
        # Stub out the busy wait.
        self.stub_out_not_replaying(time, 'sleep')

        drv._do_create_snapshot(snap_ref, snap_file, snap_path)

        create_info = {'snapshot_id': snap_ref['id'],
                       'type': 'qcow2',
                       'new_file': snap_file}

        drv._nova.create_volume_snapshot(ctxt, self.VOLUME_UUID, create_info)

        snap_ref_progress = snap_ref.copy()
        snap_ref_progress['status'] = 'creating'

        snap_ref_progress_0p = snap_ref_progress.copy()
        snap_ref_progress_0p['progress'] = '0%'
        db.snapshot_get(ctxt, self.SNAP_UUID).AndReturn(snap_ref_progress_0p)

        snap_ref_progress_50p = snap_ref_progress.copy()
        snap_ref_progress_50p['progress'] = '50%'
        db.snapshot_get(ctxt, self.SNAP_UUID).AndReturn(snap_ref_progress_50p)

        snap_ref_progress_90p = snap_ref_progress.copy()
        snap_ref_progress_90p['progress'] = '90%'
        db.snapshot_get(ctxt, self.SNAP_UUID).AndReturn(snap_ref_progress_90p)

        mox.ReplayAll()

        drv._create_snapshot_online(snap_ref, snap_file, snap_path)

        mox.VerifyAll()

    def test_create_snapshot_online_novafailure(self):
        (mox, drv) = self._mox, self._driver

        volume = self._simple_volume()
        volume['status'] = 'in-use'

        hashed = drv._get_hash_str(self.TEST_EXPORT1)
        volume_file = 'volume-%s' % self.VOLUME_UUID
        volume_path = '%s/%s/%s' % (self.TEST_MNT_POINT_BASE,
                                    hashed,
                                    volume_file)

        ctxt = context.RequestContext('fake_user', 'fake_project')

        snap_ref = {'name': 'test snap (online)',
                    'volume_id': self.VOLUME_UUID,
                    'volume': volume,
                    'id': self.SNAP_UUID,
                    'context': ctxt}

        snap_path = '%s.%s' % (volume_path, self.SNAP_UUID)
        snap_file = '%s.%s' % (volume_file, self.SNAP_UUID)

        mox.StubOutWithMock(drv, '_execute')
        mox.StubOutWithMock(drv, '_do_create_snapshot')
        mox.StubOutWithMock(drv, '_nova')
        # Stub out the busy wait.
        self.stub_out_not_replaying(time, 'sleep')
        mox.StubOutWithMock(db, 'snapshot_get')

        drv._do_create_snapshot(snap_ref, snap_file, snap_path)

        create_info = {'snapshot_id': snap_ref['id'],
                       'type': 'qcow2',
                       'new_file': snap_file}

        drv._nova.create_volume_snapshot(ctxt, self.VOLUME_UUID, create_info)

        snap_ref_progress = snap_ref.copy()
        snap_ref_progress['status'] = 'creating'

        snap_ref_progress_0p = snap_ref_progress.copy()
        snap_ref_progress_0p['progress'] = '0%'
        db.snapshot_get(ctxt, self.SNAP_UUID).AndReturn(snap_ref_progress_0p)

        snap_ref_progress_50p = snap_ref_progress.copy()
        snap_ref_progress_50p['progress'] = '50%'
        db.snapshot_get(ctxt, self.SNAP_UUID).AndReturn(snap_ref_progress_50p)

        snap_ref_progress_99p = snap_ref_progress.copy()
        snap_ref_progress_99p['progress'] = '99%'
        snap_ref_progress_99p['status'] = 'error'
        db.snapshot_get(ctxt, self.SNAP_UUID).AndReturn(snap_ref_progress_99p)

        mox.ReplayAll()

        self.assertRaisesAndMessageMatches(
            exception.RemoteFSException,
            'Nova returned "error" status while creating snapshot.',
            drv._create_snapshot_online,
            snap_ref, snap_file, snap_path)

        mox.VerifyAll()

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
        # Stub out the busy wait.
        self.stub_out_not_replaying(time, 'sleep')
        mox.StubOutWithMock(drv, '_read_info_file')
        mox.StubOutWithMock(drv, '_write_info_file')
        mox.StubOutWithMock(db, 'snapshot_get')
        mox.StubOutWithMock(image_utils, 'qemu_img_info')
        mox.StubOutWithMock(drv, '_ensure_share_writable')

        snap_info = {'active': snap_file,
                     self.SNAP_UUID: snap_file}

        drv._ensure_share_writable(volume_dir)

        drv._read_info_file(info_path, empty_if_missing=True).\
            AndReturn(snap_info)

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

        snap_ref_progress = snap_ref.copy()
        snap_ref_progress['status'] = 'deleting'

        snap_ref_progress_0p = snap_ref_progress.copy()
        snap_ref_progress_0p['progress'] = '0%'
        db.snapshot_get(ctxt, self.SNAP_UUID).AndReturn(snap_ref_progress_0p)

        snap_ref_progress_50p = snap_ref_progress.copy()
        snap_ref_progress_50p['progress'] = '50%'
        db.snapshot_get(ctxt, self.SNAP_UUID).AndReturn(snap_ref_progress_50p)

        snap_ref_progress_90p = snap_ref_progress.copy()
        snap_ref_progress_90p['progress'] = '90%'
        db.snapshot_get(ctxt, self.SNAP_UUID).AndReturn(snap_ref_progress_90p)

        drv._write_info_file(info_path, snap_info)

        drv._execute('rm', '-f', volume_path, run_as_root=True)

        mox.ReplayAll()

        drv.delete_snapshot(snap_ref)

        mox.VerifyAll()

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
        snap_file = '%s.%s' % (volume_file, self.SNAP_UUID)
        snap_file_2 = '%s.%s' % (volume_file, self.SNAP_UUID_2)

        mox.StubOutWithMock(drv, '_execute')
        mox.StubOutWithMock(drv, '_nova')
        # Stub out the busy wait.
        self.stub_out_not_replaying(time, 'sleep')
        mox.StubOutWithMock(drv, '_read_info_file')
        mox.StubOutWithMock(drv, '_write_info_file')
        mox.StubOutWithMock(db, 'snapshot_get')
        mox.StubOutWithMock(image_utils, 'qemu_img_info')
        mox.StubOutWithMock(drv, '_ensure_share_writable')

        snap_info = {'active': snap_file_2,
                     self.SNAP_UUID: snap_file,
                     self.SNAP_UUID_2: snap_file_2}

        drv._ensure_share_writable(volume_dir)

        drv._read_info_file(info_path, empty_if_missing=True).\
            AndReturn(snap_info)

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

        snap_ref_progress = snap_ref.copy()
        snap_ref_progress['status'] = 'deleting'

        snap_ref_progress_0p = snap_ref_progress.copy()
        snap_ref_progress_0p['progress'] = '0%'
        db.snapshot_get(ctxt, self.SNAP_UUID).AndReturn(snap_ref_progress_0p)

        snap_ref_progress_50p = snap_ref_progress.copy()
        snap_ref_progress_50p['progress'] = '50%'
        db.snapshot_get(ctxt, self.SNAP_UUID).AndReturn(snap_ref_progress_50p)

        snap_ref_progress_90p = snap_ref_progress.copy()
        snap_ref_progress_90p['progress'] = '90%'
        db.snapshot_get(ctxt, self.SNAP_UUID).AndReturn(snap_ref_progress_90p)

        drv._write_info_file(info_path, snap_info)

        drv._execute('rm', '-f', snap_path, run_as_root=True)

        mox.ReplayAll()

        drv.delete_snapshot(snap_ref)

        mox.VerifyAll()

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
        volume_dir = os.path.join(self.TEST_MNT_POINT_BASE, hashed)
        volume_path = '%s/%s/%s' % (self.TEST_MNT_POINT_BASE,
                                    hashed,
                                    volume_file)
        info_path = '%s.info' % volume_path

        snap_path = '%s.%s' % (volume_path, self.SNAP_UUID)
        snap_file = '%s.%s' % (volume_file, self.SNAP_UUID)

        mox.StubOutWithMock(drv, '_execute')
        mox.StubOutWithMock(drv, '_nova')
        # Stub out the busy wait.
        self.stub_out_not_replaying(time, 'sleep')
        mox.StubOutWithMock(drv, '_read_info_file')
        mox.StubOutWithMock(db, 'snapshot_get')
        mox.StubOutWithMock(image_utils, 'qemu_img_info')
        mox.StubOutWithMock(drv, '_ensure_share_writable')

        snap_info = {'active': snap_file,
                     self.SNAP_UUID: snap_file}

        drv._ensure_share_writable(volume_dir)

        drv._read_info_file(info_path, empty_if_missing=True).\
            AndReturn(snap_info)

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

        snap_ref_progress = snap_ref.copy()
        snap_ref_progress['status'] = 'deleting'

        snap_ref_progress_0p = snap_ref_progress.copy()
        snap_ref_progress_0p['progress'] = '0%'
        db.snapshot_get(ctxt, self.SNAP_UUID).AndReturn(snap_ref_progress_0p)

        snap_ref_progress_50p = snap_ref_progress.copy()
        snap_ref_progress_50p['progress'] = '50%'
        db.snapshot_get(ctxt, self.SNAP_UUID).AndReturn(snap_ref_progress_50p)

        snap_ref_progress_90p = snap_ref_progress.copy()
        snap_ref_progress_90p['status'] = 'error_deleting'
        snap_ref_progress_90p['progress'] = '90%'
        db.snapshot_get(ctxt, self.SNAP_UUID).AndReturn(snap_ref_progress_90p)

        mox.ReplayAll()

        self.assertRaisesAndMessageMatches(exception.GlusterfsException,
                                           'Unable to delete snapshot',
                                           drv.delete_snapshot,
                                           snap_ref)

        mox.VerifyAll()

    def test_get_backing_chain_for_path(self):
        (mox, drv) = self._mox, self._driver

        CONF.set_override('glusterfs_mount_point_base',
                          self.TEST_MNT_POINT_BASE)

        volume = self._simple_volume()
        vol_filename = volume['name']
        vol_filename_2 = volume['name'] + '.asdfjkl'
        vol_filename_3 = volume['name'] + 'qwertyuiop'
        hashed = drv._get_hash_str(self.TEST_EXPORT1)
        vol_dir = '%s/%s' % (self.TEST_MNT_POINT_BASE, hashed)
        vol_path = '%s/%s' % (vol_dir, vol_filename)
        vol_path_2 = '%s/%s' % (vol_dir, vol_filename_2)
        vol_path_3 = '%s/%s' % (vol_dir, vol_filename_3)

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

        mox.VerifyAll()

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

        mox.VerifyAll()

    def test_create_volume_from_snapshot(self):
        (mox, drv) = self._mox, self._driver

        src_volume = self._simple_volume()
        snap_ref = {'volume_name': src_volume['name'],
                    'name': 'clone-snap-%s' % src_volume['id'],
                    'size': src_volume['size'],
                    'volume_size': src_volume['size'],
                    'volume_id': src_volume['id'],
                    'id': 'tmp-snap-%s' % src_volume['id'],
                    'volume': src_volume,
                    'status': 'available'}

        new_volume = DumbVolume()
        new_volume['size'] = snap_ref['size']

        mox.StubOutWithMock(drv, '_ensure_shares_mounted')
        mox.StubOutWithMock(drv, '_find_share')
        mox.StubOutWithMock(drv, '_do_create_volume')
        mox.StubOutWithMock(drv, '_copy_volume_from_snapshot')

        drv._ensure_shares_mounted()

        drv._find_share(new_volume['size']).AndReturn(self.TEST_EXPORT1)

        drv._do_create_volume(new_volume)
        drv._copy_volume_from_snapshot(snap_ref,
                                       new_volume,
                                       new_volume['size'])

        mox.ReplayAll()

        drv.create_volume_from_snapshot(new_volume, snap_ref)

        mox.VerifyAll()

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

        mox.VerifyAll()

        self.assertEqual(conn_info['data']['format'], 'raw')
        self.assertEqual(conn_info['driver_volume_type'], 'glusterfs')
        self.assertEqual(conn_info['data']['name'], volume['name'])
        self.assertEqual(conn_info['mount_point_base'],
                         self.TEST_MNT_POINT_BASE)

    def test_get_mount_point_base(self):
        drv = self._driver

        self.assertEqual(drv._get_mount_point_base(),
                         self.TEST_MNT_POINT_BASE)

    def test_backup_volume(self):
        """Backup a volume with no snapshots."""

        (mox, drv) = self._mox, self._driver

        mox.StubOutWithMock(drv.db, 'volume_get')
        mox.StubOutWithMock(drv, 'get_active_image_from_info')
        mox.StubOutWithMock(drv, '_qemu_img_info')
        mox.StubOutWithMock(base_driver.VolumeDriver, 'backup_volume')

        ctxt = context.RequestContext('fake_user', 'fake_project')
        volume = self._simple_volume()
        backup = {'volume_id': volume['id']}

        drv.db.volume_get(ctxt, volume['id']).AndReturn(volume)

        drv.get_active_image_from_info(IgnoreArg()).AndReturn('/some/path')

        info = imageutils.QemuImgInfo()
        info.file_format = 'raw'

        drv._qemu_img_info(IgnoreArg()).AndReturn(info)

        base_driver.VolumeDriver.backup_volume(IgnoreArg(),
                                               IgnoreArg(),
                                               IgnoreArg())

        mox.ReplayAll()

        drv.backup_volume(ctxt, backup, IgnoreArg())

        mox.VerifyAll()

    def test_backup_volume_previous_snap(self):
        """Backup a volume that previously had a snapshot.

           Snapshot was deleted, snap_info is different from above.
        """

        (mox, drv) = self._mox, self._driver

        mox.StubOutWithMock(drv.db, 'volume_get')
        mox.StubOutWithMock(drv, 'get_active_image_from_info')
        mox.StubOutWithMock(drv, '_qemu_img_info')
        mox.StubOutWithMock(base_driver.VolumeDriver, 'backup_volume')

        ctxt = context.RequestContext('fake_user', 'fake_project')
        volume = self._simple_volume()
        backup = {'volume_id': volume['id']}

        drv.db.volume_get(ctxt, volume['id']).AndReturn(volume)

        drv.get_active_image_from_info(IgnoreArg()).AndReturn('/some/file2')

        info = imageutils.QemuImgInfo()
        info.file_format = 'raw'

        drv._qemu_img_info(IgnoreArg()).AndReturn(info)

        base_driver.VolumeDriver.backup_volume(IgnoreArg(),
                                               IgnoreArg(),
                                               IgnoreArg())

        mox.ReplayAll()

        drv.backup_volume(ctxt, backup, IgnoreArg())

        mox.VerifyAll()

    def test_backup_snap_failure_1(self):
        """Backup fails if snapshot exists (database)."""

        (mox, drv) = self._mox, self._driver
        mox.StubOutWithMock(drv.db, 'snapshot_get_all_for_volume')

        ctxt = context.RequestContext('fake_user', 'fake_project')
        volume = self._simple_volume()
        backup = {'volume_id': volume['id']}

        drv.db.snapshot_get_all_for_volume(ctxt, volume['id']).AndReturn(
            [{'snap1': 'a'}, {'snap2': 'b'}])

        mox.ReplayAll()

        self.assertRaises(exception.InvalidVolume,
                          drv.backup_volume,
                          ctxt, backup, IgnoreArg())

        mox.VerifyAll()

    def test_backup_snap_failure_2(self):
        """Backup fails if snapshot exists (on-disk)."""

        (mox, drv) = self._mox, self._driver
        mox.StubOutWithMock(drv.db, 'volume_get')
        mox.StubOutWithMock(drv, 'get_active_image_from_info')
        mox.StubOutWithMock(drv, '_qemu_img_info')

        ctxt = context.RequestContext('fake_user', 'fake_project')
        volume = self._simple_volume()
        backup = {'volume_id': volume['id']}

        drv.db.volume_get(ctxt, volume['id']).AndReturn(volume)

        drv.get_active_image_from_info(IgnoreArg()).\
            AndReturn('/some/path/file2')

        info = imageutils.QemuImgInfo()
        info.file_format = 'raw'
        info.backing_file = 'file1'

        drv._qemu_img_info(IgnoreArg()).AndReturn(info)

        mox.ReplayAll()

        self.assertRaises(exception.InvalidVolume,
                          drv.backup_volume,
                          ctxt, backup, IgnoreArg())

        mox.VerifyAll()

    def test_backup_failure_unsupported_format(self):
        """Attempt to backup a volume with a qcow2 base."""

        (mox, drv) = self._mox, self._driver

        mox.StubOutWithMock(drv, '_qemu_img_info')
        mox.StubOutWithMock(drv.db, 'volume_get')
        mox.StubOutWithMock(drv, 'get_active_image_from_info')

        ctxt = context.RequestContext('fake_user', 'fake_project')
        volume = self._simple_volume()
        backup = {'volume_id': volume['id']}

        drv.get_active_image_from_info(IgnoreArg()).AndReturn('/some/path')

        info = imageutils.QemuImgInfo()
        info.file_format = 'qcow2'

        drv.db.volume_get(ctxt, volume['id']).AndReturn(volume)
        drv._qemu_img_info(IgnoreArg()).AndReturn(info)

        mox.ReplayAll()

        self.assertRaises(exception.InvalidVolume,
                          drv.backup_volume,
                          ctxt, backup, IgnoreArg())

        mox.VerifyAll()

    def test_copy_volume_to_image_raw_image(self):
        drv = self._driver

        volume = self._simple_volume()
        volume_path = '%s/%s' % (self.TEST_MNT_POINT, volume['name'])
        image_meta = {'id': '10958016-e196-42e3-9e7f-5d8927ae3099'}

        with contextlib.nested(
            mock.patch.object(drv, 'get_active_image_from_info'),
            mock.patch.object(drv, '_local_volume_dir'),
            mock.patch.object(image_utils, 'qemu_img_info'),
            mock.patch.object(image_utils, 'upload_volume'),
            mock.patch.object(image_utils, 'create_temporary_file')
        ) as (mock_get_active_image_from_info, mock_local_volume_dir,
              mock_qemu_img_info, mock_upload_volume,
              mock_create_temporary_file):
            mock_get_active_image_from_info.return_value = volume['name']

            mock_local_volume_dir.return_value = self.TEST_MNT_POINT

            mock_create_temporary_file.return_value = self.TEST_TMP_FILE

            qemu_img_output = """image: %s
            file format: raw
            virtual size: 1.0G (1073741824 bytes)
            disk size: 173K
            """ % volume['name']
            img_info = imageutils.QemuImgInfo(qemu_img_output)
            mock_qemu_img_info.return_value = img_info

            upload_path = volume_path

            drv.copy_volume_to_image(mock.ANY, volume, mock.ANY, image_meta)

            mock_get_active_image_from_info.assert_called_once_with(volume)
            mock_local_volume_dir.assert_called_once_with(volume)
            mock_qemu_img_info.assert_called_once_with(volume_path)
            mock_upload_volume.assert_called_once_with(
                mock.ANY, mock.ANY, mock.ANY, upload_path)
            mock_create_temporary_file.assert_once_called_with()

    def test_copy_volume_to_image_qcow2_image(self):
        """Upload a qcow2 image file which has to be converted to raw first."""
        drv = self._driver

        volume = self._simple_volume()
        volume_path = '%s/%s' % (self.TEST_MNT_POINT, volume['name'])
        image_meta = {'id': '10958016-e196-42e3-9e7f-5d8927ae3099'}

        with contextlib.nested(
            mock.patch.object(drv, 'get_active_image_from_info'),
            mock.patch.object(drv, '_local_volume_dir'),
            mock.patch.object(image_utils, 'qemu_img_info'),
            mock.patch.object(image_utils, 'convert_image'),
            mock.patch.object(image_utils, 'upload_volume'),
            mock.patch.object(image_utils, 'create_temporary_file')
        ) as (mock_get_active_image_from_info, mock_local_volume_dir,
              mock_qemu_img_info, mock_convert_image, mock_upload_volume,
              mock_create_temporary_file):
            mock_get_active_image_from_info.return_value = volume['name']

            mock_local_volume_dir.return_value = self.TEST_MNT_POINT

            mock_create_temporary_file.return_value = self.TEST_TMP_FILE

            qemu_img_output = """image: %s
            file format: qcow2
            virtual size: 1.0G (1073741824 bytes)
            disk size: 173K
            """ % volume['name']
            img_info = imageutils.QemuImgInfo(qemu_img_output)
            mock_qemu_img_info.return_value = img_info

            upload_path = self.TEST_TMP_FILE

            drv.copy_volume_to_image(mock.ANY, volume, mock.ANY, image_meta)

            mock_get_active_image_from_info.assert_called_once_with(volume)
            mock_local_volume_dir.assert_called_with(volume)
            mock_qemu_img_info.assert_called_once_with(volume_path)
            mock_convert_image.assert_called_once_with(
                volume_path, upload_path, 'raw')
            mock_upload_volume.assert_called_once_with(
                mock.ANY, mock.ANY, mock.ANY, upload_path)
            mock_create_temporary_file.assert_once_called_with()

    def test_copy_volume_to_image_snapshot_exists(self):
        """Upload an active snapshot which has to be converted to raw first."""
        drv = self._driver

        volume = self._simple_volume()
        volume_path = '%s/volume-%s' % (self.TEST_MNT_POINT, self.VOLUME_UUID)
        volume_filename = 'volume-%s' % self.VOLUME_UUID
        image_meta = {'id': '10958016-e196-42e3-9e7f-5d8927ae3099'}

        with contextlib.nested(
            mock.patch.object(drv, 'get_active_image_from_info'),
            mock.patch.object(drv, '_local_volume_dir'),
            mock.patch.object(image_utils, 'qemu_img_info'),
            mock.patch.object(image_utils, 'convert_image'),
            mock.patch.object(image_utils, 'upload_volume'),
            mock.patch.object(image_utils, 'create_temporary_file')
        ) as (mock_get_active_image_from_info, mock_local_volume_dir,
              mock_qemu_img_info, mock_convert_image, mock_upload_volume,
              mock_create_temporary_file):
            mock_get_active_image_from_info.return_value = volume['name']

            mock_local_volume_dir.return_value = self.TEST_MNT_POINT

            mock_create_temporary_file.return_value = self.TEST_TMP_FILE

            qemu_img_output = """image: volume-%s.%s
            file format: qcow2
            virtual size: 1.0G (1073741824 bytes)
            disk size: 173K
            backing file: %s
            """ % (self.VOLUME_UUID, self.SNAP_UUID, volume_filename)
            img_info = imageutils.QemuImgInfo(qemu_img_output)
            mock_qemu_img_info.return_value = img_info

            upload_path = self.TEST_TMP_FILE

            drv.copy_volume_to_image(mock.ANY, volume, mock.ANY, image_meta)

            mock_get_active_image_from_info.assert_called_once_with(volume)
            mock_local_volume_dir.assert_called_with(volume)
            mock_qemu_img_info.assert_called_once_with(volume_path)
            mock_convert_image.assert_called_once_with(
                volume_path, upload_path, 'raw')
            mock_upload_volume.assert_called_once_with(
                mock.ANY, mock.ANY, mock.ANY, upload_path)
            mock_create_temporary_file.assert_once_called_with()
