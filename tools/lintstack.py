#!/usr/bin/env python
# Copyright (c) 2013, AT&T Labs, Yun Mao <yunmao@gmail.com>
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

"""pylint error checking."""

from __future__ import print_function

import json
import re
import sys

from pylint import lint
from pylint.reporters import text
from six.moves import cStringIO as StringIO

ignore_codes = [
    # Note(maoy): E1103 is error code related to partial type inference
    "E1103"
]

ignore_messages = [
    # Note(maoy): this error message is the pattern of E0202. It should be
    # ignored for cinder.tests modules
    "An attribute affected in cinder.tests",

    # Note(fengqian): this error message is the pattern of [E0611].
    "No name 'urllib' in module '_MovedItems'",

    # Note(e0ne): this error message is for SQLAlchemy update() calls
    # It should be ignored because use six module to keep py3.X compatibility.
    # in DB schema migrations.
    "No value passed for parameter 'dml'",

    # Note(xyang): these error messages are for the code [E1101].
    # They should be ignored because 'sha256' and 'sha224' are functions in
    # 'hashlib'.
    "Module 'hashlib' has no 'sha256' member",
    "Module 'hashlib' has no 'sha224' member",

    # Note(aarefiev): this error message is for SQLAlchemy rename calls in
    # DB migration(033_add_encryption_unique_key).
    "Instance of 'Table' has no 'rename' member",

    # NOTE(geguileo): these error messages are for code [E1101], and they can
    # be ignored because a SQLAlchemy ORM class will have __table__ member
    # during runtime.
    "Class 'ConsistencyGroup' has no '__table__' member",
    "Class 'Cgsnapshot' has no '__table__' member",
    "Class 'Group' has no '__table__' member",
    "Class 'GroupSnapshot' has no '__table__' member",

    # NOTE(xyang): this error message is for code [E1120] when checking if
    # there are already 'groups' entries in 'quota_classes' `in DB migration
    # (078_add_groups_and_group_volume_type_mapping_table).
    "No value passed for parameter 'functions' in function call",

    # NOTE(dulek): This one is related to objects.
    "No value passed for parameter 'id' in function call",

    # NOTE(geguileo): v3 common manage class for volumes and snapshots
    "Instance of 'ManageResource' has no 'volume_api' member",
    "Instance of 'ManageResource' has no '_list_manageable_view' member",
]

# Note(maoy):  We ignore cinder.tests for now due to high false
# positive rate.
ignore_modules = ["cinder/tests/"]

# Note(thangp): E0213, E1101, and E1102 should be ignored for only
# cinder.object modules. E0213 and E1102 are error codes related to
# the first argument of a method, but should be ignored because the method
# is a remotable class method. E1101 is error code related to accessing a
# non-existent member of an object, but should be ignored because the object
# member is created dynamically.
objects_ignore_codes = ["E0213", "E1101", "E1102"]
# NOTE(dulek): We're ignoring messages related to non-existent objects in
# cinder.objects namespace. This is because this namespace is populated when
# registering the objects, and pylint is unable to detect that.
objects_ignore_regexp = "Module 'cinder.objects' has no '.*' member"
objects_ignore_modules = ["cinder/objects/"]

KNOWN_PYLINT_EXCEPTIONS_FILE = "tools/pylint_exceptions"


