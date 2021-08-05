#    Copyright 2011 Justin Santa Barbara
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

import datetime
import json
import os
import sys
from unittest import mock

import ddt
from oslo_utils import timeutils
import webob.exc

import cinder
from cinder.api import api_utils
from cinder import context
from cinder import exception
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import test
from cinder import utils
from cinder.volume import volume_utils

POOL_CAPS = {'total_capacity_gb': 0,
             'free_capacity_gb': 0,
             'allocated_capacity_gb': 0,
             'provisioned_capacity_gb': 0,
             'max_over_subscription_ratio': '1.0',
             'thin_provisioning_support': False,
             'thick_provisioning_support': True,
             'reserved_percentage': 0,
             'volume_backend_name': 'lvm1',
             'timestamp': timeutils.utcnow(),
             'multiattach': True,
             'uuid': 'a3a593da-7f8d-4bb7-8b4c-f2bc1e0b4824'}


class ExecuteTestCase(test.TestCase):
    @mock.patch('cinder.utils.processutils.execute')
    def test_execute(self, mock_putils_exe):
        output = utils.execute('a', 1, foo='bar')
        self.assertEqual(mock_putils_exe.return_value, output)
        mock_putils_exe.assert_called_once_with('a', 1, foo='bar')

    @mock.patch('cinder.utils.get_root_helper')
    @mock.patch('cinder.utils.processutils.execute')
    def test_execute_root(self, mock_putils_exe, mock_get_helper):
        output = utils.execute('a', 1, foo='bar', run_as_root=True)
        self.assertEqual(mock_putils_exe.return_value, output)
        mock_helper = mock_get_helper.return_value
        mock_putils_exe.assert_called_once_with('a', 1, foo='bar',
                                                run_as_root=True,
                                                root_helper=mock_helper)

    @mock.patch('cinder.utils.get_root_helper')
    @mock.patch('cinder.utils.processutils.execute')
    def test_execute_root_and_helper(self, mock_putils_exe, mock_get_helper):
        mock_helper = mock.Mock()
        output = utils.execute('a', 1, foo='bar', run_as_root=True,
                               root_helper=mock_helper)
        self.assertEqual(mock_putils_exe.return_value, output)
        self.assertFalse(mock_get_helper.called)
        mock_putils_exe.assert_called_once_with('a', 1, foo='bar',
                                                run_as_root=True,
                                                root_helper=mock_helper)


@ddt.ddt
class GenericUtilsTestCase(test.TestCase):
    def test_as_int(self):
        test_obj_int = '2'
        test_obj_float = '2.2'
        for obj in [test_obj_int, test_obj_float]:
            self.assertEqual(2, utils.as_int(obj))

        obj = 'not_a_number'
        self.assertEqual(obj, utils.as_int(obj))
        self.assertRaises(TypeError,
                          utils.as_int,
                          obj,
                          quiet=False)

    def test_check_exclusive_options(self):
        utils.check_exclusive_options()
        utils.check_exclusive_options(something=None,
                                      pretty_keys=True,
                                      unit_test=True)

        self.assertRaises(exception.InvalidInput,
                          utils.check_exclusive_options,
                          test=True,
                          unit=False,
                          pretty_keys=True)

        self.assertRaises(exception.InvalidInput,
                          utils.check_exclusive_options,
                          test=True,
                          unit=False,
                          pretty_keys=False)

    def test_hostname_unicode_sanitization(self):
        hostname = u"\u7684.test.example.com"
        self.assertEqual("test.example.com",
                         volume_utils.sanitize_hostname(hostname))

    def test_hostname_sanitize_periods(self):
        hostname = "....test.example.com..."
        self.assertEqual("test.example.com",
                         volume_utils.sanitize_hostname(hostname))

    def test_hostname_sanitize_dashes(self):
        hostname = "----test.example.com---"
        self.assertEqual("test.example.com",
                         volume_utils.sanitize_hostname(hostname))

    def test_hostname_sanitize_characters(self):
        hostname = "(#@&$!(@*--#&91)(__=+--test-host.example!!.com-0+"
        self.assertEqual("91----test-host.example.com-0",
                         volume_utils.sanitize_hostname(hostname))

    def test_hostname_translate(self):
        hostname = "<}\x1fh\x10e\x08l\x02l\x05o\x12!{>"
        self.assertEqual("hello", volume_utils.sanitize_hostname(hostname))

    @mock.patch('os.path.join', side_effect=lambda x, y: '/'.join((x, y)))
    def test_make_dev_path(self, mock_join):
        self.assertEqual('/dev/xvda', utils.make_dev_path('xvda'))
        self.assertEqual('/dev/xvdb1', utils.make_dev_path('xvdb', 1))
        self.assertEqual('/foo/xvdc1', utils.make_dev_path('xvdc', 1, '/foo'))

    @test.testtools.skipIf(sys.platform == "darwin", "SKIP on OSX")
    @mock.patch('tempfile.NamedTemporaryFile')
    @mock.patch.object(os, 'open')
    @mock.patch.object(os, 'fdatasync')
    @mock.patch.object(os, 'fsync')
    @mock.patch.object(os, 'rename')
    @mock.patch.object(os, 'close')
    @mock.patch.object(os.path, 'isfile')
    @mock.patch.object(os, 'unlink')
    def test_write_configfile(self, mock_unlink, mock_isfile, mock_close,
                              mock_rename, mock_fsync, mock_fdatasync,
                              mock_open, mock_tmp):
        filename = 'foo'
        directory = '/some/random/path'
        filepath = os.path.join(directory, filename)
        expected = ('\n<target iqn.2010-10.org.openstack:volume-%(id)s>\n'
                    '    backing-store %(bspath)s\n'
                    '    driver iscsi\n'
                    '    incominguser chap_foo chap_bar\n'
                    '    bsoflags foo\n'
                    '    write-cache bar\n'
                    '</target>\n' % {'id': filename,
                                     'bspath': filepath})

        # Normal case
        utils.robust_file_write(directory, filename, expected)
        mock_open.assert_called_once_with(directory, os.O_DIRECTORY)
        mock_rename.assert_called_once_with(mock.ANY, filepath)
        self.assertEqual(
            expected.encode('utf-8'),
            mock_tmp.return_value.__enter__.return_value.write.call_args[0][0]
        )

        # Failure to write persistent file.
        tempfile = '/some/tempfile'
        mock_tmp.return_value.__enter__.return_value.name = tempfile
        mock_rename.side_effect = OSError
        self.assertRaises(OSError,
                          utils.robust_file_write,
                          directory,
                          filename,
                          mock.MagicMock())
        mock_isfile.assert_called_once_with(tempfile)
        mock_unlink.assert_called_once_with(tempfile)

    def test_check_ssh_injection(self):
        cmd_list = ['ssh', '-D', 'my_name@name_of_remote_computer']
        self.assertIsNone(utils.check_ssh_injection(cmd_list))
        cmd_list = ['echo', '"quoted arg with space"']
        self.assertIsNone(utils.check_ssh_injection(cmd_list))
        cmd_list = ['echo', "'quoted arg with space'"]
        self.assertIsNone(utils.check_ssh_injection(cmd_list))

    def test_check_ssh_injection_on_error(self):
        with_unquoted_space = ['ssh', 'my_name@      name_of_remote_computer']
        self.assertRaises(exception.SSHInjectionThreat,
                          utils.check_ssh_injection,
                          with_unquoted_space)
        with_danger_chars = ['||', 'my_name@name_of_remote_computer']
        self.assertRaises(exception.SSHInjectionThreat,
                          utils.check_ssh_injection,
                          with_danger_chars)
        with_danger_char = [';', 'my_name@name_of_remote_computer']
        self.assertRaises(exception.SSHInjectionThreat,
                          utils.check_ssh_injection,
                          with_danger_char)
        with_special = ['cmd', 'virus;ls']
        self.assertRaises(exception.SSHInjectionThreat,
                          utils.check_ssh_injection,
                          with_special)
        quoted_with_unescaped = ['cmd', '"arg\"withunescaped"']
        self.assertRaises(exception.SSHInjectionThreat,
                          utils.check_ssh_injection,
                          quoted_with_unescaped)
        bad_before_quotes = ['cmd', 'virus;"quoted argument"']
        self.assertRaises(exception.SSHInjectionThreat,
                          utils.check_ssh_injection,
                          bad_before_quotes)
        bad_after_quotes = ['echo', '"quoted argument";rm -rf']
        self.assertRaises(exception.SSHInjectionThreat,
                          utils.check_ssh_injection,
                          bad_after_quotes)
        bad_within_quotes = ['echo', "'quoted argument `rm -rf`'"]
        self.assertRaises(exception.SSHInjectionThreat,
                          utils.check_ssh_injection,
                          bad_within_quotes)
        with_multiple_quotes = ['echo', '"quoted";virus;"quoted"']
        self.assertRaises(exception.SSHInjectionThreat,
                          utils.check_ssh_injection,
                          with_multiple_quotes)
        with_multiple_quotes = ['echo', '"quoted";virus;\'quoted\'']
        self.assertRaises(exception.SSHInjectionThreat,
                          utils.check_ssh_injection,
                          with_multiple_quotes)

    @mock.patch('os.stat')
    def test_get_file_mode(self, mock_stat):
        class stat_result(object):
            st_mode = 0o777
            st_gid = 33333

        test_file = '/var/tmp/made_up_file'
        mock_stat.return_value = stat_result
        mode = utils.get_file_mode(test_file)
        self.assertEqual(0o777, mode)
        mock_stat.assert_called_once_with(test_file)

    @mock.patch('os.stat')
    def test_get_file_gid(self, mock_stat):

        class stat_result(object):
            st_mode = 0o777
            st_gid = 33333

        test_file = '/var/tmp/made_up_file'
        mock_stat.return_value = stat_result
        gid = utils.get_file_gid(test_file)
        self.assertEqual(33333, gid)
        mock_stat.assert_called_once_with(test_file)

    @mock.patch('cinder.utils.CONF')
    def test_get_root_helper(self, mock_conf):
        mock_conf.rootwrap_config = '/path/to/conf'
        self.assertEqual('sudo cinder-rootwrap /path/to/conf',
                         utils.get_root_helper())

    @ddt.data({'path_a': 'test', 'path_b': 'test', 'exp_eq': True})
    @ddt.data({'path_a': 'test', 'path_b': 'other', 'exp_eq': False})
    @ddt.unpack
    @mock.patch('os.path.normcase')
    def test_paths_normcase_equal(self, mock_normcase, path_a,
                                  path_b, exp_eq):
        # os.path.normcase will lower the path string on Windows
        # while doing nothing on other platforms.
        mock_normcase.side_effect = lambda x: x

        result = utils.paths_normcase_equal(path_a, path_b)
        self.assertEqual(exp_eq, result)

        mock_normcase.assert_has_calls([mock.call(path_a), mock.call(path_b)])


