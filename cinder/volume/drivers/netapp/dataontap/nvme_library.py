# Copyright (c) 2023 NetApp, Inc. All rights reserved.
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
Volume driver library for NetApp C-mode NVMe storage systems.
"""


import sys
import uuid

from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import units
import six

from cinder import exception
from cinder.i18n import _
from cinder.volume.drivers.netapp.dataontap.client import api as netapp_api
from cinder.volume.drivers.netapp.dataontap.performance import perf_cmode
from cinder.volume.drivers.netapp.dataontap.utils import capabilities
from cinder.volume.drivers.netapp.dataontap.utils import loopingcalls
from cinder.volume.drivers.netapp.dataontap.utils import utils as dot_utils
from cinder.volume.drivers.netapp import options as na_opts
from cinder.volume.drivers.netapp import utils as na_utils
from cinder.volume import volume_utils

LOG = logging.getLogger(__name__)


class NetAppNamespace(object):
    """Represents a namespace on NetApp storage."""

    def __init__(self, handle, name, size, metadata_dict):
        self.handle = handle
        self.name = name
        self.size = size
        self.metadata = metadata_dict or {}

    def get_metadata_property(self, prop):
        """Get the metadata property of a namespace."""
        if prop in self.metadata:
            return self.metadata[prop]
        name = self.name
        LOG.debug("No metadata property %(prop)s defined for the namespace "
                  "%(name)s", {'prop': prop, 'name': name})

    def __str__(self, *args, **kwargs):
        return ('NetApp namespace [handle:%s, name:%s, size:%s, metadata:%s]'
                % (self.handle, self.name, self.size, self.metadata))


@six.add_metaclass(volume_utils.TraceWrapperMetaclass)
class NetAppNVMeStorageLibrary(object):
    """NetApp NVMe storage library for Data ONTAP."""

    # do not increment this as it may be used in volume type definitions.
    VERSION = "1.0.0"
    REQUIRED_FLAGS = ['netapp_login', 'netapp_password',
                      'netapp_server_hostname']
    ALLOWED_NAMESPACE_OS_TYPES = ['aix', 'linux', 'vmware', 'windows']
    ALLOWED_SUBSYSTEM_HOST_TYPES = ['aix', 'linux', 'vmware', 'windows']
    DEFAULT_NAMESPACE_OS = 'linux'
    DEFAULT_HOST_TYPE = 'linux'
    DEFAULT_FILTER_FUNCTION = 'capabilities.utilization < 70'
    DEFAULT_GOODNESS_FUNCTION = '100 - capabilities.utilization'
    REQUIRED_CMODE_FLAGS = ['netapp_vserver']
    NVME_PORT = 4420
    NVME_TRANSPORT = "tcp"

    def __init__(self, driver_name, driver_protocol, **kwargs):

        na_utils.validate_instantiation(**kwargs)

        self.driver_name = driver_name
        self.driver_protocol = driver_protocol
        self.rest_client = None
        self._stats = {}
        self.namespace_table = {}
        self.namespace_ostype = None
        self.host_type = None
        self.app_version = kwargs.get("app_version", "unknown")
        self.host = kwargs.get('host')
        self.backend_name = self.host.split('@')[1]

        self.configuration = kwargs['configuration']
        self.configuration.append_config_values(na_opts.netapp_connection_opts)
        self.configuration.append_config_values(na_opts.netapp_basicauth_opts)
        self.configuration.append_config_values(na_opts.netapp_transport_opts)
        self.configuration.append_config_values(
            na_opts.netapp_provisioning_opts)
        self.configuration.append_config_values(na_opts.netapp_san_opts)
        self.configuration.append_config_values(na_opts.netapp_cluster_opts)

        self.max_over_subscription_ratio = (
            volume_utils.get_max_over_subscription_ratio(
                self.configuration.max_over_subscription_ratio,
                supports_auto=True))
        self.reserved_percentage = self.configuration.reserved_percentage
        self.loopingcalls = loopingcalls.LoopingCalls()

    def do_setup(self, context):
        na_utils.check_flags(self.REQUIRED_FLAGS, self.configuration)
        self.namespace_ostype = (self.configuration.netapp_namespace_ostype
                                 or self.DEFAULT_NAMESPACE_OS)
        self.host_type = (self.configuration.netapp_host_type
                          or self.DEFAULT_HOST_TYPE)

        na_utils.check_flags(self.REQUIRED_CMODE_FLAGS, self.configuration)

        # NOTE(felipe_rodrigues): NVMe driver is only available with
        # REST client.
        self.client = dot_utils.get_client_for_backend(
            self.backend_name, force_rest=True)
        self.vserver = self.client.vserver

        # Storage service catalog.
        self.ssc_library = capabilities.CapabilitiesLibrary(
            self.driver_protocol, self.vserver, self.client,
            self.configuration)

        self.ssc_library.check_api_permissions()

        self.using_cluster_credentials = (
            self.ssc_library.cluster_user_supported())

        # Performance monitoring library.
        self.perf_library = perf_cmode.PerformanceCmodeLibrary(
            self.client)

    def _update_ssc(self):
        """Refresh the storage service catalog with the latest set of pools."""

        self.ssc_library.update_ssc(self._get_flexvol_to_pool_map())

    def _get_flexvol_to_pool_map(self):
        """Get the flexvols that match the pool name search pattern.

        The map is of the format suitable for seeding the storage service
        catalog: {<flexvol_name> : {'pool_name': <flexvol_name>}}
        """

        pool_regex = na_utils.get_pool_name_filter_regex(self.configuration)

        pools = {}
        flexvol_names = self.client.list_flexvols()

        for flexvol_name in flexvol_names:

            msg_args = {
                'flexvol': flexvol_name,
                'vol_pattern': pool_regex.pattern,
            }

            if pool_regex.match(flexvol_name):
                msg = "Volume '%(flexvol)s' matches %(vol_pattern)s"
                LOG.debug(msg, msg_args)
                pools[flexvol_name] = {'pool_name': flexvol_name}
            else:
                msg = "Volume '%(flexvol)s' does not match %(vol_pattern)s"
                LOG.debug(msg, msg_args)

        return pools

    def check_for_setup_error(self):
        """Check that the driver is working and can communicate.

        Discovers the namespaces on the NetApp server.
        """
        if not self._get_flexvol_to_pool_map():
            msg = _('No pools are available for provisioning volumes. '
                    'Ensure that the configuration option '
                    'netapp_pool_name_search_pattern is set correctly.')
            raise na_utils.NetAppDriverException(msg)
        self._add_looping_tasks()

        if self.namespace_ostype not in self.ALLOWED_NAMESPACE_OS_TYPES:
            msg = _("Invalid value for NetApp configuration"
                    " option netapp_namespace_ostype.")
            LOG.error(msg)
            raise na_utils.NetAppDriverException(msg)
        if self.host_type not in self.ALLOWED_SUBSYSTEM_HOST_TYPES:
            msg = _("Invalid value for NetApp configuration"
                    " option netapp_host_type.")
            LOG.error(msg)
            raise na_utils.NetAppDriverException(msg)

        namespace_list = self.client.get_namespace_list()
        self._extract_and_populate_namespaces(namespace_list)
        LOG.debug("Success getting list of namespace from server.")

        self.loopingcalls.start_tasks()

    def _add_looping_tasks(self):
        """Add tasks that need to be executed at a fixed interval.

        Inheriting class overrides and then explicitly calls this method.
        """
        # Note(cknight): Run the update once in the current thread to prevent a
        # race with the first invocation of _update_volume_stats.
        self._update_ssc()

        # Add the task that updates the slow-changing storage service catalog.
        self.loopingcalls.add_task(self._update_ssc,
                                   loopingcalls.ONE_HOUR,
                                   loopingcalls.ONE_HOUR)

        # Add the task that logs EMS messages.
        self.loopingcalls.add_task(
            self._handle_ems_logging,
            loopingcalls.ONE_HOUR)

    def _handle_ems_logging(self):
        """Log autosupport messages."""

        base_ems_message = dot_utils.build_ems_log_message_0(
            self.driver_name, self.app_version)
        self.client.send_ems_log_message(base_ems_message)

        pool_ems_message = dot_utils.build_ems_log_message_1(
            self.driver_name, self.app_version, self.vserver,
            self.ssc_library.get_ssc_flexvol_names(), [])
        self.client.send_ems_log_message(pool_ems_message)

    def get_pool(self, volume):
        """Return pool name where volume resides.

        :param volume: The volume hosted by the driver.
        :return: Name of the pool where given volume is hosted.
        """
        name = volume['name']
        metadata = self._get_namespace_attr(name, 'metadata') or dict()
        return metadata.get('Volume', None)

    def create_volume(self, volume):
        """Driver entry point for creating a new volume (ONTAP namespace)."""

        LOG.debug('create_volume on %s', volume['host'])

        # get Data ONTAP volume name as pool name.
        pool_name = volume_utils.extract_host(volume['host'], level='pool')
        if pool_name is None:
            msg = _("Pool is not available in the volume host field.")
            raise exception.InvalidHost(reason=msg)

        namespace = volume.name
        size = int(volume['size']) * units.Gi
        metadata = {'OsType': self.namespace_ostype,
                    'Path': '/vol/%s/%s' % (pool_name, namespace)}

        try:
            self.client.create_namespace(pool_name, namespace, size, metadata)
        except Exception:
            LOG.exception("Exception creating namespace %(name)s in pool "
                          "%(pool)s.", {'name': namespace, 'pool': pool_name})
            msg = _("Volume %s could not be created.")
            raise exception.VolumeBackendAPIException(data=msg % namespace)
        LOG.debug('Created namespace with name %(name)s.', {'name': namespace})

        metadata['Volume'] = pool_name
        metadata['Qtree'] = None
        handle = self._create_namespace_handle(metadata)
        self._add_namespace_to_table(
            NetAppNamespace(handle, namespace, size, metadata))

        return

    def delete_volume(self, volume):
        """Driver entry point for destroying existing volumes."""
        self._delete_namespace(volume['name'])

    def _delete_namespace(self, namespace_name):
        """Helper method to delete namespace backing a volume or snapshot."""

        metadata = self._get_namespace_attr(namespace_name, 'metadata')
        if metadata:
            try:
                self.client.destroy_namespace(metadata['Path'])
            except netapp_api.NaApiError as e:
                if e.code in netapp_api.REST_NAMESPACE_EOBJECTNOTFOUND:
                    LOG.warning("Failure deleting namespace %(name)s. "
                                "%(message)s",
                                {'name': namespace_name, 'message': e})
                else:
                    error_message = (_('A NetApp Api Error occurred: %s') % e)
                    raise na_utils.NetAppDriverException(error_message)
            self.namespace_table.pop(namespace_name)
        else:
            LOG.warning("No entry in namespace table for volume/snapshot"
                        " %(name)s.", {'name': namespace_name})

    def ensure_export(self, context, volume):
        """Driver entry point to get the export info for an existing volume."""
        handle = self._get_namespace_attr(volume['name'], 'handle')
        return {'provider_location': handle}

    def create_export(self, context, volume):
        """Driver entry point to get the export info for a new volume."""
        handle = self._get_namespace_attr(volume['name'], 'handle')
        return {'provider_location': handle}

    def remove_export(self, context, volume):
        """Driver entry point to remove an export for a volume.

        Since exporting is idempotent in this driver, we have nothing
        to do for unexporting.
        """

        pass

    def create_snapshot(self, snapshot):
        """Driver entry point for creating a snapshot.

        This driver implements snapshots by using efficient single-file
        (namespace) cloning.
        """
        self._create_snapshot(snapshot)

    def _create_snapshot(self, snapshot):
        vol_name = snapshot['volume_name']
        snapshot_name = snapshot['name']
        namespace = self._get_namespace_from_table(vol_name)
        self._clone_namespace(namespace.name, snapshot_name)

    def _clone_namespace(self, name, new_name):
        """Clone namespace with the given handle to the new name."""
        metadata = self._get_namespace_attr(name, 'metadata')
        volume = metadata['Volume']

        self.client.clone_namespace(volume, name, new_name)

        LOG.debug("Cloned namespace with new name %s", new_name)
        namespace = self.client.get_namespace_by_args(
            vserver=self.vserver, path=f'/vol/{volume}/{new_name}')
        if len(namespace) == 0:
            msg = _("No cloned namespace named %s found on the filer.")
            raise exception.VolumeBackendAPIException(data=msg % new_name)

        cloned_namespace = namespace[0]
        self._add_namespace_to_table(
            NetAppNamespace(
                f"{cloned_namespace['Vserver']}:{cloned_namespace['Path']}",
                new_name,
                cloned_namespace['Size'],
                cloned_namespace))

    def delete_snapshot(self, snapshot):
        """Driver entry point for deleting a snapshot."""
        self._delete_namespace(snapshot['name'])
        LOG.debug("Snapshot %s deletion successful.", snapshot['name'])

    def create_volume_from_snapshot(self, volume, snapshot):
        source = {'name': snapshot['name'], 'size': snapshot['volume_size']}
        self._clone_source_to_destination(source, volume)

    def create_cloned_volume(self, volume, src_vref):
        src_namespace = self._get_namespace_from_table(src_vref['name'])
        source = {'name': src_namespace.name, 'size': src_vref['size']}
        self._clone_source_to_destination(source, volume)

    def _clone_source_to_destination(self, source, destination_volume):
        source_size = source['size']
        destination_size = destination_volume['size']

        source_name = source['name']
        destination_name = destination_volume['name']

        try:
            self._clone_namespace(source_name, destination_name)

            if destination_size != source_size:

                try:
                    self._extend_volume(destination_volume, destination_size)
                except Exception:
                    with excutils.save_and_reraise_exception():
                        LOG.error("Resizing %s failed. Cleaning volume.",
                                  destination_volume['id'])
                        self.delete_volume(destination_volume)

        except Exception:
            LOG.exception("Exception cloning volume %(name)s from source "
                          "volume %(source)s.",
                          {'name': destination_name, 'source': source_name})

            msg = _("Volume %s could not be created from source volume.")
            raise exception.VolumeBackendAPIException(
                data=msg % destination_name)

    def _create_namespace_handle(self, metadata):
        """Returns namespace handle based on filer type."""
        return '%s:%s' % (self.vserver, metadata['Path'])

    def _extract_namespace_info(self, namespace):
        """Extracts the namespace from API and populates the table."""

        path = namespace['Path']
        (_rest, _splitter, name) = path.rpartition('/')
        handle = self._create_namespace_handle(namespace)
        size = namespace['Size']
        return NetAppNamespace(handle, name, size, namespace)

    def _extract_and_populate_namespaces(self, api_namespaces):
        """Extracts the namespaces from API and populates the table."""

        for namespace in api_namespaces:
            discovered_namespace = self._extract_namespace_info(namespace)
            self._add_namespace_to_table(discovered_namespace)

    def _add_namespace_to_table(self, namespace):
        """Adds namespace to cache table."""
        if not isinstance(namespace, NetAppNamespace):
            msg = _("Object is not a NetApp namespace.")
            raise exception.VolumeBackendAPIException(data=msg)
        self.namespace_table[namespace.name] = namespace

    def _get_namespace_from_table(self, name):
        """Gets namespace from cache table.

        Refreshes cache if namespace not found in cache.
        """
        namespace = self.namespace_table.get(name)
        if namespace is None:
            namespace_list = self.client.get_namespace_list()
            self._extract_and_populate_namespaces(namespace_list)
            namespace = self.namespace_table.get(name)
            if namespace is None:
                raise exception.VolumeNotFound(volume_id=name)
        return namespace

    def _get_namespace_attr(self, name, attr):
        """Get the namespace attribute if found else None."""
        try:
            attr = getattr(self._get_namespace_from_table(name), attr)
            return attr
        except exception.VolumeNotFound as e:
            LOG.error("Message: %s", e.msg)
        except Exception as e:
            LOG.error("Error getting namespace attribute. Exception: %s", e)
        return None

    def get_volume_stats(self, refresh=False, filter_function=None,
                         goodness_function=None):
        """Get volume stats.

        If 'refresh' is True, update the stats first.
        """

        if refresh:
            self._update_volume_stats(filter_function=filter_function,
                                      goodness_function=goodness_function)
        return self._stats

    def _update_volume_stats(self, filter_function=None,
                             goodness_function=None):
        """Retrieve backend stats."""

        LOG.debug('Updating volume stats')
        data = {}
        backend_name = self.configuration.safe_get('volume_backend_name')
        data['volume_backend_name'] = backend_name or self.driver_name
        data['vendor_name'] = 'NetApp'
        data['driver_version'] = self.VERSION
        data['storage_protocol'] = self.driver_protocol
        data['pools'] = self._get_pool_stats(
            filter_function=filter_function,
            goodness_function=goodness_function)
        data['sparse_copy_volume'] = True
        data['replication_enabled'] = False

        self._stats = data

    def _get_pool_stats(self, filter_function=None, goodness_function=None):
        """Retrieve pool (Data ONTAP flexvol) stats.

        Pool statistics are assembled from static driver capabilities, the
        Storage Service Catalog of flexvol attributes, and real-time capacity
        and controller utilization metrics.  The pool name is the flexvol name.
        """

        pools = []

        ssc = self.ssc_library.get_ssc()
        if not ssc:
            return pools

        # Utilization and performance metrics require cluster-scoped
        # credentials
        if self.using_cluster_credentials:
            # Get up-to-date node utilization metrics just once
            self.perf_library.update_performance_cache(ssc)

            # Get up-to-date aggregate capacities just once
            aggregates = self.ssc_library.get_ssc_aggregates()
            aggr_capacities = self.client.get_aggregate_capacities(
                aggregates)
        else:
            aggr_capacities = {}

        for ssc_vol_name, ssc_vol_info in ssc.items():

            pool = dict()

            # Add storage service catalog data
            pool.update(ssc_vol_info)

            # Add driver capabilities and config info
            pool['QoS_support'] = False
            pool['multiattach'] = False
            pool['online_extend_support'] = False
            pool['consistencygroup_support'] = False
            pool['consistent_group_snapshot_enabled'] = False
            pool['reserved_percentage'] = self.reserved_percentage
            pool['max_over_subscription_ratio'] = (
                self.max_over_subscription_ratio)

            # Add up-to-date capacity info
            capacity = self.client.get_flexvol_capacity(
                flexvol_name=ssc_vol_name)

            size_total_gb = capacity['size-total'] / units.Gi
            pool['total_capacity_gb'] = na_utils.round_down(size_total_gb)

            size_available_gb = capacity['size-available'] / units.Gi
            pool['free_capacity_gb'] = na_utils.round_down(size_available_gb)

            if self.configuration.netapp_driver_reports_provisioned_capacity:
                namespaces = self.client.get_namespace_sizes_by_volume(
                    ssc_vol_name)
                provisioned_cap = 0
                for namespace in namespaces:
                    namespace_name = namespace['path'].split('/')[-1]
                    # Filtering namespaces that matches the volume name
                    # template to exclude snapshots.
                    if volume_utils.extract_id_from_volume_name(
                            namespace_name):
                        provisioned_cap = provisioned_cap + namespace['size']
                pool['provisioned_capacity_gb'] = na_utils.round_down(
                    float(provisioned_cap) / units.Gi)

            if self.using_cluster_credentials:
                dedupe_used = self.client.get_flexvol_dedupe_used_percent(
                    ssc_vol_name)
            else:
                dedupe_used = 0.0
            pool['netapp_dedupe_used_percent'] = na_utils.round_down(
                dedupe_used)

            aggregate_name = ssc_vol_info.get('netapp_aggregate')
            aggr_capacity = aggr_capacities.get(aggregate_name, {})
            pool['netapp_aggregate_used_percent'] = aggr_capacity.get(
                'percent-used', 0)

            # Add utilization data
            utilization = self.perf_library.get_node_utilization_for_pool(
                ssc_vol_name)
            pool['utilization'] = na_utils.round_down(utilization)
            pool['filter_function'] = filter_function
            pool['goodness_function'] = goodness_function

            pools.append(pool)

        return pools

    def get_default_filter_function(self):
        """Get the default filter_function string."""
        return self.DEFAULT_FILTER_FUNCTION

    def get_default_goodness_function(self):
        """Get the default goodness_function string."""
        return self.DEFAULT_GOODNESS_FUNCTION

    def extend_volume(self, volume, new_size):
        """Driver entry point to increase the size of a volume."""
        self._extend_volume(volume, new_size)

    def _extend_volume(self, volume, new_size):
        """Extend an existing volume to the new size."""
        name = volume['name']
        namespace = self._get_namespace_from_table(name)
        path = namespace.metadata['Path']
        curr_size_bytes = str(namespace.size)
        new_size_bytes = str(int(new_size) * units.Gi)
        # Reused by clone scenarios.
        # Hence comparing the stored size.
        if curr_size_bytes == new_size_bytes:
            LOG.info("No need to extend volume %s"
                     " as it is already the requested new size.", name)
            return

        self.client.namespace_resize(path, new_size_bytes)

        self.namespace_table[name].size = new_size_bytes

    def _get_or_create_subsystem(self, host_nqn, host_os_type):
        """Checks for an subsystem for a host.

        Creates subsystem if not already present with given host os type and
        adds the host.
        """
        # Backend supports different subsystems with the same hosts, so
        # instead of reusing non OpenStack subsystem, we make sure we only use
        # our own, thus being compatible with custom subsystem.
        subsystems = self.client.get_subsystem_by_host(
            host_nqn)
        if subsystems:
            subsystem_name = subsystems[0]['name']
            host_os_type = subsystems[0]['os_type']
        else:
            subsystem_name = na_utils.OPENSTACK_PREFIX + str(uuid.uuid4())
            self.client.create_subsystem(subsystem_name, host_os_type,
                                         host_nqn)

        return subsystem_name, host_os_type

    def _find_mapped_namespace_subsystem(self, path, host_nqn):
        """Find an subsystem for a namespace mapped to the given host."""
        subsystems = [subsystem['name'] for subsystem in
                      self.client.get_subsystem_by_host(host_nqn)]

        # Map subsystem name to namespace-id for the requested host.
        namespace_map = {v['subsystem']: v['uuid']
                         for v in self.client.get_namespace_map(path)
                         if v['subsystem'] in subsystems}

        subsystem_name = n_uuid = None
        # Give preference to OpenStack subsystems, just use the last one if not
        # present to allow unmapping old mappings that used a custom subsystem.
        for subsystem_name, n_uuid in namespace_map.items():
            if subsystem_name.startswith(na_utils.OPENSTACK_PREFIX):
                break

        return subsystem_name, n_uuid

    def _map_namespace(self, name, host_nqn):
        """Maps namespace to the host nqn and returns its ID assigned."""

        subsystem_name, subsystem_host_os = self._get_or_create_subsystem(
            host_nqn, self.host_type)
        if subsystem_host_os != self.host_type:
            LOG.warning("Namespace misalignment may occur for current"
                        " subsystem %(sub_name)s with host OS type"
                        " %(sub_os)s. Please configure subsystem manually"
                        " according to the type of the host OS.",
                        {'sub_name': subsystem_name,
                         'sub_os': subsystem_host_os})

        metadata = self._get_namespace_attr(name, 'metadata')
        path = metadata['Path']
        try:
            ns_uuid = self.client.map_namespace(
                path, subsystem_name,)
            return subsystem_name, ns_uuid
        except netapp_api.NaApiError:
            exc_info = sys.exc_info()
            (subsystem_name, ns_uuid) = self._find_mapped_namespace_subsystem(
                path, host_nqn)
            if ns_uuid is not None and subsystem_name:
                return subsystem_name, ns_uuid
            else:
                six.reraise(*exc_info)

    def initialize_connection(self, volume, connector):
        """Initializes the connection and returns connection info.

        Assign any created volume to a compute node/host so that it can be
        used from that host. Example return values:

        .. code-block:: default

            {
                'driver_volume_type': 'nvmeof',
                'data': {
                    'target_nqn' 'nqn.1992-01.example.com:subsystem',
                    'host_nqn': 'nqn.1992-01.example.com:string',
                    'portals': [
                        ('10.10.10.10', '4420', 'tcp')
                    ],
                    'uuid': 'a1129e6f-8497-4c0c-be01-3eab1ba684ed'
                }
            }

        """
        host_nqn = connector.get("nqn")
        if not host_nqn:
            raise exception.VolumeBackendAPIException(
                data=_("Initialize connection error: no host nqn available!"))

        name = volume['name']
        subsystem, namespace_uuid = self._map_namespace(name, host_nqn)

        LOG.debug("Mapped namespace %(name)s to the host NQN %(host_nqn)s",
                  {'name': name, 'host_nqn': host_nqn})

        target_nqn = self.client.get_nvme_subsystem_nqn(subsystem)
        if not target_nqn:
            msg = _('Failed to get subsystem %(subsystem)s target NQN for the '
                    'namespace %(name)s')
            msg_args = {'subsystem': subsystem, 'name': name}
            raise exception.VolumeBackendAPIException(data=msg % msg_args)

        target_portals = self.client.get_nvme_target_portals()
        if not target_portals:
            msg = _('Failed to get target portals for the namespace %s')
            raise exception.VolumeBackendAPIException(
                data=msg % name)

        portal = (target_portals[0], self.NVME_PORT, self.NVME_TRANSPORT)
        data = {
            "target_nqn": str(target_nqn),
            "host_nqn": host_nqn,
            "portals": [portal],
            "vol_uuid": namespace_uuid
        }
        conn_info = {"driver_volume_type": "nvmeof", "data": data}
        LOG.debug("Initialize connection info: %s", conn_info)

        return conn_info

    def _unmap_namespace(self, path, host_nqn):
        """Unmaps a namespace from given host."""

        namespace_unmap_list = []
        if host_nqn:
            (subsystem, _) = self._find_mapped_namespace_subsystem(
                path, host_nqn)
            namespace_unmap_list.append((path, subsystem))
        else:
            namespace_maps = self.client.get_namespace_map(path)
            namespace_unmap_list = [
                (path, m['subsystem']) for m in namespace_maps]

        for _path, _subsystem in namespace_unmap_list:
            self.client.unmap_namespace(_path, _subsystem)

    def terminate_connection(self, volume, connector, **kwargs):
        """Driver entry point to unattach a volume from an instance.

        Unmask the namespace on the storage system so the given initiator can
        no longer access it.
        """

        name = volume['name']
        host_nqn = None
        if connector is None:
            LOG.debug('Unmapping namespace %(name)s from all hosts.',
                      {'name': name})
        else:
            host_nqn = connector.get("nqn")
            LOG.debug("Unmapping namespace %(name)s from the host "
                      "%(host_nqn)s", {'name': name, 'host_nqn': host_nqn})

        metadata = self._get_namespace_attr(name, 'metadata')
        path = metadata['Path']
        self._unmap_namespace(path, host_nqn)
