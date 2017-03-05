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


class ViewBuilder(common.ViewBuilder):
    """Model group_snapshot API responses as a python dictionary."""

    _collection_name = "group_snapshots"

    def __init__(self):
        """Initialize view builder."""
        super(ViewBuilder, self).__init__()

    def summary_list(self, request, group_snapshots):
        """Show a list of group_snapshots without many details."""
        return self._list_view(self.summary, request, group_snapshots)

    def detail_list(self, request, group_snapshots):
        """Detailed view of a list of group_snapshots ."""
        return self._list_view(self.detail, request, group_snapshots)

    def summary(self, request, group_snapshot):
        """Generic, non-detailed view of a group_snapshot."""
        return {
            'group_snapshot': {
                'id': group_snapshot.id,
                'name': group_snapshot.name,
                # NOTE(xyang): group_type_id is added for migrating CGs
                # to generic volume groups
                'group_type_id': group_snapshot.group_type_id,
            }
        }

    def detail(self, request, group_snapshot):
        """Detailed view of a single group_snapshot."""
        return {
            'group_snapshot': {
                'id': group_snapshot.id,
                'group_id': group_snapshot.group_id,
                'group_type_id': group_snapshot.group_type_id,
                'status': group_snapshot.status,
                'created_at': group_snapshot.created_at,
                'name': group_snapshot.name,
                'description': group_snapshot.description
            }
        }

    def _list_view(self, func, request, group_snapshots):
        """Provide a view for a list of group_snapshots."""
        group_snapshots_list = [func(request, group_snapshot)['group_snapshot']
                                for group_snapshot in group_snapshots]
        group_snapshot_links = self._get_collection_links(
            request, group_snapshots_list, self._collection_name)
        group_snapshots_dict = dict(group_snapshots=group_snapshots_list)
        if group_snapshot_links:
            group_snapshots_dict['group_snapshot_links'] = group_snapshot_links

        return group_snapshots_dict
