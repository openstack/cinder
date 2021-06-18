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

"""The limits V3 api."""

from cinder.api import microversions as mv
from cinder.api.openstack import wsgi
from cinder.api.v2 import limits as limits_v2
from cinder.api.views import limits as limits_views
from cinder import quota

QUOTAS = quota.QUOTAS


class LimitsController(limits_v2.LimitsController):
    """Controller for accessing limits in the OpenStack API."""

    def index(self, req):
        """Return all global and rate limit information."""
        context = req.environ['cinder.context']
        params = req.params.copy()
        req_version = req.api_version_request

        # TODO(wangxiyuan): Support "tenant_id" here to keep the backwards
        # compatibility. Remove it once we drop all support for "tenant".
        if (req_version.matches(None,
                                mv.get_prior_version(mv.LIMITS_ADMIN_FILTER))
                or not context.is_admin):
            params.pop('project_id', None)
            params.pop('tenant_id', None)
        project_id = params.get(
            'project_id', params.get('tenant_id', context.project_id))

        quotas = QUOTAS.get_project_quotas(context, project_id,
                                           usages=False)
        abs_limits = {k: v['limit'] for k, v in quotas.items()}
        rate_limits = req.environ.get("cinder.limits", [])

        builder = self._get_view_builder(req)
        return builder.build(rate_limits, abs_limits)

    def _get_view_builder(self, req):
        return limits_views.ViewBuilder()


def create_resource():
    return wsgi.Resource(LimitsController())
