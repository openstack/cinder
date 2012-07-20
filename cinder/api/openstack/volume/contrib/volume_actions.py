#   Copyright 2012 OpenStack, LLC.
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

import os.path
import traceback

import webob
from webob import exc

from cinder.api.openstack import common
from cinder.api.openstack import extensions
from cinder.api.openstack import wsgi
from cinder import volume
from cinder import exception
from cinder import flags
from cinder.openstack.common import log as logging


FLAGS = flags.FLAGS
LOG = logging.getLogger(__name__)


def authorize(context, action_name):
    action = 'volume_actions:%s' % action_name
    extensions.extension_authorizer('volume', action)(context)


class VolumeActionsController(wsgi.Controller):
    def __init__(self, *args, **kwargs):
        super(VolumeActionsController, self).__init__(*args, **kwargs)
        self.volume_api = volume.API()

    @wsgi.action('os-attach')
    def _attach(self, req, id, body):
        """Add attachment metadata."""
        context = req.environ['cinder.context']
        volume = self.volume_api.get(context, id)

        instance_uuid = body['os-attach']['instance_uuid']
        mountpoint = body['os-attach']['mountpoint']

        self.volume_api.attach(context, volume,
                               instance_uuid, mountpoint)
        return webob.Response(status_int=202)

    @wsgi.action('os-detach')
    def _detach(self, req, id, body):
        """Clear attachment metadata."""
        context = req.environ['cinder.context']
        volume = self.volume_api.get(context, id)
        self.volume_api.detach(context, volume)
        return webob.Response(status_int=202)

    @wsgi.action('os-reserve')
    def _reserve(self, req, id, body):
        """Mark volume as reserved."""
        context = req.environ['cinder.context']
        volume = self.volume_api.get(context, id)
        self.volume_api.reserve_volume(context, volume)
        return webob.Response(status_int=202)

    @wsgi.action('os-unreserve')
    def _unreserve(self, req, id, body):
        """Unmark volume as reserved."""
        context = req.environ['cinder.context']
        volume = self.volume_api.get(context, id)
        self.volume_api.unreserve_volume(context, volume)
        return webob.Response(status_int=202)

    @wsgi.action('os-initialize_connection')
    def _initialize_connection(self, req, id, body):
        """Initialize volume attachment."""
        context = req.environ['cinder.context']
        volume = self.volume_api.get(context, id)
        connector = body['os-initialize_connection']['connector']
        info = self.volume_api.initialize_connection(context,
                                                     volume,
                                                     connector)
        return {'connection_info': info}

    @wsgi.action('os-terminate_connection')
    def _terminate_connection(self, req, id, body):
        """Terminate volume attachment."""
        context = req.environ['cinder.context']
        volume = self.volume_api.get(context, id)
        connector = body['os-terminate_connection']['connector']
        self.volume_api.terminate_connection(context, volume, connector)
        return webob.Response(status_int=202)


class Volume_actions(extensions.ExtensionDescriptor):
    """Enable volume actions
    """

    name = "VolumeActions"
    alias = "os-volume-actions"
    namespace = "http://docs.openstack.org/volume/ext/volume-actions/api/v1.1"
    updated = "2012-05-31T00:00:00+00:00"

    def get_controller_extensions(self):
        controller = VolumeActionsController()
        extension = extensions.ControllerExtension(self, 'volumes', controller)
        return [extension]
