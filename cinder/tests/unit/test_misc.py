
#    Copyright 2010 OpenStack Foundation
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

import glob
import os


from cinder import exception
from cinder.i18n import _
from cinder import test


class ExceptionTestCase(test.TestCase):
    @staticmethod
    def _raise_exc(exc):
        raise exc()

    def test_exceptions_raise(self):
        # NOTE(dprince): disable format errors since we are not passing kwargs
        self.flags(fatal_exception_format_errors=False)
        for name in dir(exception):
            exc = getattr(exception, name)
            if isinstance(exc, type):
                self.assertRaises(exc, self._raise_exc, exc)


class ProjectTestCase(test.TestCase):
    def test_all_migrations_have_downgrade(self):
        topdir = os.path.normpath(os.path.dirname(__file__) + '/../../../')
        py_glob = os.path.join(topdir, "cinder", "db", "sqlalchemy",
                               "migrate_repo", "versions", "*.py")
        downgrades = []
        for path in glob.iglob(py_glob):
            has_upgrade = False
            has_downgrade = False
            with open(path, "r") as f:
                for line in f:
                    if 'def upgrade(' in line:
                        has_upgrade = True
                    if 'def downgrade(' in line:
                        has_downgrade = True

                if has_upgrade and has_downgrade:
                    fname = os.path.basename(path)
                    downgrades.append(fname)

        helpful_msg = (_("The following migrations have a downgrade, "
                         "which are not allowed: "
                         "\n\t%s") % '\n\t'.join(sorted(downgrades)))
        self.assertFalse(downgrades, msg=helpful_msg)
