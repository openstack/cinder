# Copyright (c) 2011 OpenStack Foundation
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

import collections

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import timeutils

from cinder import context as cinder_context
from cinder import exception
from cinder.i18n import _LI, _LW
from cinder import objects
from cinder.openstack.common.scheduler import filters
from cinder.openstack.common.scheduler import weights
from cinder import utils
from cinder.volume import utils as vol_utils


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

CONF = cfg.CONF
CONF.register_opts(host_manager_opts)
CONF.import_opt('scheduler_driver', 'cinder.scheduler.manager')
CONF.import_opt('max_over_subscription_ratio', 'cinder.volume.driver')

LOG = logging.getLogger(__name__)


class ReadOnlyDict(collections.Mapping):
    """A read-only dict."""
    def __init__(self, source=None):
        if source is not None:
            self.data = dict(source)
        else:
            self.data = {}

    def __getitem__(self, key):
        return self.data[key]

    def __iter__(self):
        return iter(self.data)

    def __len__(self):
        return len(self.data)

    def __repr__(self):
        return '%s(%r)' % (self.__class__.__name__, self.data)


class HostState(object):
    """Mutable and immutable information tracked for a volume backend."""

    def __init__(self, host, capabilities=None, service=None):
        self.capabilities = None
        self.service = None
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
        # capacity has been allocated in cinder POV, which should be
        # sum(vol['size'] for vol in vols_on_hosts)
        self.allocated_capacity_gb = 0
        self.free_capacity_gb = None
        self.reserved_percentage = 0
        # The apparent allocated space indicating how much capacity
        # has been provisioned. This could be the sum of sizes of
        # all volumes on a backend, which could be greater than or
        # equal to the allocated_capacity_gb.
        self.provisioned_capacity_gb = 0
        self.max_over_subscription_ratio = 1.0
        self.thin_provisioning_support = False
        self.thick_provisioning_support = False
        # Does this backend support attaching a volume to more than
        # once host/instance?
        self.multiattach = False

        # PoolState for all pools
        self.pools = {}

        self.updated = None

    def update_capabilities(self, capabilities=None, service=None):
        # Read-only capability dicts

        if capabilities is None:
            capabilities = {}
        self.capabilities = ReadOnlyDict(capabilities)
        if service is None:
            service = {}
        self.service = ReadOnlyDict(service)

    def update_from_volume_capability(self, capability, service=None):
        """Update information about a host from its volume_node info.

        'capability' is the status info reported by volume backend, a typical
        capability looks like this:

        capability = {
            'volume_backend_name': 'Local iSCSI', #\
            'vendor_name': 'OpenStack',           #  backend level
            'driver_version': '1.0',              #  mandatory/fixed
            'storage_protocol': 'iSCSI',          #- stats&capabilities

            'active_volumes': 10,                 #\
            'IOPS_provisioned': 30000,            #  optional custom
            'fancy_capability_1': 'eat',          #  stats & capabilities
            'fancy_capability_2': 'drink',        #/

            'pools': [
                {'pool_name': '1st pool',         #\
                 'total_capacity_gb': 500,        #  mandatory stats for
                 'free_capacity_gb': 230,         #  pools
                 'allocated_capacity_gb': 270,    # |
                 'QoS_support': 'False',          # |
                 'reserved_percentage': 0,        #/

                 'dying_disks': 100,              #\
                 'super_hero_1': 'spider-man',    #  optional custom
                 'super_hero_2': 'flash',         #  stats & capabilities
                 'super_hero_3': 'neoncat'        #/
                 },
                {'pool_name': '2nd pool',
                 'total_capacity_gb': 1024,
                 'free_capacity_gb': 1024,
                 'allocated_capacity_gb': 0,
                 'QoS_support': 'False',
                 'reserved_percentage': 0,

                 'dying_disks': 200,
                 'super_hero_1': 'superman',
                 'super_hero_2': ' ',
                 'super_hero_2': 'Hulk',
                 }
            ]
        }
        """
        self.update_capabilities(capability, service)

        if capability:
            if self.updated and self.updated > capability['timestamp']:
                return

            # Update backend level info
            self.update_backend(capability)

            # Update pool level info
            self.update_pools(capability, service)

    def update_pools(self, capability, service):
        """Update storage pools information from backend reported info."""
        if not capability:
            return

        pools = capability.get('pools', None)
        active_pools = set()
        if pools and isinstance(pools, list):
            # Update all pools stats according to information from list
            # of pools in volume capacity
            for pool_cap in pools:
                pool_name = pool_cap['pool_name']
                self._append_backend_info(pool_cap)
                cur_pool = self.pools.get(pool_name, None)
                if not cur_pool:
                    # Add new pool
                    cur_pool = PoolState(self.host, pool_cap, pool_name)
                    self.pools[pool_name] = cur_pool
                cur_pool.update_from_volume_capability(pool_cap, service)

                active_pools.add(pool_name)
        elif pools is None:
            # To handle legacy driver that doesn't report pool
            # information in the capability, we have to prepare
            # a pool from backend level info, or to update the one
            # we created in self.pools.
            pool_name = self.volume_backend_name
            if pool_name is None:
                # To get DEFAULT_POOL_NAME
                pool_name = vol_utils.extract_host(self.host, 'pool', True)

            if len(self.pools) == 0:
                # No pool was there
                single_pool = PoolState(self.host, capability, pool_name)
                self._append_backend_info(capability)
                self.pools[pool_name] = single_pool
            else:
                # this is a update from legacy driver
                try:
                    single_pool = self.pools[pool_name]
                except KeyError:
                    single_pool = PoolState(self.host, capability, pool_name)
                    self._append_backend_info(capability)
                    self.pools[pool_name] = single_pool

            single_pool.update_from_volume_capability(capability, service)
            active_pools.add(pool_name)

        # remove non-active pools from self.pools
        nonactive_pools = set(self.pools.keys()) - active_pools
        for pool in nonactive_pools:
            LOG.debug("Removing non-active pool %(pool)s @ %(host)s "
                      "from scheduler cache.", {'pool': pool,
                                                'host': self.host})
            del self.pools[pool]

    def _append_backend_info(self, pool_cap):
        # Fill backend level info to pool if needed.
        if not pool_cap.get('volume_backend_name', None):
            pool_cap['volume_backend_name'] = self.volume_backend_name

        if not pool_cap.get('storage_protocol', None):
            pool_cap['storage_protocol'] = self.storage_protocol

        if not pool_cap.get('vendor_name', None):
            pool_cap['vendor_name'] = self.vendor_name

        if not pool_cap.get('driver_version', None):
            pool_cap['driver_version'] = self.driver_version

        if not pool_cap.get('timestamp', None):
            pool_cap['timestamp'] = self.updated

    def update_backend(self, capability):
        self.volume_backend_name = capability.get('volume_backend_name', None)
        self.vendor_name = capability.get('vendor_name', None)
        self.driver_version = capability.get('driver_version', None)
        self.storage_protocol = capability.get('storage_protocol', None)
        self.updated = capability['timestamp']

    def consume_from_volume(self, volume):
        """Incrementally update host state from an volume."""
        volume_gb = volume['size']
        self.allocated_capacity_gb += volume_gb
        self.provisioned_capacity_gb += volume_gb
        if self.free_capacity_gb == 'infinite':
            # There's virtually infinite space on back-end
            pass
        elif self.free_capacity_gb == 'unknown':
            # Unable to determine the actual free space on back-end
            pass
        else:
            self.free_capacity_gb -= volume_gb
        self.updated = timeutils.utcnow()

    def __repr__(self):
        # FIXME(zhiteng) backend level free_capacity_gb isn't as
        # meaningful as it used to be before pool is introduced, we'd
        # come up with better representation of HostState.
        return ("host '%s': free_capacity_gb: %s, pools: %s" %
                (self.host, self.free_capacity_gb, self.pools))


