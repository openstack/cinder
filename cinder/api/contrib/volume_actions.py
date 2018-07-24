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


from castellan import key_manager
from oslo_config import cfg
import oslo_messaging as messaging
from oslo_utils import strutils
import six
from six.moves import http_client
import webob

from cinder.api import extensions
from cinder.api import microversions as mv
from cinder.api.openstack import wsgi
from cinder.api.schemas import volume_actions as volume_action
from cinder.api import validation
from cinder import exception
from cinder.i18n import _
from cinder.policies import volume_actions as policy
from cinder import volume


CONF = cfg.CONF


class VolumeActionsController(wsgi.Controller):
    def __init__(self, *args, **kwargs):
        super(VolumeActionsController, self).__init__(*args, **kwargs)
        self._key_mgr = None
        self.volume_api = volume.API()

    @property
    def _key_manager(self):
        # Allows for lazy initialization of the key manager
        if self._key_mgr is None:
            self._key_mgr = key_manager.API(CONF)

        return self._key_mgr

    @wsgi.response(http_client.ACCEPTED)
    @wsgi.action('os-attach')
    @validation.schema(volume_action.attach)
    def _attach(self, req, id, body):
        """Add attachment metadata."""
        context = req.environ['cinder.context']
        # Not found exception will be handled at the wsgi level
        volume = self.volume_api.get(context, id)

        # instance UUID is an option now
        instance_uuid = None
        if 'instance_uuid' in body['os-attach']:
            instance_uuid = body['os-attach']['instance_uuid']
        host_name = None
        # Keep API backward compatibility
        if 'host_name' in body['os-attach']:
            host_name = body['os-attach']['host_name']
        mountpoint = body['os-attach']['mountpoint']
        mode = body['os-attach'].get('mode', 'rw')

        try:
            self.volume_api.attach(context, volume,
                                   instance_uuid, host_name, mountpoint, mode)
        except messaging.RemoteError as error:
            if error.exc_type in ['InvalidVolume', 'InvalidUUID',
                                  'InvalidVolumeAttachMode']:
                msg = _("Error attaching volume - %(err_type)s: "
                        "%(err_msg)s") % {
                    'err_type': error.exc_type, 'err_msg': error.value}
                raise webob.exc.HTTPBadRequest(explanation=msg)
            else:
                # There are also few cases where attach call could fail due to
                # db or volume driver errors. These errors shouldn't be exposed
                # to the user and in such cases it should raise 500 error.
                raise

    @wsgi.response(http_client.ACCEPTED)
    @wsgi.action('os-detach')
    @validation.schema(volume_action.detach)
    def _detach(self, req, id, body):
        """Clear attachment metadata."""
        context = req.environ['cinder.context']
        # Not found exception will be handled at the wsgi level
        volume = self.volume_api.get(context, id)

        attachment_id = None
        attachment_id = body['os-detach'].get('attachment_id', None)

        try:
            self.volume_api.detach(context, volume, attachment_id)
        except messaging.RemoteError as error:
            if error.exc_type in ['VolumeAttachmentNotFound', 'InvalidVolume']:
                msg = _("Error detaching volume - %(err_type)s: "
                        "%(err_msg)s") % {
                    'err_type': error.exc_type, 'err_msg': error.value}
                raise webob.exc.HTTPBadRequest(explanation=msg)
            else:
                # There are also few cases where detach call could fail due to
                # db or volume driver errors. These errors shouldn't be exposed
                # to the user and in such cases it should raise 500 error.
                raise

    @wsgi.response(http_client.ACCEPTED)
    @wsgi.action('os-reserve')
    def _reserve(self, req, id, body):
        """Mark volume as reserved."""
        context = req.environ['cinder.context']
        # Not found exception will be handled at the wsgi level
        volume = self.volume_api.get(context, id)

        self.volume_api.reserve_volume(context, volume)

    @wsgi.response(http_client.ACCEPTED)
    @wsgi.action('os-unreserve')
    def _unreserve(self, req, id, body):
        """Unmark volume as reserved."""
        context = req.environ['cinder.context']
        # Not found exception will be handled at the wsgi level
        volume = self.volume_api.get(context, id)

        self.volume_api.unreserve_volume(context, volume)

    @wsgi.response(http_client.ACCEPTED)
    @wsgi.action('os-begin_detaching')
    def _begin_detaching(self, req, id, body):
        """Update volume status to 'detaching'."""
        context = req.environ['cinder.context']
        # Not found exception will be handled at the wsgi level
        volume = self.volume_api.get(context, id)

        self.volume_api.begin_detaching(context, volume)

    @wsgi.response(http_client.ACCEPTED)
    @wsgi.action('os-roll_detaching')
    def _roll_detaching(self, req, id, body):
        """Roll back volume status to 'in-use'."""
        context = req.environ['cinder.context']
        # Not found exception will be handled at the wsgi level
        volume = self.volume_api.get(context, id)

        self.volume_api.roll_detaching(context, volume)

    @wsgi.action('os-initialize_connection')
    @validation.schema(volume_action.initialize_connection)
    def _initialize_connection(self, req, id, body):
        """Initialize volume attachment."""
        context = req.environ['cinder.context']
        # Not found exception will be handled at the wsgi level
        volume = self.volume_api.get(context, id)
        connector = body['os-initialize_connection']['connector']
        try:
            info = self.volume_api.initialize_connection(context,
                                                         volume,
                                                         connector)
        except exception.InvalidInput as err:
            raise webob.exc.HTTPBadRequest(
                explanation=err.msg)
        except exception.VolumeBackendAPIException:
            msg = _("Unable to fetch connection information from backend.")
            raise webob.exc.HTTPInternalServerError(explanation=msg)
        except messaging.RemoteError as error:
            if error.exc_type == 'InvalidInput':
                raise exception.InvalidInput(reason=error.value)
            raise

        return {'connection_info': info}

    @wsgi.response(http_client.ACCEPTED)
    @wsgi.action('os-terminate_connection')
    @validation.schema(volume_action.terminate_connection)
    def _terminate_connection(self, req, id, body):
        """Terminate volume attachment."""
        context = req.environ['cinder.context']
        # Not found exception will be handled at the wsgi level
        volume = self.volume_api.get(context, id)
        connector = body['os-terminate_connection']['connector']
        try:
            self.volume_api.terminate_connection(context, volume, connector)
        except exception.VolumeBackendAPIException:
            msg = _("Unable to terminate volume connection from backend.")
            raise webob.exc.HTTPInternalServerError(explanation=msg)

    @wsgi.response(http_client.ACCEPTED)
    @wsgi.action('os-volume_upload_image')
    @validation.schema(volume_action.volume_upload_image, mv.V2_BASE_VERSION,
                       mv.get_prior_version(mv.UPLOAD_IMAGE_PARAMS))
    @validation.schema(volume_action.volume_upload_image_v31,
                       mv.UPLOAD_IMAGE_PARAMS)
    def _volume_upload_image(self, req, id, body):
        """Uploads the specified volume to image service."""
        context = req.environ['cinder.context']
        params = body['os-volume_upload_image']
        req_version = req.api_version_request

        force = params.get('force', 'False')
        force = strutils.bool_from_string(force, strict=True)

        # Not found exception will be handled at the wsgi level
        volume = self.volume_api.get(context, id)

        context.authorize(policy.UPLOAD_IMAGE_POLICY)
        # check for valid disk-format
        disk_format = params.get("disk_format", "raw")

        image_metadata = {"container_format": params.get(
            "container_format", "bare"),
            "disk_format": disk_format,
            "name": params["image_name"]}

        if volume.encryption_key_id:
            # Clone volume encryption key: the current key cannot
            # be reused because it will be deleted when the volume is
            # deleted.
            # TODO(eharney): Currently, there is no mechanism to remove
            # these keys, because Glance will not delete the key from
            # Barbican when the image is deleted.
            encryption_key_id = self._key_manager.store(
                context,
                self._key_manager.get(context, volume.encryption_key_id))

            image_metadata['cinder_encryption_key_id'] = encryption_key_id

        if req_version >= mv.get_api_version(
                mv.UPLOAD_IMAGE_PARAMS):

            image_metadata['visibility'] = params.get('visibility', 'private')
            image_metadata['protected'] = strutils.bool_from_string(
                params.get('protected', 'False'), strict=True)

            if image_metadata['visibility'] == 'public':
                context.authorize(policy.UPLOAD_PUBLIC_POLICY)

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

    @wsgi.response(http_client.ACCEPTED)
    @wsgi.action('os-extend')
    @validation.schema(volume_action.extend)
    def _extend(self, req, id, body):
        """Extend size of volume."""
        context = req.environ['cinder.context']
        req_version = req.api_version_request
        # Not found exception will be handled at the wsgi level
        volume = self.volume_api.get(context, id)

        size = int(body['os-extend']['new_size'])
        try:
            if (req_version.matches(mv.VOLUME_EXTEND_INUSE) and
                    volume.status in ['in-use']):
                self.volume_api.extend_attached_volume(context, volume, size)
            else:
                self.volume_api.extend(context, volume, size)
        except exception.InvalidVolume as error:
            raise webob.exc.HTTPBadRequest(explanation=error.msg)

    @wsgi.response(http_client.ACCEPTED)
    @wsgi.action('os-update_readonly_flag')
    @validation.schema(volume_action.volume_readonly_update)
    def _volume_readonly_update(self, req, id, body):
        """Update volume readonly flag."""
        context = req.environ['cinder.context']
        # Not found exception will be handled at the wsgi level
        volume = self.volume_api.get(context, id)

        readonly_flag = body['os-update_readonly_flag']['readonly']

        readonly_flag = strutils.bool_from_string(readonly_flag,
                                                  strict=True)

        self.volume_api.update_readonly_flag(context, volume, readonly_flag)

    @wsgi.response(http_client.ACCEPTED)
    @wsgi.action('os-retype')
    @validation.schema(volume_action.retype)
    def _retype(self, req, id, body):
        """Change type of existing volume."""
        context = req.environ['cinder.context']
        volume = self.volume_api.get(context, id)
        new_type = body['os-retype']['new_type']
        policy = body['os-retype'].get('migration_policy')

        self.volume_api.retype(context, volume, new_type, policy)

    @wsgi.response(http_client.OK)
    @wsgi.action('os-set_bootable')
    @validation.schema(volume_action.set_bootable)
    def _set_bootable(self, req, id, body):
        """Update bootable status of a volume."""
        context = req.environ['cinder.context']
        # Not found exception will be handled at the wsgi level
        volume = self.volume_api.get(context, id)

        bootable = strutils.bool_from_string(
            body['os-set_bootable']['bootable'], strict=True)

        update_dict = {'bootable': bootable}

        self.volume_api.update(context, volume, update_dict)


class Volume_actions(extensions.ExtensionDescriptor):
    """Enable volume actions."""

    name = "VolumeActions"
    alias = "os-volume-actions"
    updated = "2012-05-31T00:00:00+00:00"

    def get_controller_extensions(self):
        controller = VolumeActionsController()
        extension = extensions.ControllerExtension(self, 'volumes', controller)
        return [extension]
