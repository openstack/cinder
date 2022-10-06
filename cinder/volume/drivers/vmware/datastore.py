# Copyright (c) 2014 VMware, Inc.
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
Classes and utility methods for datastore selection.
"""

from collections.abc import Iterable
import random

from oslo_log import log as logging
from oslo_vmware import pbm
from oslo_vmware import vim_util

from cinder import coordination
from cinder import exception
from cinder.volume.drivers.vmware import exceptions as vmdk_exceptions


LOG = logging.getLogger(__name__)


class DatastoreType(object):
    """Supported datastore types."""

    NFS = "nfs"
    VMFS = "vmfs"
    VSAN = "vsan"
    VVOL = "vvol"
    NFS41 = "nfs41"

    _ALL_TYPES = {NFS, VMFS, VSAN, VVOL, NFS41}

    @staticmethod
    def get_all_types():
        return DatastoreType._ALL_TYPES


class DatastoreSelector(object):
    """Class for selecting datastores which satisfy input requirements."""

    HARD_AFFINITY_DS_TYPE = "hardAffinityDatastoreTypes"
    HARD_ANTI_AFFINITY_DS = "hardAntiAffinityDatastores"
    SIZE_BYTES = "sizeBytes"
    PROFILE_NAME = "storageProfileName"

    # TODO(vbala) Remove dependency on volumeops.
    def __init__(self, vops, session, max_objects, ds_regex=None,
                 random_ds=False, random_ds_range=None):
        self._vops = vops
        self._session = session
        self._max_objects = max_objects
        self._ds_regex = ds_regex
        self._profile_id_cache = {}
        self._random_ds = random_ds
        self._random_ds_range = random_ds_range

    @coordination.synchronized('vmware-datastore-profile-{profile_name}')
    def get_profile_id(self, profile_name):
        """Get vCenter profile ID for the given profile name.

        :param profile_name: profile name
        :return: vCenter profile ID
        :raises ProfileNotFoundException:
        """
        if profile_name in self._profile_id_cache:
            LOG.debug("Returning cached ID for profile: %s.", profile_name)
            return self._profile_id_cache[profile_name]

        profile_id = pbm.get_profile_id_by_name(self._session, profile_name)
        if profile_id is None:
            LOG.error("Storage profile: %s cannot be found in vCenter.",
                      profile_name)
            raise vmdk_exceptions.ProfileNotFoundException(
                storage_profile=profile_name)

        self._profile_id_cache[profile_name] = profile_id
        LOG.debug("Storage profile: %(name)s resolved to vCenter profile ID: "
                  "%(id)s.",
                  {'name': profile_name,
                   'id': profile_id})
        return profile_id

    def _filter_by_profile(self, datastores, profile_id):
        """Filter out input datastores that do not match the given profile."""
        cf = self._session.pbm.client.factory
        hubs = pbm.convert_datastores_to_hubs(cf, datastores)
        hubs = pbm.filter_hubs_by_profile(self._session, hubs, profile_id)
        hub_ids = [hub.hubId for hub in hubs]
        return {k: v for k, v in datastores.items()
                if vim_util.get_moref_value(k) in hub_ids}

    def is_host_in_buildup_cluster(self, host_ref, host_cluster_ref=None,
                                   cluster_cache=None):
        """Check if a host is in a cluster marked as in buildup

        :param host_ref: a ManagedObjectReference to HostSystem
        :param host_cluster_ref: (optional) ManagedObjectReference to
                             ClusterComputeResource pointing to the cluster of
                             the given host. Will be fetched if not given.
        :param cluster_cache: (optional) dict from ManagedObjectReference value
                              to dict (property name, property value) for
                              ClusterComputeResource objects. Can be set if the
                              required properties for
                              get_cluster_custom_attributes() were prefetched
                              for multiple clusters.
        """
        if cluster_cache is None:
            cluster_cache = {}

        if host_cluster_ref is None:
            host_cluster_ref = self._vops._get_parent(host_ref,
                                                      "ClusterComputeResource")

        host_cluster_value = vim_util.get_moref_value(host_cluster_ref)

        attrs = self._vops.get_cluster_custom_attributes(
            host_cluster_ref, props=cluster_cache.get(host_cluster_value))
        LOG.debug("Cluster %s custom attributes: %s",
                  host_cluster_value, attrs)

        if not attrs or 'buildup' not in attrs:
            return False

        def bool_from_str(bool_str):
            return bool_str.lower() == "true"

        return bool_from_str(attrs['buildup']['value'])

    def _is_host_usable(self, host_ref, host_prop_map=None):
        """Check a host's connectionState and inMaintenanceMode properties

        :param host_ref: a ManagedObjectReference to HostSystem
        :param host_prop_map: (optional) a dict from ManagedObjectReference
                              value to a dict (property name, property value).
                              Can be set if the required properties were
                              prefetched for multiple hosts.
        :return: boolean if the host is usable
        """
        if host_prop_map is None:
            host_prop_map = {}

        props = host_prop_map.get(host_ref.value)
        if props is None:
            props = self._get_host_properties(host_ref)
            host_prop_map[host_ref.value] = props

        connection_state = props.get('runtime.connectionState')
        in_maintenance = props.get('runtime.inMaintenanceMode')
        if None in (connection_state, in_maintenance):
            return False

        return (connection_state == 'connected' and
                not in_maintenance)

    def _filter_hosts(self, hosts):
        """Filter out hosts in buildup cluster or otherwise unusable"""
        if not hosts:
            return []

        if isinstance(hosts, Iterable):
            # prefetch host properties
            host_properties = ['runtime.connectionState',
                               'runtime.inMaintenanceMode', 'parent']
            host_prop_map = self._get_properties_for_morefs(
                'HostSystem', hosts, host_properties)

            # prefetch cluster properties
            host_cluster_refs = set(
                h_props['parent'] for h_props in host_prop_map.values()
                if h_props.get('parent'))
            cluster_prop_map = self._get_properties_for_morefs(
                'ClusterComputeResource', list(host_cluster_refs),
                ['availableField', 'customValue'])
        else:
            host_prop_map = cluster_prop_map = None
            hosts = [hosts]

        valid_hosts = []
        for host in hosts:
            host_ref_value = vim_util.get_moref_value(host)
            host_props = host_prop_map.get(host_ref_value, {})
            host_cluster_ref = host_props.get('parent')
            if self.is_host_in_buildup_cluster(
                    host, host_cluster_ref=host_cluster_ref,
                    cluster_cache=cluster_prop_map):
                continue

            if not self._is_host_usable(host, host_prop_map=host_prop_map):
                continue

            valid_hosts.append(host)

        return valid_hosts

    def is_datastore_usable(self, summary):
        return summary.accessible and not self._vops._in_maintenance(
            summary)

    def _filter_datastores(self,
                           datastores,
                           size_bytes,
                           profile_id,
                           hard_anti_affinity_ds,
                           hard_affinity_ds_types,
                           valid_host_refs=None):

        if not datastores:
            return

        def _is_valid_ds_type(summary):
            ds_type = summary.type.lower()
            return (ds_type in DatastoreType.get_all_types() and
                    (hard_affinity_ds_types is None or
                     ds_type in hard_affinity_ds_types))

        valid_host_refs = valid_host_refs or []
        valid_hosts = [vim_util.get_moref_value(host_ref)
                       for host_ref in valid_host_refs]

        def _is_ds_accessible_to_valid_host(host_mounts):
            for host_mount in host_mounts:
                if vim_util.get_moref_value(host_mount.key) in valid_hosts:
                    return True

        def _is_ds_valid(ds_ref, ds_props):
            summary = ds_props.get('summary')
            host_mounts = ds_props.get('host')
            if (summary is None or host_mounts is None):
                return False

            if self._ds_regex and not self._ds_regex.match(summary.name):
                return False

            if (hard_anti_affinity_ds and
                    vim_util.get_moref_value(ds_ref) in hard_anti_affinity_ds):
                return False

            if summary.capacity == 0 or summary.freeSpace < size_bytes:
                return False

            if (valid_hosts and
                    not _is_ds_accessible_to_valid_host(host_mounts)):
                return False

            return (_is_valid_ds_type(summary) and
                    self.is_datastore_usable(summary))

        datastores = {k: v for k, v in datastores.items()
                      if _is_ds_valid(k, v)}

        if datastores and profile_id:
            datastores = self._filter_by_profile(datastores, profile_id)

        return datastores

    def _get_object_properties(self, obj_content):
        props = {}
        if hasattr(obj_content, 'propSet'):
            prop_set = obj_content.propSet
            if prop_set:
                props = {prop.name: prop.val for prop in prop_set}
        return props

    def _get_datastores(self):
        vim = self._session.vim
        datastores = {}
        retrieve_result = self._session.invoke_api(
            vim_util,
            'get_objects',
            vim,
            'Datastore',
            self._max_objects,
            properties_to_collect=['host', 'summary'])

        with vim_util.WithRetrieval(vim, retrieve_result) as objects:
            for obj_content in objects:
                props = self._get_object_properties(obj_content)
                if ('host' in props and
                        hasattr(props['host'], 'DatastoreHostMount')):
                    props['host'] = props['host'].DatastoreHostMount
                datastores[obj_content.obj] = props

        return datastores

    def select_datastore_by_name(self, name):
        """Find a datastore by it's name.

            Returns a host_ref and datastore summary.
        """

        resource_pool = None
        datastore = None
        datastores = self._get_datastores()
        for k, v in datastores.items():
            if v['summary'].name == name:
                datastore = v

        if not datastore:
            # this shouldn't ever happen as the scheduler told us
            # to use this named datastore
            return (None, None, None)

        summary = datastore['summary']
        # pick a host that's available
        hosts = [host['key'] for host in datastore['host']]
        hosts = self._filter_hosts(hosts)
        if not hosts:
            raise exception.InvalidInput(
                "No hosts available for datastore '%s'" % name)

        host = random.choice(hosts)

        # host_ref = datastore['host'][0]['key']
        host_props = self._get_host_properties(host)
        parent = host_props.get('parent')

        resource_pool = self._get_resource_pool(parent)
        return (host, resource_pool, summary)

    def _get_host_properties(self, host_ref):
        properties = ['runtime.connectionState', 'runtime.inMaintenanceMode',
                      'parent']
        retrieve_result = self._session.invoke_api(vim_util,
                                                   'get_object_properties',
                                                   self._session.vim,
                                                   host_ref,
                                                   properties)

        if retrieve_result:
            return self._get_object_properties(retrieve_result[0])

    def _get_properties_for_morefs(self, type_, morefs, properties):
        """Fetch properties for the given morefs of type type_

        :param type_: a ManagedObject type
        :param morefs: a list of ManagedObjectReference for the given type_
        :param properties: a list of strings defining the properties to fetch
        :returns: a dict of ManagedObjectReference values mapped to a dict of
                  (property name, property value)
        """
        obj_prop_map = {}

        result = \
            self._session.invoke_api(
                vim_util,
                "get_properties_for_a_collection_of_objects",
                self._session.vim,
                type_, morefs,
                properties)
        with vim_util.WithRetrieval(self._session.vim, result) as objects:
            for obj in objects:
                props = self._get_object_properties(obj)

                obj_prop_map[vim_util.get_moref_value(obj.obj)] = {
                    prop: props.get(prop) for prop in properties}

        return obj_prop_map

    def _get_resource_pool(self, cluster_ref):
        return self._session.invoke_api(vim_util,
                                        'get_object_property',
                                        self._session.vim,
                                        cluster_ref,
                                        'resourcePool')

    def _select_best_datastore(self, datastores, valid_host_refs=None):

        if not datastores:
            return

        def _sort_key(ds_props):
            host = ds_props.get('host')
            summary = ds_props.get('summary')
            space_utilization = (1.0 -
                                 (summary.freeSpace / float(summary.capacity)))
            return (-len(host), space_utilization)

        host_prop_map = {}

        valid_host_refs = valid_host_refs or []
        valid_hosts = [vim_util.get_moref_value(host_ref)
                       for host_ref in valid_host_refs]

        def _select_host(host_mounts, host_prop_map):
            random.shuffle(host_mounts)
            for host_mount in host_mounts:
                host_mount_key_value = vim_util.get_moref_value(host_mount.key)
                if valid_hosts and host_mount_key_value not in valid_hosts:
                    continue
                if (self._vops._is_usable(host_mount.mountInfo) and
                        self._is_host_usable(host_mount.key,
                                             host_prop_map=host_prop_map)):
                    return host_mount.key

        sorted_ds_props = sorted(datastores.values(), key=_sort_key)
        if self._random_ds:
            LOG.debug('Shuffling best datastore selection.')
            if self._random_ds_range:
                sorted_ds_props = sorted_ds_props[:self._random_ds_range]
            random.shuffle(sorted_ds_props)

        for ds_props in sorted_ds_props:
            host_ref = _select_host(
                ds_props['host'], host_prop_map=host_prop_map)
            if host_ref:
                host_ref_value = vim_util.get_moref_value(host_ref)
                rp = self._get_resource_pool(
                    host_prop_map[host_ref_value]['parent'])
                return (host_ref, rp, ds_props['summary'])

    def select_datastore(self, req, hosts=None):
        """Selects a datastore satisfying the given requirements.

        A datastore which is connected to maximum number of hosts is
        selected. Ties if any are broken based on space utilization--
        datastore with least space utilization is preferred. It returns
        the selected datastore's summary along with a host and resource
        pool where the volume can be created.

        :param req: selection requirements
        :param hosts: list of hosts to consider
        :return: (host, resourcePool, summary)
        """
        LOG.debug("Using requirements: %s for datastore selection.", req)

        hard_affinity_ds_types = req.get(
            DatastoreSelector.HARD_AFFINITY_DS_TYPE)
        hard_anti_affinity_datastores = req.get(
            DatastoreSelector.HARD_ANTI_AFFINITY_DS)
        size_bytes = req[DatastoreSelector.SIZE_BYTES]
        profile_name = req.get(DatastoreSelector.PROFILE_NAME)

        profile_id = None
        if profile_name is not None:
            profile_id = self.get_profile_id(profile_name)

        datastores = self._get_datastores()
        # We don't want to use hosts in buildup
        LOG.debug("FILTER hosts start {}".format(hosts))
        valid_hosts = self._filter_hosts(hosts)
        LOG.debug("FILTERED hosts valid {}".format(valid_hosts))
        datastores = self._filter_datastores(datastores,
                                             size_bytes,
                                             profile_id,
                                             hard_anti_affinity_datastores,
                                             hard_affinity_ds_types,
                                             valid_host_refs=valid_hosts)
        res = self._select_best_datastore(datastores,
                                          valid_host_refs=valid_hosts)
        LOG.debug("Selected (host, resourcepool, datastore): %s", res)
        return res

    def is_datastore_compliant(self, datastore, profile_name):
        """Check if the datastore is compliant with given profile.

        :param datastore: datastore to check the compliance
        :param profile_name: profile to check the compliance against
        :return: True if the datastore is compliant; False otherwise
        :raises ProfileNotFoundException:
        """
        LOG.debug("Checking datastore: %(datastore)s compliance against "
                  "profile: %(profile)s.",
                  {'datastore': datastore,
                   'profile': profile_name})
        if profile_name is None:
            # Any datastore is trivially compliant with a None profile.
            return True

        profile_id = self.get_profile_id(profile_name)
        # _filter_by_profile expects a map of datastore references to its
        # properties. It only uses the properties to construct a map of
        # filtered datastores to its properties. Here we don't care about
        # the datastore property, so pass it as None.
        is_compliant = bool(self._filter_by_profile({datastore: None},
                                                    profile_id))
        LOG.debug("Compliance is %(is_compliant)s for datastore: "
                  "%(datastore)s against profile: %(profile)s.",
                  {'is_compliant': is_compliant,
                   'datastore': datastore,
                   'profile': profile_name})
        return is_compliant
