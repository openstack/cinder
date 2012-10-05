# Copyright (c) 2011 OpenStack, LLC.
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

"""
Manage hosts in the current zone.
"""

import UserDict

from cinder import db
from cinder import exception
from cinder import flags
from cinder.openstack.common import cfg
from cinder.openstack.common import log as logging
from cinder.openstack.common.scheduler import filters
from cinder.openstack.common.scheduler import weights
from cinder.openstack.common import timeutils
from cinder import utils


host_manager_opts = [
    cfg.ListOpt('scheduler_default_filters',
                default=[
                    'AvailabilityZoneFilter',
                    'CapacityFilter',
                    'CapabilitiesFilter'
                ],
                help='Which filter class names to use for filtering hosts '
                     'when not specified in the request.'),
    cfg.ListOpt('scheduler_default_weighers',
                default=[
                    'CapacityWeigher'
                ],
                help='Which weigher class names to use for weighing hosts.')
]

FLAGS = flags.FLAGS
FLAGS.register_opts(host_manager_opts)

LOG = logging.getLogger(__name__)


class ReadOnlyDict(UserDict.IterableUserDict):
    """A read-only dict."""
    def __init__(self, source=None):
        self.data = {}
        self.update(source)

    def __setitem__(self, key, item):
        raise TypeError

    def __delitem__(self, key):
        raise TypeError

    def clear(self):
        raise TypeError

    def pop(self, key, *args):
        raise TypeError

    def popitem(self):
        raise TypeError

    def update(self, source=None):
        if source is None:
            return
        elif isinstance(source, UserDict.UserDict):
            self.data = source.data
        elif isinstance(source, type({})):
            self.data = source
        else:
            raise TypeError


class HostState(object):
    """Mutable and immutable information tracked for a host."""

    def __init__(self, host, capabilities=None, service=None):
        self.host = host
        self.update_capabilities(capabilities, service)

        self.volume_backend_name = None
        self.vendor_name = None
        self.driver_version = 0
        self.storage_protocol = None
        self.QoS_support = False
        # Mutable available resources.
        # These will change as resources are virtually "consumed".
        self.total_capacity_gb = 0
        self.free_capacity_gb = 0
        self.reserved_percentage = 0

        self.updated = None

    def update_capabilities(self, capabilities=None, service=None):
        # Read-only capability dicts

        if capabilities is None:
            capabilities = {}
        self.capabilities = ReadOnlyDict(capabilities)
        if service is None:
            service = {}
        self.service = ReadOnlyDict(service)

    def update_from_volume_capability(self, capability):
        """Update information about a host from its volume_node info."""
        if self.updated and self.updated > capability['timestamp']:
            return

        if capability:
            self.volume_backend = capability.get('volume_backend_name', None)
            self.vendor_name = capability.get('vendor_name', None)
            self.driver_version = capability.get('driver_version', None)
            self.storage_protocol = capability.get('storage_protocol', None)
            self.QoS_support = capability.get('QoS_support', False)

            self.total_capacity_gb = capability['total_capacity_gb']
            self.free_capacity_gb = capability['free_capacity_gb']
            self.reserved_percentage = capability['reserved_percentage']

            self.updated = capability['timestamp']

    def consume_from_volume(self, volume):
        """Incrementally update host state from an volume"""
        volume_gb = volume['size']
        self.free_capacity_gb -= volume_gb
        self.updated = timeutils.utcnow()

    def __repr__(self):
        return ("host '%s': free_capacity_gb: %s" %
                (self.host, self.free_capacity_gb))


