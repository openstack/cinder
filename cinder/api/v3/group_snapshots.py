# Copyright (C) 2016 EMC Corporation.
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

"""The group_snapshots API."""

from oslo_log import log as logging
import six
from six.moves import http_client
import webob
from webob import exc

from cinder.api import common
from cinder.api.openstack import wsgi
from cinder.api.v3.views import group_snapshots as group_snapshot_views
from cinder import exception
from cinder import group as group_api
from cinder.i18n import _
from cinder import rpc
from cinder.volume import group_types

LOG = logging.getLogger(__name__)

GROUP_SNAPSHOT_API_VERSION = '3.14'


class GroupSnapshotsController(wsgi.Controller):
    """The group_snapshots API controller for the OpenStack API."""

    _view_builder_class = group_snapshot_views.ViewBuilder

    def __init__(self):
        self.group_snapshot_api = group_api.API()
        super(GroupSnapshotsController, self).__init__()

    def _check_default_cgsnapshot_type(self, group_type_id):
        if group_types.is_default_cgsnapshot_type(group_type_id):
            msg = (_("Group_type %(group_type)s is reserved for migrating "
                     "CGs to groups. Migrated group snapshots can only be "
                     "operated by CG snapshot APIs.")
                   % {'group_type': group_type_id})
            raise exc.HTTPBadRequest(explanation=msg)

    @wsgi.Controller.api_version(GROUP_SNAPSHOT_API_VERSION)
    def show(self, req, id):
        """Return data about the given group_snapshot."""
        LOG.debug('show called for member %s', id)
        context = req.environ['cinder.context']

        group_snapshot = self.group_snapshot_api.get_group_snapshot(
            context,
            group_snapshot_id=id)

        self._check_default_cgsnapshot_type(group_snapshot.group_type_id)

        return self._view_builder.detail(req, group_snapshot)

    @wsgi.Controller.api_version(GROUP_SNAPSHOT_API_VERSION)
    def delete(self, req, id):
        """Delete a group_snapshot."""
        LOG.debug('delete called for member %s', id)
        context = req.environ['cinder.context']

        LOG.info('Delete group_snapshot with id: %s', id, context=context)

        try:
            group_snapshot = self.group_snapshot_api.get_group_snapshot(
                context,
                group_snapshot_id=id)
            self._check_default_cgsnapshot_type(group_snapshot.group_type_id)
            self.group_snapshot_api.delete_group_snapshot(context,
                                                          group_snapshot)
        except exception.InvalidGroupSnapshot as e:
            raise exc.HTTPBadRequest(explanation=six.text_type(e))
        except exception.GroupSnapshotNotFound:
            # Not found exception will be handled at the wsgi level
            raise
        except Exception:
            msg = _("Error occurred when deleting group snapshot %s.") % id
            LOG.exception(msg)
            raise exc.HTTPBadRequest(explanation=msg)

        return webob.Response(status_int=http_client.ACCEPTED)

    @wsgi.Controller.api_version(GROUP_SNAPSHOT_API_VERSION)
    def index(self, req):
        """Returns a summary list of group_snapshots."""
        return self._get_group_snapshots(req, is_detail=False)

    @wsgi.Controller.api_version(GROUP_SNAPSHOT_API_VERSION)
    def detail(self, req):
        """Returns a detailed list of group_snapshots."""
        return self._get_group_snapshots(req, is_detail=True)

    def _get_group_snapshots(self, req, is_detail):
        """Returns a list of group_snapshots through view builder."""

        context = req.environ['cinder.context']
        req_version = req.api_version_request
        filters = marker = limit = offset = sort_keys = sort_dirs = None
        if req_version.matches("3.29"):
            filters = req.params.copy()
            marker, limit, offset = common.get_pagination_params(filters)
            sort_keys, sort_dirs = common.get_sort_params(filters)

        if req_version.matches(common.FILTERING_VERSION):
            support_like = (True if req_version.matches(
                common.LIKE_FILTER_VERSION) else False)
            common.reject_invalid_filters(context, filters, 'group_snapshot',
                                          support_like)

        group_snapshots = self.group_snapshot_api.get_all_group_snapshots(
            context, filters=filters, marker=marker, limit=limit,
            offset=offset, sort_keys=sort_keys, sort_dirs=sort_dirs)
        if is_detail:
            group_snapshots = self._view_builder.detail_list(req,
                                                             group_snapshots)
        else:
            group_snapshots = self._view_builder.summary_list(req,
                                                              group_snapshots)

        new_group_snapshots = []
        for grp_snap in group_snapshots['group_snapshots']:
            try:
                # Only show group snapshots not migrated from CG snapshots
                self._check_default_cgsnapshot_type(grp_snap['group_type_id'])
                if not is_detail:
                    grp_snap.pop('group_type_id', None)
                new_group_snapshots.append(grp_snap)
            except exc.HTTPBadRequest:
                # Skip migrated group snapshot
                pass

        group_snapshots['group_snapshots'] = new_group_snapshots
        return group_snapshots

    @wsgi.Controller.api_version(GROUP_SNAPSHOT_API_VERSION)
    @wsgi.response(http_client.ACCEPTED)
    def create(self, req, body):
        """Create a new group_snapshot."""
        LOG.debug('Creating new group_snapshot %s', body)
        self.assert_valid_body(body, 'group_snapshot')

        context = req.environ['cinder.context']
        group_snapshot = body['group_snapshot']
        self.validate_name_and_description(group_snapshot)

        try:
            group_id = group_snapshot['group_id']
        except KeyError:
            msg = _("'group_id' must be specified")
            raise exc.HTTPBadRequest(explanation=msg)

        group = self.group_snapshot_api.get(context, group_id)
        self._check_default_cgsnapshot_type(group.group_type_id)
        name = group_snapshot.get('name', None)
        description = group_snapshot.get('description', None)

        LOG.info("Creating group_snapshot %(name)s.",
                 {'name': name},
                 context=context)

        try:
            new_group_snapshot = self.group_snapshot_api.create_group_snapshot(
                context, group, name, description)
        except (exception.InvalidGroup,
                exception.InvalidGroupSnapshot,
                exception.InvalidVolume) as error:
            raise exc.HTTPBadRequest(explanation=error.msg)

        retval = self._view_builder.summary(req, new_group_snapshot)

        return retval

    @wsgi.Controller.api_version('3.19')
    @wsgi.action("reset_status")
    def reset_status(self, req, id, body):
        return self._reset_status(req, id, body)

    def _reset_status(self, req, id, body):
        """Reset status on group snapshots"""

        context = req.environ['cinder.context']
        try:
            status = body['reset_status']['status'].lower()
        except (TypeError, KeyError):
            raise exc.HTTPBadRequest(explanation=_("Must specify 'status'"))

        LOG.debug("Updating group '%(id)s' with "
                  "'%(update)s'", {'id': id,
                                   'update': status})
        try:
            notifier = rpc.get_notifier('groupSnapshotStatusUpdate')
            notifier.info(context, 'groupsnapshots.reset_status.start',
                          {'id': id,
                           'update': status})
            gsnapshot = self.group_snapshot_api.get_group_snapshot(context, id)

            self.group_snapshot_api.reset_group_snapshot_status(context,
                                                                gsnapshot,
                                                                status)
            notifier.info(context, 'groupsnapshots.reset_status.end',
                          {'id': id,
                           'update': status})
        except exception.GroupSnapshotNotFound as error:
            # Not found exception will be handled at the wsgi level
            notifier.error(context, 'groupsnapshots.reset_status',
                           {'error_message': error.msg,
                            'id': id})
            raise
        except exception.InvalidGroupSnapshotStatus as error:
            notifier.error(context, 'groupsnapshots.reset_status',
                           {'error_message': error.msg,
                            'id': id})
            raise exc.HTTPBadRequest(explanation=error.msg)
        return webob.Response(status_int=http_client.ACCEPTED)


def create_resource():
    return wsgi.Resource(GroupSnapshotsController())
