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
import logging

import six
import webob

from cinder.api import common
from cinder.api import extensions
from cinder.api.openstack import wsgi
from cinder.api import xmlutil
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
        try:
            volume = self.volume_api.get(context, volume_id)
            meta = self.volume_api.get_volume_image_metadata(context, volume)
        except exception.VolumeNotFound:
            msg = _('Volume with volume id %s does not exist.') % volume_id
            raise webob.exc.HTTPNotFound(explanation=msg)
        return (volume, meta)

    def _get_all_images_metadata(self, context):
        """Returns the image metadata for all volumes."""
        try:
            all_metadata = self.volume_api.get_volumes_image_metadata(context)
        except Exception as e:
            LOG.debug('Problem retrieving volume image metadata. '
                      'It will be skipped. Error: %s', six.text_type(e))
            all_metadata = {}
        return all_metadata

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
                image_meta = image_metas.get(vol['id'], {})
                vol['volume_image_metadata'] = dict(image_meta)

    @wsgi.extends
    def show(self, req, resp_obj, id):
        context = req.environ['cinder.context']
        if authorize(context):
            resp_obj.attach(xml=VolumeImageMetadataTemplate())
            self._add_image_metadata(context, [resp_obj.obj['volume']])

    @wsgi.extends
    def detail(self, req, resp_obj):
        context = req.environ['cinder.context']
        if authorize(context):
            resp_obj.attach(xml=VolumesImageMetadataTemplate())
            # Just get the image metadata of those volumes in response.
            self._add_image_metadata(context,
                                     list(resp_obj.obj.get('volumes', [])))

    @wsgi.action("os-set_image_metadata")
    @wsgi.serializers(xml=common.MetadataTemplate)
    @wsgi.deserializers(xml=common.MetadataDeserializer)
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
        except exception.VolumeNotFound:
            msg = _('Volume with volume id %s does not exist.') % volume_id
            raise webob.exc.HTTPNotFound(explanation=msg)
        except (ValueError, AttributeError):
            msg = _("Malformed request body.")
            raise webob.exc.HTTPBadRequest(explanation=msg)
        except exception.InvalidVolumeMetadata as error:
            raise webob.exc.HTTPBadRequest(explanation=error.msg)
        except exception.InvalidVolumeMetadataSize as error:
            raise webob.exc.HTTPRequestEntityTooLarge(explanation=error.msg)

    @wsgi.action("os-show_image_metadata")
    @wsgi.serializers(xml=common.MetadataTemplate)
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
                    msg = _("Metadata item was not found.")
                    raise webob.exc.HTTPNotFound(explanation=msg)

                self.volume_api.delete_volume_metadata(
                    context, vol, key,
                    meta_type=common.METADATA_TYPES.image)
            else:
                msg = _("The key cannot be None.")
                raise webob.exc.HTTPBadRequest(explanation=msg)

            return webob.Response(status_int=200)


class Volume_image_metadata(extensions.ExtensionDescriptor):
    """Show image metadata associated with the volume."""

    name = "VolumeImageMetadata"
    alias = "os-vol-image-meta"
    namespace = ("http://docs.openstack.org/volume/ext/"
                 "volume_image_metadata/api/v1")
    updated = "2012-12-07T00:00:00+00:00"

    def get_controller_extensions(self):
        controller = VolumeImageMetadataController()
        extension = extensions.ControllerExtension(self, 'volumes', controller)
        return [extension]


class VolumeImageMetadataMetadataTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('volume_image_metadata',
                                       selector='volume_image_metadata')
        elem = xmlutil.SubTemplateElement(root, 'meta',
                                          selector=xmlutil.get_items)
        elem.set('key', 0)
        elem.text = 1

        return xmlutil.MasterTemplate(root, 1)


class VolumeImageMetadataTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('volume', selector='volume')
        root.append(VolumeImageMetadataMetadataTemplate())

        alias = Volume_image_metadata.alias
        namespace = Volume_image_metadata.namespace

        return xmlutil.SlaveTemplate(root, 1, nsmap={alias: namespace})


class VolumesImageMetadataTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('volumes')
        elem = xmlutil.SubTemplateElement(root, 'volume', selector='volume')
        elem.append(VolumeImageMetadataMetadataTemplate())

        alias = Volume_image_metadata.alias
        namespace = Volume_image_metadata.namespace

        return xmlutil.SlaveTemplate(root, 1, nsmap={alias: namespace})
