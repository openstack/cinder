# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

from cinder import flags
from cinder.openstack.common import jsonutils
import cinder.openstack.common.rpc.proxy


FLAGS = flags.FLAGS


class SchedulerAPI(cinder.openstack.common.rpc.proxy.RpcProxy):
    '''Client side of the scheduler rpc API.

    API version history:

        1.0 - Initial version.
        1.1 - Add create_volume() method
        1.2 - Add request_spec, filter_properties arguments
              to create_volume()
    '''

    RPC_API_VERSION = '1.0'

    def __init__(self):
        super(SchedulerAPI, self).__init__(
            topic=FLAGS.scheduler_topic,
            default_version=self.RPC_API_VERSION)

    def create_volume(self, ctxt, topic, volume_id, snapshot_id=None,
                      image_id=None, request_spec=None,
                      filter_properties=None):
        request_spec_p = jsonutils.to_primitive(request_spec)
        return self.cast(ctxt, self.make_msg(
            'create_volume',
            topic=topic,
            volume_id=volume_id,
            snapshot_id=snapshot_id,
            image_id=image_id,
            request_spec=request_spec_p,
            filter_properties=filter_properties),
            version='1.2')

    def update_service_capabilities(self, ctxt,
                                    service_name, host,
                                    capabilities):
        self.fanout_cast(ctxt, self.make_msg('update_service_capabilities',
                         service_name=service_name, host=host,
                         capabilities=capabilities))
