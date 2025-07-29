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

    def get_cluster_capacity(self):
        """Get cluster capacity information for ASA r2."""
        query = {
            'fields': 'block_storage.size,block_storage.available'
        }

        try:
            response = self.send_request('/storage/cluster',
                                         'get', query=query,
                                         enable_tunneling=False)
            if not response:
                LOG.error('No response received from cluster capacity API')
                return {}

            block_storage = response.get('block_storage', {})

            size_total = block_storage.get('size', 0)
            size_available = block_storage.get('available', 0)

            capacity = {
                'size-total': float(size_total),
                'size-available': float(size_available)
            }

            LOG.debug('Cluster total size %s:', capacity['size-total'])
            LOG.debug('Cluster available size %s:', capacity['size-available'])

            return capacity

        except Exception as e:
            LOG.exception('Failed to get cluster capacity: %s', e)
            msg = _('Failed to get cluster capacity: %s')
            raise netapp_utils.NetAppDriverException(msg % e)

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
        """Issues API request for creating LUN on volume."""
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

    def _get_backend_lun_or_namespace(self, path):
        """Get the backend LUN or namespace"""
        paths = path.split("/")
        lun_name = paths[3].replace("-", "_")
        return lun_name
