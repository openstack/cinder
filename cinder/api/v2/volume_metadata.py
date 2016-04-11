# Copyright 2013 OpenStack Foundation.
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

import webob

from cinder.api import common
from cinder.api.openstack import wsgi
from cinder import exception
from cinder.i18n import _
from cinder import volume


class Controller(wsgi.Controller):
    """The volume metadata API controller for the OpenStack API."""

    def __init__(self):
        self.volume_api = volume.API()
        super(Controller, self).__init__()

    def _get_metadata(self, context, volume_id):
        # The metadata is at the second position of the tuple returned
        # from _get_volume_and_metadata
        return self._get_volume_and_metadata(context, volume_id)[1]

    def _get_volume_and_metadata(self, context, volume_id):
        try:
            volume = self.volume_api.get(context, volume_id)
            meta = self.volume_api.get_volume_metadata(context, volume)
        except exception.VolumeNotFound as error:
            raise webob.exc.HTTPNotFound(explanation=error.msg)
        return (volume, meta)

    @wsgi.serializers(xml=common.MetadataTemplate)
    def index(self, req, volume_id):
        """Returns the list of metadata for a given volume."""
        context = req.environ['cinder.context']
        return {'metadata': self._get_metadata(context, volume_id)}

    @wsgi.serializers(xml=common.MetadataTemplate)
    @wsgi.deserializers(xml=common.MetadataDeserializer)
    def create(self, req, volume_id, body):
        self.assert_valid_body(body, 'metadata')
        context = req.environ['cinder.context']
        metadata = body['metadata']

        new_metadata = self._update_volume_metadata(context,
                                                    volume_id,
                                                    metadata,
                                                    delete=False)

        return {'metadata': new_metadata}

    @wsgi.serializers(xml=common.MetaItemTemplate)
    @wsgi.deserializers(xml=common.MetaItemDeserializer)
    def update(self, req, volume_id, id, body):
        self.assert_valid_body(body, 'meta')
        meta_item = body['meta']

        if id not in meta_item:
            expl = _('Request body and URI mismatch')
            raise webob.exc.HTTPBadRequest(explanation=expl)

        if len(meta_item) > 1:
            expl = _('Request body contains too many items')
            raise webob.exc.HTTPBadRequest(explanation=expl)

        context = req.environ['cinder.context']
        self._update_volume_metadata(context,
                                     volume_id,
                                     meta_item,
                                     delete=False)

        return {'meta': meta_item}

    @wsgi.serializers(xml=common.MetadataTemplate)
    @wsgi.deserializers(xml=common.MetadataDeserializer)
    def update_all(self, req, volume_id, body):
        self.assert_valid_body(body, 'metadata')
        metadata = body['metadata']
        context = req.environ['cinder.context']

        new_metadata = self._update_volume_metadata(context,
                                                    volume_id,
                                                    metadata,
                                                    delete=True)

        return {'metadata': new_metadata}

    def _update_volume_metadata(self, context,
                                volume_id, metadata,
                                delete=False):
        try:
            volume = self.volume_api.get(context, volume_id)
            return self.volume_api.update_volume_metadata(
                context,
                volume,
                metadata,
                delete,
                meta_type=common.METADATA_TYPES.user)
        except exception.VolumeNotFound as error:
            raise webob.exc.HTTPNotFound(explanation=error.msg)

        except (ValueError, AttributeError):
            msg = _("Malformed request body")
            raise webob.exc.HTTPBadRequest(explanation=msg)

        except exception.InvalidVolumeMetadata as error:
            raise webob.exc.HTTPBadRequest(explanation=error.msg)

        except exception.InvalidVolumeMetadataSize as error:
            raise webob.exc.HTTPRequestEntityTooLarge(explanation=error.msg)

    @wsgi.serializers(xml=common.MetaItemTemplate)
    def show(self, req, volume_id, id):
        """Return a single metadata item."""
        context = req.environ['cinder.context']
        data = self._get_metadata(context, volume_id)

        try:
            return {'meta': {id: data[id]}}
        except KeyError:
            msg = _("Metadata item was not found")
            raise webob.exc.HTTPNotFound(explanation=msg)

    def delete(self, req, volume_id, id):
        """Deletes an existing metadata."""
        context = req.environ['cinder.context']

        volume, metadata = self._get_volume_and_metadata(context, volume_id)

        if id not in metadata:
            msg = _("Metadata item was not found")
            raise webob.exc.HTTPNotFound(explanation=msg)

        try:
            self.volume_api.delete_volume_metadata(
                context,
                volume,
                id,
                meta_type=common.METADATA_TYPES.user)
        except exception.VolumeNotFound as error:
            raise webob.exc.HTTPNotFound(explanation=error.msg)
        return webob.Response(status_int=200)


def create_resource():
    return wsgi.Resource(Controller())
