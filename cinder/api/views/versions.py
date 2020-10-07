# Copyright 2010-2011 OpenStack Foundation
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
import re
import urllib

from oslo_config import cfg


versions_opts = [
    cfg.StrOpt('public_endpoint',
               help="Public url to use for versions endpoint. The default "
                    "is None, which will use the request's host_url "
                    "attribute to populate the URL base. If Cinder is "
                    "operating behind a proxy, you will want to change "
                    "this to represent the proxy's URL."),
]

CONF = cfg.CONF
CONF.register_opts(versions_opts)


def get_view_builder(req):
    base_url = CONF.public_endpoint or req.application_url
    return ViewBuilder(base_url)


class ViewBuilder(object):
    def __init__(self, base_url):
        """Initialize ViewBuilder.

        :param base_url: url of the root wsgi application
        """
        self.base_url = base_url

    def build_versions(self, versions):
        views = [self._build_version(versions[key])
                 for key in sorted(list(versions.keys()))]
        return dict(versions=views)

    def _build_version(self, version):
        view = copy.deepcopy(version)
        view['links'] = self._build_links(version)
        return view

    def _build_links(self, version_data):
        """Generate a container of links that refer to the provided version."""
        links = copy.deepcopy(version_data.get('links', {}))
        version_num = version_data["id"].split('.')[0]
        links.append({'rel': 'self',
                      'href': self._generate_href(version=version_num)})
        return links

    def _generate_href(self, version='v3', path=None):
        """Create a URL that refers to a specific version_number."""
        base_url = self._get_base_url_without_version()
        # Always add '/' to base_url end for urljoin href url
        base_url = base_url.rstrip('/') + '/'
        rel_version = version.lstrip('/')
        href = urllib.parse.urljoin(base_url, rel_version).rstrip('/') + '/'
        if path:
            href += path.lstrip('/')
        return href

    def _get_base_url_without_version(self):
        """Get the base URL with out the /v3 suffix."""
        return re.sub('v[1-9]+/?$', '', self.base_url)
