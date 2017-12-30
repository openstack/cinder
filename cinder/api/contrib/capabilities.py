# Copyright (c) 2015 Hitachi Data Systems, Inc.
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

import oslo_messaging

from cinder.api import extensions
from cinder.api.openstack import wsgi
from cinder.api.views import capabilities as capabilities_view
from cinder.common import constants
from cinder import exception
from cinder.i18n import _
from cinder import objects
from cinder.policies import capabilities as policy
from cinder.volume import rpcapi


class CapabilitiesController(wsgi.Controller):
    """The Capabilities controller for the OpenStack API."""

    _view_builder_class = capabilities_view.ViewBuilder

    def __init__(self):
        # FIXME(jdg):  Is it kosher that this just
        # skips the volume.api and goes straight to RPC
        # from here?
        self.volume_api = rpcapi.VolumeAPI()
        super(CapabilitiesController, self).__init__()

    def show(self, req, id):
        """Return capabilities list of given backend."""
        context = req.environ['cinder.context']
        context.authorize(policy.CAPABILITIES_POLICY)
        filters = {'host_or_cluster': id, 'binary': constants.VOLUME_BINARY}
        services = objects.ServiceList.get_all(context, filters)
        if not services:
            msg = (_("Can't find service: %s") % id)
            raise exception.NotFound(msg)
        topic = services[0].service_topic_queue
        try:
            capabilities = self.volume_api.get_capabilities(context, topic,
                                                            False)
        except oslo_messaging.MessagingTimeout:
            raise exception.RPCTimeout(service=topic)
        return self._view_builder.summary(req, capabilities, topic)


class Capabilities(extensions.ExtensionDescriptor):
    """Capabilities support."""

    name = "Capabilities"
    alias = "capabilities"
    updated = "2015-08-31T00:00:00+00:00"

    def get_resources(self):
        resources = []
        res = extensions.ResourceExtension(
            Capabilities.alias,
            CapabilitiesController())

        resources.append(res)
        return resources
