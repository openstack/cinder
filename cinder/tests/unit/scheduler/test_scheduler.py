
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
from oslo_config import cfg
from oslo_log import log as logging

from cinder import context
from cinder import db
from cinder import exception
from cinder.i18n import _
from cinder.scheduler import driver
from cinder.scheduler import filter_scheduler
from cinder.scheduler import manager
from cinder import test


CONF = cfg.CONF


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
        self.manager._startup_delay = False
        self.context = context.RequestContext('fake_user', 'fake_project')
        self.topic = 'fake_topic'
        self.fake_args = (1, 2, 3)
        self.fake_kwargs = {'cat': 'meow', 'dog': 'woof'}

    def test_1_correct_init(self):
        # Correct scheduler driver
        manager = self.manager
        self.assertIsInstance(manager.driver, self.driver_cls)

    @mock.patch('eventlet.sleep')
    @mock.patch('cinder.volume.rpcapi.VolumeAPI.publish_service_capabilities')
    def test_init_host_with_rpc(self, publish_capabilities_mock, sleep_mock):
        self.manager._startup_delay = True
        self.manager.init_host_with_rpc()
        publish_capabilities_mock.assert_called_once_with(mock.ANY)
        sleep_mock.assert_called_once_with(CONF.periodic_interval)
        self.assertFalse(self.manager._startup_delay)

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

    @mock.patch('cinder.scheduler.driver.Scheduler.schedule_create_volume')
    @mock.patch('eventlet.sleep')
    def test_create_volume_no_delay(self, _mock_sleep, _mock_sched_create):
        fake_volume_id = 1
        topic = 'fake_topic'

        request_spec = {'volume_id': fake_volume_id}

        self.manager.create_volume(self.context, topic, fake_volume_id,
                                   request_spec=request_spec,
                                   filter_properties={})
        _mock_sched_create.assert_called_once_with(self.context, request_spec,
                                                   {})
        self.assertFalse(_mock_sleep.called)

    @mock.patch('cinder.scheduler.driver.Scheduler.schedule_create_volume')
    @mock.patch('cinder.scheduler.driver.Scheduler.is_ready')
    @mock.patch('eventlet.sleep')
    def test_create_volume_delay_scheduled_after_3_tries(self, _mock_sleep,
                                                         _mock_is_ready,
                                                         _mock_sched_create):
        self.manager._startup_delay = True
        fake_volume_id = 1
        topic = 'fake_topic'

        request_spec = {'volume_id': fake_volume_id}

        _mock_is_ready.side_effect = [False, False, True]

        self.manager.create_volume(self.context, topic, fake_volume_id,
                                   request_spec=request_spec,
                                   filter_properties={})
        _mock_sched_create.assert_called_once_with(self.context, request_spec,
                                                   {})
        calls = [mock.call(1)] * 2
        _mock_sleep.assert_has_calls(calls)
        self.assertEqual(2, _mock_sleep.call_count)

    @mock.patch('cinder.scheduler.driver.Scheduler.schedule_create_volume')
    @mock.patch('cinder.scheduler.driver.Scheduler.is_ready')
    @mock.patch('eventlet.sleep')
    def test_create_volume_delay_scheduled_in_1_try(self, _mock_sleep,
                                                    _mock_is_ready,
                                                    _mock_sched_create):
        self.manager._startup_delay = True
        fake_volume_id = 1
        topic = 'fake_topic'

        request_spec = {'volume_id': fake_volume_id}

        _mock_is_ready.return_value = True

        self.manager.create_volume(self.context, topic, fake_volume_id,
                                   request_spec=request_spec,
                                   filter_properties={})
        _mock_sched_create.assert_called_once_with(self.context, request_spec,
                                                   {})
        self.assertFalse(_mock_sleep.called)

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

    def test_chance_simple_scheduler_mocked(self):
        # Test FilterScheduler is loaded and predefined combination
        # of filters and weighers overrides the default value of config option
        # scheduler_default_filters and scheduler_default_weighers when
        # ChanceScheduler or SimpleScheduler is configured as scheduler_driver.
        chance = 'cinder.scheduler.chance.ChanceScheduler'
        simple = 'cinder.scheduler.simple.SimpleScheduler'
        default_filters = ['AvailabilityZoneFilter',
                           'CapacityFilter',
                           'CapabilitiesFilter']
        self.flags(scheduler_driver=chance,
                   scheduler_default_filters=['CapacityFilter'],
                   scheduler_default_weighers=['CapacityWeigher'])
        self.manager = self.manager_cls()
        self.assertTrue(isinstance(self.manager.driver,
                                   filter_scheduler.FilterScheduler))
        self.assertEqual(CONF.scheduler_default_filters,
                         default_filters)
        self.assertEqual(CONF.scheduler_default_weighers,
                         ['ChanceWeigher'])

        self.flags(scheduler_driver=simple,
                   scheduler_default_filters=['CapacityFilter'],
                   scheduler_default_weighers=['CapacityWeigher'])
        self.manager = self.manager_cls()
        self.assertTrue(isinstance(self.manager.driver,
                                   filter_scheduler.FilterScheduler))
        self.assertEqual(CONF.scheduler_default_filters,
                         default_filters)
        self.assertEqual(CONF.scheduler_default_weighers,
                         ['AllocatedCapacityWeigher'])

    @mock.patch('cinder.db.volume_update')
    @mock.patch('cinder.db.volume_get')
    def test_retype_volume_exception_returns_volume_state(self, _mock_vol_get,
                                                          _mock_vol_update):
        # Test NoValidHost exception behavior for retype.
        # Puts the volume in original state and eats the exception.
        fake_volume_id = 1
        topic = 'fake_topic'
        volume_id = fake_volume_id
        request_spec = {'volume_id': fake_volume_id, 'volume_type': {'id': 3},
                        'migration_policy': 'on-demand'}
        vol_info = {'id': fake_volume_id, 'status': 'in-use',
                    'volume_attachment': [{'id': 'fake_id',
                                           'instance_uuid': 'foo',
                                           'attached_host': None}]}

        _mock_vol_get.return_value = vol_info
        _mock_vol_update.return_value = {'status': 'in-use'}
        _mock_find_retype_host = mock.Mock(
            side_effect=exception.NoValidHost(reason=""))
        orig_retype = self.manager.driver.find_retype_host
        self.manager.driver.find_retype_host = _mock_find_retype_host

        self.manager.retype(self.context, topic, volume_id,
                            request_spec=request_spec,
                            filter_properties={})

        _mock_vol_get.assert_called_once_with(self.context, fake_volume_id)
        _mock_find_retype_host.assert_called_once_with(self.context,
                                                       request_spec, {},
                                                       'on-demand')
        _mock_vol_update.assert_called_once_with(self.context, fake_volume_id,
                                                 {'status': 'in-use'})
        self.manager.driver.find_retype_host = orig_retype

    def test_create_consistencygroup_exceptions(self):
        with mock.patch.object(filter_scheduler.FilterScheduler,
                               'schedule_create_consistencygroup') as mock_cg:
            original_driver = self.manager.driver
            self.manager.driver = filter_scheduler.FilterScheduler
            LOG = logging.getLogger('cinder.scheduler.manager')
            self.stubs.Set(LOG, 'error', mock.Mock())
            self.stubs.Set(LOG, 'exception', mock.Mock())
            self.stubs.Set(db, 'consistencygroup_update', mock.Mock())

            ex = exception.CinderException('test')
            mock_cg.side_effect = ex
            group_id = '1'
            self.assertRaises(exception.CinderException,
                              self.manager.create_consistencygroup,
                              self.context,
                              'volume',
                              group_id)
            LOG.exception.assert_called_once_with(_(
                "Failed to create consistency group "
                "%(group_id)s."), {'group_id': group_id})
            db.consistencygroup_update.assert_called_once_with(
                self.context, group_id, {'status': 'error'})

            mock_cg.reset_mock()
            LOG.exception.reset_mock()
            db.consistencygroup_update.reset_mock()

            mock_cg.side_effect = exception.NoValidHost(
                reason="No weighed hosts available")
            self.manager.create_consistencygroup(
                self.context, 'volume', group_id)
            LOG.error.assert_called_once_with(_(
                "Could not find a host for consistency group "
                "%(group_id)s.") % {'group_id': group_id})
            db.consistencygroup_update.assert_called_once_with(
                self.context, group_id, {'status': 'error'})

            self.manager.driver = original_driver


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

    @mock.patch('cinder.scheduler.host_manager.HostManager.'
                'has_all_capabilities', return_value=False)
    def test_is_ready(self, _mock_has_caps):
        ready = self.driver.is_ready()
        _mock_has_caps.assert_called_once_with()
        self.assertFalse(ready)


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
    @mock.patch('oslo_utils.timeutils.utcnow')
    def test_volume_host_update_db(self, _mock_utcnow, _mock_vol_update):
        _mock_utcnow.return_value = 'fake-now'
        driver.volume_update_db(self.context, 31337, 'fake_host')
        _mock_vol_update.assert_called_once_with(self.context, 31337,
                                                 {'host': 'fake_host',
                                                  'scheduled_at': 'fake-now'})
