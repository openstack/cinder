# Copyright (C) 2012 Hewlett-Packard Development Company, L.P.
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
from cinder.api import microversions as mv


class ViewBuilder(common.ViewBuilder):
    """Model transfer API responses as a python dictionary."""

    _collection_name = "os-volume-transfer"

    def __init__(self):
        """Initialize view builder."""
        super(ViewBuilder, self).__init__()

    def summary_list(self, request, transfers, origin_transfer_count):
        """Show a list of transfers without many details."""
        return self._list_view(self.summary, request, transfers,
                               origin_transfer_count)

    def detail_list(self, request, transfers, origin_transfer_count):
        """Detailed view of a list of transfers ."""
        return self._list_view(self.detail, request, transfers,
                               origin_transfer_count)

    def summary(self, request, transfer):
        """Generic, non-detailed view of a transfer."""
        return {
            'transfer': {
                'id': transfer['id'],
                'volume_id': transfer.get('volume_id'),
                'name': transfer['display_name'],
                'links': self._get_links(request,
                                         transfer['id']),
            },
        }

    def detail(self, request, transfer):
        """Detailed view of a single transfer."""
        detail_body = {
            'transfer': {
                'id': transfer.get('id'),
                'created_at': transfer.get('created_at'),
                'name': transfer.get('display_name'),
                'volume_id': transfer.get('volume_id'),
                'links': self._get_links(request, transfer['id'])
            }
        }
        req_version = request.api_version_request
        if req_version.matches(mv.TRANSFER_WITH_SNAPSHOTS):
            detail_body['transfer'].update({'no_snapshots':
                                            transfer.get('no_snapshots')})
        if req_version.matches(mv.TRANSFER_WITH_HISTORY):
            transfer_history = {
                'destination_project_id': transfer['destination_project_id'],
                'source_project_id': transfer['source_project_id'],
                'accepted': transfer['accepted']
            }
            detail_body['transfer'].update(transfer_history)
        return detail_body

    def create(self, request, transfer):
        """Detailed view of a single transfer when created."""
        create_body = {
            'transfer': {
                'id': transfer.get('id'),
                'created_at': transfer.get('created_at'),
                'name': transfer.get('display_name'),
                'volume_id': transfer.get('volume_id'),
                'auth_key': transfer.get('auth_key'),
                'links': self._get_links(request, transfer['id'])
            }
        }
        req_version = request.api_version_request
        if req_version.matches(mv.TRANSFER_WITH_SNAPSHOTS):
            create_body['transfer'].update({'no_snapshots':
                                            transfer.get('no_snapshots')})
        if req_version.matches(mv.TRANSFER_WITH_HISTORY):
            transfer_history = {
                'destination_project_id': transfer['destination_project_id'],
                'source_project_id': transfer['source_project_id'],
                'accepted': transfer['accepted']
            }
            create_body['transfer'].update(transfer_history)
        return create_body

    def _list_view(self, func, request, transfers, origin_transfer_count):
        """Provide a view for a list of transfers."""
        transfers_list = [func(request, transfer)['transfer'] for transfer in
                          transfers]
        transfers_links = self._get_collection_links(request,
                                                     transfers,
                                                     self._collection_name,
                                                     origin_transfer_count)
        transfers_dict = dict(transfers=transfers_list)

        if transfers_links:
            transfers_dict['transfers_links'] = transfers_links

        return transfers_dict
