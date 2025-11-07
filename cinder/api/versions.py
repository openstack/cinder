# Copyright 2010 OpenStack Foundation
# Copyright 2015 Clinton Knight
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


import copy
from http import HTTPStatus

from oslo_config import cfg
from oslo_service import wsgi as base_wsgi

from cinder.api.openstack import api_version_request
from cinder.api.openstack import wsgi
from cinder.api.views import versions as views_versions

CONF = cfg.CONF

_LINKS = [{
    "rel": "describedby",
    "type": "text/html",
    "href": "https://docs.openstack.org/",
}]
_KNOWN_VERSIONS = {
    "v3.0": {
        "id": "v3.0",
        "status": "CURRENT",
        "version": api_version_request._MAX_API_VERSION,
        "min_version": api_version_request._MIN_API_VERSION,
        "updated": api_version_request.UPDATED,
        "links": _LINKS,
        "media-types": [{
            "base": "application/json",
            "type": "application/vnd.openstack.volume+json;version=3",
        }]
    },
}


class Versions(base_wsgi.Router):
    """Route versions requests."""

    def __init__(self):
        mapper = wsgi.APIMapper()
        controller = create_resource()
        mapper.connect('versions', '/', controller=controller, action='all')
        mapper.redirect('', '/')
        super().__init__(mapper)

    @classmethod
    def factory(cls, global_config, **local_config):
        """Simple paste factory.

        :class:`oslo_service.wsgi.Router` doesn't have this.
        """
        return cls()


class VersionsController(wsgi.Controller):

    def __init__(self):
        super(VersionsController, self).__init__(None)

    @wsgi.Controller.api_version('3.0')
    def index(self, req):  # pylint: disable=E0102
        """Return versions supported after the start of microversions."""
        builder = views_versions.get_view_builder(req)
        known_versions = copy.deepcopy(_KNOWN_VERSIONS)
        return builder.build_versions(known_versions)

    # NOTE (cknight): Calling the versions API without
    # /v3 in the URL will lead to this unversioned
    # method, which should always return info about all
    # available versions.
    @wsgi.response(HTTPStatus.MULTIPLE_CHOICES)
    def all(self, req):
        """Return all known and enabled versions."""
        builder = views_versions.get_view_builder(req)
        known_versions = copy.deepcopy(_KNOWN_VERSIONS)

        return builder.build_versions(known_versions)


def create_resource():
    return wsgi.Resource(VersionsController())
