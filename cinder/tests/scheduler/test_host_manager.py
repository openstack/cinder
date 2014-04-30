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

import mock

from oslo.config import cfg

from cinder import exception
from cinder.openstack.common.scheduler import filters
from cinder.openstack.common import timeutils
from cinder.scheduler import host_manager
from cinder import test


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
                           for x in xrange(1, 5)]

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
        self.assertEqual(len(filter_classes), 1)
        self.assertEqual(filter_classes[0].__name__, 'FakeFilterClass2')

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
        self.assertEqual(set(result), set(self.fake_hosts))

    @mock.patch('cinder.openstack.common.timeutils.utcnow')
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
        self.assertEqual(self.host_manager.service_states, service_states)
        # Make sure original dictionary wasn't copied
        self.assertEqual(host1_volume_capabs['timestamp'], 1)

        host1_volume_capabs['timestamp'] = 31337
        host2_volume_capabs['timestamp'] = 31338
        host3_volume_capabs['timestamp'] = 31339

        expected = {'host1': host1_volume_capabs,
                    'host2': host2_volume_capabs,
                    'host3': host3_volume_capabs}
        self.assertDictMatch(service_states, expected)

    @mock.patch('cinder.db.service_get_all_by_topic')
    @mock.patch('cinder.utils.service_is_up')
    def test_get_all_host_states(self, _mock_service_is_up,
                                 _mock_service_get_all_by_topic):
        context = 'fake_context'
        topic = CONF.volume_topic

        services = [
            dict(id=1, host='host1', topic='volume', disabled=False,
                 availability_zone='zone1', updated_at=timeutils.utcnow()),
            dict(id=2, host='host2', topic='volume', disabled=False,
                 availability_zone='zone1', updated_at=timeutils.utcnow()),
            dict(id=3, host='host3', topic='volume', disabled=False,
                 availability_zone='zone2', updated_at=timeutils.utcnow()),
            dict(id=4, host='host4', topic='volume', disabled=False,
                 availability_zone='zone3', updated_at=timeutils.utcnow()),
        ]

        # First test: service_is_up is always True, host5 is disabled
        _mock_service_get_all_by_topic.return_value = services
        _mock_service_is_up.return_value = True
        _mock_warning = mock.Mock()
        host_manager.LOG.warn = _mock_warning

        # Get all states
        self.host_manager.get_all_host_states(context)
        _mock_service_get_all_by_topic.assert_called_with(context,
                                                          topic,
                                                          disabled=False)
        expected = []
        for service in services:
            expected.append(mock.call(service))
        self.assertEqual(expected, _mock_service_is_up.call_args_list)

        # Get host_state_map and make sure we have the first 4 hosts
        host_state_map = self.host_manager.host_state_map
        self.assertEqual(len(host_state_map), 4)
        for i in xrange(4):
            volume_node = services[i]
            host = volume_node['host']
            self.assertEqual(host_state_map[host].service, volume_node)

        # Second test: Now service_is_up returns False for host4
        _mock_service_is_up.reset_mock()
        _mock_service_is_up.side_effect = [True, True, True, False]
        _mock_service_get_all_by_topic.reset_mock()
        _mock_warning.reset_mock()

        # Get all states, make sure host 4 is reported as down
        self.host_manager.get_all_host_states(context)
        _mock_service_get_all_by_topic.assert_called_with(context,
                                                          topic,
                                                          disabled=False)
        expected = []
        for service in services:
            expected.append(mock.call(service))
        self.assertEqual(expected, _mock_service_is_up.call_args_list)
        expected = []
        for num in ['4']:
            expected.append(mock.call("volume service is down. "
                                      "(host: host" + num + ")"))
        self.assertEqual(expected, _mock_warning.call_args_list)

        # Get host_state_map and make sure we have the first 4 hosts
        host_state_map = self.host_manager.host_state_map
        self.assertEqual(len(host_state_map), 3)
        for i in xrange(3):
            volume_node = services[i]
            host = volume_node['host']
            self.assertEqual(host_state_map[host].service,
                             volume_node)


class HostStateTestCase(test.TestCase):
    """Test case for HostState class."""

    def test_update_from_volume_capability(self):
        fake_host = host_manager.HostState('host1')
        self.assertIsNone(fake_host.free_capacity_gb)

        volume_capability = {'total_capacity_gb': 1024,
                             'free_capacity_gb': 512,
                             'reserved_percentage': 0,
                             'timestamp': None}

        fake_host.update_from_volume_capability(volume_capability)
        self.assertEqual(fake_host.free_capacity_gb, 512)

    def test_update_from_volume_infinite_capability(self):
        fake_host = host_manager.HostState('host1')
        self.assertIsNone(fake_host.free_capacity_gb)

        volume_capability = {'total_capacity_gb': 'infinite',
                             'free_capacity_gb': 'infinite',
                             'reserved_percentage': 0,
                             'timestamp': None}

        fake_host.update_from_volume_capability(volume_capability)
        self.assertEqual(fake_host.total_capacity_gb, 'infinite')
        self.assertEqual(fake_host.free_capacity_gb, 'infinite')

    def test_update_from_volume_unknown_capability(self):
        fake_host = host_manager.HostState('host1')
        self.assertIsNone(fake_host.free_capacity_gb)

        volume_capability = {'total_capacity_gb': 'infinite',
                             'free_capacity_gb': 'unknown',
                             'reserved_percentage': 0,
                             'timestamp': None}

        fake_host.update_from_volume_capability(volume_capability)
        self.assertEqual(fake_host.total_capacity_gb, 'infinite')
        self.assertEqual(fake_host.free_capacity_gb, 'unknown')
