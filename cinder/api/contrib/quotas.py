# Copyright 2011 OpenStack Foundation
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

import webob

from keystoneclient import exceptions
from keystoneclient.v3 import client

from cinder.api import extensions
from cinder.api.openstack import wsgi
from cinder.api import xmlutil
from cinder import db
from cinder.db.sqlalchemy import api as sqlalchemy_api
from cinder import exception
from cinder.i18n import _
from cinder import quota
from cinder import utils

from oslo_config import cfg
from oslo_utils import strutils


CONF = cfg.CONF
QUOTAS = quota.QUOTAS
NON_QUOTA_KEYS = ['tenant_id', 'id']

authorize_update = extensions.extension_authorizer('volume', 'quotas:update')
authorize_show = extensions.extension_authorizer('volume', 'quotas:show')
authorize_delete = extensions.extension_authorizer('volume', 'quotas:delete')


class QuotaTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('quota_set', selector='quota_set')
        root.set('id')

        for resource in QUOTAS.resources:
            elem = xmlutil.SubTemplateElement(root, resource)
            elem.text = resource

        return xmlutil.MasterTemplate(root, 1)


class QuotaSetsController(wsgi.Controller):

    def _format_quota_set(self, project_id, quota_set):
        """Convert the quota object to a result dict."""

        quota_set['id'] = str(project_id)

        return dict(quota_set=quota_set)

    def _validate_existing_resource(self, key, value, quota_values):
        if key == 'per_volume_gigabytes':
            return
        v = quota_values.get(key, {})
        if value < (v.get('in_use', 0) + v.get('reserved', 0)):
            msg = _("Quota %s limit must be equal or greater than existing "
                    "resources.") % key
            raise webob.exc.HTTPBadRequest(explanation=msg)

    def _validate_quota_limit(self, quota, key, project_quotas=None,
                              parent_project_quotas=None):
        limit = self.validate_integer(quota[key], key, min_value=-1,
                                      max_value=db.MAX_INT)

        if parent_project_quotas:
            free_quota = (parent_project_quotas[key]['limit'] -
                          parent_project_quotas[key]['in_use'] -
                          parent_project_quotas[key]['reserved'] -
                          parent_project_quotas[key].get('allocated', 0))

            current = 0
            if project_quotas.get(key):
                current = project_quotas[key]['limit']

            if limit - current > free_quota:
                msg = _("Free quota available is %s.") % free_quota
                raise webob.exc.HTTPBadRequest(explanation=msg)
        return limit

    def _get_quotas(self, context, id, usages=False, parent_project_id=None):
        values = QUOTAS.get_project_quotas(context, id, usages=usages,
                                           parent_project_id=parent_project_id)

        if usages:
            return values
        else:
            return {k: v['limit'] for k, v in values.items()}

    def _authorize_update_or_delete(self, context_project,
                                    target_project_id,
                                    parent_id):
        """Checks if update or delete are allowed in the current hierarchy.

        With hierarchical projects, only the admin of the parent or the root
        project has privilege to perform quota update and delete operations.

        :param context_project: The project in which the user is scoped to.
        :param target_project_id: The id of the project in which the
                                  user want to perform an update or
                                  delete operation.
        :param parent_id: The parent id of the project in which the user
                          want to perform an update or delete operation.
        """
        if context_project.parent_id and parent_id != context_project.id:
            msg = _("Update and delete quota operations can only be made "
                    "by an admin of immediate parent or by the CLOUD admin.")
            raise webob.exc.HTTPForbidden(explanation=msg)

        if context_project.id != target_project_id:
            if not self._is_descendant(target_project_id,
                                       context_project.subtree):
                msg = _("Update and delete quota operations can only be made "
                        "to projects in the same hierarchy of the project in "
                        "which users are scoped to.")
                raise webob.exc.HTTPForbidden(explanation=msg)
        else:
            msg = _("Update and delete quota operations can only be made "
                    "by an admin of immediate parent or by the CLOUD admin.")
            raise webob.exc.HTTPForbidden(explanation=msg)

    def _authorize_show(self, context_project, target_project):
        """Checks if show is allowed in the current hierarchy.

        With hierarchical projects, are allowed to perform quota show operation
        users with admin role in, at least, one of the following projects: the
        current project; the immediate parent project; or the root project.

        :param context_project: The project in which the user
                                is scoped to.
        :param target_project: The project in which the user wants
                               to perform a show operation.
        """
        if target_project.parent_id:
            if target_project.id != context_project.id:
                if not self._is_descendant(target_project.id,
                                           context_project.subtree):
                    msg = _("Show operations can only be made to projects in "
                            "the same hierarchy of the project in which users "
                            "are scoped to.")
                    raise webob.exc.HTTPForbidden(explanation=msg)
                if context_project.id != target_project.parent_id:
                    if context_project.parent_id:
                        msg = _("Only users with token scoped to immediate "
                                "parents or root projects are allowed to see "
                                "its children quotas.")
                        raise webob.exc.HTTPForbidden(explanation=msg)
        elif context_project.parent_id:
            msg = _("An user with a token scoped to a subproject is not "
                    "allowed to see the quota of its parents.")
            raise webob.exc.HTTPForbidden(explanation=msg)

    def _is_descendant(self, target_project_id, subtree):
        if subtree is not None:
            for key, value in subtree.items():
                if key == target_project_id:
                    return True
                if self._is_descendant(target_project_id, value):
                    return True
        return False

    def _get_project(self, context, id, subtree_as_ids=False):
        """A Helper method to get the project hierarchy.

        Along with Hierachical Multitenancy, projects can be hierarchically
        organized. Therefore, we need to know the project hierarchy, if any, in
        order to do quota operations properly.
        """
        try:
            keystone = client.Client(auth_url=CONF.keymgr.encryption_auth_url,
                                     token=context.auth_token,
                                     project_id=context.project_id)
            project = keystone.projects.get(id, subtree_as_ids=subtree_as_ids)
        except exceptions.NotFound:
            msg = (_("Tenant ID: %s does not exist.") % id)
            raise webob.exc.HTTPNotFound(explanation=msg)
        return project

    @wsgi.serializers(xml=QuotaTemplate)
    def show(self, req, id):
        """Show quota for a particular tenant

        This works for hierarchical and non-hierarchical projects. For
        hierarchical projects admin of current project, immediate
        parent of the project or the CLOUD admin are able to perform
        a show.

        :param req: request
        :param id: target project id that needs to be updated
        """
        context = req.environ['cinder.context']
        authorize_show(context)
        params = req.params
        target_project_id = id

        if not hasattr(params, '__call__') and 'usage' in params:
            usage = strutils.bool_from_string(params['usage'])
        else:
            usage = False

        try:
            # With hierarchical projects, only the admin of the current project
            # or the root project has privilege to perform quota show
            # operations.
            target_project = self._get_project(context, target_project_id)
            context_project = self._get_project(context, context.project_id,
                                                subtree_as_ids=True)

            self._authorize_show(context_project, target_project)
            parent_project_id = target_project.parent_id
        except exceptions.Forbidden:
            # NOTE(e0ne): Keystone API v2 requires admin permissions for
            # project_get method. We ignore Forbidden exception for
            # non-admin users.
            parent_project_id = target_project_id

        try:
            sqlalchemy_api.authorize_project_context(context,
                                                     target_project_id)
        except exception.NotAuthorized:
            raise webob.exc.HTTPForbidden()

        quotas = self._get_quotas(context, target_project_id, usage,
                                  parent_project_id=parent_project_id)
        return self._format_quota_set(target_project_id, quotas)

    @wsgi.serializers(xml=QuotaTemplate)
    def update(self, req, id, body):
        """Update Quota for a particular tenant

        This works for hierarchical and non-hierarchical projects. For
        hierarchical projects only immediate parent admin or the
        CLOUD admin are able to perform an update.

        :param req: request
        :param id: target project id that needs to be updated
        :param body: key, value pair that that will be
                     applied to the resources if the update
                     succeeds
        """
        context = req.environ['cinder.context']
        authorize_update(context)
        self.validate_string_length(id, 'quota_set_name',
                                    min_length=1, max_length=255)

        self.assert_valid_body(body, 'quota_set')

        # Get the optional argument 'skip_validation' from body,
        # if skip_validation is False, then validate existing resource.
        skip_flag = body.get('skip_validation', True)
        if not utils.is_valid_boolstr(skip_flag):
            msg = _("Invalid value '%s' for skip_validation.") % skip_flag
            raise exception.InvalidParameterValue(err=msg)
        skip_flag = strutils.bool_from_string(skip_flag)

        target_project_id = id
        bad_keys = []

        # NOTE(ankit): Pass #1 - In this loop for body['quota_set'].items(),
        # we figure out if we have any bad keys.
        for key, value in body['quota_set'].items():
            if (key not in QUOTAS and key not in NON_QUOTA_KEYS):
                bad_keys.append(key)
                continue

        if len(bad_keys) > 0:
            msg = _("Bad key(s) in quota set: %s") % ",".join(bad_keys)
            raise webob.exc.HTTPBadRequest(explanation=msg)

        # Get the parent_id of the target project to verify whether we are
        # dealing with hierarchical namespace or non-hierarchical namespace.
        target_project = self._get_project(context, target_project_id)
        parent_id = target_project.parent_id

        if parent_id:
            # Get the children of the project which the token is scoped to
            # in order to know if the target_project is in its hierarchy.
            context_project = self._get_project(context,
                                                context.project_id,
                                                subtree_as_ids=True)
            self._authorize_update_or_delete(context_project,
                                             target_project.id,
                                             parent_id)
            parent_project_quotas = QUOTAS.get_project_quotas(
                context, parent_id)

        # NOTE(ankit): Pass #2 - In this loop for body['quota_set'].keys(),
        # we validate the quota limits to ensure that we can bail out if
        # any of the items in the set is bad. Meanwhile we validate value
        # to ensure that the value can't be lower than number of existing
        # resources.
        quota_values = QUOTAS.get_project_quotas(context, target_project_id,
                                                 defaults=False)
        valid_quotas = {}
        allocated_quotas = {}
        for key in body['quota_set'].keys():
            if key in NON_QUOTA_KEYS:
                continue

            if not skip_flag:
                self._validate_existing_resource(key, value, quota_values)

            if parent_id:
                value = self._validate_quota_limit(body['quota_set'], key,
                                                   quota_values,
                                                   parent_project_quotas)
                allocated_quotas[key] = (
                    parent_project_quotas[key].get('allocated', 0) + value)
            else:
                value = self._validate_quota_limit(body['quota_set'], key)
            valid_quotas[key] = value

        # NOTE(ankit): Pass #3 - At this point we know that all the keys and
        # values are valid and we can iterate and update them all in one shot
        # without having to worry about rolling back etc as we have done
        # the validation up front in the 2 loops above.
        for key, value in valid_quotas.items():
            try:
                db.quota_update(context, target_project_id, key, value)
            except exception.ProjectQuotaNotFound:
                db.quota_create(context, target_project_id, key, value)
            except exception.AdminRequired:
                raise webob.exc.HTTPForbidden()
            # If hierarchical projects, update child's quota first
            # and then parents quota. In future this needs to be an
            # atomic operation.
            if parent_id:
                if key in allocated_quotas.keys():
                    try:
                        db.quota_allocated_update(context, parent_id, key,
                                                  allocated_quotas[key])
                    except exception.ProjectQuotaNotFound:
                        parent_limit = parent_project_quotas[key]['limit']
                        db.quota_create(context, parent_id, key, parent_limit,
                                        allocated=allocated_quotas[key])

        return {'quota_set': self._get_quotas(context, target_project_id,
                                              parent_project_id=parent_id)}

    @wsgi.serializers(xml=QuotaTemplate)
    def defaults(self, req, id):
        context = req.environ['cinder.context']
        authorize_show(context)
        try:
            project = self._get_project(context, context.project_id)
            parent_id = project.parent_id
        except exceptions.Forbidden:
            # NOTE(e0ne): Keystone API v2 requires admin permissions for
            # project_get method. We ignore Forbidden exception for
            # non-admin users.
            parent_id = context.project_id

        return self._format_quota_set(id, QUOTAS.get_defaults(
            context, parent_project_id=parent_id))

    @wsgi.serializers(xml=QuotaTemplate)
    def delete(self, req, id):
        """Delete Quota for a particular tenant.

        This works for hierarchical and non-hierarchical projects. For
        hierarchical projects only immediate parent admin or the
        CLOUD admin are able to perform a delete.

        :param req: request
        :param id: target project id that needs to be updated
        """
        context = req.environ['cinder.context']
        authorize_delete(context)

        # Get the parent_id of the target project to verify whether we are
        # dealing with hierarchical namespace or non-hierarchical namespace.
        target_project = self._get_project(context, id)
        parent_id = target_project.parent_id

        try:
            project_quotas = QUOTAS.get_project_quotas(
                context, target_project.id, usages=True,
                parent_project_id=parent_id, defaults=False)
        except exception.NotAuthorized:
            raise webob.exc.HTTPForbidden()

        # If the project which is being deleted has allocated part of its quota
        # to its subprojects, then subprojects' quotas should be deleted first.
        for key, value in project_quotas.items():
            if 'allocated' in project_quotas[key].keys():
                if project_quotas[key]['allocated'] != 0:
                    msg = _("About to delete child projects having "
                            "non-zero quota. This should not be performed")
                    raise webob.exc.HTTPBadRequest(explanation=msg)

        if parent_id:
            # Get the children of the project which the token is scoped to in
            # order to know if the target_project is in its hierarchy.
            context_project = self._get_project(context,
                                                context.project_id,
                                                subtree_as_ids=True)
            self._authorize_update_or_delete(context_project,
                                             target_project.id,
                                             parent_id)
            parent_project_quotas = QUOTAS.get_project_quotas(
                context, parent_id, parent_project_id=parent_id)

            # Delete child quota first and later update parent's quota.
            try:
                db.quota_destroy_by_project(context, target_project.id)
            except exception.AdminRequired:
                raise webob.exc.HTTPForbidden()

            # Update the allocated of the parent
            for key, value in project_quotas.items():
                project_hard_limit = project_quotas[key]['limit']
                parent_allocated = parent_project_quotas[key]['allocated']
                parent_allocated -= project_hard_limit
                db.quota_allocated_update(context, parent_id, key,
                                          parent_allocated)
        else:
            try:
                db.quota_destroy_by_project(context, target_project.id)
            except exception.AdminRequired:
                raise webob.exc.HTTPForbidden()


class Quotas(extensions.ExtensionDescriptor):
    """Quota management support."""

    name = "Quotas"
    alias = "os-quota-sets"
    namespace = "http://docs.openstack.org/volume/ext/quotas-sets/api/v1.1"
    updated = "2011-08-08T00:00:00+00:00"

    def get_resources(self):
        resources = []

        res = extensions.ResourceExtension('os-quota-sets',
                                           QuotaSetsController(),
                                           member_actions={'defaults': 'GET'})
        resources.append(res)

        return resources
