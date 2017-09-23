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

from cinder.api import microversions as mv
from cinder.api.v2.views import volumes as views_v2


class ViewBuilder(views_v2.ViewBuilder):
    """Model a volumes API V3 response as a python dictionary."""

    def quick_summary(self, volume_count, volume_size,
                      all_distinct_metadata=None):
        """View of volumes summary.

        It includes number of volumes, size of volumes and all distinct
        metadata of volumes.
        """
        summary = {
            'volume-summary': {
                'total_count': volume_count,
                'total_size': volume_size
            }
        }
        if all_distinct_metadata is not None:
            summary['volume-summary']['metadata'] = all_distinct_metadata
        return summary

    def detail(self, request, volume):
        """Detailed view of a single volume."""
        volume_ref = super(ViewBuilder, self).detail(request, volume)

        req_version = request.api_version_request
        # Add group_id if min version is greater than or equal to GROUP_VOLUME.
        if req_version.matches(mv.GROUP_VOLUME, None):
            volume_ref['volume']['group_id'] = volume.get('group_id')

        # Add provider_id if min version is greater than or equal to
        # VOLUME_DETAIL_PROVIDER_ID for admin.
        if (request.environ['cinder.context'].is_admin and
                req_version.matches(mv.VOLUME_DETAIL_PROVIDER_ID, None)):
            volume_ref['volume']['provider_id'] = volume.get('provider_id')

        return volume_ref
