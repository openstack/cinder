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
import hashlib
import os
import time
import uuid

import mock
from oslo_concurrency import processutils as putils
from oslo_config import cfg
from oslo_utils import timeutils
import paramiko
import six

import cinder
from cinder import exception
from cinder import ssh_utils
from cinder import test
from cinder import utils


CONF = cfg.CONF


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


class GetFromPathTestCase(test.TestCase):
    def test_tolerates_nones(self):
        f = utils.get_from_path

        input = []
        self.assertEqual([], f(input, "a"))
        self.assertEqual([], f(input, "a/b"))
        self.assertEqual([], f(input, "a/b/c"))

        input = [None]
        self.assertEqual([], f(input, "a"))
        self.assertEqual([], f(input, "a/b"))
        self.assertEqual([], f(input, "a/b/c"))

        input = [{'a': None}]
        self.assertEqual([], f(input, "a"))
        self.assertEqual([], f(input, "a/b"))
        self.assertEqual([], f(input, "a/b/c"))

        input = [{'a': {'b': None}}]
        self.assertEqual([{'b': None}], f(input, "a"))
        self.assertEqual([], f(input, "a/b"))
        self.assertEqual([], f(input, "a/b/c"))

        input = [{'a': {'b': {'c': None}}}]
        self.assertEqual([{'b': {'c': None}}], f(input, "a"))
        self.assertEqual([{'c': None}], f(input, "a/b"))
        self.assertEqual([], f(input, "a/b/c"))

        input = [{'a': {'b': {'c': None}}}, {'a': None}]
        self.assertEqual([{'b': {'c': None}}], f(input, "a"))
        self.assertEqual([{'c': None}], f(input, "a/b"))
        self.assertEqual([], f(input, "a/b/c"))

        input = [{'a': {'b': {'c': None}}}, {'a': {'b': None}}]
        self.assertEqual([{'b': {'c': None}}, {'b': None}], f(input, "a"))
        self.assertEqual([{'c': None}], f(input, "a/b"))
        self.assertEqual([], f(input, "a/b/c"))

    def test_does_select(self):
        f = utils.get_from_path

        input = [{'a': 'a_1'}]
        self.assertEqual(['a_1'], f(input, "a"))
        self.assertEqual([], f(input, "a/b"))
        self.assertEqual([], f(input, "a/b/c"))

        input = [{'a': {'b': 'b_1'}}]
        self.assertEqual([{'b': 'b_1'}], f(input, "a"))
        self.assertEqual(['b_1'], f(input, "a/b"))
        self.assertEqual([], f(input, "a/b/c"))

        input = [{'a': {'b': {'c': 'c_1'}}}]
        self.assertEqual([{'b': {'c': 'c_1'}}], f(input, "a"))
        self.assertEqual([{'c': 'c_1'}], f(input, "a/b"))
        self.assertEqual(['c_1'], f(input, "a/b/c"))

        input = [{'a': {'b': {'c': 'c_1'}}}, {'a': None}]
        self.assertEqual([{'b': {'c': 'c_1'}}], f(input, "a"))
        self.assertEqual([{'c': 'c_1'}], f(input, "a/b"))
        self.assertEqual(['c_1'], f(input, "a/b/c"))

        input = [{'a': {'b': {'c': 'c_1'}}},
                 {'a': {'b': None}}]
        self.assertEqual([{'b': {'c': 'c_1'}}, {'b': None}], f(input, "a"))
        self.assertEqual([{'c': 'c_1'}], f(input, "a/b"))
        self.assertEqual(['c_1'], f(input, "a/b/c"))

        input = [{'a': {'b': {'c': 'c_1'}}},
                 {'a': {'b': {'c': 'c_2'}}}]
        self.assertEqual([{'b': {'c': 'c_1'}}, {'b': {'c': 'c_2'}}],
                         f(input, "a"))
        self.assertEqual([{'c': 'c_1'}, {'c': 'c_2'}], f(input, "a/b"))
        self.assertEqual(['c_1', 'c_2'], f(input, "a/b/c"))

        self.assertEqual([], f(input, "a/b/c/d"))
        self.assertEqual([], f(input, "c/a/b/d"))
        self.assertEqual([], f(input, "i/r/t"))

    def test_flattens_lists(self):
        f = utils.get_from_path

        input = [{'a': [1, 2, 3]}]
        self.assertEqual([1, 2, 3], f(input, "a"))
        self.assertEqual([], f(input, "a/b"))
        self.assertEqual([], f(input, "a/b/c"))

        input = [{'a': {'b': [1, 2, 3]}}]
        self.assertEqual([{'b': [1, 2, 3]}], f(input, "a"))
        self.assertEqual([1, 2, 3], f(input, "a/b"))
        self.assertEqual([], f(input, "a/b/c"))

        input = [{'a': {'b': [1, 2, 3]}}, {'a': {'b': [4, 5, 6]}}]
        self.assertEqual([1, 2, 3, 4, 5, 6], f(input, "a/b"))
        self.assertEqual([], f(input, "a/b/c"))

        input = [{'a': [{'b': [1, 2, 3]}, {'b': [4, 5, 6]}]}]
        self.assertEqual([1, 2, 3, 4, 5, 6], f(input, "a/b"))
        self.assertEqual([], f(input, "a/b/c"))

        input = [{'a': [1, 2, {'b': 'b_1'}]}]
        self.assertEqual([1, 2, {'b': 'b_1'}], f(input, "a"))
        self.assertEqual(['b_1'], f(input, "a/b"))

    def test_bad_xpath(self):
        f = utils.get_from_path

        self.assertRaises(exception.Error, f, [], None)
        self.assertRaises(exception.Error, f, [], "")
        self.assertRaises(exception.Error, f, [], "/")
        self.assertRaises(exception.Error, f, [], "/a")
        self.assertRaises(exception.Error, f, [], "/a/")
        self.assertRaises(exception.Error, f, [], "//")
        self.assertRaises(exception.Error, f, [], "//a")
        self.assertRaises(exception.Error, f, [], "a//a")
        self.assertRaises(exception.Error, f, [], "a//a/")
        self.assertRaises(exception.Error, f, [], "a/a/")

    def test_real_failure1(self):
        # Real world failure case...
        #  We weren't coping when the input was a Dictionary instead of a List
        # This led to test_accepts_dictionaries
        f = utils.get_from_path

        inst = {'fixed_ip': {'floating_ips': [{'address': '1.2.3.4'}],
                             'address': '192.168.0.3'},
                'hostname': ''}

        private_ips = f(inst, 'fixed_ip/address')
        public_ips = f(inst, 'fixed_ip/floating_ips/address')
        self.assertEqual(['192.168.0.3'], private_ips)
        self.assertEqual(['1.2.3.4'], public_ips)

    def test_accepts_dictionaries(self):
        f = utils.get_from_path

        input = {'a': [1, 2, 3]}
        self.assertEqual([1, 2, 3], f(input, "a"))
        self.assertEqual([], f(input, "a/b"))
        self.assertEqual([], f(input, "a/b/c"))

        input = {'a': {'b': [1, 2, 3]}}
        self.assertEqual([{'b': [1, 2, 3]}], f(input, "a"))
        self.assertEqual([1, 2, 3], f(input, "a/b"))
        self.assertEqual([], f(input, "a/b/c"))

        input = {'a': [{'b': [1, 2, 3]}, {'b': [4, 5, 6]}]}
        self.assertEqual([1, 2, 3, 4, 5, 6], f(input, "a/b"))
        self.assertEqual([], f(input, "a/b/c"))

        input = {'a': [1, 2, {'b': 'b_1'}]}
        self.assertEqual([1, 2, {'b': 'b_1'}], f(input, "a"))
        self.assertEqual(['b_1'], f(input, "a/b"))


