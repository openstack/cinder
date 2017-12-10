# Copyright (C) 2012 - 2014 EMC Corporation.
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

"""The consistencygroups api."""

from oslo_log import log as logging
from oslo_log import versionutils
from oslo_utils import strutils
from six.moves import http_client
import webob
from webob import exc

from cinder.api import common
from cinder.api import extensions
from cinder.api.openstack import wsgi
from cinder.api.views import consistencygroups as consistencygroup_views
from cinder import exception
from cinder import group as group_api
from cinder.i18n import _
from cinder.policies import group_actions as gp_action_policy
from cinder.policies import groups as group_policy
from cinder.volume import group_types

LOG = logging.getLogger(__name__)
DEPRECATE_CG_API_MSG = ("Consistency Group APIs are deprecated. "
                        "Use Generic Volume Group APIs instead.")


class ConsistencyGroupsController(wsgi.Controller):
    """The ConsistencyGroups API controller for the OpenStack API."""

    _view_builder_class = consistencygroup_views.ViewBuilder

    def __init__(self):
        self.group_api = group_api.API()
        super(ConsistencyGroupsController, self).__init__()

    def show(self, req, id):
        """Return data about the given consistency group."""
        versionutils.report_deprecated_feature(LOG, DEPRECATE_CG_API_MSG)
        LOG.debug('show called for member %s', id)
        context = req.environ['cinder.context']

        # Not found exception will be handled at the wsgi level
        consistencygroup = self._get(context, id)

        return self._view_builder.detail(req, consistencygroup)

    def delete(self, req, id, body):
        """Delete a consistency group."""
        versionutils.report_deprecated_feature(LOG, DEPRECATE_CG_API_MSG)
        LOG.debug('delete called for member %s', id)
        context = req.environ['cinder.context']
        force = False
        if body:
            self.assert_valid_body(body, 'consistencygroup')

            cg_body = body['consistencygroup']
            try:
                force = strutils.bool_from_string(cg_body.get('force', False),
                                                  strict=True)
            except ValueError:
                msg = _("Invalid value '%s' for force.") % force
                raise exc.HTTPBadRequest(explanation=msg)

        LOG.info('Delete consistency group with id: %s', id)

        try:
            group = self._get(context, id)
            context.authorize(gp_action_policy.DELETE_POLICY, target_obj=group)
            self.group_api.delete(context, group, force)
        # Not found exception will be handled at the wsgi level
        except exception.InvalidConsistencyGroup as error:
            raise exc.HTTPBadRequest(explanation=error.msg)

        return webob.Response(status_int=http_client.ACCEPTED)

    def index(self, req):
        """Returns a summary list of consistency groups."""
        versionutils.report_deprecated_feature(LOG, DEPRECATE_CG_API_MSG)
        return self._get_consistencygroups(req, is_detail=False)

    def detail(self, req):
        """Returns a detailed list of consistency groups."""
        versionutils.report_deprecated_feature(LOG, DEPRECATE_CG_API_MSG)
        return self._get_consistencygroups(req, is_detail=True)

    def _get(self, context, id):
        # Not found exception will be handled at the wsgi level
        consistencygroup = self.group_api.get(context, group_id=id)

        return consistencygroup

    def _get_cgsnapshot(self, context, id):
        # Not found exception will be handled at the wsgi level
        cgsnapshot = self.group_api.get_group_snapshot(
            context,
            group_snapshot_id=id)

        return cgsnapshot

    def _get_consistencygroups(self, req, is_detail):
        """Returns a list of consistency groups through view builder."""
        context = req.environ['cinder.context']
        context.authorize(group_policy.GET_ALL_POLICY)
        filters = req.params.copy()

        # make another copy of filters, since it is being modified in
        # consistencygroup_api while getting consistencygroups
        marker, limit, offset = common.get_pagination_params(filters)
        sort_keys, sort_dirs = common.get_sort_params(filters)

        groups = self.group_api.get_all(
            context, filters=filters, marker=marker, limit=limit,
            offset=offset, sort_keys=sort_keys, sort_dirs=sort_dirs)

        if is_detail:
            groups = self._view_builder.detail_list(req, groups)
        else:
            groups = self._view_builder.summary_list(req, groups)

        return groups

    @wsgi.response(http_client.ACCEPTED)
    def create(self, req, body):
        """Create a new consistency group."""
        versionutils.report_deprecated_feature(LOG, DEPRECATE_CG_API_MSG)
        LOG.debug('Creating new consistency group %s', body)
        self.assert_valid_body(body, 'consistencygroup')

        context = req.environ['cinder.context']
        context.authorize(group_policy.CREATE_POLICY)
        consistencygroup = body['consistencygroup']
        self.validate_name_and_description(consistencygroup)
        name = consistencygroup.get('name', None)
        description = consistencygroup.get('description', None)
        volume_types = consistencygroup.get('volume_types', None)
        if not volume_types:
            msg = _("volume_types must be provided to create "
                    "consistency group %(name)s.") % {'name': name}
            raise exc.HTTPBadRequest(explanation=msg)
        volume_types = volume_types.rstrip(',').split(',')
        availability_zone = consistencygroup.get('availability_zone', None)
        group_type = group_types.get_default_cgsnapshot_type()
        if not group_type:
            msg = (_('Group type %s not found. Rerun migration script to '
                     'create the default cgsnapshot type.') %
                   group_types.DEFAULT_CGSNAPSHOT_TYPE)
            raise exc.HTTPBadRequest(explanation=msg)

        LOG.info("Creating consistency group %(name)s.",
                 {'name': name})

        try:
            new_consistencygroup = self.group_api.create(
                context, name, description, group_type['id'], volume_types,
                availability_zone=availability_zone)
        except (exception.InvalidConsistencyGroup,
                exception.InvalidGroup,
                exception.InvalidVolumeType,
                exception.ObjectActionError) as error:
            raise exc.HTTPBadRequest(explanation=error.msg)
        except exception.NotFound:
            # Not found exception will be handled at the wsgi level
            raise

        retval = self._view_builder.summary(req, new_consistencygroup)
        return retval

    @wsgi.response(http_client.ACCEPTED)
    def create_from_src(self, req, body):
        """Create a new consistency group from a source.

        The source can be a CG snapshot or a CG. Note that
        this does not require volume_types as the "create"
        API above.
        """
        versionutils.report_deprecated_feature(LOG, DEPRECATE_CG_API_MSG)
        LOG.debug('Creating new consistency group %s.', body)
        self.assert_valid_body(body, 'consistencygroup-from-src')

        context = req.environ['cinder.context']
        context.authorize(group_policy.CREATE_POLICY)
        consistencygroup = body['consistencygroup-from-src']
        self.validate_name_and_description(consistencygroup)
        name = consistencygroup.get('name', None)
        description = consistencygroup.get('description', None)
        cgsnapshot_id = consistencygroup.get('cgsnapshot_id', None)
        source_cgid = consistencygroup.get('source_cgid', None)
        if not cgsnapshot_id and not source_cgid:
            msg = _("Either 'cgsnapshot_id' or 'source_cgid' must be "
                    "provided to create consistency group %(name)s "
                    "from source.") % {'name': name}
            raise exc.HTTPBadRequest(explanation=msg)

        if cgsnapshot_id and source_cgid:
            msg = _("Cannot provide both 'cgsnapshot_id' and 'source_cgid' "
                    "to create consistency group %(name)s from "
                    "source.") % {'name': name}
            raise exc.HTTPBadRequest(explanation=msg)

        if cgsnapshot_id:
            LOG.info("Creating consistency group %(name)s from "
                     "cgsnapshot %(snap)s.",
                     {'name': name, 'snap': cgsnapshot_id})
        elif source_cgid:
            LOG.info("Creating consistency group %(name)s from "
                     "source consistency group %(source_cgid)s.",
                     {'name': name, 'source_cgid': source_cgid})

        try:
            if source_cgid:
                self._get(context, source_cgid)
            if cgsnapshot_id:
                self._get_cgsnapshot(context, cgsnapshot_id)
            new_group = self.group_api.create_from_src(
                context, name, description, cgsnapshot_id, source_cgid)
        except exception.NotFound:
            # Not found exception will be handled at the wsgi level
            raise
        except exception.CinderException as error:
            raise exc.HTTPBadRequest(explanation=error.msg)

        retval = self._view_builder.summary(req, new_group)
        return retval

    def _check_update_parameters(self, name, description, add_volumes,
                                 remove_volumes):
        if not (name or description or add_volumes or remove_volumes):
            msg = _("Name, description, add_volumes, and remove_volumes "
                    "can not be all empty in the request body.")
            raise exc.HTTPBadRequest(explanation=msg)

    def _update(self, context, group, name, description, add_volumes,
                remove_volumes,
                allow_empty=False):
        LOG.info("Updating consistency group %(id)s with name %(name)s "
                 "description: %(description)s add_volumes: "
                 "%(add_volumes)s remove_volumes: %(remove_volumes)s.",
                 {'id': group.id,
                  'name': name,
                  'description': description,
                  'add_volumes': add_volumes,
                  'remove_volumes': remove_volumes})

        self.group_api.update(context, group, name, description,
                              add_volumes, remove_volumes)

    def update(self, req, id, body):
        """Update the consistency group.

        Expected format of the input parameter 'body':

        .. code-block:: json

            {
                "consistencygroup":
                {
                    "name": "my_cg",
                    "description": "My consistency group",
                    "add_volumes": "volume-uuid-1,volume-uuid-2,...",
                    "remove_volumes": "volume-uuid-8,volume-uuid-9,..."
                }
            }

        """
        versionutils.report_deprecated_feature(LOG, DEPRECATE_CG_API_MSG)
        LOG.debug('Update called for consistency group %s.', id)
        if not body:
            msg = _("Missing request body.")
            raise exc.HTTPBadRequest(explanation=msg)

        self.assert_valid_body(body, 'consistencygroup')
        context = req.environ['cinder.context']
        group = self._get(context, id)
        context.authorize(group_policy.UPDATE_POLICY, target_obj=group)
        consistencygroup = body.get('consistencygroup', None)
        self.validate_name_and_description(consistencygroup)
        name = consistencygroup.get('name', None)
        description = consistencygroup.get('description', None)
        add_volumes = consistencygroup.get('add_volumes', None)
        remove_volumes = consistencygroup.get('remove_volumes', None)

        self._check_update_parameters(name, description, add_volumes,
                                      remove_volumes)
        self._update(context, group, name, description, add_volumes,
                     remove_volumes)
        return webob.Response(status_int=http_client.ACCEPTED)


class Consistencygroups(extensions.ExtensionDescriptor):
    """consistency groups support."""

    name = 'Consistencygroups'
    alias = 'consistencygroups'
    updated = '2014-08-18T00:00:00+00:00'

    def get_resources(self):
        resources = []
        res = extensions.ResourceExtension(
            Consistencygroups.alias, ConsistencyGroupsController(),
            collection_actions={'detail': 'GET', 'create_from_src': 'POST'},
            member_actions={'delete': 'POST', 'update': 'PUT'})
        resources.append(res)
        return resources
