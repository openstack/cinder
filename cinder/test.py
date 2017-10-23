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
import copy
import logging
import os
import uuid

import fixtures
import mock
from oslo_concurrency import lockutils
from oslo_config import cfg
from oslo_config import fixture as config_fixture
from oslo_log.fixture import logging_error as log_fixture
import oslo_messaging
from oslo_messaging import conffixture as messaging_conffixture
from oslo_serialization import jsonutils
from oslo_utils import strutils
from oslo_utils import timeutils
from oslotest import moxstubout
import six
import testtools

from cinder.common import config  # noqa Need to register global_opts
from cinder import context
from cinder import coordination
from cinder.db import migration
from cinder.db.sqlalchemy import api as sqla_api
from cinder import i18n
from cinder.objects import base as objects_base
from cinder import rpc
from cinder import service
from cinder.tests import fixtures as cinder_fixtures
from cinder.tests.unit import conf_fixture
from cinder.tests.unit import fake_notifier
from cinder.volume import utils


CONF = cfg.CONF

_DB_CACHE = None


class TestingException(Exception):
    pass


class Database(fixtures.Fixture):

    def __init__(self, db_api, db_migrate, sql_connection):
        self.sql_connection = sql_connection

        # Suppress logging for test runs
        migrate_logger = logging.getLogger('migrate')
        migrate_logger.setLevel(logging.WARNING)

        self.engine = db_api.get_engine()
        self.engine.dispose()
        conn = self.engine.connect()
        db_migrate.db_sync()
        self._DB = "".join(line for line in conn.connection.iterdump())
        self.engine.dispose()

    def setUp(self):
        super(Database, self).setUp()

        conn = self.engine.connect()
        conn.connection.executescript(self._DB)
        self.addCleanup(self.engine.dispose)


