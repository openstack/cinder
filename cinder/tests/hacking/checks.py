# Copyright (c) 2014 OpenStack Foundation.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import ast
import re

from hacking import core

"""
Guidelines for writing new hacking checks

 - Use only for Cinder specific tests. OpenStack general tests
   should be submitted to the common 'hacking' module.
 - Pick numbers in the range N3xx. Find the current test with
   the highest allocated number and then pick the next value.
 - Keep the test method code in the source file ordered based
   on the N3xx value.
 - List the new rule in the top level HACKING.rst file
 - Add test cases for each new rule to
   cinder/tests/unit/test_hacking.py

"""

# NOTE(thangp): Ignore N323 pep8 error caused by importing cinder objects
UNDERSCORE_IMPORT_FILES = ['cinder/objects/__init__.py',
                           'cinder/objects/manageableresources.py']

mutable_default_args = re.compile(r"^\s*def .+\((.+=\{\}|.+=\[\])")
translated_log = re.compile(
    r"(.)*LOG\.(audit|debug|error|info|warn|warning|critical|exception)"
    r"\(\s*_\(\s*('|\")")
string_translation = re.compile(r"(.)*_\(\s*('|\")")
underscore_import_check = re.compile(r"(.)*i18n\s+import(.)* _$")
underscore_import_check_multi = re.compile(r"(.)*i18n\s+import(.)* _, (.)*")
# We need this for cases where they have created their own _ function.
custom_underscore_check = re.compile(r"(.)*_\s*=\s*(.)*")
no_print_statements = re.compile(r"\s*print\s*\(.+\).*")
dict_constructor_with_list_copy_re = re.compile(r".*\bdict\((\[)?(\(|\[)")

logging_instance = re.compile(
    r"(.)*LOG\.(warning|info|debug|error|exception)\(")

assert_True = re.compile(
    r".*assertEqual\(True, .*\)")


class BaseASTChecker(ast.NodeVisitor):
    """Provides a simple framework for writing AST-based checks.

    Subclasses should implement visit_* methods like any other AST visitor
    implementation. When they detect an error for a particular node the
    method should call ``self.add_error(offending_node)``. Details about
    where in the code the error occurred will be pulled from the node
    object.

    Subclasses should also provide a class variable named CHECK_DESC to
    be used for the human readable error message.

    """

    def __init__(self, tree, filename):
        """This object is created automatically by pep8.

        :param tree: an AST tree
        :param filename: name of the file being analyzed
                         (ignored by our checks)
        """
        self._tree = tree
        self._errors = []

    def run(self):
        """Called automatically by pep8."""
        self.visit(self._tree)
        return self._errors

    def add_error(self, node, message=None):
        """Add an error caused by a node to the list of errors for pep8."""

        # Need to disable pylint check here as it doesn't catch CHECK_DESC
        # being defined in the subclasses.
        message = message or self.CHECK_DESC  # pylint: disable=E1101
        error = (node.lineno, node.col_offset, message, self.__class__)
        self._errors.append(error)

    def _check_call_names(self, call_node, names):
        if isinstance(call_node, ast.Call):
            if isinstance(call_node.func, ast.Name):
                if call_node.func.id in names:
                    return True
        return False


@core.flake8ext
def no_translate_logs(logical_line, filename):
    """Check for 'LOG.*(_('

    Starting with the Pike series, OpenStack no longer supports log
    translation. We shouldn't translate logs.

    - This check assumes that 'LOG' is a logger.
    - Use filename so we can start enforcing this in specific folders
      instead of needing to do so all at once.

    C312
    """
    if translated_log.match(logical_line):
        yield(0, "C312: Log messages should not be translated!")


@core.flake8ext
def no_mutable_default_args(logical_line):
    msg = "N322: Method's default argument shouldn't be mutable!"
    if mutable_default_args.match(logical_line):
        yield (0, msg)


