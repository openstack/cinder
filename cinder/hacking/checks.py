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

UNDERSCORE_IMPORT_FILES = []

translated_log = re.compile(
    r"(.)*LOG\.(audit|error|info|warn|warning|critical|exception)"
    "\(\s*_\(\s*('|\")")
string_translation = re.compile(r"(.)*_\(\s*('|\")")
vi_header_re = re.compile(r"^#\s+vim?:.+")
underscore_import_check = re.compile(r"(.)*import _(.)*")
# We need this for cases where they have created their own _ function.
custom_underscore_check = re.compile(r"(.)*_\s*=\s*(.)*")
no_audit_log = re.compile(r"(.)*LOG\.audit(.)*")


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


def check_no_log_audit(logical_line):
    """Ensure that we are not using LOG.audit messages

    Plans are in place going forward as discussed in the following
    spec (https://review.openstack.org/#/c/91446/) to take out
    LOG.audit messages.  Given that audit was a concept invented
    for OpenStack we can enforce not using it.
    """

    if no_audit_log.match(logical_line):
        yield(0, "N324: Found LOG.audit.  Use LOG.info instead.")


def factory(register):
    register(no_vi_headers)
    register(no_translate_debug_logs)
    register(no_mutable_default_args)
    register(check_explicit_underscore_import)
    register(check_no_log_audit)
