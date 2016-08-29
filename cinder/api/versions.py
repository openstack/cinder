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

from cinder.api import extensions
from cinder.api import openstack
from cinder.api.openstack import api_version_request
from cinder.api.openstack import wsgi
from cinder.api.views import versions as views_versions


_LINKS = [{
    "rel": "describedby",
    "type": "text/html",
    "href": "http://docs.openstack.org/",
}]

_MEDIA_TYPES = [{
    "base":
    "application/json",
    "type":
    "application/vnd.openstack.volume+json;version=1",
},
]

_KNOWN_VERSIONS = {
    "v1.0": {
        "id": "v1.0",
        "status": "DEPRECATED",
        "version": "",
        "min_version": "",
        "updated": "2016-05-02T20:25:19Z",
        "links": _LINKS,
        "media-types": _MEDIA_TYPES,
    },
    "v2.0": {
        "id": "v2.0",
        "status": "SUPPORTED",
        "version": "",
        "min_version": "",
        "updated": "2014-06-28T12:20:21Z",
        "links": _LINKS,
        "media-types": _MEDIA_TYPES,
    },
    "v3.0": {
        "id": "v3.0",
        "status": "CURRENT",
        "version": api_version_request._MAX_API_VERSION,
        "min_version": api_version_request._MIN_API_VERSION,
        "updated": "2016-02-08T12:20:21Z",
        "links": _LINKS,
        "media-types": _MEDIA_TYPES,
    },
}


class Versions(openstack.APIRouter):
    """Route versions requests."""

    ExtensionManager = extensions.ExtensionManager

    def _setup_routes(self, mapper, ext_mgr):
        self.resources['versions'] = create_resource()
        mapper.connect('versions', '/',
                       controller=self.resources['versions'],
                       action='all')
        mapper.redirect('', '/')


class VersionsController(wsgi.Controller):

    def __init__(self):
        super(VersionsController, self).__init__(None)

    @wsgi.Controller.api_version('1.0')
    def index(self, req):  # pylint: disable=E0102
        """Return versions supported prior to the microversions epoch."""
        builder = views_versions.get_view_builder(req)
        known_versions = copy.deepcopy(_KNOWN_VERSIONS)
        known_versions.pop('v2.0')
        known_versions.pop('v3.0')
        return builder.build_versions(known_versions)

    @index.api_version('2.0')
    def index(self, req):  # pylint: disable=E0102
        """Return versions supported prior to the microversions epoch."""
        builder = views_versions.get_view_builder(req)
        known_versions = copy.deepcopy(_KNOWN_VERSIONS)
        known_versions.pop('v1.0')
        known_versions.pop('v3.0')
        return builder.build_versions(known_versions)

    @index.api_version('3.0')
    def index(self, req):  # pylint: disable=E0102
        """Return versions supported after the start of microversions."""
        builder = views_versions.get_view_builder(req)
        known_versions = copy.deepcopy(_KNOWN_VERSIONS)
        known_versions.pop('v1.0')
        known_versions.pop('v2.0')
        return builder.build_versions(known_versions)

    # NOTE (cknight): Calling the versions API without
    # /v1, /v2, or /v3 in the URL will lead to this unversioned
    # method, which should always return info about all
    # available versions.
    @wsgi.response(300)
    def all(self, req):
        """Return all known versions."""
        builder = views_versions.get_view_builder(req)
        known_versions = copy.deepcopy(_KNOWN_VERSIONS)
        return builder.build_versions(known_versions)


def create_resource():
    return wsgi.Resource(VersionsController())
