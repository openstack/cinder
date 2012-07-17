# vim: tabstop=4 shiftwidth=4 softtabstop=4

#    Copyright 2010 OpenStack LLC
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

import commands
import errno
import glob
import os
import select

from eventlet import greenpool
from eventlet import greenthread
import lockfile

from cinder import exception
from cinder import test
from cinder import utils


class ExceptionTestCase(test.TestCase):
    @staticmethod
    def _raise_exc(exc):
        raise exc()

    def test_exceptions_raise(self):
        for name in dir(exception):
            exc = getattr(exception, name)
            if isinstance(exc, type):
                self.assertRaises(exc, self._raise_exc, exc)


class ProjectTestCase(test.TestCase):
    def test_authors_up_to_date(self):
        topdir = os.path.normpath(os.path.dirname(__file__) + '/../../')
        missing = set()
        contributors = set()
        mailmap = utils.parse_mailmap(os.path.join(topdir, '.mailmap'))
        authors_file = open(os.path.join(topdir,
                                         'Authors'), 'r').read().lower()

        if os.path.exists(os.path.join(topdir, '.git')):
            for email in commands.getoutput('git log --format=%ae').split():
                if not email:
                    continue
                if "jenkins" in email and "openstack.org" in email:
                    continue
                email = '<' + email.lower() + '>'
                contributors.add(utils.str_dict_replace(email, mailmap))
        else:
            return

        for contributor in contributors:
            if contributor == 'cinder-core':
                continue
            if not contributor in authors_file:
                missing.add(contributor)

        self.assertTrue(len(missing) == 0,
                        '%r not listed in Authors' % missing)

    def test_all_migrations_have_downgrade(self):
        topdir = os.path.normpath(os.path.dirname(__file__) + '/../../')
        py_glob = os.path.join(topdir, "cinder", "db", "sqlalchemy",
                               "migrate_repo", "versions", "*.py")
        missing_downgrade = []
        for path in glob.iglob(py_glob):
            has_upgrade = False
            has_downgrade = False
            with open(path, "r") as f:
                for line in f:
                    if 'def upgrade(' in line:
                        has_upgrade = True
                    if 'def downgrade(' in line:
                        has_downgrade = True

                if has_upgrade and not has_downgrade:
                    fname = os.path.basename(path)
                    missing_downgrade.append(fname)

        helpful_msg = (_("The following migrations are missing a downgrade:"
                         "\n\t%s") % '\n\t'.join(sorted(missing_downgrade)))
        self.assert_(not missing_downgrade, helpful_msg)