class PoolState(HostState):
    def __init__(self, host, capabilities, pool_name):
        new_host = vol_utils.append_host(host, pool_name)
        super(PoolState, self).__init__(new_host, capabilities)
        self.pool_name = pool_name
        # No pools in pool
        self.pools = None

    def update_from_volume_capability(self, capability, service=None):
        """Update information about a pool from its volume_node info."""
        self.update_capabilities(capability, service)
        if capability:
            if self.updated and self.updated > capability['timestamp']:
                return
            self.update_backend(capability)

            self.total_capacity_gb = capability.get('total_capacity_gb', 0)
            self.free_capacity_gb = capability.get('free_capacity_gb', 0)
            self.allocated_capacity_gb = capability.get(
                'allocated_capacity_gb', 0)
            self.QoS_support = capability.get('QoS_support', False)
            self.reserved_percentage = capability.get('reserved_percentage', 0)
            # provisioned_capacity_gb is the apparent total capacity of
            # all the volumes created on a backend, which is greater than
            # or equal to allocated_capacity_gb, which is the apparent
            # total capacity of all the volumes created on a backend
            # in Cinder. Using allocated_capacity_gb as the default of
            # provisioned_capacity_gb if it is not set.
            self.provisioned_capacity_gb = capability.get(
                'provisioned_capacity_gb', self.allocated_capacity_gb)
            self.max_over_subscription_ratio = capability.get(
                'max_over_subscription_ratio',
                CONF.max_over_subscription_ratio)
            self.thin_provisioning_support = capability.get(
                'thin_provisioning_support', False)
            self.thick_provisioning_support = capability.get(
                'thick_provisioning_support', False)
            self.multiattach = capability.get('multiattach', False)

    def update_pools(self, capability):
        # Do nothing, since we don't have pools within pool, yet
        pass


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

        self._no_capabilities_hosts = set()  # Hosts having no capabilities
        self._update_host_state_map(cinder_context.get_admin_context())

    def _choose_host_filters(self, filter_cls_names):
        """Return a list of available filter names.

        This function checks input filter names against a predefined set
        of acceptable filterss (all loaded filters).  If input is None,
        it uses CONF.scheduler_default_filters instead.
        """
        if filter_cls_names is None:
            filter_cls_names = CONF.scheduler_default_filters
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
            raise exception.SchedulerHostFilterNotFound(
                filter_name=", ".join(bad_filters))
        return good_filters

    def _choose_host_weighers(self, weight_cls_names):
        """Return a list of available weigher names.

        This function checks input weigher names against a predefined set
        of acceptable weighers (all loaded weighers).  If input is None,
        it uses CONF.scheduler_default_weighers instead.
        """
        if weight_cls_names is None:
            weight_cls_names = CONF.scheduler_default_weighers
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
            raise exception.SchedulerHostWeigherNotFound(
                weigher_name=", ".join(bad_weighers))
        return good_weighers

    def get_filtered_hosts(self, hosts, filter_properties,
                           filter_class_names=None):
        """Filter hosts and return only ones passing all filters."""
        filter_classes = self._choose_host_filters(filter_class_names)
        return self.filter_handler.get_filtered_objects(filter_classes,
                                                        hosts,
                                                        filter_properties)

    def get_weighed_hosts(self, hosts, weight_properties,
                          weigher_class_names=None):
        """Weigh the hosts."""
        weigher_classes = self._choose_host_weighers(weigher_class_names)
        return self.weight_handler.get_weighed_objects(weigher_classes,
                                                       hosts,
                                                       weight_properties)

    def update_service_capabilities(self, service_name, host, capabilities):
        """Update the per-service capabilities based on this notification."""
        if service_name != 'volume':
            LOG.debug('Ignoring %(service_name)s service update '
                      'from %(host)s',
                      {'service_name': service_name, 'host': host})
            return

        # Copy the capabilities, so we don't modify the original dict
        capab_copy = dict(capabilities)
        capab_copy["timestamp"] = timeutils.utcnow()  # Reported time
        self.service_states[host] = capab_copy

        LOG.debug("Received %(service_name)s service update from "
                  "%(host)s: %(cap)s",
                  {'service_name': service_name, 'host': host,
                   'cap': capabilities})

        self._no_capabilities_hosts.discard(host)

    def has_all_capabilities(self):
        return len(self._no_capabilities_hosts) == 0

    def _update_host_state_map(self, context):

        # Get resource usage across the available volume nodes:
        topic = CONF.volume_topic
        volume_services = objects.ServiceList.get_all_by_topic(context,
                                                               topic,
                                                               disabled=False)
        active_hosts = set()
        no_capabilities_hosts = set()
        for service in volume_services.objects:
            host = service.host
            if not utils.service_is_up(service):
                LOG.warning(_LW("volume service is down. (host: %s)"), host)
                continue
            capabilities = self.service_states.get(host, None)
            if capabilities is None:
                no_capabilities_hosts.add(host)
                continue

            host_state = self.host_state_map.get(host)
            if not host_state:
                host_state = self.host_state_cls(host,
                                                 capabilities=capabilities,
                                                 service=
                                                 dict(service))
                self.host_state_map[host] = host_state
            # update capabilities and attributes in host_state
            host_state.update_from_volume_capability(capabilities,
                                                     service=
                                                     dict(service))
            active_hosts.add(host)

        self._no_capabilities_hosts = no_capabilities_hosts

        # remove non-active hosts from host_state_map
        nonactive_hosts = set(self.host_state_map.keys()) - active_hosts
        for host in nonactive_hosts:
            LOG.info(_LI("Removing non-active host: %(host)s from "
                         "scheduler cache."), {'host': host})
            del self.host_state_map[host]

    def get_all_host_states(self, context):
        """Returns a dict of all the hosts the HostManager knows about.

        Each of the consumable resources in HostState are
        populated with capabilities scheduler received from RPC.

        For example:
          {'192.168.1.100': HostState(), ...}
        """

        self._update_host_state_map(context)

        # build a pool_state map and return that map instead of host_state_map
        all_pools = {}
        for host, state in self.host_state_map.items():
            for key in state.pools:
                pool = state.pools[key]
                # use host.pool_name to make sure key is unique
                pool_key = '.'.join([host, pool.pool_name])
                all_pools[pool_key] = pool

        return all_pools.values()

    def get_pools(self, context):
        """Returns a dict of all pools on all hosts HostManager knows about."""

        self._update_host_state_map(context)

        all_pools = []
        for host, state in self.host_state_map.items():
            for key in state.pools:
                pool = state.pools[key]
                # use host.pool_name to make sure key is unique
                pool_key = vol_utils.append_host(host, pool.pool_name)
                new_pool = dict(name=pool_key)
                new_pool.update(dict(capabilities=pool.capabilities))
                all_pools.append(new_pool)

        return all_pools