class GenericUtilsTestCase(test.TestCase):

    @mock.patch('os.path.exists', return_value=True)
    def test_find_config(self, mock_exists):
        path = '/etc/cinder/cinder.conf'
        cfgpath = utils.find_config(path)
        self.assertEqual(path, cfgpath)

        mock_exists.return_value = False
        self.assertRaises(exception.ConfigNotFound,
                          utils.find_config,
                          path)

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

    def test_is_int_like(self):
        self.assertTrue(utils.is_int_like(1))
        self.assertTrue(utils.is_int_like(-1))
        self.assertTrue(utils.is_int_like(0b1))
        self.assertTrue(utils.is_int_like(0o1))
        self.assertTrue(utils.is_int_like(0x1))
        self.assertTrue(utils.is_int_like('1'))
        self.assertFalse(utils.is_int_like(1.0))
        self.assertFalse(utils.is_int_like('abc'))

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

    def test_require_driver_intialized(self):
        driver = mock.Mock()
        driver.initialized = True
        utils.require_driver_initialized(driver)

        driver.initialized = False
        self.assertRaises(exception.DriverNotInitialized,
                          utils.require_driver_initialized,
                          driver)

    def test_hostname_unicode_sanitization(self):
        hostname = u"\u7684.test.example.com"
        self.assertEqual("test.example.com",
                         utils.sanitize_hostname(hostname))

    def test_hostname_sanitize_periods(self):
        hostname = "....test.example.com..."
        self.assertEqual("test.example.com",
                         utils.sanitize_hostname(hostname))

    def test_hostname_sanitize_dashes(self):
        hostname = "----test.example.com---"
        self.assertEqual("test.example.com",
                         utils.sanitize_hostname(hostname))

    def test_hostname_sanitize_characters(self):
        hostname = "(#@&$!(@*--#&91)(__=+--test-host.example!!.com-0+"
        self.assertEqual("91----test-host.example.com-0",
                         utils.sanitize_hostname(hostname))

    def test_hostname_translate(self):
        hostname = "<}\x1fh\x10e\x08l\x02l\x05o\x12!{>"
        self.assertEqual("hello", utils.sanitize_hostname(hostname))

    def test_is_valid_boolstr(self):
        self.assertTrue(utils.is_valid_boolstr(True))
        self.assertTrue(utils.is_valid_boolstr('trUe'))
        self.assertTrue(utils.is_valid_boolstr(False))
        self.assertTrue(utils.is_valid_boolstr('faLse'))
        self.assertTrue(utils.is_valid_boolstr('yeS'))
        self.assertTrue(utils.is_valid_boolstr('nO'))
        self.assertTrue(utils.is_valid_boolstr('y'))
        self.assertTrue(utils.is_valid_boolstr('N'))
        self.assertTrue(utils.is_valid_boolstr(1))
        self.assertTrue(utils.is_valid_boolstr('1'))
        self.assertTrue(utils.is_valid_boolstr(0))
        self.assertTrue(utils.is_valid_boolstr('0'))

    def test_generate_glance_url(self):
        generated_url = utils.generate_glance_url()
        actual_url = "http://%s:%d" % (CONF.glance_host,
                                       CONF.glance_port)
        self.assertEqual(generated_url, actual_url)

    @mock.patch('os.path.join', side_effect=lambda x, y: '/'.join((x, y)))
    def test_make_dev_path(self, mock_join):
        self.assertEqual('/dev/xvda', utils.make_dev_path('xvda'))
        self.assertEqual('/dev/xvdb1', utils.make_dev_path('xvdb', 1))
        self.assertEqual('/foo/xvdc1', utils.make_dev_path('xvdc', 1, '/foo'))

    @mock.patch('cinder.utils.execute')
    def test_read_file_as_root(self, mock_exec):
        out = mock.Mock()
        err = mock.Mock()
        mock_exec.return_value = (out, err)
        test_filepath = '/some/random/path'
        output = utils.read_file_as_root(test_filepath)
        mock_exec.assert_called_once_with('cat', test_filepath,
                                          run_as_root=True)
        self.assertEqual(out, output)

    @mock.patch('cinder.utils.execute',
                side_effect=putils.ProcessExecutionError)
    def test_read_file_as_root_fails(self, mock_exec):
        test_filepath = '/some/random/path'
        self.assertRaises(exception.FileNotFound,
                          utils.read_file_as_root,
                          test_filepath)

    @mock.patch('oslo_utils.timeutils.utcnow')
    def test_service_is_up(self, mock_utcnow):
        fts_func = datetime.datetime.fromtimestamp
        fake_now = 1000
        down_time = 5

        self.flags(service_down_time=down_time)
        mock_utcnow.return_value = fts_func(fake_now)

        # Up (equal)
        service = {'updated_at': fts_func(fake_now - down_time),
                   'created_at': fts_func(fake_now - down_time)}
        result = utils.service_is_up(service)
        self.assertTrue(result)

        # Up
        service = {'updated_at': fts_func(fake_now - down_time + 1),
                   'created_at': fts_func(fake_now - down_time + 1)}
        result = utils.service_is_up(service)
        self.assertTrue(result)

        # Down
        service = {'updated_at': fts_func(fake_now - down_time - 1),
                   'created_at': fts_func(fake_now - down_time - 1)}
        result = utils.service_is_up(service)
        self.assertFalse(result)

    def test_safe_parse_xml(self):

        normal_body = ('<?xml version="1.0" ?>'
                       '<foo><bar><v1>hey</v1><v2>there</v2></bar></foo>')

        def killer_body():
            return (("""<!DOCTYPE x [
                    <!ENTITY a "%(a)s">
                    <!ENTITY b "%(b)s">
                    <!ENTITY c "%(c)s">]>
                <foo>
                    <bar>
                        <v1>%(d)s</v1>
                    </bar>
                </foo>""") % {
                'a': 'A' * 10,
                'b': '&a;' * 10,
                'c': '&b;' * 10,
                'd': '&c;' * 9999,
            }).strip()

        dom = utils.safe_minidom_parse_string(normal_body)
        # Some versions of minidom inject extra newlines so we ignore them
        result = str(dom.toxml()).replace('\n', '')
        self.assertEqual(normal_body, result)

        self.assertRaises(ValueError,
                          utils.safe_minidom_parse_string,
                          killer_body())

    def test_xhtml_escape(self):
        self.assertEqual('&quot;foo&quot;', utils.xhtml_escape('"foo"'))
        self.assertEqual('&apos;foo&apos;', utils.xhtml_escape("'foo'"))

    def test_hash_file(self):
        data = 'Mary had a little lamb, its fleece as white as snow'
        flo = six.StringIO(data)
        h1 = utils.hash_file(flo)
        h2 = hashlib.sha1(data).hexdigest()
        self.assertEqual(h1, h2)

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

    @mock.patch('paramiko.SSHClient')
    def test_create_channel(self, mock_client):
        test_width = 600
        test_height = 800
        mock_channel = mock.Mock()
        mock_client.invoke_shell.return_value = mock_channel
        utils.create_channel(mock_client, test_width, test_height)
        mock_client.invoke_shell.assert_called_once_with()
        mock_channel.resize_pty.assert_called_once_with(test_width,
                                                        test_height)

    @mock.patch('os.stat')
    def test_get_file_mode(self, mock_stat):
        class stat_result(object):
            st_mode = 0o777
            st_gid = 33333

        test_file = '/var/tmp/made_up_file'
        mock_stat.return_value = stat_result
        mode = utils.get_file_mode(test_file)
        self.assertEqual(mode, 0o777)
        mock_stat.assert_called_once_with(test_file)

    @mock.patch('os.stat')
    def test_get_file_gid(self, mock_stat):

        class stat_result(object):
            st_mode = 0o777
            st_gid = 33333

        test_file = '/var/tmp/made_up_file'
        mock_stat.return_value = stat_result
        gid = utils.get_file_gid(test_file)
        self.assertEqual(gid, 33333)
        mock_stat.assert_called_once_with(test_file)

    @mock.patch('cinder.utils.CONF')
    def test_get_root_helper(self, mock_conf):
        mock_conf.rootwrap_config = '/path/to/conf'
        self.assertEqual('sudo cinder-rootwrap /path/to/conf',
                         utils.get_root_helper())


