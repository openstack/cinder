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

from oslo_config import cfg
from oslo_log import log as logging
from oslo_service import wsgi as base_wsgi
import routes

from cinder.api import extensions
from cinder.api.openstack import wsgi
from cinder.api.v3 import attachments
from cinder.api.v3 import backups
from cinder.api.v3 import clusters
from cinder.api.v3 import consistencygroups
from cinder.api.v3 import default_types
from cinder.api.v3 import group_snapshots
from cinder.api.v3 import group_specs
from cinder.api.v3 import group_types
from cinder.api.v3 import groups
from cinder.api.v3 import limits
from cinder.api.v3 import messages
from cinder.api.v3 import resource_filters
from cinder.api.v3 import snapshot_manage
from cinder.api.v3 import snapshot_metadata
from cinder.api.v3 import snapshots
from cinder.api.v3 import types
from cinder.api.v3 import volume_manage
from cinder.api.v3 import volume_metadata
from cinder.api.v3 import volume_transfer
from cinder.api.v3 import volumes
from cinder.api.v3 import workers
from cinder.api import versions

CONF = cfg.CONF
LOG = logging.getLogger(__name__)


class ProjectMapper(wsgi.APIMapper):
    def resource(self, member_name, collection_name, **kwargs):
        """Base resource path handler

        This method is compatible with resource paths that include a
        project_id and those that don't. Including project_id in the URLs
        was a legacy API requirement; and making API requests against
        such endpoints won't work for users that don't belong to a
        particular project.
        """
        # NOTE: project_id parameter is only valid if its hex or hex + dashes
        # (note, integers are a subset of this). This is required to handle
        # our overlapping routes issues.
        project_id_regex = CONF.project_id_regex
        project_id_token = '{project_id:%s}' % project_id_regex

        if 'parent_resource' not in kwargs:
            kwargs['path_prefix'] = '%s/' % project_id_token
        else:
            parent_resource = kwargs['parent_resource']
            p_collection = parent_resource['collection_name']
            p_member = parent_resource['member_name']
            kwargs['path_prefix'] = '%s/%s/:%s_id' % (
                project_id_token, p_collection, p_member
            )

        routes.Mapper.resource(
            self, member_name, collection_name, **kwargs
        )

        # Add additional routes without project_id.
        if 'parent_resource' not in kwargs:
            del kwargs['path_prefix']
        else:
            parent_resource = kwargs['parent_resource']
            p_collection = parent_resource['collection_name']
            p_member = parent_resource['member_name']
            kwargs['path_prefix'] = '%s/:%s_id' % (p_collection, p_member)

        routes.Mapper.resource(
            self, member_name, collection_name, **kwargs
        )


