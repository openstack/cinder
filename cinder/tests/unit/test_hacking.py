#    Copyright 2014 Red Hat, Inc.
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

import ddt
import textwrap

import mock
import pep8

from cinder.hacking import checks
from cinder import test


@ddt.ddt
class HackingTestCase(test.TestCase):
    """This class tests the hacking checks in cinder.hacking.checks

    This class ensures that Cinder's hacking checks are working by passing
    strings to the check methods like the pep8/flake8 parser would. The parser
    loops over each line in the file and then passes the parameters to the
    check method. The parameter names in the check method dictate what type of
    object is passed to the check method. The parameter types are::

        logical_line: A processed line with the following modifications:
            - Multi-line statements converted to a single line.
            - Stripped left and right.
            - Contents of strings replaced with "xxx" of same length.
            - Comments removed.
        physical_line: Raw line of text from the input file.
        lines: a list of the raw lines from the input file
        tokens: the tokens that contribute to this logical line
        line_number: line number in the input file
        total_lines: number of lines in the input file
        blank_lines: blank lines before this one
        indent_char: indentation character in this file (" " or "\t")
        indent_level: indentation (with tabs expanded to multiples of 8)
        previous_indent_level: indentation on previous line
        previous_logical: previous logical line
        filename: Path of the file being run through pep8

    When running a test on a check method the return will be False/None if
    there is no violation in the sample input. If there is an error a tuple is
    returned with a position in the line, and a message. So to check the result
    just assertTrue if the check is expected to fail and assertFalse if it
    should pass.
    """

    def test_no_vi_headers(self):

        lines = ['Line 1\n', 'Line 2\n', 'Line 3\n', 'Line 4\n', 'Line 5\n',
                 'Line 6\n', 'Line 7\n', 'Line 8\n', 'Line 9\n', 'Line 10\n',
                 'Line 11\n']

        self.assertEqual(None, checks.no_vi_headers(
            "Test string foo", 1, lines))
        self.assertEqual(2, len(list(checks.no_vi_headers(
            "# vim: et tabstop=4 shiftwidth=4 softtabstop=4",
            2, lines))))
        self.assertEqual(2, len(list(checks.no_vi_headers(
            "# vim: et tabstop=4 shiftwidth=4 softtabstop=4",
            8, lines))))
        self.assertEqual(None, checks.no_vi_headers(
            "Test end string for vi",
            9, lines))
        # vim header outside of boundary (first/last 5 lines)
        self.assertEqual(None, checks.no_vi_headers(
            "# vim: et tabstop=4 shiftwidth=4 softtabstop=4",
            6, lines))

    def test_no_translate_debug_logs(self):
        self.assertEqual(1, len(list(checks.no_translate_debug_logs(
            "LOG.debug(_('foo'))", "cinder/scheduler/foo.py"))))

        self.assertEqual(0, len(list(checks.no_translate_debug_logs(
            "LOG.debug('foo')", "cinder/scheduler/foo.py"))))

        self.assertEqual(0, len(list(checks.no_translate_debug_logs(
            "LOG.info(_('foo'))", "cinder/scheduler/foo.py"))))

    def test_check_explicit_underscore_import(self):
        self.assertEqual(1, len(list(checks.check_explicit_underscore_import(
            "LOG.info(_('My info message'))",
            "cinder.tests.unit/other_files.py"))))
        self.assertEqual(1, len(list(checks.check_explicit_underscore_import(
            "msg = _('My message')",
            "cinder.tests.unit/other_files.py"))))
        self.assertEqual(0, len(list(checks.check_explicit_underscore_import(
            "from cinder.i18n import _",
            "cinder.tests.unit/other_files.py"))))
        self.assertEqual(0, len(list(checks.check_explicit_underscore_import(
            "LOG.info(_('My info message'))",
            "cinder.tests.unit/other_files.py"))))
        self.assertEqual(0, len(list(checks.check_explicit_underscore_import(
            "msg = _('My message')",
            "cinder.tests.unit/other_files.py"))))
        self.assertEqual(0, len(list(checks.check_explicit_underscore_import(
            "from cinder.i18n import _, _LW",
            "cinder.tests.unit/other_files2.py"))))
        self.assertEqual(0, len(list(checks.check_explicit_underscore_import(
            "msg = _('My message')",
            "cinder.tests.unit/other_files2.py"))))
        self.assertEqual(0, len(list(checks.check_explicit_underscore_import(
            "_ = translations.ugettext",
            "cinder.tests.unit/other_files3.py"))))
        self.assertEqual(0, len(list(checks.check_explicit_underscore_import(
            "msg = _('My message')",
            "cinder.tests.unit/other_files3.py"))))
        # Complete code coverage by falling through all checks
        self.assertEqual(0, len(list(checks.check_explicit_underscore_import(
            "LOG.info('My info message')",
            "cinder.tests.unit/other_files4.py"))))

    # We are patching pep8 so that only the check under test is actually
    # installed.
    @mock.patch('pep8._checks',
                {'physical_line': {}, 'logical_line': {}, 'tree': {}})
    def _run_check(self, code, checker, filename=None):
        pep8.register_check(checker)

        lines = textwrap.dedent(code).strip().splitlines(True)

        checker = pep8.Checker(filename=filename, lines=lines)
        checker.check_all()
        checker.report._deferred_print.sort()
        return checker.report._deferred_print

    def _assert_has_errors(self, code, checker, expected_errors=None,
                           filename=None):
        actual_errors = [e[:3] for e in
                         self._run_check(code, checker, filename)]
        self.assertEqual(expected_errors or [], actual_errors)

    def _assert_has_no_errors(self, code, checker, filename=None):
        self._assert_has_errors(code, checker, filename=filename)

    def test_logging_format_args(self):
        checker = checks.CheckLoggingFormatArgs
        code = """
               import logging
               LOG = logging.getLogger()
               LOG.info("Message without a second argument.")
               LOG.critical("Message with %s arguments.", 'two')
               LOG.debug("Volume %s caught fire and is at %d degrees C and"
                         " climbing.", 'volume1', 500)
               """
        self._assert_has_no_errors(code, checker)

        code = """
               import logging
               LOG = logging.getLogger()
               LOG.{0}("Volume %s caught fire and is at %d degrees C and "
                      "climbing.", ('volume1', 500))
               """
        for method in checker.LOG_METHODS:
            self._assert_has_errors(code.format(method), checker,
                                    expected_errors=[(4, 21, 'C310')])

        code = """
               import logging
               LOG = logging.getLogger()
               LOG.log(logging.DEBUG, "Volume %s caught fire and is at %d"
                       " degrees C and climbing.", ('volume1', 500))
               """
        self._assert_has_errors(code, checker,
                                expected_errors=[(4, 37, 'C310')])

    def test_opt_type_registration_args(self):
        checker = checks.CheckOptRegistrationArgs
        code = """
               CONF.register_opts([opt1, opt2, opt3])
               CONF.register_opts((opt4, opt5))
               CONF.register_opt(lonely_opt)
               CONF.register_opts([OPT1, OPT2], group="group_of_opts")
               CONF.register_opt(single_opt, group=blah)
               """
        self._assert_has_no_errors(code, checker)

        code = """
               CONF.register_opt([opt4, opt5, opt6])
               CONF.register_opt((opt7, opt8))
               CONF.register_opts(lonely_opt)
               CONF.register_opt((an_opt, another_opt))
               """
        self._assert_has_errors(code, checker,
                                expected_errors=[(1, 18, 'C311'),
                                                 (2, 19, 'C311'),
                                                 (3, 19, 'C311'),
                                                 (4, 19, 'C311')])

        code = """
               CONF.register_opt(single_opt)
               CONF.register_opts(other_opt)
               CONF.register_opt(multiple_opts)
               tuple_opts = (one_opt, two_opt)
               CONF.register_opts(tuple_opts)
               """
        self._assert_has_errors(code, checker,
                                expected_errors=[(2, 19, 'C311'),
                                                 (3, 18, 'C311')])

    def test_str_unicode_exception(self):

        checker = checks.CheckForStrUnicodeExc
        code = """
               def f(a, b):
                   try:
                       p = str(a) + str(b)
                   except ValueError as e:
                       p = str(e)
                   return p
               """
        errors = [(5, 16, 'N325')]
        self._assert_has_errors(code, checker, expected_errors=errors)

        code = """
               def f(a, b):
                   try:
                       p = unicode(a) + str(b)
                   except ValueError as e:
                       p = e
                   return p
               """
        self._assert_has_no_errors(code, checker)

        code = """
               def f(a, b):
                   try:
                       p = str(a) + str(b)
                   except ValueError as e:
                       p = unicode(e)
                   return p
               """
        errors = [(5, 20, 'N325')]
        self._assert_has_errors(code, checker, expected_errors=errors)

        code = """
               def f(a, b):
                   try:
                       p = str(a) + str(b)
                   except ValueError as e:
                       try:
                           p  = unicode(a) + unicode(b)
                       except ValueError as ve:
                           p = str(e) + str(ve)
                       p = e
                   return p
               """
        errors = [(8, 20, 'N325'), (8, 29, 'N325')]
        self._assert_has_errors(code, checker, expected_errors=errors)

        code = """
               def f(a, b):
                   try:
                       p = str(a) + str(b)
                   except ValueError as e:
                       try:
                           p  = unicode(a) + unicode(b)
                       except ValueError as ve:
                           p = str(e) + unicode(ve)
                       p = str(e)
                   return p
               """
        errors = [(8, 20, 'N325'), (8, 33, 'N325'), (9, 16, 'N325')]
        self._assert_has_errors(code, checker, expected_errors=errors)

    def test_check_no_log_audit(self):
        self.assertEqual(1, len(list(checks.check_no_log_audit(
            "LOG.audit('My test audit log')"))))
        self.assertEqual(0, len(list(checks.check_no_log_audit(
            "LOG.info('My info test log.')"))))

    def test_no_mutable_default_args(self):
        self.assertEqual(0, len(list(checks.no_mutable_default_args(
            "def foo (bar):"))))
        self.assertEqual(1, len(list(checks.no_mutable_default_args(
            "def foo (bar=[]):"))))
        self.assertEqual(1, len(list(checks.no_mutable_default_args(
            "def foo (bar={}):"))))

    def test_oslo_namespace_imports_check(self):
        self.assertEqual(1, len(list(checks.check_oslo_namespace_imports(
            "from oslo.concurrency import foo"))))
        self.assertEqual(0, len(list(checks.check_oslo_namespace_imports(
            "from oslo_concurrency import bar"))))
        self.assertEqual(1, len(list(checks.check_oslo_namespace_imports(
            "from oslo.db import foo"))))
        self.assertEqual(0, len(list(checks.check_oslo_namespace_imports(
            "from oslo_db import bar"))))
        self.assertEqual(1, len(list(checks.check_oslo_namespace_imports(
            "from oslo.config import foo"))))
        self.assertEqual(0, len(list(checks.check_oslo_namespace_imports(
            "from oslo_config import bar"))))
        self.assertEqual(1, len(list(checks.check_oslo_namespace_imports(
            "from oslo.utils import foo"))))
        self.assertEqual(0, len(list(checks.check_oslo_namespace_imports(
            "from oslo_utils import bar"))))
        self.assertEqual(1, len(list(checks.check_oslo_namespace_imports(
            "from oslo.serialization import foo"))))
        self.assertEqual(0, len(list(checks.check_oslo_namespace_imports(
            "from oslo_serialization import bar"))))
        self.assertEqual(1, len(list(checks.check_oslo_namespace_imports(
            "from oslo.log import foo"))))
        self.assertEqual(0, len(list(checks.check_oslo_namespace_imports(
            "from oslo_log import bar"))))

    def test_no_contextlib_nested(self):
        self.assertEqual(1, len(list(checks.check_no_contextlib_nested(
            "with contextlib.nested("))))
        self.assertEqual(1, len(list(checks.check_no_contextlib_nested(
            "  with nested("))))
        self.assertEqual(0, len(list(checks.check_no_contextlib_nested(
            "with my.nested("))))
        self.assertEqual(0, len(list(checks.check_no_contextlib_nested(
            "with foo as bar"))))

    def test_check_datetime_now(self):
        self.assertEqual(1, len(list(checks.check_datetime_now(
            "datetime.now", False))))
        self.assertEqual(0, len(list(checks.check_datetime_now(
            "timeutils.utcnow", False))))

    def test_check_datetime_now_noqa(self):
        self.assertEqual(0, len(list(checks.check_datetime_now(
                                     "datetime.now()  # noqa", True))))

    def test_check_timeutils_strtime(self):
        self.assertEqual(1, len(list(checks.check_timeutils_strtime(
            "timeutils.strtime"))))
        self.assertEqual(0, len(list(checks.check_timeutils_strtime(
            "strftime"))))

    def test_validate_log_translations(self):
        self.assertEqual(1, len(list(checks.validate_log_translations(
            "LOG.info('foo')", "foo.py"))))
        self.assertEqual(1, len(list(checks.validate_log_translations(
            "LOG.warning('foo')", "foo.py"))))
        self.assertEqual(1, len(list(checks.validate_log_translations(
            "LOG.error('foo')", "foo.py"))))
        self.assertEqual(1, len(list(checks.validate_log_translations(
            "LOG.exception('foo')", "foo.py"))))
        self.assertEqual(0, len(list(checks.validate_log_translations(
            "LOG.info('foo')", "cinder/tests/foo.py"))))
        self.assertEqual(0, len(list(checks.validate_log_translations(
            "LOG.info(_LI('foo')", "foo.py"))))
        self.assertEqual(0, len(list(checks.validate_log_translations(
            "LOG.warning(_LW('foo')", "foo.py"))))
        self.assertEqual(0, len(list(checks.validate_log_translations(
            "LOG.error(_LE('foo')", "foo.py"))))
        self.assertEqual(0, len(list(checks.validate_log_translations(
            "LOG.exception(_LE('foo')", "foo.py"))))

    def test_check_unicode_usage(self):
        self.assertEqual(1, len(list(checks.check_unicode_usage(
            "unicode(msg)", False))))
        self.assertEqual(0, len(list(checks.check_unicode_usage(
            "unicode(msg)  # noqa", True))))

    def test_no_print_statements(self):
        self.assertEqual(0, len(list(checks.check_no_print_statements(
            "a line with no print statement",
            "cinder/file.py", False))))
        self.assertEqual(1, len(list(checks.check_no_print_statements(
            "print('My print statement')",
            "cinder/file.py", False))))
        self.assertEqual(0, len(list(checks.check_no_print_statements(
            "print('My print statement in cinder/cmd, which is ok.')",
            "cinder/cmd/file.py", False))))
        self.assertEqual(0, len(list(checks.check_no_print_statements(
            "print('My print statement that I just must have.')",
            "cinder.tests.unit/file.py", True))))
        self.assertEqual(1, len(list(checks.check_no_print_statements(
            "print ('My print with space')",
            "cinder/volume/anotherFile.py", False))))

    def test_dict_constructor_with_list_copy(self):
        self.assertEqual(1, len(list(checks.dict_constructor_with_list_copy(
            "    dict([(i, connect_info[i])"))))

        self.assertEqual(1, len(list(checks.dict_constructor_with_list_copy(
            "    attrs = dict([(k, _from_json(v))"))))

        self.assertEqual(1, len(list(checks.dict_constructor_with_list_copy(
            "        type_names = dict((value, key) for key, value in"))))

        self.assertEqual(1, len(list(checks.dict_constructor_with_list_copy(
            "   dict((value, key) for key, value in"))))

        self.assertEqual(1, len(list(checks.dict_constructor_with_list_copy(
            "foo(param=dict((k, v) for k, v in bar.items()))"))))

        self.assertEqual(1, len(list(checks.dict_constructor_with_list_copy(
            " dict([[i,i] for i in range(3)])"))))

        self.assertEqual(1, len(list(checks.dict_constructor_with_list_copy(
            "  dd = dict([i,i] for i in range(3))"))))

        self.assertEqual(0, len(list(checks.dict_constructor_with_list_copy(
            "  dict()"))))

        self.assertEqual(0, len(list(checks.dict_constructor_with_list_copy(
            "        create_kwargs = dict(snapshot=snapshot,"))))

        self.assertEqual(0, len(list(checks.dict_constructor_with_list_copy(
            "      self._render_dict(xml, data_el, data.__dict__)"))))

    @ddt.unpack
    @ddt.data(
        (1, 'LOG.info', "cinder/tests/unit/fake.py", False),
        (1, 'LOG.warning', "cinder/tests/fake.py", False),
        (1, 'LOG.error', "cinder/tests/fake.py", False),
        (1, 'LOG.exception', "cinder/tests/fake.py", False),
        (1, 'LOG.debug', "cinder/tests/fake.py", False),
        (0, 'LOG.info.assert_called_once_with', "cinder/tests/fake.py", False),
        (0, 'some.LOG.error.call', "cinder/tests/fake.py", False),
        (0, 'LOG.warning', "cinder/tests/unit/fake.py", True),
        (0, 'LOG.warning', "cinder/tests/unit/integrated/fake.py", False))
    def test_no_test_log(self, first, second, third, fourth):
        self.assertEqual(first, len(list(checks.no_test_log(
            "%s('arg')" % second, third, fourth))))
