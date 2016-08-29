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

from cinder import exception
from cinder import test
from cinder.tests.unit.volume.drivers.netapp.dataontap.performance \
    import fakes as fake
from cinder.volume.drivers.netapp.dataontap.performance import perf_base


@ddt.ddt
class PerformanceLibraryTestCase(test.TestCase):

    def setUp(self):
        super(PerformanceLibraryTestCase, self).setUp()

        with mock.patch.object(perf_base.PerformanceLibrary,
                               '_init_counter_info'):
            self.zapi_client = mock.Mock()
            self.perf_library = perf_base.PerformanceLibrary(self.zapi_client)
            self.perf_library.system_object_name = 'system'
            self.perf_library.avg_processor_busy_base_counter_name = (
                'cpu_elapsed_time1')

    def test_init(self):

        mock_zapi_client = mock.Mock()
        mock_init_counter_info = self.mock_object(
            perf_base.PerformanceLibrary, '_init_counter_info')

        library = perf_base.PerformanceLibrary(mock_zapi_client)

        self.assertEqual(mock_zapi_client, library.zapi_client)
        mock_init_counter_info.assert_called_once_with()

    def test_init_counter_info(self):

        self.perf_library._init_counter_info()

        self.assertIsNone(self.perf_library.system_object_name)
        self.assertIsNone(
            self.perf_library.avg_processor_busy_base_counter_name)

    def test_get_node_utilization_kahuna_overutilized(self):

        mock_get_kahuna_utilization = self.mock_object(
            self.perf_library, '_get_kahuna_utilization', return_value=61.0)
        mock_get_average_cpu_utilization = self.mock_object(
            self.perf_library, '_get_average_cpu_utilization',
            return_value=25.0)

        result = self.perf_library._get_node_utilization('fake1',
                                                         'fake2',
                                                         'fake_node')

        self.assertAlmostEqual(100.0, result)
        mock_get_kahuna_utilization.assert_called_once_with('fake1', 'fake2')
        self.assertFalse(mock_get_average_cpu_utilization.called)

    @ddt.data({'cpu': -0.01, 'cp_time': 10000, 'poll_time': 0},
              {'cpu': 1.01, 'cp_time': 0, 'poll_time': 1000},
              {'cpu': 0.50, 'cp_time': 0, 'poll_time': 0})
    @ddt.unpack
    def test_get_node_utilization_zero_time(self, cpu, cp_time, poll_time):

        mock_get_kahuna_utilization = self.mock_object(
            self.perf_library, '_get_kahuna_utilization', return_value=59.0)
        mock_get_average_cpu_utilization = self.mock_object(
            self.perf_library, '_get_average_cpu_utilization',
            return_value=cpu)
        mock_get_total_consistency_point_time = self.mock_object(
            self.perf_library, '_get_total_consistency_point_time',
            return_value=cp_time)
        mock_get_consistency_point_p2_flush_time = self.mock_object(
            self.perf_library, '_get_consistency_point_p2_flush_time',
            return_value=cp_time)
        mock_get_total_time = self.mock_object(
            self.perf_library, '_get_total_time', return_value=poll_time)
        mock_get_adjusted_consistency_point_time = self.mock_object(
            self.perf_library, '_get_adjusted_consistency_point_time')

        result = self.perf_library._get_node_utilization('fake1',
                                                         'fake2',
                                                         'fake_node')

        expected = max(min(100.0, 100.0 * cpu), 0)
        self.assertEqual(expected, result)

        mock_get_kahuna_utilization.assert_called_once_with('fake1', 'fake2')
        mock_get_average_cpu_utilization.assert_called_once_with('fake1',
                                                                 'fake2')
        mock_get_total_consistency_point_time.assert_called_once_with('fake1',
                                                                      'fake2')
        mock_get_consistency_point_p2_flush_time.assert_called_once_with(
            'fake1', 'fake2')
        mock_get_total_time.assert_called_once_with('fake1',
                                                    'fake2',
                                                    'total_cp_msecs')
        self.assertFalse(mock_get_adjusted_consistency_point_time.called)

    @ddt.data({'cpu': 0.75, 'adjusted_cp_time': 8000, 'expected': 80},
              {'cpu': 0.80, 'adjusted_cp_time': 7500, 'expected': 80},
              {'cpu': 0.50, 'adjusted_cp_time': 11000, 'expected': 100})
    @ddt.unpack
    def test_get_node_utilization(self, cpu, adjusted_cp_time, expected):

        mock_get_kahuna_utilization = self.mock_object(
            self.perf_library, '_get_kahuna_utilization', return_value=59.0)
        mock_get_average_cpu_utilization = self.mock_object(
            self.perf_library, '_get_average_cpu_utilization',
            return_value=cpu)
        mock_get_total_consistency_point_time = self.mock_object(
            self.perf_library, '_get_total_consistency_point_time',
            return_value=90.0)
        mock_get_consistency_point_p2_flush_time = self.mock_object(
            self.perf_library, '_get_consistency_point_p2_flush_time',
            return_value=50.0)
        mock_get_total_time = self.mock_object(
            self.perf_library, '_get_total_time', return_value=10000)
        mock_get_adjusted_consistency_point_time = self.mock_object(
            self.perf_library, '_get_adjusted_consistency_point_time',
            return_value=adjusted_cp_time)

        result = self.perf_library._get_node_utilization('fake1',
                                                         'fake2',
                                                         'fake_node')

        self.assertEqual(expected, result)

        mock_get_kahuna_utilization.assert_called_once_with('fake1', 'fake2')
        mock_get_average_cpu_utilization.assert_called_once_with('fake1',
                                                                 'fake2')
        mock_get_total_consistency_point_time.assert_called_once_with('fake1',
                                                                      'fake2')
        mock_get_consistency_point_p2_flush_time.assert_called_once_with(
            'fake1', 'fake2')
        mock_get_total_time.assert_called_once_with('fake1',
                                                    'fake2',
                                                    'total_cp_msecs')
        mock_get_adjusted_consistency_point_time.assert_called_once_with(
            90.0, 50.0)

    def test_get_node_utilization_calculation_error(self):

        self.mock_object(self.perf_library,
                         '_get_kahuna_utilization',
                         return_value=59.0)
        self.mock_object(self.perf_library,
                         '_get_average_cpu_utilization',
                         return_value=25.0)
        self.mock_object(self.perf_library,
                         '_get_total_consistency_point_time',
                         return_value=90.0)
        self.mock_object(self.perf_library,
                         '_get_consistency_point_p2_flush_time',
                         return_value=50.0)
        self.mock_object(self.perf_library,
                         '_get_total_time',
                         return_value=10000)
        self.mock_object(self.perf_library,
                         '_get_adjusted_consistency_point_time',
                         side_effect=ZeroDivisionError)

        result = self.perf_library._get_node_utilization('fake1',
                                                         'fake2',
                                                         'fake_node')

        self.assertEqual(perf_base.DEFAULT_UTILIZATION, result)

    def test_get_kahuna_utilization(self):

        mock_get_performance_counter = self.mock_object(
            self.perf_library,
            '_get_performance_counter_average_multi_instance',
            return_value=[0.2, 0.3])

        result = self.perf_library._get_kahuna_utilization('fake_t1',
                                                           'fake_t2')

        self.assertAlmostEqual(50.0, result)
        mock_get_performance_counter.assert_called_once_with(
            'fake_t1', 'fake_t2', 'domain_busy:kahuna',
            'processor_elapsed_time')

    def test_get_average_cpu_utilization(self):

        mock_get_performance_counter_average = self.mock_object(
            self.perf_library, '_get_performance_counter_average',
            return_value=0.45)

        result = self.perf_library._get_average_cpu_utilization('fake_t1',
                                                                'fake_t2')

        self.assertAlmostEqual(0.45, result)
        mock_get_performance_counter_average.assert_called_once_with(
            'fake_t1', 'fake_t2', 'avg_processor_busy', 'cpu_elapsed_time1')

    def test_get_total_consistency_point_time(self):

        mock_get_performance_counter_delta = self.mock_object(
            self.perf_library, '_get_performance_counter_delta',
            return_value=500)

        result = self.perf_library._get_total_consistency_point_time(
            'fake_t1', 'fake_t2')

        self.assertEqual(500, result)
        mock_get_performance_counter_delta.assert_called_once_with(
            'fake_t1', 'fake_t2', 'total_cp_msecs')

    def test_get_consistency_point_p2_flush_time(self):

        mock_get_performance_counter_delta = self.mock_object(
            self.perf_library, '_get_performance_counter_delta',
            return_value=500)

        result = self.perf_library._get_consistency_point_p2_flush_time(
            'fake_t1', 'fake_t2')

        self.assertEqual(500, result)
        mock_get_performance_counter_delta.assert_called_once_with(
            'fake_t1', 'fake_t2', 'cp_phase_times:p2_flush')

    def test_get_total_time(self):

        mock_find_performance_counter_timestamp = self.mock_object(
            self.perf_library, '_find_performance_counter_timestamp',
            side_effect=[100, 105])

        result = self.perf_library._get_total_time('fake_t1',
                                                   'fake_t2',
                                                   'fake_counter')

        self.assertEqual(5000, result)
        mock_find_performance_counter_timestamp.assert_has_calls([
            mock.call('fake_t1', 'fake_counter'),
            mock.call('fake_t2', 'fake_counter')])

    def test_get_adjusted_consistency_point_time(self):

        result = self.perf_library._get_adjusted_consistency_point_time(
            500, 200)

        self.assertAlmostEqual(360.0, result)

    def test_get_performance_counter_delta(self):

        result = self.perf_library._get_performance_counter_delta(
            fake.COUNTERS_T1, fake.COUNTERS_T2, 'total_cp_msecs')

        self.assertEqual(1482, result)

    def test_get_performance_counter_average(self):

        result = self.perf_library._get_performance_counter_average(
            fake.COUNTERS_T1, fake.COUNTERS_T2, 'domain_busy:kahuna',
            'processor_elapsed_time', 'processor0')

        self.assertAlmostEqual(0.00281954360981, result)

    def test_get_performance_counter_average_multi_instance(self):

        result = (
            self.perf_library._get_performance_counter_average_multi_instance(
                fake.COUNTERS_T1, fake.COUNTERS_T2, 'domain_busy:kahuna',
                'processor_elapsed_time'))

        expected = [0.002819543609809441, 0.0033421611147606135]
        self.assertAlmostEqual(expected, result)

    def test_find_performance_counter_value(self):

        result = self.perf_library._find_performance_counter_value(
            fake.COUNTERS_T1, 'domain_busy:kahuna',
            instance_name='processor0')

        self.assertEqual('2712467226', result)

    def test_find_performance_counter_value_not_found(self):

        self.assertRaises(
            exception.NotFound,
            self.perf_library._find_performance_counter_value,
            fake.COUNTERS_T1, 'invalid', instance_name='processor0')

    def test_find_performance_counter_timestamp(self):

        result = self.perf_library._find_performance_counter_timestamp(
            fake.COUNTERS_T1, 'domain_busy')

        self.assertEqual('1453573777', result)

    def test_find_performance_counter_timestamp_not_found(self):

        self.assertRaises(
            exception.NotFound,
            self.perf_library._find_performance_counter_timestamp,
            fake.COUNTERS_T1, 'invalid', instance_name='processor0')

    def test_expand_performance_array(self):

        counter_info = {
            'labels': ['idle', 'kahuna', 'storage', 'exempt'],
            'name': 'domain_busy',
        }
        self.zapi_client.get_performance_counter_info = mock.Mock(
            return_value=counter_info)

        counter = {
            'node-name': 'cluster1-01',
            'instance-uuid': 'cluster1-01:kernel:processor0',
            'domain_busy': '969142314286,2567571412,2131582146,5383861579',
            'instance-name': 'processor0',
            'timestamp': '1453512244',
        }
        self.perf_library._expand_performance_array('wafl',
                                                    'domain_busy',
                                                    counter)

        modified_counter = {
            'node-name': 'cluster1-01',
            'instance-uuid': 'cluster1-01:kernel:processor0',
            'domain_busy': '969142314286,2567571412,2131582146,5383861579',
            'instance-name': 'processor0',
            'timestamp': '1453512244',
            'domain_busy:idle': '969142314286',
            'domain_busy:kahuna': '2567571412',
            'domain_busy:storage': '2131582146',
            'domain_busy:exempt': '5383861579',
        }
        self.assertEqual(modified_counter, counter)

    def test_get_base_counter_name(self):

        counter_info = {
            'base-counter': 'cpu_elapsed_time',
            'labels': [],
            'name': 'avg_processor_busy',
        }
        self.zapi_client.get_performance_counter_info = mock.Mock(
            return_value=counter_info)

        result = self.perf_library._get_base_counter_name(
            'system:constituent', 'avg_processor_busy')

        self.assertEqual('cpu_elapsed_time', result)
