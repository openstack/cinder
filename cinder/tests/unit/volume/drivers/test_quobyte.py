# Copyright (c) 2014 Quobyte Inc.
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
"""Unit tests for the Quobyte driver module."""

import errno
import os
import shutil
import traceback
from unittest import mock

import ddt
from oslo_concurrency import processutils as putils
from oslo_utils import fileutils
from oslo_utils import imageutils
from oslo_utils import units
import psutil
import six

from cinder import context
from cinder import db
from cinder import exception
from cinder.image import image_utils
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume
from cinder.tests.unit import test
from cinder.volume import configuration as conf
from cinder.volume.drivers import quobyte
from cinder.volume.drivers import remotefs


class FakeDb(object):
    msg = "Tests are broken: mock this out."

    def volume_get(self, *a, **kw):
        raise Exception(self.msg)

    def snapshot_get_all_for_volume(self, *a, **kw):
        """Mock this if you want results from it."""
        return []

    def volume_get_all(self, *a, **kw):
        return []


@ddt.ddt
class QuobyteDriverTestCase(test.TestCase):
    """Test case for Quobyte driver."""

    TEST_QUOBYTE_VOLUME = 'quobyte://quobyte-host/openstack-volumes'
    TEST_QUOBYTE_VOLUME_WITHOUT_PROTOCOL = 'quobyte-host/openstack-volumes'
    TEST_SIZE_IN_GB = 1
    TEST_MNT_HASH = "1331538734b757ed52d0e18c0a7210cd"
    TEST_MNT_POINT_BASE = '/fake-mnt'
    TEST_MNT_POINT = os.path.join(TEST_MNT_POINT_BASE, TEST_MNT_HASH)
    TEST_FILE_NAME = 'test.txt'
    TEST_SHARES_CONFIG_FILE = '/etc/cinder/test-shares.conf'
    TEST_TMP_FILE = '/tmp/tempfile'
    VOLUME_UUID = 'abcdefab-cdef-abcd-efab-cdefabcdefab'
    SNAP_UUID = 'bacadaca-baca-daca-baca-dacadacadaca'
    SNAP_UUID_2 = 'bebedede-bebe-dede-bebe-dedebebedede'
    CACHE_NAME = quobyte.QuobyteDriver.QUOBYTE_VOLUME_SNAP_CACHE_DIR_NAME

    def _get_fake_snapshot(self, src_volume):
        snapshot = fake_snapshot.fake_snapshot_obj(
            self.context,
            volume_name=src_volume.name,
            display_name='clone-snap-%s' % src_volume.id,
            size=src_volume.size,
            volume_size=src_volume.size,
            volume_id=src_volume.id,
            id=self.SNAP_UUID)
        snapshot.volume = src_volume
        return snapshot

    def setUp(self):
        super(QuobyteDriverTestCase, self).setUp()

        self._configuration = mock.Mock(conf.Configuration)
        self._configuration.append_config_values(mock.ANY)
        self._configuration.quobyte_volume_url = \
            self.TEST_QUOBYTE_VOLUME
        self._configuration.quobyte_client_cfg = None
        self._configuration.quobyte_sparsed_volumes = True
        self._configuration.quobyte_qcow2_volumes = False
        self._configuration.quobyte_mount_point_base = \
            self.TEST_MNT_POINT_BASE
        self._configuration.nas_secure_file_operations = "true"
        self._configuration.nas_secure_file_permissions = "true"
        self._configuration.quobyte_volume_from_snapshot_cache = False
        self._configuration.quobyte_overlay_volumes = False

        self._driver = quobyte.QuobyteDriver(configuration=self._configuration)
        self._driver.shares = {}
        self._driver.set_nas_security_options(is_new_cinder_install=False)
        self._driver.base = self._configuration.quobyte_mount_point_base

        self.context = context.get_admin_context()

    def assertRaisesAndMessageMatches(
            self, excClass, msg, callableObj, *args, **kwargs):
        """Ensure that the specified exception was raised. """

        caught = False
        try:
            callableObj(*args, **kwargs)
        except Exception as exc:
            caught = True
            self.assertIsInstance(exc, excClass,
                                  'Wrong exception caught: %s Stacktrace: %s' %
                                  (exc, traceback.format_exc()))
            self.assertIn(msg, six.text_type(exc))

        if not caught:
            self.fail('Expected raised exception but nothing caught.')

    def get_mock_partitions(self):
        mypart = mock.Mock()
        mypart.device = "quobyte@"
        mypart.mountpoint = self.TEST_MNT_POINT
        return [mypart]

    @mock.patch.object(os, "symlink")
    def test__create_overlay_volume_from_snapshot(self, os_sl_mock):
        drv = self._driver
        drv._execute = mock.Mock()
        vol = self._simple_volume()
        snap = self._get_fake_snapshot(vol)
        r_path = os.path.join(drv.QUOBYTE_VOLUME_SNAP_CACHE_DIR_NAME,
                              snap.id)
        vol_path = drv._local_path_volume(vol)

        drv._create_overlay_volume_from_snapshot(vol, snap, 1, "qcow2")

        drv._execute.assert_called_once_with(
            'qemu-img', 'create', '-f', 'qcow2', '-o',
            'backing_file=%s,backing_fmt=qcow2' % (r_path), vol_path, "1G",
            run_as_root=drv._execute_as_root)
        os_sl_mock.assert_called_once_with(
            drv.local_path(vol),
            drv._local_volume_from_snap_cache_path(snap) + '.child-' + vol.id)

    def test__create_regular_file(self):
        with mock.patch.object(self._driver, "_execute") as qb_exec_mock:
            tmp_path = "/path/for/test"
            test_size = 1

            self._driver._create_regular_file(tmp_path, test_size)

            qb_exec_mock.assert_called_once_with(
                'fallocate', '-l', '%sGiB' % test_size, tmp_path,
                run_as_root=self._driver._execute_as_root)

    @mock.patch.object(os, "makedirs")
    @mock.patch.object(os.path, "join", return_value="dummy_path")
    @mock.patch.object(os, "access", return_value=True)
    def test__ensure_volume_cache_ok(self, os_access_mock, os_join_mock,
                                     os_makedirs_mock):
        tmp_path = "/some/random/path"

        self._driver._ensure_volume_from_snap_cache(tmp_path)

        calls = [mock.call("dummy_path", os.F_OK),
                 mock.call("dummy_path", os.R_OK),
                 mock.call("dummy_path", os.W_OK),
                 mock.call("dummy_path", os.X_OK)]
        os_access_mock.assert_has_calls(calls)
        os_join_mock.assert_called_once_with(
            tmp_path, self._driver.QUOBYTE_VOLUME_SNAP_CACHE_DIR_NAME)
        self.assertFalse(os_makedirs_mock.called)

    @mock.patch.object(fileutils, "ensure_tree")
    @mock.patch.object(os.path, "join", return_value="dummy_path")
    @mock.patch.object(os, "access", return_value=True)
    def test__ensure_volume_cache_create(self, os_access_mock, os_join_mock,
                                         os_makedirs_mock):
        tmp_path = "/some/random/path"
        os_access_mock.side_effect = [False, True, True, True]

        self._driver._ensure_volume_from_snap_cache(tmp_path)

        calls = [mock.call("dummy_path", os.F_OK),
                 mock.call("dummy_path", os.R_OK),
                 mock.call("dummy_path", os.W_OK),
                 mock.call("dummy_path", os.X_OK)]
        os_access_mock.assert_has_calls(calls)
        os_join_mock.assert_called_once_with(
            tmp_path, self._driver.QUOBYTE_VOLUME_SNAP_CACHE_DIR_NAME)
        os_makedirs_mock.assert_called_once_with("dummy_path")

    @mock.patch.object(os, "makedirs")
    @mock.patch.object(os.path, "join", return_value="dummy_path")
    @mock.patch.object(os, "access", return_value=True)
    def test__ensure_volume_cache_error(self, os_access_mock, os_join_mock,
                                        os_makedirs_mock):
        tmp_path = "/some/random/path"
        os_access_mock.side_effect = [True, False, False, False]

        self.assertRaises(
            exception.VolumeDriverException,
            self._driver._ensure_volume_from_snap_cache, tmp_path)

        calls = [mock.call("dummy_path", os.F_OK),
                 mock.call("dummy_path", os.R_OK)]
        os_access_mock.assert_has_calls(calls)
        os_join_mock.assert_called_once_with(
            tmp_path, self._driver.QUOBYTE_VOLUME_SNAP_CACHE_DIR_NAME)
        self.assertFalse(os_makedirs_mock.called)

    @mock.patch.object(remotefs.RemoteFSSnapDriverDistributed,
                       "_get_backing_chain_for_path")
    @ddt.data(
        [[], []],
        [[{'filename': "A"}, {'filename': CACHE_NAME}], [{'filename': "A"}]],
        [[{'filename': "A"}, {'filename': "B"}], [{'filename': "A"},
                                                  {'filename': "B"}]]
    )
    @ddt.unpack
    def test__get_backing_chain_for_path(self, test_chain,
                                         result_chain, rfs_chain_mock):
        drv = self._driver
        rfs_chain_mock.return_value = test_chain

        result = drv._get_backing_chain_for_path("foo", "bar")

        self.assertEqual(result_chain, result)

    @mock.patch.object(image_utils, 'qemu_img_info')
    @mock.patch('os.path.basename')
    def _test__qemu_img_info(self, mock_basename, mock_qemu_img_info,
                             backing_file, base_dir, valid_backing_file=True):
        drv = self._driver
        drv._execute_as_root = True
        fake_vol_name = "volume-" + self.VOLUME_UUID
        mock_info = mock_qemu_img_info.return_value
        mock_info.image = mock.sentinel.image_path
        mock_info.backing_file = backing_file

        drv._VALID_IMAGE_EXTENSIONS = ['raw', 'qcow2']

        mock_basename.side_effect = [mock.sentinel.image_basename,
                                     mock.sentinel.backing_file_basename]

        if valid_backing_file:
            img_info = drv._qemu_img_info_base(
                mock.sentinel.image_path, fake_vol_name, base_dir)
            self.assertEqual(mock_info, img_info)
            self.assertEqual(mock.sentinel.image_basename,
                             mock_info.image)
            expected_basename_calls = [mock.call(mock.sentinel.image_path)]
            if backing_file:
                self.assertEqual(mock.sentinel.backing_file_basename,
                                 mock_info.backing_file)
                expected_basename_calls.append(mock.call(backing_file))
            mock_basename.assert_has_calls(expected_basename_calls)
        else:
            self.assertRaises(exception.RemoteFSInvalidBackingFile,
                              drv._qemu_img_info_base,
                              mock.sentinel.image_path,
                              fake_vol_name, base_dir)

        mock_qemu_img_info.assert_called_with(mock.sentinel.image_path,
                                              force_share=True,
                                              run_as_root=True)

    @ddt.data(['/other_random_path', '/mnt'],
              ['/other_basedir/' + TEST_MNT_HASH + '/volume-' + VOLUME_UUID,
               '/fake_basedir'],
              ['/mnt/invalid_hash/volume-' + VOLUME_UUID, '/mnt'],
              ['/mnt/' + TEST_MNT_HASH + '/invalid_vol_name', '/mnt'],
              ['/mnt/' + TEST_MNT_HASH + '/volume-' + VOLUME_UUID + '.info',
               '/fake_basedir'],
              ['/mnt/' + TEST_MNT_HASH + '/volume-' + VOLUME_UUID +
               '.random-suffix', '/mnt'],
              ['/mnt/' + TEST_MNT_HASH + '/volume-' + VOLUME_UUID +
               '.invalidext', '/mnt'])
    @ddt.unpack
    def test__qemu_img_info_invalid_backing_file(self, backing_file, basedir):
        self._test__qemu_img_info(backing_file=backing_file, base_dir=basedir,
                                  valid_backing_file=False)

    @ddt.data([None, '/mnt'],
              ['/mnt/' + TEST_MNT_HASH + '/volume-' + VOLUME_UUID,
               '/mnt'],
              ['/mnt/' + TEST_MNT_HASH + '/volume-' + VOLUME_UUID + '.qcow2',
               '/mnt'],
              ['/mnt/' + TEST_MNT_HASH + '/volume-' + VOLUME_UUID +
               '.404f-404', '/mnt'],
              ['/mnt/' + TEST_MNT_HASH + '/volume-' + VOLUME_UUID +
               '.tmp-snap-404f-404', '/mnt'])
    @ddt.unpack
    def test__qemu_img_info_valid_backing_file(self, backing_file, basedir):
        self._test__qemu_img_info(backing_file=backing_file, base_dir=basedir)

    @ddt.data(['/mnt/' + TEST_MNT_HASH + '/' + CACHE_NAME + '/' + VOLUME_UUID,
               '/mnt'],
              ['/mnt/' + TEST_MNT_HASH + '/' + CACHE_NAME + '/' + VOLUME_UUID +
               '.child-aaaaa', '/mnt'],
              ['/mnt/' + TEST_MNT_HASH + '/' + CACHE_NAME + '/' + VOLUME_UUID +
               '.parent-bbbbbb', '/mnt'],
              ['/mnt/' + TEST_MNT_HASH + '/' + CACHE_NAME + '/tmp-snap-' +
               VOLUME_UUID, '/mnt'])
    @ddt.unpack
    def test__qemu_img_info_valid_cache_backing_file(self, backing_file,
                                                     basedir):
        self._test__qemu_img_info(backing_file=backing_file, base_dir=basedir)

    @mock.patch.object(os, "listdir", return_value=["fake_vol"])
    @mock.patch.object(fileutils, "delete_if_exists")
    def test__remove_from_vol_cache_no_refs(self, fu_die_mock, os_list_mock):
        drv = self._driver
        volume = self._simple_volume()
        cache_path = drv.QUOBYTE_VOLUME_SNAP_CACHE_DIR_NAME + "/fake_vol"
        suf = ".test_suffix"

        drv._remove_from_vol_cache(cache_path, suf, volume)

        fu_die_mock.assert_has_calls([
            mock.call(os.path.join(drv._local_volume_dir(volume),
                                   drv.QUOBYTE_VOLUME_SNAP_CACHE_DIR_NAME,
                                   "fake_vol.test_suffix")),
            mock.call(os.path.join(drv._local_volume_dir(volume),
                                   drv.QUOBYTE_VOLUME_SNAP_CACHE_DIR_NAME,
                                   "fake_vol"))])
        os_list_mock.assert_called_once_with(os.path.join(
            drv._local_volume_dir(volume),
            drv.QUOBYTE_VOLUME_SNAP_CACHE_DIR_NAME))

    @mock.patch.object(os, "listdir", return_value=["fake_vol",
                                                    "fake_vol.more_ref"])
    @mock.patch.object(fileutils, "delete_if_exists")
    def test__remove_from_vol_cache_with_refs(self, fu_die_mock, os_list_mock):
        drv = self._driver
        volume = self._simple_volume()
        cache_path = drv.QUOBYTE_VOLUME_SNAP_CACHE_DIR_NAME + "/fake_vol"
        suf = ".test_suffix"

        drv._remove_from_vol_cache(cache_path, suf, volume)

        fu_die_mock.assert_called_once_with(
            os.path.join(drv._local_volume_dir(volume),
                         drv.QUOBYTE_VOLUME_SNAP_CACHE_DIR_NAME,
                         "fake_vol.test_suffix"))
        os_list_mock.assert_called_once_with(os.path.join(
            drv._local_volume_dir(volume),
            drv.QUOBYTE_VOLUME_SNAP_CACHE_DIR_NAME))

    def test_local_path(self):
        """local_path common use case."""
        drv = self._driver
        vol_id = self.VOLUME_UUID
        volume = self._simple_volume(_name_id=vol_id)

        self.assertEqual(
            os.path.join(self.TEST_MNT_POINT, 'volume-%s' % vol_id),
            drv.local_path(volume))

    def test_mount_quobyte_should_mount_correctly(self):
        with mock.patch.object(self._driver, '_execute') as mock_execute, \
                mock.patch('cinder.volume.drivers.quobyte.QuobyteDriver'
                           '.read_proc_mount') as mock_open, \
                mock.patch('oslo_utils.fileutils.ensure_tree') as mock_mkdir, \
                mock.patch('cinder.volume.drivers.quobyte.QuobyteDriver'
                           '._validate_volume') as mock_validate:
            # Content of /proc/mount (not mounted yet).
            mock_open.return_value = six.StringIO(
                "/dev/sda5 / ext4 rw,relatime,data=ordered 0 0")

            self._driver._mount_quobyte(self.TEST_QUOBYTE_VOLUME,
                                        self.TEST_MNT_POINT)

            mock_mkdir.assert_called_once_with(self.TEST_MNT_POINT)
            mount_call = mock.call(
                'mount.quobyte', '--disable-xattrs', self.TEST_QUOBYTE_VOLUME,
                self.TEST_MNT_POINT, run_as_root=False)

            mock_execute.assert_has_calls(
                [mount_call], any_order=False)
            mock_validate.called_once_with(self.TEST_MNT_POINT)

    def test_mount_quobyte_already_mounted_detected_seen_in_proc_mount(self):
        with mock.patch('cinder.volume.drivers.quobyte.QuobyteDriver'
                        '.read_proc_mount') as mock_open, \
                mock.patch('cinder.volume.drivers.quobyte.QuobyteDriver'
                           '._validate_volume') as mock_validate:
            # Content of /proc/mount (already mounted).
            mock_open.return_value = six.StringIO(
                "quobyte@%s %s fuse rw,nosuid,nodev,noatime,user_id=1000"
                ",group_id=100,default_permissions,allow_other 0 0"
                % (self.TEST_QUOBYTE_VOLUME, self.TEST_MNT_POINT))

            self._driver._mount_quobyte(self.TEST_QUOBYTE_VOLUME,
                                        self.TEST_MNT_POINT)
            mock_validate.assert_called_once_with(self.TEST_MNT_POINT)

    def test_mount_quobyte_should_suppress_already_mounted_error(self):
        """test_mount_quobyte_should_suppress_already_mounted_error

           Based on /proc/mount, the file system is not mounted yet. However,
           mount.quobyte returns with an 'already mounted' error. This is
           a last-resort safe-guard in case /proc/mount parsing was not
           successful.

           Because _mount_quobyte gets called with ensure=True, the error will
           be suppressed instead.
        """
        with mock.patch.object(self._driver, '_execute') as mock_execute, \
                mock.patch('cinder.volume.drivers.quobyte.QuobyteDriver'
                           '.read_proc_mount') as mock_open, \
                mock.patch('oslo_utils.fileutils.ensure_tree') as mock_mkdir, \
                mock.patch('cinder.volume.drivers.quobyte.QuobyteDriver'
                           '._validate_volume') as mock_validate:
            # Content of /proc/mount (empty).
            mock_open.return_value = six.StringIO()
            mock_execute.side_effect = [None, putils.ProcessExecutionError(
                stderr='is busy or already mounted')]

            self._driver._mount_quobyte(self.TEST_QUOBYTE_VOLUME,
                                        self.TEST_MNT_POINT,
                                        ensure=True)

            mock_mkdir.assert_called_once_with(self.TEST_MNT_POINT)
            mount_call = mock.call(
                'mount.quobyte', '--disable-xattrs', self.TEST_QUOBYTE_VOLUME,
                self.TEST_MNT_POINT, run_as_root=False)
            mock_execute.assert_has_calls([mount_call],
                                          any_order=False)
            mock_validate.assert_called_once_with(self.TEST_MNT_POINT)

    @mock.patch.object(psutil, "disk_partitions")
    def test_mount_quobyte_should_reraise_already_mounted_error(self,
                                                                part_mock):
        """test_mount_quobyte_should_reraise_already_mounted_error

        Like test_mount_quobyte_should_suppress_already_mounted_error
        but with ensure=False.
        """
        part_mock.return_value = []  # no quobyte@ devices
        with mock.patch.object(self._driver, '_execute') as mock_execute, \
                mock.patch('oslo_utils.fileutils.ensure_tree') as mock_mkdir, \
                mock.patch('cinder.volume.drivers.quobyte.QuobyteDriver'
                           '.read_proc_mount') as mock_open:
            mock_open.return_value = six.StringIO()
            mock_execute.side_effect = [
                None,  # mkdir
                putils.ProcessExecutionError(  # mount
                    stderr='is busy or already mounted')]

            self.assertRaises(exception.VolumeDriverException,
                              self._driver._mount_quobyte,
                              self.TEST_QUOBYTE_VOLUME,
                              self.TEST_MNT_POINT,
                              ensure=False)

            mock_mkdir.assert_called_once_with(self.TEST_MNT_POINT)
            mount_call = mock.call(
                'mount.quobyte', '--disable-xattrs', self.TEST_QUOBYTE_VOLUME,
                self.TEST_MNT_POINT, run_as_root=False)
            mock_execute.assert_has_calls([mount_call],
                                          any_order=False)

    def test_get_hash_str(self):
        """_get_hash_str should calculation correct value."""
        drv = self._driver

        self.assertEqual(self.TEST_MNT_HASH,
                         drv._get_hash_str(self.TEST_QUOBYTE_VOLUME))

    def test_get_available_capacity_with_df(self):
        """_get_available_capacity should calculate correct value."""
        drv = self._driver

        df_total_size = 2620544
        df_avail = 1490560
        df_head = 'Filesystem 1K-blocks Used Available Use% Mounted on\n'
        df_data = 'quobyte@%s %d 996864 %d 41%% %s' % \
                  (self.TEST_QUOBYTE_VOLUME, df_total_size, df_avail,
                   self.TEST_MNT_POINT)
        df_output = df_head + df_data

        drv._get_mount_point_for_share = mock.Mock(return_value=self.
                                                   TEST_MNT_POINT)

        drv._execute = mock.Mock(return_value=(df_output, None))

        self.assertEqual((df_avail, df_total_size),
                         drv._get_available_capacity(self.TEST_QUOBYTE_VOLUME))
        (drv._get_mount_point_for_share.
            assert_called_once_with(self.TEST_QUOBYTE_VOLUME))
        (drv._execute.
         assert_called_once_with('df',
                                 '--portability',
                                 '--block-size',
                                 '1',
                                 self.TEST_MNT_POINT,
                                 run_as_root=self._driver._execute_as_root))

    def test_get_capacity_info(self):
        with mock.patch.object(self._driver, '_get_available_capacity') \
                as mock_get_available_capacity:
            drv = self._driver

            df_size = 2620544
            df_avail = 1490560

            mock_get_available_capacity.return_value = (df_avail, df_size)

            size, available, used = drv._get_capacity_info(mock.ANY)

            mock_get_available_capacity.assert_called_once_with(mock.ANY)

            self.assertEqual(df_size, size)
            self.assertEqual(df_avail, available)
            self.assertEqual(size - available, used)

    def test_load_shares_config(self):
        """_load_shares_config takes the Volume URL and strips quobyte://."""
        drv = self._driver

        drv._load_shares_config()

        self.assertIn(self.TEST_QUOBYTE_VOLUME_WITHOUT_PROTOCOL, drv.shares)

    def test_load_shares_config_without_protocol(self):
        """Same as test_load_shares_config, but URL is without quobyte://."""
        drv = self._driver

        drv.configuration.quobyte_volume_url = \
            self.TEST_QUOBYTE_VOLUME_WITHOUT_PROTOCOL

        drv._load_shares_config()

        self.assertIn(self.TEST_QUOBYTE_VOLUME_WITHOUT_PROTOCOL, drv.shares)

    def test_ensure_share_mounted(self):
        """_ensure_share_mounted simple use case."""
        with mock.patch.object(self._driver, '_get_mount_point_for_share') as \
                mock_get_mount_point, \
                mock.patch.object(self._driver, '_mount_quobyte') as \
                mock_mount:
            drv = self._driver
            drv._ensure_share_mounted(self.TEST_QUOBYTE_VOLUME)

            mock_get_mount_point.assert_called_once_with(
                self.TEST_QUOBYTE_VOLUME)
            mock_mount.assert_called_once_with(
                self.TEST_QUOBYTE_VOLUME_WITHOUT_PROTOCOL,
                mock_get_mount_point.return_value,
                ensure=True)

    def test_ensure_shares_mounted_should_save_mounting_successfully(self):
        """_ensure_shares_mounted should save share if mounted with success."""
        with mock.patch.object(self._driver, '_ensure_share_mounted') \
                as mock_ensure_share_mounted:
            drv = self._driver

            drv._ensure_shares_mounted()

            mock_ensure_share_mounted.assert_called_once_with(
                self.TEST_QUOBYTE_VOLUME_WITHOUT_PROTOCOL)
            self.assertIn(self.TEST_QUOBYTE_VOLUME_WITHOUT_PROTOCOL,
                          drv._mounted_shares)

    def test_ensure_shares_mounted_should_not_save_mounting_with_error(self):
        """_ensure_shares_mounted should not save if mount raised an error."""
        with mock.patch.object(self._driver, '_ensure_share_mounted') \
                as mock_ensure_share_mounted:
            drv = self._driver

            mock_ensure_share_mounted.side_effect = Exception()

            drv._ensure_shares_mounted()

            mock_ensure_share_mounted.assert_called_once_with(
                self.TEST_QUOBYTE_VOLUME_WITHOUT_PROTOCOL)
            self.assertEqual(1, len(drv.shares))
            self.assertEqual(0, len(drv._mounted_shares))

    @mock.patch.object(quobyte.QuobyteDriver, "set_nas_security_options")
    def test_do_setup(self, qb_snso_mock):
        """do_setup runs successfully."""
        drv = self._driver

        drv.do_setup(mock.create_autospec(context.RequestContext))

        qb_snso_mock.assert_called_once_with(is_new_cinder_install=mock.ANY)

    @mock.patch.object(quobyte.QuobyteDriver, "set_nas_security_options")
    def test_do_setup_overlay(self, qb_snso_mock):
        """do_setup runs successfully."""
        drv = self._driver
        drv.configuration.quobyte_qcow2_volumes = True
        drv.configuration.quobyte_overlay_volumes = True
        drv.configuration.quobyte_volume_from_snapshot_cache = True

        drv.do_setup(mock.create_autospec(context.RequestContext))

        qb_snso_mock.assert_called_once_with(is_new_cinder_install=mock.ANY)
        self.assertTrue(drv.configuration.quobyte_overlay_volumes)

    @mock.patch.object(quobyte.QuobyteDriver, "set_nas_security_options")
    def test_do_setup_no_overlay(self, qb_snso_mock):
        """do_setup runs successfully."""
        drv = self._driver
        drv.configuration.quobyte_overlay_volumes = True
        drv.configuration.quobyte_volume_from_snapshot_cache = True
        drv.configuration.quobyte_qcow2_volumes = False

        drv.do_setup(mock.create_autospec(context.RequestContext))

        qb_snso_mock.assert_called_once_with(is_new_cinder_install=mock.ANY)
        self.assertFalse(drv.configuration.quobyte_overlay_volumes)

    def test_check_for_setup_error_throws_quobyte_volume_url_not_set(self):
        """check_for_setup_error throws if 'quobyte_volume_url' is not set."""
        drv = self._driver

        drv.configuration.quobyte_volume_url = None

        self.assertRaisesAndMessageMatches(exception.VolumeDriverException,
                                           'no Quobyte volume configured',
                                           drv.check_for_setup_error)

    def test_check_for_setup_error_throws_client_not_installed(self):
        """check_for_setup_error throws if client is not installed."""
        drv = self._driver
        drv._execute = mock.Mock(side_effect=OSError
                                 (errno.ENOENT, 'No such file or directory'))

        self.assertRaisesAndMessageMatches(exception.VolumeDriverException,
                                           'mount.quobyte is not installed',
                                           drv.check_for_setup_error)
        drv._execute.assert_called_once_with('mount.quobyte',
                                             check_exit_code=False,
                                             run_as_root=False)

    def test_check_for_setup_error_throws_client_not_executable(self):
        """check_for_setup_error throws if client cannot be executed."""
        drv = self._driver

        drv._execute = mock.Mock(side_effect=OSError
                                 (errno.EPERM, 'Operation not permitted'))

        self.assertRaisesAndMessageMatches(OSError,
                                           'Operation not permitted',
                                           drv.check_for_setup_error)
        drv._execute.assert_called_once_with('mount.quobyte',
                                             check_exit_code=False,
                                             run_as_root=False)

    def test_find_share_should_throw_error_if_there_is_no_mounted_shares(self):
        """_find_share should throw error if there is no mounted share."""
        drv = self._driver

        drv._mounted_shares = []

        self.assertRaises(exception.NotFound,
                          drv._find_share,
                          self._simple_volume())

    def test_find_share(self):
        """_find_share simple use case."""
        drv = self._driver

        drv._mounted_shares = [self.TEST_QUOBYTE_VOLUME]

        self.assertEqual(self.TEST_QUOBYTE_VOLUME,
                         drv._find_share(self._simple_volume()))

    def test_find_share_does_not_throw_error_if_there_isnt_enough_space(self):
        """_find_share intentionally does not throw when no space is left."""
        with mock.patch.object(self._driver, '_get_available_capacity') \
                as mock_get_available_capacity:
            drv = self._driver

            df_size = 2620544
            df_avail = 0
            mock_get_available_capacity.return_value = (df_avail, df_size)

            drv._mounted_shares = [self.TEST_QUOBYTE_VOLUME]

            self.assertEqual(self.TEST_QUOBYTE_VOLUME,
                             drv._find_share(self._simple_volume()))

            # The current implementation does not call _get_available_capacity.
            # Future ones might do and therefore we mocked it.
            self.assertGreaterEqual(mock_get_available_capacity.call_count, 0)

    def _simple_volume(self, **kwargs):
        updates = {'id': self.VOLUME_UUID,
                   'provider_location': self.TEST_QUOBYTE_VOLUME,
                   'display_name': 'volume-%s' % self.VOLUME_UUID,
                   'name': 'volume-%s' % self.VOLUME_UUID,
                   'size': 10,
                   'status': 'available'}

        updates.update(kwargs)
        if 'display_name' not in updates:
            updates['display_name'] = 'volume-%s' % updates['id']

        return fake_volume.fake_volume_obj(self.context, **updates)

    def test_create_sparsed_volume(self):
        drv = self._driver
        volume = self._simple_volume()

        drv._create_sparsed_file = mock.Mock()
        drv._set_rw_permissions_for_all = mock.Mock()

        drv._do_create_volume(volume)
        drv._create_sparsed_file.assert_called_once_with(mock.ANY, mock.ANY)
        drv._set_rw_permissions_for_all.assert_called_once_with(mock.ANY)

    def test_create_nonsparsed_volume(self):
        drv = self._driver
        volume = self._simple_volume()

        old_value = self._configuration.quobyte_sparsed_volumes
        self._configuration.quobyte_sparsed_volumes = False

        drv._create_regular_file = mock.Mock()
        drv._set_rw_permissions_for_all = mock.Mock()

        drv._do_create_volume(volume)
        drv._create_regular_file.assert_called_once_with(mock.ANY, mock.ANY)
        drv._set_rw_permissions_for_all.assert_called_once_with(mock.ANY)

        self._configuration.quobyte_sparsed_volumes = old_value

    def test_create_qcow2_volume(self):
        drv = self._driver

        volume = self._simple_volume()
        old_value = self._configuration.quobyte_qcow2_volumes
        self._configuration.quobyte_qcow2_volumes = True

        drv._execute = mock.Mock()

        hashed = drv._get_hash_str(volume['provider_location'])
        path = '%s/%s/volume-%s' % (self.TEST_MNT_POINT_BASE,
                                    hashed,
                                    self.VOLUME_UUID)

        drv._do_create_volume(volume)

        assert_calls = [mock.call('qemu-img', 'create', '-f', 'qcow2',
                                  '-o', 'preallocation=metadata', path,
                                  str(volume['size'] * units.Gi),
                                  run_as_root=self._driver._execute_as_root),
                        mock.call('chmod', 'ugo+rw', path,
                                  run_as_root=self._driver._execute_as_root)]
        drv._execute.assert_has_calls(assert_calls)

        self._configuration.quobyte_qcow2_volumes = old_value

    def test_create_volume_should_ensure_quobyte_mounted(self):
        """create_volume ensures shares provided in config are mounted."""
        drv = self._driver

        drv.LOG = mock.Mock()
        drv._find_share = mock.Mock()
        drv._find_share.return_value = self.TEST_QUOBYTE_VOLUME
        drv._do_create_volume = mock.Mock()
        drv._ensure_shares_mounted = mock.Mock()

        volume = self._simple_volume(size=self.TEST_SIZE_IN_GB)
        drv.create_volume(volume)

        drv._find_share.assert_called_once_with(mock.ANY)
        drv._do_create_volume.assert_called_once_with(volume)
        drv._ensure_shares_mounted.assert_called_once_with()

    def test_create_volume_should_return_provider_location(self):
        """create_volume should return provider_location with found share."""
        drv = self._driver

        drv.LOG = mock.Mock()
        drv._ensure_shares_mounted = mock.Mock()
        drv._do_create_volume = mock.Mock()
        drv._find_share = mock.Mock(return_value=self.TEST_QUOBYTE_VOLUME)

        volume = self._simple_volume(size=self.TEST_SIZE_IN_GB)
        result = drv.create_volume(volume)
        self.assertEqual(self.TEST_QUOBYTE_VOLUME, result['provider_location'])

        drv._do_create_volume.assert_called_once_with(volume)
        drv._ensure_shares_mounted.assert_called_once_with()
        drv._find_share.assert_called_once_with(volume)

    @mock.patch('oslo_utils.fileutils.delete_if_exists')
    def test_delete_volume(self, mock_delete_if_exists):
        volume = self._simple_volume()
        volume_filename = 'volume-%s' % self.VOLUME_UUID
        volume_path = '%s/%s' % (self.TEST_MNT_POINT, volume_filename)
        info_file = volume_path + '.info'

        with mock.patch.object(self._driver, '_ensure_share_mounted') as \
                mock_ensure_share_mounted, \
                mock.patch.object(self._driver, '_local_volume_dir') as \
                mock_local_volume_dir, \
                mock.patch.object(self._driver,
                                  'get_active_image_from_info') as \
                mock_active_image_from_info, \
                mock.patch.object(self._driver, '_execute') as \
                mock_execute, \
                mock.patch.object(self._driver, '_local_path_volume') as \
                mock_local_path_volume, \
                mock.patch.object(self._driver, '_local_path_volume_info') as \
                mock_local_path_volume_info:
            self._driver._qemu_img_info = mock.Mock()
            self._driver._qemu_img_info.return_value = mock.Mock()
            self._driver._qemu_img_info.return_value.backing_file = None
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
                                                 run_as_root=
                                                 self._driver._execute_as_root)
            mock_local_path_volume_info.assert_called_once_with(volume)
            mock_local_path_volume.assert_called_once_with(volume)
            mock_delete_if_exists.assert_any_call(volume_path)
            mock_delete_if_exists.assert_any_call(info_file)

    @mock.patch.object(os, 'access', return_value=True)
    @mock.patch('oslo_utils.fileutils.delete_if_exists')
    def test_delete_volume_backing_file(self, mock_delete_if_exists,
                                        os_acc_mock):
        drv = self._driver
        volume = self._simple_volume()
        volume_filename = 'volume-%s' % self.VOLUME_UUID
        volume_path = '%s/%s' % (self.TEST_MNT_POINT, volume_filename)
        info_file = volume_path + '.info'
        drv._ensure_share_mounted = mock.Mock()
        drv._local_volume_dir = mock.Mock()
        drv._local_volume_dir.return_value = self.TEST_MNT_POINT
        drv.get_active_image_from_info = mock.Mock()
        drv.get_active_image_from_info.return_value = volume_filename
        drv._qemu_img_info = mock.Mock()
        drv._qemu_img_info.return_value = mock.Mock()
        drv._qemu_img_info.return_value.backing_file = os.path.join(
            drv.QUOBYTE_VOLUME_SNAP_CACHE_DIR_NAME, "cached_volume_file")
        drv._remove_from_vol_cache = mock.Mock()
        drv._execute = mock.Mock()
        drv._local_path_volume = mock.Mock()
        drv._local_path_volume.return_value = volume_path
        drv._local_path_volume_info = mock.Mock()
        drv._local_path_volume_info.return_value = info_file

        drv.delete_volume(volume)

        drv._ensure_share_mounted.assert_called_once_with(
            volume['provider_location'])
        drv._local_volume_dir.assert_called_once_with(volume)
        drv.get_active_image_from_info.assert_called_once_with(volume)
        drv._qemu_img_info.assert_called_once_with(
            drv.local_path(volume), drv.get_active_image_from_info())
        drv._remove_from_vol_cache.assert_called_once_with(
            drv._qemu_img_info().backing_file, ".child-" + volume.id, volume)
        drv._execute.assert_called_once_with('rm', '-f', volume_path,
                                             run_as_root=
                                             self._driver._execute_as_root)
        drv._local_path_volume.assert_called_once_with(volume)
        drv._local_path_volume_info.assert_called_once_with(volume)
        mock_delete_if_exists.assert_any_call(volume_path)
        mock_delete_if_exists.assert_any_call(info_file)
        os_acc_mock.assert_called_once_with(drv._local_path_volume(volume),
                                            os.F_OK)

    @mock.patch.object(os, 'access', return_value=True)
    def test_delete_should_ensure_share_mounted(self, os_acc_mock):
        """delete_volume should ensure that corresponding share is mounted."""
        drv = self._driver
        drv._execute = mock.Mock()
        drv._qemu_img_info = mock.Mock()
        drv._qemu_img_info.return_value = mock.Mock()
        drv._qemu_img_info.return_value.backing_file = "/virtual/test/file"
        volume = self._simple_volume(display_name='volume-123')
        drv._ensure_share_mounted = mock.Mock()
        drv._remove_from_vol_cache = mock.Mock()

        drv.delete_volume(volume)

        (drv._ensure_share_mounted.
         assert_called_once_with(self.TEST_QUOBYTE_VOLUME))
        drv._qemu_img_info.assert_called_once_with(
            drv._local_path_volume(volume),
            drv.get_active_image_from_info(volume))
        # backing file is not in cache, no cache cleanup:
        self.assertFalse(drv._remove_from_vol_cache.called)
        drv._execute.assert_called_once_with('rm', '-f',
                                             drv.local_path(volume),
                                             run_as_root=False)
        os_acc_mock.assert_called_once_with(drv._local_path_volume(volume),
                                            os.F_OK)

    def test_delete_should_not_delete_if_provider_location_not_provided(self):
        """delete_volume shouldn't delete if provider_location missed."""
        drv = self._driver

        drv._ensure_share_mounted = mock.Mock()
        drv._execute = mock.Mock()

        volume = self._simple_volume(display_name='volume-123',
                                     provider_location=None)

        drv.delete_volume(volume)

        drv._ensure_share_mounted.assert_not_called()
        drv._execute.assert_not_called()

    @ddt.data(True, False)
    @mock.patch.object(remotefs.RemoteFSSnapDriverDistributed,
                       "_is_volume_attached")
    def test_extend_volume(self, is_attached, mock_remote_attached):
        drv = self._driver

        volume = self._simple_volume()

        volume_path = '%s/%s/volume-%s' % (self.TEST_MNT_POINT_BASE,
                                           drv._get_hash_str(
                                               self.TEST_QUOBYTE_VOLUME),
                                           self.VOLUME_UUID)

        qemu_img_info_output = """image: volume-%s
        file format: qcow2
        virtual size: 1.0G (1073741824 bytes)
        disk size: 473K
        """ % self.VOLUME_UUID

        img_info = imageutils.QemuImgInfo(qemu_img_info_output)

        image_utils.qemu_img_info = mock.Mock(return_value=img_info)
        image_utils.resize_image = mock.Mock()

        mock_remote_attached.return_value = is_attached

        if is_attached:
            self.assertRaises(exception.ExtendVolumeError, drv.extend_volume,
                              volume, 3)
        else:
            drv.extend_volume(volume, 3)

            image_utils.qemu_img_info.assert_called_once_with(volume_path,
                                                              force_share=True,
                                                              run_as_root=False
                                                              )
            image_utils.resize_image.assert_called_once_with(volume_path, 3)

    def test_copy_volume_from_snapshot(self):
        drv = self._driver

        # lots of test vars to be prepared at first
        dest_volume = self._simple_volume(
            id='c1073000-0000-0000-0000-0000000c1073')
        src_volume = self._simple_volume()

        vol_dir = os.path.join(self.TEST_MNT_POINT_BASE,
                               drv._get_hash_str(self.TEST_QUOBYTE_VOLUME))
        src_vol_path = os.path.join(vol_dir, src_volume['name'])
        dest_vol_path = os.path.join(vol_dir, dest_volume['name'])
        info_path = os.path.join(vol_dir, src_volume['name']) + '.info'

        snapshot = self._get_fake_snapshot(src_volume)

        snap_file = dest_volume['name'] + '.' + snapshot['id']
        snap_path = os.path.join(vol_dir, snap_file)

        size = dest_volume['size']

        qemu_img_output = """image: %s
        file format: raw
        virtual size: 1.0G (1073741824 bytes)
        disk size: 173K
        backing file: %s
        """ % (snap_file, src_volume['name'])
        img_info = imageutils.QemuImgInfo(qemu_img_output)

        # mocking and testing starts here
        image_utils.convert_image = mock.Mock()
        drv._read_info_file = mock.Mock(return_value=
                                        {'active': snap_file,
                                         snapshot['id']: snap_file})
        image_utils.qemu_img_info = mock.Mock(return_value=img_info)
        drv._set_rw_permissions = mock.Mock()

        drv._copy_volume_from_snapshot(snapshot, dest_volume, size)

        drv._read_info_file.assert_called_once_with(info_path)
        image_utils.qemu_img_info.assert_called_once_with(snap_path,
                                                          force_share=True,
                                                          run_as_root=False)
        (image_utils.convert_image.
         assert_called_once_with(src_vol_path,
                                 dest_vol_path,
                                 'raw',
                                 run_as_root=self._driver._execute_as_root))
        drv._set_rw_permissions.assert_called_once_with(dest_vol_path)

    @mock.patch.object(quobyte.QuobyteDriver, "_fallocate_file")
    @mock.patch.object(os, "access", return_value=True)
    def test_copy_volume_from_snapshot_cached(self, os_ac_mock,
                                              qb_falloc_mock):
        drv = self._driver
        drv.configuration.quobyte_volume_from_snapshot_cache = True

        # lots of test vars to be prepared at first
        dest_volume = self._simple_volume(
            id='c1073000-0000-0000-0000-0000000c1073')
        src_volume = self._simple_volume()

        vol_dir = os.path.join(self.TEST_MNT_POINT_BASE,
                               drv._get_hash_str(self.TEST_QUOBYTE_VOLUME))
        dest_vol_path = os.path.join(vol_dir, dest_volume['name'])
        info_path = os.path.join(vol_dir, src_volume['name']) + '.info'

        snapshot = self._get_fake_snapshot(src_volume)

        snap_file = dest_volume['name'] + '.' + snapshot['id']
        snap_path = os.path.join(vol_dir, snap_file)
        cache_path = os.path.join(vol_dir,
                                  drv.QUOBYTE_VOLUME_SNAP_CACHE_DIR_NAME,
                                  snapshot['id'])

        size = dest_volume['size']

        qemu_img_output = """image: %s
        file format: raw
        virtual size: 1.0G (1073741824 bytes)
        disk size: 173K
        backing file: %s
        """ % (snap_file, src_volume['name'])
        img_info = imageutils.QemuImgInfo(qemu_img_output)

        # mocking and testing starts here
        image_utils.convert_image = mock.Mock()
        drv._read_info_file = mock.Mock(return_value=
                                        {'active': snap_file,
                                         snapshot['id']: snap_file})
        image_utils.qemu_img_info = mock.Mock(return_value=img_info)
        drv._set_rw_permissions = mock.Mock()
        shutil.copyfile = mock.Mock()

        drv._copy_volume_from_snapshot(snapshot, dest_volume, size)

        drv._read_info_file.assert_called_once_with(info_path)
        image_utils.qemu_img_info.assert_called_once_with(snap_path,
                                                          force_share=True,
                                                          run_as_root=False)
        self.assertFalse(image_utils.convert_image.called,
                         ("_convert_image was called but should not have been")
                         )
        os_ac_mock.assert_called_once_with(
            drv._local_volume_from_snap_cache_path(snapshot), os.F_OK)
        qb_falloc_mock.assert_called_once_with(dest_vol_path, size)
        shutil.copyfile.assert_called_once_with(cache_path, dest_vol_path)
        drv._set_rw_permissions.assert_called_once_with(dest_vol_path)

    @mock.patch.object(os, "symlink")
    @mock.patch.object(os, "access", return_value=False)
    def test_copy_volume_from_snapshot_not_cached_overlay(self, os_ac_mock,
                                                          os_sl_mock):
        drv = self._driver
        drv.configuration.quobyte_qcow2_volumes = True
        drv.configuration.quobyte_volume_from_snapshot_cache = True
        drv.configuration.quobyte_overlay_volumes = True

        # lots of test vars to be prepared at first
        dest_volume = self._simple_volume(
            id='c1073000-0000-0000-0000-0000000c1073')
        src_volume = self._simple_volume()
        vol_dir = os.path.join(self.TEST_MNT_POINT_BASE,
                               drv._get_hash_str(self.TEST_QUOBYTE_VOLUME))
        src_vol_path = os.path.join(vol_dir, src_volume['name'])

        vol_dir = os.path.join(self.TEST_MNT_POINT_BASE,
                               drv._get_hash_str(self.TEST_QUOBYTE_VOLUME))
        dest_vol_path = os.path.join(vol_dir, dest_volume['name'])
        info_path = os.path.join(vol_dir, src_volume['name']) + '.info'

        snapshot = self._get_fake_snapshot(src_volume)

        snap_file = dest_volume['name'] + '.' + snapshot['id']
        snap_path = os.path.join(vol_dir, snap_file)

        size = dest_volume['size']

        qemu_img_output = """image: %s
        file format: raw
        virtual size: 1.0G (1073741824 bytes)
        disk size: 173K
        backing file: %s
        """ % (snap_file, src_volume['name'])
        img_info = imageutils.QemuImgInfo(qemu_img_output)

        # mocking and testing starts here
        image_utils.convert_image = mock.Mock()
        drv._read_info_file = mock.Mock(return_value=
                                        {'active': snap_file,
                                         snapshot['id']: snap_file})
        image_utils.qemu_img_info = mock.Mock(return_value=img_info)
        drv._set_rw_permissions = mock.Mock()
        drv._create_overlay_volume_from_snapshot = mock.Mock()

        drv._copy_volume_from_snapshot(snapshot, dest_volume, size)

        drv._read_info_file.assert_called_once_with(info_path)
        os_ac_mock.assert_called_once_with(
            drv._local_volume_from_snap_cache_path(snapshot), os.F_OK)
        image_utils.qemu_img_info.assert_called_once_with(snap_path,
                                                          force_share=True,
                                                          run_as_root=False)
        (image_utils.convert_image.
         assert_called_once_with(
             src_vol_path,
             drv._local_volume_from_snap_cache_path(snapshot), 'qcow2',
             run_as_root=self._driver._execute_as_root))
        os_sl_mock.assert_called_once_with(
            src_vol_path,
            drv._local_volume_from_snap_cache_path(snapshot) + '.parent-'
            + snapshot.id)
        drv._create_overlay_volume_from_snapshot.assert_called_once_with(
            dest_volume, snapshot, size, 'qcow2')
        drv._set_rw_permissions.assert_called_once_with(dest_vol_path)

    @mock.patch.object(quobyte.QuobyteDriver, "_fallocate_file")
    def test_copy_volume_from_snapshot_not_cached(self, qb_falloc_mock):
        drv = self._driver
        drv.configuration.quobyte_volume_from_snapshot_cache = True

        # lots of test vars to be prepared at first
        dest_volume = self._simple_volume(
            id='c1073000-0000-0000-0000-0000000c1073')
        src_volume = self._simple_volume()

        vol_dir = os.path.join(self.TEST_MNT_POINT_BASE,
                               drv._get_hash_str(self.TEST_QUOBYTE_VOLUME))
        src_vol_path = os.path.join(vol_dir, src_volume['name'])
        dest_vol_path = os.path.join(vol_dir, dest_volume['name'])
        info_path = os.path.join(vol_dir, src_volume['name']) + '.info'

        snapshot = self._get_fake_snapshot(src_volume)

        snap_file = dest_volume['name'] + '.' + snapshot['id']
        snap_path = os.path.join(vol_dir, snap_file)
        cache_path = os.path.join(vol_dir,
                                  drv.QUOBYTE_VOLUME_SNAP_CACHE_DIR_NAME,
                                  snapshot['id'])

        size = dest_volume['size']

        qemu_img_output = """image: %s
        file format: raw
        virtual size: 1.0G (1073741824 bytes)
        disk size: 173K
        backing file: %s
        """ % (snap_file, src_volume['name'])
        img_info = imageutils.QemuImgInfo(qemu_img_output)

        # mocking and testing starts here
        image_utils.convert_image = mock.Mock()
        drv._read_info_file = mock.Mock(return_value=
                                        {'active': snap_file,
                                         snapshot['id']: snap_file})
        image_utils.qemu_img_info = mock.Mock(return_value=img_info)
        drv._set_rw_permissions = mock.Mock()
        shutil.copyfile = mock.Mock()

        drv._copy_volume_from_snapshot(snapshot, dest_volume, size)

        drv._read_info_file.assert_called_once_with(info_path)
        image_utils.qemu_img_info.assert_called_once_with(snap_path,
                                                          force_share=True,
                                                          run_as_root=False)
        (image_utils.convert_image.
         assert_called_once_with(
             src_vol_path,
             drv._local_volume_from_snap_cache_path(snapshot), 'raw',
             run_as_root=self._driver._execute_as_root))
        qb_falloc_mock.assert_called_once_with(dest_vol_path, size)
        shutil.copyfile.assert_called_once_with(cache_path, dest_vol_path)
        drv._set_rw_permissions.assert_called_once_with(dest_vol_path)

    @ddt.data(['available', True], ['backing-up', True],
              ['creating', False], ['deleting', False])
    @ddt.unpack
    def test_create_volume_from_snapshot(self, state, should_work):
        drv = self._driver

        src_volume = self._simple_volume()

        snap_ref = fake_snapshot.fake_snapshot_obj(
            self.context,
            volume_name=src_volume.name,
            display_name='clone-snap-%s' % src_volume.id,
            volume_size=src_volume.size,
            volume_id=src_volume.id,
            id=self.SNAP_UUID,
            status=state)
        snap_ref.volume = src_volume

        new_volume = self._simple_volume(size=snap_ref.volume_size)

        drv._ensure_shares_mounted = mock.Mock()
        drv._find_share = mock.Mock(return_value=self.TEST_QUOBYTE_VOLUME)
        drv._copy_volume_from_snapshot = mock.Mock()

        if should_work:
            drv.create_volume_from_snapshot(new_volume, snap_ref)

            drv._ensure_shares_mounted.assert_called_once_with()
            drv._find_share.assert_called_once_with(new_volume)
            (drv._copy_volume_from_snapshot.
             assert_called_once_with(snap_ref, new_volume, new_volume['size']))
        else:
            self.assertRaises(exception.InvalidSnapshot,
                              drv.create_volume_from_snapshot,
                              new_volume,
                              snap_ref)

    def test_initialize_connection(self):
        drv = self._driver

        volume = self._simple_volume()
        vol_dir = os.path.join(self.TEST_MNT_POINT_BASE,
                               drv._get_hash_str(self.TEST_QUOBYTE_VOLUME))
        vol_path = os.path.join(vol_dir, volume['name'])

        qemu_img_output = """image: %s
        file format: raw
        virtual size: 1.0G (1073741824 bytes)
        disk size: 173K
        """ % volume['name']
        img_info = imageutils.QemuImgInfo(qemu_img_output)

        drv.get_active_image_from_info = mock.Mock(return_value=volume['name'])
        image_utils.qemu_img_info = mock.Mock(return_value=img_info)

        conn_info = drv.initialize_connection(volume, None)

        drv.get_active_image_from_info.assert_called_once_with(volume)
        image_utils.qemu_img_info.assert_called_once_with(vol_path,
                                                          force_share=True,
                                                          run_as_root=False)

        self.assertEqual('raw', conn_info['data']['format'])
        self.assertEqual('quobyte', conn_info['driver_volume_type'])
        self.assertEqual(volume['name'], conn_info['data']['name'])
        self.assertEqual(self.TEST_MNT_POINT_BASE,
                         conn_info['mount_point_base'])

    @mock.patch('cinder.db.volume_glance_metadata_get', return_value={})
    def test_copy_volume_to_image_raw_image(self, vol_glance_metadata):
        drv = self._driver

        volume_type_id = db.volume_type_create(
            self.context, {'name': 'quo_type', 'extra_specs': {}}).get('id')
        volume = self._simple_volume(volume_type_id=volume_type_id)
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
            mock_qemu_img_info.assert_called_once_with(volume_path,
                                                       force_share=True,
                                                       run_as_root=False)
            mock_upload_volume.assert_called_once_with(
                mock.ANY, mock.ANY, mock.ANY, upload_path, run_as_root=False,
                store_id=None, base_image_ref=None, compress=True,
                volume_format='raw')
            self.assertTrue(mock_create_temporary_file.called)

    @mock.patch('cinder.db.volume_glance_metadata_get', return_value={})
    def test_copy_volume_to_image_qcow2_image(self, vol_glance_metadata):
        """Upload a qcow2 image file which has to be converted to raw first."""
        drv = self._driver

        volume_type_id = db.volume_type_create(
            self.context, {'name': 'quo_type', 'extra_specs': {}}).get('id')
        volume = self._simple_volume(volume_type_id=volume_type_id)
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
            mock_qemu_img_info.assert_called_once_with(volume_path,
                                                       force_share=True,
                                                       run_as_root=False)
            mock_convert_image.assert_called_once_with(
                volume_path, upload_path, 'raw', run_as_root=False)
            mock_upload_volume.assert_called_once_with(
                mock.ANY, mock.ANY, mock.ANY, upload_path, run_as_root=False,
                store_id=None, base_image_ref=None, compress=True,
                volume_format='raw')
            self.assertTrue(mock_create_temporary_file.called)

    @mock.patch('cinder.db.volume_glance_metadata_get', return_value={})
    def test_copy_volume_to_image_snapshot_exists(self, vol_glance_metadata):
        """Upload an active snapshot which has to be converted to raw first."""
        drv = self._driver

        volume_type_id = db.volume_type_create(
            self.context, {'name': 'quo_type', 'extra_specs': {}}).get('id')
        volume = self._simple_volume(volume_type_id=volume_type_id)
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
            mock_qemu_img_info.assert_called_once_with(volume_path,
                                                       force_share=True,
                                                       run_as_root=False)
            mock_convert_image.assert_called_once_with(
                volume_path, upload_path, 'raw', run_as_root=False)
            mock_upload_volume.assert_called_once_with(
                mock.ANY, mock.ANY, mock.ANY, upload_path, run_as_root=False,
                store_id=None, base_image_ref=None, compress=True,
                volume_format='raw')
            self.assertTrue(mock_create_temporary_file.called)

    def test_set_nas_security_options_default(self):
        drv = self._driver
        self.assertEqual("true", drv.configuration.nas_secure_file_operations)
        self.assertEqual("true",
                         drv.configuration.nas_secure_file_permissions)
        self.assertFalse(drv._execute_as_root)

    def test_set_nas_security_options_insecure(self):
        drv = self._driver
        drv.configuration.nas_secure_file_operations = "false"
        drv.configuration.nas_secure_file_permissions = "false"

        drv.set_nas_security_options(is_new_cinder_install=True)

        self.assertEqual("false",
                         drv.configuration.nas_secure_file_operations)
        self.assertEqual("false",
                         drv.configuration.nas_secure_file_permissions)
        self.assertTrue(drv._execute_as_root)

    def test_set_nas_security_options_explicitly_secure(self):
        drv = self._driver
        drv.configuration.nas_secure_file_operations = "true"
        drv.configuration.nas_secure_file_permissions = "true"

        drv.set_nas_security_options(is_new_cinder_install=True)

        self.assertEqual("true",
                         drv.configuration.nas_secure_file_operations)
        self.assertEqual("true",
                         drv.configuration.nas_secure_file_permissions)
        self.assertFalse(drv._execute_as_root)

    @mock.patch.object(psutil, "disk_partitions")
    @mock.patch.object(os, "stat")
    def test_validate_volume_all_good_prefix_val(self, stat_mock, part_mock):
        part_mock.return_value = self.get_mock_partitions()
        drv = self._driver

        def statMockCall(*args):
            if args[0] == self.TEST_MNT_POINT:
                stat_result = mock.Mock()
                stat_result.st_size = 0
                return stat_result
            return os.stat(args)
        stat_mock.side_effect = statMockCall

        drv._validate_volume(self.TEST_MNT_POINT)

        stat_mock.assert_called_once_with(self.TEST_MNT_POINT)
        part_mock.assert_called_once_with(all=True)

    @mock.patch.object(psutil, "disk_partitions")
    @mock.patch.object(os, "stat")
    def test_validate_volume_all_good_subtype_val(self, stat_mock, part_mock):
        part_mock.return_value = self.get_mock_partitions()
        part_mock.return_value[0].device = "not_quobyte"
        part_mock.return_value[0].fstype = "fuse.quobyte"
        drv = self._driver

        def statMockCall(*args):
            if args[0] == self.TEST_MNT_POINT:
                stat_result = mock.Mock()
                stat_result.st_size = 0
                return stat_result
            return os.stat(args)
        stat_mock.side_effect = statMockCall

        drv._validate_volume(self.TEST_MNT_POINT)

        stat_mock.assert_called_once_with(self.TEST_MNT_POINT)
        part_mock.assert_called_once_with(all=True)

    @mock.patch.object(psutil, "disk_partitions")
    @mock.patch.object(os, "stat")
    def test_validate_volume_mount_not_working(self, stat_mock, part_mock):
        part_mock.return_value = self.get_mock_partitions()
        drv = self._driver

        def statMockCall(*args):
            if args[0] == self.TEST_MNT_POINT:
                raise exception.VolumeDriverException()
        stat_mock.side_effect = [statMockCall, os.stat]

        self.assertRaises(
            exception.VolumeDriverException,
            drv._validate_volume,
            self.TEST_MNT_POINT)
        stat_mock.assert_called_once_with(self.TEST_MNT_POINT)
        part_mock.assert_called_once_with(all=True)

    @mock.patch.object(psutil, "disk_partitions")
    def test_validate_volume_no_mtab_entry(self, part_mock):
        part_mock.return_value = []  # no quobyte@ devices
        msg = ("Volume driver reported an error: "
               "No matching Quobyte mount entry for %(mpt)s"
               " could be found for validation in partition list."
               % {'mpt': self.TEST_MNT_POINT})

        self.assertRaisesAndMessageMatches(
            exception.VolumeDriverException,
            msg,
            self._driver._validate_volume,
            self.TEST_MNT_POINT)

    @mock.patch.object(psutil, "disk_partitions")
    def test_validate_volume_wrong_mount_type(self, part_mock):
        mypart = mock.Mock()
        mypart.device = "not-quobyte"
        mypart.mountpoint = self.TEST_MNT_POINT
        part_mock.return_value = [mypart]
        msg = ("Volume driver reported an error: "
               "The mount %(mpt)s is not a valid"
               " Quobyte volume according to partition list."
               % {'mpt': self.TEST_MNT_POINT})
        drv = self._driver

        self.assertRaisesAndMessageMatches(
            exception.VolumeDriverException,
            msg,
            drv._validate_volume,
            self.TEST_MNT_POINT)
        part_mock.assert_called_once_with(all=True)

    @mock.patch.object(psutil, "disk_partitions")
    def test_validate_volume_stale_mount(self, part_mock):
        part_mock.return_value = self.get_mock_partitions()
        drv = self._driver

        # As this uses a local fs the dir size is >0, raising an exception
        self.assertRaises(
            exception.VolumeDriverException,
            drv._validate_volume,
            self.TEST_MNT_POINT)
