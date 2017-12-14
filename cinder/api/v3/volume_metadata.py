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

from oslo_serialization import jsonutils
import six
from six.moves import http_client
import webob

from cinder.api import microversions as mv
from cinder.api.openstack import wsgi
from cinder.api.schemas import volume_metadata as metadata
from cinder.api.v2 import volume_metadata as volume_meta_v2
from cinder.api import validation


class Controller(volume_meta_v2.Controller):
    """The volume metadata API controller for the OpenStack API."""
    def _validate_etag(self, req, volume_id):
        if not req.if_match:
            return True
        context = req.environ['cinder.context']
        metadata = self._get_metadata(context, volume_id)
        data = jsonutils.dumps({"metadata": metadata})
        if six.PY3:
            data = data.encode('utf-8')
        checksum = hashlib.md5(data).hexdigest()
        return checksum in req.if_match.etags

    @wsgi.extends
    def index(self, req, volume_id):
        req_version = req.api_version_request
        metadata = super(Controller, self).index(req, volume_id)
        if req_version.matches(mv.ETAGS):
            data = jsonutils.dumps(metadata)
            if six.PY3:
                data = data.encode('utf-8')
            resp = webob.Response()
            resp.headers['Etag'] = hashlib.md5(data).hexdigest()
            resp.body = data
            return resp
        return metadata

    @wsgi.extends
    @validation.schema(metadata.update)
    def update(self, req, volume_id, id, body):
        req_version = req.api_version_request
        if req_version.matches(mv.ETAGS):
            if not self._validate_etag(req, volume_id):
                return webob.Response(
                    status_int=http_client.PRECONDITION_FAILED)
        return super(Controller, self).update(req, volume_id,
                                              id, body=body)

    @wsgi.extends
    @validation.schema(metadata.create)
    def update_all(self, req, volume_id, body):
        req_version = req.api_version_request
        if req_version.matches(mv.ETAGS):
            if not self._validate_etag(req, volume_id):
                return webob.Response(
                    status_int=http_client.PRECONDITION_FAILED)
        return super(Controller, self).update_all(req, volume_id,
                                                  body=body)


def create_resource():
    return wsgi.Resource(Controller())
