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

from cinder.common import constants
from cinder import rpc


class SchedulerAPI(rpc.RPCAPI):
    """Client side of the scheduler rpc API.

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
    """

    RPC_API_VERSION = '3.0'
    TOPIC = constants.SCHEDULER_TOPIC
    BINARY = 'cinder-scheduler'

    def create_consistencygroup(self, ctxt, topic, group,
                                request_spec_list=None,
                                filter_properties_list=None):
        version = self._compat_ver('3.0', '2.0')
        cctxt = self.client.prepare(version=version)
        request_spec_p_list = []
        for request_spec in request_spec_list:
            request_spec_p = jsonutils.to_primitive(request_spec)
            request_spec_p_list.append(request_spec_p)

        msg_args = {
            'group': group, 'request_spec_list': request_spec_p_list,
            'filter_properties_list': filter_properties_list,
        }

        if version == '2.0':
            msg_args['topic'] = topic

        return cctxt.cast(ctxt, 'create_consistencygroup', **msg_args)

    def create_group(self, ctxt, topic, group,
                     group_spec=None,
                     request_spec_list=None,
                     group_filter_properties=None,
                     filter_properties_list=None):
        version = self._compat_ver('3.0', '2.3')
        cctxt = self.client.prepare(version=version)
        request_spec_p_list = []
        for request_spec in request_spec_list:
            request_spec_p = jsonutils.to_primitive(request_spec)
            request_spec_p_list.append(request_spec_p)
        group_spec_p = jsonutils.to_primitive(group_spec)

        msg_args = {
            'group': group, 'group_spec': group_spec_p,
            'request_spec_list': request_spec_p_list,
            'group_filter_properties': group_filter_properties,
            'filter_properties_list': filter_properties_list,
        }

        if version == '2.3':
            msg_args['topic'] = topic

        return cctxt.cast(ctxt, 'create_group', **msg_args)

    def create_volume(self, ctxt, topic, volume_id, snapshot_id=None,
                      image_id=None, request_spec=None,
                      filter_properties=None, volume=None):
        request_spec_p = jsonutils.to_primitive(request_spec)
        msg_args = {'snapshot_id': snapshot_id, 'image_id': image_id,
                    'request_spec': request_spec_p,
                    'filter_properties': filter_properties, 'volume': volume}
        version = self._compat_ver('3.0', '2.2', '2.0')
        if version in ('2.2', '2.0'):
            msg_args['volume_id'] = volume.id
            msg_args['topic'] = topic
        if version == '2.0':
            # Send request_spec as dict
            msg_args['request_spec'] = jsonutils.to_primitive(request_spec)

        cctxt = self.client.prepare(version=version)
        return cctxt.cast(ctxt, 'create_volume', **msg_args)

    def migrate_volume_to_host(self, ctxt, topic, volume_id, host,
                               force_host_copy=False, request_spec=None,
                               filter_properties=None, volume=None):
        request_spec_p = jsonutils.to_primitive(request_spec)
        msg_args = {'host': host, 'force_host_copy': force_host_copy,
                    'request_spec': request_spec_p,
                    'filter_properties': filter_properties, 'volume': volume}
        version = self._compat_ver('3.0', '2.0')

        if version == '2.0':
            msg_args['volume_id'] = volume.id
            msg_args['topic'] = topic

        cctxt = self.client.prepare(version=version)
        return cctxt.cast(ctxt, 'migrate_volume_to_host', **msg_args)

    def retype(self, ctxt, topic, volume_id, request_spec=None,
               filter_properties=None, volume=None):

        request_spec_p = jsonutils.to_primitive(request_spec)
        msg_args = {'request_spec': request_spec_p,
                    'filter_properties': filter_properties, 'volume': volume}
        version = self._compat_ver('3.0', '2.0')

        if version == '2.0':
            msg_args['volume_id'] = volume.id
            msg_args['topic'] = topic

        cctxt = self.client.prepare(version=version)
        return cctxt.cast(ctxt, 'retype', **msg_args)

    def manage_existing(self, ctxt, topic, volume_id,
                        request_spec=None, filter_properties=None,
                        volume=None):
        request_spec_p = jsonutils.to_primitive(request_spec)
        msg_args = {
            'request_spec': request_spec_p,
            'filter_properties': filter_properties, 'volume': volume,
        }
        version = self._compat_ver('3.0', '2.1', '2.0')
        if version in ('2.1', '2.0'):
            msg_args['volume_id'] = volume.id
            msg_args['topic'] = topic
        if version == '2.0':
            msg_args.pop('volume')
        cctxt = self.client.prepare(version=version)
        return cctxt.cast(ctxt, 'manage_existing', **msg_args)

    def get_pools(self, ctxt, filters=None):
        version = self._compat_ver('3.0', '2.0')
        cctxt = self.client.prepare(version=version)
        return cctxt.call(ctxt, 'get_pools',
                          filters=filters)

    def update_service_capabilities(self, ctxt,
                                    service_name, host,
                                    capabilities):
        version = self._compat_ver('3.0', '2.0')
        cctxt = self.client.prepare(fanout=True, version=version)
        cctxt.cast(ctxt, 'update_service_capabilities',
                   service_name=service_name, host=host,
                   capabilities=capabilities)
