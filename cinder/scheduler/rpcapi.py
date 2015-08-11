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
import oslo_messaging as messaging
from oslo_serialization import jsonutils

from cinder.objects import base as objects_base
from cinder import rpc


CONF = cfg.CONF


class SchedulerAPI(object):
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
    """

    RPC_API_VERSION = '1.0'

    def __init__(self):
        super(SchedulerAPI, self).__init__()
        target = messaging.Target(topic=CONF.scheduler_topic,
                                  version=self.RPC_API_VERSION)
        serializer = objects_base.CinderObjectSerializer()
        self.client = rpc.get_client(target, version_cap='1.8',
                                     serializer=serializer)

    def create_consistencygroup(self, ctxt, topic, group,
                                request_spec_list=None,
                                filter_properties_list=None):

        cctxt = self.client.prepare(version='1.8')
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
                      filter_properties=None):

        cctxt = self.client.prepare(version='1.2')
        request_spec_p = jsonutils.to_primitive(request_spec)
        return cctxt.cast(ctxt, 'create_volume',
                          topic=topic,
                          volume_id=volume_id,
                          snapshot_id=snapshot_id,
                          image_id=image_id,
                          request_spec=request_spec_p,
                          filter_properties=filter_properties)

    def migrate_volume_to_host(self, ctxt, topic, volume_id, host,
                               force_host_copy=False, request_spec=None,
                               filter_properties=None):

        cctxt = self.client.prepare(version='1.3')
        request_spec_p = jsonutils.to_primitive(request_spec)
        return cctxt.cast(ctxt, 'migrate_volume_to_host',
                          topic=topic,
                          volume_id=volume_id,
                          host=host,
                          force_host_copy=force_host_copy,
                          request_spec=request_spec_p,
                          filter_properties=filter_properties)

    def retype(self, ctxt, topic, volume_id,
               request_spec=None, filter_properties=None):

        cctxt = self.client.prepare(version='1.4')
        request_spec_p = jsonutils.to_primitive(request_spec)
        return cctxt.cast(ctxt, 'retype',
                          topic=topic,
                          volume_id=volume_id,
                          request_spec=request_spec_p,
                          filter_properties=filter_properties)

    def manage_existing(self, ctxt, topic, volume_id,
                        request_spec=None, filter_properties=None):
        cctxt = self.client.prepare(version='1.5')
        request_spec_p = jsonutils.to_primitive(request_spec)
        return cctxt.cast(ctxt, 'manage_existing',
                          topic=topic,
                          volume_id=volume_id,
                          request_spec=request_spec_p,
                          filter_properties=filter_properties)

    def get_pools(self, ctxt, filters=None):
        cctxt = self.client.prepare(version='1.7')
        return cctxt.call(ctxt, 'get_pools',
                          filters=filters)

    def update_service_capabilities(self, ctxt,
                                    service_name, host,
                                    capabilities):
        # FIXME(flaper87): What to do with fanout?
        cctxt = self.client.prepare(fanout=True)
        cctxt.cast(ctxt, 'update_service_capabilities',
                   service_name=service_name, host=host,
                   capabilities=capabilities)