class TemporaryChownTestCase(test.TestCase):
    @mock.patch('os.stat')
    @mock.patch('os.getuid', return_value=1234)
    @mock.patch('cinder.utils.execute')
    def test_get_uid(self, mock_exec, mock_getuid, mock_stat):
        mock_stat.return_value.st_uid = 5678
        test_filename = 'a_file'
        with utils.temporary_chown(test_filename):
            mock_exec.assert_called_once_with('chown', '1234', test_filename,
                                              run_as_root=True)
        mock_getuid.assert_called_once_with()
        mock_stat.assert_called_once_with(test_filename)
        calls = [mock.call('chown', '1234', test_filename, run_as_root=True),
                 mock.call('chown', '5678', test_filename, run_as_root=True)]
        mock_exec.assert_has_calls(calls)

    @mock.patch('os.stat')
    @mock.patch('os.getuid', return_value=1234)
    @mock.patch('cinder.utils.execute')
    def test_supplied_owner_uid(self, mock_exec, mock_getuid, mock_stat):
        mock_stat.return_value.st_uid = 5678
        test_filename = 'a_file'
        with utils.temporary_chown(test_filename, owner_uid=9101):
            mock_exec.assert_called_once_with('chown', '9101', test_filename,
                                              run_as_root=True)
        self.assertFalse(mock_getuid.called)
        mock_stat.assert_called_once_with(test_filename)
        calls = [mock.call('chown', '9101', test_filename, run_as_root=True),
                 mock.call('chown', '5678', test_filename, run_as_root=True)]
        mock_exec.assert_has_calls(calls)

    @mock.patch('os.stat')
    @mock.patch('os.getuid', return_value=5678)
    @mock.patch('cinder.utils.execute')
    def test_matching_uid(self, mock_exec, mock_getuid, mock_stat):
        mock_stat.return_value.st_uid = 5678
        test_filename = 'a_file'
        with utils.temporary_chown(test_filename):
            pass
        mock_getuid.assert_called_once_with()
        mock_stat.assert_called_once_with(test_filename)
        self.assertFalse(mock_exec.called)

    @mock.patch('os.name', 'nt')
    @mock.patch('os.stat')
    @mock.patch('cinder.utils.execute')
    def test_temporary_chown_win32(self, mock_exec, mock_stat):
        with utils.temporary_chown(mock.sentinel.path):
            pass

        mock_exec.assert_not_called()
        mock_stat.assert_not_called()


class TempdirTestCase(test.TestCase):
    @mock.patch('tempfile.mkdtemp')
    @mock.patch('shutil.rmtree')
    def test_tempdir(self, mock_rmtree, mock_mkdtemp):
        with utils.tempdir(a='1', b=2) as td:
            self.assertEqual(mock_mkdtemp.return_value, td)
            self.assertFalse(mock_rmtree.called)
        mock_mkdtemp.assert_called_once_with(a='1', b=2)
        mock_rmtree.assert_called_once_with(mock_mkdtemp.return_value)

    @mock.patch('tempfile.mkdtemp')
    @mock.patch('shutil.rmtree', side_effect=OSError)
    def test_tempdir_error(self, mock_rmtree, mock_mkdtemp):
        with utils.tempdir(a='1', b=2) as td:
            self.assertEqual(mock_mkdtemp.return_value, td)
            self.assertFalse(mock_rmtree.called)
        mock_mkdtemp.assert_called_once_with(a='1', b=2)
        mock_rmtree.assert_called_once_with(mock_mkdtemp.return_value)


class WalkClassHierarchyTestCase(test.TestCase):
    def test_walk_class_hierarchy(self):
        class A(object):
            pass

        class B(A):
            pass

        class C(A):
            pass

        class D(B):
            pass

        class E(A):
            pass

        class_pairs = zip((D, B, E),
                          api_utils.walk_class_hierarchy(A, encountered=[C]))
        for actual, expected in class_pairs:
            self.assertEqual(expected, actual)

        class_pairs = zip((D, B, C, E), api_utils.walk_class_hierarchy(A))
        for actual, expected in class_pairs:
            self.assertEqual(expected, actual)


