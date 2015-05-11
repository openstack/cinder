# Copyright 2011 OpenStack Foundation
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

"""Tests For miscellaneous util methods used with volume."""

import mock
from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_log import log as logging

from cinder import exception
from cinder import test
from cinder import utils
from cinder.volume import throttling
from cinder.volume import utils as volume_utils


LOG = logging.getLogger(__name__)

CONF = cfg.CONF


class NotifyUsageTestCase(test.TestCase):
    @mock.patch('cinder.volume.utils._usage_from_volume')
    @mock.patch('cinder.volume.utils.CONF')
    @mock.patch('cinder.volume.utils.rpc')
    def test_notify_about_volume_usage(self, mock_rpc, mock_conf, mock_usage):
        mock_conf.host = 'host1'
        output = volume_utils.notify_about_volume_usage(mock.sentinel.context,
                                                        mock.sentinel.volume,
                                                        'test_suffix')
        self.assertIsNone(output)
        mock_usage.assert_called_once_with(mock.sentinel.context,
                                           mock.sentinel.volume)
        mock_rpc.get_notifier.assert_called_once_with('volume', 'host1')
        mock_rpc.get_notifier.return_value.info.assert_called_once_with(
            mock.sentinel.context,
            'volume.test_suffix',
            mock_usage.return_value)

    @mock.patch('cinder.volume.utils._usage_from_volume')
    @mock.patch('cinder.volume.utils.CONF')
    @mock.patch('cinder.volume.utils.rpc')
    def test_notify_about_volume_usage_with_kwargs(self, mock_rpc, mock_conf,
                                                   mock_usage):
        mock_conf.host = 'host1'
        output = volume_utils.notify_about_volume_usage(
            mock.sentinel.context,
            mock.sentinel.volume,
            'test_suffix',
            extra_usage_info={'a': 'b', 'c': 'd'},
            host='host2')
        self.assertIsNone(output)
        mock_usage.assert_called_once_with(mock.sentinel.context,
                                           mock.sentinel.volume, a='b', c='d')
        mock_rpc.get_notifier.assert_called_once_with('volume', 'host2')
        mock_rpc.get_notifier.return_value.info.assert_called_once_with(
            mock.sentinel.context,
            'volume.test_suffix',
            mock_usage.return_value)

    @mock.patch('cinder.volume.utils._usage_from_volume')
    @mock.patch('cinder.volume.utils.CONF')
    @mock.patch('cinder.volume.utils.rpc')
    def test_notify_about_replication_usage(self, mock_rpc,
                                            mock_conf, mock_usage):
        mock_conf.host = 'host1'
        output = volume_utils.notify_about_replication_usage(
            mock.sentinel.context,
            mock.sentinel.volume,
            'test_suffix')
        self.assertIsNone(output)
        mock_usage.assert_called_once_with(mock.sentinel.context,
                                           mock.sentinel.volume)
        mock_rpc.get_notifier.assert_called_once_with('replication', 'host1')
        mock_rpc.get_notifier.return_value.info.assert_called_once_with(
            mock.sentinel.context,
            'replication.test_suffix',
            mock_usage.return_value)

    @mock.patch('cinder.volume.utils._usage_from_volume')
    @mock.patch('cinder.volume.utils.CONF')
    @mock.patch('cinder.volume.utils.rpc')
    def test_notify_about_replication_usage_with_kwargs(self, mock_rpc,
                                                        mock_conf, mock_usage):
        mock_conf.host = 'host1'
        output = volume_utils.notify_about_replication_usage(
            mock.sentinel.context,
            mock.sentinel.volume,
            'test_suffix',
            extra_usage_info={'a': 'b', 'c': 'd'},
            host='host2')
        self.assertIsNone(output)
        mock_usage.assert_called_once_with(mock.sentinel.context,
                                           mock.sentinel.volume,
                                           a='b', c='d')
        mock_rpc.get_notifier.assert_called_once_with('replication', 'host2')
        mock_rpc.get_notifier.return_value.info.assert_called_once_with(
            mock.sentinel.context,
            'replication.test_suffix',
            mock_usage.return_value)

    @mock.patch('cinder.volume.utils._usage_from_volume')
    @mock.patch('cinder.volume.utils.CONF')
    @mock.patch('cinder.volume.utils.rpc')
    def test_notify_about_replication_error(self, mock_rpc,
                                            mock_conf, mock_usage):
        mock_conf.host = 'host1'
        output = volume_utils.notify_about_replication_error(
            mock.sentinel.context,
            mock.sentinel.volume,
            'test_suffix')
        self.assertIsNone(output)
        mock_usage.assert_called_once_with(mock.sentinel.context,
                                           mock.sentinel.volume)
        mock_rpc.get_notifier.assert_called_once_with('replication', 'host1')
        mock_rpc.get_notifier.return_value.error.assert_called_once_with(
            mock.sentinel.context,
            'replication.test_suffix',
            mock_usage.return_value)

    @mock.patch('cinder.volume.utils._usage_from_volume')
    @mock.patch('cinder.volume.utils.CONF')
    @mock.patch('cinder.volume.utils.rpc')
    def test_notify_about_replication_error_with_kwargs(self, mock_rpc,
                                                        mock_conf, mock_usage):
        mock_conf.host = 'host1'
        output = volume_utils.notify_about_replication_error(
            mock.sentinel.context,
            mock.sentinel.volume,
            'test_suffix',
            extra_error_info={'a': 'b', 'c': 'd'},
            host='host2')
        self.assertIsNone(output)
        mock_usage.assert_called_once_with(mock.sentinel.context,
                                           mock.sentinel.volume,
                                           a='b', c='d')
        mock_rpc.get_notifier.assert_called_once_with('replication', 'host2')
        mock_rpc.get_notifier.return_value.error.assert_called_once_with(
            mock.sentinel.context,
            'replication.test_suffix',
            mock_usage.return_value)

    @mock.patch('cinder.volume.utils._usage_from_snapshot')
    @mock.patch('cinder.volume.utils.CONF')
    @mock.patch('cinder.volume.utils.rpc')
    def test_notify_about_snapshot_usage(self, mock_rpc,
                                         mock_conf, mock_usage):
        mock_conf.host = 'host1'
        output = volume_utils.notify_about_snapshot_usage(
            mock.sentinel.context,
            mock.sentinel.snapshot,
            'test_suffix')
        self.assertIsNone(output)
        mock_usage.assert_called_once_with(mock.sentinel.context,
                                           mock.sentinel.snapshot)
        mock_rpc.get_notifier.assert_called_once_with('snapshot', 'host1')
        mock_rpc.get_notifier.return_value.info.assert_called_once_with(
            mock.sentinel.context,
            'snapshot.test_suffix',
            mock_usage.return_value)

    @mock.patch('cinder.volume.utils._usage_from_snapshot')
    @mock.patch('cinder.volume.utils.CONF')
    @mock.patch('cinder.volume.utils.rpc')
    def test_notify_about_snapshot_usage_with_kwargs(self, mock_rpc, mock_conf,
                                                     mock_usage):
        mock_conf.host = 'host1'
        output = volume_utils.notify_about_snapshot_usage(
            mock.sentinel.context,
            mock.sentinel.snapshot,
            'test_suffix',
            extra_usage_info={'a': 'b', 'c': 'd'},
            host='host2')
        self.assertIsNone(output)
        mock_usage.assert_called_once_with(mock.sentinel.context,
                                           mock.sentinel.snapshot,
                                           a='b', c='d')
        mock_rpc.get_notifier.assert_called_once_with('snapshot', 'host2')
        mock_rpc.get_notifier.return_value.info.assert_called_once_with(
            mock.sentinel.context,
            'snapshot.test_suffix',
            mock_usage.return_value)

    def test_usage_from_snapshot(self):
        raw_snapshot = {
            'project_id': '12b0330ec2584a',
            'user_id': '158cba1b8c2bb6008e',
            'volume': {'availability_zone': 'nova'},
            'volume_id': '55614621',
            'volume_size': 1,
            'id': '343434a2',
            'display_name': '11',
            'created_at': '2014-12-11T10:10:00',
            'status': 'pause',
            'deleted': '',
        }
        usage_info = volume_utils._usage_from_snapshot(
            mock.sentinel.context,
            raw_snapshot)
        expected_snapshot = {
            'tenant_id': '12b0330ec2584a',
            'user_id': '158cba1b8c2bb6008e',
            'availability_zone': 'nova',
            'volume_id': '55614621',
            'volume_size': 1,
            'snapshot_id': '343434a2',
            'display_name': '11',
            'created_at': '2014-12-11T10:10:00',
            'status': 'pause',
            'deleted': '',
        }
        self.assertEqual(expected_snapshot, usage_info)

    @mock.patch('cinder.volume.utils._usage_from_consistencygroup')
    @mock.patch('cinder.volume.utils.CONF')
    @mock.patch('cinder.volume.utils.rpc')
    def test_notify_about_consistencygroup_usage(self, mock_rpc,
                                                 mock_conf, mock_usage):
        mock_conf.host = 'host1'
        output = volume_utils.notify_about_consistencygroup_usage(
            mock.sentinel.context,
            mock.sentinel.consistencygroup,
            'test_suffix')
        self.assertIsNone(output)
        mock_usage.assert_called_once_with(mock.sentinel.context,
                                           mock.sentinel.consistencygroup)
        mock_rpc.get_notifier.assert_called_once_with('consistencygroup',
                                                      'host1')
        mock_rpc.get_notifier.return_value.info.assert_called_once_with(
            mock.sentinel.context,
            'consistencygroup.test_suffix',
            mock_usage.return_value)

    @mock.patch('cinder.volume.utils._usage_from_consistencygroup')
    @mock.patch('cinder.volume.utils.CONF')
    @mock.patch('cinder.volume.utils.rpc')
    def test_notify_about_consistencygroup_usage_with_kwargs(self, mock_rpc,
                                                             mock_conf,
                                                             mock_usage):
        mock_conf.host = 'host1'
        output = volume_utils.notify_about_consistencygroup_usage(
            mock.sentinel.context,
            mock.sentinel.consistencygroup,
            'test_suffix',
            extra_usage_info={'a': 'b', 'c': 'd'},
            host='host2')
        self.assertIsNone(output)
        mock_usage.assert_called_once_with(mock.sentinel.context,
                                           mock.sentinel.consistencygroup,
                                           a='b', c='d')
        mock_rpc.get_notifier.assert_called_once_with('consistencygroup',
                                                      'host2')
        mock_rpc.get_notifier.return_value.info.assert_called_once_with(
            mock.sentinel.context,
            'consistencygroup.test_suffix',
            mock_usage.return_value)

    @mock.patch('cinder.volume.utils._usage_from_cgsnapshot')
    @mock.patch('cinder.volume.utils.CONF')
    @mock.patch('cinder.volume.utils.rpc')
    def test_notify_about_cgsnapshot_usage(self, mock_rpc,
                                           mock_conf, mock_usage):
        mock_conf.host = 'host1'
        output = volume_utils.notify_about_cgsnapshot_usage(
            mock.sentinel.context,
            mock.sentinel.cgsnapshot,
            'test_suffix')
        self.assertIsNone(output)
        mock_usage.assert_called_once_with(mock.sentinel.context,
                                           mock.sentinel.cgsnapshot)
        mock_rpc.get_notifier.assert_called_once_with('cgsnapshot', 'host1')
        mock_rpc.get_notifier.return_value.info.assert_called_once_with(
            mock.sentinel.context,
            'cgsnapshot.test_suffix',
            mock_usage.return_value)

    @mock.patch('cinder.volume.utils._usage_from_cgsnapshot')
    @mock.patch('cinder.volume.utils.CONF')
    @mock.patch('cinder.volume.utils.rpc')
    def test_notify_about_cgsnapshot_usage_with_kwargs(self, mock_rpc,
                                                       mock_conf, mock_usage):
        mock_conf.host = 'host1'
        output = volume_utils.notify_about_cgsnapshot_usage(
            mock.sentinel.context,
            mock.sentinel.cgsnapshot,
            'test_suffix',
            extra_usage_info={'a': 'b', 'c': 'd'},
            host='host2')
        self.assertIsNone(output)
        mock_usage.assert_called_once_with(mock.sentinel.context,
                                           mock.sentinel.cgsnapshot,
                                           a='b', c='d')
        mock_rpc.get_notifier.assert_called_once_with('cgsnapshot', 'host2')
        mock_rpc.get_notifier.return_value.info.assert_called_once_with(
            mock.sentinel.context,
            'cgsnapshot.test_suffix',
            mock_usage.return_value)


