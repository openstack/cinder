# Copyright (c) 2016 Red Hat, Inc.
# All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License"); you may
#  not use this file except in compliance with the License. You may obtain
#  a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#  WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#  License for the specific language governing permissions and limitations
#  under the License.

from cinder.api import common
from cinder.api import extensions
from cinder.api.openstack import wsgi
from cinder import exception
from cinder.i18n import _


class ManageResource(object):
    """Mixin class for v3 of ManageVolume and ManageSnapshot.

    It requires that any class inheriting from this one has `volume_api` and
    `_list_manageable_view` attributes.
    """
    VALID_SORT_KEYS = {'reference', 'size'}
    VALID_SORT_DIRS = {'asc', 'desc'}

    def _set_resource_type(self, resource):
        self._authorizer = extensions.extension_authorizer(resource,
                                                           'list_manageable')
        self.get_manageable = getattr(self.volume_api,
                                      'get_manageable_%ss' % resource)

    def _ensure_min_version(self, req, allowed_version):
        version = req.api_version_request
        if not version.matches(allowed_version, None):
            raise exception.VersionNotFoundForAPIMethod(version=version)

    def _get_resources(self, req, is_detail):
        self._ensure_min_version(req, '3.8')

        context = req.environ['cinder.context']
        self._authorizer(context)

        params = req.params.copy()
        cluster_name, host = common.get_cluster_host(req, params, '3.17')
        marker, limit, offset = common.get_pagination_params(params)
        sort_keys, sort_dirs = common.get_sort_params(params,
                                                      default_key='reference')

        # These parameters are generally validated at the DB layer, but in this
        # case sorting is not done by the DB
        invalid_keys = set(sort_keys).difference(self.VALID_SORT_KEYS)
        if invalid_keys:
            msg = _("Invalid sort keys passed: %s") % ', '.join(invalid_keys)
            raise exception.InvalidParameterValue(err=msg)

        invalid_dirs = set(sort_dirs).difference(self.VALID_SORT_DIRS)
        if invalid_dirs:
            msg = _("Invalid sort dirs passed: %s") % ', '.join(invalid_dirs)
            raise exception.InvalidParameterValue(err=msg)

        resources = self.get_manageable(context, host, cluster_name,
                                        marker=marker, limit=limit,
                                        offset=offset, sort_keys=sort_keys,
                                        sort_dirs=sort_dirs)
        view_builder = getattr(self._list_manageable_view,
                               'detail_list' if is_detail else 'summary_list')
        return view_builder(req, resources, len(resources))

    @wsgi.extends
    def index(self, req):
        """Returns a summary list of volumes available to manage."""
        return self._get_resources(req, False)

    @wsgi.extends
    def detail(self, req):
        """Returns a detailed list of volumes available to manage."""
        return self._get_resources(req, True)
