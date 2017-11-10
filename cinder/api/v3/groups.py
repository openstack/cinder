# Copyright (c) 2016 EMC Corporation
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

"""The groups controller."""

from oslo_log import log as logging
from oslo_utils import strutils
from oslo_utils import uuidutils
from six.moves import http_client
import webob
from webob import exc

from cinder.api import common
from cinder.api import microversions as mv
from cinder.api.openstack import wsgi
from cinder.api.schemas import groups as group
from cinder.api.v3.views import groups as views_groups
from cinder.api import validation
from cinder import exception
from cinder import group as group_api
from cinder.i18n import _
from cinder import rpc
from cinder.volume import group_types

LOG = logging.getLogger(__name__)


class GroupsController(wsgi.Controller):
    """The groups API controller for the OpenStack API."""

    _view_builder_class = views_groups.ViewBuilder

    def __init__(self):
        self.group_api = group_api.API()
        super(GroupsController, self).__init__()

    def _check_default_cgsnapshot_type(self, group_type_id):
        if group_types.is_default_cgsnapshot_type(group_type_id):
            msg = _("Group_type %(group_type)s is reserved for migrating "
                    "CGs to groups. Migrated group can only be operated by "
                    "CG APIs.") % {'group_type': group_type_id}
            raise exc.HTTPBadRequest(explanation=msg)

    @wsgi.Controller.api_version(mv.GROUP_VOLUME)
    def show(self, req, id):
        """Return data about the given group."""
        LOG.debug('show called for member %s', id)
        context = req.environ['cinder.context']

        # Not found exception will be handled at the wsgi level
        group = self.group_api.get(
            context,
            group_id=id)

        self._check_default_cgsnapshot_type(group.group_type_id)

        return self._view_builder.detail(req, group)

    @wsgi.Controller.api_version(mv.GROUP_VOLUME_RESET_STATUS)
    @wsgi.action("reset_status")
    @validation.schema(group.reset_status)
    def reset_status(self, req, id, body):
        return self._reset_status(req, id, body)

    def _reset_status(self, req, id, body):
        """Reset status on generic group."""

        context = req.environ['cinder.context']
        status = body['reset_status']['status'].lower()

        LOG.debug("Updating group '%(id)s' with "
                  "'%(update)s'", {'id': id,
                                   'update': status})
        try:
            notifier = rpc.get_notifier('groupStatusUpdate')
            notifier.info(context, 'groups.reset_status.start',
                          {'id': id,
                           'update': status})
            group = self.group_api.get(context, id)

            self.group_api.reset_status(context, group, status)
            notifier.info(context, 'groups.reset_status.end',
                          {'id': id,
                           'update': status})
        except exception.GroupNotFound as error:
            # Not found exception will be handled at the wsgi level
            notifier.error(context, 'groups.reset_status',
                           {'error_message': error.msg,
                            'id': id})
            raise
        except exception.InvalidGroupStatus as error:
            notifier.error(context, 'groups.reset_status',
                           {'error_message': error.msg,
                            'id': id})
            raise exc.HTTPBadRequest(explanation=error.msg)
        return webob.Response(status_int=http_client.ACCEPTED)

    @wsgi.Controller.api_version(mv.GROUP_VOLUME)
    @wsgi.action("delete")
    @validation.schema(group.delete)
    def delete_group(self, req, id, body):
        return self._delete(req, id, body)

    def _delete(self, req, id, body):
        """Delete a group."""
        LOG.debug('delete called for group %s', id)
        context = req.environ['cinder.context']
        grp_body = body['delete']
        del_vol = strutils.bool_from_string(grp_body.get(
            'delete-volumes', False))

        LOG.info('Delete group with id: %s', id,
                 context=context)

        try:
            group = self.group_api.get(context, id)
            self._check_default_cgsnapshot_type(group.group_type_id)
            self.group_api.delete(context, group, del_vol)
        except exception.GroupNotFound:
            # Not found exception will be handled at the wsgi level
            raise
        except exception.InvalidGroup as error:
            raise exc.HTTPBadRequest(explanation=error.msg)

        return webob.Response(status_int=http_client.ACCEPTED)

    @wsgi.Controller.api_version(mv.GROUP_VOLUME)
    def index(self, req):
        """Returns a summary list of groups."""
        return self._get_groups(req, is_detail=False)

    @wsgi.Controller.api_version(mv.GROUP_VOLUME)
    def detail(self, req):
        """Returns a detailed list of groups."""
        return self._get_groups(req, is_detail=True)

    def _get_groups(self, req, is_detail):
        """Returns a list of groups through view builder."""
        context = req.environ['cinder.context']
        filters = req.params.copy()
        api_version = req.api_version_request
        marker, limit, offset = common.get_pagination_params(filters)
        sort_keys, sort_dirs = common.get_sort_params(filters)

        filters.pop('list_volume', None)
        if api_version.matches(mv.RESOURCE_FILTER):
            support_like = (True if api_version.matches(
                mv.LIKE_FILTER) else False)
            common.reject_invalid_filters(context, filters, 'group',
                                          support_like)

        groups = self.group_api.get_all(
            context, filters=filters, marker=marker, limit=limit,
            offset=offset, sort_keys=sort_keys, sort_dirs=sort_dirs)

        new_groups = []
        for grp in groups:
            try:
                # Only show groups not migrated from CGs
                self._check_default_cgsnapshot_type(grp.group_type_id)
                new_groups.append(grp)
            except exc.HTTPBadRequest:
                # Skip migrated group
                pass

        if is_detail:
            groups = self._view_builder.detail_list(
                req, new_groups)
        else:
            groups = self._view_builder.summary_list(
                req, new_groups)
        return groups

    @wsgi.Controller.api_version(mv.GROUP_VOLUME)
    @wsgi.response(http_client.ACCEPTED)
    @validation.schema(group.create)
    def create(self, req, body):
        """Create a new group."""
        LOG.debug('Creating new group %s', body)
        context = req.environ['cinder.context']
        group = body['group']
        name = group.get('name')
        description = group.get('description')
        if name:
            name = name.strip()
        if description:
            description = description.strip()
        group_type = group['group_type']
        if not uuidutils.is_uuid_like(group_type):
            req_group_type = group_types.get_group_type_by_name(context,
                                                                group_type)
            group_type = req_group_type['id']
        self._check_default_cgsnapshot_type(group_type)
        volume_types = group['volume_types']
        availability_zone = group.get('availability_zone')

        LOG.info("Creating group %(name)s.",
                 {'name': name},
                 context=context)

        try:
            new_group = self.group_api.create(
                context, name, description, group_type, volume_types,
                availability_zone=availability_zone)
        except (exception.Invalid, exception.ObjectActionError) as error:
            raise exc.HTTPBadRequest(explanation=error.msg)
        except exception.NotFound:
            # Not found exception will be handled at the wsgi level
            raise

        retval = self._view_builder.summary(req, new_group)
        return retval

    @wsgi.Controller.api_version(mv.GROUP_SNAPSHOTS)
    @wsgi.action("create-from-src")
    @wsgi.response(http_client.ACCEPTED)
    @validation.schema(group.create_from_source)
    def create_from_src(self, req, body):
        """Create a new group from a source.

        The source can be a group snapshot or a group. Note that
        this does not require group_type and volume_types as the
        "create" API above.
        """
        LOG.debug('Creating new group %s.', body)

        context = req.environ['cinder.context']
        group = body['create-from-src']
        name = group.get('name')
        description = group.get('description')
        if name:
            name = name.strip()
        if description:
            description = description.strip()
        group_snapshot_id = group.get('group_snapshot_id', None)
        source_group_id = group.get('source_group_id', None)

        group_type_id = None
        if group_snapshot_id:
            LOG.info("Creating group %(name)s from group_snapshot "
                     "%(snap)s.",
                     {'name': name, 'snap': group_snapshot_id},
                     context=context)
            grp_snap = self.group_api.get_group_snapshot(context,
                                                         group_snapshot_id)
            group_type_id = grp_snap.group_type_id
        elif source_group_id:
            LOG.info("Creating group %(name)s from "
                     "source group %(source_group_id)s.",
                     {'name': name, 'source_group_id': source_group_id},
                     context=context)
            source_group = self.group_api.get(context, source_group_id)
            group_type_id = source_group.group_type_id

        self._check_default_cgsnapshot_type(group_type_id)

        try:
            new_group = self.group_api.create_from_src(
                context, name, description, group_snapshot_id, source_group_id)
        except exception.InvalidGroup as error:
            raise exc.HTTPBadRequest(explanation=error.msg)
        except (exception.GroupNotFound, exception.GroupSnapshotNotFound):
            # Not found exception will be handled at the wsgi level
            raise
        except exception.CinderException as error:
            raise exc.HTTPBadRequest(explanation=error.msg)

        retval = self._view_builder.summary(req, new_group)
        return retval

    @wsgi.Controller.api_version(mv.GROUP_VOLUME)
    @validation.schema(group.update)
    def update(self, req, id, body):
        """Update the group.

        Expected format of the input parameter 'body':

        .. code-block:: json

            {
                "group":
                {
                    "name": "my_group",
                    "description": "My group",
                    "add_volumes": "volume-uuid-1,volume-uuid-2,...",
                    "remove_volumes": "volume-uuid-8,volume-uuid-9,..."
                }
            }

        """
        LOG.debug('Update called for group %s.', id)

        context = req.environ['cinder.context']

        group = body['group']
        name = group.get('name')
        description = group.get('description')
        if name:
            name = name.strip()
        if description:
            description = description.strip()
        add_volumes = group.get('add_volumes')
        remove_volumes = group.get('remove_volumes')

        LOG.info("Updating group %(id)s with name %(name)s "
                 "description: %(description)s add_volumes: "
                 "%(add_volumes)s remove_volumes: %(remove_volumes)s.",
                 {'id': id, 'name': name,
                  'description': description,
                  'add_volumes': add_volumes,
                  'remove_volumes': remove_volumes},
                 context=context)

        try:
            group = self.group_api.get(context, id)
            self._check_default_cgsnapshot_type(group.group_type_id)
            self.group_api.update(
                context, group, name, description,
                add_volumes, remove_volumes)
        except exception.GroupNotFound:
            # Not found exception will be handled at the wsgi level
            raise
        except exception.InvalidGroup as error:
            raise exc.HTTPBadRequest(explanation=error.msg)

        return webob.Response(status_int=http_client.ACCEPTED)

    @wsgi.Controller.api_version(mv.GROUP_REPLICATION)
    @wsgi.action("enable_replication")
    @validation.schema(group.enable_replication)
    def enable_replication(self, req, id, body):
        """Enables replications for a group."""
        context = req.environ['cinder.context']

        LOG.info('Enable replication group with id: %s.', id,
                 context=context)

        try:
            group = self.group_api.get(context, id)
            self.group_api.enable_replication(context, group)
            # Not found exception will be handled at the wsgi level
        except (exception.InvalidGroup, exception.InvalidGroupType,
                exception.InvalidVolume, exception.InvalidVolumeType) as error:
            raise exc.HTTPBadRequest(explanation=error.msg)

        return webob.Response(status_int=http_client.ACCEPTED)

    @wsgi.Controller.api_version(mv.GROUP_REPLICATION)
    @wsgi.action("disable_replication")
    @validation.schema(group.disable_replication)
    def disable_replication(self, req, id, body):
        """Disables replications for a group."""
        context = req.environ['cinder.context']

        LOG.info('Disable replication group with id: %s.', id,
                 context=context)

        try:
            group = self.group_api.get(context, id)
            self.group_api.disable_replication(context, group)
            # Not found exception will be handled at the wsgi level
        except (exception.InvalidGroup, exception.InvalidGroupType,
                exception.InvalidVolume, exception.InvalidVolumeType) as error:
            raise exc.HTTPBadRequest(explanation=error.msg)

        return webob.Response(status_int=http_client.ACCEPTED)

    @wsgi.Controller.api_version(mv.GROUP_REPLICATION)
    @wsgi.action("failover_replication")
    @validation.schema(group.failover_replication)
    def failover_replication(self, req, id, body):
        """Fails over replications for a group."""
        context = req.environ['cinder.context']

        grp_body = body['failover_replication']

        allow_attached = strutils.bool_from_string(
            grp_body.get('allow_attached_volume', False))
        secondary_backend_id = grp_body.get('secondary_backend_id')

        LOG.info('Failover replication group with id: %s.', id,
                 context=context)

        try:
            group = self.group_api.get(context, id)
            self.group_api.failover_replication(context, group, allow_attached,
                                                secondary_backend_id)
            # Not found exception will be handled at the wsgi level
        except (exception.InvalidGroup, exception.InvalidGroupType,
                exception.InvalidVolume, exception.InvalidVolumeType) as error:
            raise exc.HTTPBadRequest(explanation=error.msg)

        return webob.Response(status_int=http_client.ACCEPTED)

    @wsgi.Controller.api_version(mv.GROUP_REPLICATION)
    @wsgi.action("list_replication_targets")
    @validation.schema(group.list_replication)
    def list_replication_targets(self, req, id, body):
        """List replication targets for a group."""
        context = req.environ['cinder.context']

        LOG.info('List replication targets for group with id: %s.', id,
                 context=context)

        # Not found exception will be handled at the wsgi level
        group = self.group_api.get(context, id)
        replication_targets = self.group_api.list_replication_targets(
            context, group)

        return replication_targets


def create_resource():
    return wsgi.Resource(GroupsController())
