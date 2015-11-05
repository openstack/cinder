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

from oslo_log import log as logging
from oslo_utils import excutils
from oslo_vmware import exceptions
from oslo_vmware import pbm

from cinder.i18n import _LE, _LW
from cinder.volume.drivers.vmware import exceptions as vmdk_exceptions


LOG = logging.getLogger(__name__)


class DatastoreType(object):
    """Supported datastore types."""

    NFS = "nfs"
    VMFS = "vmfs"
    VSAN = "vsan"

    _ALL_TYPES = {NFS, VMFS, VSAN}

    @staticmethod
    def get_all_types():
        return DatastoreType._ALL_TYPES


class DatastoreSelector(object):
    """Class for selecting datastores which satisfy input requirements."""

    HARD_AFFINITY_DS_TYPE = "hardAffinityDatastoreTypes"
    HARD_ANTI_AFFINITY_DS = "hardAntiAffinityDatastores"
    PREF_UTIL_THRESH = "preferredUtilizationThreshold"
    SIZE_BYTES = "sizeBytes"
    PROFILE_NAME = "storageProfileName"

    # TODO(vbala) Remove dependency on volumeops.
    def __init__(self, vops, session):
        self._vops = vops
        self._session = session

    def get_profile_id(self, profile_name):
        """Get vCenter profile ID for the given profile name.

        :param profile_name: profile name
        :return: vCenter profile ID
        :raises: ProfileNotFoundException
        """
        profile_id = pbm.get_profile_id_by_name(self._session, profile_name)
        if profile_id is None:
            LOG.error(_LE("Storage profile: %s cannot be found in vCenter."),
                      profile_name)
            raise vmdk_exceptions.ProfileNotFoundException(
                storage_profile=profile_name)
        LOG.debug("Storage profile: %(name)s resolved to vCenter profile ID: "
                  "%(id)s.",
                  {'name': profile_name,
                   'id': profile_id})
        return profile_id

    def _filter_by_profile(self, datastores, profile_id):
        """Filter out input datastores that do not match the given profile."""
        cf = self._session.pbm.client.factory
        hubs = pbm.convert_datastores_to_hubs(cf, datastores)
        filtered_hubs = pbm.filter_hubs_by_profile(self._session, hubs,
                                                   profile_id)
        return pbm.filter_datastores_by_hubs(filtered_hubs, datastores)

    def _filter_datastores(self, datastores, size_bytes, profile_id,
                           hard_anti_affinity_datastores,
                           hard_affinity_ds_types):
        """Filter datastores based on profile, size and affinity."""
        LOG.debug(
            "Filtering datastores: %(datastores)s based on size (bytes): "
            "%(size)d, profile: %(profile)s, hard-anti-affinity-datastores: "
            "%(hard_anti_affinity_datastores)s, hard-affinity-datastore-types:"
            " %(hard_affinity_ds_types)s.",
            {'datastores': datastores,
             'size': size_bytes,
             'profile': profile_id,
             'hard_anti_affinity_datastores': hard_anti_affinity_datastores,
             'hard_affinity_ds_types': hard_affinity_ds_types})
        if hard_anti_affinity_datastores is None:
            hard_anti_affinity_datastores = []
        filtered_datastores = [ds for ds in datastores if ds.value not in
                               hard_anti_affinity_datastores]

        if filtered_datastores and profile_id is not None:
            filtered_datastores = self._filter_by_profile(
                filtered_datastores, profile_id)
            LOG.debug("Profile: %(id)s matched by datastores: %(datastores)s.",
                      {'datastores': filtered_datastores,
                       'id': profile_id})

        filtered_summaries = [self._vops.get_summary(ds) for ds in
                              filtered_datastores]

        return [summary for summary in filtered_summaries
                if (summary.freeSpace > size_bytes and
                    (hard_affinity_ds_types is None or
                     summary.type.lower() in hard_affinity_ds_types))]

    def _get_all_hosts(self):
        """Get all ESX hosts managed by vCenter."""
        all_hosts = []

        retrieve_result = self._vops.get_hosts()
        while retrieve_result:
            hosts = retrieve_result.objects
            if not hosts:
                break

            for host in hosts:
                if self._vops.is_host_usable(host.obj):
                    all_hosts.append(host.obj)
            retrieve_result = self._vops.continue_retrieval(
                retrieve_result)
        return all_hosts

    def _compute_space_utilization(self, datastore_summary):
        """Compute space utilization of the given datastore."""
        return (
            1.0 -
            datastore_summary.freeSpace / float(datastore_summary.capacity)
        )

    def _select_best_summary(self, summaries):
        """Selects the best datastore summary.

        Selects the datastore which is connected to maximum number of hosts.
        Ties are broken based on space utilization-- datastore with low space
        utilization is preferred.
        """
        best_summary = None
        max_host_count = 0
        best_space_utilization = 1.0

        for summary in summaries:
            host_count = len(self._vops.get_connected_hosts(
                summary.datastore))
            if host_count > max_host_count:
                max_host_count = host_count
                best_space_utilization = self._compute_space_utilization(
                    summary
                )
                best_summary = summary
            elif host_count == max_host_count:
                # break the tie based on space utilization
                space_utilization = self._compute_space_utilization(
                    summary
                )
                if space_utilization < best_space_utilization:
                    best_space_utilization = space_utilization
                    best_summary = summary

        LOG.debug("Datastore: %(datastore)s is connected to %(host_count)d "
                  "host(s) and has space utilization: %(utilization)s.",
                  {'datastore': best_summary.datastore,
                   'host_count': max_host_count,
                   'utilization': best_space_utilization})
        return (best_summary, best_space_utilization)

    def select_datastore(self, req, hosts=None):
        """Selects a datastore satisfying the given requirements.

        Returns the selected datastore summary along with a compute host and
        resource pool where a VM can be created.

        :param req: selection requirements
        :param hosts: list of hosts to consider
        :return: (host, resourcePool, summary)
        """
        best_candidate = ()
        best_utilization = 1.0

        hard_affinity_ds_types = req.get(
            DatastoreSelector.HARD_AFFINITY_DS_TYPE)
        hard_anti_affinity_datastores = req.get(
            DatastoreSelector.HARD_ANTI_AFFINITY_DS)
        pref_utilization_thresh = req.get(DatastoreSelector.PREF_UTIL_THRESH,
                                          -1)
        size_bytes = req[DatastoreSelector.SIZE_BYTES]
        profile_name = req.get(DatastoreSelector.PROFILE_NAME)

        profile_id = None
        if profile_name is not None:
            profile_id = self.get_profile_id(profile_name)

        if not hosts:
            hosts = self._get_all_hosts()

        LOG.debug("Using hosts: %(hosts)s for datastore selection based on "
                  "requirements: %(req)s.",
                  {'hosts': hosts,
                   'req': req})
        for host_ref in hosts:
            try:
                (datastores, rp) = self._vops.get_dss_rp(host_ref)
            except exceptions.VimConnectionException:
                # No need to try other hosts when there is a connection problem
                with excutils.save_and_reraise_exception():
                    LOG.exception(_LE("Error occurred while "
                                      "selecting datastore."))
            except exceptions.VimException:
                # TODO(vbala) volumeops.get_dss_rp shouldn't throw VimException
                # for empty datastore list.
                LOG.warning(_LW("Unable to fetch datastores connected "
                                "to host %s."), host_ref, exc_info=True)
                continue

            if not datastores:
                continue

            filtered_summaries = self._filter_datastores(
                datastores, size_bytes, profile_id,
                hard_anti_affinity_datastores, hard_affinity_ds_types)
            LOG.debug("Datastores remaining after filtering: %s.",
                      filtered_summaries)

            if not filtered_summaries:
                continue

            (summary, utilization) = self._select_best_summary(
                filtered_summaries)
            if (pref_utilization_thresh == -1 or
                    utilization <= pref_utilization_thresh):
                return (host_ref, rp, summary)

            if utilization < best_utilization:
                best_candidate = (host_ref, rp, summary)
                best_utilization = utilization

        LOG.debug("Best candidate: %s.", best_candidate)
        return best_candidate

    def is_datastore_compliant(self, datastore, profile_name):
        """Check if the datastore is compliant with given profile.

        :param datastore: datastore to check the compliance
        :param profile_name: profile to check the compliance against
        :return: True if the datastore is compliant; False otherwise
        :raises: ProfileNotFoundException
        """
        LOG.debug("Checking datastore: %(datastore)s compliance against "
                  "profile: %(profile)s.",
                  {'datastore': datastore,
                   'profile': profile_name})
        if profile_name is None:
            # Any datastore is trivially compliant with a None profile.
            return True

        profile_id = self.get_profile_id(profile_name)
        is_compliant = bool(self._filter_by_profile([datastore], profile_id))
        LOG.debug("Compliance is %(is_compliant)s for datastore: "
                  "%(datastore)s against profile: %(profile)s.",
                  {'is_compliant': is_compliant,
                   'datastore': datastore,
                   'profile': profile_name})
        return is_compliant