class GetDiskOfPartitionTestCase(test.TestCase):
    def test_devpath_is_diskpath(self):
        devpath = '/some/path'
        st_mock = mock.Mock()
        output = utils._get_disk_of_partition(devpath, st_mock)
        self.assertEqual('/some/path', output[0])
        self.assertIs(st_mock, output[1])

        with mock.patch('os.stat') as mock_stat:
            devpath = '/some/path'
            output = utils._get_disk_of_partition(devpath)
            mock_stat.assert_called_once_with(devpath)
            self.assertEqual(devpath, output[0])
            self.assertIs(mock_stat.return_value, output[1])

    @mock.patch('os.stat', side_effect=OSError)
    def test_stat_oserror(self, mock_stat):
        st_mock = mock.Mock()
        devpath = '/some/path1'
        output = utils._get_disk_of_partition(devpath, st_mock)
        mock_stat.assert_called_once_with('/some/path')
        self.assertEqual(devpath, output[0])
        self.assertIs(st_mock, output[1])

    @mock.patch('stat.S_ISBLK', return_value=True)
    @mock.patch('os.stat')
    def test_diskpath_is_block_device(self, mock_stat, mock_isblk):
        st_mock = mock.Mock()
        devpath = '/some/path1'
        output = utils._get_disk_of_partition(devpath, st_mock)
        self.assertEqual('/some/path', output[0])
        self.assertEqual(mock_stat.return_value, output[1])

    @mock.patch('stat.S_ISBLK', return_value=False)
    @mock.patch('os.stat')
    def test_diskpath_is_not_block_device(self, mock_stat, mock_isblk):
        st_mock = mock.Mock()
        devpath = '/some/path1'
        output = utils._get_disk_of_partition(devpath, st_mock)
        self.assertEqual(devpath, output[0])
        self.assertEqual(st_mock, output[1])


class GetBlkdevMajorMinorTestCase(test.TestCase):
    @mock.patch('os.stat')
    def test_get_file_size(self, mock_stat):

        class stat_result(object):
            st_mode = 0o777
            st_size = 1074253824

        test_file = '/var/tmp/made_up_file'
        mock_stat.return_value = stat_result
        size = utils.get_file_size(test_file)
        self.assertEqual(size, stat_result.st_size)
        mock_stat.assert_called_once_with(test_file)

    @test.testtools.skipIf(sys.platform == 'darwin', 'Not supported on macOS')
    @mock.patch('os.stat')
    def test_get_blkdev_major_minor(self, mock_stat):

        class stat_result(object):
            st_mode = 0o60660
            st_rdev = os.makedev(253, 7)

        test_device = '/dev/made_up_blkdev'
        mock_stat.return_value = stat_result
        dev = utils.get_blkdev_major_minor(test_device)
        self.assertEqual('253:7', dev)
        mock_stat.assert_called_once_with(test_device)

    @mock.patch('os.stat')
    @mock.patch.object(utils, 'execute')
    def _test_get_blkdev_major_minor_file(self, test_partition,
                                          mock_exec, mock_stat):
        mock_exec.return_value = (
            'Filesystem Size Used Avail Use%% Mounted on\n'
            '%s 4096 2048 2048 50%% /tmp\n' % test_partition, None)

        test_file = '/tmp/file'
        test_disk = '/dev/made_up_disk'

        class stat_result_file(object):
            st_mode = 0o660

        class stat_result_partition(object):
            st_mode = 0o60660
            st_rdev = os.makedev(8, 65)

        class stat_result_disk(object):
            st_mode = 0o60660
            st_rdev = os.makedev(8, 64)

        def fake_stat(path):
            try:
                return {test_file: stat_result_file,
                        test_partition: stat_result_partition,
                        test_disk: stat_result_disk}[path]
            except KeyError:
                raise OSError

        mock_stat.side_effect = fake_stat

        dev = utils.get_blkdev_major_minor(test_file)
        mock_stat.assert_any_call(test_file)
        mock_exec.assert_called_once_with('df', test_file)
        if test_partition.startswith('/'):
            mock_stat.assert_any_call(test_partition)
            mock_stat.assert_any_call(test_disk)
        return dev

    def test_get_blkdev_major_minor_file(self):
        dev = self._test_get_blkdev_major_minor_file('/dev/made_up_disk1')
        self.assertEqual('8:64', dev)

    def test_get_blkdev_major_minor_file_nfs(self):
        dev = self._test_get_blkdev_major_minor_file('nfs-server:/export/path')
        self.assertIsNone(dev)

    @mock.patch('os.stat')
    @mock.patch('stat.S_ISCHR', return_value=False)
    @mock.patch('stat.S_ISBLK', return_value=False)
    def test_get_blkdev_failure(self, mock_isblk, mock_ischr, mock_stat):
        path = '/some/path'
        self.assertRaises(exception.CinderException,
                          utils.get_blkdev_major_minor,
                          path, lookup_for_file=False)
        mock_stat.assert_called_once_with(path)
        mock_isblk.assert_called_once_with(mock_stat.return_value.st_mode)
        mock_ischr.assert_called_once_with(mock_stat.return_value.st_mode)

    @mock.patch('os.stat')
    @mock.patch('stat.S_ISCHR', return_value=True)
    @mock.patch('stat.S_ISBLK', return_value=False)
    def test_get_blkdev_is_chr(self, mock_isblk, mock_ischr, mock_stat):
        path = '/some/path'
        output = utils.get_blkdev_major_minor(path, lookup_for_file=False)
        mock_stat.assert_called_once_with(path)
        mock_isblk.assert_called_once_with(mock_stat.return_value.st_mode)
        mock_ischr.assert_called_once_with(mock_stat.return_value.st_mode)
        self.assertIsNone(output)


class MonkeyPatchTestCase(test.TestCase):
    """Unit test for utils.monkey_patch()."""
    def setUp(self):
        super(MonkeyPatchTestCase, self).setUp()
        self.example_package = 'cinder.tests.unit.monkey_patch_example.'
        self.flags(
            monkey_patch=True,
            monkey_patch_modules=[self.example_package + 'example_a' + ':'
                                  + self.example_package
                                  + 'example_decorator'])

    def test_monkey_patch(self):
        utils.monkey_patch()
        cinder.tests.unit.monkey_patch_example.CALLED_FUNCTION = []
        from cinder.tests.unit.monkey_patch_example import example_a
        from cinder.tests.unit.monkey_patch_example import example_b

        self.assertEqual('Example function', example_a.example_function_a())
        exampleA = example_a.ExampleClassA()
        exampleA.example_method()
        ret_a = exampleA.example_method_add(3, 5)
        self.assertEqual(8, ret_a)

        self.assertEqual('Example function', example_b.example_function_b())
        exampleB = example_b.ExampleClassB()
        exampleB.example_method()
        ret_b = exampleB.example_method_add(3, 5)

        self.assertEqual(8, ret_b)
        package_a = self.example_package + 'example_a.'
        self.assertIn(package_a + 'example_function_a',
                      cinder.tests.unit.monkey_patch_example.CALLED_FUNCTION)

        self.assertIn(package_a + 'ExampleClassA.example_method',
                      cinder.tests.unit.monkey_patch_example.CALLED_FUNCTION)
        self.assertIn(package_a + 'ExampleClassA.example_method_add',
                      cinder.tests.unit.monkey_patch_example.CALLED_FUNCTION)
        package_b = self.example_package + 'example_b.'
        self.assertNotIn(
            package_b + 'example_function_b',
            cinder.tests.unit.monkey_patch_example.CALLED_FUNCTION)
        self.assertNotIn(
            package_b + 'ExampleClassB.example_method',
            cinder.tests.unit.monkey_patch_example.CALLED_FUNCTION)
        self.assertNotIn(
            package_b + 'ExampleClassB.example_method_add',
            cinder.tests.unit.monkey_patch_example.CALLED_FUNCTION)


