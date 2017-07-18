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
import six

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
   cinder/tests/test_hacking.py

"""

# NOTE(thangp): Ignore N323 pep8 error caused by importing cinder objects
UNDERSCORE_IMPORT_FILES = ['cinder/objects/__init__.py',
                           'cinder/objects/manageableresources.py']

mutable_default_args = re.compile(r"^\s*def .+\((.+=\{\}|.+=\[\])")
translated_log = re.compile(
    r"(.)*LOG\.(audit|debug|error|info|warn|warning|critical|exception)"
    "\(\s*_\(\s*('|\")")
string_translation = re.compile(r"(.)*_\(\s*('|\")")
vi_header_re = re.compile(r"^#\s+vim?:.+")
underscore_import_check = re.compile(r"(.)*i18n\s+import(.)* _$")
underscore_import_check_multi = re.compile(r"(.)*i18n\s+import(.)* _, (.)*")
# We need this for cases where they have created their own _ function.
custom_underscore_check = re.compile(r"(.)*_\s*=\s*(.)*")
no_audit_log = re.compile(r"(.)*LOG\.audit(.)*")
no_print_statements = re.compile(r"\s*print\s*\(.+\).*")
dict_constructor_with_list_copy_re = re.compile(r".*\bdict\((\[)?(\(|\[)")

# NOTE(jsbryant): When other oslo libraries switch over non-namespaced
# imports, we will need to add them to the regex below.
oslo_namespace_imports = re.compile(r"from[\s]*oslo[.](concurrency|db"
                                    "|config|utils|serialization|log)")
no_contextlib_nested = re.compile(r"\s*with (contextlib\.)?nested\(")

logging_instance = re.compile(
    r"(.)*LOG\.(warning|info|debug|error|exception)\(")

assert_None = re.compile(
    r".*assertEqual\(None, .*\)")
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


def no_vi_headers(physical_line, line_number, lines):
    """Check for vi editor configuration in source files.

    By default vi modelines can only appear in the first or
    last 5 lines of a source file.

    N314
    """
    # NOTE(gilliard): line_number is 1-indexed
    if line_number <= 5 or line_number > len(lines) - 5:
        if vi_header_re.match(physical_line):
            return 0, "N314: Don't put vi configuration in source files"


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


def no_mutable_default_args(logical_line):
    msg = "N322: Method's default argument shouldn't be mutable!"
    if mutable_default_args.match(logical_line):
        yield (0, msg)


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


class CheckForStrUnicodeExc(BaseASTChecker):
    """Checks for the use of str() or unicode() on an exception.

    This currently only handles the case where str() or unicode()
    is used in the scope of an exception handler.  If the exception
    is passed into a function, returned from an assertRaises, or
    used on an exception created in the same scope, this does not
    catch it.
    """

    CHECK_DESC = ('N325 str() and unicode() cannot be used on an '
                  'exception.  Remove or use six.text_type()')

    def __init__(self, tree, filename):
        super(CheckForStrUnicodeExc, self).__init__(tree, filename)
        self.name = []
        self.already_checked = []

    # Python 2
    def visit_TryExcept(self, node):
        for handler in node.handlers:
            if handler.name:
                self.name.append(handler.name.id)
                super(CheckForStrUnicodeExc, self).generic_visit(node)
                self.name = self.name[:-1]
            else:
                super(CheckForStrUnicodeExc, self).generic_visit(node)

    # Python 3
    def visit_ExceptHandler(self, node):
        if node.name:
            self.name.append(node.name)
            super(CheckForStrUnicodeExc, self).generic_visit(node)
            self.name = self.name[:-1]
        else:
            super(CheckForStrUnicodeExc, self).generic_visit(node)

    def visit_Call(self, node):
        if self._check_call_names(node, ['str', 'unicode']):
            if node not in self.already_checked:
                self.already_checked.append(node)
                if isinstance(node.args[0], ast.Name):
                    if node.args[0].id in self.name:
                        self.add_error(node.args[0])
        super(CheckForStrUnicodeExc, self).generic_visit(node)


class CheckLoggingFormatArgs(BaseASTChecker):
    """Check for improper use of logging format arguments.

    LOG.debug("Volume %s caught fire and is at %d degrees C and climbing.",
              ('volume1', 500))

    The format arguments should not be a tuple as it is easy to miss.

    """

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
        elif isinstance(node, six.string_types):
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
        elif isinstance(node, six.string_types):
            return node
        else:  # could be Subscript, Call or many more
            return None

    def _is_list_or_tuple(self, obj):
        return isinstance(obj, ast.List) or isinstance(obj, ast.Tuple)

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


def check_datetime_now(logical_line, noqa):
    if noqa:
        return

    msg = ("C301: Found datetime.now(). "
           "Please use timeutils.utcnow() from oslo_utils.")
    if 'datetime.now' in logical_line:
        yield(0, msg)


_UNICODE_USAGE_REGEX = re.compile(r'\bunicode *\(')


def check_unicode_usage(logical_line, noqa):
    if noqa:
        return

    msg = "C302: Found unicode() call. Please use six.text_type()."

    if _UNICODE_USAGE_REGEX.search(logical_line):
        yield(0, msg)


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


def check_no_log_audit(logical_line):
    """Ensure that we are not using LOG.audit messages

    Plans are in place going forward as discussed in the following
    spec (https://review.openstack.org/#/c/91446/) to take out
    LOG.audit messages.  Given that audit was a concept invented
    for OpenStack we can enforce not using it.
    """

    if no_audit_log.match(logical_line):
        yield(0, "C304: Found LOG.audit.  Use LOG.info instead.")


def check_timeutils_strtime(logical_line):
    msg = ("C306: Found timeutils.strtime(). "
           "Please use datetime.datetime.isoformat() or datetime.strftime()")
    if 'timeutils.strtime' in logical_line:
        yield(0, msg)


def no_log_warn(logical_line):
    msg = "C307: LOG.warn is deprecated, please use LOG.warning!"
    if "LOG.warn(" in logical_line:
        yield (0, msg)


def dict_constructor_with_list_copy(logical_line):
    msg = ("N336: Must use a dict comprehension instead of a dict constructor "
           "with a sequence of key-value pairs.")
    if dict_constructor_with_list_copy_re.match(logical_line):
        yield (0, msg)


def check_timeutils_isotime(logical_line):
    msg = ("C308: Found timeutils.isotime(). "
           "Please use datetime.datetime.isoformat()")
    if 'timeutils.isotime' in logical_line:
        yield(0, msg)


def no_test_log(logical_line, filename, noqa):
    if ('cinder/tests/tempest' in filename or
            'cinder/tests' not in filename or noqa):
        return
    msg = "C309: Unit tests should not perform logging."
    if logging_instance.match(logical_line):
        yield (0, msg)


def validate_assertTrue(logical_line):
    if re.match(assert_True, logical_line):
        msg = ("C313: Unit tests should use assertTrue(value) instead"
               " of using assertEqual(True, value).")
        yield(0, msg)


def factory(register):
    register(no_vi_headers)
    register(no_translate_logs)
    register(no_mutable_default_args)
    register(check_explicit_underscore_import)
    register(CheckForStrUnicodeExc)
    register(CheckLoggingFormatArgs)
    register(CheckOptRegistrationArgs)
    register(check_datetime_now)
    register(check_timeutils_strtime)
    register(check_timeutils_isotime)
    register(check_unicode_usage)
    register(check_no_print_statements)
    register(check_no_log_audit)
    register(no_log_warn)
    register(dict_constructor_with_list_copy)
    register(no_test_log)
    register(validate_assertTrue)
