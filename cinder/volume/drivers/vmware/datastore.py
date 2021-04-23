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

import random

from oslo_log import log as logging
from oslo_vmware import pbm
from oslo_vmware import vim_util

from cinder import coordination
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
    def __init__(self, vops, session, max_objects, ds_regex=None):
        self._vops = vops
        self._session = session
        self._max_objects = max_objects
        self._ds_regex = ds_regex
        self._profile_id_cache = {}

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

        def _is_ds_usable(summary):
            return summary.accessible and not self._vops._in_maintenance(
                summary)

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

            return _is_valid_ds_type(summary) and _is_ds_usable(summary)

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
        datastores = {}
        retrieve_result = self._session.invoke_api(
            vim_util,
            'get_objects',
            self._session.vim,
            'Datastore',
            self._max_objects,
            properties_to_collect=['host', 'summary'])

        while retrieve_result:
            if retrieve_result.objects:
                for obj_content in retrieve_result.objects:
                    props = self._get_object_properties(obj_content)
                    if ('host' in props and
                            hasattr(props['host'], 'DatastoreHostMount')):
                        props['host'] = props['host'].DatastoreHostMount
                    datastores[obj_content.obj] = props
            retrieve_result = self._session.invoke_api(vim_util,
                                                       'continue_retrieval',
                                                       self._session.vim,
                                                       retrieve_result)

        return datastores

    def _get_host_properties(self, host_ref):
        retrieve_result = self._session.invoke_api(vim_util,
                                                   'get_object_properties',
                                                   self._session.vim,
                                                   host_ref,
                                                   ['runtime', 'parent'])

        if retrieve_result:
            return self._get_object_properties(retrieve_result[0])

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

        def _is_host_usable(host_ref):
            props = host_prop_map.get(vim_util.get_moref_value(host_ref))
            if props is None:
                props = self._get_host_properties(host_ref)
                host_prop_map[vim_util.get_moref_value(host_ref)] = props

            runtime = props.get('runtime')
            parent = props.get('parent')
            if runtime and parent:
                return (runtime.connectionState == 'connected' and
                        not runtime.inMaintenanceMode)
            else:
                return False

        valid_host_refs = valid_host_refs or []
        valid_hosts = [vim_util.get_moref_value(host_ref)
                       for host_ref in valid_host_refs]

        def _select_host(host_mounts):
            random.shuffle(host_mounts)
            for host_mount in host_mounts:
                host_mount_key_value = vim_util.get_moref_value(host_mount.key)
                if valid_hosts and host_mount_key_value not in valid_hosts:
                    continue
                if (self._vops._is_usable(host_mount.mountInfo) and
                        _is_host_usable(host_mount.key)):
                    return host_mount.key

        sorted_ds_props = sorted(datastores.values(), key=_sort_key)
        for ds_props in sorted_ds_props:
            host_ref = _select_host(ds_props['host'])
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
        datastores = self._filter_datastores(datastores,
                                             size_bytes,
                                             profile_id,
                                             hard_anti_affinity_datastores,
                                             hard_affinity_ds_types,
                                             valid_host_refs=hosts)
        res = self._select_best_datastore(datastores, valid_host_refs=hosts)
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