class AuditPeriodTest(test.TestCase):

    def setUp(self):
        super(AuditPeriodTest, self).setUp()
        test_time = datetime.datetime(second=23,
                                      minute=12,
                                      hour=8,
                                      day=5,
                                      month=3,
                                      year=2012)
        patcher = mock.patch.object(timeutils, 'utcnow')
        self.addCleanup(patcher.stop)
        self.mock_utcnow = patcher.start()
        self.mock_utcnow.return_value = test_time

    def test_hour(self):
        begin, end = utils.last_completed_audit_period(unit='hour')
        self.assertEqual(datetime.datetime(hour=7, day=5, month=3, year=2012),
                         begin)
        self.assertEqual(datetime.datetime(hour=8, day=5, month=3, year=2012),
                         end)

    def test_hour_with_offset_before_current(self):
        begin, end = utils.last_completed_audit_period(unit='hour@10')
        self.assertEqual(datetime.datetime(minute=10,
                                           hour=7,
                                           day=5,
                                           month=3,
                                           year=2012),
                         begin)
        self.assertEqual(datetime.datetime(minute=10,
                                           hour=8,
                                           day=5,
                                           month=3,
                                           year=2012),
                         end)

    def test_hour_with_offset_after_current(self):
        begin, end = utils.last_completed_audit_period(unit='hour@30')
        self.assertEqual(datetime.datetime(minute=30,
                                           hour=6,
                                           day=5,
                                           month=3,
                                           year=2012),
                         begin)
        self.assertEqual(datetime.datetime(minute=30,
                                           hour=7,
                                           day=5,
                                           month=3,
                                           year=2012),
                         end)

    def test_day(self):
        begin, end = utils.last_completed_audit_period(unit='day')
        self.assertEqual(datetime.datetime(day=4, month=3, year=2012), begin)
        self.assertEqual(datetime.datetime(day=5, month=3, year=2012), end)

    def test_day_with_offset_before_current(self):
        begin, end = utils.last_completed_audit_period(unit='day@6')
        self.assertEqual(datetime.datetime(hour=6, day=4, month=3, year=2012),
                         begin)
        self.assertEqual(datetime.datetime(hour=6, day=5, month=3, year=2012),
                         end)

    def test_day_with_offset_after_current(self):
        begin, end = utils.last_completed_audit_period(unit='day@10')
        self.assertEqual(datetime.datetime(hour=10, day=3, month=3, year=2012),
                         begin)
        self.assertEqual(datetime.datetime(hour=10, day=4, month=3, year=2012),
                         end)

    def test_month(self):
        begin, end = utils.last_completed_audit_period(unit='month')
        self.assertEqual(datetime.datetime(day=1, month=2, year=2012), begin)
        self.assertEqual(datetime.datetime(day=1, month=3, year=2012), end)

    def test_month_with_offset_before_current(self):
        begin, end = utils.last_completed_audit_period(unit='month@2')
        self.assertEqual(datetime.datetime(day=2, month=2, year=2012), begin)
        self.assertEqual(datetime.datetime(day=2, month=3, year=2012), end)

    def test_month_with_offset_after_current(self):
        begin, end = utils.last_completed_audit_period(unit='month@15')
        self.assertEqual(datetime.datetime(day=15, month=1, year=2012), begin)
        self.assertEqual(datetime.datetime(day=15, month=2, year=2012), end)

    @mock.patch('oslo_utils.timeutils.utcnow',
                return_value=datetime.datetime(day=1,
                                               month=1,
                                               year=2012))
    def test_month_jan_day_first(self, mock_utcnow):
        begin, end = utils.last_completed_audit_period(unit='month')
        self.assertEqual(datetime.datetime(day=1, month=11, year=2011), begin)
        self.assertEqual(datetime.datetime(day=1, month=12, year=2011), end)

    @mock.patch('oslo_utils.timeutils.utcnow',
                return_value=datetime.datetime(day=2,
                                               month=1,
                                               year=2012))
    def test_month_jan_day_not_first(self, mock_utcnow):
        begin, end = utils.last_completed_audit_period(unit='month')
        self.assertEqual(datetime.datetime(day=1, month=12, year=2011), begin)
        self.assertEqual(datetime.datetime(day=1, month=1, year=2012), end)

    def test_year(self):
        begin, end = utils.last_completed_audit_period(unit='year')
        self.assertEqual(datetime.datetime(day=1, month=1, year=2011), begin)
        self.assertEqual(datetime.datetime(day=1, month=1, year=2012), end)

    def test_year_with_offset_before_current(self):
        begin, end = utils.last_completed_audit_period(unit='year@2')
        self.assertEqual(datetime.datetime(day=1, month=2, year=2011), begin)
        self.assertEqual(datetime.datetime(day=1, month=2, year=2012), end)

    def test_year_with_offset_after_current(self):
        begin, end = utils.last_completed_audit_period(unit='year@6')
        self.assertEqual(datetime.datetime(day=1, month=6, year=2010), begin)
        self.assertEqual(datetime.datetime(day=1, month=6, year=2011), end)

    def test_invalid_unit(self):
        self.assertRaises(ValueError,
                          utils.last_completed_audit_period,
                          unit='invalid_unit')

    @mock.patch('cinder.utils.CONF')
    def test_uses_conf_unit(self, mock_conf):
        mock_conf.volume_usage_audit_period = 'hour'
        begin1, end1 = utils.last_completed_audit_period()
        self.assertEqual(60.0 * 60, (end1 - begin1).total_seconds())

        mock_conf.volume_usage_audit_period = 'day'
        begin2, end2 = utils.last_completed_audit_period()

        self.assertEqual(60.0 * 60 * 24, (end2 - begin2).total_seconds())


class BrickUtils(test.TestCase):
    """Unit test to test the brick utility wrapper functions."""

    @mock.patch('cinder.volume.volume_utils.CONF')
    @mock.patch('os_brick.initiator.connector.get_connector_properties')
    @mock.patch('cinder.utils.get_root_helper')
    def test_brick_get_connector_properties(self, mock_helper, mock_get,
                                            mock_conf):
        mock_conf.my_ip = '1.2.3.4'
        output = volume_utils.brick_get_connector_properties()
        mock_helper.assert_called_once_with()
        mock_get.assert_called_once_with(mock_helper.return_value, '1.2.3.4',
                                         False, False)
        self.assertEqual(mock_get.return_value, output)

    @mock.patch('os_brick.initiator.connector.InitiatorConnector.factory')
    @mock.patch('cinder.utils.get_root_helper')
    def test_brick_get_connector(self, mock_helper, mock_factory):
        output = volume_utils.brick_get_connector('protocol')
        mock_helper.assert_called_once_with()
        self.assertEqual(mock_factory.return_value, output)
        mock_factory.assert_called_once_with(
            'protocol', mock_helper.return_value, driver=None,
            use_multipath=False, device_scan_attempts=3)

    @mock.patch('os_brick.encryptors.get_volume_encryptor')
    @mock.patch('cinder.utils.get_root_helper')
    def test_brick_attach_volume_encryptor(self, mock_helper,
                                           mock_get_encryptor):
        attach_info = {'device': {'path': 'dev/sda'},
                       'conn': {'driver_volume_type': 'iscsi',
                                'data': {}, }}
        encryption = {'encryption_key_id': fake.ENCRYPTION_KEY_ID}
        ctxt = mock.Mock(name='context')
        mock_encryptor = mock.Mock()
        mock_get_encryptor.return_value = mock_encryptor
        volume_utils.brick_attach_volume_encryptor(ctxt,
                                                   attach_info,
                                                   encryption)

        connection_info = attach_info['conn']
        connection_info['data']['device_path'] = attach_info['device']['path']
        mock_helper.assert_called_once_with()
        mock_get_encryptor.assert_called_once_with(
            root_helper=mock_helper.return_value,
            connection_info=connection_info,
            keymgr=mock.ANY,
            **encryption)
        mock_encryptor.attach_volume.assert_called_once_with(
            ctxt, **encryption)

    @mock.patch('os_brick.encryptors.get_volume_encryptor')
    @mock.patch('cinder.utils.get_root_helper')
    def test_brick_detach_volume_encryptor(self,
                                           mock_helper, mock_get_encryptor):
        attach_info = {'device': {'path': 'dev/sda'},
                       'conn': {'driver_volume_type': 'iscsi',
                                'data': {}, }}
        encryption = {'encryption_key_id': fake.ENCRYPTION_KEY_ID}
        mock_encryptor = mock.Mock()
        mock_get_encryptor.return_value = mock_encryptor
        volume_utils.brick_detach_volume_encryptor(attach_info, encryption)

        mock_helper.assert_called_once_with()
        connection_info = attach_info['conn']
        connection_info['data']['device_path'] = attach_info['device']['path']
        mock_get_encryptor.assert_called_once_with(
            root_helper=mock_helper.return_value,
            connection_info=connection_info,
            keymgr=mock.ANY,
            **encryption)
        mock_encryptor.detach_volume.assert_called_once_with(**encryption)


