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

"""The resource filters api."""

from cinder.api import common
from cinder.api.openstack import wsgi
from cinder.api.v3.views import resource_filters as filter_views


FILTER_API_VERSION = '3.33'


class ResourceFiltersController(wsgi.Controller):
    """The resource filter API controller for the OpenStack API."""

    _view_builder_class = filter_views.ViewBuilder

    def __init__(self, ext_mgr=None):
        """Initialize controller class."""
        self.ext_mgr = ext_mgr
        super(ResourceFiltersController, self).__init__()

    @wsgi.Controller.api_version(FILTER_API_VERSION)
    def index(self, req):
        """Return a list of resource filters."""
        resource = req.params.get('resource', None)
        filters = common.get_enabled_resource_filters(resource=resource)
        return filter_views.ViewBuilder.list(filters)


def create_resource(ext_mgr):
    """Create the wsgi resource for this controller."""
    return wsgi.Resource(ResourceFiltersController(ext_mgr))
