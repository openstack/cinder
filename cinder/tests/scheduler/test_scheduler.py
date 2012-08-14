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
"""
Tests For Scheduler
"""


from cinder import context
from cinder import db
from cinder import flags
from cinder.openstack.common import rpc
from cinder.openstack.common import timeutils
from cinder.scheduler import driver
from cinder.scheduler import manager
from cinder import test
from cinder import utils

FLAGS = flags.FLAGS


class SchedulerManagerTestCase(test.TestCase):
    """Test case for scheduler manager"""

    manager_cls = manager.SchedulerManager
    driver_cls = driver.Scheduler
    driver_cls_name = 'cinder.scheduler.driver.Scheduler'

    class AnException(Exception):
        pass

    def setUp(self):
        super(SchedulerManagerTestCase, self).setUp()
        self.flags(scheduler_driver=self.driver_cls_name)
        self.manager = self.manager_cls()
        self.context = context.RequestContext('fake_user', 'fake_project')
        self.topic = 'fake_topic'
        self.fake_args = (1, 2, 3)
        self.fake_kwargs = {'cat': 'meow', 'dog': 'woof'}

    def test_1_correct_init(self):
        # Correct scheduler driver
        manager = self.manager
        self.assertTrue(isinstance(manager.driver, self.driver_cls))

    def test_get_host_list(self):
        expected = 'fake_hosts'

        self.mox.StubOutWithMock(self.manager.driver, 'get_host_list')
        self.manager.driver.get_host_list().AndReturn(expected)

        self.mox.ReplayAll()
        result = self.manager.get_host_list(self.context)
        self.assertEqual(result, expected)

    def test_get_service_capabilities(self):
        expected = 'fake_service_capabs'

        self.mox.StubOutWithMock(self.manager.driver,
                'get_service_capabilities')
        self.manager.driver.get_service_capabilities().AndReturn(
                expected)

        self.mox.ReplayAll()
        result = self.manager.get_service_capabilities(self.context)
        self.assertEqual(result, expected)

    def test_update_service_capabilities(self):
        service_name = 'fake_service'
        host = 'fake_host'

        self.mox.StubOutWithMock(self.manager.driver,
                'update_service_capabilities')

        # Test no capabilities passes empty dictionary
        self.manager.driver.update_service_capabilities(service_name,
                host, {})
        self.mox.ReplayAll()
        result = self.manager.update_service_capabilities(self.context,
                service_name=service_name, host=host)
        self.mox.VerifyAll()

        self.mox.ResetAll()
        # Test capabilities passes correctly
        capabilities = {'fake_capability': 'fake_value'}
        self.manager.driver.update_service_capabilities(
                service_name, host, capabilities)
        self.mox.ReplayAll()
        result = self.manager.update_service_capabilities(self.context,
                service_name=service_name, host=host,
                capabilities=capabilities)

    def test_existing_method(self):
        def stub_method(self, *args, **kwargs):
            pass
        setattr(self.manager.driver, 'schedule_stub_method', stub_method)

        self.mox.StubOutWithMock(self.manager.driver,
                'schedule_stub_method')
        self.manager.driver.schedule_stub_method(self.context,
                *self.fake_args, **self.fake_kwargs)

        self.mox.ReplayAll()
        self.manager.stub_method(self.context, self.topic,
                *self.fake_args, **self.fake_kwargs)

    def test_missing_method_fallback(self):
        self.mox.StubOutWithMock(self.manager.driver, 'schedule')
        self.manager.driver.schedule(self.context, self.topic,
                'noexist', *self.fake_args, **self.fake_kwargs)

        self.mox.ReplayAll()
        self.manager.noexist(self.context, self.topic,
                *self.fake_args, **self.fake_kwargs)

    def _mox_schedule_method_helper(self, method_name):
        # Make sure the method exists that we're going to test call
        def stub_method(*args, **kwargs):
            pass

        setattr(self.manager.driver, method_name, stub_method)

        self.mox.StubOutWithMock(self.manager.driver,
                method_name)


class SchedulerTestCase(test.TestCase):
    """Test case for base scheduler driver class"""

    # So we can subclass this test and re-use tests if we need.
    driver_cls = driver.Scheduler

    def setUp(self):
        super(SchedulerTestCase, self).setUp()
        self.driver = self.driver_cls()
        self.context = context.RequestContext('fake_user', 'fake_project')
        self.topic = 'fake_topic'

    def test_get_host_list(self):
        expected = 'fake_hosts'

        self.mox.StubOutWithMock(self.driver.host_manager, 'get_host_list')
        self.driver.host_manager.get_host_list().AndReturn(expected)

        self.mox.ReplayAll()
        result = self.driver.get_host_list()
        self.assertEqual(result, expected)

    def test_get_service_capabilities(self):
        expected = 'fake_service_capabs'

        self.mox.StubOutWithMock(self.driver.host_manager,
                'get_service_capabilities')
        self.driver.host_manager.get_service_capabilities().AndReturn(
                expected)

        self.mox.ReplayAll()
        result = self.driver.get_service_capabilities()
        self.assertEqual(result, expected)

    def test_update_service_capabilities(self):
        service_name = 'fake_service'
        host = 'fake_host'

        self.mox.StubOutWithMock(self.driver.host_manager,
                'update_service_capabilities')

        capabilities = {'fake_capability': 'fake_value'}
        self.driver.host_manager.update_service_capabilities(
                service_name, host, capabilities)
        self.mox.ReplayAll()
        result = self.driver.update_service_capabilities(service_name,
                host, capabilities)

    def test_hosts_up(self):
        service1 = {'host': 'host1'}
        service2 = {'host': 'host2'}
        services = [service1, service2]

        self.mox.StubOutWithMock(db, 'service_get_all_by_topic')
        self.mox.StubOutWithMock(utils, 'service_is_up')

        db.service_get_all_by_topic(self.context,
                self.topic).AndReturn(services)
        utils.service_is_up(service1).AndReturn(False)
        utils.service_is_up(service2).AndReturn(True)

        self.mox.ReplayAll()
        result = self.driver.hosts_up(self.context, self.topic)
        self.assertEqual(result, ['host2'])


