# Copyright (C) 2017 Huawei.
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

from oslo_serialization import jsonutils as json
from tempest.lib.common import rest_client
from tempest.lib.services.volume.v3 import base_client


class VolumeRevertClient(base_client.BaseClient):
    """Client class to send revert to snapshot action API request"""

    def __init__(self, auth_provider, service, region, **kwargs):
        super(VolumeRevertClient, self).__init__(
            auth_provider, service, region, **kwargs)

    def revert_to_snapshot(self, volume, snapshot_id):
        """Revert a volume to snapshot."""
        post_body = {'snapshot_id': snapshot_id}
        post_body = json.dumps({'revert': post_body})
        resp, body = self.post('volumes/%s/action' % volume['id'],
                               post_body)
        return rest_client.ResponseBody(resp, body)
