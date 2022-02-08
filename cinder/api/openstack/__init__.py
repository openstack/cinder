# Copyright (c) 2013 OpenStack Foundation
#
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
WSGI middleware for OpenStack API controllers.
"""

from oslo_config import cfg
from oslo_log import log as logging
from oslo_service import wsgi as base_wsgi
import routes

from cinder.api.openstack import wsgi
from cinder.i18n import _


openstack_api_opts = [
    cfg.StrOpt('project_id_regex',
               default=r"[0-9a-f\-]+",
               help=r'The validation regex for project_ids used in urls. '
                    r'This defaults to [0-9a-f\\-]+ if not set, '
                    r'which matches normal uuids created by keystone.'),
]

CONF = cfg.CONF
CONF.register_opts(openstack_api_opts)
LOG = logging.getLogger(__name__)


class APIMapper(routes.Mapper):
    def routematch(self, url=None, environ=None):
        if url == "":
            result = self._match("", environ)
            return result[0], result[1]
        return routes.Mapper.routematch(self, url, environ)

    def connect(self, *args, **kwargs):
        # NOTE(inhye): Default the format part of a route to only accept json
        #             so it doesn't eat all characters after a '.'
        #             in the url.
        kwargs.setdefault('requirements', {})
        if not kwargs['requirements'].get('format'):
            kwargs['requirements']['format'] = 'json'
        return routes.Mapper.connect(self, *args, **kwargs)


class ProjectMapper(APIMapper):
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
            kwargs['path_prefix'] = '%s/%s/:%s_id' % (project_id_token,
                                                      p_collection,
                                                      p_member)
        routes.Mapper.resource(self,
                               member_name,
                               collection_name,
                               **kwargs)

        # Add additional routes without project_id.
        if 'parent_resource' not in kwargs:
            del kwargs['path_prefix']
        else:
            parent_resource = kwargs['parent_resource']
            p_collection = parent_resource['collection_name']
            p_member = parent_resource['member_name']
            kwargs['path_prefix'] = '%s/:%s_id' % (p_collection,
                                                   p_member)
        routes.Mapper.resource(self,
                               member_name,
                               collection_name,
                               **kwargs)


class APIRouter(base_wsgi.Router):
    """Routes requests on the API to the appropriate controller and method."""
    ExtensionManager = None  # override in subclasses

    @classmethod
    def factory(cls, global_config, **local_config):
        """Simple paste factory, :class:`cinder.wsgi.Router` doesn't have."""
        return cls()

    def __init__(self, ext_mgr=None):
        if ext_mgr is None:
            if self.ExtensionManager:
                ext_mgr = self.ExtensionManager()
            else:
                raise Exception(_("Must specify an ExtensionManager class"))

        mapper = ProjectMapper()
        self.resources = {}
        self._setup_routes(mapper, ext_mgr)
        self._setup_ext_routes(mapper, ext_mgr)
        self._setup_extensions(ext_mgr)
        super(APIRouter, self).__init__(mapper)

    def _setup_ext_routes(self, mapper, ext_mgr):
        for resource in ext_mgr.get_resources():
            LOG.debug('Extended resource: %s',
                      resource.collection)

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
                LOG.warning('Extension %(ext_name)s: Cannot extend '
                            'resource %(collection)s: No such resource',
                            {'ext_name': extension.extension.name,
                             'collection': collection})
                continue

            LOG.debug('Extension %(ext_name)s extending resource: '
                      '%(collection)s',
                      {'ext_name': extension.extension.name,
                       'collection': collection})

            resource = self.resources[collection]
            resource.register_actions(controller)
            resource.register_extensions(controller)

    def _setup_routes(self, mapper, ext_mgr):
        raise NotImplementedError
