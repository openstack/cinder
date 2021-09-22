# Copyright (c) 2021 SAP Corporation
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

"""The Migrate by connector API."""


from oslo_log import log as logging
from oslo_utils import strutils
from six.moves import http_client

from cinder.api.contrib import admin_actions
from cinder.api import extensions
from cinder.api.openstack import wsgi
from cinder.api.schemas import vmware_extension_actions as vmware_actions
from cinder.api import validation


LOG = logging.getLogger(__name__)


class VMWareVolumeExtensionsController(admin_actions.VolumeAdminController):

    collection = 'volumes'

    @wsgi.response(http_client.ACCEPTED)
    @wsgi.action('os-migrate_volume_by_connector')
    @validation.schema(vmware_actions.migrate_volume_by_connector)
    def _migrate_volume_by_connector(self, req, id, body):
        """Migrate a volume based on connector.

        This is an SAP VMWare extension that requires
        the connector of the vmware vcenter to be provided.
        The connector will contain the correct vcenter uuid
        so that the scheduler can find the right cinder backend
        to migrate the volume.
        """
        context = req.environ['cinder.context']
        # Not found exception will be handled at the wsgi level
        volume = self._get(context, id)
        self.authorize(context, 'migrate_volume', target_obj=volume)
        params = body['os-migrate_volume_by_connector']
        connector = params.get('connector', {})
        lock_volume = strutils.bool_from_string(
            params.get('lock_volume', False),
            strict=True)

        self.volume_api.migrate_volume_by_connector(
            context, volume, connector, lock_volume)


class Vmware_migrate(extensions.ExtensionDescriptor):
    """Enable admin actions."""

    name = "Vmware_migrate"
    alias = "os-vmware-admin-actions"
    updated = "2021-09-25T00:00:00+00:00"

    def get_controller_extensions(self):
        controller = VMWareVolumeExtensionsController()
        extension = extensions.ControllerExtension(
            self, controller.collection, controller)
        return [extension]
