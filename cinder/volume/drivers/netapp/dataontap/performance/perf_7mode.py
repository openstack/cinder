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
"""
Performance metrics functions and cache for NetApp 7-mode Data ONTAP systems.
"""

from oslo_log import log as logging

from cinder.volume.drivers.netapp.dataontap.client import api as netapp_api
from cinder.volume.drivers.netapp.dataontap.performance import perf_base


LOG = logging.getLogger(__name__)


class Performance7modeLibrary(perf_base.PerformanceLibrary):

    def __init__(self, zapi_client):
        super(Performance7modeLibrary, self).__init__(zapi_client)

        self.performance_counters = []
        self.utilization = perf_base.DEFAULT_UTILIZATION
        self.node_name = self.zapi_client.get_system_name()

    def _init_counter_info(self):
        """Set a few counter names based on Data ONTAP version."""

        super(Performance7modeLibrary, self)._init_counter_info()

        if self.zapi_client.features.SYSTEM_METRICS:
            self.system_object_name = 'system'
            try:
                self.avg_processor_busy_base_counter_name = (
                    self._get_base_counter_name('system',
                                                'avg_processor_busy'))
            except netapp_api.NaApiError:
                self.avg_processor_busy_base_counter_name = 'cpu_elapsed_time1'
                LOG.exception('Could not get performance base counter '
                              'name. Performance-based scheduler '
                              'functions may not be available.')

    def update_performance_cache(self):
        """Called periodically to update node utilization metrics."""

        # Nothing to do on older systems
        if not self.zapi_client.features.SYSTEM_METRICS:
            return

        # Get new performance counters and save only the last 10
        counters = self._get_node_utilization_counters()
        if not counters:
            return

        self.performance_counters.append(counters)
        self.performance_counters = self.performance_counters[-10:]

        # Update utilization using newest & oldest sample
        if len(self.performance_counters) < 2:
            self.utilization = perf_base.DEFAULT_UTILIZATION
        else:
            self.utilization = self._get_node_utilization(
                self.performance_counters[0], self.performance_counters[-1],
                self.node_name)

    def get_node_utilization(self):
        """Get the node utilization, if available."""

        return self.utilization

    def _get_node_utilization_counters(self):
        """Get all performance counters for calculating node utilization."""

        try:
            return (self._get_node_utilization_system_counters() +
                    self._get_node_utilization_wafl_counters() +
                    self._get_node_utilization_processor_counters())
        except netapp_api.NaApiError:
            LOG.exception('Could not get utilization counters from node '
                          '%s', self.node_name)
            return None

    def _get_node_utilization_system_counters(self):
        """Get the system counters for calculating node utilization."""

        system_instance_names = (
            self.zapi_client.get_performance_instance_names(
                self.system_object_name))

        system_counter_names = [
            'avg_processor_busy',
            self.avg_processor_busy_base_counter_name,
        ]
        if 'cpu_elapsed_time1' in system_counter_names:
            system_counter_names.append('cpu_elapsed_time')

        system_counters = self.zapi_client.get_performance_counters(
            self.system_object_name, system_instance_names,
            system_counter_names)

        return system_counters

    def _get_node_utilization_wafl_counters(self):
        """Get the WAFL counters for calculating node utilization."""

        wafl_instance_names = self.zapi_client.get_performance_instance_names(
            'wafl')

        wafl_counter_names = ['total_cp_msecs', 'cp_phase_times']
        wafl_counters = self.zapi_client.get_performance_counters(
            'wafl', wafl_instance_names, wafl_counter_names)

        # Expand array data so we can use wafl:cp_phase_times[P2_FLUSH]
        for counter in wafl_counters:
            if 'cp_phase_times' in counter:
                self._expand_performance_array(
                    'wafl', 'cp_phase_times', counter)

        return wafl_counters

    def _get_node_utilization_processor_counters(self):
        """Get the processor counters for calculating node utilization."""

        processor_instance_names = (
            self.zapi_client.get_performance_instance_names('processor'))

        processor_counter_names = ['domain_busy', 'processor_elapsed_time']
        processor_counters = self.zapi_client.get_performance_counters(
            'processor', processor_instance_names, processor_counter_names)

        # Expand array data so we can use processor:domain_busy[kahuna]
        for counter in processor_counters:
            if 'domain_busy' in counter:
                self._expand_performance_array(
                    'processor', 'domain_busy', counter)

        return processor_counters