class LVMVolumeDriverTestCase(test.TestCase):
    def test_convert_blocksize_option(self):
        # Test valid volume_dd_blocksize
        bs, count = volume_utils._calculate_count(1024, '10M')
        self.assertEqual(bs, '10M')
        self.assertEqual(count, 103)

        bs, count = volume_utils._calculate_count(1024, '1xBBB')
        self.assertEqual(bs, '1M')
        self.assertEqual(count, 1024)

        # Test 'volume_dd_blocksize' with fraction
        bs, count = volume_utils._calculate_count(1024, '1.3M')
        self.assertEqual(bs, '1M')
        self.assertEqual(count, 1024)

        # Test zero-size 'volume_dd_blocksize'
        bs, count = volume_utils._calculate_count(1024, '0M')
        self.assertEqual(bs, '1M')
        self.assertEqual(count, 1024)

        # Test negative 'volume_dd_blocksize'
        bs, count = volume_utils._calculate_count(1024, '-1M')
        self.assertEqual(bs, '1M')
        self.assertEqual(count, 1024)

        # Test non-digital 'volume_dd_blocksize'
        bs, count = volume_utils._calculate_count(1024, 'ABM')
        self.assertEqual(bs, '1M')
        self.assertEqual(count, 1024)


class OdirectSupportTestCase(test.TestCase):
    @mock.patch('cinder.utils.execute')
    def test_check_for_odirect_support(self, mock_exec):
        output = volume_utils.check_for_odirect_support('/dev/abc', '/dev/def')
        self.assertTrue(output)
        mock_exec.assert_called_once_with('dd', 'count=0', 'if=/dev/abc',
                                          'of=/dev/def', 'oflag=direct',
                                          run_as_root=True)
        mock_exec.reset_mock()

        output = volume_utils.check_for_odirect_support('/dev/abc', '/dev/def',
                                                        'iflag=direct')
        self.assertTrue(output)
        mock_exec.assert_called_once_with('dd', 'count=0', 'if=/dev/abc',
                                          'of=/dev/def', 'iflag=direct',
                                          run_as_root=True)

    @mock.patch('cinder.utils.execute',
                side_effect=processutils.ProcessExecutionError)
    def test_check_for_odirect_support_error(self, mock_exec):
        output = volume_utils.check_for_odirect_support('/dev/abc', '/dev/def')
        self.assertFalse(output)
        mock_exec.assert_called_once_with('dd', 'count=0', 'if=/dev/abc',
                                          'of=/dev/def', 'oflag=direct',
                                          run_as_root=True)


