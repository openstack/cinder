# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

"""Base classes for our unit tests.

Allows overriding of CONF for use of fakes, and some black magic for
inline callbacks.

"""


import functools
import os
import shutil
import uuid

import fixtures
import mox
from oslo.config import cfg
import stubout
import testtools

from cinder.common import config  # Need to register global_opts
from cinder.db import migration
from cinder.openstack.common.db.sqlalchemy import session
from cinder.openstack.common import log as logging
from cinder.openstack.common import timeutils
from cinder import service
from cinder.tests import conf_fixture


test_opts = [
    cfg.StrOpt('sqlite_clean_db',
               default='clean.sqlite',
               help='File name of clean sqlite db'),
    cfg.BoolOpt('fake_tests',
                default=True,
                help='should we use everything for testing'), ]

CONF = cfg.CONF
CONF.register_opts(test_opts)

LOG = logging.getLogger(__name__)

_DB_CACHE = None


class TestingException(Exception):
    pass


class Database(fixtures.Fixture):

    def __init__(self, db_session, db_migrate, sql_connection,
                 sqlite_db, sqlite_clean_db):
        self.sql_connection = sql_connection
        self.sqlite_db = sqlite_db
        self.sqlite_clean_db = sqlite_clean_db

        self.engine = db_session.get_engine()
        self.engine.dispose()
        conn = self.engine.connect()
        if sql_connection == "sqlite://":
            if db_migrate.db_version() > db_migrate.INIT_VERSION:
                return
        else:
            testdb = os.path.join(CONF.state_path, sqlite_db)
            if os.path.exists(testdb):
                return
        db_migrate.db_sync()
#        self.post_migrations()
        if sql_connection == "sqlite://":
            conn = self.engine.connect()
            self._DB = "".join(line for line in conn.connection.iterdump())
            self.engine.dispose()
        else:
            cleandb = os.path.join(CONF.state_path, sqlite_clean_db)
            shutil.copyfile(testdb, cleandb)

    def setUp(self):
        super(Database, self).setUp()

        if self.sql_connection == "sqlite://":
            conn = self.engine.connect()
            conn.connection.executescript(self._DB)
            self.addCleanup(self.engine.dispose)
        else:
            shutil.copyfile(
                os.path.join(CONF.state_path, self.sqlite_clean_db),
                os.path.join(CONF.state_path, self.sqlite_db))