class TestCase(testtools.TestCase):
    """Test case base class for all unit tests."""

    POLICY_PATH = 'cinder/tests/unit/policy.json'
    RESOURCE_FILTER_PATH = 'etc/cinder/resource_filters.json'
    MOCK_WORKER = True
    MOCK_TOOZ = True

    def _get_joined_notifier(self, *args, **kwargs):
        # We create a new fake notifier but we join the notifications with
        # the default notifier
        notifier = fake_notifier.get_fake_notifier(*args, **kwargs)
        notifier.notifications = self.notifier.notifications
        return notifier

    def setUp(self):
        """Run before each test method to initialize test environment."""
        super(TestCase, self).setUp()

        # Create default notifier
        self.notifier = fake_notifier.get_fake_notifier()

        # Mock rpc get notifier with fake notifier method that joins all
        # notifications with the default notifier
        self.patch('cinder.rpc.get_notifier',
                   side_effect=self._get_joined_notifier)

        if self.MOCK_WORKER:
            # Mock worker creation for all tests that don't care about it
            clean_path = 'cinder.objects.cleanable.CinderCleanableObject.%s'
            for method in ('create_worker', 'set_worker', 'unset_worker'):
                self.patch(clean_path % method, return_value=None)

        if self.MOCK_TOOZ:
            self.patch('cinder.coordination.Coordinator.start')
            self.patch('cinder.coordination.Coordinator.stop')
            self.patch('cinder.coordination.Coordinator.get_lock')

        # Unit tests do not need to use lazy gettext
        i18n.enable_lazy(False)

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

        environ_enabled = (lambda var_name:
                           strutils.bool_from_string(os.environ.get(var_name)))
        if environ_enabled('OS_STDOUT_CAPTURE'):
            stdout = self.useFixture(fixtures.StringStream('stdout')).stream
            self.useFixture(fixtures.MonkeyPatch('sys.stdout', stdout))
        if environ_enabled('OS_STDERR_CAPTURE'):
            stderr = self.useFixture(fixtures.StringStream('stderr')).stream
            self.useFixture(fixtures.MonkeyPatch('sys.stderr', stderr))

        self.useFixture(log_fixture.get_logging_handle_error_fixture())
        self.useFixture(cinder_fixtures.StandardLogging())

        rpc.add_extra_exmods("cinder.tests.unit")
        self.addCleanup(rpc.clear_extra_exmods)
        self.addCleanup(rpc.cleanup)

        self.messaging_conf = messaging_conffixture.ConfFixture(CONF)
        self.messaging_conf.transport_driver = 'fake'
        self.messaging_conf.response_timeout = 15
        self.useFixture(self.messaging_conf)

        # Load oslo_messaging_notifications config group so we can set an
        # override to prevent notifications from being ignored due to the
        # short-circuit mechanism.
        oslo_messaging.get_notification_transport(CONF)
        #  We need to use a valid driver for the notifications, so we use test.
        self.override_config('driver', ['test'],
                             group='oslo_messaging_notifications')
        rpc.init(CONF)

        # NOTE(geguileo): This is required because _determine_obj_version_cap
        # and _determine_rpc_version_cap functions in cinder.rpc.RPCAPI cache
        # versions in LAST_RPC_VERSIONS and LAST_OBJ_VERSIONS so we may have
        # weird interactions between tests if we don't clear them before each
        # test.
        rpc.LAST_OBJ_VERSIONS = {}
        rpc.LAST_RPC_VERSIONS = {}

        conf_fixture.set_defaults(CONF)
        CONF([], default_config_files=[])

        # NOTE(vish): We need a better method for creating fixtures for tests
        #             now that we have some required db setup for the system
        #             to work properly.
        self.start = timeutils.utcnow()

        CONF.set_default('connection', 'sqlite://', 'database')
        CONF.set_default('sqlite_synchronous', False, 'database')

        global _DB_CACHE
        if not _DB_CACHE:
            _DB_CACHE = Database(sqla_api, migration,
                                 sql_connection=CONF.database.connection)
        self.useFixture(_DB_CACHE)

        # NOTE(danms): Make sure to reset us back to non-remote objects
        # for each test to avoid interactions. Also, backup the object
        # registry.
        objects_base.CinderObject.indirection_api = None
        self._base_test_obj_backup = copy.copy(
            objects_base.CinderObjectRegistry._registry._obj_classes)
        self.addCleanup(self._restore_obj_registry)

        # emulate some of the mox stuff, we can't use the metaclass
        # because it screws with our generators
        mox_fixture = self.useFixture(moxstubout.MoxStubout())
        self.mox = mox_fixture.mox
        self.stubs = mox_fixture.stubs
        self.addCleanup(CONF.reset)
        self.addCleanup(self._common_cleanup)
        self.injected = []
        self._services = []

        fake_notifier.mock_notifier(self)

        self.override_config('fatal_exception_format_errors', True)
        # This will be cleaned up by the NestedTempfile fixture
        lock_path = self.useFixture(fixtures.TempDir()).path
        self.fixture = self.useFixture(
            config_fixture.Config(lockutils.CONF))
        self.fixture.config(lock_path=lock_path,
                            group='oslo_concurrency')
        lockutils.set_defaults(lock_path)
        self.override_config('policy_file',
                             os.path.join(
                                 os.path.abspath(
                                     os.path.join(
                                         os.path.dirname(__file__),
                                         '..',
                                     )
                                 ),
                                 self.POLICY_PATH),
                             group='oslo_policy')
        self.override_config('resource_query_filters_file',
                             os.path.join(
                                 os.path.abspath(
                                     os.path.join(
                                         os.path.dirname(__file__),
                                         '..',
                                     )
                                 ),
                                 self.RESOURCE_FILTER_PATH))
        self._disable_osprofiler()

        # NOTE(geguileo): This is required because common get_by_id method in
        # cinder.db.sqlalchemy.api caches get methods and if we use a mocked
        # get method in one test it would carry on to the next test.  So we
        # clear out the cache.
        sqla_api._GET_METHODS = {}

        self.override_config('backend_url', 'file://' + lock_path,
                             group='coordination')
        coordination.COORDINATOR.start()
        self.addCleanup(coordination.COORDINATOR.stop)

    def _restore_obj_registry(self):
        objects_base.CinderObjectRegistry._registry._obj_classes = \
            self._base_test_obj_backup

    def _disable_osprofiler(self):
        """Disable osprofiler.

        osprofiler should not run for unit tests.
        """

        side_effect = lambda value: value
        mock_decorator = mock.MagicMock(side_effect=side_effect)
        p = mock.patch("osprofiler.profiler.trace_cls",
                       return_value=mock_decorator)
        p.start()

    def _common_cleanup(self):
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

    def override_config(self, name, override, group=None):
        """Cleanly override CONF variables."""
        CONF.set_override(name, override, group)
        self.addCleanup(CONF.clear_override, name, group)

    def flags(self, **kw):
        """Override CONF variables for a test."""
        for k, v in kw.items():
            self.override_config(k, v)

    def start_service(self, name, host=None, **kwargs):
        host = host if host else uuid.uuid4().hex
        kwargs.setdefault('host', host)
        kwargs.setdefault('binary', 'cinder-%s' % name)
        svc = service.Service.create(**kwargs)
        svc.start()
        self._services.append(svc)
        return svc

    def mock_object(self, obj, attr_name, *args, **kwargs):
        """Use python mock to mock an object attribute

        Mocks the specified objects attribute with the given value.
        Automatically performs 'addCleanup' for the mock.

        """
        patcher = mock.patch.object(obj, attr_name, *args, **kwargs)
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result

    def patch(self, path, *args, **kwargs):
        """Use python mock to mock a path with automatic cleanup."""
        patcher = mock.patch(path, *args, **kwargs)
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result

    # Useful assertions
    def assert_notify_called(self, mock_notify, calls):
        for i in range(0, len(calls)):
            mock_call = mock_notify.call_args_list[i]
            call = calls[i]

            posargs = mock_call[0]

            self.assertEqual(call[0], posargs[0])
            self.assertEqual(call[1], posargs[2])

    def assertTrue(self, x, *args, **kwargs):
        if isinstance(x, six.string_types):
            raise AssertionError("%s (%s) is a string. Use a more "
                                 "specific assertion such as assertEqual." %
                                 (x, type(x)))
        super(TestCase, self).assertTrue(x, *args, **kwargs)