class ClearVolumeTestCase(test.TestCase):
    @mock.patch('cinder.volume.utils.copy_volume', return_value=None)
    @mock.patch('cinder.volume.utils.CONF')
    def test_clear_volume_conf(self, mock_conf, mock_copy):
        mock_conf.volume_clear = 'zero'
        mock_conf.volume_clear_size = 0
        mock_conf.volume_dd_blocksize = '1M'
        mock_conf.volume_clear_ionice = '-c3'
        output = volume_utils.clear_volume(1024, 'volume_path')
        self.assertIsNone(output)
        mock_copy.assert_called_once_with('/dev/zero', 'volume_path', 1024,
                                          '1M', sync=True,
                                          execute=utils.execute, ionice='-c3',
                                          throttle=None)

    @mock.patch('cinder.volume.utils.copy_volume', return_value=None)
    @mock.patch('cinder.volume.utils.CONF')
    def test_clear_volume_args(self, mock_conf, mock_copy):
        mock_conf.volume_clear = 'shred'
        mock_conf.volume_clear_size = 0
        mock_conf.volume_dd_blocksize = '1M'
        mock_conf.volume_clear_ionice = '-c3'
        output = volume_utils.clear_volume(1024, 'volume_path', 'zero', 1,
                                           '-c0')
        self.assertIsNone(output)
        mock_copy.assert_called_once_with('/dev/zero', 'volume_path', 1,
                                          '1M', sync=True,
                                          execute=utils.execute, ionice='-c0',
                                          throttle=None)

    @mock.patch('cinder.utils.execute')
    @mock.patch('cinder.volume.utils.CONF')
    def test_clear_volume_shred(self, mock_conf, mock_exec):
        mock_conf.volume_clear = 'shred'
        mock_conf.volume_clear_size = 1
        mock_conf.volume_clear_ionice = None
        output = volume_utils.clear_volume(1024, 'volume_path')
        self.assertIsNone(output)
        mock_exec.assert_called_once_with(
            'shred', '-n3', '-s1MiB', "volume_path", run_as_root=True)

    @mock.patch('cinder.utils.execute')
    @mock.patch('cinder.volume.utils.CONF')
    def test_clear_volume_shred_not_clear_size(self, mock_conf, mock_exec):
        mock_conf.volume_clear = 'shred'
        mock_conf.volume_clear_size = None
        mock_conf.volume_clear_ionice = None
        output = volume_utils.clear_volume(1024, 'volume_path')
        self.assertIsNone(output)
        mock_exec.assert_called_once_with(
            'shred', '-n3', "volume_path", run_as_root=True)

    @mock.patch('cinder.volume.utils.CONF')
    def test_clear_volume_invalid_opt(self, mock_conf):
        mock_conf.volume_clear = 'non_existent_volume_clearer'
        mock_conf.volume_clear_size = 0
        mock_conf.volume_clear_ionice = None
        self.assertRaises(exception.InvalidConfigurationValue,
                          volume_utils.clear_volume,
                          1024, "volume_path")


