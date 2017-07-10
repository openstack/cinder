# Copyright 2016 EMC Corporation
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

"""The volumes snapshots V3 API."""

import ast

from oslo_log import log as logging

from cinder.api import common
from cinder.api.openstack import wsgi
from cinder.api.v2 import snapshots as snapshots_v2
from cinder.api.v3.views import snapshots as snapshot_views
from cinder import utils

LOG = logging.getLogger(__name__)


class SnapshotsController(snapshots_v2.SnapshotsController):
    """The Snapshots API controller for the OpenStack API."""

    _view_builder_class = snapshot_views.ViewBuilder

    def _get_snapshot_filter_options(self):
        """returns tuple of valid filter options"""

        return 'status', 'volume_id', 'name', 'metadata'

    def _format_snapshot_filter_options(self, search_opts):
        """Convert valid filter options to correct expected format"""

        # Get the dict object out of queried metadata
        # convert metadata query value from string to dict
        if 'metadata' in search_opts.keys():
            try:
                search_opts['metadata'] = ast.literal_eval(
                    search_opts['metadata'])
            except (ValueError, SyntaxError):
                LOG.debug('Could not evaluate value %s, assuming string',
                          search_opts['metadata'])

    @common.process_general_filtering('snapshot')
    def _process_snapshot_filtering(self, context=None, filters=None,
                                    req_version=None):
        """Formats allowed filters"""

        # if the max version is less than or same as 3.21
        # metadata based filtering is not supported
        if req_version.matches(None, "3.21"):
            filters.pop('metadata', None)

        # Filter out invalid options
        allowed_search_options = self._get_snapshot_filter_options()

        utils.remove_invalid_filter_options(context, filters,
                                            allowed_search_options)

    def _items(self, req, is_detail=True):
        """Returns a list of snapshots, transformed through view builder."""
        context = req.environ['cinder.context']
        req_version = req.api_version_request
        # Pop out non search_opts and create local variables
        search_opts = req.GET.copy()
        sort_keys, sort_dirs = common.get_sort_params(search_opts)
        marker, limit, offset = common.get_pagination_params(search_opts)

        # process filters
        self._process_snapshot_filtering(context=context,
                                         filters=search_opts,
                                         req_version=req_version)
        # process snapshot filters to appropriate formats if required
        self._format_snapshot_filter_options(search_opts)

        req_version = req.api_version_request
        if req_version.matches("3.30", None) and 'name' in sort_keys:
            sort_keys[sort_keys.index('name')] = 'display_name'

        # NOTE(thingee): v3 API allows name instead of display_name
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


def create_resource(ext_mgr):
    return wsgi.Resource(SnapshotsController(ext_mgr))
