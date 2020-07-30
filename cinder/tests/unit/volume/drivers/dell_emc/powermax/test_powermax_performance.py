# Copyright (c) 2020 Dell Inc. or its subsidiaries.
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

from copy import deepcopy
from unittest import mock

from cinder.tests.unit import test
from cinder.tests.unit.volume.drivers.dell_emc.powermax import (
    powermax_data as tpd)
from cinder.tests.unit.volume.drivers.dell_emc.powermax import (
    powermax_fake_objects as tpfo)
from cinder.volume.drivers.dell_emc.powermax import iscsi
from cinder.volume.drivers.dell_emc.powermax import performance
from cinder.volume.drivers.dell_emc.powermax import rest
from cinder.volume.drivers.dell_emc.powermax import utils
from cinder.volume import volume_utils


class PowerMaxPerformanceTest(test.TestCase):

    def setUp(self):
        self.data = tpd.PowerMaxData()
        self.reference_cinder_conf = tpfo.FakeConfiguration(
            None, 'ProvisionTests', 1, 1, san_ip='1.1.1.1', san_login='smc',
            powermax_array=self.data.array, powermax_srp='SRP_1',
            san_password='smc', san_api_port=8443,
            powermax_port_groups=[self.data.port_group_name_i],
            load_balance=True, load_balance_real_time=True,
            load_data_format='avg', load_look_back=60,
            load_look_back_real_time=10, port_group_load_metric='PercentBusy',
            port_load_metric='PercentBusy')
        self.reference_perf_conf = {
            'load_balance': True, 'load_balance_rt': True,
            'perf_registered': True, 'rt_registered': True,
            'collection_interval': 5, 'data_format': 'Average',
            'look_back': 60, 'look_back_rt': 10,
            'port_group_metric': 'PercentBusy', 'port_metric': 'PercentBusy'}

        super(PowerMaxPerformanceTest, self).setUp()

        volume_utils.get_max_over_subscription_ratio = mock.Mock()
        rest.PowerMaxRest._establish_rest_session = mock.Mock(
            return_value=tpfo.FakeRequestsSession())
        driver = iscsi.PowerMaxISCSIDriver(
            configuration=self.reference_cinder_conf)
        self.driver = driver
        self.common = self.driver.common
        self.performance = self.driver.performance
        self.rest = self.common.rest

    def test_set_performance_configuration(self):
        """Test set_performance_configuration diagnostic & real time."""
        self.assertEqual(self.reference_perf_conf, self.performance.config)

    @mock.patch.object(
        performance.PowerMaxPerformance, 'get_array_registration_details',
        return_value=(True, False, 5))
    def test_set_performance_configuration_no_rt_reg_rt_disabled(
            self, mck_reg):
        """Test set_performance_configuration real-time disabled.

        Test configurations settings when real-time is disabled in cinder.conf
        and real-time metrics are not registered in Unisphere.
        """
        cinder_conf = deepcopy(self.reference_cinder_conf)
        cinder_conf.load_balance_real_time = False
        rest.PowerMaxRest._establish_rest_session = mock.Mock(
            return_value=tpfo.FakeRequestsSession())
        temp_driver = iscsi.PowerMaxISCSIDriver(configuration=cinder_conf)
        perf_conf = deepcopy(self.reference_perf_conf)
        perf_conf['load_balance_rt'] = False
        perf_conf['rt_registered'] = False
        self.assertEqual(perf_conf, temp_driver.performance.config)

    def test_set_performance_configuration_rt_reg_rt_disabled(self):
        """Test set_performance_configuration real-time disabled v2.

        Test configurations settings when real-time is disabled in cinder.conf
        and real-time metrics are registered in Unisphere.
        """
        cinder_conf = deepcopy(self.reference_cinder_conf)
        cinder_conf.load_balance_real_time = False
        rest.PowerMaxRest._establish_rest_session = mock.Mock(
            return_value=tpfo.FakeRequestsSession())
        temp_driver = iscsi.PowerMaxISCSIDriver(configuration=cinder_conf)
        perf_conf = deepcopy(self.reference_perf_conf)
        perf_conf['load_balance_rt'] = False
        perf_conf['rt_registered'] = True
        self.assertEqual(perf_conf, temp_driver.performance.config)

    @mock.patch.object(
        performance.PowerMaxPerformance, 'get_array_registration_details',
        return_value=(False, False, 5))
    def test_set_performance_configuration_not_perf_registered(self, mck_reg):
        """Test set_performance_configuration performance metrics not enabled.

        This tests config settings where user has enabled load balancing in
        cinder.conf but Unisphere is not registered for performance metrics.
        """
        cinder_conf = deepcopy(self.reference_cinder_conf)
        rest.PowerMaxRest._establish_rest_session = mock.Mock(
            return_value=tpfo.FakeRequestsSession())
        temp_driver = iscsi.PowerMaxISCSIDriver(configuration=cinder_conf)
        perf_conf = {'load_balance': False}
        self.assertEqual(perf_conf, temp_driver.performance.config)

    def test_set_performance_configuration_invalid_data_format(self):
        """Test set_performance_configuration invalid data format, avg set."""
        cinder_conf = deepcopy(self.reference_cinder_conf)
        cinder_conf.load_data_format = 'InvalidFormat'
        rest.PowerMaxRest._establish_rest_session = mock.Mock(
            return_value=tpfo.FakeRequestsSession())
        temp_driver = iscsi.PowerMaxISCSIDriver(configuration=cinder_conf)
        self.assertEqual(self.reference_perf_conf,
                         temp_driver.performance.config)

    def test_set_performance_configuration_max_data_format(self):
        """Test set_performance_configuration max data format, max set."""
        cinder_conf = deepcopy(self.reference_cinder_conf)
        cinder_conf.load_data_format = 'MAXIMUM'
        rest.PowerMaxRest._establish_rest_session = mock.Mock(
            return_value=tpfo.FakeRequestsSession())
        temp_driver = iscsi.PowerMaxISCSIDriver(configuration=cinder_conf)
        perf_conf = deepcopy(self.reference_perf_conf)
        perf_conf['data_format'] = 'Maximum'
        self.assertEqual(perf_conf, temp_driver.performance.config)

    def test_set_performance_configuration_lookback_invalid(self):
        """Test set_performance_configuration invalid lookback windows."""
        # Window set to negative value
        cinder_conf = deepcopy(self.reference_cinder_conf)
        cinder_conf.load_look_back = -1
        rest.PowerMaxRest._establish_rest_session = mock.Mock(
            return_value=tpfo.FakeRequestsSession())
        temp_driver = iscsi.PowerMaxISCSIDriver(configuration=cinder_conf)
        perf_conf = deepcopy(self.reference_perf_conf)
        perf_conf['look_back'] = 60
        self.assertEqual(perf_conf, temp_driver.performance.config)

        # Window set to value larger than upper limit of 1440
        cinder_conf.load_look_back = 9999
        temp_driver = iscsi.PowerMaxISCSIDriver(configuration=cinder_conf)
        self.assertEqual(perf_conf, temp_driver.performance.config)

    def test_set_performance_configuration_rt_lookback_invalid(self):
        """Test set_performance_configuration invalid rt lookback windows."""
        # Window set to negative value
        cinder_conf = deepcopy(self.reference_cinder_conf)
        cinder_conf.load_look_back_real_time = -1
        rest.PowerMaxRest._establish_rest_session = mock.Mock(
            return_value=tpfo.FakeRequestsSession())
        temp_driver = iscsi.PowerMaxISCSIDriver(configuration=cinder_conf)
        perf_conf = deepcopy(self.reference_perf_conf)
        perf_conf['look_back_rt'] = 1
        self.assertEqual(perf_conf, temp_driver.performance.config)

        # Window set to value larger than upper limit of 1440
        cinder_conf.load_look_back_real_time = 100
        temp_driver = iscsi.PowerMaxISCSIDriver(configuration=cinder_conf)
        self.assertEqual(perf_conf, temp_driver.performance.config)

    def test_set_performance_configuration_invalid_pg_metric(self):
        """Test set_performance_configuration invalid pg metric."""
        cinder_conf = deepcopy(self.reference_cinder_conf)
        cinder_conf.port_group_load_metric = 'InvalidMetric'
        rest.PowerMaxRest._establish_rest_session = mock.Mock(
            return_value=tpfo.FakeRequestsSession())
        temp_driver = iscsi.PowerMaxISCSIDriver(configuration=cinder_conf)
        self.assertEqual(self.reference_perf_conf,
                         temp_driver.performance.config)

    def test_set_performance_configuration_invalid_port_metric(self):
        """Test set_performance_configuration invalid port metric."""
        cinder_conf = deepcopy(self.reference_cinder_conf)
        cinder_conf.port_load_metric = 'InvalidMetric'
        rest.PowerMaxRest._establish_rest_session = mock.Mock(
            return_value=tpfo.FakeRequestsSession())
        temp_driver = iscsi.PowerMaxISCSIDriver(configuration=cinder_conf)
        self.assertEqual(self.reference_perf_conf,
                         temp_driver.performance.config)

    def test_get_array_registration_details(self):
        """Test get_array_registration_details."""
        p_reg, rt_reg, c_int = self.performance.get_array_registration_details(
            self.data.array)
        self.assertEqual((True, True, 5), (p_reg, rt_reg, c_int))

    def test_get_array_performance_keys(self):
        """Test get_array_performance_keys."""
        f_date, l_date = self.performance.get_array_performance_keys(
            self.data.array)
        self.assertEqual(self.data.f_date_a, f_date)
        self.assertEqual(self.data.l_date, l_date)

    def test_get_look_back_window_interval_timestamp(self):
        """Test _get_look_back_window_interval_timestamp."""
        self.assertEqual(
            self.data.l_date - (utils.ONE_MINUTE * 10),
            self.performance._get_look_back_window_interval_timestamp(
                self.data.l_date, 10))

    def test_process_load(self):
        """Test _process_load to calculate average of all intervals."""
        performance_data = self.data.dummy_performance_data
        perf_metrics = performance_data['resultList']['result']
        metric = self.data.perf_pb_metric
        ref_total = 0
        for interval in perf_metrics:
            ref_total += interval.get(metric)
        ref_avg = ref_total / len(perf_metrics)
        avg, total, count = self.performance._process_load(
            performance_data, metric)
        self.assertEqual(avg, ref_avg)
        self.assertEqual(total, ref_total)
        self.assertEqual(count, len(perf_metrics))

    def test_get_port_group_performance_stats(self):
        """Test _get_port_group_performance_stats."""
        array_id = self.data.array
        port_group_id = self.data.port_group_name_i
        f_date = self.data.f_date_a
        l_date = self.data.l_date
        metric = self.data.perf_pb_metric
        data_format = self.data.perf_df_avg
        avg, total, count = self.performance._get_port_group_performance_stats(
            array_id, port_group_id, f_date, l_date, metric, data_format)
        self.assertTrue(avg > 0)
        self.assertIsInstance(avg, float)
        self.assertTrue(total > 0)
        self.assertIsInstance(total, float)
        self.assertTrue(count > 0)
        self.assertIsInstance(count, int)

    def test_get_port_performance_stats_diagnostic(self):
        """Test _get_port_performance_stats diagnostic."""
        array_id = self.data.array
        dir_id = self.data.iscsi_dir
        port_id = self.data.iscsi_port
        f_date = self.data.f_date_a
        l_date = self.data.l_date
        metric = self.data.perf_pb_metric
        data_format = self.data.perf_df_avg
        res_type = 'diagnostic'
        ref_target_uri = '/performance/FEPort/metrics'
        ref_resource = '%(res)s Port performance metrics' % {'res': res_type}
        ref_request_body = {
            utils.SYMM_ID: array_id, utils.DIR_ID: dir_id,
            utils.PORT_ID: port_id, utils.S_DATE: f_date, utils.E_DATE: l_date,
            utils.DATA_FORMAT: data_format, utils.METRICS: [metric]}
        with mock.patch.object(
                self.rest, 'post_request',
                side_effect=self.rest.post_request) as mck_post:
            avg, total, count = self.performance._get_port_performance_stats(
                array_id, dir_id, port_id, f_date, l_date, metric, data_format,
                real_time=False)
            mck_post.assert_called_once_with(
                ref_target_uri, ref_resource, ref_request_body)
            self.assertTrue(avg > 0)
            self.assertIsInstance(avg, float)
            self.assertTrue(total > 0)
            self.assertIsInstance(total, float)
            self.assertTrue(count > 0)
            self.assertIsInstance(count, int)

    def test_get_port_performance_stats_real_time(self):
        """Test _get_port_performance_stats real-time."""
        array_id = self.data.array
        dir_id = self.data.iscsi_dir
        port_id = self.data.iscsi_port
        f_date = self.data.f_date_a
        l_date = self.data.l_date
        metric = self.data.perf_pb_metric
        res_type = 'real-time'
        ref_target_uri = '/performance/realtime/metrics'
        ref_resource = '%(res)s Port performance metrics' % {'res': res_type}
        ref_request_body = {
            utils.SYMM_ID: array_id,
            utils.INST_ID: self.data.iscsi_dir_port,
            utils.S_DATE: f_date, utils.E_DATE: l_date,
            utils.CAT: utils.FE_PORT_RT, utils.METRICS: [metric]}
        with mock.patch.object(
                self.rest, 'post_request',
                side_effect=self.rest.post_request) as mck_post:
            avg, total, count = self.performance._get_port_performance_stats(
                array_id, dir_id, port_id, f_date, l_date, metric,
                real_time=True)
            mck_post.assert_called_once_with(
                ref_target_uri, ref_resource, ref_request_body)
            self.assertTrue(avg > 0)
            self.assertIsInstance(avg, float)
            self.assertTrue(total > 0)
            self.assertIsInstance(total, float)
            self.assertTrue(count > 0)
            self.assertIsInstance(count, int)

    def test_process_port_group_load_min(self):
        """Test process_port_group_load min load."""
        array_id = self.data.array
        port_groups = self.data.perf_port_groups
        avg, metric, port_group = self.performance.process_port_group_load(
            array_id, port_groups)
        self.assertTrue(avg > 0)
        self.assertIsInstance(avg, float)
        self.assertEqual(metric,
                         self.performance.config.get('port_group_metric'))
        self.assertIn(port_group, port_groups)

    def test_process_port_group_load_max(self):
        """Test process_port_group_load max load."""
        array_id = self.data.array
        port_groups = self.data.perf_port_groups
        avg, metric, port_group = self.performance.process_port_group_load(
            array_id, port_groups, max_load=True)
        self.assertTrue(abs(avg) > 0)
        self.assertIsInstance(avg, float)
        self.assertEqual(metric,
                         self.performance.config.get('port_group_metric'))
        self.assertIn(port_group, port_groups)

    def test_process_port_load_real_time_min(self):
        """Test process_port_load min load real-time."""
        array_id = self.data.array
        ports = self.data.perf_ports
        avg, metric, port = self.performance.process_port_group_load(
            array_id, ports)
        self.assertTrue(avg > 0)
        self.assertIsInstance(avg, float)
        self.assertEqual(metric,
                         self.performance.config.get('port_group_metric'))
        self.assertIn(port, ports)

    def test_process_port_load_real_time_max(self):
        """Test process_port_load max load real-time."""
        array_id = self.data.array
        ports = self.data.perf_ports
        avg, metric, port = self.performance.process_port_group_load(
            array_id, ports, max_load=True)
        self.assertTrue(abs(avg) > 0)
        self.assertIsInstance(avg, float)
        self.assertEqual(metric,
                         self.performance.config.get('port_group_metric'))
        self.assertIn(port, ports)

    def test_process_port_load_diagnostic_min(self):
        """Test process_port_load min load real-time."""
        array_id = self.data.array
        ports = self.data.perf_ports
        self.performance.config['load_balance_rt'] = False
        avg, metric, port = self.performance.process_port_group_load(
            array_id, ports)
        self.assertTrue(avg > 0)
        self.assertIsInstance(avg, float)
        self.assertEqual(metric,
                         self.performance.config.get('port_group_metric'))
        self.assertIn(port, ports)

    def test_process_port_load_diagnostic_max(self):
        """Test process_port_load min load real-time."""
        array_id = self.data.array
        ports = self.data.perf_ports
        self.performance.config['load_balance_rt'] = False
        avg, metric, port = self.performance.process_port_group_load(
            array_id, ports, max_load=True)
        self.assertTrue(abs(avg) > 0)
        self.assertIsInstance(avg, float)
        self.assertEqual(metric,
                         self.performance.config.get('port_group_metric'))
        self.assertIn(port, ports)