class TemporaryChownTestCase(test.TestCase):
    @mock.patch('os.stat')
    @mock.patch('os.getuid', return_value=1234)
    @mock.patch('cinder.utils.execute')
    def test_get_uid(self, mock_exec, mock_getuid, mock_stat):
        mock_stat.return_value.st_uid = 5678
        test_filename = 'a_file'
        with utils.temporary_chown(test_filename):
            mock_exec.assert_called_once_with('chown', 1234, test_filename,
                                              run_as_root=True)
        mock_getuid.asset_called_once_with()
        mock_stat.assert_called_once_with(test_filename)
        calls = [mock.call('chown', 1234, test_filename, run_as_root=True),
                 mock.call('chown', 5678, test_filename, run_as_root=True)]
        mock_exec.assert_has_calls(calls)

    @mock.patch('os.stat')
    @mock.patch('os.getuid', return_value=1234)
    @mock.patch('cinder.utils.execute')
    def test_supplied_owner_uid(self, mock_exec, mock_getuid, mock_stat):
        mock_stat.return_value.st_uid = 5678
        test_filename = 'a_file'
        with utils.temporary_chown(test_filename, owner_uid=9101):
            mock_exec.assert_called_once_with('chown', 9101, test_filename,
                                              run_as_root=True)
        self.assertFalse(mock_getuid.called)
        mock_stat.assert_called_once_with(test_filename)
        calls = [mock.call('chown', 9101, test_filename, run_as_root=True),
                 mock.call('chown', 5678, test_filename, run_as_root=True)]
        mock_exec.assert_has_calls(calls)

    @mock.patch('os.stat')
    @mock.patch('os.getuid', return_value=5678)
    @mock.patch('cinder.utils.execute')
    def test_matching_uid(self, mock_exec, mock_getuid, mock_stat):
        mock_stat.return_value.st_uid = 5678
        test_filename = 'a_file'
        with utils.temporary_chown(test_filename):
            pass
        mock_getuid.asset_called_once_with()
        mock_stat.assert_called_once_with(test_filename)
        self.assertFalse(mock_exec.called)


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
                          utils.walk_class_hierarchy(A, encountered=[C]))
        for actual, expected in class_pairs:
            self.assertEqual(actual, expected)

        class_pairs = zip((D, B, C, E), utils.walk_class_hierarchy(A))
        for actual, expected in class_pairs:
            self.assertEqual(actual, expected)


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
        self.assertRaises(exception.Error,
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
        self.assertIs(None, output)


class MonkeyPatchTestCase(test.TestCase):
    """Unit test for utils.monkey_patch()."""
    def setUp(self):
        super(MonkeyPatchTestCase, self).setUp()
        self.example_package = 'cinder.tests.monkey_patch_example.'
        self.flags(
            monkey_patch=True,
            monkey_patch_modules=[self.example_package + 'example_a' + ':'
                                  + self.example_package
                                  + 'example_decorator'])

    def test_monkey_patch(self):
        utils.monkey_patch()
        cinder.tests.monkey_patch_example.CALLED_FUNCTION = []
        from cinder.tests.monkey_patch_example import example_a
        from cinder.tests.monkey_patch_example import example_b

        self.assertEqual('Example function', example_a.example_function_a())
        exampleA = example_a.ExampleClassA()
        exampleA.example_method()
        ret_a = exampleA.example_method_add(3, 5)
        self.assertEqual(ret_a, 8)

        self.assertEqual('Example function', example_b.example_function_b())
        exampleB = example_b.ExampleClassB()
        exampleB.example_method()
        ret_b = exampleB.example_method_add(3, 5)

        self.assertEqual(ret_b, 8)
        package_a = self.example_package + 'example_a.'
        self.assertTrue(package_a + 'example_function_a'
                        in cinder.tests.monkey_patch_example.CALLED_FUNCTION)

        self.assertTrue(package_a + 'ExampleClassA.example_method'
                        in cinder.tests.monkey_patch_example.CALLED_FUNCTION)
        self.assertTrue(package_a + 'ExampleClassA.example_method_add'
                        in cinder.tests.monkey_patch_example.CALLED_FUNCTION)
        package_b = self.example_package + 'example_b.'
        self.assertFalse(package_b + 'example_function_b'
                         in cinder.tests.monkey_patch_example.CALLED_FUNCTION)
        self.assertFalse(package_b + 'ExampleClassB.example_method'
                         in cinder.tests.monkey_patch_example.CALLED_FUNCTION)
        self.assertFalse(package_b + 'ExampleClassB.example_method_add'
                         in cinder.tests.monkey_patch_example.CALLED_FUNCTION)


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
        self.assertEqual(begin,
                         datetime.datetime(hour=7,
                                           day=5,
                                           month=3,
                                           year=2012))
        self.assertEqual(end, datetime.datetime(hour=8,
                                                day=5,
                                                month=3,
                                                year=2012))

    def test_hour_with_offset_before_current(self):
        begin, end = utils.last_completed_audit_period(unit='hour@10')
        self.assertEqual(begin, datetime.datetime(minute=10,
                                                  hour=7,
                                                  day=5,
                                                  month=3,
                                                  year=2012))
        self.assertEqual(end, datetime.datetime(minute=10,
                                                hour=8,
                                                day=5,
                                                month=3,
                                                year=2012))

    def test_hour_with_offset_after_current(self):
        begin, end = utils.last_completed_audit_period(unit='hour@30')
        self.assertEqual(begin, datetime.datetime(minute=30,
                                                  hour=6,
                                                  day=5,
                                                  month=3,
                                                  year=2012))
        self.assertEqual(end, datetime.datetime(minute=30,
                                                hour=7,
                                                day=5,
                                                month=3,
                                                year=2012))

    def test_day(self):
        begin, end = utils.last_completed_audit_period(unit='day')
        self.assertEqual(begin, datetime.datetime(day=4,
                                                  month=3,
                                                  year=2012))
        self.assertEqual(end, datetime.datetime(day=5,
                                                month=3,
                                                year=2012))

    def test_day_with_offset_before_current(self):
        begin, end = utils.last_completed_audit_period(unit='day@6')
        self.assertEqual(begin, datetime.datetime(hour=6,
                                                  day=4,
                                                  month=3,
                                                  year=2012))
        self.assertEqual(end, datetime.datetime(hour=6,
                                                day=5,
                                                month=3,
                                                year=2012))

    def test_day_with_offset_after_current(self):
        begin, end = utils.last_completed_audit_period(unit='day@10')
        self.assertEqual(begin, datetime.datetime(hour=10,
                                                  day=3,
                                                  month=3,
                                                  year=2012))
        self.assertEqual(end, datetime.datetime(hour=10,
                                                day=4,
                                                month=3,
                                                year=2012))

    def test_month(self):
        begin, end = utils.last_completed_audit_period(unit='month')
        self.assertEqual(begin, datetime.datetime(day=1,
                                                  month=2,
                                                  year=2012))
        self.assertEqual(end, datetime.datetime(day=1,
                                                month=3,
                                                year=2012))

    def test_month_with_offset_before_current(self):
        begin, end = utils.last_completed_audit_period(unit='month@2')
        self.assertEqual(begin, datetime.datetime(day=2,
                                                  month=2,
                                                  year=2012))
        self.assertEqual(end, datetime.datetime(day=2,
                                                month=3,
                                                year=2012))

    def test_month_with_offset_after_current(self):
        begin, end = utils.last_completed_audit_period(unit='month@15')
        self.assertEqual(begin, datetime.datetime(day=15,
                                                  month=1,
                                                  year=2012))
        self.assertEqual(end, datetime.datetime(day=15,
                                                month=2,
                                                year=2012))

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
        self.assertEqual(begin, datetime.datetime(day=1,
                                                  month=1,
                                                  year=2011))
        self.assertEqual(end, datetime.datetime(day=1,
                                                month=1,
                                                year=2012))

    def test_year_with_offset_before_current(self):
        begin, end = utils.last_completed_audit_period(unit='year@2')
        self.assertEqual(begin, datetime.datetime(day=1,
                                                  month=2,
                                                  year=2011))
        self.assertEqual(end, datetime.datetime(day=1,
                                                month=2,
                                                year=2012))

    def test_year_with_offset_after_current(self):
        begin, end = utils.last_completed_audit_period(unit='year@6')
        self.assertEqual(begin, datetime.datetime(day=1,
                                                  month=6,
                                                  year=2010))
        self.assertEqual(end, datetime.datetime(day=1,
                                                month=6,
                                                year=2011))

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


class FakeSSHClient(object):

    def __init__(self):
        self.id = uuid.uuid4()
        self.transport = FakeTransport()

    def set_missing_host_key_policy(self, policy):
        self.policy = policy

    def load_system_host_keys(self):
        self.system_host_keys = 'system_host_keys'

    def load_host_keys(self, hosts_key_file):
        self.hosts_key_file = hosts_key_file

    def connect(self, ip, port=22, username=None, password=None,
                pkey=None, timeout=10):
        pass

    def get_transport(self):
        return self.transport

    def get_policy(self):
        return self.policy

    def get_host_keys(self):
        return '127.0.0.1 ssh-rsa deadbeef'

    def close(self):
        pass

    def __call__(self, *args, **kwargs):
        pass


class FakeSock(object):
    def settimeout(self, timeout):
        pass


class FakeTransport(object):

    def __init__(self):
        self.active = True
        self.sock = FakeSock()

    def set_keepalive(self, timeout):
        pass

    def is_active(self):
        return self.active


class SSHPoolTestCase(test.TestCase):
    """Unit test for SSH Connection Pool."""
    @mock.patch('cinder.ssh_utils.CONF')
    @mock.patch('__builtin__.open')
    @mock.patch('paramiko.SSHClient')
    @mock.patch('os.path.isfile', return_value=True)
    def test_ssh_default_hosts_key_file(self, mock_isfile, mock_sshclient,
                                        mock_open, mock_conf):
        mock_ssh = mock.MagicMock()
        mock_sshclient.return_value = mock_ssh
        mock_conf.ssh_hosts_key_file = '/var/lib/cinder/ssh_known_hosts'

        # create with customized setting
        sshpool = ssh_utils.SSHPool("127.0.0.1", 22, 10,
                                    "test",
                                    password="test",
                                    min_size=1,
                                    max_size=1)

        host_key_files = sshpool.hosts_key_file

        self.assertEqual('/var/lib/cinder/ssh_known_hosts', host_key_files)

        mock_ssh.load_host_keys.assert_called_once_with(
            '/var/lib/cinder/ssh_known_hosts')

    @mock.patch('cinder.ssh_utils.CONF')
    @mock.patch('__builtin__.open')
    @mock.patch('paramiko.SSHClient')
    @mock.patch('os.path.isfile', return_value=True)
    def test_ssh_host_key_file_kwargs(self, mock_isfile, mock_sshclient,
                                      mock_open, mock_conf):
        mock_ssh = mock.MagicMock()
        mock_sshclient.return_value = mock_ssh
        mock_conf.ssh_hosts_key_file = '/var/lib/cinder/ssh_known_hosts'

        # create with customized setting
        sshpool = ssh_utils.SSHPool("127.0.0.1", 22, 10,
                                    "test",
                                    password="test",
                                    min_size=1,
                                    max_size=1,
                                    hosts_key_file='dummy_host_keyfile')

        host_key_files = sshpool.hosts_key_file

        self.assertIn('dummy_host_keyfile', host_key_files)
        self.assertIn('/var/lib/cinder/ssh_known_hosts', host_key_files)

        expected = [
            mock.call.load_host_keys('dummy_host_keyfile'),
            mock.call.load_host_keys('/var/lib/cinder/ssh_known_hosts')]

        mock_ssh.assert_has_calls(expected, any_order=True)

    @mock.patch('cinder.ssh_utils.CONF')
    @mock.patch('__builtin__.open')
    @mock.patch('os.path.isfile', return_value=True)
    @mock.patch('paramiko.RSAKey.from_private_key_file')
    @mock.patch('paramiko.SSHClient')
    def test_single_ssh_connect(self, mock_sshclient, mock_pkey, mock_isfile,
                                mock_open, mock_conf):
        mock_conf.ssh_hosts_key_file = '/var/lib/cinder/ssh_known_hosts'

        # create with password
        sshpool = ssh_utils.SSHPool("127.0.0.1", 22, 10,
                                    "test",
                                    password="test",
                                    min_size=1,
                                    max_size=1)
        with sshpool.item() as ssh:
            first_id = ssh.id

        with sshpool.item() as ssh:
            second_id = ssh.id

        self.assertEqual(first_id, second_id)
        self.assertEqual(1, mock_sshclient.return_value.connect.call_count)

        # create with private key
        sshpool = ssh_utils.SSHPool("127.0.0.1", 22, 10,
                                    "test",
                                    privatekey="test",
                                    min_size=1,
                                    max_size=1)
        self.assertEqual(2, mock_sshclient.return_value.connect.call_count)

        # attempt to create with no password or private key
        self.assertRaises(paramiko.SSHException,
                          ssh_utils.SSHPool,
                          "127.0.0.1", 22, 10,
                          "test",
                          min_size=1,
                          max_size=1)

    @mock.patch('__builtin__.open')
    @mock.patch('paramiko.SSHClient')
    def test_closed_reopened_ssh_connections(self, mock_sshclient, mock_open):
        mock_sshclient.return_value = eval('FakeSSHClient')()
        sshpool = ssh_utils.SSHPool("127.0.0.1", 22, 10,
                                    "test",
                                    password="test",
                                    min_size=1,
                                    max_size=4)
        with sshpool.item() as ssh:
            mock_sshclient.reset_mock()
            first_id = ssh.id

        with sshpool.item() as ssh:
            second_id = ssh.id
            ssh.get_transport().active = False
            sshpool.remove(ssh)

        self.assertEqual(first_id, second_id)

        # create a new client
        mock_sshclient.return_value = FakeSSHClient()
        with sshpool.item() as ssh:
            third_id = ssh.id

        self.assertNotEqual(first_id, third_id)

    @mock.patch('cinder.ssh_utils.CONF')
    @mock.patch('__builtin__.open')
    @mock.patch('paramiko.SSHClient')
    def test_missing_ssh_hosts_key_config(self, mock_sshclient, mock_open,
                                          mock_conf):
        mock_sshclient.return_value = FakeSSHClient()

        mock_conf.ssh_hosts_key_file = None
        # create with password
        self.assertRaises(exception.ParameterNotFound,
                          ssh_utils.SSHPool,
                          "127.0.0.1", 22, 10,
                          "test",
                          password="test",
                          min_size=1,
                          max_size=1)

    @mock.patch('__builtin__.open')
    @mock.patch('paramiko.SSHClient')
    def test_create_default_known_hosts_file(self, mock_sshclient,
                                             mock_open):
        mock_sshclient.return_value = FakeSSHClient()

        CONF.state_path = '/var/lib/cinder'
        CONF.ssh_hosts_key_file = '/var/lib/cinder/ssh_known_hosts'

        default_file = '/var/lib/cinder/ssh_known_hosts'

        ssh_pool = ssh_utils.SSHPool("127.0.0.1", 22, 10,
                                     "test",
                                     password="test",
                                     min_size=1,
                                     max_size=1)

        with ssh_pool.item() as ssh:
            mock_open.assert_called_once_with(default_file, 'a')
            ssh_pool.remove(ssh)

    @mock.patch('os.path.isfile', return_value=False)
    @mock.patch('__builtin__.open')
    @mock.patch('paramiko.SSHClient')
    def test_ssh_missing_hosts_key_file(self, mock_sshclient, mock_open,
                                        mock_isfile):
        mock_sshclient.return_value = FakeSSHClient()

        CONF.ssh_hosts_key_file = '/tmp/blah'

        self.assertNotIn(CONF.state_path, CONF.ssh_hosts_key_file)
        self.assertRaises(exception.InvalidInput,
                          ssh_utils.SSHPool,
                          "127.0.0.1", 22, 10,
                          "test",
                          password="test",
                          min_size=1,
                          max_size=1)

    @mock.patch.multiple('cinder.ssh_utils.CONF',
                         strict_ssh_host_key_policy=True,
                         ssh_hosts_key_file='/var/lib/cinder/ssh_known_hosts')
    @mock.patch('__builtin__.open')
    @mock.patch('paramiko.SSHClient')
    @mock.patch('os.path.isfile', return_value=True)
    def test_ssh_strict_host_key_policy(self, mock_isfile, mock_sshclient,
                                        mock_open):
        mock_sshclient.return_value = FakeSSHClient()

        # create with customized setting
        sshpool = ssh_utils.SSHPool("127.0.0.1", 22, 10,
                                    "test",
                                    password="test",
                                    min_size=1,
                                    max_size=1)

        with sshpool.item() as ssh:
            self.assertTrue(isinstance(ssh.get_policy(),
                                       paramiko.RejectPolicy))

    @mock.patch('__builtin__.open')
    @mock.patch('paramiko.SSHClient')
    @mock.patch('os.path.isfile', return_value=True)
    def test_ssh_not_strict_host_key_policy(self, mock_isfile, mock_sshclient,
                                            mock_open):
        mock_sshclient.return_value = FakeSSHClient()

        CONF.strict_ssh_host_key_policy = False

        # create with customized setting
        sshpool = ssh_utils.SSHPool("127.0.0.1", 22, 10,
                                    "test",
                                    password="test",
                                    min_size=1,
                                    max_size=1)

        with sshpool.item() as ssh:
            self.assertTrue(isinstance(ssh.get_policy(),
                                       paramiko.AutoAddPolicy))


class BrickUtils(test.TestCase):
    """Unit test to test the brick utility
    wrapper functions.
    """

    @mock.patch('cinder.utils.CONF')
    @mock.patch('cinder.brick.initiator.connector.get_connector_properties')
    @mock.patch('cinder.utils.get_root_helper')
    def test_brick_get_connector_properties(self, mock_helper, mock_get,
                                            mock_conf):
        mock_conf.my_ip = '1.2.3.4'
        output = utils.brick_get_connector_properties()
        mock_helper.assert_called_once_with()
        mock_get.assert_called_once_with(mock_helper.return_value, '1.2.3.4',
                                         False, False)
        self.assertEqual(mock_get.return_value, output)

    @mock.patch('cinder.brick.initiator.connector.InitiatorConnector.factory')
    @mock.patch('cinder.utils.get_root_helper')
    def test_brick_get_connector(self, mock_helper, mock_factory):
        output = utils.brick_get_connector('protocol')
        mock_helper.assert_called_once_with()
        self.assertEqual(mock_factory.return_value, output)
        mock_factory.assert_called_once_with(
            'protocol', mock_helper.return_value, driver=None,
            execute=putils.execute, use_multipath=False,
            device_scan_attempts=3)


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


class AddVisibleAdminMetadataTestCase(test.TestCase):
    def test_add_visible_admin_metadata_visible_key_only(self):
        admin_metadata = [{"key": "invisible_key", "value": "invisible_value"},
                          {"key": "readonly", "value": "visible"},
                          {"key": "attached_mode", "value": "visible"}]
        metadata = [{"key": "key", "value": "value"},
                    {"key": "readonly", "value": "existing"}]
        volume = {'volume_admin_metadata': admin_metadata,
                  'volume_metadata': metadata}
        utils.add_visible_admin_metadata(volume)
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
        utils.add_visible_admin_metadata(volume)
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
        utils.add_visible_admin_metadata(volume)
        self.assertEqual([{"key": "key", "value": "value"}],
                         volume['volume_metadata'])

        admin_metadata = {"invisible_key1": "invisible_value1",
                          "invisible_key2": "invisible_value2",
                          "invisible_key3": "invisible_value3"}
        metadata = {"key": "value"}
        volume = {'admin_metadata': admin_metadata,
                  'metadata': metadata}
        utils.add_visible_admin_metadata(volume)
        self.assertEqual({'key': 'value'}, volume['metadata'])

    def test_add_visible_admin_metadata_no_existing_metadata(self):
        admin_metadata = [{"key": "invisible_key", "value": "invisible_value"},
                          {"key": "readonly", "value": "visible"},
                          {"key": "attached_mode", "value": "visible"}]
        volume = {'volume_admin_metadata': admin_metadata}
        utils.add_visible_admin_metadata(volume)
        self.assertEqual({'attached_mode': 'visible', 'readonly': 'visible'},
                         volume['metadata'])

        admin_metadata = {"invisible_key": "invisible_value",
                          "readonly": "visible",
                          "attached_mode": "visible"}
        volume = {'admin_metadata': admin_metadata}
        utils.add_visible_admin_metadata(volume)
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

        utils.remove_invalid_filter_options(ctxt, filters,
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

        utils.remove_invalid_filter_options(ctxt, filters,
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
    def setUp(self):
        super(TestRetryDecorator, self).setUp()

    def test_no_retry_required(self):
        self.counter = 0

        with mock.patch.object(time, 'sleep') as mock_sleep:
            @utils.retry(exception.VolumeBackendAPIException,
                         interval=2,
                         retries=3,
                         backoff_rate=2)
            def succeeds():
                self.counter += 1
                return 'success'

            ret = succeeds()
            self.assertFalse(mock_sleep.called)
            self.assertEqual(ret, 'success')
            self.assertEqual(self.counter, 1)

    def test_retries_once(self):
        self.counter = 0
        interval = 2
        backoff_rate = 2
        retries = 3

        with mock.patch.object(time, 'sleep') as mock_sleep:
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
            self.assertEqual(ret, 'success')
            self.assertEqual(self.counter, 2)
            self.assertEqual(mock_sleep.call_count, 1)
            mock_sleep.assert_called_with(interval * backoff_rate)

    def test_limit_is_reached(self):
        self.counter = 0
        retries = 3
        interval = 2
        backoff_rate = 4

        with mock.patch.object(time, 'sleep') as mock_sleep:
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

            for i in xrange(retries):
                if i > 0:
                    interval *= backoff_rate
                    expected_sleep_arg.append(float(interval))

            mock_sleep.assert_has_calls(map(mock.call, expected_sleep_arg))

    def test_wrong_exception_no_retry(self):

        with mock.patch.object(time, 'sleep') as mock_sleep:
            @utils.retry(exception.VolumeBackendAPIException)
            def raise_unexpected_error():
                raise WrongException("wrong exception")

            self.assertRaises(WrongException, raise_unexpected_error)
            self.assertFalse(mock_sleep.called)


class VersionTestCase(test.TestCase):
    def test_convert_version_to_int(self):
        self.assertEqual(utils.convert_version_to_int('6.2.0'), 6002000)
        self.assertEqual(utils.convert_version_to_int((6, 4, 3)), 6004003)
        self.assertEqual(utils.convert_version_to_int((5, )), 5)
        self.assertRaises(exception.CinderException,
                          utils.convert_version_to_int, '5a.6b')

    def test_convert_version_to_string(self):
        self.assertEqual(utils.convert_version_to_str(6007000), '6.7.0')
        self.assertEqual(utils.convert_version_to_str(4), '4')

    def test_convert_version_to_tuple(self):
        self.assertEqual(utils.convert_version_to_tuple('6.7.0'), (6, 7, 0))
