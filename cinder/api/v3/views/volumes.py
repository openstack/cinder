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

from cinder.api import common
from cinder.api import microversions as mv
from cinder.common import constants as cinder_constants
from cinder import group as group_api
from cinder.objects import fields
from cinder.volume import group_types


class ViewBuilder(common.ViewBuilder):
    """Model a volumes API V3 response as a python dictionary."""

    _collection_name = "volumes"

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
        """Generic, non-detailed view of a volume."""
        return {
            'volume': {
                'id': volume['id'],
                'name': volume['display_name'],
                'links': self._get_links(request,
                                         volume['id']),
            },
        }

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

    def _get_volume_status(self, volume):
        # NOTE(wanghao): for fixing bug 1504007, we introduce 'managing',
        # 'error_managing' and 'error_managing_deleting' status into managing
        # process, but still expose 'creating' and 'error' and 'deleting'
        # status to user for API compatibility.
        status_map = {
            'managing': 'creating',
            'error_managing': 'error',
            'error_managing_deleting': 'deleting',
        }
        vol_status = volume.get('status')
        return status_map.get(vol_status, vol_status)

    def _get_volume_metadata(self, volume):
        """Retrieve the metadata of the volume object."""
        return volume.metadata

    def _get_volume_type(self, request, volume):
        """Retrieve the type of the volume object.

        Retrieves the volume type name for microversion 3.63.
        Otherwise, it uses either the name or ID.
        """
        req_version = request.api_version_request
        if req_version.matches(mv.VOLUME_TYPE_ID_IN_VOLUME_DETAIL):
            if volume.get('volume_type'):
                return volume['volume_type']['name']
            return None

        if volume['volume_type_id'] and volume.get('volume_type'):
            return volume['volume_type']['name']
        else:
            return volume['volume_type_id']

    def _is_volume_encrypted(self, volume):
        """Determine if volume is encrypted."""
        return volume.get('encryption_key_id') is not None

    def _get_attachments(self, volume, ctxt):
        """Retrieve the attachments of the volume object."""
        attachments = []

        for attachment in volume.volume_attachment:
            if (
                attachment.get('attach_status') ==
                fields.VolumeAttachStatus.ATTACHED
            ):
                a = {'id': attachment.get('volume_id'),
                     'attachment_id': attachment.get('id'),
                     'volume_id': attachment.get('volume_id'),
                     'server_id': attachment.get('instance_uuid'),
                     'host_name': None,
                     'device': attachment.get('mountpoint'),
                     'attached_at': attachment.get('attach_time'),
                     }
                # When glance is cinder backed, we require the
                # host_name to determine when to detach a multiattach
                # volume. Glance always uses service credentials to
                # request Cinder so we are not exposing the host value
                # to end users (non-admin).
                if ctxt.is_admin or 'service' in ctxt.roles:
                    a['host_name'] = attachment.get('attached_host')
                attachments.append(a)

        return attachments

    def legacy_detail(self, request, volume):
        """Detailed view of a single volume."""
        volume_ref = {
            'volume': {
                'id': volume.get('id'),
                'status': self._get_volume_status(volume),
                'size': volume.get('size'),
                'availability_zone': volume.get('availability_zone'),
                'created_at': volume.get('created_at'),
                'updated_at': volume.get('updated_at'),
                'name': volume.get('display_name'),
                'description': volume.get('display_description'),
                'volume_type': self._get_volume_type(request, volume),
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
        ctxt = request.environ['cinder.context']

        attachments = self._get_attachments(volume, ctxt)
        volume_ref['volume']['attachments'] = attachments

        if ctxt.is_admin:
            volume_ref['volume']['migration_status'] = (
                volume.get('migration_status'))

        # NOTE(xyang): Display group_id as consistencygroup_id in detailed
        # view of the volume if group is converted from cg.
        group_id = volume.get('group_id')
        if group_id is not None:
            # Not found exception will be handled at the wsgi level
            grp = group_api.API().get(ctxt, group_id)
            cgsnap_type = group_types.get_default_cgsnapshot_type()
            if grp.group_type_id == cgsnap_type['id']:
                volume_ref['volume']['consistencygroup_id'] = group_id

        return volume_ref

    def detail(self, request, volume):
        """Detailed view of a single volume."""
        volume_ref = self.legacy_detail(request, volume)

        req_version = request.api_version_request
        # Add group_id if min version is greater than or equal to GROUP_VOLUME.
        if req_version.matches(mv.GROUP_VOLUME, None):
            volume_ref['volume']['group_id'] = volume.get('group_id')

        # Add provider_id if min version is greater than or equal to
        # VOLUME_DETAIL_PROVIDER_ID for admin.
        if (request.environ['cinder.context'].is_admin and
                req_version.matches(mv.VOLUME_DETAIL_PROVIDER_ID, None)):
            volume_ref['volume']['provider_id'] = volume.get('provider_id')

        if req_version.matches(
                mv.VOLUME_SHARED_TARGETS_AND_SERVICE_FIELDS, None):

            # For microversion 3.69 or higher it is acceptable to be null
            # but for earlier versions we convert None to True
            shared = volume.get('shared_targets', False)
            if (not req_version.matches(mv.SHARED_TARGETS_TRISTATE, None)
                    and shared is None):
                shared = True

            volume_ref['volume']['shared_targets'] = shared
            volume_ref['volume']['service_uuid'] = volume.get(
                'service_uuid', None)

        if (request.environ['cinder.context'].is_admin and req_version.matches(
                mv.VOLUME_CLUSTER_NAME, None)):
            volume_ref['volume']['cluster_name'] = volume.get(
                'cluster_name', None)

        if req_version.matches(mv.VOLUME_TYPE_ID_IN_VOLUME_DETAIL, None):
            volume_ref[
                'volume']["volume_type_id"] = volume['volume_type'].get('id')

        if req_version.matches(mv.ENCRYPTION_KEY_ID_IN_DETAILS, None):
            encryption_key_id = volume.get('encryption_key_id', None)
            if (encryption_key_id and
                    encryption_key_id != cinder_constants.FIXED_KEY_ID):
                volume_ref['volume']['encryption_key_id'] = encryption_key_id

        if req_version.matches(mv.USE_QUOTA):
            volume_ref['volume']['consumes_quota'] = volume.get('use_quota')

        return volume_ref

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
        volumes_dict = {"volumes": volumes_list}

        if volumes_links:
            volumes_dict['volumes_links'] = volumes_links

        req_version = request.api_version_request
        if req_version.matches(
                mv.SUPPORT_COUNT_INFO, None) and volume_count is not None:
            volumes_dict['count'] = volume_count

        return volumes_dict
