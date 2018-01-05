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

from oslo_log import log as logging
from oslo_utils import strutils

from cinder.api import extensions
from cinder.api.openstack import wsgi
from cinder.api.schemas import quotas
from cinder.api import validation
from cinder import db
from cinder import exception
from cinder.i18n import _
from cinder.policies import quotas as policy
from cinder import quota
from cinder import quota_utils
from cinder import utils

LOG = logging.getLogger(__name__)

QUOTAS = quota.QUOTAS
GROUP_QUOTAS = quota.GROUP_QUOTAS
NON_QUOTA_KEYS = quota.NON_QUOTA_KEYS


class QuotaSetsController(wsgi.Controller):

    def _format_quota_set(self, project_id, quota_set):
        """Convert the quota object to a result dict."""

        quota_set['id'] = str(project_id)

        return dict(quota_set=quota_set)

    def _validate_existing_resource(self, key, value, quota_values):
        # -1 limit will always be greater than the existing value
        if key == 'per_volume_gigabytes' or value == -1:
            return
        v = quota_values.get(key, {})
        used = (v.get('in_use', 0) + v.get('reserved', 0))
        if QUOTAS.using_nested_quotas():
            used += v.get('allocated', 0)
        if value < used:
            msg = (_("Quota %(key)s limit must be equal or greater than "
                     "existing resources. Current usage is %(usage)s "
                     "and the requested limit is %(limit)s.")
                   % {'key': key,
                      'usage': used,
                      'limit': value})
            raise webob.exc.HTTPBadRequest(explanation=msg)

    def _get_quotas(self, context, id, usages=False):
        values = QUOTAS.get_project_quotas(context, id, usages=usages)
        group_values = GROUP_QUOTAS.get_project_quotas(context, id,
                                                       usages=usages)
        values.update(group_values)

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
        if context_project.is_admin_project:
            # The calling project has admin privileges and should be able
            # to operate on all quotas.
            return
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

        With hierarchical projects, users are allowed to perform a quota show
        operation if they have the cloud admin role or if they belong to at
        least one of the following projects: the target project, its immediate
        parent project, or the root project of its hierarchy.

        :param context_project: The project in which the user
                                is scoped to.
        :param target_project: The project in which the user wants
                               to perform a show operation.
        """
        if context_project.is_admin_project:
            # The calling project has admin privileges and should be able
            # to view all quotas.
            return
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

    def show(self, req, id):
        """Show quota for a particular tenant

        This works for hierarchical and non-hierarchical projects. For
        hierarchical projects admin of current project, immediate
        parent of the project or the CLOUD admin are able to perform
        a show.

        :param req: request
        :param id: target project id that needs to be shown
        """
        context = req.environ['cinder.context']
        params = req.params
        target_project_id = id
        context.authorize(policy.SHOW_POLICY,
                          target={'project_id': target_project_id})

        if not hasattr(params, '__call__') and 'usage' in params:
            usage = utils.get_bool_param('usage', params)
        else:
            usage = False

        if QUOTAS.using_nested_quotas():
            # With hierarchical projects, only the admin of the current project
            # or the root project has privilege to perform quota show
            # operations.
            target_project = quota_utils.get_project_hierarchy(
                context, target_project_id)
            context_project = quota_utils.get_project_hierarchy(
                context, context.project_id, subtree_as_ids=True,
                is_admin_project=context.is_admin)

            self._authorize_show(context_project, target_project)

        quotas = self._get_quotas(context, target_project_id, usage)
        return self._format_quota_set(target_project_id, quotas)

    @validation.schema(quotas.update_quota)
    def update(self, req, id, body):
        """Update Quota for a particular tenant

        This works for hierarchical and non-hierarchical projects. For
        hierarchical projects only immediate parent admin or the
        CLOUD admin are able to perform an update.

        :param req: request
        :param id: target project id that needs to be updated
        :param body: key, value pair that will be applied to
                     the resources if the update succeeds
        """
        context = req.environ['cinder.context']
        target_project_id = id
        context.authorize(policy.UPDATE_POLICY,
                          target={'project_id': target_project_id})
        self.validate_string_length(id, 'quota_set_name',
                                    min_length=1, max_length=255)

        # Saving off this value since we need to use it multiple times
        use_nested_quotas = QUOTAS.using_nested_quotas()
        if use_nested_quotas:
            # Get the parent_id of the target project to verify whether we are
            # dealing with hierarchical namespace or non-hierarchical namespace
            target_project = quota_utils.get_project_hierarchy(
                context, target_project_id, parents_as_ids=True)
            parent_id = target_project.parent_id

            if parent_id:
                # Get the children of the project which the token is scoped to
                # in order to know if the target_project is in its hierarchy.
                context_project = quota_utils.get_project_hierarchy(
                    context, context.project_id, subtree_as_ids=True,
                    is_admin_project=context.is_admin)
                self._authorize_update_or_delete(context_project,
                                                 target_project.id,
                                                 parent_id)

        # NOTE(ankit): Pass #1 - In this loop for body['quota_set'].keys(),
        # we validate the quota limits to ensure that we can bail out if
        # any of the items in the set is bad. Meanwhile we validate value
        # to ensure that the value can't be lower than number of existing
        # resources.
        quota_values = QUOTAS.get_project_quotas(context, target_project_id,
                                                 defaults=False)
        group_quota_values = GROUP_QUOTAS.get_project_quotas(context,
                                                             target_project_id,
                                                             defaults=False)
        quota_values.update(group_quota_values)
        valid_quotas = {}
        reservations = []
        for key in body['quota_set'].keys():
            if key in NON_QUOTA_KEYS:
                continue
            self._validate_existing_resource(key, body['quota_set'][key],
                                             quota_values)

            if use_nested_quotas:
                try:
                    reservations += self._update_nested_quota_allocated(
                        context, target_project, quota_values, key,
                        body['quota_set'][key])
                except exception.OverQuota as e:
                    if reservations:
                        db.reservation_rollback(context, reservations)
                    raise webob.exc.HTTPBadRequest(explanation=e.msg)

            valid_quotas[key] = body['quota_set'][key]

        # NOTE(ankit): Pass #2 - At this point we know that all the keys and
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

        if reservations:
            db.reservation_commit(context, reservations)
        return {'quota_set': self._get_quotas(context, target_project_id)}

    def _get_quota_usage(self, quota_obj):
        return (quota_obj.get('in_use', 0) + quota_obj.get('allocated', 0) +
                quota_obj.get('reserved', 0))

    def _update_nested_quota_allocated(self, ctxt, target_project,
                                       target_project_quotas, res, new_limit):
        reservations = []
        # per_volume_gigabytes doesn't make sense to nest
        if res == "per_volume_gigabytes":
            return reservations

        quota_for_res = target_project_quotas.get(res, {})
        orig_quota_from_target_proj = quota_for_res.get('limit', 0)
        # If limit was -1, we were "taking" current child's usage from parent
        if orig_quota_from_target_proj == -1:
            orig_quota_from_target_proj = self._get_quota_usage(quota_for_res)

        new_quota_from_target_proj = new_limit
        # If we set limit to -1, we will "take" the current usage from parent
        if new_limit == -1:
            new_quota_from_target_proj = self._get_quota_usage(quota_for_res)

        res_change = new_quota_from_target_proj - orig_quota_from_target_proj
        if res_change != 0:
            deltas = {res: res_change}
            resources = QUOTAS.resources
            resources.update(GROUP_QUOTAS.resources)
            reservations += quota_utils.update_alloc_to_next_hard_limit(
                ctxt, resources, deltas, res, None, target_project.id)

        return reservations

    def defaults(self, req, id):
        context = req.environ['cinder.context']
        context.authorize(policy.SHOW_POLICY, target={'project_id': id})
        defaults = QUOTAS.get_defaults(context, project_id=id)
        group_defaults = GROUP_QUOTAS.get_defaults(context, project_id=id)
        defaults.update(group_defaults)
        return self._format_quota_set(id, defaults)

    def delete(self, req, id):
        """Delete Quota for a particular tenant.

        This works for hierarchical and non-hierarchical projects. For
        hierarchical projects only immediate parent admin or the
        CLOUD admin are able to perform a delete.

        :param req: request
        :param id: target project id that needs to be deleted
        """
        context = req.environ['cinder.context']
        context.authorize(policy.DELETE_POLICY, target={'project_id': id})

        if QUOTAS.using_nested_quotas():
            self._delete_nested_quota(context, id)
        else:
            db.quota_destroy_by_project(context, id)

    def _delete_nested_quota(self, ctxt, proj_id):
        # Get the parent_id of the target project to verify whether we are
        # dealing with hierarchical namespace or non-hierarchical
        # namespace.
        try:
            project_quotas = QUOTAS.get_project_quotas(
                ctxt, proj_id, usages=True, defaults=False)
            project_group_quotas = GROUP_QUOTAS.get_project_quotas(
                ctxt, proj_id, usages=True, defaults=False)
            project_quotas.update(project_group_quotas)
        except exception.NotAuthorized:
            raise webob.exc.HTTPForbidden()

        target_project = quota_utils.get_project_hierarchy(
            ctxt, proj_id)
        parent_id = target_project.parent_id
        if parent_id:
            # Get the children of the project which the token is scoped to
            # in order to know if the target_project is in its hierarchy.
            context_project = quota_utils.get_project_hierarchy(
                ctxt, ctxt.project_id, subtree_as_ids=True)
            self._authorize_update_or_delete(context_project,
                                             target_project.id,
                                             parent_id)

        defaults = QUOTAS.get_defaults(ctxt, proj_id)
        defaults.update(GROUP_QUOTAS.get_defaults(ctxt, proj_id))
        # If the project which is being deleted has allocated part of its
        # quota to its subprojects, then subprojects' quotas should be
        # deleted first.
        for res, value in project_quotas.items():
            if 'allocated' in project_quotas[res].keys():
                if project_quotas[res]['allocated'] > 0:
                    msg = _("About to delete child projects having "
                            "non-zero quota. This should not be performed")
                    raise webob.exc.HTTPBadRequest(explanation=msg)
            # Ensure quota usage wouldn't exceed limit on a delete
            self._validate_existing_resource(
                res, defaults[res], project_quotas)

        db.quota_destroy_by_project(ctxt, target_project.id)

        for res, limit in project_quotas.items():
            # Update child limit to 0 so the parent hierarchy gets it's
            # allocated values updated properly
            self._update_nested_quota_allocated(
                ctxt, target_project, project_quotas, res, 0)

    def validate_setup_for_nested_quota_use(self, req):
        """Validates that the setup supports using nested quotas.

        Ensures that Keystone v3 or greater is being used, and that the
        existing quotas make sense to nest in the current hierarchy (e.g. that
        no child quota would be larger than it's parent).
        """
        ctxt = req.environ['cinder.context']
        ctxt.authorize(policy.VALIDATE_NESTED_QUOTA_POLICY)
        params = req.params
        try:
            resources = QUOTAS.resources
            resources.update(GROUP_QUOTAS.resources)
            allocated = params.get('fix_allocated_quotas', 'False')
            try:
                fix_allocated = strutils.bool_from_string(allocated,
                                                          strict=True)
            except ValueError:
                msg = _("Invalid param 'fix_allocated_quotas':%s") % allocated
                raise webob.exc.HTTPBadRequest(explanation=msg)

            quota_utils.validate_setup_for_nested_quota_use(
                ctxt, resources, quota.NestedDbQuotaDriver(),
                fix_allocated_quotas=fix_allocated)
        except exception.InvalidNestedQuotaSetup as e:
            raise webob.exc.HTTPBadRequest(explanation=e.msg)


class Quotas(extensions.ExtensionDescriptor):
    """Quota management support."""

    name = "Quotas"
    alias = "os-quota-sets"
    updated = "2011-08-08T00:00:00+00:00"

    def get_resources(self):
        resources = []

        res = extensions.ResourceExtension(
            'os-quota-sets', QuotaSetsController(),
            member_actions={'defaults': 'GET'},
            collection_actions={'validate_setup_for_nested_quota_use': 'GET'})
        resources.append(res)

        return resources