class StringLengthTestCase(test.TestCase):
    def test_check_string_length(self):
        self.assertIsNone(utils.check_string_length(
                          'test', 'name', max_length=255))
        self.assertRaises(exception.InvalidInput,
                          utils.check_string_length,
                          11, 'name', max_length=255)
        self.assertRaises(exception.InvalidInput,
                          utils.check_string_length,
                          '', 'name', min_length=1)
        self.assertRaises(exception.InvalidInput,
                          utils.check_string_length,
                          'a' * 256, 'name', max_length=255)
        self.assertRaises(exception.InvalidInput,
                          utils.check_string_length,
                          dict(), 'name', max_length=255)


class AddVisibleAdminMetadataTestCase(test.TestCase):
    def test_add_visible_admin_metadata_visible_key_only(self):
        admin_metadata = [{"key": "invisible_key", "value": "invisible_value"},
                          {"key": "readonly", "value": "visible"},
                          {"key": "attached_mode", "value": "visible"}]
        metadata = [{"key": "key", "value": "value"},
                    {"key": "readonly", "value": "existing"}]
        volume = {'volume_admin_metadata': admin_metadata,
                  'volume_metadata': metadata}
        api_utils.add_visible_admin_metadata(volume)
        self.assertEqual([{"key": "key", "value": "value"},
                          {"key": "readonly", "value": "visible"},
                          {"key": "attached_mode", "value": "visible"}],
                         volume['volume_metadata'])

        admin_metadata = {"invisible_key": "invisible_value",
                          "readonly": "visible",
                          "attached_mode": "visible"}
        metadata = {"key": "value", "readonly": "existing"}
        volume = {'admin_metadata': admin_metadata,
                  'metadata': metadata}
        api_utils.add_visible_admin_metadata(volume)
        self.assertEqual({'key': 'value',
                          'attached_mode': 'visible',
                          'readonly': 'visible'},
                         volume['metadata'])

    def test_add_visible_admin_metadata_no_visible_keys(self):
        admin_metadata = [
            {"key": "invisible_key1", "value": "invisible_value1"},
            {"key": "invisible_key2", "value": "invisible_value2"},
            {"key": "invisible_key3", "value": "invisible_value3"}]
        metadata = [{"key": "key", "value": "value"}]
        volume = {'volume_admin_metadata': admin_metadata,
                  'volume_metadata': metadata}
        api_utils.add_visible_admin_metadata(volume)
        self.assertEqual([{"key": "key", "value": "value"}],
                         volume['volume_metadata'])

        admin_metadata = {"invisible_key1": "invisible_value1",
                          "invisible_key2": "invisible_value2",
                          "invisible_key3": "invisible_value3"}
        metadata = {"key": "value"}
        volume = {'admin_metadata': admin_metadata,
                  'metadata': metadata}
        api_utils.add_visible_admin_metadata(volume)
        self.assertEqual({'key': 'value'}, volume['metadata'])

    def test_add_visible_admin_metadata_no_existing_metadata(self):
        admin_metadata = [{"key": "invisible_key", "value": "invisible_value"},
                          {"key": "readonly", "value": "visible"},
                          {"key": "attached_mode", "value": "visible"}]
        volume = {'volume_admin_metadata': admin_metadata}
        api_utils.add_visible_admin_metadata(volume)
        self.assertEqual({'attached_mode': 'visible', 'readonly': 'visible'},
                         volume['metadata'])

        admin_metadata = {"invisible_key": "invisible_value",
                          "readonly": "visible",
                          "attached_mode": "visible"}
        volume = {'admin_metadata': admin_metadata}
        api_utils.add_visible_admin_metadata(volume)
        self.assertEqual({'attached_mode': 'visible', 'readonly': 'visible'},
                         volume['metadata'])


class InvalidFilterTestCase(test.TestCase):
    def test_admin_allows_all_options(self):
        ctxt = mock.Mock(name='context')
        ctxt.is_admin = True

        filters = {'allowed1': None, 'allowed2': None, 'not_allowed1': None}
        fltrs_orig = {'allowed1': None, 'allowed2': None, 'not_allowed1': None}
        allowed_search_options = ('allowed1', 'allowed2')
        allowed_orig = ('allowed1', 'allowed2')

        api_utils.remove_invalid_filter_options(ctxt, filters,
                                                allowed_search_options)

        self.assertEqual(allowed_orig, allowed_search_options)
        self.assertEqual(fltrs_orig, filters)

    def test_admin_allows_some_options(self):
        ctxt = mock.Mock(name='context')
        ctxt.is_admin = False

        filters = {'allowed1': None, 'allowed2': None, 'not_allowed1': None}
        fltrs_orig = {'allowed1': None, 'allowed2': None, 'not_allowed1': None}
        allowed_search_options = ('allowed1', 'allowed2')
        allowed_orig = ('allowed1', 'allowed2')

        api_utils.remove_invalid_filter_options(ctxt, filters,
                                                allowed_search_options)

        self.assertEqual(allowed_orig, allowed_search_options)
        self.assertNotEqual(fltrs_orig, filters)
        self.assertEqual(allowed_search_options, tuple(sorted(filters.keys())))


class IsBlkDeviceTestCase(test.TestCase):
    @mock.patch('stat.S_ISBLK', return_value=True)
    @mock.patch('os.stat')
    def test_is_blk_device(self, mock_os_stat, mock_S_ISBLK):
        dev = 'some_device'
        self.assertTrue(utils.is_blk_device(dev))

    @mock.patch('stat.S_ISBLK', return_value=False)
    @mock.patch('os.stat')
    def test_not_is_blk_device(self, mock_os_stat, mock_S_ISBLK):
        dev = 'not_some_device'
        self.assertFalse(utils.is_blk_device(dev))

    @mock.patch('stat.S_ISBLK', side_effect=Exception)
    @mock.patch('os.stat')
    def test_fail_is_blk_device(self, mock_os_stat, mock_S_ISBLK):
        dev = 'device_exception'
        self.assertFalse(utils.is_blk_device(dev))


