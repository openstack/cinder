# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 OpenStack Foundation
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
from cinder.openstack.common import log as logging


LOG = logging.getLogger(__name__)


class ViewBuilder(common.ViewBuilder):
    """Model a server API response as a python dictionary."""

    _collection_name = "volumes"

    def __init__(self):
        """Initialize view builder."""
        super(ViewBuilder, self).__init__()

    def summary_list(self, request, volumes):
        """Show a list of volumes without many details."""
        return self._list_view(self.summary, request, volumes)

    def detail_list(self, request, volumes):
        """Detailed view of a list of volumes."""
        return self._list_view(self.detail, request, volumes)

    def summary(self, request, volume):
        """Generic, non-detailed view of an volume."""
        return {
            'volume': {
                'id': volume['id'],
                'name': volume['display_name'],
                'links': self._get_links(request,
                                         volume['id']),
            },
        }

    def detail(self, request, volume):
        """Detailed view of a single volume."""
        return {
            'volume': {
                'id': volume.get('id'),
                'status': volume.get('status'),
                'size': volume.get('size'),
                'availability_zone': volume.get('availability_zone'),
                'created_at': volume.get('created_at'),
                'attachments': self._get_attachments(volume),
                'name': volume.get('display_name'),
                'description': volume.get('display_description'),
                'volume_type': self._get_volume_type(volume),
                'snapshot_id': volume.get('snapshot_id'),
                'source_volid': volume.get('source_volid'),
                'metadata': self._get_volume_metadata(volume),
                'links': self._get_links(request, volume['id']),
                'user_id': volume.get('user_id'),
                'bootable': str(volume.get('bootable')).lower()
            }
        }

    def _get_attachments(self, volume):
        """Retrieves the attachments of the volume object"""
        attachments = []

        if volume['attach_status'] == 'attached':
            d = {}
            volume_id = volume['id']

            # note(justinsb): we use the volume id as the id of the attachments
            # object
            d['id'] = volume_id

            d['volume_id'] = volume_id
            d['server_id'] = volume['instance_uuid']
            d['host_name'] = volume['attached_host']
            if volume.get('mountpoint'):
                d['device'] = volume['mountpoint']
            attachments.append(d)

        return attachments

    def _get_volume_metadata(self, volume):
        """Retrieves the metadata of the volume object"""
        if volume.get('volume_metadata'):
            metadata = volume.get('volume_metadata')
            return dict((item['key'], item['value']) for item in metadata)
        # avoid circular ref when vol is a Volume instance
        elif volume.get('metadata') and isinstance(volume.get('metadata'),
                                                   dict):
            return volume['metadata']
        return {}

    def _get_volume_type(self, volume):
        """Retrieves the type the volume object is"""
        if volume['volume_type_id'] and volume.get('volume_type'):
            return volume['volume_type']['name']
        else:
            return volume['volume_type_id']

    def _list_view(self, func, request, volumes):
        """Provide a view for a list of volumes."""
        volumes_list = [func(request, volume)['volume'] for volume in volumes]
        volumes_links = self._get_collection_links(request,
                                                   volumes,
                                                   self._collection_name)
        volumes_dict = dict(volumes=volumes_list)

        if volumes_links:
            volumes_dict['volumes_links'] = volumes_links

        return volumes_dict