class ModelsObjectComparatorMixin(object):
    def _dict_from_object(self, obj, ignored_keys):
        if ignored_keys is None:
            ignored_keys = []
        obj = jsonutils.to_primitive(obj)  # Convert to dict first.
        items = obj.items()
        return {k: v for k, v in items
                if k not in ignored_keys}

    def _assertEqualObjects(self, obj1, obj2, ignored_keys=None):
        obj1 = self._dict_from_object(obj1, ignored_keys)
        obj2 = self._dict_from_object(obj2, ignored_keys)

        self.assertEqual(
            len(obj1), len(obj2),
            "Keys mismatch: %s" % six.text_type(
                set(obj1.keys()) ^ set(obj2.keys())))
        for key, value in obj1.items():
            self.assertEqual(value, obj2[key])

    def _assertEqualListsOfObjects(self, objs1, objs2, ignored_keys=None,
                                   msg=None):
        obj_to_dict = lambda o: self._dict_from_object(o, ignored_keys)
        objs1 = map(obj_to_dict, objs1)
        objs2 = list(map(obj_to_dict, objs2))
        # We don't care about the order of the lists, as long as they are in
        for obj1 in objs1:
            self.assertIn(obj1, objs2)
            objs2.remove(obj1)
        self.assertEqual([], objs2)

    def _assertEqualListsOfPrimitivesAsSets(self, primitives1, primitives2):
        self.assertEqual(len(primitives1), len(primitives2))
        for primitive in primitives1:
            self.assertIn(primitive, primitives2)

        for primitive in primitives2:
            self.assertIn(primitive, primitives1)


class RPCAPITestCase(TestCase, ModelsObjectComparatorMixin):
    def setUp(self):
        super(RPCAPITestCase, self).setUp()
        self.context = context.get_admin_context()
        self.rpcapi = None
        self.base_version = '2.0'

    def _test_rpc_api(self, method, rpc_method, server=None, fanout=False,
                      version=None, expected_method=None,
                      expected_kwargs_diff=None, retval=None,
                      expected_retval=None, **kwargs):
        """Runs a test against RPC API method.

        :param method: Name of RPC API method.
        :param rpc_method: Expected RPC message type (cast or call).
        :param server: Expected hostname.
        :param fanout: True if expected call/cast should be fanout.
        :param version: Expected autocalculated RPC API version.
        :param expected_method: Expected RPC method name.
        :param expected_kwargs_diff: Map of expected changes between keyword
                                     arguments passed into the method and sent
                                     over RPC.
        :param retval: Value returned by RPC call/cast.
        :param expected_retval: Expected RPC API response (if different than
                                retval).
        :param kwargs: Parameters passed into the RPC API method.
        """

        rpcapi = self.rpcapi()
        expected_kwargs_diff = expected_kwargs_diff or {}
        version = version or self.base_version
        topic = None
        if server is not None:
            backend = utils.extract_host(server)
            server = utils.extract_host(server, 'host')
            topic = 'cinder-volume.%s' % backend

        if expected_method is None:
            expected_method = method

        if expected_retval is None:
            expected_retval = retval

        target = {
            "server": server,
            "fanout": fanout,
            "version": version,
            "topic": topic,
        }

        # Initially we expect that we'll pass same arguments to RPC API method
        # and RPC call/cast...
        expected_msg = copy.deepcopy(kwargs)
        # ... but here we're taking exceptions into account.
        expected_msg.update(expected_kwargs_diff)

        def _fake_prepare_method(*args, **kwds):
            # This is checking if target will be properly created.
            for kwd in kwds:
                self.assertEqual(target[kwd], kwds[kwd])
            return rpcapi.client

        def _fake_rpc_method(*args, **kwargs):
            # This checks if positional arguments passed to RPC method match.
            self.assertEqual((self.context, expected_method), args)

            # This checks if keyword arguments passed to RPC method match.
            for kwarg, value in kwargs.items():
                # Getting possible changes into account.
                if isinstance(value, objects_base.CinderObject):
                    # We need to compare objects differently.
                    self._assertEqualObjects(expected_msg[kwarg], value)
                else:
                    self.assertEqual(expected_msg[kwarg], value)

            # Returning fake value we're supposed to return.
            if retval:
                return retval

        # Enable mocks that will check everything and run RPC method.
        with mock.patch.object(rpcapi.client, "prepare",
                               side_effect=_fake_prepare_method):
            with mock.patch.object(rpcapi.client, rpc_method,
                                   side_effect=_fake_rpc_method):
                real_retval = getattr(rpcapi, method)(self.context, **kwargs)
                self.assertEqual(expected_retval, real_retval)