class WrongException(Exception):
    pass


class TestRetryDecorator(test.TestCase):
    def test_no_retry_required(self):
        self.counter = 0

        with mock.patch('tenacity.nap.sleep') as mock_sleep:
            @utils.retry(exception.VolumeBackendAPIException,
                         interval=2,
                         retries=3,
                         backoff_rate=2)
            def succeeds():
                self.counter += 1
                return 'success'

            ret = succeeds()
            self.assertFalse(mock_sleep.called)
            self.assertEqual('success', ret)
            self.assertEqual(1, self.counter)

    def test_no_retry_required_random(self):
        self.counter = 0

        with mock.patch('tenacity.nap.sleep') as mock_sleep:
            @utils.retry(exception.VolumeBackendAPIException,
                         interval=2,
                         retries=3,
                         backoff_rate=2,
                         wait_random=True)
            def succeeds():
                self.counter += 1
                return 'success'

            ret = succeeds()
            self.assertFalse(mock_sleep.called)
            self.assertEqual('success', ret)
            self.assertEqual(1, self.counter)

    def test_retries_once(self):
        self.counter = 0
        interval = 2
        backoff_rate = 2
        retries = 3

        with mock.patch('tenacity.nap.sleep') as mock_sleep:
            @utils.retry(exception.VolumeBackendAPIException,
                         interval,
                         retries,
                         backoff_rate)
            def fails_once():
                self.counter += 1
                if self.counter < 2:
                    raise exception.VolumeBackendAPIException(data='fake')
                else:
                    return 'success'

            ret = fails_once()
            self.assertEqual('success', ret)
            self.assertEqual(2, self.counter)
            self.assertEqual(1, mock_sleep.call_count)
            mock_sleep.assert_called_with(interval)

    def test_retries_once_random(self):
        self.counter = 0
        interval = 2
        backoff_rate = 2
        retries = 3

        with mock.patch('tenacity.nap.sleep') as mock_sleep:
            @utils.retry(exception.VolumeBackendAPIException,
                         interval,
                         retries,
                         backoff_rate,
                         wait_random=True)
            def fails_once():
                self.counter += 1
                if self.counter < 2:
                    raise exception.VolumeBackendAPIException(data='fake')
                else:
                    return 'success'

            ret = fails_once()
            self.assertEqual('success', ret)
            self.assertEqual(2, self.counter)
            self.assertEqual(1, mock_sleep.call_count)
            self.assertTrue(mock_sleep.called)

    def test_limit_is_reached(self):
        self.counter = 0
        retries = 3
        interval = 2
        backoff_rate = 4

        with mock.patch('tenacity.nap.sleep') as mock_sleep:
            @utils.retry(exception.VolumeBackendAPIException,
                         interval,
                         retries,
                         backoff_rate)
            def always_fails():
                self.counter += 1
                raise exception.VolumeBackendAPIException(data='fake')

            self.assertRaises(exception.VolumeBackendAPIException,
                              always_fails)
            self.assertEqual(retries, self.counter)

            expected_sleep_arg = []
            for i in range(retries):
                if i > 0:
                    interval *= (backoff_rate ** (i - 1))
                    expected_sleep_arg.append(float(interval))

            mock_sleep.assert_has_calls(
                list(map(mock.call, expected_sleep_arg)))

    def test_wrong_exception_no_retry(self):

        with mock.patch('tenacity.nap.sleep') as mock_sleep:
            @utils.retry(exception.VolumeBackendAPIException)
            def raise_unexpected_error():
                raise WrongException("wrong exception")

            self.assertRaises(WrongException, raise_unexpected_error)
            self.assertFalse(mock_sleep.called)

    @mock.patch('tenacity.nap.sleep')
    def test_retry_exit_code(self, sleep_mock):

        exit_code = 5
        exception = utils.processutils.ProcessExecutionError

        @utils.retry(retry=utils.retry_if_exit_code, retry_param=exit_code)
        def raise_retriable_exit_code():
            raise exception(exit_code=exit_code)

        self.assertRaises(exception, raise_retriable_exit_code)
        self.assertEqual(2, sleep_mock.call_count)
        sleep_mock.assert_has_calls([mock.call(1), mock.call(2)])

    @mock.patch('tenacity.nap.sleep')
    def test_retry_exit_code_non_retriable(self, sleep_mock):

        exit_code = 5
        exception = utils.processutils.ProcessExecutionError

        @utils.retry(retry=utils.retry_if_exit_code, retry_param=exit_code)
        def raise_non_retriable_exit_code():
            raise exception(exit_code=exit_code + 1)

        self.assertRaises(exception, raise_non_retriable_exit_code)
        sleep_mock.assert_not_called()


@ddt.ddt
class TestCalculateVirtualFree(test.TestCase):
    @ddt.data(
        {'total': 30.01, 'free': 28.01, 'provisioned': 2.0, 'max_ratio': 1.0,
         'thin_support': False, 'thick_support': True,
         'is_thin_lun': False, 'expected': 27.01},
        {'total': 20.01, 'free': 18.01, 'provisioned': 2.0, 'max_ratio': 2.0,
         'thin_support': True, 'thick_support': False,
         'is_thin_lun': True, 'expected': 37.02},
        {'total': 20.01, 'free': 18.01, 'provisioned': 2.0, 'max_ratio': 2.0,
         'thin_support': True, 'thick_support': True,
         'is_thin_lun': True, 'expected': 37.02},
        {'total': 30.01, 'free': 28.01, 'provisioned': 2.0, 'max_ratio': 2.0,
         'thin_support': True, 'thick_support': True,
         'is_thin_lun': False, 'expected': 27.01},
    )
    @ddt.unpack
    def test_utils_calculate_virtual_free_capacity_provision_type(
            self, total, free, provisioned, max_ratio, thin_support,
            thick_support, is_thin_lun, expected):
        host_stat = {'total_capacity_gb': total,
                     'free_capacity_gb': free,
                     'provisioned_capacity_gb': provisioned,
                     'max_over_subscription_ratio': max_ratio,
                     'thin_provisioning_support': thin_support,
                     'thick_provisioning_support': thick_support,
                     'reserved_percentage': 5}

        free_capacity = utils.calculate_virtual_free_capacity(
            host_stat['total_capacity_gb'],
            host_stat['free_capacity_gb'],
            host_stat['provisioned_capacity_gb'],
            host_stat['thin_provisioning_support'],
            host_stat['max_over_subscription_ratio'],
            host_stat['reserved_percentage'],
            is_thin_lun)

        self.assertEqual(expected, free_capacity)


class Comparable(utils.ComparableMixin):
    def __init__(self, value):
        self.value = value

    def _cmpkey(self):
        return self.value


class TestComparableMixin(test.TestCase):

    def setUp(self):
        super(TestComparableMixin, self).setUp()
        self.one = Comparable(1)
        self.two = Comparable(2)

    def test_lt(self):
        self.assertTrue(self.one < self.two)
        self.assertFalse(self.two < self.one)
        self.assertFalse(self.one < self.one)

    def test_le(self):
        self.assertTrue(self.one <= self.two)
        self.assertFalse(self.two <= self.one)
        self.assertTrue(self.one <= self.one)

    def test_eq(self):
        self.assertFalse(self.one == self.two)
        self.assertFalse(self.two == self.one)
        self.assertTrue(self.one == self.one)

    def test_ge(self):
        self.assertFalse(self.one >= self.two)
        self.assertTrue(self.two >= self.one)
        self.assertTrue(self.one >= self.one)

    def test_gt(self):
        self.assertFalse(self.one > self.two)
        self.assertTrue(self.two > self.one)
        self.assertFalse(self.one > self.one)

    def test_ne(self):
        self.assertTrue(self.one != self.two)
        self.assertTrue(self.two != self.one)
        self.assertFalse(self.one != self.one)

    def test_compare(self):
        self.assertEqual(NotImplemented,
                         self.one._compare(1, self.one._cmpkey))


