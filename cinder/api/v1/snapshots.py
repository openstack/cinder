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

"""The volumes snapshots api."""


from six.moves import http_client
from webob import exc

from cinder.api.openstack import wsgi
from cinder.api.v2 import snapshots as snapshots_v2


def _snapshot_v2_to_v1(snapv2_result):
    """Transform a v2 snapshot dict to v1."""
    snapshots = snapv2_result.get('snapshots')
    if snapshots is None:
        snapshots = [snapv2_result['snapshot']]

    for snapv1 in snapshots:
        # The updated_at property was added in v2
        snapv1.pop('updated_at', None)

        # Name and description were renamed
        snapv1['display_name'] = snapv1.pop('name', '')
        snapv1['display_description'] = snapv1.pop('description', '')

    return snapv2_result


def _update_search_opts(req):
    """Update the requested search options.

    This is a little silly, as ``display_name`` needs to be switched
    to just ``name``, which internally to v2 gets switched to be
    ``display_name``. Oh well.
    """
    if 'display_name' in req.GET:
        req.GET['name'] = req.GET.pop('display_name')
    return req


class SnapshotsController(snapshots_v2.SnapshotsController):
    """The Snapshots API controller for the OpenStack API."""

    def show(self, req, id):
        """Return data about the given snapshot."""
        result = super(SnapshotsController, self).show(req, id)
        return _snapshot_v2_to_v1(result)

    def index(self, req):
        """Returns a summary list of snapshots."""
        return _snapshot_v2_to_v1(
            super(SnapshotsController, self).index(
                _update_search_opts(req)))

    def detail(self, req):
        """Returns a detailed list of snapshots."""
        return _snapshot_v2_to_v1(
            super(SnapshotsController, self).detail(
                _update_search_opts(req)))

    @wsgi.response(http_client.OK)
    def create(self, req, body):
        """Creates a new snapshot."""
        if (body is None or not body.get('snapshot') or
                not isinstance(body['snapshot'], dict)):
            raise exc.HTTPUnprocessableEntity()

        if 'display_name' in body['snapshot']:
            body['snapshot']['name'] = body['snapshot'].pop('display_name')

        if 'display_description' in body['snapshot']:
            body['snapshot']['description'] = body['snapshot'].pop(
                'display_description')

        if 'metadata' not in body['snapshot']:
            body['snapshot']['metadata'] = {}

        return _snapshot_v2_to_v1(
            super(SnapshotsController, self).create(req, body))

    def update(self, req, id, body):
        """Update a snapshot."""
        try:
            return _snapshot_v2_to_v1(
                super(SnapshotsController, self).update(req, id, body))
        except exc.HTTPBadRequest:
            raise exc.HTTPUnprocessableEntity()


def create_resource(ext_mgr):
    return wsgi.Resource(SnapshotsController(ext_mgr))
