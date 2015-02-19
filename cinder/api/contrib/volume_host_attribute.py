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

from oslo_log import log as logging

from cinder.api import extensions
from cinder.api.openstack import wsgi
from cinder.api import xmlutil


LOG = logging.getLogger(__name__)
authorize = extensions.soft_extension_authorizer('volume',
                                                 'volume_host_attribute')


class VolumeHostAttributeController(wsgi.Controller):
    def _add_volume_host_attribute(self, context, req, resp_volume):
        db_volume = req.get_db_volume(resp_volume['id'])
        key = "%s:host" % Volume_host_attribute.alias
        resp_volume[key] = db_volume['host']

    @wsgi.extends
    def show(self, req, resp_obj, id):
        context = req.environ['cinder.context']
        if authorize(context):
            resp_obj.attach(xml=VolumeHostAttributeTemplate())
            volume = resp_obj.obj['volume']
            self._add_volume_host_attribute(context, req, volume)

    @wsgi.extends
    def detail(self, req, resp_obj):
        context = req.environ['cinder.context']
        if authorize(context):
            resp_obj.attach(xml=VolumeListHostAttributeTemplate())
            for vol in list(resp_obj.obj['volumes']):
                self._add_volume_host_attribute(context, req, vol)


class Volume_host_attribute(extensions.ExtensionDescriptor):
    """Expose host as an attribute of a volume."""

    name = "VolumeHostAttribute"
    alias = "os-vol-host-attr"
    namespace = ("http://docs.openstack.org/volume/ext/"
                 "volume_host_attribute/api/v2")
    updated = "2011-11-03T00:00:00+00:00"

    def get_controller_extensions(self):
        controller = VolumeHostAttributeController()
        extension = extensions.ControllerExtension(self, 'volumes', controller)
        return [extension]


def make_volume(elem):
    elem.set('{%s}host' % Volume_host_attribute.namespace,
             '%s:host' % Volume_host_attribute.alias)


class VolumeHostAttributeTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('volume', selector='volume')
        make_volume(root)
        alias = Volume_host_attribute.alias
        namespace = Volume_host_attribute.namespace
        return xmlutil.SlaveTemplate(root, 1, nsmap={alias: namespace})


class VolumeListHostAttributeTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('volumes')
        elem = xmlutil.SubTemplateElement(root, 'volume', selector='volumes')
        make_volume(elem)
        alias = Volume_host_attribute.alias
        namespace = Volume_host_attribute.namespace
        return xmlutil.SlaveTemplate(root, 1, nsmap={alias: namespace})