@ddt.ddt
class TestValidateInteger(test.TestCase):

    @ddt.data(
        (2 ** 31) + 1,  # More than max value
        -12,  # Less than min value
        2.05,  # Float value
        "12.05",  # Float value in string format
        "should be int",  # String
        u"test"  # String in unicode format
    )
    def test_validate_integer_raise_assert(self, value):
        self.assertRaises(webob.exc.HTTPBadRequest,
                          api_utils.validate_integer,
                          value, 'limit', min_value=-1, max_value=(2 ** 31))

    @ddt.data(
        "123",  # integer in string format
        123,  # integer
        u"123"  # integer in unicode format
    )
    def test_validate_integer(self, value):
        res = api_utils.validate_integer(value, 'limit', min_value=-1,
                                         max_value=(2 ** 31))
        self.assertEqual(123, res)


@ddt.ddt
class TestNotificationShortCircuit(test.TestCase):
    def test_do_nothing_getter(self):
        """Test any attribute will always return the same instance (self)."""
        donothing = utils.DoNothing()
        self.assertIs(donothing, donothing.anyname)

    def test_do_nothing_caller(self):
        """Test calling the object will always return the same instance."""
        donothing = utils.DoNothing()
        self.assertIs(donothing, donothing())

    def test_do_nothing_json_serializable(self):
        """Test calling the object will always return the same instance."""
        donothing = utils.DoNothing()
        self.assertEqual('""', json.dumps(donothing))

    @utils.if_notifications_enabled
    def _decorated_method(self):
        return mock.sentinel.success

    def test_if_notification_enabled_when_enabled(self):
        """Test method is called when notifications are enabled."""
        result = self._decorated_method()
        self.assertEqual(mock.sentinel.success, result)

    @ddt.data([], ['noop'], ['noop', 'noop'])
    def test_if_notification_enabled_when_disabled(self, driver):
        """Test method is not called when notifications are disabled."""
        self.override_config('driver', driver,
                             group='oslo_messaging_notifications')
        result = self._decorated_method()
        self.assertEqual(utils.DO_NOTHING, result)


@ddt.ddt
class TestLogLevels(test.TestCase):
    @ddt.data(None, '', 'wronglevel')
    def test_get_log_method_invalid(self, level):
        self.assertRaises(exception.InvalidInput,
                          utils.get_log_method, level)

    @ddt.data(('info', utils.logging.INFO), ('warning', utils.logging.WARNING),
              ('INFO', utils.logging.INFO), ('wArNiNg', utils.logging.WARNING),
              ('error', utils.logging.ERROR), ('debug', utils.logging.DEBUG))
    @ddt.unpack
    def test_get_log_method(self, level, logger):
        result = utils.get_log_method(level)
        self.assertEqual(logger, result)

    def test_get_log_levels(self):
        levels = utils.get_log_levels('cinder.api')
        self.assertTrue(len(levels) > 1)
        self.assertSetEqual({'INFO'}, set(levels.values()))

    @ddt.data(None, '', 'wronglevel')
    def test_set_log_levels_invalid(self, level):
        self.assertRaises(exception.InvalidInput,
                          utils.set_log_levels, '', level)

    def test_set_log_levels(self):
        prefix = 'cinder.utils'
        levels = utils.get_log_levels(prefix)

        utils.set_log_levels(prefix, 'debug')
        levels = utils.get_log_levels(prefix)
        self.assertEqual('DEBUG', levels[prefix])

        utils.set_log_levels(prefix, 'warning')
        levels = utils.get_log_levels(prefix)
        self.assertEqual('WARNING', levels[prefix])


@ddt.ddt
class TestCheckMetadataProperties(test.TestCase):
    @ddt.data(
        {'a': {'foo': 'bar'}},  # value is a nested dict
        {'a': 123},  # value is an integer
        {'a': 123.4},  # value is a float
        {'a': True},  # value is a bool
        {'a': ('foo', 'bar')},  # value is a tuple
        {'a': []},  # value is a list
        {'a': None}  # value is None
    )
    def test_metadata_value_not_string_raise(self, meta):
        self.assertRaises(exception.InvalidVolumeMetadata,
                          utils.check_metadata_properties,
                          meta)

    def test_metadata_value_not_dict_raise(self):
        meta = 123
        self.assertRaises(exception.InvalidInput,
                          utils.check_metadata_properties,
                          meta)


POOL_CAP1 = {'allocated_capacity_gb': 10, 'provisioned_capacity_gb': 10,
             'thin_provisioning_support': False, 'total_capacity_gb': 10,
             'free_capacity_gb': 10, 'max_over_subscription_ratio': 1.0}
POOL_CAP2 = {'allocated_capacity_gb': 10, 'provisioned_capacity_gb': 10,
             'thin_provisioning_support': True, 'total_capacity_gb': 100,
             'free_capacity_gb': 95, 'max_over_subscription_ratio': None}
POOL_CAP3 = {'allocated_capacity_gb': 0, 'provisioned_capacity_gb': 0,
             'thin_provisioning_support': True, 'total_capacity_gb': 100,
             'free_capacity_gb': 100, 'max_over_subscription_ratio': 'auto'}
POOL_CAP4 = {'allocated_capacity_gb': 100,
             'thin_provisioning_support': True, 'total_capacity_gb': 2500,
             'free_capacity_gb': 500, 'max_over_subscription_ratio': 'auto'}
POOL_CAP5 = {'allocated_capacity_gb': 10000,
             'thin_provisioning_support': True, 'total_capacity_gb': 2500,
             'free_capacity_gb': 0.1, 'max_over_subscription_ratio': 'auto'}
POOL_CAP6 = {'allocated_capacity_gb': 1000, 'provisioned_capacity_gb': 1010,
             'thin_provisioning_support': True, 'total_capacity_gb': 2500,
             'free_capacity_gb': 2500, 'max_over_subscription_ratio': 'auto'}
POOL_CAP7 = {'allocated_capacity_gb': 10, 'provisioned_capacity_gb': 10,
             'thin_provisioning_support': True, 'total_capacity_gb': 10,
             'free_capacity_gb': 10}
POOL_CAP8 = {'allocated_capacity_gb': 10, 'provisioned_capacity_gb': 10,
             'thin_provisioning_support': True, 'total_capacity_gb': 10,
             'free_capacity_gb': 10, 'max_over_subscription_ratio': '15.5'}
POOL_CAP9 = {'allocated_capacity_gb': 10, 'provisioned_capacity_gb': 10,
             'thin_provisioning_support': True, 'total_capacity_gb': 10,
             'free_capacity_gb': 'unknown',
             'max_over_subscription_ratio': '15.5'}
POOL_CAP10 = {'allocated_capacity_gb': 10, 'provisioned_capacity_gb': 10,
              'thin_provisioning_support': True,
              'total_capacity_gb': 'infinite', 'free_capacity_gb': 10,
              'max_over_subscription_ratio': '15.5'}


