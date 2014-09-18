#   Copyright 2014 IBM Corp.
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

import webob
from webob import exc

from cinder.api import extensions
from cinder.api.openstack import wsgi
from cinder import exception
from cinder.i18n import _
from cinder.openstack.common import log as logging
from cinder import volume

LOG = logging.getLogger(__name__)
authorize = extensions.extension_authorizer('volume', 'volume_unmanage')


class VolumeUnmanageController(wsgi.Controller):
    def __init__(self, *args, **kwargs):
        super(VolumeUnmanageController, self).__init__(*args, **kwargs)
        self.volume_api = volume.API()

    @wsgi.response(202)
    @wsgi.action('os-unmanage')
    def unmanage(self, req, id, body):
        """Stop managing a volume.

        This action is very much like a delete, except that a different
        method (unmanage) is called on the Cinder driver.  This has the effect
        of removing the volume from Cinder management without actually
        removing the backend storage object associated with it.

        There are no required parameters.

        A Not Found error is returned if the specified volume does not exist.

        A Bad Request error is returned if the specified volume is still
        attached to an instance.
        """
        context = req.environ['cinder.context']
        authorize(context)

        LOG.info(_("Unmanage volume with id: %s"), id, context=context)

        try:
            vol = self.volume_api.get(context, id)
            self.volume_api.delete(context, vol, unmanage_only=True)
        except exception.NotFound:
            msg = _("Volume could not be found")
            raise exc.HTTPNotFound(explanation=msg)
        except exception.VolumeAttached:
            msg = _("Volume cannot be deleted while in attached state")
            raise exc.HTTPBadRequest(explanation=msg)
        return webob.Response(status_int=202)


class Volume_unmanage(extensions.ExtensionDescriptor):
    """Enable volume unmanage operation."""

    name = "VolumeUnmanage"
    alias = "os-volume-unmanage"
    namespace = "http://docs.openstack.org/volume/ext/volume-unmanage/api/v1.1"
    updated = "2012-05-31T00:00:00+00:00"

    def get_controller_extensions(self):
        controller = VolumeUnmanageController()
        extension = extensions.ControllerExtension(self, 'volumes', controller)
        return [extension]
