#   Copyright 2012 OpenStack Foundation
#
#   Licensed under the Apache License, Version 2.0 (the "License"); you may
#   not use this file except in compliance with the License. You may obtain
#   a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#   WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#   License for the specific language governing permissions and limitations
#   under the License.

from cinder.api import extensions
from cinder.api.openstack import wsgi
from cinder.policies import volumes as policy


class VolumeHostAttributeController(wsgi.Controller):
    def _add_volume_host_attribute(self, req, resp_volume):
        db_volume = req.get_db_volume(resp_volume['id'])
        key = "%s:host" % Volume_host_attribute.alias
        resp_volume[key] = db_volume['host']

    @wsgi.extends
    def show(self, req, resp_obj, id):
        context = req.environ['cinder.context']
        if context.authorize(policy.HOST_ATTRIBUTE_POLICY, fatal=False):
            volume = resp_obj.obj['volume']
            self._add_volume_host_attribute(req, volume)

    @wsgi.extends
    def detail(self, req, resp_obj):
        context = req.environ['cinder.context']
        if context.authorize(policy.HOST_ATTRIBUTE_POLICY, fatal=False):
            for vol in list(resp_obj.obj['volumes']):
                self._add_volume_host_attribute(req, vol)


class Volume_host_attribute(extensions.ExtensionDescriptor):
    """Expose host as an attribute of a volume."""

    name = "VolumeHostAttribute"
    alias = "os-vol-host-attr"
    updated = "2011-11-03T00:00:00+00:00"

    def get_controller_extensions(self):
        controller = VolumeHostAttributeController()
        extension = extensions.ControllerExtension(self, 'volumes', controller)
        return [extension]
