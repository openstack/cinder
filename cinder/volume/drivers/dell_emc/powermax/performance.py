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

from heapq import heappop
from heapq import heappush
import time

from oslo_log import log as logging

from cinder.volume.drivers.dell_emc.powermax import utils


LOG = logging.getLogger(__name__)


class PowerMaxPerformance(object):
    """Performance Class for Dell EMC PowerMax volume drivers.

    It supports VMAX 3, All Flash and PowerMax arrays.
    """

    def __init__(self, rest, performance_config):
        self.rest = rest
        self.config = performance_config

    def set_performance_configuration(self, array_id, cinder_conf):
        """Set the performance configuration if details present in cinder.conf.

        :param array_id: the array serial number -- str
        :param cinder_conf: cinder configuration options -- dict
        """
        # Get performance registration, real-time registration, and collection
        # interval information for PowerMax array
        p_reg, rt_reg, c_int = self.get_array_registration_details(array_id)

        # Get load balance settings from cinder backend configuration
        lb_enabled = cinder_conf.safe_get(utils.LOAD_BALANCE)
        rt_enabled = cinder_conf.safe_get(utils.LOAD_BALANCE_RT)

        # Real-time
        if rt_enabled and not rt_reg:
            LOG.warning(
                "Real-time load balancing is enabled but array %(arr)s is not "
                "registered for real-time performance metrics collection. "
                "Diagnostic performance metrics will be used instead.",
                {'arr': array_id})
            rt_enabled = False

        # Load balancing enabled but array not registered for perf metrics
        if (lb_enabled or rt_enabled) and not p_reg:
            LOG.warning(
                "Load balancing is enabled but array %(arr)s is not "
                "registered for performance metrics collection. Reverting to "
                "default random Port and Port Group selection",
                {'arr': array_id})
            return {'load_balance': False}

        data_format = cinder_conf.safe_get(utils.PERF_DATA_FORMAT)
        if data_format.lower() not in ['average', 'avg', 'maximum', 'max']:
            LOG.warning("Incorrect data format '%(df)s', reverting to "
                        "default value 'Average'.", {'df': data_format})
            data_format = 'Average'

        if data_format.lower() in ['average', 'avg']:
            data_format = 'Average'
        elif data_format.lower() in ['maximum', 'max']:
            data_format = 'Maximum'

        # Get diagnostic metrics look back window
        lb_diagnostic = cinder_conf.safe_get(utils.LOAD_LOOKBACK)
        if not lb_diagnostic:
            LOG.warning(
                "Diagnostic look back window not set in cinder.conf, "
                "reverting to default value of 60 for most recent hour of "
                "metrics.")
            lb_diagnostic = 60
        elif lb_diagnostic < 0 or lb_diagnostic > 1440:
            LOG.warning(
                "Diagnostic look back window '%(lb)s' is not within the "
                "minimum and maximum range 0-1440, reverting to default "
                "value of 60 for most recent hour of metrics.", {
                    'lb': lb_diagnostic})
            lb_diagnostic = 60

        # Get real-time metrics look back window
        lb_real_time = cinder_conf.safe_get(utils.LOAD_LOOKBACK_RT)
        if rt_enabled:
            if not lb_real_time:
                LOG.warning(
                    "Real-time look back window not set in cinder.conf, "
                    "reverting to default value of 1 for for most recent "
                    "minute of metrics.")
                lb_real_time = 1
            elif lb_real_time < 1 or lb_real_time > 60:
                LOG.warning(
                    "Real-time look back window '%(lb)s' is not within the "
                    "minimum and maximum range 1-60, reverting to default "
                    "value of 1 for for most recent minute of metrics.", {
                        'lb': lb_real_time})
                lb_real_time = 1

        # Get Port Group metric for load calculation
        pg_metric = cinder_conf.safe_get(utils.PORT_GROUP_LOAD_METRIC)
        if not pg_metric:
            LOG.warning(
                "Port Group performance metric not set in cinder.conf, "
                "reverting to default metric 'PercentBusy'.")
            pg_metric = 'PercentBusy'
        elif pg_metric not in utils.PG_METRICS:
            LOG.warning(
                "Port Group performance metric selected for load "
                "balancing '%(pg_met)s' is not valid, reverting to "
                "default metric 'PercentBusy'.", {
                    'pg_met': pg_metric})
            pg_metric = 'PercentBusy'

        # Get Port metric for load calculation
        port_metric = cinder_conf.safe_get(utils.PORT_LOAD_METRIC)
        valid_port_metrics = (
            utils.PORT_RT_METRICS if rt_enabled else utils.PORT_METRICS)
        if not port_metric:
            LOG.warning(
                "Port performance metric not set in cinder.conf, "
                "reverting to default metric 'PercentBusy'.")
            port_metric = 'PercentBusy'
        elif port_metric not in valid_port_metrics:
            LOG.warning(
                "Port performance metric selected for load balancing "
                "'%(port_met)s' is not valid, reverting to default metric "
                "'PercentBusy'.", {'port_met': port_metric})
            port_metric = 'PercentBusy'

        self.config = {
            'load_balance': lb_enabled, 'load_balance_rt': rt_enabled,
            'perf_registered': p_reg, 'rt_registered': rt_reg,
            'collection_interval': c_int, 'data_format': data_format,
            'look_back': lb_diagnostic, 'look_back_rt': lb_real_time,
            'port_group_metric': pg_metric, 'port_metric': port_metric}

    def get_array_registration_details(self, array_id):
        """Get array performance registration details.

        :param array_id: the array serial number -- str
        :returns: performance registered, real-time registered,
                  collection interval -- bool, bool, int
        """
        LOG.info("Retrieving array %(arr)s performance registration details.",
                 {'arr': array_id})

        array_reg_uri = self.rest.build_uri(
            category=utils.PERFORMANCE, resource_level=utils.ARRAY_PERF,
            resource_type=utils.REG_DETAILS, resource_type_id=array_id,
            no_version=True)
        reg_details = self.rest.get_request(
            target_uri=array_reg_uri,
            resource_type='Array registration details')

        array_reg_info = reg_details.get(utils.REG_DETAILS_INFO)[0]
        perf_registered = array_reg_info.get(utils.DIAGNOSTIC)
        real_time_registered = array_reg_info.get(utils.REAL_TIME)
        collection_interval = array_reg_info.get(utils.COLLECTION_INT)

        return perf_registered, real_time_registered, collection_interval

    def get_array_performance_keys(self, array_id):
        """Get array performance keys (first and last available timestamps).

        :param array_id: the array serial number
        :returns: first date, last date -- int, int
        """
        LOG.debug("Retrieving array %(arr)s performance keys.",
                  {'arr': array_id})

        array_keys_uri = self.rest.build_uri(
            category=utils.PERFORMANCE, resource_level=utils.ARRAY_PERF,
            resource_type=utils.KEYS, no_version=True)

        array_keys = self.rest.get_request(
            target_uri=array_keys_uri, resource_type='Array performance keys')

        env_symm_info = array_keys.get(utils.ARRAY_INFO)
        f_date, l_date = None, None
        for symm in env_symm_info:
            if symm.get(utils.SYMM_ID) == array_id:
                f_date, l_date = symm.get(utils.F_DATE), symm.get(utils.L_DATE)

        return f_date, l_date

    @staticmethod
    def _get_look_back_window_interval_timestamp(l_date, lb_window):
        """Get first date value when calculated from last date and window.

        :param l_date: the last (most recent) timestamp -- int
        :param lb_window: the look back window in minutes -- int
        :returns: the first timestamp -- int
        """
        return l_date - (utils.ONE_MINUTE * lb_window)

    @staticmethod
    def _process_load(performance_data, metric):
        """Process the load for a given performance response, return average.

        :param performance_data: raw performance data from REST API -- dict
        :param metric: performance metric in use -- str
        :returns: range average, range total, interval count -- float, int, int
        """
        data = performance_data.get(utils.RESULT_LIST)
        result = data.get(utils.RESULT)

        total = 0
        for timestamp in result:
            total += timestamp.get(metric)

        return total / len(result), total, len(result)

    def _get_port_group_performance_stats(
            self, array_id, port_group_id, f_date, l_date, metric,
            data_format):
        """Get performance data for a given port group and performance metric.

        :param array_id: the array serial number -- str
        :param port_group_id: the port group id -- str
        :param f_date: first date for stats -- int
        :param l_date: last date for stats -- int
        :param metric: performance metric -- str
        :param data_format: performance data format -- str
        :returns: range average, range total, interval count -- float, float,
                                                                int
        """
        request_body = {
            utils.SYMM_ID: array_id, utils.PORT_GROUP_ID: port_group_id,
            utils.S_DATE: f_date, utils.E_DATE: l_date,
            utils.DATA_FORMAT: data_format, utils.METRICS: [metric]}

        port_group_uri = self.rest.build_uri(
            category=utils.PERFORMANCE, resource_level=utils.PORT_GROUP,
            resource_type=utils.METRICS, no_version=True)

        result = self.rest.post_request(
            port_group_uri, 'Port Group performance metrics',
            request_body)

        return self._process_load(result, metric)

    def _get_port_performance_stats(
            self, array_id, director_id, port_id, f_date, l_date, metric,
            data_format=None, real_time=False):
        """Get performance data for a given port and performance metric.

        :param array_id: the array serial number -- str
        :param director_id: the director id -- str
        :param port_id: the port id -- str
        :param f_date: first date for stats -- int
        :param l_date: last date for stats -- int
        :param metric: performance metric -- str
        :param data_format: performance data format -- str
        :param real_time: if metrics are real-time -- bool
        :returns: range average, range total, interval count -- float, float,
                                                                int
        """
        if real_time:
            target_uri = self.rest.build_uri(
                category=utils.PERFORMANCE, resource_level=utils.REAL_TIME,
                resource_type=utils.METRICS, no_version=True)
            res_type = 'real-time'
            dir_port = ('%(dir)s:%(port)s' % {'dir': director_id,
                                              'port': port_id})
            request_body = {
                utils.SYMM_ID: array_id, utils.INST_ID: dir_port,
                utils.S_DATE: f_date, utils.E_DATE: l_date,
                utils.CAT: utils.FE_PORT_RT, utils.METRICS: [metric]}

        else:
            target_uri = self.rest.build_uri(
                category=utils.PERFORMANCE, resource_level=utils.FE_PORT_DIAG,
                resource_type=utils.METRICS, no_version=True)
            res_type = 'diagnostic'
            request_body = {
                utils.SYMM_ID: array_id,
                utils.DIR_ID: director_id, utils.PORT_ID: port_id,
                utils.S_DATE: f_date, utils.E_DATE: l_date,
                utils.DATA_FORMAT: data_format, utils.METRICS: [metric]}

        resource = '%(res)s Port performance metrics' % {'res': res_type}
        result = self.rest.post_request(
            target_uri, resource, request_body)

        return self._process_load(result, metric)

    def process_port_group_load(
            self, array_id, port_groups, max_load=False):
        """Calculate the load for one or more port groups.

        :param array_id: the array serial number -- str
        :param port_groups: port group names -- list
        :param max_load: if max load port group should be returned -- bool
        :returns: low/max avg, metric, port group -- tuple(float, str, str)
        """
        LOG.info("Calculating array %(arr)s load for Port Groups %(pg)s.",
                 {'arr': array_id, 'pg': port_groups})

        data_format = self.config.get('data_format')
        lb_window = self.config.get('look_back')
        pg_metric = self.config.get('port_group_metric')

        __, l_date = self.get_array_performance_keys(array_id)
        f_date = self._get_look_back_window_interval_timestamp(
            l_date, lb_window)

        heap_low, heap_high = [], []

        start_time = time.time()
        for pg in port_groups:
            avg, total, cnt = self._get_port_group_performance_stats(
                array_id, pg, f_date, l_date, pg_metric, data_format)
            LOG.debug(
                "Port Group '%(pg)s' %(df)s %(met)s load for %(interval)s min "
                "interval: %(avg)s",
                {'pg': pg, 'df': data_format, 'met': pg_metric,
                 'interval': lb_window, 'avg': avg})

            # Add PG average to lowest load heap
            heappush(heap_low, (avg, pg_metric, pg))
            # Add inverse PG average to highest load heap
            heappush(heap_high, (-avg, pg_metric, pg))

        LOG.debug("Time taken to analyse Port Group performance: %(t)ss",
                  {'t': time.time() - start_time})

        return heappop(heap_high) if max_load else heappop(heap_low)

    def process_port_load(self, array_id, ports, max_load=False):
        """Calculate the load for one or more ports.

        :param array_id: the array serial number -- str
        :param ports: physical dir:port names -- list
        :param max_load: if max load port should be returned -- bool
        :returns: low/max avg, metric, port -- tuple(float, str, str)
        """
        LOG.info("Calculating array %(arr)s load for Ports %(port)s.",
                 {'arr': array_id, 'port': ports})

        rt_enabled = self.config.get('load_balance_rt')
        rt_registered = self.config.get('rt_registered')

        if rt_enabled and rt_registered:
            real_time, data_format = True, None
            lb_window = self.config.get('look_back_rt')
        else:
            real_time, data_format = False, self.config.get('data_format')
            lb_window = self.config.get('look_back')

        port_metric = self.config.get('port_metric')
        __, l_date = self.get_array_performance_keys(array_id)
        f_date = self._get_look_back_window_interval_timestamp(
            l_date, lb_window)

        heap_low, heap_high = [], []
        start_time = time.time()
        for port in ports:
            dir_id = port.split(':')[0]
            port_no = port.split(':')[1]

            avg, total, cnt = self._get_port_performance_stats(
                array_id, dir_id, port_no, f_date, l_date, port_metric,
                data_format, real_time=real_time)
            LOG.debug(
                "Port '%(dir)s:%(port)s' %(df)s %(met)s load for %(int)s min "
                "interval: %(avg)s",
                {'dir': dir_id, 'port': port_no,
                 'df': data_format if data_format else '',
                 'met': port_metric, 'int': lb_window, 'avg': avg})

            # Add PG average to lowest load heap
            heappush(heap_low, (avg, port_metric, port))
            # Add inverse PG average to highest load heap
            heappush(heap_high, (-avg, port_metric, port))

        LOG.debug("Time taken to analyse Port Group performance: %(t)ss",
                  {'t': time.time() - start_time})

        return heappop(heap_high) if max_load else heappop(heap_low)