class APIRouter(base_wsgi.Router):
    """Routes requests on the API to the appropriate controller and method."""
    def __init__(self, ext_mgr=None):
        ext_mgr = ext_mgr or extensions.ExtensionManager()
        mapper = ProjectMapper()
        self.resources = {}
        self._setup_routes(mapper, ext_mgr)
        self._setup_ext_routes(mapper, ext_mgr)
        self._setup_extensions(ext_mgr)
        super().__init__(mapper)

    @classmethod
    def factory(cls, global_config, **local_config):
        """Simple paste factory.

        :class:`oslo_service.wsgi.Router` doesn't have this.
        """
        return cls()

    def _setup_ext_routes(self, mapper, ext_mgr):
        for resource in ext_mgr.get_resources():
            LOG.debug('Extended resource: %s', resource.collection)

            wsgi_resource = wsgi.Resource(resource.controller)
            self.resources[resource.collection] = wsgi_resource
            kargs = dict(
                controller=wsgi_resource,
                collection=resource.collection_actions,
                member=resource.member_actions)

            if resource.parent:
                kargs['parent_resource'] = resource.parent

            mapper.resource(resource.collection, resource.collection, **kargs)

            if resource.custom_routes_fn:
                resource.custom_routes_fn(mapper, wsgi_resource)

    def _setup_extensions(self, ext_mgr):
        for extension in ext_mgr.get_controller_extensions():
            collection = extension.collection
            controller = extension.controller

            if collection not in self.resources:
                LOG.warning(
                    'Extension %(ext_name)s: Cannot extend '
                    'resource %(collection)s: No such resource',
                    {
                        'ext_name': extension.extension.name,
                        'collection': collection,
                    },
                )
                continue

            LOG.debug(
                'Extension %(ext_name)s extending resource: %(collection)s',
                {
                    'ext_name': extension.extension.name,
                    'collection': collection,
                },
            )

            resource = self.resources[collection]
            resource.register_extensions(controller)

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
                        controller=self.resources['messages'])

        self.resources['clusters'] = clusters.create_resource()
        mapper.create_route(
            '/clusters', 'GET', self.resources['clusters'], 'index')
        mapper.create_route(
            '/clusters/detail', 'GET', self.resources['clusters'], 'detail')
        mapper.create_route(
            '/clusters/{id}', 'GET', self.resources['clusters'], 'show')
        mapper.create_route(
            '/clusters/enable', 'PUT', self.resources['clusters'], 'enable')
        mapper.create_route(
            '/clusters/disable', 'PUT', self.resources['clusters'], 'disable')

        self.resources['types'] = types.create_resource()
        mapper.resource("type", "types",
                        controller=self.resources['types'],
                        member={'action': 'POST'})

        self.resources['group_types'] = group_types.create_resource()
        mapper.resource("group_type", "group_types",
                        controller=self.resources['group_types'])

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
        for path_prefix in ['/{project_id}', '']:
            # project_id is optional
            mapper.connect("groups",
                           "%s/groups/{id}/action" % path_prefix,
                           controller=self.resources["groups"],
                           action="action",
                           conditions={"method": ["POST"]})
            mapper.connect("groups/action",
                           "%s/groups/action" % path_prefix,
                           controller=self.resources["groups"],
                           action="action",
                           conditions={"method": ["POST"]})

        self.resources['group_snapshots'] = group_snapshots.create_resource()
        mapper.resource("group_snapshot", "group_snapshots",
                        controller=self.resources['group_snapshots'],
                        collection={'detail': 'GET'},
                        member={'action': 'POST'})
        for path_prefix in ['/{project_id}', '']:
            # project_id is optional
            mapper.connect("group_snapshots",
                           "%s/group_snapshots/{id}/action" % path_prefix,
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

        for path_prefix in ['/{project_id}', '']:
            # project_id is optional
            mapper.connect("metadata",
                           "%s/snapshots/{snapshot_id}/metadata" % path_prefix,
                           controller=snapshot_metadata_controller,
                           action='update_all',
                           conditions={"method": ['PUT']})

        self.resources['volume_metadata'] = volume_metadata.create_resource()
        volume_metadata_controller = self.resources['volume_metadata']

        mapper.resource("volume_metadata", "metadata",
                        controller=volume_metadata_controller,
                        parent_resource=dict(member_name='volume',
                                             collection_name='volumes'))

        for path_prefix in ['/{project_id}', '']:
            # project_id is optional
            mapper.connect("metadata",
                           "%s/volumes/{volume_id}/metadata" % path_prefix,
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

        self.resources['default_types'] = default_types.create_resource()
        for path_prefix in ['/{project_id}', '']:
            # project_id is optional
            mapper.connect(
                "default-types", "%s/default-types/{id}" % path_prefix,
                controller=self.resources['default_types'],
                action='create_update',
                conditions={"method": ['PUT']})

            mapper.connect(
                "default-types", "%s/default-types" % path_prefix,
                controller=self.resources['default_types'],
                action='index',
                conditions={"method": ['GET']})

            mapper.connect(
                "default-types", "%s/default-types/{id}" % path_prefix,
                controller=self.resources['default_types'],
                action='detail',
                conditions={"method": ['GET']})

            mapper.connect(
                "default-types", "%s/default-types/{id}" % path_prefix,
                controller=self.resources['default_types'],
                action='delete',
                conditions={"method": ['DELETE']})
