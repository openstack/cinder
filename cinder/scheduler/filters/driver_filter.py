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
import six

from cinder.i18n import _LW
from cinder.openstack.common.scheduler import filters
from cinder.scheduler.evaluator import evaluator


LOG = logging.getLogger(__name__)


class DriverFilter(filters.BaseHostFilter):
    """DriverFilter filters hosts based on a 'filter function' and metrics.

    DriverFilter filters based on volume host's provided 'filter function'
    and metrics.
    """

    def host_passes(self, host_state, filter_properties):
        """Determines whether a host has a passing filter_function or not."""
        stats = self._generate_stats(host_state, filter_properties)

        LOG.debug("Checking host '%s'", stats['host_stats']['host'])
        result = self._check_filter_function(stats)
        LOG.debug("Result: %s", result)
        LOG.debug("Done checking host '%s'", stats['host_stats']['host'])

        return result

    def _check_filter_function(self, stats):
        """Checks if a volume passes a host's filter function.

           Returns a tuple in the format (filter_passing, filter_invalid).
           Both values are booleans.
        """
        if stats['filter_function'] is None:
            LOG.debug("Filter function not set :: passing host")
            return True

        try:
            filter_result = self._run_evaluator(stats['filter_function'],
                                                stats)
        except Exception as ex:
            # Warn the admin for now that there is an error in the
            # filter function.
            LOG.warning(_LW("Error in filtering function "
                            "'%(function)s' : '%(error)s' :: failing host"),
                        {'function': stats['filter_function'],
                         'error': ex, })
            return False

        return filter_result

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

    def _generate_stats(self, host_state, filter_properties):
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

        filter_function = None

        if ('filter_function' in host_caps and
                host_caps['filter_function'] is not None):
            filter_function = six.text_type(host_caps['filter_function'])

        qos_specs = filter_properties.get('qos_specs', {})

        volume_type = filter_properties.get('volume_type', {})
        extra_specs = volume_type.get('extra_specs', {})

        request_spec = filter_properties.get('request_spec', {})
        volume_stats = request_spec.get('volume_properties', {})

        stats = {
            'host_stats': host_stats,
            'host_caps': host_caps,
            'extra_specs': extra_specs,
            'qos_specs': qos_specs,
            'volume_stats': volume_stats,
            'volume_type': volume_type,
            'filter_function': filter_function,
        }

        return stats
