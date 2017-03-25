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

from oslo_log import log as logging
from oslo_utils import encodeutils
from oslo_utils import strutils
from six.moves import http_client
import webob
from webob import exc

from cinder.api import common
from cinder.api.openstack import wsgi
from cinder.api.views import snapshots as snapshot_views
from cinder import exception
from cinder.i18n import _
from cinder import utils
from cinder import volume
from cinder.volume import utils as volume_utils


LOG = logging.getLogger(__name__)


class SnapshotsController(wsgi.Controller):
    """The Snapshots API controller for the OpenStack API."""

    _view_builder_class = snapshot_views.ViewBuilder

    def __init__(self, ext_mgr=None):
        self.volume_api = volume.API()
        self.ext_mgr = ext_mgr
        super(SnapshotsController, self).__init__()

    def show(self, req, id):
        """Return data about the given snapshot."""
        context = req.environ['cinder.context']

        # Not found exception will be handled at the wsgi level
        snapshot = self.volume_api.get_snapshot(context, id)
        req.cache_db_snapshot(snapshot)

        return self._view_builder.detail(req, snapshot)

    def delete(self, req, id):
        """Delete a snapshot."""
        context = req.environ['cinder.context']

        LOG.info("Delete snapshot with id: %s", id)

        # Not found exception will be handled at the wsgi level
        snapshot = self.volume_api.get_snapshot(context, id)
        self.volume_api.delete_snapshot(context, snapshot)

        return webob.Response(status_int=http_client.ACCEPTED)

    def index(self, req):
        """Returns a summary list of snapshots."""
        return self._items(req, is_detail=False)

    def detail(self, req):
        """Returns a detailed list of snapshots."""
        return self._items(req, is_detail=True)

    def _items(self, req, is_detail=True):
        """Returns a list of snapshots, transformed through view builder."""
        context = req.environ['cinder.context']

        # Pop out non search_opts and create local variables
        search_opts = req.GET.copy()
        sort_keys, sort_dirs = common.get_sort_params(search_opts)
        marker, limit, offset = common.get_pagination_params(search_opts)

        # Filter out invalid options
        allowed_search_options = ('status', 'volume_id', 'name')
        utils.remove_invalid_filter_options(context, search_opts,
                                            allowed_search_options)

        # NOTE(thingee): v2 API allows name instead of display_name
        if 'name' in search_opts:
            search_opts['display_name'] = search_opts.pop('name')

        snapshots = self.volume_api.get_all_snapshots(context,
                                                      search_opts=search_opts,
                                                      marker=marker,
                                                      limit=limit,
                                                      sort_keys=sort_keys,
                                                      sort_dirs=sort_dirs,
                                                      offset=offset)

        req.cache_db_snapshots(snapshots.objects)

        if is_detail:
            snapshots = self._view_builder.detail_list(req, snapshots.objects)
        else:
            snapshots = self._view_builder.summary_list(req, snapshots.objects)
        return snapshots

    @wsgi.response(http_client.ACCEPTED)
    def create(self, req, body):
        """Creates a new snapshot."""
        kwargs = {}
        context = req.environ['cinder.context']

        self.assert_valid_body(body, 'snapshot')

        snapshot = body['snapshot']
        kwargs['metadata'] = snapshot.get('metadata', None)

        try:
            volume_id = snapshot['volume_id']
        except KeyError:
            msg = _("'volume_id' must be specified")
            raise exc.HTTPBadRequest(explanation=msg)

        volume = self.volume_api.get(context, volume_id)
        force = snapshot.get('force', False)
        LOG.info("Create snapshot from volume %s", volume_id)
        self.validate_name_and_description(snapshot)

        # NOTE(thingee): v2 API allows name instead of display_name
        if 'name' in snapshot:
            snapshot['display_name'] = snapshot.pop('name')

        try:
            force = strutils.bool_from_string(force, strict=True)
        except ValueError as error:
            err_msg = encodeutils.exception_to_unicode(error)
            msg = _("Invalid value for 'force': '%s'") % err_msg
            raise exception.InvalidParameterValue(err=msg)

        if force:
            new_snapshot = self.volume_api.create_snapshot_force(
                context,
                volume,
                snapshot.get('display_name'),
                snapshot.get('description'),
                **kwargs)
        else:
            new_snapshot = self.volume_api.create_snapshot(
                context,
                volume,
                snapshot.get('display_name'),
                snapshot.get('description'),
                **kwargs)
        req.cache_db_snapshot(new_snapshot)

        return self._view_builder.detail(req, new_snapshot)

    def update(self, req, id, body):
        """Update a snapshot."""
        context = req.environ['cinder.context']

        if not body:
            msg = _("Missing request body")
            raise exc.HTTPBadRequest(explanation=msg)

        if 'snapshot' not in body:
            msg = (_("Missing required element '%s' in request body") %
                   'snapshot')
            raise exc.HTTPBadRequest(explanation=msg)

        snapshot = body['snapshot']
        update_dict = {}

        valid_update_keys = (
            'name',
            'description',
            'display_name',
            'display_description',
        )
        self.validate_name_and_description(snapshot)

        # NOTE(thingee): v2 API allows name instead of display_name
        if 'name' in snapshot:
            snapshot['display_name'] = snapshot.pop('name')

        # NOTE(thingee): v2 API allows description instead of
        # display_description
        if 'description' in snapshot:
            snapshot['display_description'] = snapshot.pop('description')

        for key in valid_update_keys:
            if key in snapshot:
                update_dict[key] = snapshot[key]

        # Not found exception will be handled at the wsgi level
        snapshot = self.volume_api.get_snapshot(context, id)
        volume_utils.notify_about_snapshot_usage(context, snapshot,
                                                 'update.start')
        self.volume_api.update_snapshot(context, snapshot, update_dict)

        snapshot.update(update_dict)
        req.cache_db_snapshot(snapshot)
        volume_utils.notify_about_snapshot_usage(context, snapshot,
                                                 'update.end')

        return self._view_builder.detail(req, snapshot)


def create_resource(ext_mgr):
    return wsgi.Resource(SnapshotsController(ext_mgr))
