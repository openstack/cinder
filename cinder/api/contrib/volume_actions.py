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
import oslo_messaging as messaging
from oslo_utils import strutils
import six
import webob

from cinder.api import extensions
from cinder.api.openstack import wsgi
from cinder.api import xmlutil
from cinder import exception
from cinder.i18n import _
from cinder import utils
from cinder import volume


LOG = logging.getLogger(__name__)


def authorize(context, action_name):
    action = 'volume_actions:%s' % action_name
    extensions.extension_authorizer('volume', action)(context)


class VolumeToImageSerializer(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('os-volume_upload_image',
                                       selector='os-volume_upload_image')
        root.set('id')
        root.set('updated_at')
        root.set('status')
        root.set('display_description')
        root.set('size')
        root.set('volume_type')
        root.set('image_id')
        root.set('container_format')
        root.set('disk_format')
        root.set('image_name')
        return xmlutil.MasterTemplate(root, 1)


class VolumeToImageDeserializer(wsgi.XMLDeserializer):
    """Deserializer to handle xml-formatted requests."""
    def default(self, string):
        dom = utils.safe_minidom_parse_string(string)
        action_node = dom.childNodes[0]
        action_name = action_node.tagName

        action_data = {}
        attributes = ["force", "image_name", "container_format", "disk_format"]
        for attr in attributes:
            if action_node.hasAttribute(attr):
                action_data[attr] = action_node.getAttribute(attr)
        if 'force' in action_data and action_data['force'] == 'True':
            action_data['force'] = True
        return {'body': {action_name: action_data}}


class VolumeActionsController(wsgi.Controller):
    def __init__(self, *args, **kwargs):
        super(VolumeActionsController, self).__init__(*args, **kwargs)
        self.volume_api = volume.API()

    @wsgi.action('os-attach')
    def _attach(self, req, id, body):
        """Add attachment metadata."""
        context = req.environ['cinder.context']
        try:
            volume = self.volume_api.get(context, id)
        except exception.VolumeNotFound as error:
            raise webob.exc.HTTPNotFound(explanation=error.msg)

        # instance uuid is an option now
        instance_uuid = None
        if 'instance_uuid' in body['os-attach']:
            instance_uuid = body['os-attach']['instance_uuid']
        host_name = None
        # Keep API backward compatibility
        if 'host_name' in body['os-attach']:
            host_name = body['os-attach']['host_name']
        mountpoint = body['os-attach']['mountpoint']
        if 'mode' in body['os-attach']:
            mode = body['os-attach']['mode']
        else:
            mode = 'rw'

        if instance_uuid and host_name:
            msg = _("Invalid request to attach volume to an "
                    "instance %(instance_uuid)s and a "
                    "host %(host_name)s simultaneously") % {
                'instance_uuid': instance_uuid,
                'host_name': host_name,
            }
            raise webob.exc.HTTPBadRequest(explanation=msg)
        elif instance_uuid is None and host_name is None:
            msg = _("Invalid request to attach volume to an invalid target")
            raise webob.exc.HTTPBadRequest(explanation=msg)

        if mode not in ('rw', 'ro'):
            msg = _("Invalid request to attach volume with an invalid mode. "
                    "Attaching mode should be 'rw' or 'ro'")
            raise webob.exc.HTTPBadRequest(explanation=msg)
        try:
            self.volume_api.attach(context, volume,
                                   instance_uuid, host_name, mountpoint, mode)
        except messaging.RemoteError as error:
            if error.exc_type in ['InvalidVolume', 'InvalidUUID',
                                  'InvalidVolumeAttachMode']:
                msg = "Error attaching volume - %(err_type)s: %(err_msg)s" % {
                      'err_type': error.exc_type, 'err_msg': error.value}
                raise webob.exc.HTTPBadRequest(explanation=msg)
            else:
                # There are also few cases where attach call could fail due to
                # db or volume driver errors. These errors shouldn't be exposed
                # to the user and in such cases it should raise 500 error.
                raise

        return webob.Response(status_int=202)

    @wsgi.action('os-detach')
    def _detach(self, req, id, body):
        """Clear attachment metadata."""
        context = req.environ['cinder.context']
        try:
            volume = self.volume_api.get(context, id)
        except exception.VolumeNotFound as error:
            raise webob.exc.HTTPNotFound(explanation=error.msg)

        attachment_id = None
        if body['os-detach']:
            attachment_id = body['os-detach'].get('attachment_id', None)

        try:
            self.volume_api.detach(context, volume, attachment_id)
        except messaging.RemoteError as error:
            if error.exc_type in ['VolumeAttachmentNotFound', 'InvalidVolume']:
                msg = "Error detaching volume - %(err_type)s: %(err_msg)s" % \
                      {'err_type': error.exc_type, 'err_msg': error.value}
                raise webob.exc.HTTPBadRequest(explanation=msg)
            else:
                # There are also few cases where detach call could fail due to
                # db or volume driver errors. These errors shouldn't be exposed
                # to the user and in such cases it should raise 500 error.
                raise

        return webob.Response(status_int=202)

    @wsgi.action('os-reserve')
    def _reserve(self, req, id, body):
        """Mark volume as reserved."""
        context = req.environ['cinder.context']
        try:
            volume = self.volume_api.get(context, id)
        except exception.VolumeNotFound as error:
            raise webob.exc.HTTPNotFound(explanation=error.msg)

        self.volume_api.reserve_volume(context, volume)
        return webob.Response(status_int=202)

    @wsgi.action('os-unreserve')
    def _unreserve(self, req, id, body):
        """Unmark volume as reserved."""
        context = req.environ['cinder.context']
        try:
            volume = self.volume_api.get(context, id)
        except exception.VolumeNotFound as error:
            raise webob.exc.HTTPNotFound(explanation=error.msg)

        self.volume_api.unreserve_volume(context, volume)
        return webob.Response(status_int=202)

    @wsgi.action('os-begin_detaching')
    def _begin_detaching(self, req, id, body):
        """Update volume status to 'detaching'."""
        context = req.environ['cinder.context']
        try:
            volume = self.volume_api.get(context, id)
        except exception.VolumeNotFound as error:
            raise webob.exc.HTTPNotFound(explanation=error.msg)

        self.volume_api.begin_detaching(context, volume)
        return webob.Response(status_int=202)

    @wsgi.action('os-roll_detaching')
    def _roll_detaching(self, req, id, body):
        """Roll back volume status to 'in-use'."""
        context = req.environ['cinder.context']
        try:
            volume = self.volume_api.get(context, id)
        except exception.VolumeNotFound as error:
            raise webob.exc.HTTPNotFound(explanation=error.msg)

        self.volume_api.roll_detaching(context, volume)
        return webob.Response(status_int=202)

    @wsgi.action('os-initialize_connection')
    def _initialize_connection(self, req, id, body):
        """Initialize volume attachment."""
        context = req.environ['cinder.context']
        try:
            volume = self.volume_api.get(context, id)
        except exception.VolumeNotFound as error:
            raise webob.exc.HTTPNotFound(explanation=error.msg)
        try:
            connector = body['os-initialize_connection']['connector']
        except KeyError:
            raise webob.exc.HTTPBadRequest(
                explanation=_("Must specify 'connector'"))
        try:
            info = self.volume_api.initialize_connection(context,
                                                         volume,
                                                         connector)
        except exception.InvalidInput as err:
            raise webob.exc.HTTPBadRequest(
                explanation=err)
        except exception.VolumeBackendAPIException as error:
            msg = _("Unable to fetch connection information from backend.")
            raise webob.exc.HTTPInternalServerError(explanation=msg)

        return {'connection_info': info}

    @wsgi.action('os-terminate_connection')
    def _terminate_connection(self, req, id, body):
        """Terminate volume attachment."""
        context = req.environ['cinder.context']
        try:
            volume = self.volume_api.get(context, id)
        except exception.VolumeNotFound as error:
            raise webob.exc.HTTPNotFound(explanation=error.msg)
        try:
            connector = body['os-terminate_connection']['connector']
        except KeyError:
            raise webob.exc.HTTPBadRequest(
                explanation=_("Must specify 'connector'"))
        try:
            self.volume_api.terminate_connection(context, volume, connector)
        except exception.VolumeBackendAPIException as error:
            msg = _("Unable to terminate volume connection from backend.")
            raise webob.exc.HTTPInternalServerError(explanation=msg)
        return webob.Response(status_int=202)

    @wsgi.response(202)
    @wsgi.action('os-volume_upload_image')
    @wsgi.serializers(xml=VolumeToImageSerializer)
    @wsgi.deserializers(xml=VolumeToImageDeserializer)
    def _volume_upload_image(self, req, id, body):
        """Uploads the specified volume to image service."""
        context = req.environ['cinder.context']
        params = body['os-volume_upload_image']
        if not params.get("image_name"):
            msg = _("No image_name was specified in request.")
            raise webob.exc.HTTPBadRequest(explanation=msg)

        force = params.get('force', 'False')
        try:
            force = strutils.bool_from_string(force, strict=True)
        except ValueError as error:
            msg = _("Invalid value for 'force': '%s'") % error.message
            raise webob.exc.HTTPBadRequest(explanation=msg)

        try:
            volume = self.volume_api.get(context, id)
        except exception.VolumeNotFound as error:
            raise webob.exc.HTTPNotFound(explanation=error.msg)

        authorize(context, "upload_image")
        image_metadata = {"container_format": params.get("container_format",
                                                         "bare"),
                          "disk_format": params.get("disk_format", "raw"),
                          "name": params["image_name"]}
        try:
            response = self.volume_api.copy_volume_to_image(context,
                                                            volume,
                                                            image_metadata,
                                                            force)
        except exception.InvalidVolume as error:
            raise webob.exc.HTTPBadRequest(explanation=error.msg)
        except ValueError as error:
            raise webob.exc.HTTPBadRequest(explanation=six.text_type(error))
        except messaging.RemoteError as error:
            msg = "%(err_type)s: %(err_msg)s" % {'err_type': error.exc_type,
                                                 'err_msg': error.value}
            raise webob.exc.HTTPBadRequest(explanation=msg)
        except Exception as error:
            raise webob.exc.HTTPBadRequest(explanation=six.text_type(error))
        return {'os-volume_upload_image': response}

    @wsgi.action('os-extend')
    def _extend(self, req, id, body):
        """Extend size of volume."""
        context = req.environ['cinder.context']
        try:
            volume = self.volume_api.get(context, id)
        except exception.VolumeNotFound as error:
            raise webob.exc.HTTPNotFound(explanation=error.msg)

        try:
            int(body['os-extend']['new_size'])
        except (KeyError, ValueError, TypeError):
            msg = _("New volume size must be specified as an integer.")
            raise webob.exc.HTTPBadRequest(explanation=msg)

        size = int(body['os-extend']['new_size'])
        try:
            self.volume_api.extend(context, volume, size)
        except exception.InvalidVolume as error:
            raise webob.exc.HTTPBadRequest(explanation=error.msg)

        return webob.Response(status_int=202)

    @wsgi.action('os-update_readonly_flag')
    def _volume_readonly_update(self, req, id, body):
        """Update volume readonly flag."""
        context = req.environ['cinder.context']
        try:
            volume = self.volume_api.get(context, id)
        except exception.VolumeNotFound as error:
            raise webob.exc.HTTPNotFound(explanation=error.msg)

        try:
            readonly_flag = body['os-update_readonly_flag']['readonly']
        except KeyError:
            msg = _("Must specify readonly in request.")
            raise webob.exc.HTTPBadRequest(explanation=msg)

        try:
            readonly_flag = strutils.bool_from_string(readonly_flag,
                                                      strict=True)
        except ValueError as error:
            msg = _("Invalid value for 'readonly': '%s'") % error.message
            raise webob.exc.HTTPBadRequest(explanation=msg)

        self.volume_api.update_readonly_flag(context, volume, readonly_flag)
        return webob.Response(status_int=202)

    @wsgi.action('os-retype')
    def _retype(self, req, id, body):
        """Change type of existing volume."""
        context = req.environ['cinder.context']
        volume = self.volume_api.get(context, id)
        try:
            new_type = body['os-retype']['new_type']
        except KeyError:
            msg = _("New volume type must be specified.")
            raise webob.exc.HTTPBadRequest(explanation=msg)
        policy = body['os-retype'].get('migration_policy')

        self.volume_api.retype(context, volume, new_type, policy)
        return webob.Response(status_int=202)

    @wsgi.action('os-set_bootable')
    def _set_bootable(self, req, id, body):
        """Update bootable status of a volume."""
        context = req.environ['cinder.context']
        try:
            volume = self.volume_api.get(context, id)
        except exception.VolumeNotFound as error:
            raise webob.exc.HTTPNotFound(explanation=error.msg)

        try:
            bootable = body['os-set_bootable']['bootable']
        except KeyError:
            msg = _("Must specify bootable in request.")
            raise webob.exc.HTTPBadRequest(explanation=msg)

        try:
            bootable = strutils.bool_from_string(bootable,
                                                 strict=True)
        except ValueError as error:
            msg = _("Invalid value for 'bootable': '%s'") % error.message
            raise webob.exc.HTTPBadRequest(explanation=msg)

        update_dict = {'bootable': bootable}

        self.volume_api.update(context, volume, update_dict)
        return webob.Response(status_int=200)


class Volume_actions(extensions.ExtensionDescriptor):
    """Enable volume actions."""

    name = "VolumeActions"
    alias = "os-volume-actions"
    namespace = "http://docs.openstack.org/volume/ext/volume-actions/api/v1.1"
    updated = "2012-05-31T00:00:00+00:00"

    def get_controller_extensions(self):
        controller = VolumeActionsController()
        extension = extensions.ControllerExtension(self, 'volumes', controller)
        return [extension]