class CopyVolumeTestCase(test.TestCase):
    @mock.patch('cinder.volume.utils._calculate_count',
                return_value=(1234, 5678))
    @mock.patch('cinder.volume.utils.check_for_odirect_support',
                return_value=True)
    @mock.patch('cinder.utils.execute')
    @mock.patch('cinder.volume.utils.CONF')
    def test_copy_volume_dd_iflag_and_oflag(self, mock_conf, mock_exec,
                                            mock_support, mock_count):
        fake_throttle = throttling.Throttle(['fake_throttle'])
        output = volume_utils.copy_volume('/dev/zero', '/dev/null', 1024, 1,
                                          sync=True, execute=utils.execute,
                                          ionice=None, throttle=fake_throttle)
        self.assertIsNone(output)
        mock_exec.assert_called_once_with('fake_throttle', 'dd',
                                          'if=/dev/zero',
                                          'of=/dev/null', 'count=5678',
                                          'bs=1234', 'iflag=direct',
                                          'oflag=direct', run_as_root=True)

        mock_exec.reset_mock()

        output = volume_utils.copy_volume('/dev/zero', '/dev/null', 1024, 1,
                                          sync=False, execute=utils.execute,
                                          ionice=None, throttle=fake_throttle)
        self.assertIsNone(output)
        mock_exec.assert_called_once_with('fake_throttle', 'dd',
                                          'if=/dev/zero',
                                          'of=/dev/null', 'count=5678',
                                          'bs=1234', 'iflag=direct',
                                          'oflag=direct', run_as_root=True)

    @mock.patch('cinder.volume.utils._calculate_count',
                return_value=(1234, 5678))
    @mock.patch('cinder.volume.utils.check_for_odirect_support',
                return_value=False)
    @mock.patch('cinder.utils.execute')
    def test_copy_volume_dd_no_iflag_or_oflag(self, mock_exec,
                                              mock_support, mock_count):
        fake_throttle = throttling.Throttle(['fake_throttle'])
        output = volume_utils.copy_volume('/dev/zero', '/dev/null', 1024, 1,
                                          sync=True, execute=utils.execute,
                                          ionice=None, throttle=fake_throttle)
        self.assertIsNone(output)
        mock_exec.assert_called_once_with('fake_throttle', 'dd',
                                          'if=/dev/zero',
                                          'of=/dev/null', 'count=5678',
                                          'bs=1234', 'conv=fdatasync',
                                          run_as_root=True)

        mock_exec.reset_mock()

        output = volume_utils.copy_volume('/dev/zero', '/dev/null', 1024, 1,
                                          sync=False, execute=utils.execute,
                                          ionice=None, throttle=fake_throttle)
        self.assertIsNone(output)
        mock_exec.assert_called_once_with('fake_throttle', 'dd',
                                          'if=/dev/zero',
                                          'of=/dev/null', 'count=5678',
                                          'bs=1234', run_as_root=True)

    @mock.patch('cinder.volume.utils._calculate_count',
                return_value=(1234, 5678))
    @mock.patch('cinder.volume.utils.check_for_odirect_support',
                return_value=False)
    @mock.patch('cinder.utils.execute')
    def test_copy_volume_dd_no_throttle(self, mock_exec, mock_support,
                                        mock_count):
        output = volume_utils.copy_volume('/dev/zero', '/dev/null', 1024, 1,
                                          sync=True, execute=utils.execute,
                                          ionice=None)
        self.assertIsNone(output)
        mock_exec.assert_called_once_with('dd', 'if=/dev/zero', 'of=/dev/null',
                                          'count=5678', 'bs=1234',
                                          'conv=fdatasync', run_as_root=True)

    @mock.patch('cinder.volume.utils._calculate_count',
                return_value=(1234, 5678))
    @mock.patch('cinder.volume.utils.check_for_odirect_support',
                return_value=False)
    @mock.patch('cinder.utils.execute')
    def test_copy_volume_dd_with_ionice(self, mock_exec,
                                        mock_support, mock_count):
        output = volume_utils.copy_volume('/dev/zero', '/dev/null', 1024, 1,
                                          sync=True, execute=utils.execute,
                                          ionice='-c3')
        self.assertIsNone(output)
        mock_exec.assert_called_once_with('ionice', '-c3', 'dd',
                                          'if=/dev/zero', 'of=/dev/null',
                                          'count=5678', 'bs=1234',
                                          'conv=fdatasync', run_as_root=True)


