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

"""Manage backends in the current zone."""

from __future__ import annotations

from collections import abc
import random
import typing
from typing import (Any, Iterable, Optional, Type, Union)  # noqa: H301

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import importutils
from oslo_utils import strutils
from oslo_utils import timeutils

from cinder.common import constants
from cinder import context as cinder_context
from cinder import exception
from cinder import objects
from cinder.scheduler import filters
from cinder import utils
from cinder.volume import volume_types
from cinder.volume import volume_utils


# FIXME: This file should be renamed to backend_manager, we should also rename
# HostManager class, and scheduler_host_manager option, and also the weight
# classes, and add code to maintain backward compatibility.


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
                help='Which weigher class names to use for weighing hosts.'),
    cfg.StrOpt('scheduler_weight_handler',
               default='cinder.scheduler.weights.OrderedHostWeightHandler',
               help='Which handler to use for selecting the host/pool '
                    'after weighing'),
]

CONF = cfg.CONF
CONF.register_opts(host_manager_opts)
CONF.import_opt('scheduler_driver', 'cinder.scheduler.manager')
CONF.import_opt('max_over_subscription_ratio', 'cinder.volume.driver')

LOG = logging.getLogger(__name__)


class ReadOnlyDict(abc.Mapping):
    """A read-only dict."""
    def __init__(self, source: Optional[Union[dict, 'ReadOnlyDict']] = None):
        self.data: dict
        if source is not None:
            self.data = dict(source)
        else:
            self.data = {}

    def __getitem__(self, key):
        return self.data[key]

    def __iter__(self):
        return iter(self.data)

    def __len__(self) -> int:
        return len(self.data)

    def __repr__(self) -> str:
        return '%s(%r)' % (self.__class__.__name__, self.data)


