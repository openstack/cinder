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
Performance metrics functions and cache for NetApp systems.
"""

from oslo_log import log as logging

from cinder import exception
from cinder.i18n import _


LOG = logging.getLogger(__name__)
DEFAULT_UTILIZATION = 50


class PerformanceLibrary(object):

    def __init__(self, zapi_client):

        self.zapi_client = zapi_client
        self._init_counter_info()

    def _init_counter_info(self):
        """Set a few counter names based on Data ONTAP version."""

        self.system_object_name = None
        self.avg_processor_busy_base_counter_name = None

    def _get_node_utilization(self, counters_t1, counters_t2, node_name):
        """Get node utilization from two sets of performance counters."""

        try:
            # Time spent in the single-threaded Kahuna domain
            kahuna_percent = self._get_kahuna_utilization(counters_t1,
                                                          counters_t2)

            # If Kahuna is using >60% of the CPU, the controller is fully busy
            if kahuna_percent > 60:
                return 100.0

            # Average CPU busyness across all processors
            avg_cpu_percent = 100.0 * self._get_average_cpu_utilization(
                counters_t1, counters_t2)

            # Total Consistency Point (CP) time
            total_cp_time_msec = self._get_total_consistency_point_time(
                counters_t1, counters_t2)

            # Time spent in CP Phase 2 (buffer flush)
            p2_flush_time_msec = self._get_consistency_point_p2_flush_time(
                counters_t1, counters_t2)

            # Wall-clock time between the two counter sets
            poll_time_msec = self._get_total_time(counters_t1,
                                                  counters_t2,
                                                  'total_cp_msecs')

            # If two polls happened in quick succession, use CPU utilization
            if total_cp_time_msec == 0 or poll_time_msec == 0:
                return max(min(100.0, avg_cpu_percent), 0)

            # Adjusted Consistency Point time
            adjusted_cp_time_msec = self._get_adjusted_consistency_point_time(
                total_cp_time_msec, p2_flush_time_msec)
            adjusted_cp_percent = (100.0 *
                                   adjusted_cp_time_msec / poll_time_msec)

            # Utilization is the greater of CPU busyness & CP time
            node_utilization = max(avg_cpu_percent, adjusted_cp_percent)
            return max(min(100.0, node_utilization), 0)

        except Exception:
            LOG.exception('Could not calculate node utilization for '
                          'node %s.', node_name)
            return DEFAULT_UTILIZATION

    def _get_kahuna_utilization(self, counters_t1, counters_t2):
        """Get time spent in the single-threaded Kahuna domain."""

        # Note(cknight): Because Kahuna is single-threaded, running only on
        # one CPU at a time, we can safely sum the Kahuna CPU usage
        # percentages across all processors in a node.
        return sum(self._get_performance_counter_average_multi_instance(
            counters_t1, counters_t2, 'domain_busy:kahuna',
            'processor_elapsed_time')) * 100.0

    def _get_average_cpu_utilization(self, counters_t1, counters_t2):
        """Get average CPU busyness across all processors."""

        return self._get_performance_counter_average(
            counters_t1, counters_t2, 'avg_processor_busy',
            self.avg_processor_busy_base_counter_name)

    def _get_total_consistency_point_time(self, counters_t1, counters_t2):
        """Get time spent in Consistency Points in msecs."""

        return float(self._get_performance_counter_delta(
            counters_t1, counters_t2, 'total_cp_msecs'))

    def _get_consistency_point_p2_flush_time(self, counters_t1, counters_t2):
        """Get time spent in CP Phase 2 (buffer flush) in msecs."""

        return float(self._get_performance_counter_delta(
            counters_t1, counters_t2, 'cp_phase_times:p2_flush'))

    def _get_total_time(self, counters_t1, counters_t2, counter_name):
        """Get wall clock time between two successive counters in msecs."""

        timestamp_t1 = float(self._find_performance_counter_timestamp(
            counters_t1, counter_name))
        timestamp_t2 = float(self._find_performance_counter_timestamp(
            counters_t2, counter_name))
        return (timestamp_t2 - timestamp_t1) * 1000.0

    def _get_adjusted_consistency_point_time(self, total_cp_time,
                                             p2_flush_time):
        """Get adjusted CP time by limiting CP phase 2 flush time to 20%."""

        return (total_cp_time - p2_flush_time) * 1.20

    def _get_performance_counter_delta(self, counters_t1, counters_t2,
                                       counter_name):
        """Calculate a delta value from two performance counters."""

        counter_t1 = int(
            self._find_performance_counter_value(counters_t1, counter_name))
        counter_t2 = int(
            self._find_performance_counter_value(counters_t2, counter_name))

        return counter_t2 - counter_t1

    def _get_performance_counter_average(self, counters_t1, counters_t2,
                                         counter_name, base_counter_name,
                                         instance_name=None):
        """Calculate an average value from two performance counters."""

        counter_t1 = float(self._find_performance_counter_value(
            counters_t1, counter_name, instance_name))
        counter_t2 = float(self._find_performance_counter_value(
            counters_t2, counter_name, instance_name))
        base_counter_t1 = float(self._find_performance_counter_value(
            counters_t1, base_counter_name, instance_name))
        base_counter_t2 = float(self._find_performance_counter_value(
            counters_t2, base_counter_name, instance_name))

        return (counter_t2 - counter_t1) / (base_counter_t2 - base_counter_t1)

    def _get_performance_counter_average_multi_instance(self, counters_t1,
                                                        counters_t2,
                                                        counter_name,
                                                        base_counter_name):
        """Calculate an average value from multiple counter instances."""

        averages = []
        instance_names = []
        for counter in counters_t1:
            if counter_name in counter:
                instance_names.append(counter['instance-name'])

        for instance_name in instance_names:
            average = self._get_performance_counter_average(
                counters_t1, counters_t2, counter_name, base_counter_name,
                instance_name)
            averages.append(average)

        return averages

    def _find_performance_counter_value(self, counters, counter_name,
                                        instance_name=None):
        """Given a counter set, return the value of a named instance."""

        for counter in counters:
            if counter_name in counter:
                if (instance_name is None
                        or counter['instance-name'] == instance_name):
                    return counter[counter_name]
        else:
            raise exception.NotFound(_('Counter %s not found') % counter_name)

    def _find_performance_counter_timestamp(self, counters, counter_name,
                                            instance_name=None):
        """Given a counter set, return the timestamp of a named instance."""

        for counter in counters:
            if counter_name in counter:
                if (instance_name is None
                        or counter['instance-name'] == instance_name):
                    return counter['timestamp']
        else:
            raise exception.NotFound(_('Counter %s not found') % counter_name)

    def _expand_performance_array(self, object_name, counter_name, counter):
        """Get array labels and expand counter data array."""

        # Get array labels for counter value
        counter_info = self.zapi_client.get_performance_counter_info(
            object_name, counter_name)

        array_labels = [counter_name + ':' + label.lower()
                        for label in counter_info['labels']]
        array_values = counter[counter_name].split(',')

        # Combine labels and values, and then mix into existing counter
        array_data = dict(zip(array_labels, array_values))
        counter.update(array_data)

    def _get_base_counter_name(self, object_name, counter_name):
        """Get the name of the base counter for the specified counter."""

        counter_info = self.zapi_client.get_performance_counter_info(
            object_name, counter_name)
        return counter_info['base-counter']
