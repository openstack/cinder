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
import six
import traceback

import mock
from oslo_concurrency import processutils as putils
from oslo_config import cfg
from oslo_utils import units

from cinder import context
from cinder import exception
from cinder.image import image_utils
from cinder.openstack.common import imageutils
from cinder import test
from cinder.volume import configuration as conf
from cinder.volume.drivers import quobyte


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


class QuobyteDriverTestCase(test.TestCase):
    """Test case for Quobyte driver."""

    TEST_QUOBYTE_VOLUME = 'quobyte://quobyte-host/openstack-volumes'
    TEST_QUOBYTE_VOLUME_WITHOUT_PROTOCOL = 'quobyte-host/openstack-volumes'
    TEST_SIZE_IN_GB = 1
    TEST_MNT_POINT = '/mnt/quobyte'
    TEST_MNT_POINT_BASE = '/mnt'
    TEST_LOCAL_PATH = '/mnt/quobyte/volume-123'
    TEST_FILE_NAME = 'test.txt'
    TEST_SHARES_CONFIG_FILE = '/etc/cinder/test-shares.conf'
    TEST_TMP_FILE = '/tmp/tempfile'
    VOLUME_UUID = 'abcdefab-cdef-abcd-efab-cdefabcdefab'
    SNAP_UUID = 'bacadaca-baca-daca-baca-dacadacadaca'
    SNAP_UUID_2 = 'bebedede-bebe-dede-bebe-dedebebedede'

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

        self._driver =\
            quobyte.QuobyteDriver(configuration=self._configuration,
                                  db=FakeDb())
        self._driver.shares = {}
        self._driver.set_nas_security_options(is_new_cinder_install=False)

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

    def test_local_path(self):
        """local_path common use case."""
        drv = self._driver

        volume = DumbVolume()
        volume['provider_location'] = self.TEST_QUOBYTE_VOLUME
        volume['name'] = 'volume-123'

        self.assertEqual(
            '/mnt/1331538734b757ed52d0e18c0a7210cd/volume-123',
            drv.local_path(volume))

    def test_mount_quobyte_should_mount_correctly(self):
        with mock.patch.object(self._driver, '_execute') as mock_execute, \
                mock.patch('cinder.volume.drivers.quobyte.QuobyteDriver'
                           '.read_proc_mount') as mock_open:
            # Content of /proc/mount (not mounted yet).
            mock_open.return_value = six.StringIO(
                "/dev/sda5 / ext4 rw,relatime,data=ordered 0 0")

            self._driver._mount_quobyte(self.TEST_QUOBYTE_VOLUME,
                                        self.TEST_MNT_POINT)

            mkdir_call = mock.call('mkdir', '-p', self.TEST_MNT_POINT)

            mount_call = mock.call(
                'mount.quobyte', self.TEST_QUOBYTE_VOLUME,
                self.TEST_MNT_POINT, run_as_root=False)

            getfattr_call = mock.call(
                'getfattr', '-n', 'quobyte.info', self.TEST_MNT_POINT,
                run_as_root=False)

            mock_execute.assert_has_calls(
                [mkdir_call, mount_call, getfattr_call], any_order=False)

    def test_mount_quobyte_already_mounted_detected_seen_in_proc_mount(self):
        with mock.patch.object(self._driver, '_execute') as mock_execute, \
                mock.patch('cinder.volume.drivers.quobyte.QuobyteDriver'
                           '.read_proc_mount') as mock_open:
            # Content of /proc/mount (already mounted).
            mock_open.return_value = six.StringIO(
                "quobyte@%s %s fuse rw,nosuid,nodev,noatime,user_id=1000"
                ",group_id=100,default_permissions,allow_other 0 0"
                % (self.TEST_QUOBYTE_VOLUME, self.TEST_MNT_POINT))

            self._driver._mount_quobyte(self.TEST_QUOBYTE_VOLUME,
                                        self.TEST_MNT_POINT)

            mock_execute.assert_called_once_with(
                'getfattr', '-n', 'quobyte.info', self.TEST_MNT_POINT,
                run_as_root=False)

    def test_mount_quobyte_should_suppress_and_log_already_mounted_error(self):
        """test_mount_quobyte_should_suppress_and_log_already_mounted_error

           Based on /proc/mount, the file system is not mounted yet. However,
           mount.quobyte returns with an 'already mounted' error. This is
           a last-resort safe-guard in case /proc/mount parsing was not
           successful.

           Because _mount_quobyte gets called with ensure=True, the error will
           be suppressed and logged instead.
        """
        with mock.patch.object(self._driver, '_execute') as mock_execute, \
                mock.patch('cinder.volume.drivers.quobyte.QuobyteDriver'
                           '.read_proc_mount') as mock_open, \
                mock.patch('cinder.volume.drivers.quobyte.LOG') as mock_LOG:
            # Content of /proc/mount (empty).
            mock_open.return_value = six.StringIO()
            mock_execute.side_effect = [None, putils.ProcessExecutionError(
                stderr='is busy or already mounted')]

            self._driver._mount_quobyte(self.TEST_QUOBYTE_VOLUME,
                                        self.TEST_MNT_POINT,
                                        ensure=True)

            mkdir_call = mock.call('mkdir', '-p', self.TEST_MNT_POINT)
            mount_call = mock.call(
                'mount.quobyte', self.TEST_QUOBYTE_VOLUME,
                self.TEST_MNT_POINT, run_as_root=False)
            mock_execute.assert_has_calls([mkdir_call, mount_call],
                                          any_order=False)

            mock_LOG.warning.assert_called_once_with('%s is already mounted',
                                                     self.TEST_QUOBYTE_VOLUME)

    def test_mount_quobyte_should_reraise_already_mounted_error(self):
        """test_mount_quobyte_should_reraise_already_mounted_error

        Like test_mount_quobyte_should_suppress_and_log_already_mounted_error
        but with ensure=False.
        """
        with mock.patch.object(self._driver, '_execute') as mock_execute, \
                mock.patch('cinder.volume.drivers.quobyte.QuobyteDriver'
                           '.read_proc_mount') as mock_open:
            mock_open.return_value = six.StringIO()
            mock_execute.side_effect = [
                None,  # mkdir
                putils.ProcessExecutionError(  # mount
                    stderr='is busy or already mounted')]

            self.assertRaises(putils.ProcessExecutionError,
                              self._driver._mount_quobyte,
                              self.TEST_QUOBYTE_VOLUME,
                              self.TEST_MNT_POINT,
                              ensure=False)

            mkdir_call = mock.call('mkdir', '-p', self.TEST_MNT_POINT)
            mount_call = mock.call(
                'mount.quobyte', self.TEST_QUOBYTE_VOLUME,
                self.TEST_MNT_POINT, run_as_root=False)
            mock_execute.assert_has_calls([mkdir_call, mount_call],
                                          any_order=False)

    def test_get_hash_str(self):
        """_get_hash_str should calculation correct value."""
        drv = self._driver

        self.assertEqual('1331538734b757ed52d0e18c0a7210cd',
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
                self.TEST_QUOBYTE_VOLUME,
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

    def test_do_setup(self):
        """do_setup runs successfully."""
        drv = self._driver
        drv.do_setup(mock.create_autospec(context.RequestContext))

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
                          self.TEST_SIZE_IN_GB)

    def test_find_share(self):
        """_find_share simple use case."""
        drv = self._driver

        drv._mounted_shares = [self.TEST_QUOBYTE_VOLUME]

        self.assertEqual(self.TEST_QUOBYTE_VOLUME,
                         drv._find_share(self.TEST_SIZE_IN_GB))

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
                             drv._find_share(self.TEST_SIZE_IN_GB))

            # The current implementation does not call _get_available_capacity.
            # Future ones might do and therefore we mocked it.
            self.assertGreaterEqual(mock_get_available_capacity.call_count, 0)

    def _simple_volume(self, uuid=None):
        volume = DumbVolume()
        volume['provider_location'] = self.TEST_QUOBYTE_VOLUME
        if uuid is None:
            volume['id'] = self.VOLUME_UUID
        else:
            volume['id'] = uuid
        # volume['name'] mirrors format from db/sqlalchemy/models.py
        volume['name'] = 'volume-%s' % volume['id']
        volume['size'] = 10
        volume['status'] = 'available'

        return volume

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
        drv._do_create_volume = mock.Mock()
        drv._ensure_shares_mounted = mock.Mock()

        volume = DumbVolume()
        volume['size'] = self.TEST_SIZE_IN_GB
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

        volume = DumbVolume()
        volume['size'] = self.TEST_SIZE_IN_GB
        result = drv.create_volume(volume)
        self.assertEqual(self.TEST_QUOBYTE_VOLUME, result['provider_location'])

        drv._do_create_volume.assert_called_once_with(volume)
        drv._ensure_shares_mounted.assert_called_once_with()
        drv._find_share.assert_called_once_with(self.TEST_SIZE_IN_GB)

    def test_create_cloned_volume(self):
        drv = self._driver

        drv._create_snapshot = mock.Mock()
        drv._copy_volume_from_snapshot = mock.Mock()
        drv._delete_snapshot = mock.Mock()

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

        drv._create_snapshot.assert_called_once_with(snap_ref)
        drv._copy_volume_from_snapshot.assert_called_once_with(snap_ref,
                                                               volume_ref,
                                                               volume['size'])
        drv._delete_snapshot.assert_called_once_with(mock.ANY)

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

    def test_delete_should_ensure_share_mounted(self):
        """delete_volume should ensure that corresponding share is mounted."""
        drv = self._driver

        drv._execute = mock.Mock()

        volume = DumbVolume()
        volume['name'] = 'volume-123'
        volume['provider_location'] = self.TEST_QUOBYTE_VOLUME

        drv._ensure_share_mounted = mock.Mock()

        drv.delete_volume(volume)

        (drv._ensure_share_mounted.
         assert_called_once_with(self.TEST_QUOBYTE_VOLUME))
        drv._execute.assert_called_once_with('rm', '-f',
                                             mock.ANY,
                                             run_as_root=False)

    def test_delete_should_not_delete_if_provider_location_not_provided(self):
        """delete_volume shouldn't delete if provider_location missed."""
        drv = self._driver

        drv._ensure_share_mounted = mock.Mock()
        drv._execute = mock.Mock()

        volume = DumbVolume()
        volume['name'] = 'volume-123'
        volume['provider_location'] = None

        drv.delete_volume(volume)

        assert not drv._ensure_share_mounted.called
        assert not drv._execute.called

    def test_extend_volume(self):
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

        drv.get_active_image_from_info = mock.Mock(return_value=volume['name'])
        image_utils.qemu_img_info = mock.Mock(return_value=img_info)
        image_utils.resize_image = mock.Mock()

        drv.extend_volume(volume, 3)

        drv.get_active_image_from_info.assert_called_once_with(volume)
        image_utils.qemu_img_info.assert_called_once_with(volume_path)
        image_utils.resize_image.assert_called_once_with(volume_path, 3)

    def test_copy_volume_from_snapshot(self):
        drv = self._driver

        # lots of test vars to be prepared at first
        dest_volume = self._simple_volume(
            'c1073000-0000-0000-0000-0000000c1073')
        src_volume = self._simple_volume()

        vol_dir = os.path.join(self.TEST_MNT_POINT_BASE,
                               drv._get_hash_str(self.TEST_QUOBYTE_VOLUME))
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
        drv._set_rw_permissions_for_all = mock.Mock()

        drv._copy_volume_from_snapshot(snapshot, dest_volume, size)

        drv._read_info_file.assert_called_once_with(info_path)
        image_utils.qemu_img_info.assert_called_once_with(snap_path)
        (image_utils.convert_image.
         assert_called_once_with(src_vol_path,
                                 dest_vol_path,
                                 'raw',
                                 run_as_root=self._driver._execute_as_root))
        drv._set_rw_permissions_for_all.assert_called_once_with(dest_vol_path)

    def test_create_volume_from_snapshot_status_not_available(self):
        """Expect an error when the snapshot's status is not 'available'."""
        drv = self._driver

        src_volume = self._simple_volume()
        snap_ref = {'volume_name': src_volume['name'],
                    'name': 'clone-snap-%s' % src_volume['id'],
                    'size': src_volume['size'],
                    'volume_size': src_volume['size'],
                    'volume_id': src_volume['id'],
                    'id': 'tmp-snap-%s' % src_volume['id'],
                    'volume': src_volume,
                    'status': 'error'}

        new_volume = DumbVolume()
        new_volume['size'] = snap_ref['size']

        self.assertRaises(exception.InvalidSnapshot,
                          drv.create_volume_from_snapshot,
                          new_volume,
                          snap_ref)

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

        drv._ensure_shares_mounted = mock.Mock()
        drv._find_share = mock.Mock(return_value=self.TEST_QUOBYTE_VOLUME)
        drv._do_create_volume = mock.Mock()
        drv._copy_volume_from_snapshot = mock.Mock()

        drv.create_volume_from_snapshot(new_volume, snap_ref)

        drv._ensure_shares_mounted.assert_called_once_with()
        drv._find_share.assert_called_once_with(new_volume['size'])
        drv._do_create_volume.assert_called_once_with(new_volume)
        (drv._copy_volume_from_snapshot.
         assert_called_once_with(snap_ref, new_volume, new_volume['size']))

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
        image_utils.qemu_img_info.assert_called_once_with(vol_path)

        self.assertEqual('raw', conn_info['data']['format'])
        self.assertEqual('quobyte', conn_info['driver_volume_type'])
        self.assertEqual(volume['name'], conn_info['data']['name'])
        self.assertEqual(self.TEST_MNT_POINT_BASE,
                         conn_info['mount_point_base'])

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
            self.assertTrue(mock_create_temporary_file.called)

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
            self.assertTrue(mock_create_temporary_file.called)

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
            self.assertTrue(mock_create_temporary_file.called)