class SchedulerDriverBaseTestCase(SchedulerTestCase):
    """Test cases for base scheduler driver class methods
       that can't will fail if the driver is changed"""

    def test_unimplemented_schedule(self):
        fake_args = (1, 2, 3)
        fake_kwargs = {'cat': 'meow'}

        self.assertRaises(NotImplementedError, self.driver.schedule,
                         self.context, self.topic, 'schedule_something',
                         *fake_args, **fake_kwargs)


class SchedulerDriverModuleTestCase(test.TestCase):
    """Test case for scheduler driver module methods"""

    def setUp(self):
        super(SchedulerDriverModuleTestCase, self).setUp()
        self.context = context.RequestContext('fake_user', 'fake_project')

    def test_cast_to_volume_host_update_db_with_volume_id(self):
        host = 'fake_host1'
        method = 'fake_method'
        fake_kwargs = {'volume_id': 31337,
                       'extra_arg': 'meow'}
        queue = 'fake_queue'

        self.mox.StubOutWithMock(timeutils, 'utcnow')
        self.mox.StubOutWithMock(db, 'volume_update')
        self.mox.StubOutWithMock(rpc, 'queue_get_for')
        self.mox.StubOutWithMock(rpc, 'cast')

        timeutils.utcnow().AndReturn('fake-now')
        db.volume_update(self.context, 31337,
                {'host': host, 'scheduled_at': 'fake-now'})
        rpc.queue_get_for(self.context,
                         FLAGS.volume_topic, host).AndReturn(queue)
        rpc.cast(self.context, queue,
                {'method': method,
                 'args': fake_kwargs})

        self.mox.ReplayAll()
        driver.cast_to_volume_host(self.context, host, method,
                update_db=True, **fake_kwargs)

    def test_cast_to_volume_host_update_db_without_volume_id(self):
        host = 'fake_host1'
        method = 'fake_method'
        fake_kwargs = {'extra_arg': 'meow'}
        queue = 'fake_queue'

        self.mox.StubOutWithMock(rpc, 'queue_get_for')
        self.mox.StubOutWithMock(rpc, 'cast')

        rpc.queue_get_for(self.context,
                         FLAGS.volume_topic, host).AndReturn(queue)
        rpc.cast(self.context, queue,
                {'method': method,
                 'args': fake_kwargs})

        self.mox.ReplayAll()
        driver.cast_to_volume_host(self.context, host, method,
                update_db=True, **fake_kwargs)

    def test_cast_to_volume_host_no_update_db(self):
        host = 'fake_host1'
        method = 'fake_method'
        fake_kwargs = {'extra_arg': 'meow'}
        queue = 'fake_queue'

        self.mox.StubOutWithMock(rpc, 'queue_get_for')
        self.mox.StubOutWithMock(rpc, 'cast')

        rpc.queue_get_for(self.context,
                         FLAGS.volume_topic, host).AndReturn(queue)
        rpc.cast(self.context, queue,
                {'method': method,
                 'args': fake_kwargs})

        self.mox.ReplayAll()
        driver.cast_to_volume_host(self.context, host, method,
                update_db=False, **fake_kwargs)

    def test_cast_to_host_volume_topic(self):
        host = 'fake_host1'
        method = 'fake_method'
        fake_kwargs = {'extra_arg': 'meow'}

        self.mox.StubOutWithMock(driver, 'cast_to_volume_host')
        driver.cast_to_volume_host(self.context, host, method,
                update_db=False, **fake_kwargs)

        self.mox.ReplayAll()
        driver.cast_to_host(self.context, 'volume', host, method,
                update_db=False, **fake_kwargs)

    def test_cast_to_host_unknown_topic(self):
        host = 'fake_host1'
        method = 'fake_method'
        fake_kwargs = {'extra_arg': 'meow'}
        topic = 'unknown'
        queue = 'fake_queue'

        self.mox.StubOutWithMock(rpc, 'queue_get_for')
        self.mox.StubOutWithMock(rpc, 'cast')

        rpc.queue_get_for(self.context, topic, host).AndReturn(queue)
        rpc.cast(self.context, queue,
                {'method': method,
                 'args': fake_kwargs})

        self.mox.ReplayAll()
        driver.cast_to_host(self.context, topic, host, method,
                update_db=False, **fake_kwargs)
