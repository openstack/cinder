
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

"""
Unit Tests for remote procedure calls using queue
"""


import mock
import mox
from oslo.config import cfg

from cinder import context
from cinder import db
from cinder import exception
from cinder import manager
from cinder import service
from cinder import test
from cinder import wsgi


test_service_opts = [
    cfg.StrOpt("fake_manager",
               default="cinder.tests.test_service.FakeManager",
               help="Manager for testing"),
    cfg.StrOpt("test_service_listen",
               default=None,
               help="Host to bind test service to"),
    cfg.IntOpt("test_service_listen_port",
               default=0,
               help="Port number to bind test service to"), ]

CONF = cfg.CONF
CONF.register_opts(test_service_opts)


class FakeManager(manager.Manager):
    """Fake manager for tests."""
    def __init__(self, host=None,
                 db_driver=None, service_name=None):
        super(FakeManager, self).__init__(host=host,
                                          db_driver=db_driver)

    def test_method(self):
        return 'manager'


class ExtendedService(service.Service):
    def test_method(self):
        return 'service'


class ServiceManagerTestCase(test.TestCase):
    """Test cases for Services."""

    def test_message_gets_to_manager(self):
        serv = service.Service('test',
                               'test',
                               'test',
                               'cinder.tests.test_service.FakeManager')
        serv.start()
        self.assertEqual(serv.test_method(), 'manager')

    def test_override_manager_method(self):
        serv = ExtendedService('test',
                               'test',
                               'test',
                               'cinder.tests.test_service.FakeManager')
        serv.start()
        self.assertEqual(serv.test_method(), 'service')


class ServiceFlagsTestCase(test.TestCase):
    def test_service_enabled_on_create_based_on_flag(self):
        self.flags(enable_new_services=True)
        host = 'foo'
        binary = 'cinder-fake'
        app = service.Service.create(host=host, binary=binary)
        app.start()
        app.stop()
        ref = db.service_get(context.get_admin_context(), app.service_id)
        db.service_destroy(context.get_admin_context(), app.service_id)
        self.assertFalse(ref['disabled'])

    def test_service_disabled_on_create_based_on_flag(self):
        self.flags(enable_new_services=False)
        host = 'foo'
        binary = 'cinder-fake'
        app = service.Service.create(host=host, binary=binary)
        app.start()
        app.stop()
        ref = db.service_get(context.get_admin_context(), app.service_id)
        db.service_destroy(context.get_admin_context(), app.service_id)
        self.assertTrue(ref['disabled'])


class ServiceTestCase(test.TestCase):
    """Test cases for Services."""

    def setUp(self):
        super(ServiceTestCase, self).setUp()
        self.mox.StubOutWithMock(service, 'db')

    def test_create(self):
        host = 'foo'
        binary = 'cinder-fake'
        topic = 'fake'

        # NOTE(vish): Create was moved out of mox replay to make sure that
        #             the looping calls are created in StartService.
        app = service.Service.create(host=host, binary=binary, topic=topic)

        self.assertTrue(app)

    def test_report_state_newly_disconnected(self):
        host = 'foo'
        binary = 'bar'
        topic = 'test'
        service_create = {'host': host,
                          'binary': binary,
                          'topic': topic,
                          'report_count': 0,
                          'availability_zone': 'nova'}
        service_ref = {'host': host,
                       'binary': binary,
                       'topic': topic,
                       'report_count': 0,
                       'availability_zone': 'nova',
                       'id': 1}

        service.db.service_get_by_args(mox.IgnoreArg(),
                                       host,
                                       binary).AndRaise(exception.NotFound())
        service.db.service_create(mox.IgnoreArg(),
                                  service_create).AndReturn(service_ref)
        service.db.service_get(mox.IgnoreArg(),
                               mox.IgnoreArg()).AndRaise(Exception())

        self.mox.ReplayAll()
        serv = service.Service(host,
                               binary,
                               topic,
                               'cinder.tests.test_service.FakeManager')
        serv.start()
        serv.report_state()
        self.assertTrue(serv.model_disconnected)

    def test_report_state_newly_connected(self):
        host = 'foo'
        binary = 'bar'
        topic = 'test'
        service_create = {'host': host,
                          'binary': binary,
                          'topic': topic,
                          'report_count': 0,
                          'availability_zone': 'nova'}
        service_ref = {'host': host,
                       'binary': binary,
                       'topic': topic,
                       'report_count': 0,
                       'availability_zone': 'nova',
                       'id': 1}

        service.db.service_get_by_args(mox.IgnoreArg(),
                                       host,
                                       binary).AndRaise(exception.NotFound())
        service.db.service_create(mox.IgnoreArg(),
                                  service_create).AndReturn(service_ref)
        service.db.service_get(mox.IgnoreArg(),
                               service_ref['id']).AndReturn(service_ref)
        service.db.service_update(mox.IgnoreArg(), service_ref['id'],
                                  mox.ContainsKeyValue('report_count', 1))

        self.mox.ReplayAll()
        serv = service.Service(host,
                               binary,
                               topic,
                               'cinder.tests.test_service.FakeManager')
        serv.start()
        serv.model_disconnected = True
        serv.report_state()

        self.assertFalse(serv.model_disconnected)

    def test_service_with_long_report_interval(self):
        CONF.set_override('service_down_time', 10)
        CONF.set_override('report_interval', 10)
        service.Service.create(binary="test_service",
                               manager="cinder.tests.test_service.FakeManager")
        self.assertEqual(CONF.service_down_time, 25)


class TestWSGIService(test.TestCase):

    def setUp(self):
        super(TestWSGIService, self).setUp()
        self.stubs.Set(wsgi.Loader, "load_app", mox.MockAnything())

    def test_service_random_port(self):
        test_service = service.WSGIService("test_service")
        self.assertEqual(0, test_service.port)
        test_service.start()
        self.assertNotEqual(0, test_service.port)
        test_service.stop()


class OSCompatibilityTestCase(test.TestCase):
    def _test_service_launcher(self, fake_os):
        # Note(lpetrut): The cinder-volume service needs to be spawned
        # differently on Windows due to an eventlet bug. For this reason,
        # we must check the process launcher used.
        fake_process_launcher = mock.MagicMock()
        with mock.patch('os.name', fake_os):
            with mock.patch('cinder.service.process_launcher',
                            fake_process_launcher):
                launcher = service.get_launcher()
                if fake_os == 'nt':
                    self.assertEqual(type(launcher),
                                     service.Launcher)
                else:
                    self.assertEqual(launcher,
                                     fake_process_launcher())

    def test_process_launcher_on_windows(self):
        self._test_service_launcher('nt')

    def test_process_launcher_on_linux(self):
        self._test_service_launcher('posix')