class LintOutput(object):

    _cached_filename = None
    _cached_content = None

    def __init__(self, filename, lineno, line_content, code, message,
                 lintoutput):
        self.filename = filename
        self.lineno = lineno
        self.line_content = line_content
        self.code = code
        self.message = message
        self.lintoutput = lintoutput

    @classmethod
    def from_line(cls, line):
        m = re.search(r"(\S+):(\d+): \[(\S+)(, \S+)?] (.*)", line)
        matched = m.groups()
        filename, lineno, code, message = (matched[0], int(matched[1]),
                                           matched[2], matched[-1])
        if cls._cached_filename != filename:
            with open(filename) as f:
                cls._cached_content = list(f.readlines())
                cls._cached_filename = filename
        line_content = cls._cached_content[lineno - 1].rstrip()
        return cls(filename, lineno, line_content, code, message,
                   line.rstrip())

    @classmethod
    def from_msg_to_dict(cls, msg):
        """From the output of pylint msg, to a dict, where each key
        is a unique error identifier, value is a list of LintOutput
        """
        result = {}
        for line in msg.splitlines():
            obj = cls.from_line(line)
            if obj.is_ignored():
                continue
            key = obj.key()
            if key not in result:
                result[key] = []
            result[key].append(obj)
        return result

    def is_ignored(self):
        if self.code in ignore_codes:
            return True
        if any(self.filename.startswith(name) for name in ignore_modules):
            return True
        if any(msg in self.message for msg in ignore_messages):
            return True
        if re.match(objects_ignore_regexp, self.message):
            return True
        if (self.code in objects_ignore_codes and
            any(self.filename.startswith(name)
                for name in objects_ignore_modules)):
            return True
        if (self.code in objects_ignore_codes and
            any(self.filename.startswith(name)
                for name in objects_ignore_modules)):
            return True
        return False

    def key(self):
        if self.code in ["E1101", "E1103"]:
            # These two types of errors are like Foo class has no member bar.
            # We discard the source code so that the error will be ignored
            # next time another Foo.bar is encountered.
            return self.message, ""
        return self.message, self.line_content.strip()

    def json(self):
        return json.dumps(self.__dict__)

    def review_str(self):
        return ("File %(filename)s\nLine %(lineno)d:%(line_content)s\n"
                "%(code)s: %(message)s" %
                {'filename': self.filename,
                 'lineno': self.lineno,
                 'line_content': self.line_content,
                 'code': self.code,
                 'message': self.message})


class ErrorKeys(object):

    @classmethod
    def print_json(cls, errors, output=sys.stdout):
        print("# automatically generated by tools/lintstack.py", file=output)
        for i in sorted(errors.keys()):
            print(json.dumps(i), file=output)

    @classmethod
    def from_file(cls, filename):
        keys = set()
        for line in open(filename):
            if line and line[0] != "#":
                d = json.loads(line)
                keys.add(tuple(d))
        return keys


def run_pylint():
    buff = StringIO()
    reporter = text.ParseableTextReporter(output=buff)
    args = ["--include-ids=y", "-E", "cinder"]
    lint.Run(args, reporter=reporter, exit=False)
    val = buff.getvalue()
    buff.close()
    return val


def generate_error_keys(msg=None):
    print("Generating", KNOWN_PYLINT_EXCEPTIONS_FILE)
    if msg is None:
        msg = run_pylint()
    errors = LintOutput.from_msg_to_dict(msg)
    with open(KNOWN_PYLINT_EXCEPTIONS_FILE, "w") as f:
        ErrorKeys.print_json(errors, output=f)


def validate(newmsg=None):
    print("Loading", KNOWN_PYLINT_EXCEPTIONS_FILE)
    known = ErrorKeys.from_file(KNOWN_PYLINT_EXCEPTIONS_FILE)
    if newmsg is None:
        print("Running pylint. Be patient...")
        newmsg = run_pylint()
    errors = LintOutput.from_msg_to_dict(newmsg)

    print("Unique errors reported by pylint: was %d, now %d."
          % (len(known), len(errors)))
    passed = True
    for err_key, err_list in errors.items():
        for err in err_list:
            if err_key not in known:
                print(err.lintoutput)
                print()
                passed = False
    if passed:
        print("Congrats! pylint check passed.")
        redundant = known - set(errors.keys())
        if redundant:
            print("Extra credit: some known pylint exceptions disappeared.")
            for i in sorted(redundant):
                print(json.dumps(i))
            print("Consider regenerating the exception file if you will.")
    else:
        print("Please fix the errors above. If you believe they are false "
              "positives, run 'tools/lintstack.py generate' to overwrite.")
        sys.exit(1)


def usage():
    print("""Usage: tools/lintstack.py [generate|validate]
    To generate pylint_exceptions file: tools/lintstack.py generate
    To validate the current commit: tools/lintstack.py
    """)


def main():
    option = "validate"
    if len(sys.argv) > 1:
        option = sys.argv[1]
    if option == "generate":
        generate_error_keys()
    elif option == "validate":
        validate()
    else:
        usage()


if __name__ == "__main__":
    main()
