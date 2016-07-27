#   Copyright (c) 2016 Stratoscale, Ltd.
#
#   Licensed under the Apache License, Version 2.0 (the "License"); you may
#   not use this file except in compliance with the License. You may obtain
#   a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#   WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#   License for the specific language governing permissions and limitations
#   under the License.

from cinder.api.contrib import volume_manage as volume_manage_v2
from cinder.api.openstack import wsgi
from cinder import exception


class VolumeManageController(volume_manage_v2.VolumeManageController):
    def _ensure_min_version(self, req, allowed_version):
        version = req.api_version_request
        if not version.matches(allowed_version, None):
            raise exception.VersionNotFoundForAPIMethod(version=version)

    @wsgi.response(202)
    def create(self, req, body):
        self._ensure_min_version(req, "3.8")
        return super(VolumeManageController, self).create(req, body)

    @wsgi.extends
    def index(self, req):
        """Returns a summary list of volumes available to manage."""
        self._ensure_min_version(req, "3.8")
        return super(VolumeManageController, self).index(req)

    @wsgi.extends
    def detail(self, req):
        """Returns a detailed list of volumes available to manage."""
        self._ensure_min_version(req, "3.8")
        return super(VolumeManageController, self).detail(req)


def create_resource():
    return wsgi.Resource(VolumeManageController())
