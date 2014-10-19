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
from cinder.api import xmlutil


authorize = extensions.soft_extension_authorizer('volume',
                                                 'volume_tenant_attribute')


class VolumeTenantAttributeController(wsgi.Controller):
    def _add_volume_tenant_attribute(self, context, req, resp_volume):
        db_volume = req.get_db_volume(resp_volume['id'])
        key = "%s:tenant_id" % Volume_tenant_attribute.alias
        resp_volume[key] = db_volume['project_id']

    @wsgi.extends
    def show(self, req, resp_obj, id):
        context = req.environ['cinder.context']
        if authorize(context):
            resp_obj.attach(xml=VolumeTenantAttributeTemplate())
            volume = resp_obj.obj['volume']
            self._add_volume_tenant_attribute(context, req, volume)

    @wsgi.extends
    def detail(self, req, resp_obj):
        context = req.environ['cinder.context']
        if authorize(context):
            resp_obj.attach(xml=VolumeListTenantAttributeTemplate())
            for vol in list(resp_obj.obj['volumes']):
                self._add_volume_tenant_attribute(context, req, vol)


class Volume_tenant_attribute(extensions.ExtensionDescriptor):
    """Expose the internal project_id as an attribute of a volume."""

    name = "VolumeTenantAttribute"
    alias = "os-vol-tenant-attr"
    namespace = ("http://docs.openstack.org/volume/ext/"
                 "volume_tenant_attribute/api/v2")
    updated = "2011-11-03T00:00:00+00:00"

    def get_controller_extensions(self):
        controller = VolumeTenantAttributeController()
        extension = extensions.ControllerExtension(self, 'volumes', controller)
        return [extension]


def make_volume(elem):
    elem.set('{%s}tenant_id' % Volume_tenant_attribute.namespace,
             '%s:tenant_id' % Volume_tenant_attribute.alias)


class VolumeTenantAttributeTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('volume', selector='volume')
        make_volume(root)
        alias = Volume_tenant_attribute.alias
        namespace = Volume_tenant_attribute.namespace
        return xmlutil.SlaveTemplate(root, 1, nsmap={alias: namespace})


class VolumeListTenantAttributeTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('volumes')
        elem = xmlutil.SubTemplateElement(root, 'volume', selector='volumes')
        make_volume(elem)
        alias = Volume_tenant_attribute.alias
        namespace = Volume_tenant_attribute.namespace
        return xmlutil.SlaveTemplate(root, 1, nsmap={alias: namespace})