class TestCase(testtools.TestCase):
    """Test case base class for all unit tests."""

    def setUp(self):
        """Run before each test method to initialize test environment."""
        super(TestCase, self).setUp()

        test_timeout = os.environ.get('OS_TEST_TIMEOUT', 0)
        try:
            test_timeout = int(test_timeout)
        except ValueError:
            # If timeout value is invalid do not set a timeout.
            test_timeout = 0
        if test_timeout > 0:
            self.useFixture(fixtures.Timeout(test_timeout, gentle=True))
        self.useFixture(fixtures.NestedTempfile())
        self.useFixture(fixtures.TempHomeDir())

        if (os.environ.get('OS_STDOUT_CAPTURE') == 'True' or
                os.environ.get('OS_STDOUT_CAPTURE') == '1'):
            stdout = self.useFixture(fixtures.StringStream('stdout')).stream
            self.useFixture(fixtures.MonkeyPatch('sys.stdout', stdout))
        if (os.environ.get('OS_STDERR_CAPTURE') == 'True' or
                os.environ.get('OS_STDERR_CAPTURE') == '1'):
            stderr = self.useFixture(fixtures.StringStream('stderr')).stream
            self.useFixture(fixtures.MonkeyPatch('sys.stderr', stderr))

        self.log_fixture = self.useFixture(fixtures.FakeLogger())

        conf_fixture.set_defaults(CONF)
        CONF([], default_config_files=[])

        # NOTE(vish): We need a better method for creating fixtures for tests
        #             now that we have some required db setup for the system
        #             to work properly.
        self.start = timeutils.utcnow()

        CONF.set_default('connection', 'sqlite://', 'database')
        CONF.set_default('sqlite_synchronous', False)

        self.log_fixture = self.useFixture(fixtures.FakeLogger())

        global _DB_CACHE
        if not _DB_CACHE:
            _DB_CACHE = Database(session, migration,
                                 sql_connection=CONF.database.connection,
                                 sqlite_db=CONF.sqlite_db,
                                 sqlite_clean_db=CONF.sqlite_clean_db)
        self.useFixture(_DB_CACHE)

        # emulate some of the mox stuff, we can't use the metaclass
        # because it screws with our generators
        self.mox = mox.Mox()
        self.stubs = stubout.StubOutForTesting()
        self.addCleanup(CONF.reset)
        self.addCleanup(self.mox.UnsetStubs)
        self.addCleanup(self.stubs.UnsetAll)
        self.addCleanup(self.stubs.SmartUnsetAll)
        self.addCleanup(self.mox.VerifyAll)
        self.injected = []
        self._services = []

        CONF.set_override('fatal_exception_format_errors', True)

    def tearDown(self):
        """Runs after each test method to tear down test environment."""

        # Stop any timers
        for x in self.injected:
            try:
                x.stop()
            except AssertionError:
                pass

        # Kill any services
        for x in self._services:
            try:
                x.kill()
            except Exception:
                pass

        # Delete attributes that don't start with _ so they don't pin
        # memory around unnecessarily for the duration of the test
        # suite
        for key in [k for k in self.__dict__.keys() if k[0] != '_']:
            del self.__dict__[key]
        super(TestCase, self).tearDown()

    def flags(self, **kw):
        """Override CONF variables for a test."""
        for k, v in kw.iteritems():
            CONF.set_override(k, v)

    def start_service(self, name, host=None, **kwargs):
        host = host and host or uuid.uuid4().hex
        kwargs.setdefault('host', host)
        kwargs.setdefault('binary', 'cinder-%s' % name)
        svc = service.Service.create(**kwargs)
        svc.start()
        self._services.append(svc)
        return svc

    # Useful assertions
    def assertDictMatch(self, d1, d2, approx_equal=False, tolerance=0.001):
        """Assert two dicts are equivalent.

        This is a 'deep' match in the sense that it handles nested
        dictionaries appropriately.

        NOTE:

            If you don't care (or don't know) a given value, you can specify
            the string DONTCARE as the value. This will cause that dict-item
            to be skipped.

        """
        def raise_assertion(msg):
            d1str = str(d1)
            d2str = str(d2)
            base_msg = ('Dictionaries do not match. %(msg)s d1: %(d1str)s '
                        'd2: %(d2str)s' %
                        {'msg': msg, 'd1str': d1str, 'd2str': d2str})
            raise AssertionError(base_msg)

        d1keys = set(d1.keys())
        d2keys = set(d2.keys())
        if d1keys != d2keys:
            d1only = d1keys - d2keys
            d2only = d2keys - d1keys
            raise_assertion('Keys in d1 and not d2: %(d1only)s. '
                            'Keys in d2 and not d1: %(d2only)s' %
                            {'d1only': d1only, 'd2only': d2only})

        for key in d1keys:
            d1value = d1[key]
            d2value = d2[key]
            try:
                error = abs(float(d1value) - float(d2value))
                within_tolerance = error <= tolerance
            except (ValueError, TypeError):
                # If both values aren't convertable to float, just ignore
                # ValueError if arg is a str, TypeError if it's something else
                # (like None)
                within_tolerance = False

            if hasattr(d1value, 'keys') and hasattr(d2value, 'keys'):
                self.assertDictMatch(d1value, d2value)
            elif 'DONTCARE' in (d1value, d2value):
                continue
            elif approx_equal and within_tolerance:
                continue
            elif d1value != d2value:
                raise_assertion("d1['%(key)s']=%(d1value)s != "
                                "d2['%(key)s']=%(d2value)s" %
                                {
                                    'key': key,
                                    'd1value': d1value,
                                    'd2value': d2value,
                                })

    def assertDictListMatch(self, L1, L2, approx_equal=False, tolerance=0.001):
        """Assert a list of dicts are equivalent."""
        def raise_assertion(msg):
            L1str = str(L1)
            L2str = str(L2)
            base_msg = ('List of dictionaries do not match: %(msg)s '
                        'L1: %(L1str)s L2: %(L2str)s' %
                        {'msg': msg, 'L1str': L1str, 'L2str': L2str})
            raise AssertionError(base_msg)

        L1count = len(L1)
        L2count = len(L2)
        if L1count != L2count:
            raise_assertion('Length mismatch: len(L1)=%(L1count)d != '
                            'len(L2)=%(L2count)d' %
                            {'L1count': L1count, 'L2count': L2count})

        for d1, d2 in zip(L1, L2):
            self.assertDictMatch(d1, d2, approx_equal=approx_equal,
                                 tolerance=tolerance)

    def assertSubDictMatch(self, sub_dict, super_dict):
        """Assert a sub_dict is subset of super_dict."""
        self.assertTrue(set(sub_dict.keys()).issubset(set(super_dict.keys())))
        for k, sub_value in sub_dict.items():
            super_value = super_dict[k]
            if isinstance(sub_value, dict):
                self.assertSubDictMatch(sub_value, super_value)
            elif 'DONTCARE' in (sub_value, super_value):
                continue
            else:
                self.assertEqual(sub_value, super_value)

    def assertIn(self, a, b, *args, **kwargs):
        """Python < v2.7 compatibility.  Assert 'a' in 'b'"""
        try:
            f = super(TestCase, self).assertIn
        except AttributeError:
            self.assertTrue(a in b, *args, **kwargs)
        else:
            f(a, b, *args, **kwargs)

    def assertNotIn(self, a, b, *args, **kwargs):
        """Python < v2.7 compatibility.  Assert 'a' NOT in 'b'"""
        try:
            f = super(TestCase, self).assertNotIn
        except AttributeError:
            self.assertFalse(a in b, *args, **kwargs)
        else:
            f(a, b, *args, **kwargs)
