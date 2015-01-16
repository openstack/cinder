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

import contextlib
import errno
import os
import StringIO
import traceback

import mock
import mox as mox_lib
from mox import IgnoreArg
from mox import IsA
from mox import stubout
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
        self._mox = mox_lib.Mox()
        self._configuration = mox_lib.MockObject(conf.Configuration)
        self._configuration.append_config_values(mox_lib.IgnoreArg())
        self._configuration.quobyte_volume_url = \
            self.TEST_QUOBYTE_VOLUME
        self._configuration.quobyte_client_cfg = None
        self._configuration.quobyte_sparsed_volumes = True
        self._configuration.quobyte_qcow2_volumes = False
        self._configuration.quobyte_mount_point_base = \
            self.TEST_MNT_POINT_BASE

        self.stubs = stubout.StubOutForTesting()
        self._driver =\
            quobyte.QuobyteDriver(configuration=self._configuration,
                                  db=FakeDb())
        self._driver.shares = {}
        self._driver.set_nas_security_options(is_new_cinder_install=False)
        self.execute_as_root = False
        self.addCleanup(self._mox.UnsetStubs)

    def stub_out_not_replaying(self, obj, attr_name):
        attr_to_replace = getattr(obj, attr_name)
        stub = mox_lib.MockObject(attr_to_replace)
        self.stubs.Set(obj, attr_name, stub)

    def assertRaisesAndMessageMatches(
            self, excClass, msg, callableObj, *args, **kwargs):
        """Ensure that the specified exception was raised and its message
           includes the string 'msg'.
        """

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
        with contextlib.nested(
                mock.patch.object(self._driver, '_execute'),
                mock.patch('cinder.volume.drivers.quobyte.QuobyteDriver'
                           '.read_proc_mount'),
                mock.patch('xattr.getxattr')
        ) as (mock_execute, mock_open, mock_getxattr):
            # Content of /proc/mount (not mounted yet).
            mock_open.return_value = StringIO.StringIO(
                "/dev/sda5 / ext4 rw,relatime,data=ordered 0 0")

            self._driver._mount_quobyte(self.TEST_QUOBYTE_VOLUME,
                                        self.TEST_MNT_POINT)

            mkdir_call = mock.call('mkdir', '-p', self.TEST_MNT_POINT)

            mount_call = mock.call(
                'mount.quobyte', self.TEST_QUOBYTE_VOLUME,
                self.TEST_MNT_POINT, run_as_root=False)
            mock_execute.assert_has_calls([mkdir_call, mount_call],
                                          any_order=False)
            mock_getxattr.assert_called_once_with(self.TEST_MNT_POINT,
                                                  'quobyte.info')

    def test_mount_quobyte_already_mounted_detected_seen_in_proc_mount(self):
        with contextlib.nested(
                mock.patch.object(self._driver, '_execute'),
                mock.patch('cinder.volume.drivers.quobyte.QuobyteDriver'
                           '.read_proc_mount'),
                mock.patch('xattr.getxattr')
        ) as (mock_execute, mock_open, mock_getxattr):
            # Content of /proc/mount (already mounted).
            mock_open.return_value = StringIO.StringIO(
                "quobyte@%s %s fuse rw,nosuid,nodev,noatime,user_id=1000"
                ",group_id=100,default_permissions,allow_other 0 0"
                % (self.TEST_QUOBYTE_VOLUME, self.TEST_MNT_POINT))
            mock_getxattr.return_value = "non-empty string"

            self._driver._mount_quobyte(self.TEST_QUOBYTE_VOLUME,
                                        self.TEST_MNT_POINT)

            self.assertFalse(mock_execute.called)
            mock_getxattr.assert_called_once_with(self.TEST_MNT_POINT,
                                                  'quobyte.info')

    def test_mount_quobyte_should_suppress_and_log_already_mounted_error(self):
        """Based on /proc/mount, the file system is not mounted yet. However,
           mount.quobyte returns with an 'already mounted' error.
           This is a last-resort safe-guard in case /proc/mount parsing was not
           successful.

           Because _mount_quobyte gets called with ensure=True, the error will
           be suppressed and logged instead.
        """
        with contextlib.nested(
                mock.patch.object(self._driver, '_execute'),
                mock.patch('cinder.volume.drivers.quobyte.QuobyteDriver'
                           '.read_proc_mount'),
                mock.patch('cinder.volume.drivers.quobyte.LOG')
        ) as (mock_execute, mock_open, mock_LOG):
            # Content of /proc/mount (empty).
            mock_open.return_value = StringIO.StringIO()
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

            mock_LOG.warn.assert_called_once_with('%s is already mounted',
                                                  self.TEST_QUOBYTE_VOLUME)

    def test_mount_quobyte_should_reraise_already_mounted_error(self):
        """Same as
           test_mount_quobyte_should_suppress_and_log_already_mounted_error
           but with ensure=False.
        """
        with contextlib.nested(
                mock.patch.object(self._driver, '_execute'),
                mock.patch('cinder.volume.drivers.quobyte.QuobyteDriver'
                           '.read_proc_mount')
        ) as (mock_execute, mock_open):
            mock_open.return_value = StringIO.StringIO()
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
        mox = self._mox
        drv = self._driver

        df_total_size = 2620544
        df_avail = 1490560
        df_head = 'Filesystem 1K-blocks Used Available Use% Mounted on\n'
        df_data = 'quobyte@%s %d 996864 %d 41%% %s' % \
                  (self.TEST_QUOBYTE_VOLUME, df_total_size, df_avail,
                   self.TEST_MNT_POINT)
        df_output = df_head + df_data

        mox.StubOutWithMock(drv, '_get_mount_point_for_share')
        drv._get_mount_point_for_share(self.TEST_QUOBYTE_VOLUME).\
            AndReturn(self.TEST_MNT_POINT)

        mox.StubOutWithMock(drv, '_execute')
        drv._execute('df', '--portability', '--block-size', '1',
                     self.TEST_MNT_POINT,
                     run_as_root=self.execute_as_root).AndReturn((df_output,
                                                                  None))

        mox.ReplayAll()

        self.assertEqual((df_avail, df_total_size),
                         drv._get_available_capacity(self.TEST_QUOBYTE_VOLUME))

        mox.VerifyAll()

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
        """_load_shares_config only puts the Volume URL into shares and strips
           quobyte://.
        """
        drv = self._driver

        drv._load_shares_config()

        self.assertIn(self.TEST_QUOBYTE_VOLUME_WITHOUT_PROTOCOL, drv.shares)

    def test_load_shares_config_without_protocol(self):
        """Same as test_load_shares_config, but this time the URL was specified
           without quobyte:// in front.
        """
        drv = self._driver

        drv.configuration.quobyte_volume_url = \
            self.TEST_QUOBYTE_VOLUME_WITHOUT_PROTOCOL

        drv._load_shares_config()

        self.assertIn(self.TEST_QUOBYTE_VOLUME_WITHOUT_PROTOCOL, drv.shares)

    def test_ensure_share_mounted(self):
        """_ensure_share_mounted simple use case."""
        with contextlib.nested(
                mock.patch.object(self._driver, '_get_mount_point_for_share'),
                mock.patch.object(self._driver, '_mount_quobyte')
        ) as (mock_get_mount_point, mock_mount):
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
        drv.do_setup(IsA(context.RequestContext))

    def test_check_for_setup_error_throws_quobyte_volume_url_not_set(self):
        """check_for_setup_error throws if 'quobyte_volume_url' is not set."""
        drv = self._driver

        drv.configuration.quobyte_volume_url = None

        self.assertRaisesAndMessageMatches(exception.VolumeDriverException,
                                           'no Quobyte volume configured',
                                           drv.check_for_setup_error)

    def test_check_for_setup_error_throws_client_not_installed(self):
        """check_for_setup_error throws if client is not installed."""
        mox = self._mox
        drv = self._driver

        mox.StubOutWithMock(drv, '_execute')
        drv._execute('mount.quobyte', check_exit_code=False,
                     run_as_root=False).\
            AndRaise(OSError(errno.ENOENT, 'No such file or directory'))

        mox.ReplayAll()

        self.assertRaisesAndMessageMatches(exception.VolumeDriverException,
                                           'mount.quobyte is not installed',
                                           drv.check_for_setup_error)

        mox.VerifyAll()

    def test_check_for_setup_error_throws_client_not_executable(self):
        """check_for_setup_error throws if client cannot be executed."""
        mox = self._mox
        drv = self._driver

        mox.StubOutWithMock(drv, '_execute')
        drv._execute('mount.quobyte', check_exit_code=False,
                     run_as_root=False).\
            AndRaise(OSError(errno.EPERM, 'Operation not permitted'))

        mox.ReplayAll()

        self.assertRaisesAndMessageMatches(OSError,
                                           'Operation not permitted',
                                           drv.check_for_setup_error)

        mox.VerifyAll()

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
        """_find_share intentionally does not throw when df reports no
           available space left.
        """
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
        mox = self._mox
        drv = self._driver
        volume = self._simple_volume()

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

        old_value = self._configuration.quobyte_sparsed_volumes
        self._configuration.quobyte_sparsed_volumes = False

        mox.StubOutWithMock(drv, '_create_regular_file')
        mox.StubOutWithMock(drv, '_set_rw_permissions_for_all')

        drv._create_regular_file(IgnoreArg(), IgnoreArg())
        drv._set_rw_permissions_for_all(IgnoreArg())

        mox.ReplayAll()

        drv._do_create_volume(volume)

        mox.VerifyAll()

        self._configuration.quobyte_sparsed_volumes = old_value

    def test_create_qcow2_volume(self):
        (mox, drv) = self._mox, self._driver

        volume = self._simple_volume()
        old_value = self._configuration.quobyte_qcow2_volumes
        self._configuration.quobyte_qcow2_volumes = True

        mox.StubOutWithMock(drv, '_execute')

        hashed = drv._get_hash_str(volume['provider_location'])
        path = '%s/%s/volume-%s' % (self.TEST_MNT_POINT_BASE,
                                    hashed,
                                    self.VOLUME_UUID)

        drv._execute('qemu-img', 'create', '-f', 'qcow2',
                     '-o', 'preallocation=metadata', path,
                     str(volume['size'] * units.Gi),
                     run_as_root=self.execute_as_root)

        drv._execute('chmod', 'ugo+rw', path, run_as_root=self.execute_as_root)

        mox.ReplayAll()

        drv._do_create_volume(volume)

        mox.VerifyAll()

        self._configuration.quobyte_qcow2_volumes = old_value

    def test_create_volume_should_ensure_quobyte_mounted(self):
        """create_volume ensures shares provided in config are mounted."""
        mox = self._mox
        drv = self._driver

        self.stub_out_not_replaying(quobyte, 'LOG')
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

        self.stub_out_not_replaying(quobyte, 'LOG')
        self.stub_out_not_replaying(drv, '_ensure_shares_mounted')
        self.stub_out_not_replaying(drv, '_do_create_volume')

        mox.StubOutWithMock(drv, '_find_share')
        drv._find_share(self.TEST_SIZE_IN_GB).\
            AndReturn(self.TEST_QUOBYTE_VOLUME)

        mox.ReplayAll()

        volume = DumbVolume()
        volume['size'] = self.TEST_SIZE_IN_GB
        result = drv.create_volume(volume)
        self.assertEqual(self.TEST_QUOBYTE_VOLUME, result['provider_location'])

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
            mock_execute.assert_called_once_with(
                'rm', '-f', volume_path, run_as_root=self.execute_as_root)
            mock_local_path_volume_info.assert_called_once_with(volume)
            mock_local_path_volume.assert_called_once_with(volume)
            mock_delete_if_exists.assert_any_call(volume_path)
            mock_delete_if_exists.assert_any_call(info_file)

    def test_delete_should_ensure_share_mounted(self):
        """delete_volume should ensure that corresponding share is mounted."""
        mox = self._mox
        drv = self._driver

        self.stub_out_not_replaying(drv, '_execute')

        volume = DumbVolume()
        volume['name'] = 'volume-123'
        volume['provider_location'] = self.TEST_QUOBYTE_VOLUME

        mox.StubOutWithMock(drv, '_ensure_share_mounted')
        drv._ensure_share_mounted(self.TEST_QUOBYTE_VOLUME)

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

    def test_extend_volume(self):
        (mox, drv) = self._mox, self._driver

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

        image_utils.convert_image(src_vol_path,
                                  dest_vol_path,
                                  'raw',
                                  run_as_root=self.execute_as_root)

        drv._set_rw_permissions_for_all(dest_vol_path)

        mox.ReplayAll()

        drv._copy_volume_from_snapshot(snapshot, dest_volume, size)

        mox.VerifyAll()

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

        drv._find_share(new_volume['size']).AndReturn(self.TEST_QUOBYTE_VOLUME)

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
                               drv._get_hash_str(self.TEST_QUOBYTE_VOLUME))
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
        self.assertEqual(conn_info['driver_volume_type'], 'quobyte')
        self.assertEqual(conn_info['data']['name'], volume['name'])
        self.assertEqual(conn_info['mount_point_base'],
                         self.TEST_MNT_POINT_BASE)

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
