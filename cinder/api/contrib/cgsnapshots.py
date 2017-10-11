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

"""The cgsnapshots api."""

from oslo_log import log as logging
import six
from six.moves import http_client
import webob
from webob import exc

from cinder.api import common
from cinder.api import extensions
from cinder.api.openstack import wsgi
from cinder.api.views import cgsnapshots as cgsnapshot_views
from cinder import exception
from cinder import group as group_api
from cinder.i18n import _

LOG = logging.getLogger(__name__)


class CgsnapshotsController(wsgi.Controller):
    """The cgsnapshots API controller for the OpenStack API."""

    _view_builder_class = cgsnapshot_views.ViewBuilder

    def __init__(self):
        self.group_snapshot_api = group_api.API()
        super(CgsnapshotsController, self).__init__()

    def show(self, req, id):
        """Return data about the given cgsnapshot."""
        LOG.debug('show called for member %s', id)
        context = req.environ['cinder.context']

        # Not found exception will be handled at the wsgi level
        cgsnapshot = self._get_cgsnapshot(context, id)

        return self._view_builder.detail(req, cgsnapshot)

    def delete(self, req, id):
        """Delete a cgsnapshot."""
        LOG.debug('delete called for member %s', id)
        context = req.environ['cinder.context']

        LOG.info('Delete cgsnapshot with id: %s', id)
        try:
            cgsnapshot = self._get_cgsnapshot(context, id)
            self.group_snapshot_api.delete_group_snapshot(context, cgsnapshot)
        except exception.InvalidGroupSnapshot as e:
            raise exc.HTTPBadRequest(explanation=six.text_type(e))
        except (exception.GroupSnapshotNotFound,
                exception.PolicyNotAuthorized) as e:
            # Exceptions will be handled at the wsgi level
            raise
        except Exception:
            msg = _('Failed to delete the cgsnapshot')
            raise exc.HTTPBadRequest(explanation=msg)

        return webob.Response(status_int=http_client.ACCEPTED)

    def index(self, req):
        """Returns a summary list of cgsnapshots."""
        return self._get_cgsnapshots(req, is_detail=False)

    def detail(self, req):
        """Returns a detailed list of cgsnapshots."""
        return self._get_cgsnapshots(req, is_detail=True)

    def _get_cg(self, context, id):
        # Not found exception will be handled at the wsgi level
        consistencygroup = self.group_snapshot_api.get(context, group_id=id)

        return consistencygroup

    def _get_cgsnapshot(self, context, id):
        # Not found exception will be handled at the wsgi level
        cgsnapshot = self.group_snapshot_api.get_group_snapshot(
            context, group_snapshot_id=id)

        return cgsnapshot

    def _get_cgsnapshots(self, req, is_detail):
        """Returns a list of cgsnapshots, transformed through view builder."""
        context = req.environ['cinder.context']
        grp_snapshots = self.group_snapshot_api.get_all_group_snapshots(
            context)
        grpsnap_limited_list = common.limited(grp_snapshots, req)

        if is_detail:
            grp_snapshots = self._view_builder.detail_list(
                req, grpsnap_limited_list)
        else:
            grp_snapshots = self._view_builder.summary_list(
                req, grpsnap_limited_list)

        return grp_snapshots

    @wsgi.response(http_client.ACCEPTED)
    def create(self, req, body):
        """Create a new cgsnapshot."""
        LOG.debug('Creating new cgsnapshot %s', body)
        self.assert_valid_body(body, 'cgsnapshot')

        context = req.environ['cinder.context']
        cgsnapshot = body['cgsnapshot']
        self.validate_name_and_description(cgsnapshot)

        try:
            group_id = cgsnapshot['consistencygroup_id']
        except KeyError:
            msg = _("'consistencygroup_id' must be specified")
            raise exc.HTTPBadRequest(explanation=msg)

        # Not found exception will be handled at the wsgi level
        group = self._get_cg(context, group_id)

        name = cgsnapshot.get('name', None)
        description = cgsnapshot.get('description', None)

        LOG.info("Creating cgsnapshot %(name)s.",
                 {'name': name},
                 context=context)

        try:
            new_cgsnapshot = self.group_snapshot_api.create_group_snapshot(
                context, group, name, description)
        # Not found exception will be handled at the wsgi level
        except (exception.InvalidGroup,
                exception.InvalidGroupSnapshot,
                exception.InvalidVolume) as error:
            raise exc.HTTPBadRequest(explanation=error.msg)

        retval = self._view_builder.summary(req, new_cgsnapshot)

        return retval


class Cgsnapshots(extensions.ExtensionDescriptor):
    """cgsnapshots support."""

    name = 'Cgsnapshots'
    alias = 'cgsnapshots'
    updated = '2014-08-18T00:00:00+00:00'

    def get_resources(self):
        resources = []
        res = extensions.ResourceExtension(
            Cgsnapshots.alias, CgsnapshotsController(),
            collection_actions={'detail': 'GET'})
        resources.append(res)
        return resources
