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
Performance metrics functions and cache for NetApp cDOT systems.
"""

from oslo_log import log as logging

from cinder.volume.drivers.netapp.dataontap.client import api as netapp_api
from cinder.volume.drivers.netapp.dataontap.performance import perf_base


LOG = logging.getLogger(__name__)


class PerformanceCmodeLibrary(perf_base.PerformanceLibrary):

    def __init__(self, zapi_client, use_metrics_based_utilization=False):
        super(PerformanceCmodeLibrary, self).__init__(zapi_client)

        self.performance_counters = {}
        self.pool_utilization = {}
        self.use_metrics_based_utilization = use_metrics_based_utilization
        self._aggr_node_cache = {
            'node_names': set(),
            'aggr_node_map': {},
        }

    def _init_counter_info(self):
        """Set a few counter names based on Data ONTAP version."""

        super(PerformanceCmodeLibrary, self)._init_counter_info()

        try:
            if self.zapi_client.features.SYSTEM_CONSTITUENT_METRICS:
                self.system_object_name = 'system:constituent'
                self.avg_processor_busy_base_counter_name = (
                    self._get_base_counter_name('system:constituent',
                                                'avg_processor_busy'))
            elif self.zapi_client.features.SYSTEM_METRICS:
                self.system_object_name = 'system'
                self.avg_processor_busy_base_counter_name = (
                    self._get_base_counter_name('system',
                                                'avg_processor_busy'))
        except netapp_api.NaApiError:
            if self.zapi_client.features.SYSTEM_CONSTITUENT_METRICS:
                self.avg_processor_busy_base_counter_name = 'cpu_elapsed_time'
            else:
                self.avg_processor_busy_base_counter_name = 'cpu_elapsed_time1'
            LOG.warning('Could not get performance base counter '
                        'name. Performance-based scheduler '
                        'functions may not be available.')

    def update_performance_cache(self, ssc_pools):
        """Called periodically to update per-pool node utilization metrics."""

        # Prefer REST node metrics when enabled and supported by the client.
        if (self.use_metrics_based_utilization and
                self._is_metrics_based_utilization_supported()):
            self._update_performance_cache_from_metrics(ssc_pools)
            return

        # Nothing to do on older systems
        if not (self.zapi_client.features.SYSTEM_METRICS or
                self.zapi_client.features.SYSTEM_CONSTITUENT_METRICS):
            return

        # Get aggregates and nodes for all known pools
        aggr_names = self._get_aggregates_for_pools(ssc_pools)
        node_names, aggr_node_map = self._get_nodes_for_aggregates(aggr_names)

        # Update performance counter cache for each node
        node_utilization = {}
        for node_name in node_names:
            if node_name not in self.performance_counters:
                self.performance_counters[node_name] = []

            # Get new performance counters and save only the last 10
            counters = self._get_node_utilization_counters(node_name)
            if not counters:
                continue

            self.performance_counters[node_name].append(counters)
            self.performance_counters[node_name] = (
                self.performance_counters[node_name][-10:])

            # Update utilization for each node using newest & oldest sample
            counters = self.performance_counters[node_name]
            if len(counters) < 2:
                node_utilization[node_name] = perf_base.DEFAULT_UTILIZATION
            else:
                node_utilization[node_name] = self._get_node_utilization(
                    counters[0], counters[-1], node_name)

        self.pool_utilization = self._map_node_utilization_to_pools(
            ssc_pools, aggr_node_map, node_utilization)

    def get_node_utilization_for_pool(self, pool_name):
        """Get the node utilization for the specified pool, if available."""

        return self.pool_utilization.get(pool_name,
                                         perf_base.DEFAULT_UTILIZATION)

    def _is_metrics_based_utilization_supported(self):
        """True only for a REST client with NODE_METRICS (ONTAP 9.8+)."""
        if not hasattr(self.zapi_client,
                       'get_node_utilization_from_metrics'):
            return False
        try:
            return bool(self.zapi_client.features.NODE_METRICS)
        except AttributeError:
            return False

    def _update_performance_cache_from_metrics(self, ssc_pools):
        """Set per-pool utilization from the REST node metrics endpoint."""
        aggr_names = self._get_aggregates_for_pools(ssc_pools)
        node_names, aggr_node_map = self._get_nodes_for_aggregates(aggr_names)
        LOG.debug('Metrics perf cache: aggr_names=%s node_names=%s',
                  aggr_names, node_names)

        # Read processor_utilization once per node; fall back when missing.
        node_utilization = {}
        for node_name in node_names:
            utilization = self.zapi_client.get_node_utilization_from_metrics(
                node_name)
            if utilization is None:
                utilization = self._get_metrics_fallback_utilization(
                    node_name)
            node_utilization[node_name] = utilization

        self.pool_utilization = self._map_node_utilization_to_pools(
            ssc_pools, aggr_node_map, node_utilization)
        LOG.debug('Metrics perf cache result: pool_utilization=%s',
                  self.pool_utilization)

    def _map_node_utilization_to_pools(self, ssc_pools, aggr_node_map,
                                       node_utilization):
        """Map each pool to its owning node's utilization."""
        pool_utilization = {}
        for pool_name, pool_info in ssc_pools.items():
            aggr_name = pool_info.get('netapp_aggregate', 'unknown')
            if isinstance(aggr_name, list):
                # FlexGroup: average utilization across all resolved nodes.
                values = [
                    node_utilization[aggr_node_map[a]]
                    for a in aggr_name
                    if a in aggr_node_map
                    and aggr_node_map[a] in node_utilization
                ]
                pool_utilization[pool_name] = (
                    sum(values) / len(values) if values
                    else perf_base.DEFAULT_UTILIZATION)
            elif aggr_name is None:
                # ASA r2 pools represent the SVM's disaggregated cluster.
                values = list(node_utilization.values())
                pool_utilization[pool_name] = (
                    sum(values) / len(values) if values
                    else perf_base.DEFAULT_UTILIZATION)
            else:
                node_name = aggr_node_map.get(aggr_name)
                pool_utilization[pool_name] = node_utilization.get(
                    node_name, perf_base.DEFAULT_UTILIZATION)
        return pool_utilization

    def _get_metrics_fallback_utilization(self, node_name):
        """Fall back to the default utilization when metrics are missing."""
        return perf_base.DEFAULT_UTILIZATION

    def _update_for_failover(self, zapi_client, ssc_pools):
        self.zapi_client = zapi_client
        self._aggr_node_cache = {
            'node_names': set(),
            'aggr_node_map': {},
        }
        self.update_performance_cache(ssc_pools)

    def _get_aggregates_for_pools(self, ssc_pools):
        """Get the set of aggregates that contain the specified pools."""
        aggr_names = set()
        svm_aggregates = []
        svm_aggregates_loaded = False
        for pool_name, pool_info in ssc_pools.items():
            aggr = pool_info.get('netapp_aggregate')
            if isinstance(aggr, list):
                aggr_names.update(aggr)  # FlexGroup: include all constituents
            elif aggr is None:
                # ASA r2: pools have no aggregate of their own, so resolve
                # every aggregate mapped to the SVM instead.
                if not svm_aggregates_loaded:
                    get_vserver_aggregates = getattr(
                        self.zapi_client, 'get_vserver_aggregates', None)
                    if callable(get_vserver_aggregates):
                        try:
                            svm_aggregates = get_vserver_aggregates()
                        except Exception:
                            LOG.warning(
                                'Could not resolve SVM aggregates; falling '
                                'back to cached cluster nodes.')
                    svm_aggregates_loaded = True
                aggr_names.update(svm_aggregates or [None])
            else:
                aggr_names.add(aggr)
        return aggr_names

    def _get_nodes_for_aggregates(self, aggr_names):
        """Get the cluster nodes that own the specified aggregates."""

        include_all_nodes = None in aggr_names
        lookup_names = {a for a in aggr_names if a is not None}

        # Only make API call if aggregate names changed
        aggr_node_map = self._aggr_node_cache.get('aggr_node_map')
        aggr_list_cache = set(aggr_node_map.keys()) if aggr_node_map else set()
        if not lookup_names.issubset(aggr_list_cache):
            node_names = set()
            aggr_node_map = {}
            for aggr_name in sorted(lookup_names):
                node_name = self.zapi_client.get_node_for_aggregate(aggr_name)
                if node_name:
                    node_names.add(node_name)
                    aggr_node_map[aggr_name] = node_name
            self._aggr_node_cache['node_names'] = node_names
            self._aggr_node_cache['aggr_node_map'] = aggr_node_map

        node_names = self._aggr_node_cache['node_names']
        aggr_node_map = self._aggr_node_cache['aggr_node_map']

        if include_all_nodes and not node_names:
            # SVM aggregate resolution failed; fall back to every node
            # known to the client so ASA r2 still gets a cluster-wide value.
            node_names = set(getattr(self.zapi_client, '_node_uuid_cache', {}))
            return node_names, aggr_node_map

        return node_names, aggr_node_map

    def _get_node_utilization_counters(self, node_name):
        """Get all performance counters for calculating node utilization."""

        try:
            return (self._get_node_utilization_system_counters(node_name) +
                    self._get_node_utilization_wafl_counters(node_name) +
                    self._get_node_utilization_processor_counters(node_name))
        except netapp_api.NaApiError:
            LOG.exception('Could not get utilization counters from node %s',
                          node_name)
            return None

    def _get_node_utilization_system_counters(self, node_name):
        """Get the system counters for calculating node utilization."""

        system_instance_uuids = (
            self.zapi_client.get_performance_instance_uuids(
                self.system_object_name, node_name))

        system_counter_names = [
            'avg_processor_busy',
            self.avg_processor_busy_base_counter_name,
        ]
        if 'cpu_elapsed_time1' in system_counter_names:
            system_counter_names.append('cpu_elapsed_time')

        system_counters = self.zapi_client.get_performance_counters(
            self.system_object_name, system_instance_uuids,
            system_counter_names)

        return system_counters

    def _get_node_utilization_wafl_counters(self, node_name):
        """Get the WAFL counters for calculating node utilization."""

        wafl_instance_uuids = self.zapi_client.get_performance_instance_uuids(
            'wafl', node_name)

        wafl_counter_names = ['total_cp_msecs', 'cp_phase_times']
        wafl_counters = self.zapi_client.get_performance_counters(
            'wafl', wafl_instance_uuids, wafl_counter_names)

        # Expand array data so we can use wafl:cp_phase_times[P2_FLUSH]
        for counter in wafl_counters:
            if 'cp_phase_times' in counter:
                self._expand_performance_array(
                    'wafl', 'cp_phase_times', counter)

        return wafl_counters

    def _get_node_utilization_processor_counters(self, node_name):
        """Get the processor counters for calculating node utilization."""

        processor_instance_uuids = (
            self.zapi_client.get_performance_instance_uuids('processor',
                                                            node_name))

        processor_counter_names = ['domain_busy', 'processor_elapsed_time']
        processor_counters = self.zapi_client.get_performance_counters(
            'processor', processor_instance_uuids, processor_counter_names)

        # Expand array data so we can use processor:domain_busy[kahuna]
        for counter in processor_counters:
            if 'domain_busy' in counter:
                self._expand_performance_array(
                    'processor', 'domain_busy', counter)

        return processor_counters
