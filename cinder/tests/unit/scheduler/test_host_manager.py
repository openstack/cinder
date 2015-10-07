# Copyright (c) 2011 OpenStack Foundation
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
Tests For HostManager
"""

from datetime import datetime

import mock
from oslo_config import cfg
from oslo_utils import timeutils

from cinder import exception
from cinder import objects
from cinder.openstack.common.scheduler import filters
from cinder.scheduler import host_manager
from cinder import test
from cinder.tests.unit.objects import test_service


CONF = cfg.CONF


class FakeFilterClass1(filters.BaseHostFilter):
    def host_passes(self, host_state, filter_properties):
        pass


class FakeFilterClass2(filters.BaseHostFilter):
    def host_passes(self, host_state, filter_properties):
        pass


class HostManagerTestCase(test.TestCase):
    """Test case for HostManager class."""

    def setUp(self):
        super(HostManagerTestCase, self).setUp()
        self.host_manager = host_manager.HostManager()
        self.fake_hosts = [host_manager.HostState('fake_host%s' % x)
                           for x in range(1, 5)]

    def test_choose_host_filters_not_found(self):
        self.flags(scheduler_default_filters='FakeFilterClass3')
        self.host_manager.filter_classes = [FakeFilterClass1,
                                            FakeFilterClass2]
        self.assertRaises(exception.SchedulerHostFilterNotFound,
                          self.host_manager._choose_host_filters, None)

    def test_choose_host_filters(self):
        self.flags(scheduler_default_filters=['FakeFilterClass2'])
        self.host_manager.filter_classes = [FakeFilterClass1,
                                            FakeFilterClass2]

        # Test 'volume' returns 1 correct function
        filter_classes = self.host_manager._choose_host_filters(None)
        self.assertEqual(1, len(filter_classes))
        self.assertEqual('FakeFilterClass2', filter_classes[0].__name__)

    @mock.patch('cinder.scheduler.host_manager.HostManager.'
                '_choose_host_filters')
    def test_get_filtered_hosts(self, _mock_choose_host_filters):
        filter_class = FakeFilterClass1
        mock_func = mock.Mock()
        mock_func.return_value = True
        filter_class._filter_one = mock_func
        _mock_choose_host_filters.return_value = [filter_class]

        fake_properties = {'moo': 1, 'cow': 2}
        expected = []
        for fake_host in self.fake_hosts:
            expected.append(mock.call(fake_host, fake_properties))

        result = self.host_manager.get_filtered_hosts(self.fake_hosts,
                                                      fake_properties)
        self.assertEqual(expected, mock_func.call_args_list)
        self.assertEqual(set(self.fake_hosts), set(result))

    @mock.patch('oslo_utils.timeutils.utcnow')
    def test_update_service_capabilities(self, _mock_utcnow):
        service_states = self.host_manager.service_states
        self.assertDictMatch(service_states, {})
        _mock_utcnow.side_effect = [31337, 31338, 31339]

        host1_volume_capabs = dict(free_capacity_gb=4321, timestamp=1)
        host2_volume_capabs = dict(free_capacity_gb=5432, timestamp=1)
        host3_volume_capabs = dict(free_capacity_gb=6543, timestamp=1)

        service_name = 'volume'
        self.host_manager.update_service_capabilities(service_name, 'host1',
                                                      host1_volume_capabs)
        self.host_manager.update_service_capabilities(service_name, 'host2',
                                                      host2_volume_capabs)
        self.host_manager.update_service_capabilities(service_name, 'host3',
                                                      host3_volume_capabs)

        # Make sure dictionary isn't re-assigned
        self.assertEqual(service_states, self.host_manager.service_states)
        # Make sure original dictionary wasn't copied
        self.assertEqual(1, host1_volume_capabs['timestamp'])

        host1_volume_capabs['timestamp'] = 31337
        host2_volume_capabs['timestamp'] = 31338
        host3_volume_capabs['timestamp'] = 31339

        expected = {'host1': host1_volume_capabs,
                    'host2': host2_volume_capabs,
                    'host3': host3_volume_capabs}
        self.assertDictMatch(expected, service_states)

    @mock.patch('cinder.utils.service_is_up')
    @mock.patch('cinder.db.service_get_all_by_topic')
    def test_has_all_capabilities(self, _mock_service_get_all_by_topic,
                                  _mock_service_is_up):
        _mock_service_is_up.return_value = True
        services = [
            dict(id=1, host='host1', topic='volume', disabled=False,
                 availability_zone='zone1', updated_at=timeutils.utcnow()),
            dict(id=2, host='host2', topic='volume', disabled=False,
                 availability_zone='zone1', updated_at=timeutils.utcnow()),
            dict(id=3, host='host3', topic='volume', disabled=False,
                 availability_zone='zone1', updated_at=timeutils.utcnow()),
        ]
        _mock_service_get_all_by_topic.return_value = services
        # Create host_manager again to let db.service_get_all_by_topic mock run
        self.host_manager = host_manager.HostManager()
        self.assertFalse(self.host_manager.has_all_capabilities())

        host1_volume_capabs = dict(free_capacity_gb=4321, timestamp=1)
        host2_volume_capabs = dict(free_capacity_gb=5432, timestamp=1)
        host3_volume_capabs = dict(free_capacity_gb=6543, timestamp=1)

        service_name = 'volume'
        self.host_manager.update_service_capabilities(service_name, 'host1',
                                                      host1_volume_capabs)
        self.assertFalse(self.host_manager.has_all_capabilities())
        self.host_manager.update_service_capabilities(service_name, 'host2',
                                                      host2_volume_capabs)
        self.assertFalse(self.host_manager.has_all_capabilities())
        self.host_manager.update_service_capabilities(service_name, 'host3',
                                                      host3_volume_capabs)
        self.assertTrue(self.host_manager.has_all_capabilities())

    @mock.patch('cinder.db.service_get_all_by_topic')
    @mock.patch('cinder.utils.service_is_up')
    @mock.patch('oslo_utils.timeutils.utcnow')
    def test_update_and_get_pools(self, _mock_utcnow,
                                  _mock_service_is_up,
                                  _mock_service_get_all_by_topic):
        """Test interaction between update and get_pools

        This test verifies that each time that get_pools is called it gets the
        latest copy of service_capabilities, which is timestamped with the
        current date/time.
        """
        context = 'fake_context'
        dates = [datetime.fromtimestamp(400), datetime.fromtimestamp(401),
                 datetime.fromtimestamp(402)]
        _mock_utcnow.side_effect = dates

        services = [
            # This is the first call to utcnow()
            dict(id=1, host='host1', topic='volume', disabled=False,
                 availability_zone='zone1', updated_at=timeutils.utcnow()),
        ]

        mocked_service_states = {
            'host1': dict(volume_backend_name='AAA',
                          total_capacity_gb=512, free_capacity_gb=200,
                          timestamp=None, reserved_percentage=0),
        }

        _mock_service_get_all_by_topic.return_value = services
        _mock_service_is_up.return_value = True
        _mock_warning = mock.Mock()
        host_manager.LOG.warn = _mock_warning

        host_volume_capabs = dict(free_capacity_gb=4321)

        service_name = 'volume'
        with mock.patch.dict(self.host_manager.service_states,
                             mocked_service_states):
            self.host_manager.update_service_capabilities(service_name,
                                                          'host1',
                                                          host_volume_capabs)
            res = self.host_manager.get_pools(context)
            self.assertEqual(1, len(res))
            self.assertEqual(dates[1], res[0]['capabilities']['timestamp'])

            self.host_manager.update_service_capabilities(service_name,
                                                          'host1',
                                                          host_volume_capabs)
            res = self.host_manager.get_pools(context)
            self.assertEqual(1, len(res))
            self.assertEqual(dates[2], res[0]['capabilities']['timestamp'])

    @mock.patch('cinder.db.service_get_all_by_topic')
    @mock.patch('cinder.utils.service_is_up')
    def test_get_all_host_states(self, _mock_service_is_up,
                                 _mock_service_get_all_by_topic):
        context = 'fake_context'
        topic = CONF.volume_topic

        services = [
            dict(id=1, host='host1', topic='volume', disabled=False,
                 availability_zone='zone1', updated_at=timeutils.utcnow(),
                 binary=None, deleted=False, created_at=None, modified_at=None,
                 report_count=0, deleted_at=None, disabled_reason=None),
            dict(id=2, host='host2', topic='volume', disabled=False,
                 availability_zone='zone1', updated_at=timeutils.utcnow(),
                 binary=None, deleted=False, created_at=None, modified_at=None,
                 report_count=0, deleted_at=None, disabled_reason=None),
            dict(id=3, host='host3', topic='volume', disabled=False,
                 availability_zone='zone2', updated_at=timeutils.utcnow(),
                 binary=None, deleted=False, created_at=None, modified_at=None,
                 report_count=0, deleted_at=None, disabled_reason=None),
            dict(id=4, host='host4', topic='volume', disabled=False,
                 availability_zone='zone3', updated_at=timeutils.utcnow(),
                 binary=None, deleted=False, created_at=None, modified_at=None,
                 report_count=0, deleted_at=None, disabled_reason=None),
        ]

        service_objs = []
        for db_service in services:
            service_obj = objects.Service()
            service_objs.append(objects.Service._from_db_object(context,
                                                                service_obj,
                                                                db_service))

        service_states = {
            'host1': dict(volume_backend_name='AAA',
                          total_capacity_gb=512, free_capacity_gb=200,
                          timestamp=None, reserved_percentage=0,
                          provisioned_capacity_gb=312),
            'host2': dict(volume_backend_name='BBB',
                          total_capacity_gb=256, free_capacity_gb=100,
                          timestamp=None, reserved_percentage=0,
                          provisioned_capacity_gb=156),
            'host3': dict(volume_backend_name='CCC',
                          total_capacity_gb=10000, free_capacity_gb=700,
                          timestamp=None, reserved_percentage=0,
                          provisioned_capacity_gb=9300),
        }

        # First test: service_is_up is always True, host5 is disabled,
        # host4 has no capabilities
        self.host_manager.service_states = service_states
        _mock_service_get_all_by_topic.return_value = services
        _mock_service_is_up.return_value = True
        _mock_warning = mock.Mock()
        host_manager.LOG.warning = _mock_warning

        # Get all states
        self.host_manager.get_all_host_states(context)
        _mock_service_get_all_by_topic.assert_called_with(context,
                                                          topic,
                                                          disabled=False)
        expected = []
        for service in service_objs:
            expected.append(mock.call(service))
        self.assertEqual(expected, _mock_service_is_up.call_args_list)

        # Get host_state_map and make sure we have the first 3 hosts
        host_state_map = self.host_manager.host_state_map
        self.assertEqual(3, len(host_state_map))
        for i in range(3):
            volume_node = services[i]
            host = volume_node['host']
            test_service.TestService._compare(self, volume_node,
                                              host_state_map[host].service)

        # Second test: Now service_is_up returns False for host3
        _mock_service_is_up.reset_mock()
        _mock_service_is_up.side_effect = [True, True, False, True]
        _mock_service_get_all_by_topic.reset_mock()
        _mock_warning.reset_mock()

        # Get all states, make sure host 3 is reported as down
        self.host_manager.get_all_host_states(context)
        _mock_service_get_all_by_topic.assert_called_with(context,
                                                          topic,
                                                          disabled=False)

        self.assertEqual(expected, _mock_service_is_up.call_args_list)
        self.assertTrue(_mock_warning.call_count > 0)

        # Get host_state_map and make sure we have the first 2 hosts (host3 is
        # down, host4 is missing capabilities)
        host_state_map = self.host_manager.host_state_map
        self.assertEqual(2, len(host_state_map))
        for i in range(2):
            volume_node = services[i]
            host = volume_node['host']
            test_service.TestService._compare(self, volume_node,
                                              host_state_map[host].service)

    @mock.patch('cinder.db.service_get_all_by_topic')
    @mock.patch('cinder.utils.service_is_up')
    def test_get_pools(self, _mock_service_is_up,
                       _mock_service_get_all_by_topic):
        context = 'fake_context'

        services = [
            dict(id=1, host='host1', topic='volume', disabled=False,
                 availability_zone='zone1', updated_at=timeutils.utcnow()),
            dict(id=2, host='host2@back1', topic='volume', disabled=False,
                 availability_zone='zone1', updated_at=timeutils.utcnow()),
            dict(id=3, host='host2@back2', topic='volume', disabled=False,
                 availability_zone='zone2', updated_at=timeutils.utcnow()),
        ]

        mocked_service_states = {
            'host1': dict(volume_backend_name='AAA',
                          total_capacity_gb=512, free_capacity_gb=200,
                          timestamp=None, reserved_percentage=0,
                          provisioned_capacity_gb=312),
            'host2@back1': dict(volume_backend_name='BBB',
                                total_capacity_gb=256, free_capacity_gb=100,
                                timestamp=None, reserved_percentage=0,
                                provisioned_capacity_gb=156),
            'host2@back2': dict(volume_backend_name='CCC',
                                total_capacity_gb=10000, free_capacity_gb=700,
                                timestamp=None, reserved_percentage=0,
                                provisioned_capacity_gb=9300),
        }

        _mock_service_get_all_by_topic.return_value = services
        _mock_service_is_up.return_value = True
        _mock_warning = mock.Mock()
        host_manager.LOG.warn = _mock_warning

        with mock.patch.dict(self.host_manager.service_states,
                             mocked_service_states):
            res = self.host_manager.get_pools(context)

            # check if get_pools returns all 3 pools
            self.assertEqual(3, len(res))

            expected = [
                {
                    'name': 'host1#AAA',
                    'capabilities': {
                        'timestamp': None,
                        'volume_backend_name': 'AAA',
                        'free_capacity_gb': 200,
                        'driver_version': None,
                        'total_capacity_gb': 512,
                        'reserved_percentage': 0,
                        'vendor_name': None,
                        'storage_protocol': None,
                        'provisioned_capacity_gb': 312},
                },
                {
                    'name': 'host2@back1#BBB',
                    'capabilities': {
                        'timestamp': None,
                        'volume_backend_name': 'BBB',
                        'free_capacity_gb': 100,
                        'driver_version': None,
                        'total_capacity_gb': 256,
                        'reserved_percentage': 0,
                        'vendor_name': None,
                        'storage_protocol': None,
                        'provisioned_capacity_gb': 156},
                },
                {
                    'name': 'host2@back2#CCC',
                    'capabilities': {
                        'timestamp': None,
                        'volume_backend_name': 'CCC',
                        'free_capacity_gb': 700,
                        'driver_version': None,
                        'total_capacity_gb': 10000,
                        'reserved_percentage': 0,
                        'vendor_name': None,
                        'storage_protocol': None,
                        'provisioned_capacity_gb': 9300},
                }
            ]

            def sort_func(data):
                return data['name']

            self.assertEqual(len(expected), len(res))
            self.assertEqual(sorted(expected, key=sort_func),
                             sorted(res, key=sort_func))


class HostStateTestCase(test.TestCase):
    """Test case for HostState class."""

    def test_update_from_volume_capability_nopool(self):
        fake_host = host_manager.HostState('host1')
        self.assertIsNone(fake_host.free_capacity_gb)

        volume_capability = {'total_capacity_gb': 1024,
                             'free_capacity_gb': 512,
                             'provisioned_capacity_gb': 512,
                             'reserved_percentage': 0,
                             'timestamp': None}

        fake_host.update_from_volume_capability(volume_capability)
        # Backend level stats remain uninitialized
        self.assertEqual(0, fake_host.total_capacity_gb)
        self.assertEqual(None, fake_host.free_capacity_gb)
        # Pool stats has been updated
        self.assertEqual(1024, fake_host.pools['_pool0'].total_capacity_gb)
        self.assertEqual(512, fake_host.pools['_pool0'].free_capacity_gb)
        self.assertEqual(512,
                         fake_host.pools['_pool0'].provisioned_capacity_gb)

        # Test update for existing host state
        volume_capability.update(dict(total_capacity_gb=1000))
        fake_host.update_from_volume_capability(volume_capability)
        self.assertEqual(1000, fake_host.pools['_pool0'].total_capacity_gb)

        # Test update for existing host state with different backend name
        volume_capability.update(dict(volume_backend_name='magic'))
        fake_host.update_from_volume_capability(volume_capability)
        self.assertEqual(1000, fake_host.pools['magic'].total_capacity_gb)
        self.assertEqual(512, fake_host.pools['magic'].free_capacity_gb)
        self.assertEqual(512,
                         fake_host.pools['magic'].provisioned_capacity_gb)
        # 'pool0' becomes nonactive pool, and is deleted
        self.assertRaises(KeyError, lambda: fake_host.pools['pool0'])

    def test_update_from_volume_capability_with_pools(self):
        fake_host = host_manager.HostState('host1')
        self.assertIsNone(fake_host.free_capacity_gb)
        capability = {
            'volume_backend_name': 'Local iSCSI',
            'vendor_name': 'OpenStack',
            'driver_version': '1.0.1',
            'storage_protocol': 'iSCSI',
            'pools': [
                {'pool_name': '1st pool',
                 'total_capacity_gb': 500,
                 'free_capacity_gb': 230,
                 'allocated_capacity_gb': 270,
                 'provisioned_capacity_gb': 270,
                 'QoS_support': 'False',
                 'reserved_percentage': 0,
                 'dying_disks': 100,
                 'super_hero_1': 'spider-man',
                 'super_hero_2': 'flash',
                 'super_hero_3': 'neoncat',
                 },
                {'pool_name': '2nd pool',
                 'total_capacity_gb': 1024,
                 'free_capacity_gb': 1024,
                 'allocated_capacity_gb': 0,
                 'provisioned_capacity_gb': 0,
                 'QoS_support': 'False',
                 'reserved_percentage': 0,
                 'dying_disks': 200,
                 'super_hero_1': 'superman',
                 'super_hero_2': 'Hulk',
                 }
            ],
            'timestamp': None,
        }

        fake_host.update_from_volume_capability(capability)

        self.assertEqual('Local iSCSI', fake_host.volume_backend_name)
        self.assertEqual('iSCSI', fake_host.storage_protocol)
        self.assertEqual('OpenStack', fake_host.vendor_name)
        self.assertEqual('1.0.1', fake_host.driver_version)

        # Backend level stats remain uninitialized
        self.assertEqual(0, fake_host.total_capacity_gb)
        self.assertEqual(None, fake_host.free_capacity_gb)
        # Pool stats has been updated
        self.assertEqual(2, len(fake_host.pools))

        self.assertEqual(500, fake_host.pools['1st pool'].total_capacity_gb)
        self.assertEqual(230, fake_host.pools['1st pool'].free_capacity_gb)
        self.assertEqual(270,
                         fake_host.pools['1st pool'].provisioned_capacity_gb)
        self.assertEqual(1024, fake_host.pools['2nd pool'].total_capacity_gb)
        self.assertEqual(1024, fake_host.pools['2nd pool'].free_capacity_gb)
        self.assertEqual(0,
                         fake_host.pools['2nd pool'].provisioned_capacity_gb)

        capability = {
            'volume_backend_name': 'Local iSCSI',
            'vendor_name': 'OpenStack',
            'driver_version': '1.0.2',
            'storage_protocol': 'iSCSI',
            'pools': [
                {'pool_name': '3rd pool',
                 'total_capacity_gb': 10000,
                 'free_capacity_gb': 10000,
                 'allocated_capacity_gb': 0,
                 'provisioned_capacity_gb': 0,
                 'QoS_support': 'False',
                 'reserved_percentage': 0,
                 },
            ],
            'timestamp': None,
        }

        # test update HostState Record
        fake_host.update_from_volume_capability(capability)

        self.assertEqual('1.0.2', fake_host.driver_version)

        # Non-active pool stats has been removed
        self.assertEqual(1, len(fake_host.pools))

        self.assertRaises(KeyError, lambda: fake_host.pools['1st pool'])
        self.assertRaises(KeyError, lambda: fake_host.pools['2nd pool'])

        self.assertEqual(10000, fake_host.pools['3rd pool'].total_capacity_gb)
        self.assertEqual(10000, fake_host.pools['3rd pool'].free_capacity_gb)
        self.assertEqual(0,
                         fake_host.pools['3rd pool'].provisioned_capacity_gb)

    def test_update_from_volume_infinite_capability(self):
        fake_host = host_manager.HostState('host1')
        self.assertIsNone(fake_host.free_capacity_gb)

        volume_capability = {'total_capacity_gb': 'infinite',
                             'free_capacity_gb': 'infinite',
                             'reserved_percentage': 0,
                             'timestamp': None}

        fake_host.update_from_volume_capability(volume_capability)
        # Backend level stats remain uninitialized
        self.assertEqual(0, fake_host.total_capacity_gb)
        self.assertEqual(None, fake_host.free_capacity_gb)
        # Pool stats has been updated
        self.assertEqual(
            'infinite',
            fake_host.pools['_pool0'].total_capacity_gb)
        self.assertEqual(
            'infinite',
            fake_host.pools['_pool0'].free_capacity_gb)

    def test_update_from_volume_unknown_capability(self):
        fake_host = host_manager.HostState('host1')
        self.assertIsNone(fake_host.free_capacity_gb)

        volume_capability = {'total_capacity_gb': 'infinite',
                             'free_capacity_gb': 'unknown',
                             'reserved_percentage': 0,
                             'timestamp': None}

        fake_host.update_from_volume_capability(volume_capability)
        # Backend level stats remain uninitialized
        self.assertEqual(0, fake_host.total_capacity_gb)
        self.assertEqual(None, fake_host.free_capacity_gb)
        # Pool stats has been updated
        self.assertEqual(
            'infinite',
            fake_host.pools['_pool0'].total_capacity_gb)
        self.assertEqual(
            'unknown',
            fake_host.pools['_pool0'].free_capacity_gb)

    def test_update_from_empty_volume_capability(self):
        fake_host = host_manager.HostState('host1')

        vol_cap = {'timestamp': None}

        fake_host.update_from_volume_capability(vol_cap)
        self.assertEqual(0, fake_host.total_capacity_gb)
        self.assertEqual(None, fake_host.free_capacity_gb)
        # Pool stats has been updated
        self.assertEqual(0,
                         fake_host.pools['_pool0'].total_capacity_gb)
        self.assertEqual(0,
                         fake_host.pools['_pool0'].free_capacity_gb)
        self.assertEqual(0,
                         fake_host.pools['_pool0'].provisioned_capacity_gb)


class PoolStateTestCase(test.TestCase):
    """Test case for HostState class."""

    def test_update_from_volume_capability(self):
        fake_pool = host_manager.PoolState('host1', None, 'pool0')
        self.assertIsNone(fake_pool.free_capacity_gb)

        volume_capability = {'total_capacity_gb': 1024,
                             'free_capacity_gb': 512,
                             'reserved_percentage': 0,
                             'provisioned_capacity_gb': 512,
                             'timestamp': None,
                             'cap1': 'val1',
                             'cap2': 'val2'}

        fake_pool.update_from_volume_capability(volume_capability)
        self.assertEqual('host1#pool0', fake_pool.host)
        self.assertEqual('pool0', fake_pool.pool_name)
        self.assertEqual(1024, fake_pool.total_capacity_gb)
        self.assertEqual(512, fake_pool.free_capacity_gb)
        self.assertEqual(512,
                         fake_pool.provisioned_capacity_gb)

        self.assertDictMatch(fake_pool.capabilities, volume_capability)
