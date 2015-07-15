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

from oslo_log import log as logging

from cinder.api import common


LOG = logging.getLogger(__name__)


class ViewBuilder(common.ViewBuilder):
    """Model a server API response as a python dictionary."""

    _collection_name = "volumes"

    def __init__(self):
        """Initialize view builder."""
        super(ViewBuilder, self).__init__()

    def summary_list(self, request, volumes, volume_count=None):
        """Show a list of volumes without many details."""
        return self._list_view(self.summary, request, volumes,
                               volume_count)

    def detail_list(self, request, volumes, volume_count=None):
        """Detailed view of a list of volumes."""
        return self._list_view(self.detail, request, volumes,
                               volume_count,
                               self._collection_name + '/detail')

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
        volume_ref = {
            'volume': {
                'id': volume.get('id'),
                'status': volume.get('status'),
                'size': volume.get('size'),
                'availability_zone': volume.get('availability_zone'),
                'created_at': volume.get('created_at'),
                'updated_at': volume.get('updated_at'),
                'attachments': self._get_attachments(volume),
                'name': volume.get('display_name'),
                'description': volume.get('display_description'),
                'volume_type': self._get_volume_type(volume),
                'snapshot_id': volume.get('snapshot_id'),
                'source_volid': volume.get('source_volid'),
                'metadata': self._get_volume_metadata(volume),
                'links': self._get_links(request, volume['id']),
                'user_id': volume.get('user_id'),
                'bootable': str(volume.get('bootable')).lower(),
                'encrypted': self._is_volume_encrypted(volume),
                'replication_status': volume.get('replication_status'),
                'consistencygroup_id': volume.get('consistencygroup_id'),
                'multiattach': volume.get('multiattach'),
            }
        }
        if request.environ['cinder.context'].is_admin:
            volume_ref['volume']['migration_status'] = (
                volume.get('migration_status'))
        return volume_ref

    def _is_volume_encrypted(self, volume):
        """Determine if volume is encrypted."""
        return volume.get('encryption_key_id') is not None

    def _get_attachments(self, volume):
        """Retrieve the attachments of the volume object."""
        attachments = []

        if volume['attach_status'] == 'attached':
            attaches = volume.get('volume_attachment', [])
            for attachment in attaches:
                if attachment.get('attach_status') == 'attached':
                    a = {'id': attachment.get('volume_id'),
                         'attachment_id': attachment.get('id'),
                         'volume_id': attachment.get('volume_id'),
                         'server_id': attachment.get('instance_uuid'),
                         'host_name': attachment.get('attached_host'),
                         'device': attachment.get('mountpoint'),
                         'attached_at': attachment.get('attach_time'),
                         }
                    attachments.append(a)

        return attachments

    def _get_volume_metadata(self, volume):
        """Retrieve the metadata of the volume object."""
        if volume.get('volume_metadata'):
            metadata = volume.get('volume_metadata')
            return {item['key']: item['value'] for item in metadata}
        # avoid circular ref when vol is a Volume instance
        elif volume.get('metadata') and isinstance(volume.get('metadata'),
                                                   dict):
            return volume['metadata']
        return {}

    def _get_volume_type(self, volume):
        """Retrieve the type the volume object."""
        if volume['volume_type_id'] and volume.get('volume_type'):
            return volume['volume_type']['name']
        else:
            return volume['volume_type_id']

    def _list_view(self, func, request, volumes, volume_count,
                   coll_name=_collection_name):
        """Provide a view for a list of volumes.

        :param func: Function used to format the volume data
        :param request: API request
        :param volumes: List of volumes in dictionary format
        :param volume_count: Length of the original list of volumes
        :param coll_name: Name of collection, used to generate the next link
                          for a pagination query
        :returns: Volume data in dictionary format
        """
        volumes_list = [func(request, volume)['volume'] for volume in volumes]
        volumes_links = self._get_collection_links(request,
                                                   volumes,
                                                   coll_name,
                                                   volume_count)
        volumes_dict = dict(volumes=volumes_list)

        if volumes_links:
            volumes_dict['volumes_links'] = volumes_links

        return volumes_dict
