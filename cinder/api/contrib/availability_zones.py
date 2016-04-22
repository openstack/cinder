# Copyright (c) 2013 OpenStack Foundation
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

from cinder.api import extensions
from cinder.api.openstack import wsgi
import cinder.api.views.availability_zones
import cinder.exception
import cinder.volume.api


class Controller(wsgi.Controller):

    _view_builder_class = cinder.api.views.availability_zones.ViewBuilder

    def __init__(self, *args, **kwargs):
        super(Controller, self).__init__(*args, **kwargs)
        self.volume_api = cinder.volume.api.API()

    def index(self, req):
        """Describe all known availability zones."""
        azs = self.volume_api.list_availability_zones()
        return self._view_builder.list(req, azs)


class Availability_zones(extensions.ExtensionDescriptor):
    """Describe Availability Zones."""

    name = 'AvailabilityZones'
    alias = 'os-availability-zone'
    updated = '2013-06-27T00:00:00+00:00'

    def get_resources(self):
        controller = Controller()
        res = extensions.ResourceExtension(Availability_zones.alias,
                                           controller)
        return [res]