class VolumeUtilsTestCase(test.TestCase):
    def test_null_safe_str(self):
        self.assertEqual('', volume_utils.null_safe_str(None))
        self.assertEqual('', volume_utils.null_safe_str(False))
        self.assertEqual('', volume_utils.null_safe_str(0))
        self.assertEqual('', volume_utils.null_safe_str([]))
        self.assertEqual('', volume_utils.null_safe_str(()))
        self.assertEqual('', volume_utils.null_safe_str({}))
        self.assertEqual('', volume_utils.null_safe_str(set()))
        self.assertEqual('a', volume_utils.null_safe_str('a'))
        self.assertEqual('1', volume_utils.null_safe_str(1))
        self.assertEqual('True', volume_utils.null_safe_str(True))

    @mock.patch('cinder.utils.get_root_helper')
    @mock.patch('cinder.brick.local_dev.lvm.LVM.supports_thin_provisioning')
    def test_supports_thin_provisioning(self, mock_supports_thin, mock_helper):
        self.assertEqual(mock_supports_thin.return_value,
                         volume_utils.supports_thin_provisioning())
        mock_helper.assert_called_once_with()

    @mock.patch('cinder.utils.get_root_helper')
    @mock.patch('cinder.brick.local_dev.lvm.LVM.get_all_physical_volumes')
    def test_get_all_physical_volumes(self, mock_get_vols, mock_helper):
        self.assertEqual(mock_get_vols.return_value,
                         volume_utils.get_all_physical_volumes())
        mock_helper.assert_called_once_with()

    @mock.patch('cinder.utils.get_root_helper')
    @mock.patch('cinder.brick.local_dev.lvm.LVM.get_all_volume_groups')
    def test_get_all_volume_groups(self, mock_get_groups, mock_helper):
        self.assertEqual(mock_get_groups.return_value,
                         volume_utils.get_all_volume_groups())
        mock_helper.assert_called_once_with()

    def test_generate_password(self):
        password = volume_utils.generate_password()
        self.assertTrue(any(c for c in password if c in '23456789'))
        self.assertTrue(any(c for c in password
                            if c in 'abcdefghijkmnopqrstuvwxyz'))
        self.assertTrue(any(c for c in password
                            if c in 'ABCDEFGHJKLMNPQRSTUVWXYZ'))
        self.assertEqual(16, len(password))
        self.assertEqual(10, len(volume_utils.generate_password(10)))

    @mock.patch('cinder.volume.utils.generate_password')
    def test_generate_username(self, mock_gen_pass):
        output = volume_utils.generate_username()
        self.assertEqual(mock_gen_pass.return_value, output)

    def test_extract_host(self):
        host = 'Host'
        # default level is 'backend'
        self.assertEqual(
            volume_utils.extract_host(host), 'Host')
        self.assertEqual(
            volume_utils.extract_host(host, 'host'), 'Host')
        self.assertEqual(
            volume_utils.extract_host(host, 'backend'), 'Host')
        # default_pool_name doesn't work for level other than 'pool'
        self.assertEqual(
            volume_utils.extract_host(host, 'host', True), 'Host')
        self.assertEqual(
            volume_utils.extract_host(host, 'host', False), 'Host')
        self.assertEqual(
            volume_utils.extract_host(host, 'backend', True), 'Host')
        self.assertEqual(
            volume_utils.extract_host(host, 'backend', False), 'Host')
        self.assertEqual(
            volume_utils.extract_host(host, 'pool'), None)
        self.assertEqual(
            volume_utils.extract_host(host, 'pool', True), '_pool0')

        host = 'Host@Backend'
        self.assertEqual(
            volume_utils.extract_host(host), 'Host@Backend')
        self.assertEqual(
            volume_utils.extract_host(host, 'host'), 'Host')
        self.assertEqual(
            volume_utils.extract_host(host, 'backend'), 'Host@Backend')
        self.assertEqual(
            volume_utils.extract_host(host, 'pool'), None)
        self.assertEqual(
            volume_utils.extract_host(host, 'pool', True), '_pool0')

        host = 'Host@Backend#Pool'
        self.assertEqual(
            volume_utils.extract_host(host), 'Host@Backend')
        self.assertEqual(
            volume_utils.extract_host(host, 'host'), 'Host')
        self.assertEqual(
            volume_utils.extract_host(host, 'backend'), 'Host@Backend')
        self.assertEqual(
            volume_utils.extract_host(host, 'pool'), 'Pool')
        self.assertEqual(
            volume_utils.extract_host(host, 'pool', True), 'Pool')

        host = 'Host#Pool'
        self.assertEqual(
            volume_utils.extract_host(host), 'Host')
        self.assertEqual(
            volume_utils.extract_host(host, 'host'), 'Host')
        self.assertEqual(
            volume_utils.extract_host(host, 'backend'), 'Host')
        self.assertEqual(
            volume_utils.extract_host(host, 'pool'), 'Pool')
        self.assertEqual(
            volume_utils.extract_host(host, 'pool', True), 'Pool')

    def test_append_host(self):
        host = 'Host'
        pool = 'Pool'
        expected = 'Host#Pool'
        self.assertEqual(expected,
                         volume_utils.append_host(host, pool))

        pool = None
        expected = 'Host'
        self.assertEqual(expected,
                         volume_utils.append_host(host, pool))

        host = None
        pool = 'pool'
        expected = None
        self.assertEqual(expected,
                         volume_utils.append_host(host, pool))

        host = None
        pool = None
        expected = None
        self.assertEqual(expected,
                         volume_utils.append_host(host, pool))

    def test_compare_hosts(self):
        host_1 = 'fake_host@backend1'
        host_2 = 'fake_host@backend1#pool1'
        self.assertTrue(volume_utils.hosts_are_equivalent(host_1, host_2))

        host_2 = 'fake_host@backend1'
        self.assertTrue(volume_utils.hosts_are_equivalent(host_1, host_2))

        host_2 = 'fake_host2@backend1'
        self.assertFalse(volume_utils.hosts_are_equivalent(host_1, host_2))
