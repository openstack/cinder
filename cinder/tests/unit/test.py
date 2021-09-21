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
from unittest import mock
import uuid

from eventlet import tpool
import fixtures
from keystonemiddleware import auth_token
from oslo_concurrency import lockutils
from oslo_config import cfg
from oslo_config import fixture as config_fixture
from oslo_log.fixture import logging_error as log_fixture
import oslo_messaging
from oslo_messaging import conffixture as messaging_conffixture
from oslo_serialization import jsonutils
from oslo_utils import strutils
from oslo_utils import timeutils
import testtools

from cinder.api import common as api_common
from cinder.common import config
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
from cinder.volume import configuration
from cinder.volume import driver as vol_driver
from cinder.volume import volume_types
from cinder.volume import volume_utils

CONF = config.CONF

_DB_CACHE = None
DB_SCHEMA = None
SESSION_CONFIGURED = False


class TestingException(Exception):
    pass


class Database(fixtures.Fixture):

    def __init__(self):
        super().__init__()

        # NOTE(lhx_): oslo_db.enginefacade is configured in tests the same
        # way as it's done for any other services that uses the db
        global SESSION_CONFIGURED
        if not SESSION_CONFIGURED:
            sqla_api.configure(CONF)
            SESSION_CONFIGURED = True

        # Suppress logging for test runs
        migrate_logger = logging.getLogger('migrate')
        migrate_logger.setLevel(logging.WARNING)

    def setUp(self):
        super().setUp()
        engine = sqla_api.get_engine()
        engine.dispose()
        self._cache_schema()
        conn = engine.connect()
        conn.connection.executescript(DB_SCHEMA)
        self.addCleanup(self.cleanup)

    def _cache_schema(self):
        global DB_SCHEMA
        if not DB_SCHEMA:
            engine = sqla_api.get_engine()
            conn = engine.connect()
            migration.db_sync()
            DB_SCHEMA = "".join(line for line in conn.connection.iterdump())
            engine.dispose()

    def cleanup(self):
        engine = sqla_api.get_engine()
        engine.dispose()