@core.flake8ext
def check_explicit_underscore_import(logical_line, filename):
    """Check for explicit import of the _ function

    We need to ensure that any files that are using the _() function
    to translate messages are explicitly importing the _ function.  We
    can't trust unit test to catch whether the import has been
    added so we need to check for it here.
    """

    # Build a list of the files that have _ imported.  No further
    # checking needed once it is found.
    for file in UNDERSCORE_IMPORT_FILES:
        if file in filename:
            return
    if (underscore_import_check.match(logical_line) or
            underscore_import_check_multi.match(logical_line) or
            custom_underscore_check.match(logical_line)):
        UNDERSCORE_IMPORT_FILES.append(filename)
    elif string_translation.match(logical_line):
        yield(0, "N323: Found use of _() without explicit import of _ !")


class CheckLoggingFormatArgs(BaseASTChecker):
    """Check for improper use of logging format arguments.

    LOG.debug("Volume %s caught fire and is at %d degrees C and climbing.",
              ('volume1', 500))

    The format arguments should not be a tuple as it is easy to miss.

    """

    name = 'check_logging_format_args'
    version = '1.0'

    CHECK_DESC = 'C310 Log method arguments should not be a tuple.'
    LOG_METHODS = [
        'debug', 'info',
        'warn', 'warning',
        'error', 'exception',
        'critical', 'fatal',
        'trace', 'log'
    ]

    def _find_name(self, node):
        """Return the fully qualified name or a Name or Attribute."""
        if isinstance(node, ast.Name):
            return node.id
        elif (isinstance(node, ast.Attribute)
                and isinstance(node.value, (ast.Name, ast.Attribute))):
            method_name = node.attr
            obj_name = self._find_name(node.value)
            if obj_name is None:
                return None
            return obj_name + '.' + method_name
        elif isinstance(node, str):
            return node
        else:  # could be Subscript, Call or many more
            return None

    def visit_Call(self, node):
        """Look for the 'LOG.*' calls."""
        # extract the obj_name and method_name
        if isinstance(node.func, ast.Attribute):
            obj_name = self._find_name(node.func.value)
            if isinstance(node.func.value, ast.Name):
                method_name = node.func.attr
            elif isinstance(node.func.value, ast.Attribute):
                obj_name = self._find_name(node.func.value)
                method_name = node.func.attr
            else:  # could be Subscript, Call or many more
                return super(CheckLoggingFormatArgs, self).generic_visit(node)

            # obj must be a logger instance and method must be a log helper
            if (obj_name != 'LOG'
                    or method_name not in self.LOG_METHODS):
                return super(CheckLoggingFormatArgs, self).generic_visit(node)

            # the call must have arguments
            if not len(node.args):
                return super(CheckLoggingFormatArgs, self).generic_visit(node)

            # any argument should not be a tuple
            for arg in node.args:
                if isinstance(arg, ast.Tuple):
                    self.add_error(arg)

        return super(CheckLoggingFormatArgs, self).generic_visit(node)


class CheckOptRegistrationArgs(BaseASTChecker):
    """Verifying the registration of options are well formed

    This class creates a check for single opt or list/tuple of
    opts when register_opt() or register_opts() are being called.
    """

    name = 'check_opt_registrationg_args'
    version = '1.0'

    CHECK_DESC = ('C311: Arguments being passed to register_opt/register_opts '
                  'must be a single option or list/tuple of options '
                  'respectively. Options must also end with _opt or _opts '
                  'respectively.')

    singular_method = 'register_opt'
    plural_method = 'register_opts'

    register_methods = [
        singular_method,
        plural_method,
    ]

    def _find_name(self, node):
        """Return the fully qualified name or a Name or Attribute."""
        if isinstance(node, ast.Name):
            return node.id
        elif (isinstance(node, ast.Attribute)
                and isinstance(node.value, (ast.Name, ast.Attribute))):
            method_name = node.attr
            obj_name = self._find_name(node.value)
            if obj_name is None:
                return None
            return obj_name + '.' + method_name
        elif isinstance(node, str):
            return node
        else:  # could be Subscript, Call or many more
            return None

    def _is_list_or_tuple(self, obj):
        return isinstance(obj, (ast.List, ast.Tuple))

    def visit_Call(self, node):
        """Look for the register_opt/register_opts calls."""
        # extract the obj_name and method_name
        if isinstance(node.func, ast.Attribute):
            if not isinstance(node.func.value, ast.Name):
                return (super(CheckOptRegistrationArgs,
                              self).generic_visit(node))

            method_name = node.func.attr

            # obj must be instance of register_opt() or register_opts()
            if method_name not in self.register_methods:
                return (super(CheckOptRegistrationArgs,
                              self).generic_visit(node))

            if len(node.args) > 0:
                argument_name = self._find_name(node.args[0])
                if argument_name:
                    if (method_name == self.singular_method and
                            not argument_name.lower().endswith('opt')):
                        self.add_error(node.args[0])
                    elif (method_name == self.plural_method and
                            not argument_name.lower().endswith('opts')):
                        self.add_error(node.args[0])
                else:
                    # This covers instances of register_opt()/register_opts()
                    # that are registering the objects directly and not
                    # passing in a variable referencing the options being
                    # registered.
                    if (method_name == self.singular_method and
                            self._is_list_or_tuple(node.args[0])):
                        self.add_error(node.args[0])
                    elif (method_name == self.plural_method and not
                            self._is_list_or_tuple(node.args[0])):
                        self.add_error(node.args[0])

        return super(CheckOptRegistrationArgs, self).generic_visit(node)


