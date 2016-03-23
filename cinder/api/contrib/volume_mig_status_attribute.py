#   Copyright 2013 IBM Corp.
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

authorize = extensions.soft_extension_authorizer('volume',
                                                 'volume_mig_status_attribute')


class VolumeMigStatusAttributeController(wsgi.Controller):
    def _add_volume_mig_status_attribute(self, req, resp_volume):
        db_volume = req.get_db_volume(resp_volume['id'])
        key = "%s:migstat" % Volume_mig_status_attribute.alias
        resp_volume[key] = db_volume['migration_status']
        key = "%s:name_id" % Volume_mig_status_attribute.alias
        resp_volume[key] = db_volume['_name_id']

    @wsgi.extends
    def show(self, req, resp_obj, id):
        context = req.environ['cinder.context']
        if authorize(context):
            self._add_volume_mig_status_attribute(req, resp_obj.obj['volume'])

    @wsgi.extends
    def detail(self, req, resp_obj):
        context = req.environ['cinder.context']
        if authorize(context):
            for vol in list(resp_obj.obj['volumes']):
                self._add_volume_mig_status_attribute(req, vol)


class Volume_mig_status_attribute(extensions.ExtensionDescriptor):
    """Expose migration_status as an attribute of a volume."""

    name = "VolumeMigStatusAttribute"
    alias = "os-vol-mig-status-attr"
    updated = "2013-08-08T00:00:00+00:00"

    def get_controller_extensions(self):
        controller = VolumeMigStatusAttributeController()
        extension = extensions.ControllerExtension(self, 'volumes', controller)
        return [extension]