class TestCase(testtools.TestCase):
    """Test case base class for all unit tests."""

    SOURCE_TREE_ROOT = os.path.abspath(
        os.path.join(
            os.path.dirname(__file__),
            '../../../'))
    POLICY_PATH = os.path.join(SOURCE_TREE_ROOT,
                               'cinder/tests/unit/policy.yaml')
    RESOURCE_FILTER_FILENAME = 'etc/cinder/resource_filters.json'
    RESOURCE_FILTER_PATH = os.path.join(SOURCE_TREE_ROOT,
                                        RESOURCE_FILTER_FILENAME)
    MOCK_WORKER = True
    MOCK_TOOZ = True
    FAKE_OVO_HISTORY_VERSION = '9999.999'

    def __init__(self, *args, **kwargs):

        super(TestCase, self).__init__(*args, **kwargs)

        # Suppress some log messages during test runs
        castellan_logger = logging.getLogger('castellan')
        castellan_logger.setLevel(logging.ERROR)
        stevedore_logger = logging.getLogger('stevedore')
        stevedore_logger.setLevel(logging.ERROR)

    def _get_joined_notifier(self, *args, **kwargs):
        # We create a new fake notifier but we join the notifications with
        # the default notifier
        notifier = fake_notifier.get_fake_notifier(*args, **kwargs)
        notifier.notifications = self.notifier.notifications
        return notifier

    def _reset_filter_file(self):
        self.override_config('resource_query_filters_file',
                             self.RESOURCE_FILTER_PATH)
        api_common._FILTERS_COLLECTION = None

    def setUp(self):
        """Run before each test method to initialize test environment."""
        super(TestCase, self).setUp()

        # Create default notifier
        self.notifier = fake_notifier.get_fake_notifier()

        # Mock rpc get notifier with fake notifier method that joins all
        # notifications with the default notifier
        self.patch('cinder.rpc.get_notifier',
                   side_effect=self._get_joined_notifier)

        # Protect against any case where someone doesn't directly patch a retry
        # decorated call.
        self.patch('tenacity.nap.sleep')

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
        self.messaging_conf.transport_url = 'fake:/'
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

        # Init AuthProtocol to register some base options first, such as
        # auth_url.
        auth_token.AuthProtocol('fake_app', {'auth_type': 'password',
                                             'auth_url': 'fake_url'})

        conf_fixture.set_defaults(CONF)
        CONF([], default_config_files=[])

        # NOTE(vish): We need a better method for creating fixtures for tests
        #             now that we have some required db setup for the system
        #             to work properly.
        self.start = timeutils.utcnow()

        CONF.set_default('connection', 'sqlite://', 'database')
        CONF.set_default('sqlite_synchronous', False, 'database')

        self.useFixture(Database())

        # NOTE(blk-u): WarningsFixture must be after the Database fixture
        # because sqlalchemy-migrate messes with the warnings filters.
        self.useFixture(cinder_fixtures.WarningsFixture())

        # NOTE(danms): Make sure to reset us back to non-remote objects
        # for each test to avoid interactions. Also, backup the object
        # registry.
        objects_base.CinderObject.indirection_api = None
        self._base_test_obj_backup = copy.copy(
            objects_base.CinderObjectRegistry._registry._obj_classes)
        self.addCleanup(self._restore_obj_registry)

        self.addCleanup(CONF.reset)
        self.addCleanup(self._common_cleanup)
        self._services = []

        fake_notifier.mock_notifier(self)

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
                                     os.path.dirname(__file__)
                                 ),
                                 self.POLICY_PATH),
                             group='oslo_policy')
        self.override_config('resource_query_filters_file',
                             self.RESOURCE_FILTER_PATH)
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

        # TODO(smcginnis) Python 3 deprecates assertRaisesRegexp to
        # assertRaisesRegex, but Python 2 does not have the new name. This
        # can be removed once we stop supporting py2 or the new name is
        # added.
        self.assertRaisesRegexp = self.assertRaisesRegex

        # Ensure we have the default tpool size value and we don't carry
        # threads from other test runs.
        tpool.killall()
        tpool._nthreads = 20

        # NOTE(mikal): make sure we don't load a privsep helper accidentally
        self.useFixture(cinder_fixtures.PrivsepNoHelperFixture())

        # NOTE: This volume type is created to avoid failure at database since
        # volume_type_id is non-nullable for volumes and snapshots

        self.vt = volume_types.get_default_volume_type()

        # Create fake RPC history if we don't have enough to do tests
        obj_versions = objects_base.OBJ_VERSIONS
        if len(obj_versions) == 1:
            vol_vers = obj_versions.get_current_versions()['Volume'].split('.')
            new_volume_version = '%s.%s' % (vol_vers[0], int(vol_vers[1]) + 1)
            obj_versions.add(self.FAKE_OVO_HISTORY_VERSION,
                             {'Volume': new_volume_version})

        self.latest_ovo_version = obj_versions.get_current()

    def _restore_obj_registry(self):
        objects_base.CinderObjectRegistry._registry._obj_classes = \
            self._base_test_obj_backup

    def _disable_osprofiler(self):
        """Disable osprofiler.

        osprofiler should not run for unit tests.
        """

        def side_effect(value):
            return value
        mock_decorator = mock.MagicMock(side_effect=side_effect)
        p = mock.patch("osprofiler.profiler.trace_cls",
                       return_value=mock_decorator)
        p.start()

    def _common_cleanup(self):
        """Runs after each test method to tear down test environment."""

        # Kill any services
        for x in self._services:
            try:
                x.kill()
            except Exception:
                pass

        # Delete attributes that don't start with _ so they don't pin
        # memory around unnecessarily for the duration of the test
        # suite
        for key in [k for k in self.__dict__ if k[0] != '_']:
            del self.__dict__[key]

    def override_config(self, name, override, group=None):
        """Cleanly override CONF variables."""
        CONF.set_override(name, override, group)
        self.addCleanup(CONF.clear_override, name, group)

    def flags(self, **kw):
        """Override CONF variables for a test."""
        group = kw.pop('group', None)
        for k, v in kw.items():
            self.override_config(k, v, group)

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
    def assert_notify_called(self, mock_notify, calls, any_order=False):
        if any_order is True:
            for c in calls:
                # mock_notify.call_args_list = [
                #     mock.call('INFO', 'volume.retype', ...),
                #     mock.call('WARN', 'cinder.fire', ...)]
                # m = mock_notify.call_args_list
                # m[0] = Call
                # m[0][0] = tuple('INFO', <context>, 'volume.retype', ...)
                if not any(m for m in mock_notify.call_args_list
                           if (m[0][0] == c[0]     # 'INFO'
                               and
                               m[0][2] == c[1])):  # 'volume.retype'
                    raise AssertionError("notify call not found: %s" % c)
            return

        for i in range(0, len(calls)):
            mock_call = mock_notify.call_args_list[i]
            call = calls[i]

            posargs = mock_call[0]

            self.assertEqual(call[0], posargs[0])
            self.assertEqual(call[1], posargs[2])

    def assertTrue(self, x, *args, **kwargs):
        """Assert that value is True.

        If original behavior is required we will need to do:
            assertTrue(bool(result))
        """
        # assertTrue uses msg but assertIs uses message keyword argument
        args = list(args)
        msg = kwargs.pop('msg', args.pop(0) if args else '')
        kwargs.setdefault('message', msg)
        self.assertIs(True, x, *args, **kwargs)

    def assertFalse(self, x, *args, **kwargs):
        """Assert that value is False.

        If original behavior is required we will need to do:
            assertFalse(bool(result))
        """
        # assertTrue uses msg but assertIs uses message keyword argument
        args = list(args)
        msg = kwargs.pop('msg', args.pop(0) if args else '')
        kwargs.setdefault('message', msg)
        self.assertIs(False, x, *args, **kwargs)

    def stub_out(self, old, new):
        """Replace a function for the duration of the test.

        Use the monkey patch fixture to replace a function for the
        duration of a test. Useful when you want to provide fake
        methods instead of mocks during testing.
        This should be used instead of self.stubs.Set (which is based
        on mox) going forward.
        """
        self.useFixture(fixtures.MonkeyPatch(old, new))

    def _set_unique_fqdn_override(self, value, in_shared):
        """Override the unique_fqdn_network configuration option.

        Meant for driver tests that use a Mock for their driver configuration
        instead of a real Oslo Conf.
        """
        # Since we don't use a real oslo config for the driver we don't get
        # the default initialization, so create a group and register the option
        cfg.CONF.register_group(cfg.OptGroup('driver_cfg'))
        new_config = configuration.Configuration([], config_group='driver_cfg')
        new_config.append_config_values(vol_driver.fqdn_opts)

        # Now we override the value for this test
        group = configuration.SHARED_CONF_GROUP if in_shared else 'driver_cfg'
        self.addCleanup(CONF.clear_override, 'unique_fqdn_network',
                        group=group)
        cfg.CONF.set_override('unique_fqdn_network', value, group=group)
        return new_config


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
            "Keys mismatch: %s" % str(
                set(obj1.keys()) ^ set(obj2.keys())))
        for key, value in obj1.items():
            self.assertEqual(value, obj2[key])

    def _assertEqualListsOfObjects(self, objs1, objs2, ignored_keys=None,
                                   msg=None):
        def obj_to_dict(o):
            return self._dict_from_object(o, ignored_keys)

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
            backend = volume_utils.extract_host(server)
            server = volume_utils.extract_host(server, 'host')
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
