# Copyright (c) 2025 NetApp, Inc. All rights reserved.
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
NetApp ASA r2 REST client for Data ONTAP.

This module provides the ASA r2 specific REST client that inherits from
the base REST client and overrides methods to implement ASA r2 specific
workflows when needed.
"""

from oslo_log import log as logging
from oslo_utils import excutils

from cinder.i18n import _
from cinder.volume.drivers.netapp.dataontap.client import api as netapp_api
from cinder.volume.drivers.netapp.dataontap.client import client_cmode_rest
from cinder.volume.drivers.netapp import utils as netapp_utils
from cinder.volume import volume_utils

LOG = logging.getLogger(__name__)


class RestClientASAr2(client_cmode_rest.RestClient,
                      metaclass=volume_utils.TraceWrapperMetaclass):
    """NetApp ASA r2 REST client for Data ONTAP.

    This client inherits from the base REST client and provides ASA r2
    specific functionality for disaggregated platform workflows.

    By default, all methods from the parent RestClient are called.
    Override methods only when ASA r2 specific functionality is required.
    The __getattr__ method automatically routes any missing methods to the
    parent class, eliminating the need to explicitly define every method.
    """

    def __init__(self, **kwargs):
        """Initialize the ASA r2 REST client.

        :param kwargs: Same parameters as the parent RestClient
        """
        LOG.info("Initializing NetApp ASA r2 REST client")
        super(RestClientASAr2, self).__init__(**kwargs)
        self._init_asar2_features()

    def _init_asar2_features(self):
        """Initialize ASA r2 specific features.

        This method can be used to set up ASA r2 specific features
        and capabilities that are different from the standard ONTAP.
        """
        LOG.debug("Initializing ASA r2 specific features")

        # Remove features not supported in ASA r2 by setting them to False
        self.features.add_feature('SYSTEM_CONSTITUENT_METRICS',
                                  supported=False)
        self.features.add_feature('SYSTEM_METRICS', supported=False)
        # ASA r2 has no counter-based fallback, so always refresh via metrics.
        self.features.add_feature('NODE_METRICS', supported=True)

        # Add ASA r2 specific features here
        # For example, you might want to enable specific features
        # that are only available in ASA r2 environments

        # Example of adding ASA r2 specific features:
        # self.features.add_feature('ASA_R2_SPECIFIC_FEATURE', supported=True)
        # self.features.add_feature('ASA_R2_ENHANCED_CLONING', supported=True)
        LOG.debug("ASA r2 specific features initialized successfully")

    def __getattr__(self, name):
        """Log missing method call and return None."""
        LOG.error("Method '%s' not found in ASA r2 client", name)
        return None

    def get_performance_counter_info(self, object_name, counter_name):
        """ASA r2 doesn't support performance counter APIs as of now.

        TODO: Performance counter support will be added in upcoming releases.
        """
        msg = _('Performance counter APIs are not supported on ASA r2.')
        raise netapp_utils.NetAppDriverException(msg)

    def get_performance_instance_uuids(self, object_name, node_name):
        """ASA r2 doesn't support performance counter APIs."""
        msg = _('Performance counter APIs are not supported on ASA r2.')
        raise netapp_utils.NetAppDriverException(msg)

    def get_performance_counters(self, object_name, instance_uuids,
                                 counter_names):
        """ASA r2 doesn't support performance counter APIs."""
        msg = _('Performance counter APIs are not supported on ASA r2.')
        raise netapp_utils.NetAppDriverException(msg)

    # ASA r2 does not support ONTAPI, so we raise NotImplementedError
    def get_ontapi_version(self, cached=True):
        """ASA r2 doesn't support ONTAPI."""
        return (0, 0)

    def get_cluster_info(self):
        """Get cluster information for ASA r2."""
        query_args = {
            'fields': 'name,disaggregated',
        }

        try:
            response = self.send_request('/cluster',
                                         'get', query=query_args,
                                         enable_tunneling=False)
            return response
        except Exception as e:
            LOG.exception('Failed to get cluster information: %s', e)
            return None

    def get_aggregate_disk_types(self):
        """Get storage_types as array from all aggregates."""
        query = {
            'fields': 'name,block_storage.storage_type'
        }

        try:
            response = self.send_request('/storage/aggregates',
                                         'get', query=query,
                                         enable_tunneling=False)
            if not response or 'records' not in response:
                LOG.error('No records received from aggregate API')
                return None

            # Collect storage types from all aggregates
            storage_types = []
            if response['records']:
                for record in response['records']:
                    storage_type = (
                        record.get('block_storage', {}).get('storage_type'))
                    if storage_type:
                        storage_types.append(storage_type)

                LOG.debug('Aggregate storage types: %s', storage_types)
                return storage_types

            LOG.warning('No aggregate records found')
            return None

        except Exception as e:
            LOG.exception('Failed to get aggregate storage types: %s', e)
            msg = _('Failed to get aggregate storage types: %s')
            raise netapp_utils.NetAppDriverException(msg % e)

    def create_lun(self, volume_name, lun_name, size, metadata,
                   qos_policy_group_name=None,
                   qos_policy_group_is_adaptive=False):
        """Issues API request for creating LUN."""
        initial_size = size
        lun_name = lun_name.replace("-", "_")
        body = {
            'name': lun_name,
            'space.size': str(initial_size),
            'os_type': metadata['OsType'],
        }
        if qos_policy_group_name:
            body['qos_policy.name'] = qos_policy_group_name

        try:
            self.send_request('/storage/luns', 'post', body=body)
        except netapp_api.NaApiError as ex:
            with excutils.save_and_reraise_exception():
                LOG.error('Error provisioning volume %(lun_name)s on cluster.'
                          ' Details: %(ex)s',
                          {
                              'lun_name': lun_name,
                              'ex': ex,
                          })

    def destroy_lun(self, path, force=True):
        """Destroys the LUN at the path."""
        query = {}
        lun_name = self._get_backend_lun_or_namespace(path)
        query['name'] = lun_name
        if force:
            query['allow_delete_while_mapped'] = 'true'
        self.send_request('/storage/luns/', 'delete', query=query)

    def create_namespace(self, volume_name, namespace_name, size, metadata):
        """Issues API request for creating namespace"""

        initial_size = size
        namespace_name = namespace_name.replace("-", "_")
        body = {
            'name': namespace_name,
            'space.size': str(initial_size),
            'os_type': metadata['OsType'],
        }

        try:
            self.send_request('/storage/namespaces', 'post', body=body)
        except netapp_api.NaApiError as ex:
            with excutils.save_and_reraise_exception():
                LOG.error('Error provisioning namespace %(namespace_name)s'
                          ' on cluster Details: %(ex)s',
                          {
                              'namespace_name': namespace_name,
                              'ex': ex,
                          })

    def destroy_namespace(self, path, force=True):
        """Destroys the namespace at the path."""
        lun_name = self._get_backend_lun_or_namespace(path)
        query = {
            'name': lun_name,
            'svm': self.vserver
        }
        if force:
            query['allow_delete_while_mapped'] = 'true'
        self.send_request('/storage/namespaces', 'delete', query=query)

    def get_lun_map(self, path):
        """Gets the LUN map by LUN path."""
        lun_name = self._get_backend_lun_or_namespace(path)
        return super().get_lun_map(lun_name)

    def map_lun(self, path, igroup_name, lun_id=None):
        """Maps LUN to the initiator and returns LUN id assigned."""
        lun_name = self._get_backend_lun_or_namespace(path)
        return super().map_lun(lun_name, igroup_name, lun_id)

    def get_lun_by_args(self, path=None):
        """Retrieves LUN with specified args."""
        if path:
            if 'path' in path:
                lun_name = self._get_backend_lun_or_namespace(path)
                path['path'] = lun_name
        return super().get_lun_by_args(path=path)

    def unmap_lun(self, path, igroup_name):
        """Unmaps a LUN from given initiator."""
        lun_name = self._get_backend_lun_or_namespace(path)
        super().unmap_lun(lun_name, igroup_name)

    def map_namespace(self, path, subsystem_name):
        """Maps namespace to the host nqn and returns namespace uuid."""
        namespace_name = self._get_backend_lun_or_namespace(path)
        return super().map_namespace(namespace_name, subsystem_name)

    def unmap_namespace(self, path, subsystem):
        """Unmaps a namespace from given subsystem."""
        namespace_name = self._get_backend_lun_or_namespace(path)
        super().unmap_namespace(namespace_name, subsystem)

    def get_namespace_map(self, path):
        """Gets the namespace map using its path."""
        namespace_name = self._get_backend_lun_or_namespace(path)
        return super().get_namespace_map(namespace_name)

    def do_direct_resize(self, path, new_size_bytes, force=True):
        """Resize the LUN."""
        lun_name = self._get_backend_lun_or_namespace(path)
        if lun_name is not None:
            LOG.info('Resizing LUN %s directly to new size.', lun_name)
            body = {'name': lun_name, 'space.size': new_size_bytes}
            self._lun_update_by_path(lun_name, body)

    def namespace_resize(self, path, new_size_bytes):
        """Resize the namespace."""
        namespace_name = self._get_backend_lun_or_namespace(path)
        if namespace_name is not None:
            body = {'space.size': new_size_bytes}
            query = {'name': namespace_name}
            self.send_request('/storage/namespaces',
                              'patch',
                              body=body,
                              query=query
                              )

    def get_lun_sizes_by_volume(self, volume_name):
        """"Gets the list of LUNs and their sizes"""

        query = {
            'svm.name': self.vserver,
            'fields': 'space.size,name'
        }

        response = self.send_request('/storage/luns/', 'get', query=query)

        num_records = response.get('num_records')
        if not num_records or str(num_records) == '0':
            return []

        luns = []
        for lun_info in response['records']:
            luns.append({
                'path': lun_info.get('name', ''),
                'size': float(lun_info.get('space', {}).get('size', 0))
            })
        return luns

    def get_namespace_sizes_by_volume(self, volume_name):
        """"Gets the list of namespace and their sizes"""

        query = {
            'svm.name': self.vserver,
            'fields': 'space.size,name'
        }
        response = self.send_request('/storage/namespaces', 'get', query=query)

        namespaces = []
        for namespace_info in response.get('records', []):
            namespaces.append({
                'path': namespace_info.get('name', ''),
                'size': float(namespace_info.get('space', {}).get('size', 0))
            })

        return namespaces

    def get_aggregate_capacities(self, aggregate_names):
        """Gets capacity info for multiple aggregates."""

        return super().get_aggregate_capacities(aggregate_names)

    def _get_backend_lun_or_namespace(self, path):
        """Get the backend LUN or namespace"""
        paths = path.split("/")
        return paths[- 1].replace("-", "_")

    def get_vserver_aggregates(self):
        """Return list of aggregate names mapped to this SVM.

        Uses the SVM collection REST API (`/svm/svms`) filtered by SVM name
        and extracts the `aggregates` field from the matching record.
        """
        svm_name = self.vserver
        LOG.debug("Getting aggregates for SVM: %s", svm_name)
        query = {
            "name": svm_name,
            "fields": "name,uuid,aggregates",
            "return_timeout": 30,
        }

        try:
            # /api/svm/svms?name=<svm>&fields=name,uuid,aggregates
            resp = self.send_request("/svm/svms", "get", query=query)
        except Exception as e:
            msg = _("Failed to get aggregates for SVM %(svm)s: %(err)s") % {
                "svm": svm_name,
                "err": e,
            }
            LOG.error(msg)
            raise netapp_utils.NetAppDriverException(data=msg)

        if not isinstance(resp, dict):
            msg = _("Unexpected response type when getting aggregates for "
                    "SVM %(svm)s: %(rtype)s") % {
                "svm": svm_name,
                "rtype": type(resp),
            }
            LOG.error(msg)
            raise netapp_utils.NetAppDriverException(data=msg)
        LOG.debug("Response for SVM aggregates request: %s", resp)
        records = resp.get("records")
        LOG.debug("SVM records retrieved: %s", records)
        if not records:
            msg = _("Failed to resolve SVM %(svm)s when "
                    "getting aggregates.") % {
                "svm": svm_name,
            }
            LOG.error(msg)
            raise netapp_utils.NetAppDriverException(data=msg)

        svm_record = records[0]
        aggrs = svm_record.get("aggregates") or []
        aggr_names = [aggr.get("name") for aggr in aggrs if aggr.get("name")]

        LOG.debug("SVM %s mapped aggregates: %s", svm_name, aggr_names)
        return aggr_names

    def get_storage_availability_zones(self):
        """Return list of storage availability zone names (SAZs).

        Calls /api/storage/availability-zones and extracts the *name*
        field from each record.
        """
        query = {
            'fields': 'name',
        }

        try:
            resp = self.send_request(
                '/storage/availability-zones', 'get',
                query=query, enable_tunneling=False,
            )
        except Exception as e:
            msg = _('Failed to get storage availability zones: %s') % e
            LOG.error(msg)
            raise netapp_utils.NetAppDriverException(msg)

        if not isinstance(resp, dict):
            msg = _('Unexpected response type for availability zones: %s') % (
                type(resp),
            )
            LOG.error(msg)
            raise netapp_utils.NetAppDriverException(msg)

        records = resp.get('records') or []
        saz_list = [r.get('name') for r in records if r.get('name')]

        LOG.debug('Retrieved storage availability zones: %s', saz_list)
        return saz_list

    def get_lun_sizes_by_svm(self):
        """"Gets the list of LUNs for an SVM and their sizes"""

        query = {
            'svm.name': self.vserver,
            'fields': 'space.size,name'
        }

        response = self.send_request('/storage/luns/', 'get', query=query)

        num_records = response.get('num_records')
        if not num_records or str(num_records) == '0':
            return []

        luns = []
        for lun_info in response['records']:
            luns.append({
                'path': lun_info.get('name', ''),
                'size': float(lun_info.get('space', {}).get('size', 0))
            })
        return luns

    def get_namespace_sizes_by_svm(self):
        """Gets the list of namespaces for an SVM and their sizes."""

        query = {
            'svm.name': self.vserver,
            'fields': 'space.size,name',
        }

        response = self.send_request('/storage/namespaces', 'get', query=query)

        num_records = response.get('num_records')
        if not num_records or str(num_records) == '0':
            return []

        namespaces = []
        for ns_info in response.get('records', []):
            size = ns_info.get('space', {}).get('size', 0)
            try:
                size = int(size)
            except (TypeError, ValueError):
                size = 0

            namespaces.append({
                'path': ns_info.get('name', ''),
                'size': size,
            })

        return namespaces

    def get_storage_units_by_svm(self, vserver):
        """Return storage units for the given SVM via REST.

        Each entry is a dict with:
        - 'name': storage unit name
        - 'uuid': storage unit uuid
        - 'provisioned-size': provisioned size in bytes (int), taken from
          'space.size'.
        """
        query = {
            'svm.name': vserver,
            'fields': 'name,uuid,space.size,type',
        }

        try:
            # /api/storage/storage-units?svm.name=<svm>&fields=name,uuid,space.size,type
            resp = self.send_request(
                '/storage/storage-units',
                'get',
                query=query,
            )
        except Exception as e:
            msg = _('Failed to get storage units for SVM %(svm)s: %(err)s') % {
                'svm': vserver,
                'err': e,
            }
            LOG.error(msg)
            raise netapp_utils.NetAppDriverException(msg)

        if not isinstance(resp, dict):
            msg = _('Unexpected response type for storage units: %s') % (
                type(resp),
            )
            LOG.error(msg)
            raise netapp_utils.NetAppDriverException(msg)

        records = resp.get('records') or []
        storage_units = []

        for rec in records:
            space = rec.get('space') or {}
            size = space.get('size') or 0
            try:
                size = int(size)
            except (TypeError, ValueError):
                size = 0

            storage_units.append({
                'name': rec.get('name'),
                'uuid': rec.get('uuid'),
                'provisioned-size': size,
                'type': rec.get('type')
            })

        return storage_units
