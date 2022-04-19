# Copyright (c) 2014 Hewlett-Packard Development Company, L.P.
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

from oslo_log import log as logging

from cinder.scheduler.evaluator import evaluator
from cinder.scheduler import filters


LOG = logging.getLogger(__name__)


class DriverFilter(filters.BaseBackendFilter):
    """DriverFilter filters backend based on a 'filter function' and metrics.

    DriverFilter filters based on volume backend's provided 'filter function'
    and metrics.
    """

    def backend_passes(self, backend_state, filter_properties):
        """Determines if a backend has a passing filter_function or not."""
        stats = self._generate_stats(backend_state, filter_properties)

        LOG.debug("Checking backend '%s'",
                  stats[0]['backend_stats']['backend_id'])
        # Run the filter function for all possible storage_protocol values
        # (e.g. FC, fibre_channel) and if any of them passes the filter, then
        # the backend passes.
        result = any(self._check_filter_function(stat) for stat in stats)
        LOG.debug("Result: %s", result)
        LOG.debug("Done checking backend '%s'",
                  stats[0]['backend_stats']['backend_id'])

        return result

    def _check_filter_function(self, stats):
        """Checks if a volume passes a backend's filter function.

           Returns a tuple in the format (filter_passing, filter_invalid).
           Both values are booleans.
        """
        if stats['filter_function'] is None:
            LOG.debug("Filter function not set :: passing backend")
            return True

        try:
            filter_result = self._run_evaluator(stats['filter_function'],
                                                stats)
        except Exception as ex:
            # Warn the admin for now that there is an error in the
            # filter function.
            LOG.warning("Error in filtering function "
                        "'%(function)s' : '%(error)s' :: failing backend",
                        {'function': stats['filter_function'],
                         'error': ex, })
            return False

        return filter_result

    def _run_evaluator(self, func, stats):
        """Evaluates a given function using the provided available stats."""
        backend_stats = stats['backend_stats']
        backend_caps = stats['backend_caps']
        extra_specs = stats['extra_specs']
        qos_specs = stats['qos_specs']
        volume_stats = stats['volume_stats']

        LOG.debug('Running evaluator: extra_specs: %(extra)s\n'
                  'stats: %(stats)s\n'
                  'capabilities: %(capabilities)s\n'
                  'volume: %(volume)s\n'
                  'qos: %(qos)s', {'extra': extra_specs,
                                   'stats': backend_stats,
                                   'capabilities': backend_caps,
                                   'volume': volume_stats,
                                   'qos': qos_specs})

        result = evaluator.evaluate(
            func,
            extra=extra_specs,
            stats=backend_stats,
            capabilities=backend_caps,
            volume=volume_stats,
            qos=qos_specs)

        return result

    def _generate_stats(self, backend_state, filter_properties):
        """Generates statistics from backend and volume data.

        Returns a list where each entry corresponds to a different
        storage_protocol value for those backends that use a storage protocol
        that has variants, but only if the function actually uses the protocol.
        """

        backend_stats = {
            'host': backend_state.host,
            'cluster_name': backend_state.cluster_name,
            'backend_id': backend_state.backend_id,
            'volume_backend_name': backend_state.volume_backend_name,
            'vendor_name': backend_state.vendor_name,
            'driver_version': backend_state.driver_version,
            'storage_protocol': backend_state.storage_protocol,
            'QoS_support': backend_state.QoS_support,
            'total_capacity_gb': backend_state.total_capacity_gb,
            'allocated_capacity_gb': backend_state.allocated_capacity_gb,
            'free_capacity_gb': backend_state.free_capacity_gb,
            'reserved_percentage': backend_state.reserved_percentage,
            'updated': backend_state.updated,
        }

        backend_caps = backend_state.capabilities

        filter_function = None
        uses_protocol = False

        if ('filter_function' in backend_caps and
                backend_caps['filter_function'] is not None):
            filter_function = str(backend_caps['filter_function'])
            uses_protocol = 'storage_protocol' in filter_function

        qos_specs = filter_properties.get('qos_specs', {})

        volume_type = filter_properties.get('volume_type', {})
        extra_specs = volume_type.get('extra_specs', {})

        request_spec = filter_properties.get('request_spec', {})
        volume_stats = request_spec.get('volume_properties', {})

        stats = {
            'backend_stats': backend_stats,
            'backend_caps': backend_caps,
            'extra_specs': extra_specs,
            'qos_specs': qos_specs,
            'volume_stats': volume_stats,
            'volume_type': volume_type,
            'filter_function': filter_function,
        }

        # Only create individual entries for the different protocols variants
        # if the function uses the protocol and there are variants.
        if uses_protocol and isinstance(backend_state.storage_protocol, list):
            result = []
            for protocol in backend_state.storage_protocol:
                new_stats = stats.copy()
                new_stats['backend_stats'] = dict(new_stats['backend_stats'])
                new_stats['backend_stats']['storage_protocol'] = protocol
                new_stats['backend_caps'] = dict(new_stats['backend_caps'])
                new_stats['backend_caps']['storage_protocol'] = protocol
                result.append(new_stats)

        else:
            result = [stats]
        return result
