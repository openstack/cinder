# Copyright 2011 OpenStack Foundation
# Copyright 2011 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

"""
WSGI middleware for OpenStack Volume API.
"""

from cinder.api import extensions
import cinder.api.openstack
from cinder.api.v2 import snapshot_metadata
from cinder.api.v2 import types
from cinder.api.v3 import attachments
from cinder.api.v3 import backups
from cinder.api.v3 import clusters
from cinder.api.v3 import consistencygroups
from cinder.api.v3 import group_snapshots
from cinder.api.v3 import group_specs
from cinder.api.v3 import group_types
from cinder.api.v3 import groups
from cinder.api.v3 import limits
from cinder.api.v3 import messages
from cinder.api.v3 import resource_filters
from cinder.api.v3 import snapshot_manage
from cinder.api.v3 import snapshots
from cinder.api.v3 import volume_manage
from cinder.api.v3 import volume_metadata
from cinder.api.v3 import volume_transfer
from cinder.api.v3 import volumes
from cinder.api.v3 import workers
from cinder.api import versions


class APIRouter(cinder.api.openstack.APIRouter):
    """Routes requests on the API to the appropriate controller and method."""
    ExtensionManager = extensions.ExtensionManager

    def _setup_routes(self, mapper, ext_mgr):
        self.resources['versions'] = versions.create_resource()
        mapper.connect("versions", "/",
                       controller=self.resources['versions'],
                       action='index')

        mapper.redirect("", "/")

        self.resources['volumes'] = volumes.create_resource(ext_mgr)
        mapper.resource("volume", "volumes",
                        controller=self.resources['volumes'],
                        collection={'detail': 'GET', 'summary': 'GET'},
                        member={'action': 'POST'})

        self.resources['messages'] = messages.create_resource(ext_mgr)
        mapper.resource("message", "messages",
                        controller=self.resources['messages'],
                        collection={'detail': 'GET'})

        self.resources['clusters'] = clusters.create_resource()
        mapper.resource('cluster', 'clusters',
                        controller=self.resources['clusters'],
                        collection={'detail': 'GET'})

        self.resources['types'] = types.create_resource()
        mapper.resource("type", "types",
                        controller=self.resources['types'],
                        member={'action': 'POST'})

        self.resources['group_types'] = group_types.create_resource()
        mapper.resource("group_type", "group_types",
                        controller=self.resources['group_types'],
                        member={'action': 'POST'})

        self.resources['group_specs'] = group_specs.create_resource()
        mapper.resource("group_spec", "group_specs",
                        controller=self.resources['group_specs'],
                        parent_resource=dict(member_name='group_type',
                                             collection_name='group_types'))

        self.resources['groups'] = groups.create_resource()
        mapper.resource("group", "groups",
                        controller=self.resources['groups'],
                        collection={'detail': 'GET'},
                        member={'action': 'POST'})
        mapper.connect("groups",
                       "/{project_id}/groups/{id}/action",
                       controller=self.resources["groups"],
                       action="action",
                       conditions={"method": ["POST"]})
        mapper.connect("groups/action",
                       "/{project_id}/groups/action",
                       controller=self.resources["groups"],
                       action="action",
                       conditions={"method": ["POST"]})

        self.resources['group_snapshots'] = group_snapshots.create_resource()
        mapper.resource("group_snapshot", "group_snapshots",
                        controller=self.resources['group_snapshots'],
                        collection={'detail': 'GET'},
                        member={'action': 'POST'})
        mapper.connect("group_snapshots",
                       "/{project_id}/group_snapshots/{id}/action",
                       controller=self.resources["group_snapshots"],
                       action="action",
                       conditions={"method": ["POST"]})
        self.resources['snapshots'] = snapshots.create_resource(ext_mgr)
        mapper.resource("snapshot", "snapshots",
                        controller=self.resources['snapshots'],
                        collection={'detail': 'GET'},
                        member={'action': 'POST'})

        self.resources['limits'] = limits.create_resource()
        mapper.resource("limit", "limits",
                        controller=self.resources['limits'])

        self.resources['snapshot_metadata'] = \
            snapshot_metadata.create_resource()
        snapshot_metadata_controller = self.resources['snapshot_metadata']

        mapper.resource("snapshot_metadata", "metadata",
                        controller=snapshot_metadata_controller,
                        parent_resource=dict(member_name='snapshot',
                                             collection_name='snapshots'))

        mapper.connect("metadata",
                       "/{project_id}/snapshots/{snapshot_id}/metadata",
                       controller=snapshot_metadata_controller,
                       action='update_all',
                       conditions={"method": ['PUT']})

        self.resources['volume_metadata'] = \
            volume_metadata.create_resource()
        volume_metadata_controller = self.resources['volume_metadata']

        mapper.resource("volume_metadata", "metadata",
                        controller=volume_metadata_controller,
                        parent_resource=dict(member_name='volume',
                                             collection_name='volumes'))

        mapper.connect("metadata",
                       "/{project_id}/volumes/{volume_id}/metadata",
                       controller=volume_metadata_controller,
                       action='update_all',
                       conditions={"method": ['PUT']})

        self.resources['consistencygroups'] = (
            consistencygroups.create_resource())
        mapper.resource("consistencygroup", "consistencygroups",
                        controller=self.resources['consistencygroups'],
                        collection={'detail': 'GET'},
                        member={'action': 'POST'})

        self.resources['manageable_volumes'] = volume_manage.create_resource()
        mapper.resource("manageable_volume", "manageable_volumes",
                        controller=self.resources['manageable_volumes'],
                        collection={'detail': 'GET'})

        self.resources['manageable_snapshots'] = \
            snapshot_manage.create_resource()
        mapper.resource("manageable_snapshot", "manageable_snapshots",
                        controller=self.resources['manageable_snapshots'],
                        collection={'detail': 'GET'})

        self.resources['backups'] = (
            backups.create_resource())
        mapper.resource("backup", "backups",
                        controller=self.resources['backups'],
                        collection={'detail': 'GET'})

        self.resources['attachments'] = attachments.create_resource(ext_mgr)
        mapper.resource("attachment", "attachments",
                        controller=self.resources['attachments'],
                        collection={'detail': 'GET', 'summary': 'GET'},
                        member={'action': 'POST'})

        self.resources['workers'] = workers.create_resource()
        mapper.resource('worker', 'workers',
                        controller=self.resources['workers'],
                        collection={'cleanup': 'POST'})

        self.resources['resource_filters'] = resource_filters.create_resource(
            ext_mgr)
        mapper.resource('resource_filter', 'resource_filters',
                        controller=self.resources['resource_filters'])

        self.resources['volume_transfers'] = (
            volume_transfer.create_resource())
        mapper.resource("volume-transfer", "volume-transfers",
                        controller=self.resources['volume_transfers'],
                        collection={'detail': 'GET'},
                        member={'accept': 'POST'})
