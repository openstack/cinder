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

from oslo_config import cfg
from oslo_serialization import jsonutils

from cinder import rpc


CONF = cfg.CONF


class SchedulerAPI(rpc.RPCAPI):
    """Client side of the scheduler rpc API.

    API version history:

        1.0 - Initial version.
        1.1 - Add create_volume() method
        1.2 - Add request_spec, filter_properties arguments
              to create_volume()
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
    """

    RPC_API_VERSION = '2.0'
    TOPIC = CONF.scheduler_topic
    BINARY = 'cinder-scheduler'

    def _compat_ver(self, current, legacy):
        if self.client.can_send_version(current):
            return current
        else:
            return legacy

    def create_consistencygroup(self, ctxt, topic, group,
                                request_spec_list=None,
                                filter_properties_list=None):
        version = self._compat_ver('2.0', '1.8')
        cctxt = self.client.prepare(version=version)
        request_spec_p_list = []
        for request_spec in request_spec_list:
            request_spec_p = jsonutils.to_primitive(request_spec)
            request_spec_p_list.append(request_spec_p)

        return cctxt.cast(ctxt, 'create_consistencygroup',
                          topic=topic,
                          group=group,
                          request_spec_list=request_spec_p_list,
                          filter_properties_list=filter_properties_list)

    def create_volume(self, ctxt, topic, volume_id, snapshot_id=None,
                      image_id=None, request_spec=None,
                      filter_properties=None, volume=None):
        request_spec_p = jsonutils.to_primitive(request_spec)
        msg_args = {'topic': topic, 'volume_id': volume_id,
                    'snapshot_id': snapshot_id, 'image_id': image_id,
                    'request_spec': request_spec_p,
                    'filter_properties': filter_properties}
        if self.client.can_send_version('2.0'):
            version = '2.0'
            msg_args['volume'] = volume
        elif self.client.can_send_version('1.9'):
            version = '1.9'
            msg_args['volume'] = volume
        else:
            version = '1.2'

        cctxt = self.client.prepare(version=version)
        return cctxt.cast(ctxt, 'create_volume', **msg_args)

    def migrate_volume_to_host(self, ctxt, topic, volume_id, host,
                               force_host_copy=False, request_spec=None,
                               filter_properties=None, volume=None):
        request_spec_p = jsonutils.to_primitive(request_spec)
        msg_args = {'topic': topic, 'volume_id': volume_id,
                    'host': host, 'force_host_copy': force_host_copy,
                    'request_spec': request_spec_p,
                    'filter_properties': filter_properties}
        if self.client.can_send_version('2.0'):
            version = '2.0'
            msg_args['volume'] = volume
        elif self.client.can_send_version('1.11'):
            version = '1.11'
            msg_args['volume'] = volume
        else:
            version = '1.3'

        cctxt = self.client.prepare(version=version)
        return cctxt.cast(ctxt, 'migrate_volume_to_host', **msg_args)

    def retype(self, ctxt, topic, volume_id,
               request_spec=None, filter_properties=None, volume=None):

        request_spec_p = jsonutils.to_primitive(request_spec)
        msg_args = {'topic': topic, 'volume_id': volume_id,
                    'request_spec': request_spec_p,
                    'filter_properties': filter_properties}
        if self.client.can_send_version('2.0'):
            version = '2.0'
            msg_args['volume'] = volume
        elif self.client.can_send_version('1.10'):
            version = '1.10'
            msg_args['volume'] = volume
        else:
            version = '1.4'

        cctxt = self.client.prepare(version=version)
        return cctxt.cast(ctxt, 'retype', **msg_args)

    def manage_existing(self, ctxt, topic, volume_id,
                        request_spec=None, filter_properties=None):
        version = self._compat_ver('2.0', '1.5')
        cctxt = self.client.prepare(version=version)
        request_spec_p = jsonutils.to_primitive(request_spec)
        return cctxt.cast(ctxt, 'manage_existing',
                          topic=topic,
                          volume_id=volume_id,
                          request_spec=request_spec_p,
                          filter_properties=filter_properties)

    def get_pools(self, ctxt, filters=None):
        version = self._compat_ver('2.0', '1.7')
        cctxt = self.client.prepare(version=version)
        return cctxt.call(ctxt, 'get_pools',
                          filters=filters)

    def update_service_capabilities(self, ctxt,
                                    service_name, host,
                                    capabilities):
        # FIXME(flaper87): What to do with fanout?
        version = self._compat_ver('2.0', '1.0')
        cctxt = self.client.prepare(fanout=True, version=version)
        cctxt.cast(ctxt, 'update_service_capabilities',
                   service_name=service_name, host=host,
                   capabilities=capabilities)
