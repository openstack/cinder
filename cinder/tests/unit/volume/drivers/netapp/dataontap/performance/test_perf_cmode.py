# Copyright (c) 2016 Clinton Knight
# All rights reserved.
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

import ddt
import mock

from cinder import test
from cinder.tests.unit.volume.drivers.netapp.dataontap.performance \
    import fakes as fake
from cinder.volume.drivers.netapp.dataontap.client import api as netapp_api
from cinder.volume.drivers.netapp.dataontap.performance import perf_base
from cinder.volume.drivers.netapp.dataontap.performance import perf_cmode


@ddt.ddt
class PerformanceCmodeLibraryTestCase(test.TestCase):

    def setUp(self):
        super(PerformanceCmodeLibraryTestCase, self).setUp()

        with mock.patch.object(perf_cmode.PerformanceCmodeLibrary,
                               '_init_counter_info'):
            self.zapi_client = mock.Mock()
            self.perf_library = perf_cmode.PerformanceCmodeLibrary(
                self.zapi_client)
            self.perf_library.system_object_name = 'system'
            self.perf_library.avg_processor_busy_base_counter_name = (
                'cpu_elapsed_time1')

        self._set_up_fake_pools()

    def _set_up_fake_pools(self):

        self.fake_volumes = {
            'pool1': {
                'netapp_aggregate': 'aggr1',
            },
            'pool2': {
                'netapp_aggregate': 'aggr2',
            },
            'pool3': {
                'netapp_aggregate': 'aggr2',
            },
        }

        self.fake_aggrs = set(['aggr1', 'aggr2', 'aggr3'])
        self.fake_nodes = set(['node1', 'node2'])
        self.fake_aggr_node_map = {
            'aggr1': 'node1',
            'aggr2': 'node2',
            'aggr3': 'node2',
        }

    def test_init_counter_info_not_supported(self):

        self.zapi_client.features.SYSTEM_METRICS = False
        self.zapi_client.features.SYSTEM_CONSTITUENT_METRICS = False
        mock_get_base_counter_name = self.mock_object(
            self.perf_library, '_get_base_counter_name')

        self.perf_library._init_counter_info()

        self.assertIsNone(self.perf_library.system_object_name)
        self.assertIsNone(
            self.perf_library.avg_processor_busy_base_counter_name)
        self.assertFalse(mock_get_base_counter_name.called)

    @ddt.data({
        'system_constituent': False,
        'base_counter': 'cpu_elapsed_time1',
    }, {
        'system_constituent': True,
        'base_counter': 'cpu_elapsed_time',
    })
    @ddt.unpack
    def test_init_counter_info_api_error(self, system_constituent,
                                         base_counter):

        self.zapi_client.features.SYSTEM_METRICS = True
        self.zapi_client.features.SYSTEM_CONSTITUENT_METRICS = (
            system_constituent)
        self.mock_object(self.perf_library,
                         '_get_base_counter_name',
                         side_effect=netapp_api.NaApiError)

        self.perf_library._init_counter_info()

        self.assertEqual(
            base_counter,
            self.perf_library.avg_processor_busy_base_counter_name)

    def test_init_counter_info_system(self):

        self.zapi_client.features.SYSTEM_METRICS = True
        self.zapi_client.features.SYSTEM_CONSTITUENT_METRICS = False
        mock_get_base_counter_name = self.mock_object(
            self.perf_library, '_get_base_counter_name',
            return_value='cpu_elapsed_time1')

        self.perf_library._init_counter_info()

        self.assertEqual('system', self.perf_library.system_object_name)
        self.assertEqual(
            'cpu_elapsed_time1',
            self.perf_library.avg_processor_busy_base_counter_name)
        mock_get_base_counter_name.assert_called_once_with(
            'system', 'avg_processor_busy')

    def test_init_counter_info_system_constituent(self):

        self.zapi_client.features.SYSTEM_METRICS = False
        self.zapi_client.features.SYSTEM_CONSTITUENT_METRICS = True
        mock_get_base_counter_name = self.mock_object(
            self.perf_library, '_get_base_counter_name',
            return_value='cpu_elapsed_time')

        self.perf_library._init_counter_info()

        self.assertEqual('system:constituent',
                         self.perf_library.system_object_name)
        self.assertEqual(
            'cpu_elapsed_time',
            self.perf_library.avg_processor_busy_base_counter_name)
        mock_get_base_counter_name.assert_called_once_with(
            'system:constituent', 'avg_processor_busy')

    @test.testtools.skip("launchpad bug 1715915")
    def test_update_performance_cache(self):

        self.perf_library.performance_counters = {
            'node1': list(range(11, 21)),
            'node2': list(range(21, 31)),
        }
        mock_get_aggregates_for_pools = self.mock_object(
            self.perf_library, '_get_aggregates_for_pools',
            return_value=self.fake_aggrs)
        mock_get_nodes_for_aggregates = self.mock_object(
            self.perf_library, '_get_nodes_for_aggregates',
            return_value=(self.fake_nodes, self.fake_aggr_node_map))
        mock_get_node_utilization_counters = self.mock_object(
            self.perf_library, '_get_node_utilization_counters',
            side_effect=[21, 31])
        mock_get_node_utilization = self.mock_object(
            self.perf_library, '_get_node_utilization', side_effect=[25, 75])

        self.perf_library.update_performance_cache(self.fake_volumes)

        expected_performance_counters = {
            'node1': list(range(12, 22)),
            'node2': list(range(22, 32)),
        }
        self.assertEqual(expected_performance_counters,
                         self.perf_library.performance_counters)

        expected_pool_utilization = {'pool1': 25, 'pool2': 75, 'pool3': 75}
        self.assertEqual(expected_pool_utilization,
                         self.perf_library.pool_utilization)

        mock_get_aggregates_for_pools.assert_called_once_with(
            self.fake_volumes)
        mock_get_nodes_for_aggregates.assert_called_once_with(self.fake_aggrs)
        mock_get_node_utilization_counters.assert_has_calls([
            mock.call('node1'), mock.call('node2')])
        mock_get_node_utilization.assert_has_calls([
            mock.call(12, 21, 'node1'), mock.call(22, 31, 'node2')])

    @test.testtools.skip("launchpad bug #1715915")
    def test_update_performance_cache_first_pass(self):

        mock_get_aggregates_for_pools = self.mock_object(
            self.perf_library, '_get_aggregates_for_pools',
            return_value=self.fake_aggrs)
        mock_get_nodes_for_aggregates = self.mock_object(
            self.perf_library, '_get_nodes_for_aggregates',
            return_value=(self.fake_nodes, self.fake_aggr_node_map))
        mock_get_node_utilization_counters = self.mock_object(
            self.perf_library, '_get_node_utilization_counters',
            side_effect=[11, 21])
        mock_get_node_utilization = self.mock_object(
            self.perf_library, '_get_node_utilization', side_effect=[25, 75])

        self.perf_library.update_performance_cache(self.fake_volumes)

        expected_performance_counters = {'node1': [11], 'node2': [21]}
        self.assertEqual(expected_performance_counters,
                         self.perf_library.performance_counters)

        expected_pool_utilization = {
            'pool1': perf_base.DEFAULT_UTILIZATION,
            'pool2': perf_base.DEFAULT_UTILIZATION,
            'pool3': perf_base.DEFAULT_UTILIZATION,
        }
        self.assertEqual(expected_pool_utilization,
                         self.perf_library.pool_utilization)

        mock_get_aggregates_for_pools.assert_called_once_with(
            self.fake_volumes)
        mock_get_nodes_for_aggregates.assert_called_once_with(self.fake_aggrs)
        mock_get_node_utilization_counters.assert_has_calls([
            mock.call('node1'), mock.call('node2')])
        self.assertFalse(mock_get_node_utilization.called)

    def test_update_performance_cache_unknown_nodes(self):

        self.perf_library.performance_counters = {
            'node1': range(11, 21),
            'node2': range(21, 31),
        }
        mock_get_aggregates_for_pools = self.mock_object(
            self.perf_library, '_get_aggregates_for_pools',
            return_value=self.fake_aggrs)
        mock_get_nodes_for_aggregates = self.mock_object(
            self.perf_library, '_get_nodes_for_aggregates',
            return_value=(set(), {}))
        mock_get_node_utilization_counters = self.mock_object(
            self.perf_library, '_get_node_utilization_counters',
            side_effect=[11, 21])
        mock_get_node_utilization = self.mock_object(
            self.perf_library, '_get_node_utilization', side_effect=[25, 75])

        self.perf_library.update_performance_cache(self.fake_volumes)

        expected_performance_counters = {
            'node1': range(11, 21),
            'node2': range(21, 31),
        }
        self.assertEqual(expected_performance_counters,
                         self.perf_library.performance_counters)

        expected_pool_utilization = {
            'pool1': perf_base.DEFAULT_UTILIZATION,
            'pool2': perf_base.DEFAULT_UTILIZATION,
            'pool3': perf_base.DEFAULT_UTILIZATION,
        }
        self.assertEqual(expected_pool_utilization,
                         self.perf_library.pool_utilization)

        mock_get_aggregates_for_pools.assert_called_once_with(
            self.fake_volumes)
        mock_get_nodes_for_aggregates.assert_called_once_with(self.fake_aggrs)
        self.assertFalse(mock_get_node_utilization_counters.called)
        self.assertFalse(mock_get_node_utilization.called)

    def test_update_performance_cache_counters_unavailable(self):

        self.perf_library.performance_counters = {
            'node1': range(11, 21),
            'node2': range(21, 31),
        }
        mock_get_aggregates_for_pools = self.mock_object(
            self.perf_library, '_get_aggregates_for_pools',
            return_value=self.fake_aggrs)
        mock_get_nodes_for_aggregates = self.mock_object(
            self.perf_library, '_get_nodes_for_aggregates',
            return_value=(self.fake_nodes, self.fake_aggr_node_map))
        mock_get_node_utilization_counters = self.mock_object(
            self.perf_library, '_get_node_utilization_counters',
            side_effect=[None, None])
        mock_get_node_utilization = self.mock_object(
            self.perf_library, '_get_node_utilization', side_effect=[25, 75])

        self.perf_library.update_performance_cache(self.fake_volumes)

        expected_performance_counters = {
            'node1': range(11, 21),
            'node2': range(21, 31),
        }
        self.assertEqual(expected_performance_counters,
                         self.perf_library.performance_counters)

        expected_pool_utilization = {
            'pool1': perf_base.DEFAULT_UTILIZATION,
            'pool2': perf_base.DEFAULT_UTILIZATION,
            'pool3': perf_base.DEFAULT_UTILIZATION,
        }
        self.assertEqual(expected_pool_utilization,
                         self.perf_library.pool_utilization)

        mock_get_aggregates_for_pools.assert_called_once_with(
            self.fake_volumes)
        mock_get_nodes_for_aggregates.assert_called_once_with(self.fake_aggrs)
        mock_get_node_utilization_counters.assert_has_calls([
            mock.call('node1'), mock.call('node2')],
            any_order=True)
        self.assertFalse(mock_get_node_utilization.called)

    def test_update_performance_cache_not_supported(self):

        self.zapi_client.features.SYSTEM_METRICS = False
        self.zapi_client.features.SYSTEM_CONSTITUENT_METRICS = False

        mock_get_aggregates_for_pools = self.mock_object(
            self.perf_library, '_get_aggregates_for_pools')

        self.perf_library.update_performance_cache(self.fake_volumes)

        expected_performance_counters = {}
        self.assertEqual(expected_performance_counters,
                         self.perf_library.performance_counters)

        expected_pool_utilization = {}
        self.assertEqual(expected_pool_utilization,
                         self.perf_library.pool_utilization)

        self.assertFalse(mock_get_aggregates_for_pools.called)

    @ddt.data({'pool': 'pool1', 'expected': 10.0},
              {'pool': 'pool3', 'expected': perf_base.DEFAULT_UTILIZATION})
    @ddt.unpack
    def test_get_node_utilization_for_pool(self, pool, expected):

        self.perf_library.pool_utilization = {'pool1': 10.0, 'pool2': 15.0}

        result = self.perf_library.get_node_utilization_for_pool(pool)

        self.assertAlmostEqual(expected, result)

    def test__update_for_failover(self):
        self.mock_object(self.perf_library, 'update_performance_cache')
        mock_client = mock.Mock(name='FAKE_ZAPI_CLIENT')

        self.perf_library._update_for_failover(mock_client, self.fake_volumes)

        self.assertEqual(mock_client, self.perf_library.zapi_client)
        self.perf_library.update_performance_cache.assert_called_once_with(
            self.fake_volumes)

    def test_get_aggregates_for_pools(self):

        result = self.perf_library._get_aggregates_for_pools(self.fake_volumes)

        expected_aggregate_names = set(['aggr1', 'aggr2'])
        self.assertEqual(expected_aggregate_names, result)

    def test_get_nodes_for_aggregates(self):

        aggregate_names = ['aggr1', 'aggr2', 'aggr3']
        aggregate_nodes = ['node1', 'node2', 'node2']

        mock_get_node_for_aggregate = self.mock_object(
            self.zapi_client, 'get_node_for_aggregate',
            side_effect=aggregate_nodes)

        result = self.perf_library._get_nodes_for_aggregates(aggregate_names)

        self.assertEqual(2, len(result))
        result_node_names, result_aggr_node_map = result

        expected_node_names = set(['node1', 'node2'])
        expected_aggr_node_map = dict(zip(aggregate_names, aggregate_nodes))
        self.assertEqual(expected_node_names, result_node_names)
        self.assertEqual(expected_aggr_node_map, result_aggr_node_map)
        mock_get_node_for_aggregate.assert_has_calls([
            mock.call('aggr1'), mock.call('aggr2'), mock.call('aggr3')])

    def test_get_node_utilization_counters(self):

        mock_get_node_utilization_system_counters = self.mock_object(
            self.perf_library, '_get_node_utilization_system_counters',
            return_value=['A', 'B', 'C'])
        mock_get_node_utilization_wafl_counters = self.mock_object(
            self.perf_library, '_get_node_utilization_wafl_counters',
            return_value=['D', 'E', 'F'])
        mock_get_node_utilization_processor_counters = self.mock_object(
            self.perf_library, '_get_node_utilization_processor_counters',
            return_value=['G', 'H', 'I'])

        result = self.perf_library._get_node_utilization_counters(fake.NODE)

        expected = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I']
        self.assertEqual(expected, result)

        mock_get_node_utilization_system_counters.assert_called_once_with(
            fake.NODE)
        mock_get_node_utilization_wafl_counters.assert_called_once_with(
            fake.NODE)
        mock_get_node_utilization_processor_counters.assert_called_once_with(
            fake.NODE)

    def test_get_node_utilization_counters_api_error(self):

        self.mock_object(self.perf_library,
                         '_get_node_utilization_system_counters',
                         side_effect=netapp_api.NaApiError)

        result = self.perf_library._get_node_utilization_counters(fake.NODE)

        self.assertIsNone(result)

    def test_get_node_utilization_system_counters(self):

        mock_get_performance_instance_uuids = self.mock_object(
            self.zapi_client, 'get_performance_instance_uuids',
            return_value=fake.SYSTEM_INSTANCE_UUIDS)
        mock_get_performance_counters = self.mock_object(
            self.zapi_client, 'get_performance_counters',
            return_value=fake.SYSTEM_COUNTERS)

        result = self.perf_library._get_node_utilization_system_counters(
            fake.NODE)

        self.assertEqual(fake.SYSTEM_COUNTERS, result)

        mock_get_performance_instance_uuids.assert_called_once_with(
            'system', fake.NODE)
        mock_get_performance_counters.assert_called_once_with(
            'system', fake.SYSTEM_INSTANCE_UUIDS,
            ['avg_processor_busy', 'cpu_elapsed_time1', 'cpu_elapsed_time'])

    def test_get_node_utilization_wafl_counters(self):

        mock_get_performance_instance_uuids = self.mock_object(
            self.zapi_client, 'get_performance_instance_uuids',
            return_value=fake.WAFL_INSTANCE_UUIDS)
        mock_get_performance_counters = self.mock_object(
            self.zapi_client, 'get_performance_counters',
            return_value=fake.WAFL_COUNTERS)
        mock_get_performance_counter_info = self.mock_object(
            self.zapi_client, 'get_performance_counter_info',
            return_value=fake.WAFL_CP_PHASE_TIMES_COUNTER_INFO)

        result = self.perf_library._get_node_utilization_wafl_counters(
            fake.NODE)

        self.assertEqual(fake.EXPANDED_WAFL_COUNTERS, result)

        mock_get_performance_instance_uuids.assert_called_once_with(
            'wafl', fake.NODE)
        mock_get_performance_counters.assert_called_once_with(
            'wafl', fake.WAFL_INSTANCE_UUIDS,
            ['total_cp_msecs', 'cp_phase_times'])
        mock_get_performance_counter_info.assert_called_once_with(
            'wafl', 'cp_phase_times')

    def test_get_node_utilization_processor_counters(self):

        mock_get_performance_instance_uuids = self.mock_object(
            self.zapi_client, 'get_performance_instance_uuids',
            return_value=fake.PROCESSOR_INSTANCE_UUIDS)
        mock_get_performance_counters = self.mock_object(
            self.zapi_client, 'get_performance_counters',
            return_value=fake.PROCESSOR_COUNTERS)
        self.mock_object(
            self.zapi_client, 'get_performance_counter_info',
            return_value=fake.PROCESSOR_DOMAIN_BUSY_COUNTER_INFO)

        result = self.perf_library._get_node_utilization_processor_counters(
            fake.NODE)

        self.assertEqual(fake.EXPANDED_PROCESSOR_COUNTERS, result)

        mock_get_performance_instance_uuids.assert_called_once_with(
            'processor', fake.NODE)
        mock_get_performance_counters.assert_called_once_with(
            'processor', fake.PROCESSOR_INSTANCE_UUIDS,
            ['domain_busy', 'processor_elapsed_time'])
