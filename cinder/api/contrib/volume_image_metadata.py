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

"""The Volume Image Metadata API extension."""
from six.moves import http_client
import webob

from oslo_log import log as logging

from cinder.api import common
from cinder.api import extensions
from cinder.api.openstack import wsgi
from cinder import exception
from cinder.i18n import _
from cinder import volume


LOG = logging.getLogger(__name__)

authorize = extensions.soft_extension_authorizer('volume',
                                                 'volume_image_metadata')


class VolumeImageMetadataController(wsgi.Controller):
    def __init__(self, *args, **kwargs):
        super(VolumeImageMetadataController, self).__init__(*args, **kwargs)
        self.volume_api = volume.API()

    def _get_image_metadata(self, context, volume_id):
        # Not found exception will be handled at the wsgi level
        volume = self.volume_api.get(context, volume_id)
        meta = self.volume_api.get_volume_image_metadata(context, volume)
        return (volume, meta)

    def _add_image_metadata(self, context, resp_volume_list, image_metas=None):
        """Appends the image metadata to each of the given volume.

        :param context: the request context
        :param resp_volume_list: the response volume list
        :param image_metas: The image metadata to append, if None is provided
                            it will be retrieved from the database. An empty
                            dict means there is no metadata and it should not
                            be retrieved from the db.
        """
        vol_id_list = []
        for vol in resp_volume_list:
            vol_id_list.append(vol['id'])
        if image_metas is None:
            try:
                image_metas = self.volume_api.get_list_volumes_image_metadata(
                    context, vol_id_list)
            except Exception as e:
                LOG.debug('Get image metadata error: %s', e)
                return
        if image_metas:
            for vol in resp_volume_list:
                image_meta = image_metas.get(vol['id'])
                if image_meta:
                    vol['volume_image_metadata'] = dict(image_meta)

    @wsgi.extends
    def show(self, req, resp_obj, id):
        context = req.environ['cinder.context']
        if authorize(context):
            self._add_image_metadata(context, [resp_obj.obj['volume']])

    @wsgi.extends
    def detail(self, req, resp_obj):
        context = req.environ['cinder.context']
        if authorize(context):
            # Just get the image metadata of those volumes in response.
            volumes = list(resp_obj.obj.get('volumes', []))
            if volumes:
                self._add_image_metadata(context, volumes)

    @wsgi.action("os-set_image_metadata")
    def create(self, req, id, body):
        context = req.environ['cinder.context']
        if authorize(context):
            try:
                metadata = body['os-set_image_metadata']['metadata']
            except (KeyError, TypeError):
                msg = _("Malformed request body.")
                raise webob.exc.HTTPBadRequest(explanation=msg)
            new_metadata = self._update_volume_image_metadata(context,
                                                              id,
                                                              metadata,
                                                              delete=False)

            return {'metadata': new_metadata}

    def _update_volume_image_metadata(self, context,
                                      volume_id,
                                      metadata,
                                      delete=False):
        try:
            volume = self.volume_api.get(context, volume_id)
            return self.volume_api.update_volume_metadata(
                context,
                volume,
                metadata,
                delete=False,
                meta_type=common.METADATA_TYPES.image)
        # Not found exception will be handled at the wsgi level
        except (ValueError, AttributeError):
            msg = _("Malformed request body.")
            raise webob.exc.HTTPBadRequest(explanation=msg)
        except exception.InvalidVolumeMetadata as error:
            raise webob.exc.HTTPBadRequest(explanation=error.msg)
        except exception.InvalidVolumeMetadataSize as error:
            raise webob.exc.HTTPRequestEntityTooLarge(explanation=error.msg)

    @wsgi.action("os-show_image_metadata")
    def index(self, req, id, body):
        context = req.environ['cinder.context']
        return {'metadata': self._get_image_metadata(context, id)[1]}

    @wsgi.action("os-unset_image_metadata")
    def delete(self, req, id, body):
        """Deletes an existing image metadata."""
        context = req.environ['cinder.context']
        if authorize(context):
            try:
                key = body['os-unset_image_metadata']['key']
            except (KeyError, TypeError):
                msg = _("Malformed request body.")
                raise webob.exc.HTTPBadRequest(explanation=msg)

            if key:
                vol, metadata = self._get_image_metadata(context, id)
                if key not in metadata:
                    raise exception.GlanceMetadataNotFound(id=id)

                self.volume_api.delete_volume_metadata(
                    context, vol, key,
                    meta_type=common.METADATA_TYPES.image)
            else:
                msg = _("The key cannot be None.")
                raise webob.exc.HTTPBadRequest(explanation=msg)

            return webob.Response(status_int=http_client.OK)


class Volume_image_metadata(extensions.ExtensionDescriptor):
    """Show image metadata associated with the volume."""

    name = "VolumeImageMetadata"
    alias = "os-vol-image-meta"
    updated = "2012-12-07T00:00:00+00:00"

    def get_controller_extensions(self):
        controller = VolumeImageMetadataController()
        extension = extensions.ControllerExtension(self, 'volumes', controller)
        return [extension]
