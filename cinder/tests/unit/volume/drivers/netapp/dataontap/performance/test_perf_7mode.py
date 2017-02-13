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
from cinder.volume.drivers.netapp.dataontap.performance import perf_7mode
from cinder.volume.drivers.netapp.dataontap.performance import perf_base


@ddt.ddt
class Performance7modeLibraryTestCase(test.TestCase):

    def setUp(self):
        super(Performance7modeLibraryTestCase, self).setUp()

        with mock.patch.object(perf_7mode.Performance7modeLibrary,
                               '_init_counter_info'):
            self.zapi_client = mock.Mock()
            self.zapi_client.get_system_name.return_value = fake.NODE
            self.perf_library = perf_7mode.Performance7modeLibrary(
                self.zapi_client)
            self.perf_library.system_object_name = 'system'
            self.perf_library.avg_processor_busy_base_counter_name = (
                'cpu_elapsed_time1')

    def test_init_counter_info_not_supported(self):

        self.zapi_client.features.SYSTEM_METRICS = False
        mock_get_base_counter_name = self.mock_object(
            self.perf_library, '_get_base_counter_name')

        self.perf_library._init_counter_info()

        self.assertIsNone(self.perf_library.system_object_name)
        self.assertIsNone(
            self.perf_library.avg_processor_busy_base_counter_name)
        self.assertFalse(mock_get_base_counter_name.called)

    def test_init_counter_info_api_error(self):

        self.zapi_client.features.SYSTEM_METRICS = True
        mock_get_base_counter_name = self.mock_object(
            self.perf_library, '_get_base_counter_name',
            side_effect=netapp_api.NaApiError)

        self.perf_library._init_counter_info()

        self.assertEqual('system', self.perf_library.system_object_name)
        self.assertEqual(
            'cpu_elapsed_time1',
            self.perf_library.avg_processor_busy_base_counter_name)
        mock_get_base_counter_name.assert_called_once_with(
            'system', 'avg_processor_busy')

    def test_init_counter_info_system(self):

        self.zapi_client.features.SYSTEM_METRICS = True
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

    def test_update_performance_cache(self):

        self.perf_library.performance_counters = list(range(11, 21))

        mock_get_node_utilization_counters = self.mock_object(
            self.perf_library, '_get_node_utilization_counters',
            return_value=21)
        mock_get_node_utilization = self.mock_object(
            self.perf_library, '_get_node_utilization',
            return_value=25)

        self.perf_library.update_performance_cache()

        self.assertEqual(list(range(12, 22)),
                         self.perf_library.performance_counters)
        self.assertEqual(25, self.perf_library.utilization)
        mock_get_node_utilization_counters.assert_called_once_with()
        mock_get_node_utilization.assert_called_once_with(12, 21, fake.NODE)

    def test_update_performance_cache_first_pass(self):

        mock_get_node_utilization_counters = self.mock_object(
            self.perf_library, '_get_node_utilization_counters',
            return_value=11)
        mock_get_node_utilization = self.mock_object(
            self.perf_library, '_get_node_utilization', return_value=25)

        self.perf_library.update_performance_cache()

        self.assertEqual([11], self.perf_library.performance_counters)
        mock_get_node_utilization_counters.assert_called_once_with()
        self.assertFalse(mock_get_node_utilization.called)

    def test_update_performance_cache_counters_unavailable(self):

        self.perf_library.performance_counters = list(range(11, 21))
        self.perf_library.utilization = 55.0

        mock_get_node_utilization_counters = self.mock_object(
            self.perf_library, '_get_node_utilization_counters',
            return_value=None)
        mock_get_node_utilization = self.mock_object(
            self.perf_library, '_get_node_utilization', return_value=25)

        self.perf_library.update_performance_cache()

        self.assertEqual(list(range(11, 21)),
                         self.perf_library.performance_counters)
        self.assertEqual(55.0, self.perf_library.utilization)
        mock_get_node_utilization_counters.assert_called_once_with()
        self.assertFalse(mock_get_node_utilization.called)

    def test_update_performance_cache_not_supported(self):

        self.zapi_client.features.SYSTEM_METRICS = False
        mock_get_node_utilization_counters = self.mock_object(
            self.perf_library, '_get_node_utilization_counters')

        self.perf_library.update_performance_cache()

        self.assertEqual([], self.perf_library.performance_counters)
        self.assertEqual(perf_base.DEFAULT_UTILIZATION,
                         self.perf_library.utilization)
        self.assertFalse(mock_get_node_utilization_counters.called)

    def test_get_node_utilization(self):

        self.perf_library.utilization = 47.1

        result = self.perf_library.get_node_utilization()

        self.assertEqual(47.1, result)

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

        result = self.perf_library._get_node_utilization_counters()

        expected = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I']
        self.assertEqual(expected, result)

        mock_get_node_utilization_system_counters.assert_called_once_with()
        mock_get_node_utilization_wafl_counters.assert_called_once_with()
        mock_get_node_utilization_processor_counters.assert_called_once_with()

    def test_get_node_utilization_counters_api_error(self):

        self.mock_object(self.perf_library,
                         '_get_node_utilization_system_counters',
                         side_effect=netapp_api.NaApiError)

        result = self.perf_library._get_node_utilization_counters()

        self.assertIsNone(result)

    def test_get_node_utilization_system_counters(self):

        mock_get_performance_instance_names = self.mock_object(
            self.zapi_client, 'get_performance_instance_names',
            return_value=fake.SYSTEM_INSTANCE_NAMES)
        mock_get_performance_counters = self.mock_object(
            self.zapi_client, 'get_performance_counters',
            return_value=fake.SYSTEM_COUNTERS)

        result = self.perf_library._get_node_utilization_system_counters()

        self.assertEqual(fake.SYSTEM_COUNTERS, result)

        mock_get_performance_instance_names.assert_called_once_with('system')
        mock_get_performance_counters.assert_called_once_with(
            'system', fake.SYSTEM_INSTANCE_NAMES,
            ['avg_processor_busy', 'cpu_elapsed_time1', 'cpu_elapsed_time'])

    def test_get_node_utilization_wafl_counters(self):

        mock_get_performance_instance_names = self.mock_object(
            self.zapi_client, 'get_performance_instance_names',
            return_value=fake.WAFL_INSTANCE_NAMES)
        mock_get_performance_counters = self.mock_object(
            self.zapi_client, 'get_performance_counters',
            return_value=fake.WAFL_COUNTERS)
        mock_get_performance_counter_info = self.mock_object(
            self.zapi_client, 'get_performance_counter_info',
            return_value=fake.WAFL_CP_PHASE_TIMES_COUNTER_INFO)

        result = self.perf_library._get_node_utilization_wafl_counters()

        self.assertEqual(fake.EXPANDED_WAFL_COUNTERS, result)

        mock_get_performance_instance_names.assert_called_once_with('wafl')
        mock_get_performance_counters.assert_called_once_with(
            'wafl', fake.WAFL_INSTANCE_NAMES,
            ['total_cp_msecs', 'cp_phase_times'])
        mock_get_performance_counter_info.assert_called_once_with(
            'wafl', 'cp_phase_times')

    def test_get_node_utilization_processor_counters(self):

        mock_get_performance_instance_names = self.mock_object(
            self.zapi_client, 'get_performance_instance_names',
            return_value=fake.PROCESSOR_INSTANCE_NAMES)
        mock_get_performance_counters = self.mock_object(
            self.zapi_client, 'get_performance_counters',
            return_value=fake.PROCESSOR_COUNTERS)
        self.mock_object(
            self.zapi_client, 'get_performance_counter_info',
            return_value=fake.PROCESSOR_DOMAIN_BUSY_COUNTER_INFO)

        result = self.perf_library._get_node_utilization_processor_counters()

        self.assertEqual(fake.EXPANDED_PROCESSOR_COUNTERS, result)

        mock_get_performance_instance_names.assert_called_once_with(
            'processor')
        mock_get_performance_counters.assert_called_once_with(
            'processor', fake.PROCESSOR_INSTANCE_NAMES,
            ['domain_busy', 'processor_elapsed_time'])
