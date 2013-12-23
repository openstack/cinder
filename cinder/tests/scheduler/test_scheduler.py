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

import mock

from cinder import context
from cinder import exception
from cinder.scheduler import driver
from cinder.scheduler import manager
from cinder import test


class SchedulerManagerTestCase(test.TestCase):
    """Test case for scheduler manager."""

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
        self.assertIsInstance(manager.driver, self.driver_cls)

    @mock.patch('cinder.scheduler.driver.Scheduler.'
                'update_service_capabilities')
    def test_update_service_capabilities_empty_dict(self, _mock_update_cap):
        # Test no capabilities passes empty dictionary
        service = 'fake_service'
        host = 'fake_host'

        self.manager.update_service_capabilities(self.context,
                                                 service_name=service,
                                                 host=host)
        _mock_update_cap.assert_called_once_with(service, host, {})

    @mock.patch('cinder.scheduler.driver.Scheduler.'
                'update_service_capabilities')
    def test_update_service_capabilities_correct(self, _mock_update_cap):
        # Test capabilities passes correctly
        service = 'fake_service'
        host = 'fake_host'
        capabilities = {'fake_capability': 'fake_value'}

        self.manager.update_service_capabilities(self.context,
                                                 service_name=service,
                                                 host=host,
                                                 capabilities=capabilities)
        _mock_update_cap.assert_called_once_with(service, host, capabilities)

    @mock.patch('cinder.scheduler.driver.Scheduler.schedule_create_volume')
    @mock.patch('cinder.db.volume_update')
    def test_create_volume_exception_puts_volume_in_error_state(
            self, _mock_volume_update, _mock_sched_create):
        # Test NoValidHost exception behavior for create_volume.
        # Puts the volume in 'error' state and eats the exception.
        _mock_sched_create.side_effect = exception.NoValidHost(reason="")
        fake_volume_id = 1
        topic = 'fake_topic'
        request_spec = {'volume_id': fake_volume_id}

        self.manager.create_volume(self.context, topic, fake_volume_id,
                                   request_spec=request_spec,
                                   filter_properties={})
        _mock_volume_update.assert_called_once_with(self.context,
                                                    fake_volume_id,
                                                    {'status': 'error'})
        _mock_sched_create.assert_called_once_with(self.context, request_spec,
                                                   {})

    @mock.patch('cinder.scheduler.driver.Scheduler.host_passes_filters')
    @mock.patch('cinder.db.volume_update')
    def test_migrate_volume_exception_returns_volume_state(
            self, _mock_volume_update, _mock_host_passes):
        # Test NoValidHost exception behavior for migrate_volume_to_host.
        # Puts the volume in 'error_migrating' state and eats the exception.
        _mock_host_passes.side_effect = exception.NoValidHost(reason="")
        fake_volume_id = 1
        topic = 'fake_topic'
        request_spec = {'volume_id': fake_volume_id}

        self.manager.migrate_volume_to_host(self.context, topic,
                                            fake_volume_id, 'host', True,
                                            request_spec=request_spec,
                                            filter_properties={})
        _mock_volume_update.assert_called_once_with(self.context,
                                                    fake_volume_id,
                                                    {'migration_status': None})
        _mock_host_passes.assert_called_once_with(self.context, 'host',
                                                  request_spec, {})


class SchedulerTestCase(test.TestCase):
    """Test case for base scheduler driver class."""

    # So we can subclass this test and re-use tests if we need.
    driver_cls = driver.Scheduler

    def setUp(self):
        super(SchedulerTestCase, self).setUp()
        self.driver = self.driver_cls()
        self.context = context.RequestContext('fake_user', 'fake_project')
        self.topic = 'fake_topic'

    @mock.patch('cinder.scheduler.driver.Scheduler.'
                'update_service_capabilities')
    def test_update_service_capabilities(self, _mock_update_cap):
        service_name = 'fake_service'
        host = 'fake_host'
        capabilities = {'fake_capability': 'fake_value'}
        self.driver.update_service_capabilities(service_name, host,
                                                capabilities)
        _mock_update_cap.assert_called_once_with(service_name, host,
                                                 capabilities)

    @mock.patch('cinder.db.service_get_all_by_topic')
    @mock.patch('cinder.utils.service_is_up')
    def test_hosts_up(self, _mock_serv_is_up, _mock_serv_get_all_by_topic):
        service1 = {'host': 'host1', 'disabled': False}
        service2 = {'host': 'host2', 'disabled': False}
        services = [service1, service2]

        def fake_serv_is_up(service):
            return service['host'] is 'host2'

        _mock_serv_get_all_by_topic.return_value = services
        _mock_serv_is_up.side_effect = fake_serv_is_up
        result = self.driver.hosts_up(self.context, self.topic)
        self.assertEqual(result, ['host2'])
        _mock_serv_get_all_by_topic.assert_called_once_with(self.context,
                                                            self.topic)


class SchedulerDriverBaseTestCase(SchedulerTestCase):
    """Test cases for base scheduler driver class methods
       that can't will fail if the driver is changed.
    """

    def test_unimplemented_schedule(self):
        fake_args = (1, 2, 3)
        fake_kwargs = {'cat': 'meow'}

        self.assertRaises(NotImplementedError, self.driver.schedule,
                          self.context, self.topic, 'schedule_something',
                          *fake_args, **fake_kwargs)


class SchedulerDriverModuleTestCase(test.TestCase):
    """Test case for scheduler driver module methods."""

    def setUp(self):
        super(SchedulerDriverModuleTestCase, self).setUp()
        self.context = context.RequestContext('fake_user', 'fake_project')

    @mock.patch('cinder.db.volume_update')
    @mock.patch('cinder.openstack.common.timeutils.utcnow')
    def test_volume_host_update_db(self, _mock_utcnow, _mock_vol_update):
        _mock_utcnow.return_value = 'fake-now'
        driver.volume_update_db(self.context, 31337, 'fake_host')
        _mock_vol_update.assert_called_once_with(self.context, 31337,
                                                 {'host': 'fake_host',
                                                  'scheduled_at': 'fake-now'})
