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

import textwrap

import mock
import pep8

from cinder.hacking import checks
from cinder import test


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

    def test_check_assert_called_once(self):
        self.assertEqual(0, len(list(checks.check_assert_called_once(
            ".assert_called_with(", "cinder/tests/unit/test1.py"))))
        self.assertEqual(0, len(list(checks.check_assert_called_once(
            ".assert_called_with(", "cinder/blah.py"))))
        self.assertEqual(1, len(list(checks.check_assert_called_once(
            ".assert_called_once(", "cinder/tests/unit/test1.py"))))
        self.assertEqual(0, len(list(checks.check_assert_called_once(
            ".assertEqual(", "cinder/tests/unit/test1.py"))))

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
