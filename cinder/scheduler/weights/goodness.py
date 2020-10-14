# Copyright (C) 2014 Hewlett-Packard Development Company, L.P.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from oslo_log import log as logging

from cinder.scheduler.evaluator import evaluator
from cinder.scheduler import weights


LOG = logging.getLogger(__name__)


class GoodnessWeigher(weights.BaseHostWeigher):
    """Goodness Weigher.  Assign weights based on a host's goodness function.

    Goodness rating is the following:

    .. code-block:: none

          0 -- host is a poor choice
          .
          .
         50 -- host is a good choice
          .
          .
        100 -- host is a perfect choice

    """

    def _weigh_object(self, host_state, weight_properties):
        """Determine host's goodness rating based on a goodness_function."""
        stats = self._generate_stats(host_state, weight_properties)
        LOG.debug("Checking host '%s'", stats['host_stats']['host'])
        result = self._check_goodness_function(stats)
        LOG.debug("Goodness weight for %(host)s: %(res)s",
                  {'res': result, 'host': stats['host_stats']['host']})

        return result

    def _check_goodness_function(self, stats):
        """Gets a host's goodness rating based on its goodness function."""

        goodness_rating = 0

        if stats['goodness_function'] is None:
            LOG.warning("Goodness function not set :: defaulting to "
                        "minimal goodness rating of 0")
        else:
            try:
                goodness_result = self._run_evaluator(
                    stats['goodness_function'],
                    stats)
            except Exception as ex:
                LOG.warning("Error in goodness_function function "
                            "'%(function)s' : '%(error)s' :: Defaulting "
                            "to a goodness of 0",
                            {'function': stats['goodness_function'],
                             'error': ex, })
                return goodness_rating

            if type(goodness_result) is bool:
                if goodness_result:
                    goodness_rating = 100
            elif goodness_result < 0 or goodness_result > 100:
                LOG.warning("Invalid goodness result.  Result must be "
                            "between 0 and 100.  Result generated: '%s' "
                            ":: Defaulting to a goodness of 0",
                            goodness_result)
            else:
                goodness_rating = goodness_result

        return goodness_rating

    def _run_evaluator(self, func, stats):
        """Evaluates a given function using the provided available stats."""
        host_stats = stats['host_stats']
        host_caps = stats['host_caps']
        extra_specs = stats['extra_specs']
        qos_specs = stats['qos_specs']
        volume_stats = stats['volume_stats']

        result = evaluator.evaluate(
            func,
            extra=extra_specs,
            stats=host_stats,
            capabilities=host_caps,
            volume=volume_stats,
            qos=qos_specs)

        return result

    def _generate_stats(self, host_state, weight_properties):
        """Generates statistics from host and volume data."""

        host_stats = {
            'host': host_state.host,
            'volume_backend_name': host_state.volume_backend_name,
            'vendor_name': host_state.vendor_name,
            'driver_version': host_state.driver_version,
            'storage_protocol': host_state.storage_protocol,
            'QoS_support': host_state.QoS_support,
            'total_capacity_gb': host_state.total_capacity_gb,
            'allocated_capacity_gb': host_state.allocated_capacity_gb,
            'free_capacity_gb': host_state.free_capacity_gb,
            'reserved_percentage': host_state.reserved_percentage,
            'updated': host_state.updated,
        }

        host_caps = host_state.capabilities

        goodness_function = None

        if ('goodness_function' in host_caps and
                host_caps['goodness_function'] is not None):
            goodness_function = str(host_caps['goodness_function'])

        qos_specs = weight_properties.get('qos_specs', {}) or {}

        volume_type = weight_properties.get('volume_type', {}) or {}
        extra_specs = volume_type.get('extra_specs', {})

        request_spec = weight_properties.get('request_spec', {}) or {}
        volume_stats = request_spec.get('volume_properties', {})

        stats = {
            'host_stats': host_stats,
            'host_caps': host_caps,
            'extra_specs': extra_specs,
            'qos_specs': qos_specs,
            'volume_stats': volume_stats,
            'volume_type': volume_type,
            'goodness_function': goodness_function,
        }

        return stats
