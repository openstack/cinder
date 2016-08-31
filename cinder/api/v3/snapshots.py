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

"""The volumes snapshots V3 api."""

from cinder.api.openstack import wsgi
from cinder.api.v2 import snapshots as snapshots_v2
from cinder.api.v3.views import snapshots as snapshot_views


class SnapshotsController(snapshots_v2.SnapshotsController):
    """The Snapshots API controller for the OpenStack API."""

    _view_builder_class = snapshot_views.ViewBuilder


def create_resource(ext_mgr):
    return wsgi.Resource(SnapshotsController(ext_mgr))
