# Copyright 2012, Red Hat, Inc.
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
Client side of the scheduler manager RPC API.
"""

from oslo_serialization import jsonutils
from oslo_utils import timeutils

from cinder.common import constants
from cinder import rpc


class SchedulerAPI(rpc.RPCAPI):
    """Client side of the scheduler RPC API.

    API version history:

    .. code-block:: none

        1.0 - Initial version.
        1.1 - Add create_volume() method
        1.2 - Add request_spec, filter_properties arguments to
              create_volume()
        1.3 - Add migrate_volume_to_host() method
        1.4 - Add retype method
        1.5 - Add manage_existing method
        1.6 - Add create_consistencygroup method
        1.7 - Add get_active_pools method
        1.8 - Add sending object over RPC in create_consistencygroup method
        1.9 - Adds support for sending objects over RPC in create_volume()
        1.10 - Adds support for sending objects over RPC in retype()
        1.11 - Adds support for sending objects over RPC in
               migrate_volume_to_host()

        ... Mitaka supports messaging 1.11. Any changes to existing methods in
        1.x after this point should be done so that they can handle version cap
        set to 1.11.

        2.0 - Remove 1.x compatibility
        2.1 - Adds support for sending objects over RPC in manage_existing()
        2.2 - Sends request_spec as object in create_volume()
        2.3 - Add create_group method

        ... Newton supports messaging 2.3. Any changes to existing methods in
        2.x after this point should be done so that they can handle version cap
        set to 2.3.

        3.0 - Remove 2.x compatibility
        3.1 - Adds notify_service_capabilities()
        3.2 - Adds extend_volume()
        3.3 - Add cluster support to migrate_volume, and to
              update_service_capabilities and send the timestamp from the
              capabilities.
        3.4 - Adds work_cleanup and do_cleanup methods.
        3.5 - Make notify_service_capabilities support A/A
        3.6 - Removed create_consistencygroup method
        3.7 - Adds set_log_levels and get_log_levels
        3.8 - Addds ``valid_host_capacity`` method
        3.9 - Adds create_snapshot method
        3.10 - Adds backup_id to create_volume method.
        3.11 - Adds manage_existing_snapshot method.
        3.12 - Adds create_backup method.
    """

    RPC_API_VERSION = '3.12'
    RPC_DEFAULT_VERSION = '3.0'
    TOPIC = constants.SCHEDULER_TOPIC
    BINARY = 'cinder-scheduler'

    def create_group(self, ctxt, group, group_spec=None,
                     request_spec_list=None, group_filter_properties=None,
                     filter_properties_list=None):
        cctxt = self._get_cctxt()
        request_spec_p_list = [jsonutils.to_primitive(rs)
                               for rs in request_spec_list]
        group_spec_p = jsonutils.to_primitive(group_spec)
        msg_args = {
            'group': group, 'group_spec': group_spec_p,
            'request_spec_list': request_spec_p_list,
            'group_filter_properties': group_filter_properties,
            'filter_properties_list': filter_properties_list,
        }

        cctxt.cast(ctxt, 'create_group', **msg_args)

    def create_volume(self, ctxt, volume, snapshot_id=None, image_id=None,
                      request_spec=None, filter_properties=None,
                      backup_id=None):
        volume.create_worker()
        cctxt = self._get_cctxt()
        msg_args = {'snapshot_id': snapshot_id, 'image_id': image_id,
                    'request_spec': request_spec,
                    'filter_properties': filter_properties,
                    'volume': volume, 'backup_id': backup_id}
        if not self.client.can_send_version('3.10'):
            msg_args.pop('backup_id')
        return cctxt.cast(ctxt, 'create_volume', **msg_args)

    @rpc.assert_min_rpc_version('3.8')
    def validate_host_capacity(self, ctxt, backend, request_spec,
                               filter_properties=None):
        msg_args = {'request_spec': request_spec,
                    'filter_properties': filter_properties, 'backend': backend}
        cctxt = self._get_cctxt()
        return cctxt.call(ctxt, 'validate_host_capacity', **msg_args)

    @rpc.assert_min_rpc_version('3.9')
    def create_snapshot(self, ctxt, volume, snapshot, backend,
                        request_spec=None, filter_properties=None):
        cctxt = self._get_cctxt()
        msg_args = {'request_spec': request_spec,
                    'filter_properties': filter_properties,
                    'volume': volume,
                    'snapshot': snapshot,
                    'backend': backend}
        return cctxt.cast(ctxt, 'create_snapshot', **msg_args)

    def migrate_volume(self, ctxt, volume, backend, force_copy=False,
                       request_spec=None, filter_properties=None):
        request_spec_p = jsonutils.to_primitive(request_spec)
        msg_args = {'request_spec': request_spec_p,
                    'filter_properties': filter_properties, 'volume': volume}
        version = '3.3'
        if self.client.can_send_version(version):
            msg_args['backend'] = backend
            msg_args['force_copy'] = force_copy
            method = 'migrate_volume'
        else:
            version = '3.0'
            msg_args['host'] = backend
            msg_args['force_host_copy'] = force_copy
            method = 'migrate_volume_to_host'

        cctxt = self._get_cctxt(version=version)
        return cctxt.cast(ctxt, method, **msg_args)

    def retype(self, ctxt, volume, request_spec=None, filter_properties=None):
        cctxt = self._get_cctxt()
        request_spec_p = jsonutils.to_primitive(request_spec)
        msg_args = {'request_spec': request_spec_p,
                    'filter_properties': filter_properties, 'volume': volume}
        return cctxt.cast(ctxt, 'retype', **msg_args)

    def manage_existing(self, ctxt, volume, request_spec=None,
                        filter_properties=None):
        cctxt = self._get_cctxt()
        request_spec_p = jsonutils.to_primitive(request_spec)
        msg_args = {
            'request_spec': request_spec_p,
            'filter_properties': filter_properties, 'volume': volume,
        }
        return cctxt.cast(ctxt, 'manage_existing', **msg_args)

    @rpc.assert_min_rpc_version('3.11')
    def manage_existing_snapshot(self, ctxt, volume, snapshot, ref,
                                 request_spec=None, filter_properties=None):
        cctxt = self._get_cctxt()
        request_spec_p = jsonutils.to_primitive(request_spec)
        msg_args = {
            'request_spec': request_spec_p,
            'filter_properties': filter_properties,
            'volume': volume,
            'snapshot': snapshot,
            'ref': ref,
        }
        return cctxt.cast(ctxt, 'manage_existing_snapshot', **msg_args)

    @rpc.assert_min_rpc_version('3.2')
    def extend_volume(self, ctxt, volume, new_size, reservations,
                      request_spec, filter_properties=None):
        cctxt = self._get_cctxt()

        request_spec_p = jsonutils.to_primitive(request_spec)
        msg_args = {
            'volume': volume,
            'new_size': new_size,
            'reservations': reservations,
            'request_spec': request_spec_p,
            'filter_properties': filter_properties,
        }

        return cctxt.cast(ctxt, 'extend_volume', **msg_args)

    def get_pools(self, ctxt, filters=None):
        cctxt = self._get_cctxt()
        return cctxt.call(ctxt, 'get_pools', filters=filters)

    @staticmethod
    def prepare_timestamp(timestamp):
        timestamp = timestamp or timeutils.utcnow()
        return jsonutils.to_primitive(timestamp)

    def update_service_capabilities(self, ctxt, service_name, host,
                                    capabilities, cluster_name,
                                    timestamp=None):
        msg_args = dict(service_name=service_name, host=host,
                        capabilities=capabilities)

        version = '3.3'
        # If server accepts timestamping the capabilities and the cluster name
        if self.client.can_send_version(version):
            # Serialize the timestamp
            msg_args.update(cluster_name=cluster_name,
                            timestamp=self.prepare_timestamp(timestamp))
        else:
            version = '3.0'

        cctxt = self._get_cctxt(fanout=True, version=version)
        cctxt.cast(ctxt, 'update_service_capabilities', **msg_args)

    @rpc.assert_min_rpc_version('3.1')
    def notify_service_capabilities(self, ctxt, service_name,
                                    backend, capabilities, timestamp=None):
        parameters = {'service_name': service_name,
                      'capabilities': capabilities}
        if self.client.can_send_version('3.5'):
            version = '3.5'
            parameters.update(backend=backend,
                              timestamp=self.prepare_timestamp(timestamp))
        else:
            version = '3.1'
            parameters['host'] = backend

        cctxt = self._get_cctxt(version=version)
        cctxt.cast(ctxt, 'notify_service_capabilities', **parameters)

    @rpc.assert_min_rpc_version('3.4')
    def work_cleanup(self, ctxt, cleanup_request):
        """Generate individual service cleanup requests from user request."""
        cctxt = self.client.prepare(version='3.4')
        # Response will have services that are receiving the cleanup request
        # and services that couldn't receive it since they are down.
        return cctxt.call(ctxt, 'work_cleanup',
                          cleanup_request=cleanup_request)

    @rpc.assert_min_rpc_version('3.4')
    def do_cleanup(self, ctxt, cleanup_request):
        """Perform this scheduler's resource cleanup as per cleanup_request."""
        cctxt = self.client.prepare(version='3.4')
        cctxt.cast(ctxt, 'do_cleanup', cleanup_request=cleanup_request)

    @rpc.assert_min_rpc_version('3.7')
    def set_log_levels(self, context, service, log_request):
        cctxt = self._get_cctxt(server=service.host, version='3.7')
        cctxt.cast(context, 'set_log_levels', log_request=log_request)

    @rpc.assert_min_rpc_version('3.7')
    def get_log_levels(self, context, service, log_request):
        cctxt = self._get_cctxt(server=service.host, version='3.7')
        return cctxt.call(context, 'get_log_levels', log_request=log_request)

    @rpc.assert_min_rpc_version('3.12')
    def create_backup(self, ctxt, backup):
        cctxt = self._get_cctxt()
        msg_args = {'backup': backup}
        return cctxt.cast(ctxt, 'create_backup', **msg_args)