@core.flake8ext
def check_datetime_now(logical_line, noqa):
    if noqa:
        return

    msg = ("C301: Found datetime.now(). "
           "Please use timeutils.utcnow() from oslo_utils.")
    if 'datetime.now' in logical_line:
        yield(0, msg)


@core.flake8ext
def check_no_print_statements(logical_line, filename, noqa):
    # CLI and utils programs do need to use 'print()' so
    # we shouldn't check those files.
    if noqa:
        return

    if "cinder/cmd" in filename or "tools/" in filename:
        return

    if re.match(no_print_statements, logical_line):
        msg = ("C303: print() should not be used. "
               "Please use LOG.[info|error|warning|exception|debug]. "
               "If print() must be used, use '# noqa' to skip this check.")
        yield(0, msg)


@core.flake8ext
def check_timeutils_strtime(logical_line):
    msg = ("C306: Found timeutils.strtime(). "
           "Please use datetime.datetime.isoformat() or datetime.strftime()")
    if 'timeutils.strtime' in logical_line:
        yield(0, msg)


@core.flake8ext
def dict_constructor_with_list_copy(logical_line):
    msg = ("N336: Must use a dict comprehension instead of a dict constructor "
           "with a sequence of key-value pairs.")
    if dict_constructor_with_list_copy_re.match(logical_line):
        yield (0, msg)


@core.flake8ext
def check_timeutils_isotime(logical_line):
    msg = ("C308: Found timeutils.isotime(). "
           "Please use datetime.datetime.isoformat()")
    if 'timeutils.isotime' in logical_line:
        yield(0, msg)


@core.flake8ext
def no_test_log(logical_line, filename, noqa):
    if ('cinder/tests' not in filename or noqa):
        return
    msg = "C309: Unit tests should not perform logging."
    if logging_instance.match(logical_line):
        yield (0, msg)


@core.flake8ext
def validate_assertTrue(logical_line, filename):
    # Note: a comparable check cannot be implemented for
    # assertFalse(), because assertFalse(None) passes.
    # Therefore, assertEqual(False, value) is required to
    # have the strongest test.
    if 'cinder/tests/unit' not in filename:
        return

    if re.match(assert_True, logical_line):
        msg = ("C313: Unit tests should use assertTrue(value) instead"
               " of using assertEqual(True, value).")
        yield(0, msg)


third_party_mock = re.compile("^import.mock")
from_third_party_mock = re.compile("^from.mock.import")


@core.flake8ext
def no_third_party_mock(logical_line):
    # We should only use unittest.mock, not the third party mock library that
    # was needed for py2 support.
    if (re.match(third_party_mock, logical_line) or
            re.match(from_third_party_mock, logical_line)):
        msg = ('C337: Unit tests should use the standard library "mock" '
               'module, not the third party mock lib.')
        yield(0, msg)
