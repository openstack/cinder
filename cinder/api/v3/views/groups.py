# Copyright (C) 2016 EMC Corporation.
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

from cinder.api import common
from cinder import utils


class ViewBuilder(common.ViewBuilder):
    """Model group API responses as a python dictionary."""

    _collection_name = "groups"

    def __init__(self):
        """Initialize view builder."""
        super(ViewBuilder, self).__init__()

    def summary_list(self, request, groups):
        """Show a list of groups without many details."""
        return self._list_view(self.summary, request, groups)

    def detail_list(self, request, groups):
        """Detailed view of a list of groups ."""
        return self._list_view(self.detail, request, groups)

    def summary(self, request, group):
        """Generic, non-detailed view of a group."""
        return {
            'group': {
                'id': group.id,
                'name': group.name
            }
        }

    def detail(self, request, group):
        """Detailed view of a single group."""
        group_ref = {
            'group': {
                'id': group.id,
                'status': group.status,
                'availability_zone': group.availability_zone,
                'created_at': group.created_at,
                'name': group.name,
                'description': group.description,
                'group_type': group.group_type_id,
                'volume_types': [v_type.id for v_type in group.volume_types],
            }
        }

        req_version = request.api_version_request
        # Add group_snapshot_id and source_group_id if min version is greater
        # than or equal to 3.14.
        if req_version.matches("3.14", None):
            group_ref['group']['group_snapshot_id'] = group.group_snapshot_id
            group_ref['group']['source_group_id'] = group.source_group_id

        # Add volumes if min version is greater than or equal to 3.25.
        if req_version.matches("3.25", None):
            if utils.get_bool_param('list_volume', request.params):
                group_ref['group']['volumes'] = [volume.id
                                                 for volume in group.volumes]

        # Add replication_status if min version is greater than or equal
        # to 3.38.
        if req_version.matches("3.38", None):
            group_ref['group']['replication_status'] = group.replication_status

        return group_ref

    def _list_view(self, func, request, groups):
        """Provide a view for a list of groups."""
        groups_list = [
            func(request, group)['group']
            for group in groups]
        grp_links = self._get_collection_links(request,
                                               groups,
                                               self._collection_name)
        groups_dict = dict(groups=groups_list)
        if grp_links:
            groups_dict['group_links'] = grp_links

        return groups_dict
