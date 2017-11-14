#   Copyright (c) 2016 Stratoscale, Ltd.
#
#   Licensed under the Apache License, Version 2.0 (the "License"); you may
#   not use this file except in compliance with the License. You may obtain
#   a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#   WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#   License for the specific language governing permissions and limitations
#   under the License.

from six.moves import http_client

from cinder.api.contrib import snapshot_manage as snapshot_manage_v2
from cinder.api import microversions as mv
from cinder.api.openstack import wsgi
from cinder.api.v3 import resource_common_manage as common


class SnapshotManageController(common.ManageResource,
                               snapshot_manage_v2.SnapshotManageController):
    def __init__(self, *args, **kwargs):
        super(SnapshotManageController, self).__init__(*args, **kwargs)
        self._set_resource_type('snapshot')

    @wsgi.response(http_client.ACCEPTED)
    def create(self, req, body):
        self._ensure_min_version(req, mv.MANAGE_EXISTING_LIST)
        return super(SnapshotManageController, self).create(req, body=body)


def create_resource():
    return wsgi.Resource(SnapshotManageController())
