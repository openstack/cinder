# Copyright (c) 2014 eBay Inc.
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

"""The Scheduler Stats extension"""

from cinder.api import common
from cinder.api import extensions
from cinder.api import microversions as mv
from cinder.api.openstack import wsgi
from cinder.api.views import scheduler_stats as scheduler_stats_view
from cinder.policies import scheduler_stats as policy
from cinder.scheduler import rpcapi
from cinder import utils


class SchedulerStatsController(wsgi.Controller):
    """The Scheduler Stats controller for the OpenStack API."""

    _view_builder_class = scheduler_stats_view.ViewBuilder

    def __init__(self):
        self.scheduler_api = rpcapi.SchedulerAPI()
        super(SchedulerStatsController, self).__init__()

    @common.process_general_filtering('pool')
    def _process_pool_filtering(self, context=None, filters=None,
                                req_version=None):
        if not req_version.matches(mv.POOL_FILTER):
            filters.clear()

    def get_pools(self, req):
        """List all active pools in scheduler."""
        context = req.environ['cinder.context']
        context.authorize(policy.GET_POOL_POLICY)

        detail = utils.get_bool_param('detail', req.params)

        req_version = req.api_version_request
        filters = req.params.copy()
        filters.pop('detail', None)

        self._process_pool_filtering(context=context,
                                     filters=filters,
                                     req_version=req_version)

        if not req_version.matches(mv.POOL_TYPE_FILTER):
            filters.pop('volume_type', None)

        pools = self.scheduler_api.get_pools(context, filters=filters)

        return self._view_builder.pools(req, pools, detail)


class Scheduler_stats(extensions.ExtensionDescriptor):
    """Scheduler stats support."""

    name = "Scheduler_stats"
    alias = "scheduler-stats"
    updated = "2014-09-07T00:00:00+00:00"

    def get_resources(self):
        resources = []
        res = extensions.ResourceExtension(
            Scheduler_stats.alias,
            SchedulerStatsController(),
            collection_actions={"get_pools": "GET"})

        resources.append(res)

        return resources
