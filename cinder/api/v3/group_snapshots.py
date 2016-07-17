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

"""The group_snapshots api."""

from oslo_log import log as logging
import six
import webob
from webob import exc

from cinder.api import common
from cinder.api.openstack import wsgi
from cinder.api.v3.views import group_snapshots as group_snapshot_views
from cinder import exception
from cinder import group as group_api
from cinder.i18n import _, _LI

LOG = logging.getLogger(__name__)

GROUP_SNAPSHOT_API_VERSION = '3.14'


class GroupSnapshotsController(wsgi.Controller):
    """The group_snapshots API controller for the OpenStack API."""

    _view_builder_class = group_snapshot_views.ViewBuilder

    def __init__(self):
        self.group_snapshot_api = group_api.API()
        super(GroupSnapshotsController, self).__init__()

    @wsgi.Controller.api_version(GROUP_SNAPSHOT_API_VERSION)
    def show(self, req, id):
        """Return data about the given group_snapshot."""
        LOG.debug('show called for member %s', id)
        context = req.environ['cinder.context']

        group_snapshot = self.group_snapshot_api.get_group_snapshot(
            context,
            group_snapshot_id=id)

        return self._view_builder.detail(req, group_snapshot)

    @wsgi.Controller.api_version(GROUP_SNAPSHOT_API_VERSION)
    def delete(self, req, id):
        """Delete a group_snapshot."""
        LOG.debug('delete called for member %s', id)
        context = req.environ['cinder.context']

        LOG.info(_LI('Delete group_snapshot with id: %s'), id, context=context)

        try:
            group_snapshot = self.group_snapshot_api.get_group_snapshot(
                context,
                group_snapshot_id=id)
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

        return webob.Response(status_int=202)

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
        group_snapshots = self.group_snapshot_api.get_all_group_snapshots(
            context)
        limited_list = common.limited(group_snapshots, req)

        if is_detail:
            group_snapshots = self._view_builder.detail_list(req, limited_list)
        else:
            group_snapshots = self._view_builder.summary_list(req,
                                                              limited_list)
        return group_snapshots

    @wsgi.Controller.api_version(GROUP_SNAPSHOT_API_VERSION)
    @wsgi.response(202)
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

        name = group_snapshot.get('name', None)
        description = group_snapshot.get('description', None)

        LOG.info(_LI("Creating group_snapshot %(name)s."),
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


def create_resource():
    return wsgi.Resource(GroupSnapshotsController())
