# Copyright (c) 2016 Clinton Knight.  All rights reserved.
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
"""
Storage service catalog (SSC) functions and classes for NetApp cDOT systems.
"""

from oslo_log import log as logging

from cinder import exception
from cinder.i18n import _, _LW


LOG = logging.getLogger(__name__)

# NOTE(cknight): The keys in this map are tuples that contain arguments needed
# for efficient use of the system-user-capability-get-iter cDOT API.  The
# values are SSC extra specs associated with the APIs listed in the keys.
SSC_API_MAP = {
    ('storage.aggregate', 'show', 'aggr-options-list-info'): [
        'netapp_raid_type',
    ],
    ('storage.disk', 'show', 'storage-disk-get-iter'): [
        'netapp_disk_type',
    ],
    ('snapmirror', 'show', 'snapmirror-get-iter'): [
        'netapp_mirrored',
    ],
    ('volume.efficiency', 'show', 'sis-get-iter'): [
        'netapp_dedup',
        'netapp_compression',
    ],
    ('volume', 'show', 'volume-get-iter'): [],
}


class CapabilitiesLibrary(object):

    def __init__(self, zapi_client):

        self.zapi_client = zapi_client

    def check_api_permissions(self):
        """Check which APIs that support SSC functionality are available."""

        inaccessible_apis = []
        invalid_extra_specs = []

        for api_tuple, extra_specs in SSC_API_MAP.items():
            object_name, operation_name, api = api_tuple
            if not self.zapi_client.check_cluster_api(object_name,
                                                      operation_name,
                                                      api):
                inaccessible_apis.append(api)
                invalid_extra_specs.extend(extra_specs)

        if inaccessible_apis:
            if 'volume-get-iter' in inaccessible_apis:
                msg = _('User not permitted to query Data ONTAP volumes.')
                raise exception.VolumeBackendAPIException(data=msg)
            else:
                LOG.warning(_LW('The configured user account does not have '
                                'sufficient privileges to use all needed '
                                'APIs. The following extra specs will fail '
                                'or be ignored: %s.'), invalid_extra_specs)
