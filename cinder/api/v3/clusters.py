# Copyright (c) 2016 Red Hat Inc.
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

from cinder.api import microversions as mv
from cinder.api.openstack import wsgi
from cinder.api.schemas import clusters as cluster
from cinder.api.v3.views import clusters as clusters_view
from cinder.api import validation
from cinder.common import constants
from cinder import exception
from cinder.i18n import _
from cinder import objects
from cinder.policies import clusters as policy
from cinder import utils


class ClusterController(wsgi.Controller):
    allowed_list_keys = {'name', 'binary', 'is_up', 'disabled', 'num_hosts',
                         'num_down_hosts', 'binary', 'replication_status',
                         'frozen', 'active_backend_id'}
    replication_fields = {'replication_status', 'frozen', 'active_backend_id'}

    @wsgi.Controller.api_version(mv.CLUSTER_SUPPORT)
    def show(self, req, id, binary=constants.VOLUME_BINARY):
        """Return data for a given cluster name with optional binary."""
        # Let the wsgi middleware convert NotAuthorized exceptions
        context = req.environ['cinder.context']
        context.authorize(policy.GET_POLICY)
        # Let the wsgi middleware convert NotFound exceptions
        cluster = objects.Cluster.get_by_id(context, None, binary=binary,
                                            name=id, services_summary=True)
        replication_data = req.api_version_request.matches(
            mv.REPLICATION_CLUSTER)
        return clusters_view.ViewBuilder.detail(cluster, replication_data)

    @wsgi.Controller.api_version(mv.CLUSTER_SUPPORT)
    def index(self, req):
        """Return a non detailed list of all existing clusters.

        Filter by is_up, disabled, num_hosts, and num_down_hosts.
        """
        return self._get_clusters(req, detail=False)

    @wsgi.Controller.api_version(mv.CLUSTER_SUPPORT)
    def detail(self, req):
        """Return a detailed list of all existing clusters.

        Filter by is_up, disabled, num_hosts, and num_down_hosts.
        """
        return self._get_clusters(req, detail=True)

    def _get_clusters(self, req, detail):
        # Let the wsgi middleware convert NotAuthorized exceptions
        context = req.environ['cinder.context']
        context.authorize(policy.GET_ALL_POLICY)
        replication_data = req.api_version_request.matches(
            mv.REPLICATION_CLUSTER)
        filters = dict(req.GET)
        allowed = self.allowed_list_keys
        if not replication_data:
            allowed = allowed.difference(self.replication_fields)

        # Check filters are valid
        if not allowed.issuperset(filters):
            invalid_keys = set(filters).difference(allowed)
            msg = _('Invalid filter keys: %s') % ', '.join(invalid_keys)
            raise exception.InvalidInput(reason=msg)

        # Check boolean values
        for bool_key in ('disabled', 'is_up'):
            if bool_key in filters:
                filters[bool_key] = utils.get_bool_param(bool_key, req.GET)

        # For detailed view we need the services summary information
        filters['services_summary'] = detail

        clusters = objects.ClusterList.get_all(context, **filters)
        return clusters_view.ViewBuilder.list(clusters, detail,
                                              replication_data)

    @wsgi.Controller.api_version(mv.CLUSTER_SUPPORT)
    def update(self, req, id, body):
        """Enable/Disable scheduling for a cluster."""
        # NOTE(geguileo): This method tries to be consistent with services
        # update endpoint API.

        # Let the wsgi middleware convert NotAuthorized exceptions
        context = req.environ['cinder.context']
        context.authorize(policy.UPDATE_POLICY)

        if id not in ('enable', 'disable'):
            raise exception.NotFound(message=_("Unknown action"))

        disabled = id != 'enable'
        disabled_reason = self._disable_cluster(
            req, body=body) if disabled else self._enable_cluster(
            req, body=body)

        name = body['name']

        binary = body.get('binary', constants.VOLUME_BINARY)

        # Let wsgi handle NotFound exception
        cluster = objects.Cluster.get_by_id(context, None, binary=binary,
                                            name=name)
        cluster.disabled = disabled
        cluster.disabled_reason = disabled_reason
        cluster.save()

        # We return summary data plus the disabled reason
        replication_data = req.api_version_request.matches(
            mv.REPLICATION_CLUSTER)
        ret_val = clusters_view.ViewBuilder.summary(cluster, replication_data)
        ret_val['cluster']['disabled_reason'] = disabled_reason

        return ret_val

    @validation.schema(cluster.disable_cluster)
    def _disable_cluster(self, req, body):
        reason = body.get('disabled_reason')
        if reason:
            reason = reason.strip()
        return reason

    @validation.schema(cluster.enable_cluster)
    def _enable_cluster(self, req, body):
        pass


def create_resource():
    return wsgi.Resource(ClusterController())
