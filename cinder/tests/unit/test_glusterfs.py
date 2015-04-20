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
import tempfile
import time
import traceback

import mock
from oslo_concurrency import processutils as putils
from oslo_config import cfg
from oslo_utils import units

from cinder import brick
from cinder import compute
from cinder import context
from cinder import db
from cinder import exception
from cinder.i18n import _
from cinder.image import image_utils
from cinder.openstack.common import imageutils
from cinder import test
from cinder import utils
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
    VOLUME_NAME = 'volume-%s' % VOLUME_UUID
    SNAP_UUID = 'bacadaca-baca-daca-baca-dacadacadaca'
    SNAP_UUID_2 = 'bebedede-bebe-dede-bebe-dedebebedede'

    def setUp(self):
        super(GlusterFsDriverTestCase, self).setUp()
        self._configuration = mock.MagicMock()
        self._configuration.glusterfs_shares_config = \
            self.TEST_SHARES_CONFIG_FILE
        self._configuration.glusterfs_mount_point_base = \
            self.TEST_MNT_POINT_BASE
        self._configuration.glusterfs_sparsed_volumes = True
        self._configuration.glusterfs_qcow2_volumes = False
        self._configuration.nas_secure_file_permissions = 'false'
        self._configuration.nas_secure_file_operations = 'false'
        self._configuration.nas_ip = None
        self._configuration.nas_share_path = None
        self._configuration.nas_mount_options = None

        self._driver =\
            glusterfs.GlusterfsDriver(configuration=self._configuration,
                                      db=FakeDb())
        self._driver.shares = {}
        compute.API = mock.MagicMock()

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
        drv = self._driver

        rfsclient = brick.remotefs.remotefs.RemoteFsClient

        with mock.patch.object(rfsclient, 'set_execute') as mock_set_execute:
            def my_execute(*a, **k):
                pass

            drv.set_execute(my_execute)

            mock_set_execute.assert_called_once_with(my_execute)

    def test_local_path(self):
        """local_path common use case."""
        self.override_config("glusterfs_mount_point_base",
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
        drv = self._driver

        with mock.patch.object(drv, '_execute') as mock_execute:
            drv._mount_glusterfs(self.TEST_EXPORT1, self.TEST_MNT_POINT)

            expected = [mock.call('mkdir', '-p', '/mnt/glusterfs'),
                        mock.call('mount', '-t', 'glusterfs',
                                  'glusterfs-host1:/export',
                                  '/mnt/glusterfs', run_as_root=True)]
            self.assertEqual(expected, mock_execute.mock_calls)

    def test_mount_glusterfs_should_suppress_already_mounted_error(self):
        """_mount_glusterfs should suppress already mounted error if
           ensure=True
        """
        drv = self._driver

        with mock.patch.object(drv, '_execute') as mock_execute:
            execute_iterable = (None,
                                putils.ProcessExecutionError(
                                    stderr='is busy or already mounted'))
            mock_execute.side_effect = execute_iterable
            drv._mount_glusterfs(self.TEST_EXPORT1, self.TEST_MNT_POINT,
                                 ensure=True)

            expected = [mock.call('mkdir', '-p', '/mnt/glusterfs'),
                        mock.call('mount', '-t', 'glusterfs',
                                  'glusterfs-host1:/export',
                                  '/mnt/glusterfs', run_as_root=True)]
            self.assertEqual(expected, mock_execute.mock_calls)

    def test_mount_glusterfs_should_reraise_already_mounted_error(self):
        """_mount_glusterfs should not suppress already mounted error
           if ensure=False
        """
        drv = self._driver

        with mock.patch.object(drv, '_execute') as mock_execute:
            execute_iterable = (None,
                                putils.ProcessExecutionError(
                                    stderr='is busy or already mounted'))
            mock_execute.side_effect = execute_iterable

            self.assertRaises(putils.ProcessExecutionError,
                              drv._mount_glusterfs, self.TEST_EXPORT1,
                              self.TEST_MNT_POINT, ensure=False)

            expected = [mock.call('mkdir', '-p', '/mnt/glusterfs'),
                        mock.call('mount', '-t', 'glusterfs',
                                  'glusterfs-host1:/export',
                                  '/mnt/glusterfs', run_as_root=True)]
            self.assertEqual(expected, mock_execute.mock_calls)

    def test_mount_glusterfs_should_create_mountpoint_if_not_yet(self):
        """_mount_glusterfs should create mountpoint if it doesn't exist."""
        drv = self._driver

        with mock.patch.object(drv, '_execute') as mock_execute:

            drv._mount_glusterfs(self.TEST_EXPORT1, self.TEST_MNT_POINT)

            expected = [mock.call('mkdir', '-p', '/mnt/glusterfs'),
                        mock.call('mount', '-t', 'glusterfs',
                                  'glusterfs-host1:/export',
                                  '/mnt/glusterfs', run_as_root=True)]
            self.assertEqual(expected, mock_execute.mock_calls)

    def test_get_hash_str(self):
        """_get_hash_str should calculation correct value."""
        drv = self._driver

        self.assertEqual('ab03ab34eaca46a5fb81878f7e9b91fc',
                         drv._get_hash_str(self.TEST_EXPORT1))

    def test_get_mount_point_for_share(self):
        """_get_mount_point_for_share should call RemoteFsClient."""
        drv = self._driver
        hashed_path = '/mnt/test/abcdefabcdef'

        with mock.patch.object(brick.remotefs.remotefs.RemoteFsClient,
                               'get_mount_point') as mock_get_mount_point:
            mock_get_mount_point.return_value = hashed_path

            result = drv._get_mount_point_for_share(self.TEST_EXPORT1)

            self.assertEqual(hashed_path, result)

    def test_get_available_capacity_with_df(self):
        """_get_available_capacity should calculate correct value."""
        drv = self._driver

        df_total_size = 2620544
        df_avail = 1490560
        df_head = 'Filesystem 1K-blocks Used Available Use% Mounted on\n'
        df_data = 'glusterfs-host:/export %d 996864 %d 41%% /mnt' % \
                  (df_total_size, df_avail)
        df_output = df_head + df_data

        with mock.patch.object(drv, '_get_mount_point_for_share') as \
                mock_get_mount_point_for_share,\
                mock.patch.object(drv, '_execute') as mock_execute:
            mock_get_mount_point_for_share.\
                return_value = self.TEST_MNT_POINT
            mock_execute.return_value = (df_output, None)

            result = drv._get_available_capacity(self.TEST_EXPORT1)
            self.assertEqual((df_avail, df_total_size), result)

    def test_load_shares_config(self):
        drv = self._driver

        drv.configuration.glusterfs_shares_config = (
            self.TEST_SHARES_CONFIG_FILE)

        with mock.patch.object(drv, '_read_config_file') as \
                mock_read_config_file:
            config_data = []
            config_data.append(self.TEST_EXPORT1)
            config_data.append('#' + self.TEST_EXPORT2)
            config_data.append(self.TEST_EXPORT2 + ' ' +
                               self.TEST_EXPORT2_OPTIONS)
            config_data.append('broken:share_format')
            config_data.append('')
            mock_read_config_file.return_value = config_data

            drv._load_shares_config(drv.configuration.glusterfs_shares_config)

            self.assertIn(self.TEST_EXPORT1, drv.shares)
            self.assertIn(self.TEST_EXPORT2, drv.shares)
            self.assertEqual(2, len(drv.shares))

            self.assertEqual(self.TEST_EXPORT2_OPTIONS,
                             drv.shares[self.TEST_EXPORT2])

    def test_ensure_share_mounted(self):
        """_ensure_share_mounted simple use case."""
        drv = self._driver
        with mock.patch.object(utils, 'get_file_mode') as \
                mock_get_file_mode,\
                mock.patch.object(utils, 'get_file_gid') as mock_get_file_gid,\
                mock.patch.object(drv, '_execute') as mock_execute,\
                mock.patch.object(drv, '_ensure_share_writable') as \
                mock_ensure_share_writable,\
                mock.patch.object(drv, '_get_mount_point_for_share') as \
                mock_get_mount_point_for_share,\
                mock.patch.object(drv, '_mount_glusterfs') as \
                mock_mount_glusterfs:
            mock_get_mount_point_for_share.return_value = self.TEST_MNT_POINT
            mock_get_file_mode.return_value = 0o777
            mock_get_file_gid.return_value = 333333

            drv._ensure_share_mounted(self.TEST_EXPORT1)

            mock_get_file_mode.assert_called_once_with(self.TEST_MNT_POINT)
            mock_get_file_gid.assert_called_once_with(self.TEST_MNT_POINT)
            mock_ensure_share_writable.assert_called_once_with(
                self.TEST_MNT_POINT)
            self.assertTrue(mock_ensure_share_writable.called)
            self.assertTrue(mock_mount_glusterfs.called)
            self.assertTrue(mock_execute.called)

    def test_ensure_shares_mounted_should_save_mounting_successfully(self):
        """_ensure_shares_mounted should save share if mounted with success."""
        drv = self._driver

        with mock.patch.object(drv, '_read_config_file') as \
                mock_read_config_file,\
                mock.patch.object(drv, '_ensure_share_mounted') as \
                mock_ensure_share_mounted:
            config_data = []
            config_data.append(self.TEST_EXPORT1)
            mock_read_config_file.return_value = config_data

            drv._ensure_shares_mounted()

            mock_ensure_share_mounted.\
                assert_called_once_with(self.TEST_EXPORT1)
            self.assertEqual(1, len(drv._mounted_shares))
            self.assertEqual(self.TEST_EXPORT1, drv._mounted_shares[0])

    def test_ensure_shares_mounted_should_not_save_mounting_with_error(self):
        """_ensure_shares_mounted should not save share if failed to mount."""
        drv = self._driver

        with mock.patch.object(drv, '_read_config_file') as \
                mock_read_config_file,\
                mock.patch.object(drv, '_ensure_share_mounted') as \
                mock_ensure_share_mounted:
            config_data = []
            config_data.append(self.TEST_EXPORT1)
            mock_read_config_file.return_value = config_data
            mock_ensure_share_mounted.side_effect = Exception()

            drv._ensure_shares_mounted()

            self.assertEqual(0, len(drv._mounted_shares))

    def test_setup_should_throw_error_if_shares_config_not_configured(self):
        """do_setup should throw error if shares config is not configured."""
        drv = self._driver

        drv.configuration.glusterfs_shares_config = None

        self.assertRaisesAndMessageMatches(exception.GlusterfsException,
                                           'no Gluster config file configured',
                                           drv.do_setup,
                                           mock.MagicMock())

    @mock.patch.object(os.path, 'exists')
    def test_setup_should_throw_exception_if_client_is_not_installed(
            self, mock_exists):
        """do_setup should throw exception if client is not installed."""
        drv = self._driver

        self.override_config("glusterfs_shares_config",
                             self.TEST_SHARES_CONFIG_FILE)

        with mock.patch.object(drv, '_execute') as mock_execute:
            mock_exists.return_value = True
            mock_execute.side_effect = OSError(errno.ENOENT,
                                               'No such file or directory')
            self.assertRaisesAndMessageMatches(exception.GlusterfsException,
                                               'mount.glusterfs is not '
                                               'installed',
                                               drv.do_setup,
                                               mock.MagicMock())

    def _fake_load_shares_config(self, config):
        self._driver.shares = {'127.7.7.7:/gluster1': None}

    def _fake_NamedTemporaryFile(self, prefix=None, dir=None):
        raise OSError('Permission denied!')

    @mock.patch.object(os, 'getegid')
    @mock.patch.object(os.path, 'exists')
    def test_setup_set_share_permissions(self, mock_exists, mock_getegid):
        drv = self._driver

        self.override_config("glusterfs_shares_config",
                             self.TEST_SHARES_CONFIG_FILE)

        with mock.patch.object(drv, '_execute') as mock_execute,\
                mock.patch.object(utils, 'get_file_gid') as \
                mock_get_file_gid,\
                mock.patch.object(utils, 'get_file_mode') as \
                mock_get_file_mode,\
                mock.patch.object(tempfile, 'NamedTemporaryFile') as \
                mock_named_temp:
            drv._load_shares_config = self._fake_load_shares_config
            mock_named_temp.return_value = self._fake_NamedTemporaryFile
            mock_exists.return_value = True
            mock_get_file_gid.return_value = 33333
            mock_get_file_mode.return_value = 0o000
            mock_getegid.return_value = 888

            drv.do_setup(mock.MagicMock())

            expected = [
                mock.call('mount.glusterfs', check_exit_code=False),
                mock.call('umount',
                          '/mnt/test/8f0473c9ad824b8b6a27264b9cacb005',
                          run_as_root=True),
                mock.call('mkdir', '-p',
                          '/mnt/test/8f0473c9ad824b8b6a27264b9cacb005'),
                mock.call('mount', '-t', 'glusterfs', '127.7.7.7:/gluster1',
                          '/mnt/test/8f0473c9ad824b8b6a27264b9cacb005',
                          run_as_root=True),
                mock.call('chgrp', 888,
                          '/mnt/test/8f0473c9ad824b8b6a27264b9cacb005',
                          run_as_root=True),
                mock.call('chmod', 'g+w',
                          '/mnt/test/8f0473c9ad824b8b6a27264b9cacb005',
                          run_as_root=True)]
            self.assertEqual(expected, mock_execute.mock_calls)

    def test_find_share_should_throw_error_if_there_is_no_mounted_shares(self):
        """_find_share should throw error if there is no mounted shares."""
        drv = self._driver

        drv._mounted_shares = []

        self.assertRaises(exception.GlusterfsNoSharesMounted,
                          drv._find_share,
                          self.TEST_SIZE_IN_GB)

    def test_find_share(self):
        """_find_share simple use case."""
        drv = self._driver

        drv._mounted_shares = [self.TEST_EXPORT1, self.TEST_EXPORT2]

        with mock.patch.object(drv, '_get_available_capacity') as \
                mock_get_available_capacity:
            capacity = {self.TEST_EXPORT1: (2 * units.Gi, 5 * units.Gi),
                        self.TEST_EXPORT2: (3 * units.Gi, 10 * units.Gi)}

            def capacity_side_effect(*args, **kwargs):
                return capacity[args[0]]
            mock_get_available_capacity.side_effect = capacity_side_effect

            self.assertEqual(self.TEST_EXPORT2,
                             drv._find_share(self.TEST_SIZE_IN_GB))

    def test_find_share_should_throw_error_if_there_is_no_enough_place(self):
        """_find_share should throw error if there is no share to host vol."""
        drv = self._driver

        drv._mounted_shares = [self.TEST_EXPORT1, self.TEST_EXPORT2]

        with mock.patch.object(drv, '_get_available_capacity') as \
                mock_get_available_capacity:
            capacity = {self.TEST_EXPORT1: (0, 5 * units.Gi),
                        self.TEST_EXPORT2: (0, 10 * units.Gi)}

            def capacity_side_effect(*args, **kwargs):
                return capacity[args[0]]
            mock_get_available_capacity.side_effect = capacity_side_effect

            self.assertRaises(exception.GlusterfsNoSuitableShareFound,
                              drv._find_share,
                              self.TEST_SIZE_IN_GB)

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
        drv = self._driver
        volume = self._simple_volume()

        self.override_config('glusterfs_sparsed_volumes', True)

        with mock.patch.object(drv, '_create_sparsed_file') as \
                mock_create_sparsed_file,\
                mock.patch.object(drv, '_set_rw_permissions_for_all') as \
                mock_set_rw_permissions_for_all:
            drv._do_create_volume(volume)

            volume_path = drv.local_path(volume)
            volume_size = volume['size']
            mock_create_sparsed_file.assert_called_once_with(volume_path,
                                                             volume_size)
            mock_set_rw_permissions_for_all.\
                assert_called_once_with(volume_path)

    def test_create_nonsparsed_volume(self):
        drv = self._driver
        volume = self._simple_volume()

        old_value = self._configuration.glusterfs_sparsed_volumes
        self._configuration.glusterfs_sparsed_volumes = False

        with mock.patch.object(drv, '_create_regular_file') as \
                mock_create_regular_file,\
                mock.patch.object(drv, '_set_rw_permissions_for_all') as \
                mock_set_rw_permissions_for_all:
            drv._do_create_volume(volume)

            volume_path = drv.local_path(volume)
            volume_size = volume['size']
            mock_create_regular_file.assert_called_once_with(volume_path,
                                                             volume_size)
            mock_set_rw_permissions_for_all.\
                assert_called_once_with(volume_path)
        self._configuration.glusterfs_sparsed_volumes = old_value

    def test_create_qcow2_volume(self):
        drv = self._driver
        volume = self._simple_volume()

        old_value = self._configuration.glusterfs_qcow2_volumes
        self._configuration.glusterfs_qcow2_volumes = True

        with mock.patch.object(drv, '_execute') as mock_execute,\
                mock.patch.object(drv, '_set_rw_permissions_for_all') as \
                mock_set_rw_permissions_for_all:
            hashed = drv._get_hash_str(volume['provider_location'])
            path = '%s/%s/volume-%s' % (self.TEST_MNT_POINT_BASE,
                                        hashed,
                                        self.VOLUME_UUID)

            drv._do_create_volume(volume)

            volume_path = drv.local_path(volume)
            volume_size = volume['size']
            mock_execute.assert_called_once_with('qemu-img', 'create',
                                                 '-f', 'qcow2', '-o',
                                                 'preallocation=metadata',
                                                 path,
                                                 str(volume_size * units.Gi),
                                                 run_as_root=True)
            mock_set_rw_permissions_for_all.\
                assert_called_once_with(volume_path)
        self._configuration.glusterfs_qcow2_volumes = old_value

    def test_create_volume_should_ensure_glusterfs_mounted(self):
        """create_volume ensures shares provided in config are mounted."""
        drv = self._driver

        with mock.patch.object(drv, '_find_share') as mock_find_share,\
                mock.patch.object(drv, '_do_create_volume') as \
                mock_do_create_volume,\
                mock.patch.object(drv, '_ensure_shares_mounted') as \
                mock_ensure_shares_mounted:
            volume = DumbVolume()
            volume['size'] = self.TEST_SIZE_IN_GB
            drv.create_volume(volume)
            self.assertTrue(mock_ensure_shares_mounted.called)
            self.assertTrue(mock_do_create_volume.called)
            self.assertTrue(mock_find_share.called)

    def test_create_volume_should_return_provider_location(self):
        """create_volume should return provider_location with found share."""
        drv = self._driver

        with mock.patch.object(drv, '_find_share') as mock_find_share,\
                mock.patch.object(drv, '_do_create_volume') as \
                mock_do_create_volume,\
                mock.patch.object(drv, '_ensure_shares_mounted') as \
                mock_ensure_shares_mounted:
            mock_find_share.return_value = self.TEST_EXPORT1

            volume = DumbVolume()
            volume['size'] = self.TEST_SIZE_IN_GB
            result = drv.create_volume(volume)
            self.assertEqual(self.TEST_EXPORT1, result['provider_location'])
            self.assertTrue(mock_ensure_shares_mounted.called)
            self.assertTrue(mock_do_create_volume.called)

    def test_create_cloned_volume(self):
        drv = self._driver

        with mock.patch.object(drv, '_create_snapshot') as \
                mock_create_snapshot,\
                mock.patch.object(drv, '_delete_snapshot') as \
                mock_delete_snapshot,\
                mock.patch.object(drv, '_copy_volume_from_snapshot') as \
                mock_copy_volume_from_snapshot:
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
            drv.create_cloned_volume(volume, src_vref)

            mock_create_snapshot.assert_called_once_with(snap_ref)
            mock_copy_volume_from_snapshot.\
                assert_called_once_with(snap_ref, volume_ref, volume['size'])
            self.assertTrue(mock_delete_snapshot.called)

    @mock.patch('cinder.openstack.common.fileutils.delete_if_exists')
    def test_delete_volume(self, mock_delete_if_exists):
        volume = self._simple_volume()
        volume_filename = 'volume-%s' % self.VOLUME_UUID
        volume_path = '%s/%s' % (self.TEST_MNT_POINT, volume_filename)
        info_file = volume_path + '.info'

        with mock.patch.object(self._driver, '_ensure_share_mounted') as \
                mock_ensure_share_mounted,\
                mock.patch.object(self._driver, '_local_volume_dir') as \
                mock_local_volume_dir,\
                mock.patch.object(self._driver, 'get_active_image_from_info') as \
                mock_active_image_from_info,\
                mock.patch.object(self._driver, '_execute') as \
                mock_execute,\
                mock.patch.object(self._driver, '_local_path_volume') as \
                mock_local_path_volume,\
                mock.patch.object(self._driver, '_local_path_volume_info') as \
                mock_local_path_volume_info:
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
        with mock.patch.object(self._driver, '_unmount_shares') as \
                mock_unmount_shares,\
                mock.patch.object(self._driver, '_ensure_shares_mounted') as \
                mock_ensure_shares_mounted:
            self._driver._refresh_mounts()

            self.assertTrue(mock_unmount_shares.called)
            self.assertTrue(mock_ensure_shares_mounted.called)

    def test_refresh_mounts_with_excp(self):
        with mock.patch.object(self._driver, '_unmount_shares') as \
                mock_unmount_shares,\
                mock.patch.object(self._driver, '_ensure_shares_mounted') as \
                mock_ensure_shares_mounted,\
                mock.patch.object(glusterfs, 'LOG') as mock_logger:
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

        with mock.patch.object(self._driver, '_load_shares_config') as \
                _mock_load_shares_config,\
                mock.patch.object(self._driver, '_do_umount') as \
                mock_do_umount,\
                mock.patch.object(glusterfs, 'LOG') as \
                mock_logger:
            mock_do_umount.side_effect = Exception()

            self._driver._unmount_shares()

            self.assertTrue(mock_do_umount.called)
            self.assertTrue(mock_logger.warning.called)
            self.assertFalse(mock_logger.debug.called)
            self.assertTrue(_mock_load_shares_config.called)

    def test_unmount_shares_1share(self):
        self._driver.shares = {'127.7.7.7:/gluster1': None}

        with mock.patch.object(self._driver, '_load_shares_config') as \
                _mock_load_shares_config,\
                mock.patch.object(self._driver, '_do_umount') as \
                mock_do_umount:
            self._driver._unmount_shares()

            self.assertTrue(mock_do_umount.called)
            mock_do_umount.assert_called_once_with(True,
                                                   '127.7.7.7:/gluster1')
            self.assertTrue(_mock_load_shares_config.called)

    def test_unmount_shares_2share(self):
        self._driver.shares = {'127.7.7.7:/gluster1': None,
                               '127.7.7.8:/gluster2': None}

        with mock.patch.object(self._driver, '_load_shares_config') as \
                _mock_load_shares_config,\
                mock.patch.object(self._driver, '_do_umount') as \
                mock_do_umount:
            self._driver._unmount_shares()

            mock_do_umount.assert_any_call(True,
                                           '127.7.7.7:/gluster1')
            mock_do_umount.assert_any_call(True,
                                           '127.7.7.8:/gluster2')
            self.assertTrue(_mock_load_shares_config.called)

    def test_do_umount(self):
        test_share = '127.7.7.7:/gluster1'
        test_hashpath = '/hashed/mnt/path'

        with mock.patch.object(self._driver, '_get_mount_point_for_share') as \
                mock_get_mntp_share,\
                mock.patch.object(putils, 'execute') as mock_execute:
            mock_get_mntp_share.return_value = test_hashpath

            self._driver._do_umount(True, test_share)

            self.assertTrue(mock_get_mntp_share.called)
            self.assertTrue(mock_execute.called)
            mock_get_mntp_share.assert_called_once_with(test_share)

            cmd = ['umount', test_hashpath]
            self.assertEqual(cmd[0], mock_execute.call_args[0][0])
            self.assertEqual(cmd[1], mock_execute.call_args[0][1])
            self.assertTrue(mock_execute.call_args[1]['run_as_root'])

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
            self.assertTrue(mock_execute.call_args[1]['run_as_root'])

    def test_do_umount_with_excp1(self):
        test_share = '127.7.7.7:/gluster1'
        test_hashpath = '/hashed/mnt/path'

        with mock.patch.object(self._driver, '_get_mount_point_for_share') as \
                mock_get_mntp_share,\
                mock.patch.object(putils, 'execute') as mock_execute,\
                mock.patch.object(glusterfs, 'LOG') as mock_logger:
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

        with mock.patch.object(self._driver, '_get_mount_point_for_share') as \
                mock_get_mntp_share,\
                mock.patch.object(putils, 'execute') as mock_execute,\
                mock.patch.object(glusterfs, 'LOG') as mock_logger:
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
        drv = self._driver

        with mock.patch.object(drv, '_execute') as mock_execute,\
                mock.patch.object(drv, '_ensure_share_mounted') as \
                mock_ensure_share_mounted:
            volume = DumbVolume()
            volume['name'] = 'volume-123'
            volume['provider_location'] = self.TEST_EXPORT1

            drv.delete_volume(volume)

            mock_ensure_share_mounted.\
                assert_called_once_with(self.TEST_EXPORT1)
            self.assertTrue(mock_execute.called)

    def test_delete_should_not_delete_if_provider_location_not_provided(self):
        """delete_volume shouldn't delete if provider_location missed."""
        drv = self._driver

        with mock.patch.object(drv, '_execute') as mock_execute,\
                mock.patch.object(drv, '_ensure_share_mounted') as \
                mock_ensure_share_mounted:
            volume = DumbVolume()
            volume['name'] = 'volume-123'
            volume['provider_location'] = None

            drv.delete_volume(volume)

            self.assertFalse(mock_ensure_share_mounted.called)
            self.assertFalse(mock_execute.called)

    def test_read_info_file(self):
        drv = self._driver

        with mock.patch.object(drv, '_read_file') as mock_read_file:
                hashed = drv._get_hash_str(self.TEST_EXPORT1)
                volume_path = '%s/%s/volume-%s' % (self.TEST_MNT_POINT_BASE,
                                                   hashed,
                                                   self.VOLUME_UUID)
                info_path = '%s%s' % (volume_path, '.info')

                mock_read_file.return_value = '{"%(id)s": "volume-%(id)s"}' %\
                    {'id': self.VOLUME_UUID}

                volume = DumbVolume()
                volume['id'] = self.VOLUME_UUID
                volume['name'] = 'volume-%s' % self.VOLUME_UUID

                info = drv._read_info_file(info_path)

                self.assertEqual('volume-%s' % self.VOLUME_UUID,
                                 info[self.VOLUME_UUID])

    def test_extend_volume(self):
        drv = self._driver

        volume = self._simple_volume()

        qemu_img_info_output = """image: volume-%s
        file format: qcow2
        virtual size: 1.0G (1073741824 bytes)
        disk size: 473K
        """ % self.VOLUME_UUID
        img_info = imageutils.QemuImgInfo(qemu_img_info_output)

        with mock.patch.object(drv, 'get_active_image_from_info') as \
                mock_get_active_image_from_info,\
                mock.patch.object(image_utils, 'qemu_img_info') as \
                mock_qemu_img_info,\
                mock.patch.object(image_utils, 'resize_image') as \
                mock_resize_image:
            mock_get_active_image_from_info.return_value = volume['name']
            mock_qemu_img_info.return_value = img_info

            drv.extend_volume(volume, 3)
            self.assertTrue(mock_resize_image.called)

    def test_create_snapshot_online(self):
        drv = self._driver

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

        with mock.patch.object(drv, '_do_create_snapshot') as \
                mock_do_create_snapshot,\
                mock.patch.object(db, 'snapshot_get') as mock_snapshot_get,\
                mock.patch.object(drv, '_nova') as mock_nova,\
                mock.patch.object(time, 'sleep') as mock_sleep:
            create_info = {'snapshot_id': snap_ref['id'],
                           'type': 'qcow2',
                           'new_file': snap_file}

            snap_ref_progress = snap_ref.copy()
            snap_ref_progress['status'] = 'creating'

            snap_ref_progress_0p = snap_ref_progress.copy()
            snap_ref_progress_0p['progress'] = '0%'

            snap_ref_progress_50p = snap_ref_progress.copy()
            snap_ref_progress_50p['progress'] = '50%'

            snap_ref_progress_90p = snap_ref_progress.copy()
            snap_ref_progress_90p['progress'] = '90%'

            mock_snapshot_get.side_effect = [
                snap_ref_progress_0p, snap_ref_progress_50p,
                snap_ref_progress_90p
            ]

            drv._create_snapshot_online(snap_ref, snap_file, snap_path)
            mock_do_create_snapshot.\
                assert_called_once_with(snap_ref, snap_file, snap_path)
            mock_nova.create_volume_snapshot.\
                assert_called_once_with(ctxt, self.VOLUME_UUID, create_info)
            self.assertTrue(mock_sleep.called)

    def test_create_snapshot_online_novafailure(self):
        drv = self._driver

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

        with mock.patch.object(drv, '_do_create_snapshot') as mock_do_create_snapshot,\
                mock.patch.object(db, 'snapshot_get') as mock_snapshot_get,\
                mock.patch.object(drv, '_nova') as mock_nova,\
                mock.patch.object(time, 'sleep') as mock_sleep:
            snap_ref_progress = snap_ref.copy()
            snap_ref_progress['status'] = 'creating'

            snap_ref_progress_0p = snap_ref_progress.copy()
            snap_ref_progress_0p['progress'] = '0%'

            snap_ref_progress_50p = snap_ref_progress.copy()
            snap_ref_progress_50p['progress'] = '50%'

            snap_ref_progress_99p = snap_ref_progress.copy()
            snap_ref_progress_99p['progress'] = '99%'
            snap_ref_progress_99p['status'] = 'error'

            mock_snapshot_get.side_effect = [
                snap_ref_progress_0p, snap_ref_progress_50p,
                snap_ref_progress_99p
            ]

            self.assertRaisesAndMessageMatches(
                exception.RemoteFSException,
                'Nova returned "error" status while creating snapshot.',
                drv._create_snapshot_online,
                snap_ref, snap_file, snap_path)
            self.assertTrue(mock_sleep.called)
            self.assertTrue(mock_nova.create_volume_snapshot.called)
            self.assertTrue(mock_do_create_snapshot.called)

    def test_delete_snapshot_online_1(self):
        """Delete the newest snapshot, with only one snap present."""
        drv = self._driver

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

        with mock.patch.object(drv, '_execute') as mock_execute,\
                mock.patch.object(db, 'snapshot_get') as mock_snapshot_get,\
                mock.patch.object(drv, '_nova') as mock_nova,\
                mock.patch.object(time, 'sleep') as mock_sleep,\
                mock.patch.object(drv, '_read_info_file') as \
                mock_read_info_file,\
                mock.patch.object(drv, '_write_info_file') as \
                mock_write_info_file,\
                mock.patch.object(image_utils, 'qemu_img_info') as \
                mock_qemu_img_info,\
                mock.patch.object(drv, '_ensure_share_writable') as \
                mock_ensure_share_writable:
            snap_info = {'active': snap_file,
                         self.SNAP_UUID: snap_file}
            mock_read_info_file.return_value = snap_info

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

            paths = {snap_path: img_info, volume_path: volume_img_info}

            def img_info_side_effect(*args, **kwargs):
                return paths[args[0]]

            mock_qemu_img_info.side_effect = img_info_side_effect

            delete_info = {
                'type': 'qcow2',
                'merge_target_file': None,
                'file_to_merge': None,
                'volume_id': self.VOLUME_UUID
            }

            snap_ref_progress = snap_ref.copy()
            snap_ref_progress['status'] = 'deleting'

            snap_ref_progress_0p = snap_ref_progress.copy()
            snap_ref_progress_0p['progress'] = '0%'

            snap_ref_progress_50p = snap_ref_progress.copy()
            snap_ref_progress_50p['progress'] = '50%'

            snap_ref_progress_90p = snap_ref_progress.copy()
            snap_ref_progress_90p['progress'] = '90%'

            mock_snapshot_get.side_effect = [
                snap_ref_progress_0p, snap_ref_progress_50p,
                snap_ref_progress_90p
            ]

            drv.delete_snapshot(snap_ref)

            mock_ensure_share_writable.assert_called_once_with(volume_dir)
            mock_nova.delete_volume_snapshot.\
                assert_called_once_with(ctxt, self.SNAP_UUID, delete_info)
            mock_write_info_file.assert_called_once_with(info_path, snap_info)
            mock_execute.assert_called_once_with('rm', '-f', volume_path,
                                                 run_as_root=True)
            self.assertTrue(mock_ensure_share_writable.called)
            self.assertTrue(mock_write_info_file.called)
            self.assertTrue(mock_sleep.called)
            self.assertTrue(mock_nova.delete_volume_snapshot.called)
            self.assertTrue(mock_execute.called)

    def test_delete_snapshot_online_2(self):
        """Delete the middle of 3 snapshots."""
        drv = self._driver

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

        with mock.patch.object(drv, '_execute') as mock_execute,\
                mock.patch.object(db, 'snapshot_get') as \
                mock_snapshot_get,\
                mock.patch.object(drv, '_nova') as \
                mock_nova,\
                mock.patch.object(time, 'sleep') as \
                mock_sleep,\
                mock.patch.object(drv, '_read_info_file') as \
                mock_read_info_file,\
                mock.patch.object(drv, '_write_info_file') as \
                mock_write_info_file,\
                mock.patch.object(image_utils, 'qemu_img_info') as \
                mock_qemu_img_info,\
                mock.patch.object(drv, '_ensure_share_writable') as \
                mock_ensure_share_writable:
            snap_info = {'active': snap_file_2,
                         self.SNAP_UUID: snap_file,
                         self.SNAP_UUID_2: snap_file_2}

            mock_read_info_file.return_value = snap_info

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

            paths = {snap_path: img_info, volume_path: volume_img_info}

            def img_info_side_effect(*args, **kwargs):
                return paths[args[0]]
            mock_qemu_img_info.side_effect = img_info_side_effect

            delete_info = {'type': 'qcow2',
                           'merge_target_file': volume_file,
                           'file_to_merge': snap_file,
                           'volume_id': self.VOLUME_UUID}

            snap_ref_progress = snap_ref.copy()
            snap_ref_progress['status'] = 'deleting'

            snap_ref_progress_0p = snap_ref_progress.copy()
            snap_ref_progress_0p['progress'] = '0%'

            snap_ref_progress_50p = snap_ref_progress.copy()
            snap_ref_progress_50p['progress'] = '50%'

            snap_ref_progress_90p = snap_ref_progress.copy()
            snap_ref_progress_90p['progress'] = '90%'

            mock_snapshot_get.side_effect = [
                snap_ref_progress_0p, snap_ref_progress_50p,
                snap_ref_progress_90p]

            drv.delete_snapshot(snap_ref)

            mock_ensure_share_writable.assert_called_once_with(volume_dir)
            mock_nova.delete_volume_snapshot.\
                assert_called_once_with(ctxt, self.SNAP_UUID, delete_info)
            mock_write_info_file.assert_called_once_with(info_path, snap_info)
            mock_execute.assert_called_once_with('rm', '-f',
                                                 snap_path, run_as_root=True)
            self.assertTrue(mock_ensure_share_writable.called)
            self.assertTrue(mock_write_info_file.called)
            self.assertTrue(mock_sleep.called)
            self.assertTrue(mock_nova.delete_volume_snapshot.called)
            self.assertTrue(mock_execute.called)

    def test_delete_snapshot_online_novafailure(self):
        """Delete the newest snapshot."""
        drv = self._driver

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
        snap_path = '%s.%s' % (volume_path, self.SNAP_UUID)
        snap_file = '%s.%s' % (volume_file, self.SNAP_UUID)

        with mock.patch.object(drv, '_execute') as mock_execute,\
                mock.patch.object(drv, '_do_create_snapshot') as \
                mock_do_create_snapshot,\
                mock.patch.object(db, 'snapshot_get') as \
                mock_snapshot_get,\
                mock.patch.object(drv, '_nova') as \
                mock_nova,\
                mock.patch.object(time, 'sleep') as \
                mock_sleep,\
                mock.patch.object(drv, '_read_info_file') as \
                mock_read_info_file,\
                mock.patch.object(drv, '_write_info_file') as \
                mock_write_info_file,\
                mock.patch.object(image_utils, 'qemu_img_info') as \
                mock_qemu_img_info,\
                mock.patch.object(drv, '_ensure_share_writable') as \
                mock_ensure_share_writable:
            snap_info = {'active': snap_file,
                         self.SNAP_UUID: snap_file}
            mock_read_info_file.return_value = snap_info

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

            paths = {snap_path: img_info, volume_path: volume_img_info}

            def img_info_side_effect(*args, **kwargs):
                return paths[args[0]]

            mock_qemu_img_info.side_effect = img_info_side_effect

            snap_ref_progress = snap_ref.copy()
            snap_ref_progress['status'] = 'deleting'

            snap_ref_progress_0p = snap_ref_progress.copy()
            snap_ref_progress_0p['progress'] = '0%'

            snap_ref_progress_50p = snap_ref_progress.copy()
            snap_ref_progress_50p['progress'] = '50%'

            snap_ref_progress_90p = snap_ref_progress.copy()
            snap_ref_progress_90p['status'] = 'error_deleting'
            snap_ref_progress_90p['progress'] = '90%'

            mock_snapshot_get.side_effect = [
                snap_ref_progress_0p, snap_ref_progress_50p,
                snap_ref_progress_90p]
            self.assertRaisesAndMessageMatches(exception.RemoteFSException,
                                               'Unable to delete snapshot',
                                               drv.delete_snapshot,
                                               snap_ref)
            self.assertTrue(mock_ensure_share_writable.called)
            self.assertFalse(mock_write_info_file.called)
            self.assertTrue(mock_sleep.called)
            self.assertFalse(mock_nova.called)
            self.assertFalse(mock_do_create_snapshot.called)
            self.assertFalse(mock_execute.called)

    def test_get_backing_chain_for_path(self):
        drv = self._driver

        self.override_config('glusterfs_mount_point_base',
                             self.TEST_MNT_POINT_BASE)

        volume = self._simple_volume()
        vol_filename = volume['name']
        vol_filename_2 = volume['name'] + '.abcd'
        vol_filename_3 = volume['name'] + '.efef'
        hashed = drv._get_hash_str(self.TEST_EXPORT1)
        vol_dir = '%s/%s' % (self.TEST_MNT_POINT_BASE, hashed)
        vol_path = '%s/%s' % (vol_dir, vol_filename)
        vol_path_2 = '%s/%s' % (vol_dir, vol_filename_2)
        vol_path_3 = '%s/%s' % (vol_dir, vol_filename_3)

        with mock.patch.object(drv, '_local_volume_dir') as \
                mock_local_volume_dir,\
                mock.patch.object(image_utils, 'qemu_img_info') as \
                mock_qemu_img_info:
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

            qemu_img_output_1 = qemu_img_output_base %\
                {'image_name': vol_filename}
            qemu_img_output_2 = qemu_img_output %\
                {'image_name': vol_filename_2,
                 'backing_file': vol_filename}
            qemu_img_output_3 = qemu_img_output %\
                {'image_name': vol_filename_3,
                 'backing_file': vol_filename_2}

            info_1 = imageutils.QemuImgInfo(qemu_img_output_1)
            info_2 = imageutils.QemuImgInfo(qemu_img_output_2)
            info_3 = imageutils.QemuImgInfo(qemu_img_output_3)

            img_infos = {vol_path_3: info_3,
                         vol_path_2: info_2,
                         vol_path: info_1}

            def img_info_side_effect(*args, **kwargs):
                return img_infos[args[0]]

            mock_qemu_img_info.side_effect = img_info_side_effect
            mock_local_volume_dir.return_value = vol_dir

            chain = drv._get_backing_chain_for_path(volume, vol_path_3)

            # Verify chain contains all expected data
            item_1 = drv._get_matching_backing_file(chain, vol_filename)
            self.assertEqual(vol_filename_2, item_1['filename'])
            chain.remove(item_1)
            item_2 = drv._get_matching_backing_file(chain, vol_filename_2)
            self.assertEqual(vol_filename_3, item_2['filename'])
            chain.remove(item_2)
            self.assertEqual(1, len(chain))
            self.assertEqual(vol_filename, chain[0]['filename'])

    def test_copy_volume_from_snapshot(self):
        drv = self._driver

        with mock.patch.object(image_utils, 'convert_image') as \
                mock_convert_image,\
                mock.patch.object(drv, '_read_info_file') as \
                mock_read_info_file,\
                mock.patch.object(image_utils, 'qemu_img_info') as \
                mock_qemu_img_info,\
                mock.patch.object(drv, '_set_rw_permissions_for_all') as \
                mock_set_rw_permissions:
            dest_volume = self._simple_volume(
                'c1073000-0000-0000-0000-0000000c1073')
            src_volume = self._simple_volume()

            vol_dir = os.path.join(self.TEST_MNT_POINT_BASE,
                                   drv._get_hash_str(self.TEST_EXPORT1))
            src_vol_path = os.path.join(vol_dir, src_volume['name'])
            dest_vol_path = os.path.join(vol_dir, dest_volume['name'])
            snapshot = {'volume_name': src_volume['name'],
                        'name': 'clone-snap-%s' % src_volume['id'],
                        'size': src_volume['size'],
                        'volume_size': src_volume['size'],
                        'volume_id': src_volume['id'],
                        'id': 'tmp-snap-%s' % src_volume['id'],
                        'volume': src_volume}
            snap_file = dest_volume['name'] + '.' + snapshot['id']
            size = dest_volume['size']
            mock_read_info_file.return_value = {'active': snap_file,
                                                snapshot['id']: snap_file}
            qemu_img_output = """image: %s
            file format: raw
            virtual size: 1.0G (1073741824 bytes)
            disk size: 173K
            backing file: %s
            """ % (snap_file, src_volume['name'])
            img_info = imageutils.QemuImgInfo(qemu_img_output)
            mock_qemu_img_info.return_value = img_info

            drv._copy_volume_from_snapshot(snapshot, dest_volume, size)

            mock_convert_image.assert_called_once_with(src_vol_path,
                                                       dest_vol_path, 'raw')
            mock_set_rw_permissions.assert_called_once_with(dest_vol_path)

    def test_create_volume_from_snapshot(self):
        drv = self._driver

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

        with mock.patch.object(drv, '_ensure_shares_mounted') as \
                mock_ensure_shares_mounted,\
                mock.patch.object(drv, '_find_share') as \
                mock_find_share, \
                mock.patch.object(drv, '_do_create_volume') as \
                mock_do_create_volume, \
                mock.patch.object(drv, '_copy_volume_from_snapshot') as \
                mock_copy_volume:
            mock_find_share.return_value = self.TEST_EXPORT1
            drv.create_volume_from_snapshot(new_volume, snap_ref)

            self.assertTrue(mock_ensure_shares_mounted.called)
            mock_do_create_volume.assert_called_once_with(new_volume)
            mock_copy_volume.assert_called_once_with(snap_ref,
                                                     new_volume,
                                                     new_volume['size'])

    def test_initialize_connection(self):
        drv = self._driver

        volume = self._simple_volume()
        qemu_img_output = """image: %s
        file format: raw
        virtual size: 1.0G (1073741824 bytes)
        disk size: 173K
        """ % volume['name']
        img_info = imageutils.QemuImgInfo(qemu_img_output)

        with mock.patch.object(drv, 'get_active_image_from_info') as \
                mock_get_active_image_from_info,\
                mock.patch.object(image_utils, 'qemu_img_info') as \
                mock_qemu_img_info:
            mock_get_active_image_from_info.return_value = volume['name']
            mock_qemu_img_info.return_value = img_info

            conn_info = drv.initialize_connection(volume, None)

            self.assertEqual('raw', conn_info['data']['format'])
            self.assertEqual('glusterfs', conn_info['driver_volume_type'])
            self.assertEqual(volume['name'], conn_info['data']['name'])
            self.assertEqual(self.TEST_MNT_POINT_BASE,
                             conn_info['mount_point_base'])

    def test_get_mount_point_base(self):
        drv = self._driver

        self.assertEqual(self.TEST_MNT_POINT_BASE,
                         drv._get_mount_point_base())

    def test_backup_volume(self):
        """Backup a volume with no snapshots."""
        drv = self._driver

        with mock.patch.object(drv.db, 'volume_get') as mock_volume_get,\
                mock.patch.object(drv, 'get_active_image_from_info') as \
                mock_get_active_image_from_info,\
                mock.patch.object(drv, '_qemu_img_info') as \
                mock_qemu_img_info,\
                mock.patch.object(base_driver.VolumeDriver, 'backup_volume') as \
                mock_backup_volume:
            ctxt = context.RequestContext('fake_user', 'fake_project')
            volume = self._simple_volume()
            backup = {'volume_id': volume['id']}
            mock_volume_get.return_value = volume
            mock_get_active_image_from_info.return_value = '/some/path'

            info = imageutils.QemuImgInfo()
            info.file_format = 'raw'
            mock_qemu_img_info.return_value = info

            drv.backup_volume(ctxt, backup, mock.MagicMock())
            self.assertTrue(mock_backup_volume.called)

    def test_backup_volume_previous_snap(self):
        """Backup a volume that previously had a snapshot.

           Snapshot was deleted, snap_info is different from above.
        """
        drv = self._driver

        with mock.patch.object(drv.db, 'volume_get') as mock_volume_get,\
                mock.patch.object(drv, 'get_active_image_from_info') as \
                mock_get_active_image_from_info,\
                mock.patch.object(drv, '_qemu_img_info') as \
                mock_qemu_img_info,\
                mock.patch.object(base_driver.VolumeDriver, 'backup_volume') as \
                mock_backup_volume:
            ctxt = context.RequestContext('fake_user', 'fake_project')
            volume = self._simple_volume()
            backup = {'volume_id': volume['id']}
            mock_volume_get.return_value = volume
            mock_get_active_image_from_info.return_value = '/some/file2'

            info = imageutils.QemuImgInfo()
            info.file_format = 'raw'
            mock_qemu_img_info.return_value = info

            drv.backup_volume(ctxt, backup, mock.MagicMock())
            self.assertTrue(mock_backup_volume.called)

    def test_backup_snap_failure_1(self):
        """Backup fails if snapshot exists (database)."""

        drv = self._driver

        with mock.patch.object(drv.db, 'snapshot_get_all_for_volume') as \
                mock_snapshot_get_all_for_volume:
            ctxt = context.RequestContext('fake_user', 'fake_project')
            volume = self._simple_volume()
            backup = {'volume_id': volume['id']}
            mock_snapshot_get_all_for_volume.return_value = [
                {'snap1': 'a'},
                {'snap2': 'b'}
            ]
            self.assertRaises(exception.InvalidVolume,
                              drv.backup_volume,
                              ctxt, backup, mock.MagicMock())

    def test_backup_snap_failure_2(self):
        """Backup fails if snapshot exists (on-disk)."""
        drv = self._driver

        with mock.patch.object(drv.db, 'volume_get') as mock_volume_get,\
                mock.patch.object(drv, 'get_active_image_from_info') as \
                mock_get_active_image_from_info, \
                mock.patch.object(drv, '_qemu_img_info') as \
                mock_qemu_img_info:
            ctxt = context.RequestContext('fake_user', 'fake_project')
            volume = self._simple_volume()
            backup = {'volume_id': volume['id']}
            mock_volume_get.return_value = volume
            mock_get_active_image_from_info.return_value = '/some/path/file2'

            info = imageutils.QemuImgInfo()
            info.file_format = 'raw'
            info.backing_file = 'file1'
            mock_qemu_img_info.return_value = info

            self.assertRaises(exception.InvalidVolume,
                              drv.backup_volume,
                              ctxt, backup, mock.MagicMock())

    def test_backup_failure_unsupported_format(self):
        """Attempt to backup a volume with a qcow2 base."""
        drv = self._driver

        with mock.patch.object(drv.db, 'volume_get') as mock_volume_get,\
                mock.patch.object(drv, 'get_active_image_from_info') as \
                mock_get_active_image_from_info,\
                mock.patch.object(drv, '_qemu_img_info') as mock_qemu_img_info:
            ctxt = context.RequestContext('fake_user', 'fake_project')
            volume = self._simple_volume()
            backup = {'volume_id': volume['id']}
            mock_volume_get.return_value = volume
            mock_get_active_image_from_info.return_value = '/some/path'

            info = imageutils.QemuImgInfo()
            info.file_format = 'qcow2'

            self.assertRaises(exception.InvalidVolume,
                              drv.backup_volume,
                              ctxt, backup, mock.MagicMock())

            mock_volume_get.return_value = volume
            mock_qemu_img_info.return_value = info

            self.assertRaises(exception.InvalidVolume,
                              drv.backup_volume,
                              ctxt, backup, mock.MagicMock())

    def test_copy_volume_to_image_raw_image(self):
        drv = self._driver

        volume = self._simple_volume()
        volume_path = '%s/%s' % (self.TEST_MNT_POINT, volume['name'])
        image_meta = {'id': '10958016-e196-42e3-9e7f-5d8927ae3099'}

        with mock.patch.object(drv, 'get_active_image_from_info') as \
                mock_get_active_image_from_info, \
                mock.patch.object(drv, '_local_volume_dir') as \
                mock_local_volume_dir, \
                mock.patch.object(image_utils, 'qemu_img_info') as \
                mock_qemu_img_info, \
                mock.patch.object(image_utils, 'upload_volume') as \
                mock_upload_volume, \
                mock.patch.object(image_utils, 'create_temporary_file') as \
                mock_create_temporary_file:
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
            self.assertEqual(1, mock_create_temporary_file.call_count)

    def test_copy_volume_to_image_qcow2_image(self):
        """Upload a qcow2 image file which has to be converted to raw first."""
        drv = self._driver

        volume = self._simple_volume()
        volume_path = '%s/%s' % (self.TEST_MNT_POINT, volume['name'])
        image_meta = {'id': '10958016-e196-42e3-9e7f-5d8927ae3099'}

        with mock.patch.object(drv, 'get_active_image_from_info') as \
                mock_get_active_image_from_info, \
                mock.patch.object(drv, '_local_volume_dir') as \
                mock_local_volume_dir, \
                mock.patch.object(image_utils, 'qemu_img_info') as \
                mock_qemu_img_info, \
                mock.patch.object(image_utils, 'convert_image') as \
                mock_convert_image, \
                mock.patch.object(image_utils, 'upload_volume') as \
                mock_upload_volume, \
                mock.patch.object(image_utils, 'create_temporary_file') as \
                mock_create_temporary_file:
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
            self.assertEqual(1, mock_create_temporary_file.call_count)

    def test_copy_volume_to_image_snapshot_exists(self):
        """Upload an active snapshot which has to be converted to raw first."""
        drv = self._driver

        volume = self._simple_volume()
        volume_path = '%s/volume-%s' % (self.TEST_MNT_POINT, self.VOLUME_UUID)
        volume_filename = 'volume-%s' % self.VOLUME_UUID
        image_meta = {'id': '10958016-e196-42e3-9e7f-5d8927ae3099'}

        with mock.patch.object(drv, 'get_active_image_from_info') as \
                mock_get_active_image_from_info, \
                mock.patch.object(drv, '_local_volume_dir') as \
                mock_local_volume_dir, \
                mock.patch.object(image_utils, 'qemu_img_info') as \
                mock_qemu_img_info, \
                mock.patch.object(image_utils, 'convert_image') as \
                mock_convert_image, \
                mock.patch.object(image_utils, 'upload_volume') as \
                mock_upload_volume, \
                mock.patch.object(image_utils, 'create_temporary_file') as \
                mock_create_temporary_file:
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
            self.assertEqual(1, mock_create_temporary_file.call_count)