class BackendState(object):
    """Mutable and immutable information tracked for a volume backend."""

    def __init__(self,
                 host: str,
                 cluster_name: Optional[str],
                 capabilities: Union[Optional[ReadOnlyDict],
                                     Optional[dict]] = None,
                 service=None):
        # NOTE(geguileo): We have a circular dependency between BackendState
        # and PoolState and we resolve it with an instance attribute instead
        # of a class attribute that we would assign after the PoolState
        # declaration because this way we avoid splitting the code.
        self.pool_state_cls: Type[PoolState] = PoolState

        self.capabilities: Optional[ReadOnlyDict] = None
        self.service: Optional[ReadOnlyDict] = None
        self.host: str = host
        self.cluster_name: Optional[str] = cluster_name
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
        # one host/instance?
        self.multiattach: bool = False
        self.filter_function = None
        self.goodness_function = 0

        # PoolState for all pools
        self.pools: dict = {}

        self.updated = None

    @property
    def backend_id(self) -> str:
        return self.cluster_name or self.host

    def update_capabilities(
            self,
            capabilities: Optional[Union[dict, ReadOnlyDict]] = None,
            service: Optional[dict] = None) -> None:
        # Read-only capability dicts

        if capabilities is None:
            capabilities = {}
        self.capabilities = ReadOnlyDict(capabilities)
        if service is None:
            service = {}
        self.service = ReadOnlyDict(service)

    def update_from_volume_capability(self,
                                      capability: dict[str, Any],
                                      service=None) -> None:
        """Update information about a host from its volume_node info.

        'capability' is the status info reported by volume backend, a typical
        capability looks like this:

        .. code-block:: python

         {
          capability = {
              'volume_backend_name': 'Local iSCSI', #
              'vendor_name': 'OpenStack',           #  backend level
              'driver_version': '1.0',              #  mandatory/fixed
              'storage_protocol': 'iSCSI',          #  stats&capabilities

              'active_volumes': 10,                 #
              'IOPS_provisioned': 30000,            #  optional custom
              'fancy_capability_1': 'eat',          #  stats & capabilities
              'fancy_capability_2': 'drink',        #

              'pools': [
                  {'pool_name': '1st pool',         #
                   'total_capacity_gb': 500,        #  mandatory stats for
                   'free_capacity_gb': 230,         #  pools
                   'allocated_capacity_gb': 270,    #
                   'QoS_support': 'False',          #
                   'reserved_percentage': 0,        #

                   'dying_disks': 100,              #
                   'super_hero_1': 'spider-man',    #  optional custom
                   'super_hero_2': 'flash',         #  stats & capabilities
                   'super_hero_3': 'neoncat'        #
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
                   'super_hero_2': 'Hulk'
                  }
              ]
          }
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

    def update_pools(self, capability: Optional[dict], service) -> None:
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
                    cur_pool = self.pool_state_cls(self.host,
                                                   self.cluster_name,
                                                   pool_cap,
                                                   pool_name)
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
                pool_name = volume_utils.extract_host(self.host, 'pool', True)

            if len(self.pools) == 0:
                # No pool was there
                single_pool = self.pool_state_cls(self.host, self.cluster_name,
                                                  capability, pool_name)
                self._append_backend_info(capability)
                self.pools[pool_name] = single_pool
            else:
                # this is an update from legacy driver
                try:
                    single_pool = self.pools[pool_name]
                except KeyError:
                    single_pool = self.pool_state_cls(self.host,
                                                      self.cluster_name,
                                                      capability,
                                                      pool_name)
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

    def _append_backend_info(self, pool_cap: dict[str, Any]) -> None:
        # Fill backend level info to pool if needed.
        if not pool_cap.get('volume_backend_name', None):
            pool_cap['volume_backend_name'] = self.volume_backend_name

        protocol = pool_cap.get('storage_protocol', None)
        if protocol:
            # Protocols that have variants are replaced with ALL the variants
            storage_protocol = self.get_storage_protocol_variants(protocol)
        else:  # Backend protocol has already been transformed with variants
            storage_protocol = self.storage_protocol
        pool_cap['storage_protocol'] = storage_protocol

        if not pool_cap.get('vendor_name', None):
            pool_cap['vendor_name'] = self.vendor_name

        if not pool_cap.get('driver_version', None):
            pool_cap['driver_version'] = self.driver_version

        if not pool_cap.get('timestamp', None):
            pool_cap['timestamp'] = self.updated

        self.capabilities = typing.cast(ReadOnlyDict, self.capabilities)
        if('filter_function' not in pool_cap and
                'filter_function' in self.capabilities):
            pool_cap['filter_function'] = self.capabilities['filter_function']

        if('goodness_function' not in pool_cap and
                'goodness_function' in self.capabilities):
            pool_cap['goodness_function'] = (
                self.capabilities['goodness_function'])

    def update_backend(self, capability: dict) -> None:
        self.volume_backend_name = capability.get('volume_backend_name', None)
        self.vendor_name = capability.get('vendor_name', None)
        self.driver_version = capability.get('driver_version', None)

        # Protocols that have variants are replaced with ALL the variants
        protocol = capability.get('storage_protocol', None)
        self.storage_protocol = self.get_storage_protocol_variants(protocol)
        if 'storage_protocol' in capability:
            capability['storage_protocol'] = self.storage_protocol
        self.updated = capability['timestamp']

    def consume_from_volume(self,
                            volume: objects.Volume,
                            update_time: bool = True) -> None:
        """Incrementally update host state from a volume."""
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
        if update_time:
            self.updated = timeutils.utcnow()
        LOG.debug("Consumed %s GB from backend: %s", volume['size'], self)

    def __repr__(self) -> str:
        # FIXME(zhiteng) backend level free_capacity_gb isn't as
        # meaningful as it used to be before pool is introduced, we'd
        # come up with better representation of HostState.
        grouping = 'cluster' if self.cluster_name else 'host'
        grouping_name = self.backend_id
        return ("%(grouping)s '%(grouping_name)s': "
                "free_capacity_gb: %(free_capacity_gb)s, "
                "total_capacity_gb: %(total_capacity_gb)s, "
                "allocated_capacity_gb: %(allocated_capacity_gb)s, "
                "max_over_subscription_ratio: %(mosr)s, "
                "reserved_percentage: %(reserved_percentage)s, "
                "provisioned_capacity_gb: %(provisioned_capacity_gb)s, "
                "thin_provisioning_support: %(thin_provisioning_support)s, "
                "thick_provisioning_support: %(thick)s, "
                "pools: %(pools)s, "
                "updated at: %(updated)s" %
                {'grouping': grouping, 'grouping_name': grouping_name,
                 'free_capacity_gb': self.free_capacity_gb,
                 'total_capacity_gb': self.total_capacity_gb,
                 'allocated_capacity_gb': self.allocated_capacity_gb,
                 'mosr': self.max_over_subscription_ratio,
                 'reserved_percentage': self.reserved_percentage,
                 'provisioned_capacity_gb': self.provisioned_capacity_gb,
                 'thin_provisioning_support': self.thin_provisioning_support,
                 'thick': self.thick_provisioning_support,
                 'pools': self.pools, 'updated': self.updated})

    @staticmethod
    def get_storage_protocol_variants(storage_protocol):
        if storage_protocol in constants.ISCSI_VARIANTS:
            return constants.ISCSI_VARIANTS
        if storage_protocol in constants.FC_VARIANTS:
            return constants.FC_VARIANTS
        if storage_protocol in constants.NFS_VARIANTS:
            return constants.NFS_VARIANTS
        if storage_protocol in constants.NVMEOF_VARIANTS:
            return constants.NVMEOF_VARIANTS
        return storage_protocol


class PoolState(BackendState):
    def __init__(self,
                 host: str,
                 cluster_name: Optional[str],
                 capabilities: Union[Optional[ReadOnlyDict], Optional[dict]],
                 pool_name: str):
        new_host = volume_utils.append_host(host, pool_name)
        assert new_host is not None
        new_cluster = volume_utils.append_host(cluster_name, pool_name)
        super(PoolState, self).__init__(new_host, new_cluster, capabilities)
        self.pool_name = pool_name
        # No pools in pool
        self.pools: dict = {}

    def update_from_volume_capability(self,
                                      capability: dict[str, Any],
                                      service=None) -> None:
        """Update information about a pool from its volume_node info."""
        LOG.debug("Updating capabilities for %s: %s", self.host, capability)
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
            self.thin_provisioning_support = capability.get(
                'thin_provisioning_support', False)
            self.thick_provisioning_support = capability.get(
                'thick_provisioning_support', False)

            self.max_over_subscription_ratio = (
                utils.calculate_max_over_subscription_ratio(
                    capability, CONF.max_over_subscription_ratio))

            self.multiattach = capability.get('multiattach', False)
            self.pool_state = capability.get('pool_state', 'up')

            self.filter_function = capability.get('filter_function', None)
            self.goodness_function = capability.get('goodness_function', 0)

    def update_pools(self, capability):
        # Do nothing, since we don't have pools within pool, yet
        pass


class HostManager(object):
    """Base HostManager class."""

    backend_state_cls = BackendState

    ALLOWED_SERVICE_NAMES = ('volume', 'backup')

    REQUIRED_KEYS = frozenset([
        'pool_name',
        'total_capacity_gb',
        'free_capacity_gb',
        'allocated_capacity_gb',
        'provisioned_capacity_gb',
        'thin_provisioning_support',
        'thick_provisioning_support',
        'max_over_subscription_ratio',
        'reserved_percentage'])

    def __init__(self):
        self.service_states = {}  # { <host|cluster>: {<service>: {cap k : v}}}
        self.backend_state_map: dict[str, BackendState] = {}
        self.backup_service_states = {}
        self.filter_handler = filters.BackendFilterHandler('cinder.scheduler.'
                                                           'filters')
        self.filter_classes = self.filter_handler.get_all_classes()
        self.enabled_filters = self._choose_backend_filters(
            CONF.scheduler_default_filters)
        self.weight_handler = importutils.import_object(
            CONF.scheduler_weight_handler,
            'cinder.scheduler.weights')
        self.weight_classes = self.weight_handler.get_all_classes()

        self._no_capabilities_backends = set()  # Services without capabilities
        self._update_backend_state_map(cinder_context.get_admin_context())
        self.service_states_last_update = {}

    def _choose_backend_filters(self, filter_cls_names) -> list:
        """Return a list of available filter names.

        This function checks input filter names against a predefined set
        of acceptable filters (all loaded filters). If input is None,
        it uses CONF.scheduler_default_filters instead.
        """
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

    def _choose_backend_weighers(
            self,
            weight_cls_names: Optional[list[str]]) -> list:
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

    def get_filtered_backends(self, backends, filter_properties,
                              filter_class_names=None):
        """Filter backends and return only ones passing all filters."""
        if filter_class_names is not None:
            filter_classes = self._choose_backend_filters(filter_class_names)
        else:
            filter_classes = self.enabled_filters
        return self.filter_handler.get_filtered_objects(filter_classes,
                                                        backends,
                                                        filter_properties)

    def get_weighed_backends(self, backends, weight_properties,
                             weigher_class_names=None) -> list:
        """Weigh the backends."""
        weigher_classes = self._choose_backend_weighers(weigher_class_names)

        weighed_backends = self.weight_handler.get_weighed_objects(
            weigher_classes, backends, weight_properties)

        LOG.debug("Weighed %s", weighed_backends)
        return weighed_backends

    def update_service_capabilities(self,
                                    service_name: str,
                                    host: str,
                                    capabilities: dict,
                                    cluster_name: Optional[str],
                                    timestamp) -> None:
        """Update the per-service capabilities based on this notification."""
        if service_name not in HostManager.ALLOWED_SERVICE_NAMES:
            LOG.debug('Ignoring %(service_name)s service update '
                      'from %(host)s',
                      {'service_name': service_name, 'host': host})
            return

        # Determine whether HostManager has just completed initialization, and
        # has not received the rpc message returned by volume.
        just_init = self._is_just_initialized()

        # TODO(geguileo): In P - Remove the next line since we receive the
        # timestamp
        timestamp = timestamp or timeutils.utcnow()
        # Copy the capabilities, so we don't modify the original dict
        capab_copy = dict(capabilities)
        capab_copy["timestamp"] = timestamp

        # Set the default capabilities in case None is set.
        backend = cluster_name or host

        if service_name == 'backup':
            self.backup_service_states[backend] = capabilities
            LOG.debug("Received %(service_name)s service update from "
                      "%(host)s: %(cap)s",
                      {'service_name': service_name, 'host': host,
                       'cap': capabilities})
            return

        capab_old = self.service_states.get(backend, {"timestamp": 0})
        capab_last_update = self.service_states_last_update.get(
            backend, {"timestamp": 0})

        # Ignore older updates
        if capab_old['timestamp'] and timestamp < capab_old['timestamp']:
            LOG.info('Ignoring old capability report from %s.', backend)
            return

        # If the capabilities are not changed and the timestamp is older,
        # record the capabilities.

        # There are cases: capab_old has the capabilities set,
        # but the timestamp may be None in it. So does capab_last_update.

        if (not self._get_updated_pools(capab_old, capab_copy)) and (
                (not capab_old.get("timestamp")) or
                (not capab_last_update.get("timestamp")) or
                (capab_last_update["timestamp"] < capab_old["timestamp"])):
            self.service_states_last_update[backend] = capab_old

        self.service_states[backend] = capab_copy

        cluster_msg = (('Cluster: %s - Host: ' % cluster_name) if cluster_name
                       else '')
        LOG.debug("Received %(service_name)s service update from %(cluster)s "
                  "%(host)s: %(cap)s%(cluster)s",
                  {'service_name': service_name, 'host': host,
                   'cap': capabilities,
                   'cluster': cluster_msg})

        self._no_capabilities_backends.discard(backend)
        if just_init:
            self._update_backend_state_map(cinder_context.get_admin_context())

    def notify_service_capabilities(self, service_name, backend, capabilities,
                                    timestamp):
        """Notify the ceilometer with updated volume stats"""
        if service_name != 'volume':
            return

        updated = []
        capa_new = self.service_states.get(backend, {})
        timestamp = timestamp or timeutils.utcnow()

        # Compare the capabilities and timestamps to decide notifying
        if not capa_new:
            updated = self._get_updated_pools(capa_new, capabilities)
        else:
            if timestamp > self.service_states[backend]["timestamp"]:
                updated = self._get_updated_pools(
                    self.service_states[backend], capabilities)
                if not updated:
                    updated = self._get_updated_pools(
                        self.service_states_last_update.get(backend, {}),
                        self.service_states.get(backend, {}))

        if updated:
            capab_copy = dict(capabilities)
            capab_copy["timestamp"] = timestamp
            # If capabilities changes, notify and record the capabilities.
            self.service_states_last_update[backend] = capab_copy
            self.get_usage_and_notify(capabilities, updated, backend,
                                      timestamp)

    def has_all_capabilities(self) -> bool:
        return len(self._no_capabilities_backends) == 0

    def _is_just_initialized(self) -> bool:
        return not self.service_states_last_update

    def first_receive_capabilities(self) -> bool:
        return (not self._is_just_initialized() and
                len(set(self.backend_state_map)) > 0 and
                len(self._no_capabilities_backends) == 0)

    def _update_backend_state_map(
            self,
            context: cinder_context.RequestContext) -> None:

        # Get resource usage across the available volume nodes:
        topic = constants.VOLUME_TOPIC
        volume_services = objects.ServiceList.get_all(context,
                                                      {'topic': topic,
                                                       'disabled': False,
                                                       'frozen': False})
        active_backends = set()
        active_hosts = set()
        no_capabilities_backends = set()
        for service in volume_services.objects:
            host = service.host
            if not service.is_up:
                LOG.warning("volume service is down. (host: %s)", host)
                continue

            backend_key = service.service_topic_queue
            # We only pay attention to the first up service of a cluster since
            # they all refer to the same capabilities entry in service_states
            if backend_key in active_backends:
                active_hosts.add(host)
                continue

            # Capabilities may come from the cluster or the host if the service
            # has just been converted to a cluster service.
            capabilities = (self.service_states.get(service.cluster_name, None)
                            or self.service_states.get(service.host, None))
            if capabilities is None:
                no_capabilities_backends.add(backend_key)
                continue

            # Since the service could have been added or remove from a cluster
            backend_state = self.backend_state_map.get(backend_key, None)
            if not backend_state:
                backend_state = self.backend_state_cls(
                    host,
                    service.cluster_name,
                    capabilities=capabilities,
                    service=dict(service))
                self.backend_state_map[backend_key] = backend_state

            # update capabilities and attributes in backend_state
            backend_state.update_from_volume_capability(capabilities,
                                                        service=dict(service))
            active_backends.add(backend_key)

        self._no_capabilities_backends = no_capabilities_backends

        # remove non-active keys from backend_state_map
        inactive_backend_keys = set(self.backend_state_map) - active_backends
        for backend_key in inactive_backend_keys:
            # NOTE(geguileo): We don't want to log the removal of a host from
            # the map when we are removing it because it has been added to a
            # cluster.
            if backend_key not in active_hosts:
                LOG.info("Removing non-active backend: %(backend)s from "
                         "scheduler cache.", {'backend': backend_key})
            del self.backend_state_map[backend_key]

    def revert_volume_consumed_capacity(self,
                                        pool_name: str,
                                        size: int) -> None:
        for backend_key, state in self.backend_state_map.items():
            for key in state.pools:
                pool_state = state.pools[key]
                if pool_name == '#'.join([backend_key, pool_state.pool_name]):
                    pool_state.consume_from_volume({'size': -size},
                                                   update_time=False)

    def get_all_backend_states(
            self,
            context: cinder_context.RequestContext) -> Iterable:
        """Returns a dict of all the backends the HostManager knows about.

        Each of the consumable resources in BackendState are
        populated with capabilities scheduler received from RPC.

        For example:
          {'192.168.1.100': BackendState(), ...}
        """

        self._update_backend_state_map(context)

        # build a pool_state map and return that map instead of
        # backend_state_map
        all_pools = {}
        for backend_key, state in self.backend_state_map.items():
            for key in state.pools:
                pool = state.pools[key]
                # use backend_key.pool_name to make sure key is unique
                pool_key = '.'.join([backend_key, pool.pool_name])
                all_pools[pool_key] = pool

        return all_pools.values()

    def _filter_pools_by_volume_type(
            self,
            context: cinder_context.RequestContext,
            volume_type: objects.VolumeType,
            pools: dict) -> dict:
        """Return the pools filtered by volume type specs"""

        # wrap filter properties only with volume_type
        filter_properties = {
            'context': context,
            'volume_type': volume_type,
            'resource_type': volume_type,
            'qos_specs': volume_type.get('qos_specs'),
        }

        filtered = self.get_filtered_backends(pools.values(),
                                              filter_properties)

        # filter the pools by value
        return {k: v for k, v in pools.items() if v in filtered}

    def get_pools(self,
                  context: cinder_context.RequestContext,
                  filters: Optional[dict] = None) -> list[dict]:
        """Returns a dict of all pools on all hosts HostManager knows about."""

        self._update_backend_state_map(context)

        all_pools = {}
        name = volume_type = None
        if filters:
            name = filters.pop('name', None)
            volume_type = filters.pop('volume_type', None)

        for backend_key, state in self.backend_state_map.items():
            for key in state.pools:
                filtered = False
                pool = state.pools[key]
                # use backend_key.pool_name to make sure key is unique
                pool_key = volume_utils.append_host(backend_key,
                                                    pool.pool_name)
                new_pool = dict(name=pool_key)
                new_pool.update(dict(capabilities=pool.capabilities))

                if name and new_pool.get('name') != name:
                    continue

                if filters:
                    # filter all other items in capabilities
                    for (attr, value) in filters.items():
                        cap = new_pool.get('capabilities').\
                            get(attr)   # type: ignore
                        if not self._equal_after_convert(cap, value):
                            filtered = True
                            break

                if not filtered:
                    all_pools[pool_key] = pool

        # filter pools by volume type
        if volume_type:
            volume_type = volume_types.get_by_name_or_id(
                context, volume_type)
            all_pools = (
                self._filter_pools_by_volume_type(context,
                                                  volume_type,
                                                  all_pools))

        # encapsulate pools in format:{name: XXX, capabilities: XXX}
        return [dict(name=key, capabilities=value.capabilities)
                for key, value in all_pools.items()]

    def get_usage_and_notify(self,
                             capa_new: dict,
                             updated_pools: Iterable[dict],
                             host: str,
                             timestamp) -> None:
        context = cinder_context.get_admin_context()
        usage = self._get_usage(capa_new, updated_pools, host, timestamp)

        self._notify_capacity_usage(context, usage)

    def _get_usage(self,
                   capa_new: dict,
                   updated_pools: Iterable[dict],
                   host: str,
                   timestamp) -> list[dict]:
        pools = capa_new.get('pools')
        usage = []
        if pools and isinstance(pools, list):
            backend_usage = dict(type='backend',
                                 name_to_id=host,
                                 total=0,
                                 free=0,
                                 allocated=0,
                                 provisioned=0,
                                 virtual_free=0,
                                 reported_at=timestamp)

            # Process the usage.
            for pool in pools:
                pool_usage = self._get_pool_usage(pool, host, timestamp)
                if pool_usage:
                    backend_usage["total"] += pool_usage["total"]
                    backend_usage["free"] += pool_usage["free"]
                    backend_usage["allocated"] += pool_usage["allocated"]
                    backend_usage["provisioned"] += pool_usage["provisioned"]
                    backend_usage["virtual_free"] += pool_usage["virtual_free"]
                # Only the updated pool is reported.
                if pool in updated_pools:
                    usage.append(pool_usage)
            usage.append(backend_usage)
        return usage

    def _get_pool_usage(self,
                        pool: dict,
                        host: str, timestamp) -> dict[str, Any]:
        total = pool["total_capacity_gb"]
        free = pool["free_capacity_gb"]

        unknowns = ["unknown", "infinite", None]
        if (total in unknowns) or (free in unknowns):
            return {}

        allocated = pool["allocated_capacity_gb"]
        provisioned = pool["provisioned_capacity_gb"]
        reserved = pool["reserved_percentage"]
        ratio = utils.calculate_max_over_subscription_ratio(
            pool, CONF.max_over_subscription_ratio)
        support = pool["thin_provisioning_support"]

        virtual_free = utils.calculate_virtual_free_capacity(
            total,
            free,
            provisioned,
            support,
            ratio,
            reserved,
            support)

        pool_usage = dict(
            type='pool',
            name_to_id='#'.join([host, pool['pool_name']]),
            total=float(total),
            free=float(free),
            allocated=float(allocated),
            provisioned=float(provisioned),
            virtual_free=float(virtual_free),
            reported_at=timestamp)

        return pool_usage

    def _get_updated_pools(self, old_capa: dict, new_capa: dict) -> list:
        # Judge if the capabilities should be reported.

        new_pools = new_capa.get('pools', [])
        if not new_pools:
            return []

        if isinstance(new_pools, list):
            # If the volume_stats is not well prepared, don't notify.
            if not all(
                    self.REQUIRED_KEYS.issubset(pool) for pool in new_pools):
                return []
        else:
            LOG.debug("The reported capabilities are not well structured...")
            return []

        old_pools = old_capa.get('pools', [])
        if not old_pools:
            return new_pools

        updated_pools = []

        newpools = {}
        oldpools = {}
        for new_pool in new_pools:
            newpools[new_pool['pool_name']] = new_pool

        for old_pool in old_pools:
            oldpools[old_pool['pool_name']] = old_pool

        for key in newpools:
            if key in oldpools.keys():
                for k in self.REQUIRED_KEYS:
                    if newpools[key][k] != oldpools[key][k]:
                        updated_pools.append(newpools[key])
                        break
            else:
                updated_pools.append(newpools[key])

        return updated_pools

    def _notify_capacity_usage(self,
                               context: cinder_context.RequestContext,
                               usage: list[dict]) -> None:
        if usage:
            for u in usage:
                volume_utils.notify_about_capacity_usage(
                    context, u, u['type'], None, None)
        LOG.debug("Publish storage capacity: %s.", usage)

    def _equal_after_convert(self, capability, value) -> bool:

        if isinstance(value, type(capability)) or capability is None:
            return value == capability

        if isinstance(capability, bool):
            return capability == strutils.bool_from_string(value)

        # We can not check or convert value parameter's type in
        # anywhere else.
        # If the capability and value are not in the same type,
        # we just convert them into string to compare them.
        return str(value) == str(capability)

    def get_az(self,
               volume: objects.Volume,
               availability_zone: Union[str, None]) -> Union[str, None]:
        if availability_zone:
            az = availability_zone
        elif volume:
            az = volume.availability_zone
        else:
            az = None
        return az

    def get_backup_host(self,
                        volume: objects.Volume,
                        availability_zone: Union[str, None],
                        driver=None) -> str:
        if volume:
            volume_host = volume_utils.extract_host(volume.host, 'host')
        else:
            volume_host = None
        az = self.get_az(volume, availability_zone)
        return self._get_available_backup_service_host(volume_host, az, driver)

    def _get_any_available_backup_service(self, availability_zone,
                                          driver=None):
        """Get an available backup service host.

        Get an available backup service host in the specified
        availability zone.
        """
        services = [srv for srv in self._list_backup_services(
            availability_zone, driver)]
        random.shuffle(services)
        return services[0] if services else None

    def _get_available_backup_service_host(self, host, az, driver=None) -> str:
        """Return an appropriate backup service host."""
        backup_host = None
        if not host or not CONF.backup_use_same_host:
            backup_host = self._get_any_available_backup_service(az, driver)
        elif self._is_backup_service_enabled(az, host):
            backup_host = host
        if not backup_host:
            raise exception.ServiceNotFound(service_id='cinder-backup')
        return backup_host

    def _list_backup_services(self, availability_zone, driver=None):
        """List all enabled backup services.

        :returns: list -- hosts for services that are enabled for backup.
        """
        services = []

        def _is_good_service(cap, driver, az) -> bool:
            if driver is None and az is None:
                return True
            match_driver = cap['driver_name'] == driver if driver else True
            if match_driver:
                if not az:
                    return True
                return cap['availability_zone'] == az
            return False

        for backend, capabilities in self.backup_service_states.items():
            if capabilities['backend_state']:
                if _is_good_service(capabilities, driver, availability_zone):
                    services.append(backend)

        return services

    def _az_matched(self,
                    service: objects.Service,
                    availability_zone: Optional[str]) -> bool:
        return ((not availability_zone) or
                service.availability_zone == availability_zone)

    def _is_backup_service_enabled(self,
                                   availability_zone: str,
                                   host: str) -> bool:
        """Check if there is a backup service available."""
        topic = constants.BACKUP_TOPIC
        ctxt = cinder_context.get_admin_context()
        services = objects.ServiceList.get_all_by_topic(
            ctxt, topic, disabled=False)
        for srv in services:
            if (self._az_matched(srv, availability_zone) and
                    srv.host == host and srv.is_up):
                return True
        return False
