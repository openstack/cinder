# Copyright 2020 Red Hat, Inc.
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

"""The resource filters api."""

from keystoneauth1 import exceptions as ks_exc
from six.moves import http_client
from webob import exc

from cinder.api import microversions as mv
from cinder.api.openstack import wsgi
from cinder.api.schemas import default_types as default_types
from cinder.api.v3.views import default_types as default_types_view
from cinder.api import validation
from cinder import db
from cinder import exception
from cinder.i18n import _
from cinder import objects
from cinder.policies import default_types as policy
from cinder import quota_utils


class DefaultTypesController(wsgi.Controller):
    """The Default types API controller for the OpenStack API."""

    _view_builder_class = default_types_view.ViewBuilder

    def _validate_project_and_authorize(self, context, project_id,
                                        policy_check):
        try:
            target_project = quota_utils.get_project_hierarchy(context,
                                                               project_id)
            target_project = {'project_id': target_project.id,
                              'domain_id': target_project.domain_id}
            context.authorize(policy_check, target=target_project)
        except ks_exc.http.NotFound:
            explanation = _("Project with id %s not found." % project_id)
            raise exc.HTTPNotFound(explanation=explanation)
        except exception.NotAuthorized:
            explanation = _("You are not authorized to perform this "
                            "operation.")
            raise exc.HTTPForbidden(explanation=explanation)

    @wsgi.response(http_client.OK)
    @wsgi.Controller.api_version(mv.DEFAULT_TYPE_OVERRIDES)
    @validation.schema(default_types.create_or_update)
    def create_update(self, req, id, body):
        """Set a default volume type for the specified project."""
        context = req.environ['cinder.context']

        project_id = id
        volume_type_id = body['default_type']['volume_type']

        self._validate_project_and_authorize(context, project_id,
                                             policy.CREATE_UPDATE_POLICY)
        try:
            volume_type_id = objects.VolumeType.get_by_name_or_id(
                context, volume_type_id).id

        except exception.VolumeTypeNotFound as e:
            raise exc.HTTPBadRequest(explanation=e.msg)

        default_type = db.project_default_volume_type_set(
            context, volume_type_id, project_id)

        return self._view_builder.create(default_type)

    @wsgi.response(http_client.OK)
    @wsgi.Controller.api_version(mv.DEFAULT_TYPE_OVERRIDES)
    def detail(self, req, id):
        """Return detail of a default type."""

        context = req.environ['cinder.context']

        project_id = id
        self._validate_project_and_authorize(context, project_id,
                                             policy.GET_POLICY)
        default_type = db.project_default_volume_type_get(context, project_id)
        if not default_type:
            raise exception.VolumeTypeProjectDefaultNotFound(
                project_id=project_id)
        return self._view_builder.detail(default_type)

    @wsgi.response(http_client.OK)
    @wsgi.Controller.api_version(mv.DEFAULT_TYPE_OVERRIDES)
    def index(self, req):
        """Return a list of default types."""

        context = req.environ['cinder.context']
        try:
            context.authorize(policy.GET_ALL_POLICY)
        except exception.NotAuthorized:
            explanation = _("You are not authorized to perform this "
                            "operation.")
            raise exc.HTTPForbidden(explanation=explanation)

        default_types = db.project_default_volume_type_get(context)
        return self._view_builder.index(default_types)

    @wsgi.response(http_client.NO_CONTENT)
    @wsgi.Controller.api_version(mv.DEFAULT_TYPE_OVERRIDES)
    def delete(self, req, id):
        """Unset a default volume type for a project."""

        context = req.environ['cinder.context']

        project_id = id
        self._validate_project_and_authorize(context, project_id,
                                             policy.DELETE_POLICY)
        db.project_default_volume_type_unset(context, id)


def create_resource():
    """Create the wsgi resource for this controller."""
    return wsgi.Resource(DefaultTypesController())
