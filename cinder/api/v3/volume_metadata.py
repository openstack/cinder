# Copyright 2016 OpenStack Foundation.
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

"""The volume metadata V3 api."""

import hashlib
from http import HTTPStatus

from oslo_serialization import jsonutils
import webob

from cinder.api import common
from cinder.api import microversions as mv
from cinder.api.openstack import wsgi
from cinder.api.schemas import volume_metadata as schema
from cinder.api import validation
from cinder import exception
from cinder.i18n import _
from cinder import volume


class VolumeMetadataController(wsgi.Controller):
    """The volume metadata API controller for the OpenStack API."""
    def __init__(self):
        self.volume_api = volume.API()
        super().__init__()

    def _get_metadata(self, context, volume_id):
        # The metadata is at the second position of the tuple returned
        # from _get_volume_and_metadata
        return self._get_volume_and_metadata(context, volume_id)[1]

    def _get_volume_and_metadata(self, context, volume_id):
        # Not found exception will be handled at the wsgi level
        volume = self.volume_api.get(context, volume_id)
        meta = self.volume_api.get_volume_metadata(context, volume)
        return (volume, meta)

    def _validate_etag(self, req, volume_id):
        if not req.if_match:
            return True
        context = req.environ['cinder.context']
        metadata = self._get_metadata(context, volume_id)
        data = jsonutils.dumps({"metadata": metadata})
        data = data.encode('utf-8')
        checksum = hashlib.md5(data, usedforsecurity=False).hexdigest()
        return checksum in req.if_match.etags

    @wsgi.extends
    def index(self, req, volume_id):
        context = req.environ['cinder.context']
        metadata = {'metadata': self._get_metadata(context, volume_id)}
        if req.api_version_request.matches(mv.ETAGS):
            data = jsonutils.dumps(metadata)
            data = data.encode('utf-8')
            resp = webob.Response()
            resp.headers['Etag'] = hashlib.md5(
                data, usedforsecurity=False).hexdigest()
            resp.body = data
            return resp
        return metadata

    @validation.schema(schema.create)
    def create(self, req, volume_id, body):
        context = req.environ['cinder.context']
        metadata = body['metadata']

        new_metadata = self._update_volume_metadata(
            context, volume_id, metadata, delete=False, use_create=True)
        return {'metadata': new_metadata}

    def _update_volume_metadata(self, context, volume_id, metadata,
                                delete=False, use_create=False):
        try:
            volume = self.volume_api.get(context, volume_id)
            if use_create:
                return self.volume_api.create_volume_metadata(context, volume,
                                                              metadata)
            else:
                return self.volume_api.update_volume_metadata(
                    context, volume, metadata, delete,
                    meta_type=common.METADATA_TYPES.user)
        # Not found exception will be handled at the wsgi level
        except (ValueError, AttributeError):
            msg = _("Malformed request body")
            raise webob.exc.HTTPBadRequest(explanation=msg)

        except exception.InvalidVolumeMetadata as error:
            raise webob.exc.HTTPBadRequest(explanation=error.msg)

        except exception.InvalidVolumeMetadataSize as error:
            raise webob.exc.HTTPRequestEntityTooLarge(explanation=error.msg)

    @wsgi.extends
    @validation.schema(schema.update)
    def update(self, req, volume_id, id, body):
        if req.api_version_request.matches(mv.ETAGS):
            if not self._validate_etag(req, volume_id):
                return webob.Response(
                    status_int=HTTPStatus.PRECONDITION_FAILED)

        meta_item = body['meta']

        if id not in meta_item:
            expl = _('Request body and URI mismatch')
            raise webob.exc.HTTPBadRequest(explanation=expl)

        if len(meta_item) > 1:
            expl = _('Request body contains too many items')
            raise webob.exc.HTTPBadRequest(explanation=expl)

        context = req.environ['cinder.context']
        self._update_volume_metadata(
            context, volume_id, meta_item, delete=False)

        return {'meta': meta_item}

    @wsgi.extends
    @validation.schema(schema.create)
    def update_all(self, req, volume_id, body):
        if req.api_version_request.matches(mv.ETAGS):
            if not self._validate_etag(req, volume_id):
                return webob.Response(
                    status_int=HTTPStatus.PRECONDITION_FAILED)

        metadata = body['metadata']
        context = req.environ['cinder.context']

        new_metadata = self._update_volume_metadata(
            context, volume_id, metadata, delete=True)

        return {'metadata': new_metadata}

    def show(self, req, volume_id, id):
        """Return a single metadata item."""
        context = req.environ['cinder.context']
        data = self._get_metadata(context, volume_id)

        try:
            return {'meta': {id: data[id]}}
        except KeyError:
            raise exception.VolumeMetadataNotFound(volume_id=volume_id,
                                                   metadata_key=id)

    def delete(self, req, volume_id, id):
        """Deletes an existing metadata."""
        context = req.environ['cinder.context']

        volume, metadata = self._get_volume_and_metadata(context, volume_id)

        if id not in metadata:
            raise exception.VolumeMetadataNotFound(volume_id=volume_id,
                                                   metadata_key=id)

        # Not found exception will be handled at the wsgi level
        self.volume_api.delete_volume_metadata(
            context,
            volume,
            id,
            meta_type=common.METADATA_TYPES.user)
        return webob.Response(status_int=HTTPStatus.OK)


def create_resource():
    return wsgi.Resource(VolumeMetadataController())
