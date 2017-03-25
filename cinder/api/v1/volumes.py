# Copyright 2011 Justin Santa Barbara
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

"""The volumes api."""

from oslo_log import log as logging
from six.moves import http_client
from webob import exc

from cinder.api.openstack import wsgi
from cinder.api.v2 import volumes as volumes_v2


LOG = logging.getLogger(__name__)


def _attachment_v2_to_v1(vol):
    """Converts v2 attachment details to v1 format."""
    d = []
    attachments = vol.pop('attachments', [])
    for attachment in attachments:
        a = {'id': attachment.get('id'),
             'attachment_id': attachment.get('attachment_id'),
             'volume_id': attachment.get('volume_id'),
             'server_id': attachment.get('server_id'),
             'host_name': attachment.get('host_name'),
             'device': attachment.get('device'),
             }
        d.append(a)

    return d


def _volume_v2_to_v1(volv2_results, image_id=None):
    """Converts v2 volume details to v1 format."""
    volumes = volv2_results.get('volumes')
    if volumes is None:
        volumes = [volv2_results['volume']]

    for vol in volumes:
        # Need to form the string true/false explicitly here to
        # maintain our API contract
        if vol.get('multiattach'):
            vol['multiattach'] = 'true'
        else:
            vol['multiattach'] = 'false'

        if not vol.get('image_id') and image_id:
            vol['image_id'] = image_id

        vol['attachments'] = _attachment_v2_to_v1(vol)

        if not vol.get('metadata'):
            vol['metadata'] = {}

        # Convert the name changes
        vol['display_name'] = vol.pop('name')
        vol['display_description'] = vol.pop('description', '')

        # Remove the properties not present for v1
        vol.pop('consistencygroup_id', None)
        vol.pop('encryption_key_id', None)
        vol.pop('links', None)
        vol.pop('migration_status', None)
        vol.pop('replication_status', None)
        vol.pop('updated_at', None)
        vol.pop('user_id', None)

        LOG.debug("vol=%s", vol)

    return volv2_results


class VolumeController(volumes_v2.VolumeController):
    """The Volumes API controller for the OpenStack API."""

    def show(self, req, id):
        """Return data about the given volume."""
        return _volume_v2_to_v1(super(VolumeController, self).show(
            req, id))

    def index(self, req):
        """Returns a summary list of volumes."""

        # The v1 info was much more detailed than the v2 non-detailed result
        return _volume_v2_to_v1(
            super(VolumeController, self).detail(req))

    def detail(self, req):
        """Returns a detailed list of volumes."""
        return _volume_v2_to_v1(
            super(VolumeController, self).detail(req))

    @wsgi.response(http_client.OK)
    def create(self, req, body):
        """Creates a new volume."""
        if (body is None or not body.get('volume') or
                not isinstance(body['volume'], dict)):
            raise exc.HTTPUnprocessableEntity()

        image_id = None
        if body.get('volume'):
            image_id = body['volume'].get('imageRef')

        try:
            return _volume_v2_to_v1(
                super(VolumeController, self).create(req, body),
                image_id=image_id)
        except exc.HTTPBadRequest as e:
            # Image failures are the only ones that actually used
            # HTTPBadRequest
            error_msg = '%s' % e
            if 'Invalid image' in error_msg:
                raise
            raise exc.HTTPUnprocessableEntity()

    def update(self, req, id, body):
        """Update a volume."""
        if (body is None or not body.get('volume') or
                not isinstance(body['volume'], dict)):
            raise exc.HTTPUnprocessableEntity()

        try:
            return _volume_v2_to_v1(super(VolumeController, self).update(
                req, id, body))
        except exc.HTTPBadRequest:
            raise exc.HTTPUnprocessableEntity()


def create_resource(ext_mgr):
    return wsgi.Resource(VolumeController(ext_mgr))