class HostManager(object):
    """Base HostManager class."""

    host_state_cls = HostState

    def __init__(self):
        self.service_states = {}  # { <host>: {<service>: {cap k : v}}}
        self.host_state_map = {}
        self.filter_handler = filters.HostFilterHandler('cinder.scheduler.'
                                                        'filters')
        self.filter_classes = self.filter_handler.get_all_classes()
        self.weight_handler = weights.HostWeightHandler('cinder.scheduler.'
                                                        'weights')
        self.weight_classes = self.weight_handler.get_all_classes()

    def _choose_host_filters(self, filter_cls_names):
        """Since the caller may specify which filters to use we need
        to have an authoritative list of what is permissible. This
        function checks the filter names against a predefined set
        of acceptable filters.
        """
        if filter_cls_names is None:
            filter_cls_names = FLAGS.scheduler_default_filters
        if not isinstance(filter_cls_names, (list, tuple)):
            filter_cls_names = [filter_cls_names]
        good_filters = []
        bad_filters = []
        for filter_name in filter_cls_names:
            found_class = False
            for cls in self.filter_classes:
                if cls.__name__ == filter_name:
                    found_class = True
                    good_filters.append(cls)
                    break
            if not found_class:
                bad_filters.append(filter_name)
        if bad_filters:
            msg = ", ".join(bad_filters)
            raise exception.SchedulerHostFilterNotFound(filter_name=msg)
        return good_filters

    def _choose_host_weighers(self, weight_cls_names):
        """Since the caller may specify which weighers to use, we need
        to have an authoritative list of what is permissible. This
        function checks the weigher names against a predefined set
        of acceptable weighers.
        """
        if weight_cls_names is None:
            weight_cls_names = FLAGS.scheduler_default_weighers
        if not isinstance(weight_cls_names, (list, tuple)):
            weight_cls_names = [weight_cls_names]

        good_weighers = []
        bad_weighers = []
        for weigher_name in weight_cls_names:
            found_class = False
            for cls in self.weight_classes:
                if cls.__name__ == weigher_name:
                    good_weighers.append(cls)
                    found_class = True
                    break
            if not found_class:
                bad_weighers.append(weigher_name)
        if bad_weighers:
            msg = ", ".join(bad_weighers)
            raise exception.SchedulerHostWeigherNotFound(weigher_name=msg)
        return good_weighers

    def get_filtered_hosts(self, hosts, filter_properties,
                           filter_class_names=None):
        """Filter hosts and return only ones passing all filters"""
        filter_classes = self._choose_host_filters(filter_class_names)
        return self.filter_handler.get_filtered_objects(filter_classes,
                                                        hosts,
                                                        filter_properties)

    def get_weighed_hosts(self, hosts, weight_properties,
                          weigher_class_names=None):
        """Weigh the hosts"""
        weigher_classes = self._choose_host_weighers(weigher_class_names)
        return self.weight_handler.get_weighed_objects(weigher_classes,
                                                       hosts,
                                                       weight_properties)

    def update_service_capabilities(self, service_name, host, capabilities):
        """Update the per-service capabilities based on this notification."""
        if service_name != 'volume':
            LOG.debug(_('Ignoring %(service_name)s service update '
                        'from %(host)s'), locals())
            return

        LOG.debug(_("Received %(service_name)s service update from "
                    "%(host)s.") % locals())

        # Copy the capabilities, so we don't modify the original dict
        capab_copy = dict(capabilities)
        capab_copy["timestamp"] = timeutils.utcnow()  # Reported time
        self.service_states[host] = capab_copy

    def get_all_host_states(self, context):
        """Returns a dict of all the hosts the HostManager
          knows about. Also, each of the consumable resources in HostState
          are pre-populated and adjusted based on data in the db.

          For example:
          {'192.168.1.100': HostState(), ...}
        """

        # Get resource usage across the available volume nodes:
        topic = FLAGS.volume_topic
        volume_services = db.service_get_all_by_topic(context, topic)
        for service in volume_services:
            if not utils.service_is_up(service) or service['disabled']:
                LOG.warn(_("service is down or disabled."))
                continue
            host = service['host']
            capabilities = self.service_states.get(host, None)
            host_state = self.host_state_map.get(host)
            if host_state:
                # copy capabilities to host_state.capabilities
                host_state.update_capabilities(capabilities,
                                               dict(service.iteritems()))
            else:
                host_state = self.host_state_cls(host,
                                                 capabilities=capabilities,
                                                 service=
                                                 dict(service.iteritems()))
                self.host_state_map[host] = host_state
            # update host_state
            host_state.update_from_volume_capability(capabilities)

        return self.host_state_map.itervalues()