@ddt.ddt
class TestAutoMaxOversubscriptionRatio(test.TestCase):
    @ddt.data({'data': POOL_CAP1,
               'global_max_over_subscription_ratio': 'auto',
               'expected_result': 1.0},
              {'data': POOL_CAP2,
               'global_max_over_subscription_ratio': 'auto',
               'expected_result': 2.67},
              {'data': POOL_CAP3,
               'global_max_over_subscription_ratio': '20.0',
               'expected_result': 20},
              {'data': POOL_CAP4,
               'global_max_over_subscription_ratio': '20.0',
               'expected_result': 1.05},
              {'data': POOL_CAP5,
               'global_max_over_subscription_ratio': '10.0',
               'expected_result': 5.0},
              {'data': POOL_CAP6,
               'global_max_over_subscription_ratio': '20.0',
               'expected_result': 1011.0},
              {'data': POOL_CAP7,
               'global_max_over_subscription_ratio': 'auto',
               'expected_result': 11.0},
              {'data': POOL_CAP8,
               'global_max_over_subscription_ratio': '20.0',
               'expected_result': 15.5},
              {'data': POOL_CAP9,
               'global_max_over_subscription_ratio': '20.0',
               'expected_result': 1.0},
              {'data': POOL_CAP10,
               'global_max_over_subscription_ratio': '20.0',
               'expected_result': 1.0},
              )
    @ddt.unpack
    def test_calculate_max_over_subscription_ratio(
            self, data, expected_result, global_max_over_subscription_ratio):

        result = utils.calculate_max_over_subscription_ratio(
            data, global_max_over_subscription_ratio)
        # Just for sake of testing we reduce the float precision
        if result is not None:
            result = round(result, 2)
        self.assertEqual(expected_result, result)


@ddt.ddt
class LimitOperationsTestCase(test.TestCase):
    @ddt.data(1, 5)
    @mock.patch('contextlib.suppress')
    def test_semaphore_factory_no_limit(self, processes, mock_suppress):
        res = utils.semaphore_factory(0, processes)
        mock_suppress.assert_called_once_with()
        self.assertEqual(mock_suppress.return_value, res)

    @mock.patch('eventlet.Semaphore')
    def test_semaphore_factory_with_limit(self, mock_semaphore):
        max_operations = 15
        res = utils.semaphore_factory(max_operations, 1)
        mock_semaphore.assert_called_once_with(max_operations)
        self.assertEqual(mock_semaphore.return_value, res)

    @mock.patch('cinder.utils.Semaphore')
    def test_semaphore_factory_with_limit_and_workers(self, mock_semaphore):
        max_operations = 15
        processes = 5
        res = utils.semaphore_factory(max_operations, processes)
        mock_semaphore.assert_called_once_with(max_operations)
        self.assertEqual(mock_semaphore.return_value, res)

    @mock.patch('multiprocessing.Semaphore')
    @mock.patch('eventlet.tpool.execute')
    def test_semaphore(self, mock_exec, mock_semaphore):
        limit = 15
        res = utils.Semaphore(limit)
        self.assertEqual(limit, res.limit)

        mocked_semaphore = mock_semaphore.return_value
        self.assertEqual(mocked_semaphore, res.semaphore)
        mock_semaphore.assert_called_once_with(limit)

        with res:
            mock_exec.assert_called_once_with(mocked_semaphore.__enter__)
            mocked_semaphore.__exit__.assert_not_called()
        mocked_semaphore.__exit__.assert_called_once_with(None, None, None)


class TestKeystoneProjectGet(test.TestCase):
    class FakeProject(object):
        def __init__(self, id='foo', name=None):
            self.id = id
            self.name = name
            self.description = 'fake project description'
            self.domain_id = 'default'

    @mock.patch('keystoneclient.client.Client')
    def test_get_project_keystoneclient_v2(self, ksclient_class):
        self.context = context.RequestContext('fake_user', 'fake_proj_id')
        keystoneclient = ksclient_class.return_value
        keystoneclient.version = 'v2.0'
        returned_project = self.FakeProject(self.context.project_id, 'bar')
        keystoneclient.projects.get.return_value = returned_project
        expected_project = api_utils.GenericProjectInfo(
            self.context.project_id, 'v2.0', domain_id='default', name='bar',
            description='fake project description')
        project = api_utils.get_project(
            self.context, self.context.project_id)
        self.assertEqual(expected_project.__dict__, project.__dict__)

    @mock.patch('keystoneclient.client.Client')
    def test_get_project_keystoneclient_v3(self, ksclient_class):
        self.context = context.RequestContext('fake_user', 'fake_proj_id')
        keystoneclient = ksclient_class.return_value
        keystoneclient.version = 'v3'
        returned_project = self.FakeProject(self.context.project_id, 'bar')
        keystoneclient.projects.get.return_value = returned_project
        expected_project = api_utils.GenericProjectInfo(
            self.context.project_id, 'v3', domain_id='default', name='bar',
            description='fake project description')
        project = api_utils.get_project(
            self.context, self.context.project_id)
        self.assertEqual(expected_project.__dict__, project.__dict__)


class TestCleanFileLocks(test.TestCase):

    @mock.patch('cinder.utils.LOG.warning')
    @mock.patch('cinder.utils.synchronized_remove')
    def test_clean_volume_file_locks(self, mock_remove, mock_log):
        driver = mock.Mock()

        utils.clean_volume_file_locks('UUID', driver)

        self.assertEqual(3, mock_remove.call_count)
        mock_remove.assert_has_calls([mock.call('UUID-delete_volume'),
                                      mock.call('UUID'),
                                      mock.call('UUID-detach_volume')])
        driver.clean_volume_file_locks.assert_called_once_with('UUID')
        mock_log.assert_not_called()

    @mock.patch('cinder.utils.LOG.warning')
    @mock.patch('cinder.utils.synchronized_remove')
    def test_clean_volume_file_locks_errors(self, mock_remove, mock_log):
        driver = mock.Mock()
        driver.clean_volume_file_locks.side_effect = Exception
        mock_remove.side_effect = [None, Exception, None]

        utils.clean_volume_file_locks('UUID', driver)

        self.assertEqual(3, mock_remove.call_count)
        mock_remove.assert_has_calls([mock.call('UUID-delete_volume'),
                                      mock.call('UUID'),
                                      mock.call('UUID-detach_volume')])
        driver.clean_volume_file_locks.assert_called_once_with('UUID')
        self.assertEqual(2, mock_log.call_count)

    @mock.patch('cinder.utils.LOG.warning')
    @mock.patch('cinder.utils.synchronized_remove')
    def test_clean_snapshot_file_locks(self, mock_remove, mock_log):
        driver = mock.Mock()

        utils.clean_snapshot_file_locks('UUID', driver)

        mock_remove.assert_called_once_with('UUID-delete_snapshot')
        driver.clean_snapshot_file_locks.assert_called_once_with('UUID')
        mock_log.assert_not_called()

    @mock.patch('cinder.utils.LOG.warning')
    @mock.patch('cinder.utils.synchronized_remove')
    def test_clean_snapshot_file_locks_failures(self, mock_remove, mock_log):
        driver = mock.Mock()
        driver.clean_snapshot_file_locks.side_effect = Exception
        mock_remove.side_effect = Exception

        utils.clean_snapshot_file_locks('UUID', driver)

        mock_remove.assert_called_once_with('UUID-delete_snapshot')
        driver.clean_snapshot_file_locks.assert_called_once_with('UUID')
        self.assertEqual(2, mock_log.call_count)

    @mock.patch('cinder.coordination.synchronized_remove')
    def test_api_clean_volume_file_locks(self, mock_remove):
        utils.api_clean_volume_file_locks('UUID')
        mock_remove.assert_called_once_with('attachment_update-UUID-*')
