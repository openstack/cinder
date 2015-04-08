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

import re

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
UNDERSCORE_IMPORT_FILES = ['./cinder/objects/__init__.py']

translated_log = re.compile(
    r"(.)*LOG\.(audit|error|info|warn|warning|critical|exception)"
    "\(\s*_\(\s*('|\")")
string_translation = re.compile(r"(.)*_\(\s*('|\")")
vi_header_re = re.compile(r"^#\s+vim?:.+")
underscore_import_check = re.compile(r"(.)*i18n\s+import\s+_(.)*")
# We need this for cases where they have created their own _ function.
custom_underscore_check = re.compile(r"(.)*_\s*=\s*(.)*")
no_audit_log = re.compile(r"(.)*LOG\.audit(.)*")
no_print_statements = re.compile(r"\s*print\s*\(.+\).*")

# NOTE(jsbryant): When other oslo libraries switch over non-namespaced
# imports, we will need to add them to the regex below.
oslo_namespace_imports = re.compile(r"from[\s]*oslo[.](concurrency|db"
                                    "|config|utils|serialization|log)")
no_contextlib_nested = re.compile(r"\s*with (contextlib\.)?nested\(")

log_translation_LI = re.compile(
    r"(.)*LOG\.(info)\(\s*(_\(|'|\")")
log_translation_LE = re.compile(
    r"(.)*LOG\.(exception|error)\(\s*(_\(|'|\")")
log_translation_LW = re.compile(
    r"(.)*LOG\.(warning|warn)\(\s*(_\(|'|\")")


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


def no_translate_debug_logs(logical_line, filename):
    """Check for 'LOG.debug(_('

    As per our translation policy,
    https://wiki.openstack.org/wiki/LoggingStandards#Log_Translation
    we shouldn't translate debug level logs.

    * This check assumes that 'LOG' is a logger.
    * Use filename so we can start enforcing this in specific folders instead
      of needing to do so all at once.
    N319
    """
    if logical_line.startswith("LOG.debug(_("):
        yield(0, "N319 Don't translate debug level logs")


def no_mutable_default_args(logical_line):
    msg = "N322: Method's default argument shouldn't be mutable!"
    mutable_default_args = re.compile(r"^\s*def .+\((.+=\{\}|.+=\[\])")
    if mutable_default_args.match(logical_line):
        yield (0, msg)


def check_explicit_underscore_import(logical_line, filename):
    """Check for explicit import of the _ function

    We need to ensure that any files that are using the _() function
    to translate logs are explicitly importing the _ function.  We
    can't trust unit test to catch whether the import has been
    added so we need to check for it here.
    """

    # Build a list of the files that have _ imported.  No further
    # checking needed once it is found.
    if filename in UNDERSCORE_IMPORT_FILES:
        pass
    elif (underscore_import_check.match(logical_line) or
          custom_underscore_check.match(logical_line)):
        UNDERSCORE_IMPORT_FILES.append(filename)
    elif(translated_log.match(logical_line) or
         string_translation.match(logical_line)):
        yield(0, "N323: Found use of _() without explicit import of _ !")


def check_assert_called_once(logical_line, filename):
    msg = ("N327: assert_called_once is a no-op. please use assert_called_"
           "once_with to test with explicit parameters or an assertEqual with"
           " call_count.")

    if 'cinder/tests/' in filename:
        pos = logical_line.find('.assert_called_once(')
        if pos != -1:
            yield (pos, msg)


def validate_log_translations(logical_line, filename):
    # TODO(smcginnis): The following is temporary as a series
    # of patches are done to address these issues. It should be
    # removed completely when bug 1433216 is closed.
    ignore_dirs = [
        "cinder/brick",
        "cinder/db",
        "cinder/openstack",
        "cinder/scheduler",
        "cinder/volume",
        "cinder/zonemanager"]
    for directory in ignore_dirs:
        if directory in filename:
            return

    # Translations are not required in the test directory.
    # This will not catch all instances of violations, just direct
    # misuse of the form LOG.info('Message').
    if "cinder/tests" in filename:
        return
    msg = "N328: LOG.info messages require translations `_LI()`!"
    if log_translation_LI.match(logical_line):
        yield (0, msg)
    msg = ("N329: LOG.exception and LOG.error messages require "
           "translations `_LE()`!")
    if log_translation_LE.match(logical_line):
        yield (0, msg)
    msg = "N330: LOG.warning messages require translations `_LW()`!"
    if log_translation_LW.match(logical_line):
        yield (0, msg)


def check_oslo_namespace_imports(logical_line):
    if re.match(oslo_namespace_imports, logical_line):
        msg = ("N333: '%s' must be used instead of '%s'.") % (
            logical_line.replace('oslo.', 'oslo_'),
            logical_line)
        yield(0, msg)


def check_datetime_now(logical_line, noqa):
    if noqa:
        return

    msg = ("C301: Found datetime.now(). "
           "Please use timeutils.utcnow() from oslo_utils.")
    if 'datetime.now' in logical_line:
        yield(0, msg)


def check_unicode_usage(logical_line, noqa):
    if noqa:
        return

    msg = "C302: Found unicode() call. Please use six.text_type()."

    if 'unicode(' in logical_line:
        yield(0, msg)


def check_no_print_statements(logical_line, filename, noqa):
    # The files in cinder/cmd do need to use 'print()' so
    # we don't need to check those files.  Other exemptions
    # should use '# noqa' to avoid failing here.
    if "cinder/cmd" not in filename and not noqa:
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


def check_no_contextlib_nested(logical_line):
    msg = ("C305: contextlib.nested is deprecated. With Python 2.7 and later "
           "the with-statement supports multiple nested objects. See https://"
           "docs.python.org/2/library/contextlib.html#contextlib.nested "
           "for more information.")
    if no_contextlib_nested.match(logical_line):
        yield(0, msg)


def factory(register):
    register(no_vi_headers)
    register(no_translate_debug_logs)
    register(no_mutable_default_args)
    register(check_explicit_underscore_import)
    register(check_assert_called_once)
    register(check_oslo_namespace_imports)
    register(check_datetime_now)
    register(validate_log_translations)
    register(check_unicode_usage)
    register(check_no_print_statements)
    register(check_no_log_audit)
    register(check_no_contextlib_nested)
