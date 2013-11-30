# vim: tabstop=4 shiftwidth=4 softtabstop=4

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


import __builtin__
import datetime
import hashlib
import os
import socket
import StringIO
import tempfile
import uuid

import mox
from oslo.config import cfg
import paramiko

import cinder
from cinder.brick.initiator import connector
from cinder.brick.initiator import linuxfc
from cinder import exception
from cinder.openstack.common import processutils as putils
from cinder.openstack.common import timeutils
from cinder import test
from cinder import utils


CONF = cfg.CONF


class ExecuteTestCase(test.TestCase):
    def test_retry_on_failure(self):
        fd, tmpfilename = tempfile.mkstemp()
        _, tmpfilename2 = tempfile.mkstemp()
        try:
            fp = os.fdopen(fd, 'w+')
            fp.write('''#!/bin/sh
# If stdin fails to get passed during one of the runs, make a note.
if ! grep -q foo
then
    echo 'failure' > "$1"
fi
# If stdin has failed to get passed during this or a previous run, exit early.
if grep failure "$1"
then
    exit 1
fi
runs="$(cat $1)"
if [ -z "$runs" ]
then
    runs=0
fi
runs=$(($runs + 1))
echo $runs > "$1"
exit 1
''')
            fp.close()
            os.chmod(tmpfilename, 0o755)
            self.assertRaises(putils.ProcessExecutionError,
                              utils.execute,
                              tmpfilename, tmpfilename2, attempts=10,
                              process_input='foo',
                              delay_on_retry=False)
            fp = open(tmpfilename2, 'r+')
            runs = fp.read()
            fp.close()
            self.assertNotEquals(runs.strip(), 'failure', 'stdin did not '
                                                          'always get passed '
                                                          'correctly')
            runs = int(runs.strip())
            self.assertEqual(runs, 10, 'Ran %d times instead of 10.' % (runs,))
        finally:
            os.unlink(tmpfilename)
            os.unlink(tmpfilename2)

    def test_unknown_kwargs_raises_error(self):
        self.assertRaises(putils.UnknownArgumentError,
                          utils.execute,
                          '/usr/bin/env', 'true',
                          this_is_not_a_valid_kwarg=True)

    def test_check_exit_code_boolean(self):
        utils.execute('/usr/bin/env', 'false', check_exit_code=False)
        self.assertRaises(putils.ProcessExecutionError,
                          utils.execute,
                          '/usr/bin/env', 'false', check_exit_code=True)

    def test_no_retry_on_success(self):
        fd, tmpfilename = tempfile.mkstemp()
        _, tmpfilename2 = tempfile.mkstemp()
        try:
            fp = os.fdopen(fd, 'w+')
            fp.write('''#!/bin/sh
# If we've already run, bail out.
grep -q foo "$1" && exit 1
# Mark that we've run before.
echo foo > "$1"
# Check that stdin gets passed correctly.
grep foo
''')
            fp.close()
            os.chmod(tmpfilename, 0o755)
            utils.execute(tmpfilename,
                          tmpfilename2,
                          process_input='foo',
                          attempts=2)
        finally:
            os.unlink(tmpfilename)
            os.unlink(tmpfilename2)


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

    def test_generate_glance_url(self):
        generated_url = utils.generate_glance_url()
        actual_url = "http://%s:%d" % (CONF.glance_host,
                                       CONF.glance_port)
        self.assertEqual(generated_url, actual_url)

    def test_read_cached_file(self):
        self.mox.StubOutWithMock(os.path, "getmtime")
        os.path.getmtime(mox.IgnoreArg()).AndReturn(1)
        self.mox.ReplayAll()

        cache_data = {"data": 1123, "mtime": 1}
        data = utils.read_cached_file("/this/is/a/fake", cache_data)
        self.assertEqual(cache_data["data"], data)

    def test_read_modified_cached_file(self):
        self.mox.StubOutWithMock(os.path, "getmtime")
        self.mox.StubOutWithMock(__builtin__, 'open')
        os.path.getmtime(mox.IgnoreArg()).AndReturn(2)

        fake_contents = "lorem ipsum"
        fake_file = self.mox.CreateMockAnything()
        fake_file.read().AndReturn(fake_contents)
        fake_context_manager = self.mox.CreateMockAnything()
        fake_context_manager.__enter__().AndReturn(fake_file)
        fake_context_manager.__exit__(mox.IgnoreArg(),
                                      mox.IgnoreArg(),
                                      mox.IgnoreArg())

        __builtin__.open(mox.IgnoreArg()).AndReturn(fake_context_manager)

        self.mox.ReplayAll()
        cache_data = {"data": 1123, "mtime": 1}
        self.reload_called = False

        def test_reload(reloaded_data):
            self.assertEqual(reloaded_data, fake_contents)
            self.reload_called = True

        data = utils.read_cached_file("/this/is/a/fake",
                                      cache_data,
                                      reload_func=test_reload)
        self.assertEqual(data, fake_contents)
        self.assertTrue(self.reload_called)

    def test_generate_password(self):
        password = utils.generate_password()
        self.assertTrue([c for c in password if c in '0123456789'])
        self.assertTrue([c for c in password
                         if c in 'abcdefghijklmnopqrstuvwxyz'])
        self.assertTrue([c for c in password
                         if c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'])

    def test_read_file_as_root(self):
        def fake_execute(*args, **kwargs):
            if args[1] == 'bad':
                raise putils.ProcessExecutionError
            return 'fakecontents', None

        self.stubs.Set(utils, 'execute', fake_execute)
        contents = utils.read_file_as_root('good')
        self.assertEqual(contents, 'fakecontents')
        self.assertRaises(exception.FileNotFound,
                          utils.read_file_as_root, 'bad')

    def test_temporary_chown(self):
        def fake_execute(*args, **kwargs):
            if args[0] == 'chown':
                fake_execute.uid = args[1]
        self.stubs.Set(utils, 'execute', fake_execute)

        with tempfile.NamedTemporaryFile() as f:
            with utils.temporary_chown(f.name, owner_uid=2):
                self.assertEqual(fake_execute.uid, 2)
            self.assertEqual(fake_execute.uid, os.getuid())

    def test_service_is_up(self):
        fts_func = datetime.datetime.fromtimestamp
        fake_now = 1000
        down_time = 5

        self.flags(service_down_time=down_time)
        self.mox.StubOutWithMock(timeutils, 'utcnow')

        # Up (equal)
        timeutils.utcnow().AndReturn(fts_func(fake_now))
        service = {'updated_at': fts_func(fake_now - down_time),
                   'created_at': fts_func(fake_now - down_time)}
        self.mox.ReplayAll()
        result = utils.service_is_up(service)
        self.assertTrue(result)

        self.mox.ResetAll()
        # Up
        timeutils.utcnow().AndReturn(fts_func(fake_now))
        service = {'updated_at': fts_func(fake_now - down_time + 1),
                   'created_at': fts_func(fake_now - down_time + 1)}
        self.mox.ReplayAll()
        result = utils.service_is_up(service)
        self.assertTrue(result)

        self.mox.ResetAll()
        # Down
        timeutils.utcnow().AndReturn(fts_func(fake_now))
        service = {'updated_at': fts_func(fake_now - down_time - 1),
                   'created_at': fts_func(fake_now - down_time - 1)}
        self.mox.ReplayAll()
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
        flo = StringIO.StringIO(data)
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
        with_danger_char = ['||', 'my_name@name_of_remote_computer']
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

    def test_create_channel(self):
        client = paramiko.SSHClient()
        channel = paramiko.Channel(123)
        self.mox.StubOutWithMock(client, 'invoke_shell')
        self.mox.StubOutWithMock(channel, 'resize_pty')

        client.invoke_shell().AndReturn(channel)
        channel.resize_pty(600, 800)

        self.mox.ReplayAll()
        utils.create_channel(client, 600, 800)

        self.mox.VerifyAll()

    def _make_fake_stat(self, test_file, orig_os_stat):
        """Create a fake method to stub out os.stat().

           Generate a function that will return a particular
           stat object for a given file.

           :param: test_file: file to spoof stat() for
           :param: orig_os_stat: pointer to original os.stat()
        """

        def fake_stat(path):
            if path == test_file:
                class stat_result:
                    st_mode = 0o777
                    st_gid = 33333
                return stat_result
            else:
                return orig_os_stat(path)

        return fake_stat

    def test_get_file_mode(self):
        test_file = '/var/tmp/made_up_file'

        orig_os_stat = os.stat
        os.stat = self._make_fake_stat(test_file, orig_os_stat)

        self.mox.ReplayAll()

        mode = utils.get_file_mode(test_file)
        self.assertEqual(mode, 0o777)

        self.mox.VerifyAll()

        os.stat = orig_os_stat

    def test_get_file_gid(self):
        test_file = '/var/tmp/made_up_file'

        orig_os_stat = os.stat
        os.stat = self._make_fake_stat(test_file, orig_os_stat)

        self.mox.ReplayAll()

        gid = utils.get_file_gid(test_file)
        self.assertEqual(gid, 33333)

        self.mox.VerifyAll()

        os.stat = orig_os_stat


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
        #a fairly random time to test with
        self.test_time = datetime.datetime(second=23,
                                           minute=12,
                                           hour=8,
                                           day=5,
                                           month=3,
                                           year=2012)
        timeutils.set_time_override(override_time=self.test_time)

    def tearDown(self):
        timeutils.clear_time_override()
        super(AuditPeriodTest, self).tearDown()

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


class FakeSSHClient(object):

    def __init__(self):
        self.id = uuid.uuid4()
        self.transport = FakeTransport()

    def set_missing_host_key_policy(self, policy):
        pass

    def connect(self, ip, port=22, username=None, password=None,
                pkey=None, timeout=10):
        pass

    def get_transport(self):
        return self.transport

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

    def setup(self):
        self.mox.StubOutWithMock(paramiko, "SSHClient")
        paramiko.SSHClient().AndReturn(FakeSSHClient())
        self.mox.ReplayAll()

    def test_single_ssh_connect(self):
        self.setup()
        sshpool = utils.SSHPool("127.0.0.1", 22, 10, "test", password="test",
                                min_size=1, max_size=1)
        with sshpool.item() as ssh:
            first_id = ssh.id

        with sshpool.item() as ssh:
            second_id = ssh.id

        self.assertEqual(first_id, second_id)

    def test_closed_reopend_ssh_connections(self):
        self.setup()
        sshpool = utils.SSHPool("127.0.0.1", 22, 10, "test", password="test",
                                min_size=1, max_size=2)
        with sshpool.item() as ssh:
            first_id = ssh.id
        with sshpool.item() as ssh:
            second_id = ssh.id
            # Close the connection and test for a new connection
            ssh.get_transport().active = False

        self.assertEqual(first_id, second_id)

        # The mox items are not getting setup in a new pool connection,
        # so had to reset and set again.
        self.mox.UnsetStubs()
        self.setup()

        with sshpool.item() as ssh:
            third_id = ssh.id

        self.assertNotEqual(first_id, third_id)


class BrickUtils(test.TestCase):
    """Unit test to test the brick utility
    wrapper functions.
    """

    def test_brick_get_connector_properties(self):

        self.mox.StubOutWithMock(socket, 'gethostname')
        socket.gethostname().AndReturn('fakehost')

        self.mox.StubOutWithMock(connector.ISCSIConnector, 'get_initiator')
        connector.ISCSIConnector.get_initiator().AndReturn('fakeinitiator')

        self.mox.StubOutWithMock(linuxfc.LinuxFibreChannel, 'get_fc_wwpns')
        linuxfc.LinuxFibreChannel.get_fc_wwpns().AndReturn(None)

        self.mox.StubOutWithMock(linuxfc.LinuxFibreChannel, 'get_fc_wwnns')
        linuxfc.LinuxFibreChannel.get_fc_wwnns().AndReturn(None)

        props = {'initiator': 'fakeinitiator',
                 'host': 'fakehost',
                 'ip': CONF.my_ip,
                 }

        self.mox.ReplayAll()
        props_actual = utils.brick_get_connector_properties()
        self.assertEqual(props, props_actual)
        self.mox.VerifyAll()

    def test_brick_get_connector(self):

        root_helper = utils.get_root_helper()

        self.mox.StubOutClassWithMocks(connector, 'ISCSIConnector')
        connector.ISCSIConnector(execute=putils.execute,
                                 driver=None,
                                 root_helper=root_helper,
                                 use_multipath=False,
                                 device_scan_attempts=3)

        self.mox.StubOutClassWithMocks(connector, 'FibreChannelConnector')
        connector.FibreChannelConnector(execute=putils.execute,
                                        driver=None,
                                        root_helper=root_helper,
                                        use_multipath=False,
                                        device_scan_attempts=3)

        self.mox.StubOutClassWithMocks(connector, 'AoEConnector')
        connector.AoEConnector(execute=putils.execute,
                               driver=None,
                               root_helper=root_helper,
                               device_scan_attempts=3)

        self.mox.StubOutClassWithMocks(connector, 'LocalConnector')
        connector.LocalConnector(execute=putils.execute,
                                 driver=None,
                                 root_helper=root_helper,
                                 device_scan_attempts=3)

        self.mox.ReplayAll()
        utils.brick_get_connector('iscsi')
        utils.brick_get_connector('fibre_channel')
        utils.brick_get_connector('aoe')
        utils.brick_get_connector('local')
        self.mox.VerifyAll()
