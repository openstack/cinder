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

"""The volumes V3 api."""

from cinder.api import common
from cinder.api.openstack import wsgi
from cinder.api.v2 import volumes as volumes_v2
from cinder.api.v3.views import volumes as volume_views_v3
from cinder import utils

SUMMARY_BASE_MICRO_VERSION = '3.12'


class VolumeController(volumes_v2.VolumeController):
    """The Volumes API controller for the OpenStack API V3."""

    def _get_volumes(self, req, is_detail):
        """Returns a list of volumes, transformed through view builder."""

        context = req.environ['cinder.context']
        req_version = req.api_version_request

        params = req.params.copy()
        marker, limit, offset = common.get_pagination_params(params)
        sort_keys, sort_dirs = common.get_sort_params(params)
        filters = params

        if req_version.matches(None, "3.3"):
            filters.pop('glance_metadata', None)

        if req_version.matches(None, "3.9"):
            filters.pop('group_id', None)

        utils.remove_invalid_filter_options(context, filters,
                                            self._get_volume_filter_options())
        # NOTE(thingee): v2 API allows name instead of display_name
        if 'name' in sort_keys:
            sort_keys[sort_keys.index('name')] = 'display_name'

        if 'name' in filters:
            filters['display_name'] = filters.pop('name')

        if 'group_id' in filters:
            filters['consistencygroup_id'] = filters.pop('group_id')

        strict = req.api_version_request.matches("3.2", None)
        self.volume_api.check_volume_filters(filters, strict)

        volumes = self.volume_api.get_all(context, marker, limit,
                                          sort_keys=sort_keys,
                                          sort_dirs=sort_dirs,
                                          filters=filters,
                                          viewable_admin_meta=True,
                                          offset=offset)

        for volume in volumes:
            utils.add_visible_admin_metadata(volume)

        req.cache_db_volumes(volumes.objects)

        if is_detail:
            volumes = self._view_builder.detail_list(req, volumes)
        else:
            volumes = self._view_builder.summary_list(req, volumes)
        return volumes

    @wsgi.Controller.api_version(SUMMARY_BASE_MICRO_VERSION)
    def summary(self, req):
        """Return summary of volumes."""
        view_builder_v3 = volume_views_v3.ViewBuilder()
        context = req.environ['cinder.context']
        filters = req.params.copy()

        utils.remove_invalid_filter_options(context, filters,
                                            self._get_volume_filter_options())

        volumes = self.volume_api.get_volume_summary(context, filters=filters)
        return view_builder_v3.quick_summary(volumes[0], int(volumes[1]))


def create_resource(ext_mgr):
    return wsgi.Resource(VolumeController(ext_mgr))
