# Copyright (c) 2015 Red Hat, Inc.
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

from oslo_log import log as logging

from cinder.api import common


LOG = logging.getLogger(__name__)


class ViewBuilder(common.ViewBuilder):
    """Model snapshot API responses as a python dictionary."""

    _collection_name = "snapshots"

    def __init__(self):
        """Initialize view builder."""
        super(ViewBuilder, self).__init__()

    def summary_list(self, request, snapshots, snapshot_count=None):
        """Show a list of snapshots without many details."""
        return self._list_view(self.summary, request, snapshots,
                               snapshot_count)

    def detail_list(self, request, snapshots, snapshot_count=None):
        """Detailed view of a list of snapshots."""
        return self._list_view(self.detail, request, snapshots, snapshot_count,
                               coll_name=self._collection_name + '/detail')

    def summary(self, request, snapshot):
        """Generic, non-detailed view of a snapshot."""
        if isinstance(snapshot.metadata, dict):
            metadata = snapshot.metadata
        else:
            metadata = {}

        return {
            'snapshot': {
                'id': snapshot.id,
                'created_at': snapshot.created_at,
                'updated_at': snapshot.updated_at,
                'name': snapshot.display_name,
                'description': snapshot.display_description,
                'volume_id': snapshot.volume_id,
                'status': snapshot.status,
                'size': snapshot.volume_size,
                'metadata': metadata,
            }
        }

    def detail(self, request, snapshot):
        """Detailed view of a single snapshot."""
        # NOTE(geguileo): No additional data at the moment
        return self.summary(request, snapshot)

    def _list_view(self, func, request, snapshots, snapshot_count,
                   coll_name=_collection_name):
        """Provide a view for a list of snapshots."""
        snapshots_list = [func(request, snapshot)['snapshot']
                          for snapshot in snapshots]
        snapshots_links = self._get_collection_links(request,
                                                     snapshots,
                                                     coll_name,
                                                     snapshot_count)
        snapshots_dict = {self._collection_name: snapshots_list}

        if snapshots_links:
            snapshots_dict[self._collection_name + '_links'] = snapshots_links

        return snapshots_dict
