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

import ddt

from cinder.api.views import versions
from cinder.tests.unit import test


class FakeRequest(object):
    def __init__(self, application_url):
        self.application_url = application_url


URL_BASE = 'http://localhost/volume/'
URL_BASE_NO_SLASH = 'http://localhost/volume'
FAKE_HREF = URL_BASE + 'v1/'

FAKE_VERSIONS = {
    "v1.0": {
        "id": "v1.0",
        "status": "CURRENT",
        "version": "1.1",
        "min_version": "1.0",
        "updated": "2015-07-30T11:33:21Z",
        "links": [
            {
                "rel": "describedby",
                "type": "text/html",
                "href": 'http://docs.openstack.org/',
            },
        ],
        "media-types": [
            {
                "base": "application/json",
                "type": "application/vnd.openstack.share+json;version=1",
            }
        ],
    },
}

FAKE_LINKS = [
    {
        "rel": "describedby",
        "type": "text/html",
        "href": 'http://docs.openstack.org/',
    },
    {
        'rel': 'self',
        'href': FAKE_HREF
    },
]


@ddt.ddt
class ViewBuilderTestCase(test.TestCase):

    def _get_builder(self):
        request = FakeRequest(URL_BASE)
        return versions.get_view_builder(request)

    def _get_builder_no_slash(self):
        request = FakeRequest(URL_BASE_NO_SLASH)
        return versions.get_view_builder(request)

    def test_build_versions(self):

        self.mock_object(versions.ViewBuilder,
                         '_build_links',
                         return_value=FAKE_LINKS)

        result = self._get_builder().build_versions(FAKE_VERSIONS)
        result_no_slash = self._get_builder_no_slash().build_versions(
            FAKE_VERSIONS)

        expected = {'versions': list(FAKE_VERSIONS.values())}
        expected['versions'][0]['links'] = FAKE_LINKS

        self.assertEqual(expected, result)
        self.assertEqual(expected, result_no_slash)

    def test_build_version(self):

        self.mock_object(versions.ViewBuilder,
                         '_build_links',
                         return_value=FAKE_LINKS)

        result = self._get_builder()._build_version(FAKE_VERSIONS['v1.0'])
        result_no_slash = self._get_builder_no_slash()._build_version(
            FAKE_VERSIONS['v1.0'])

        expected = copy.deepcopy(FAKE_VERSIONS['v1.0'])
        expected['links'] = FAKE_LINKS

        self.assertEqual(expected, result)
        self.assertEqual(expected, result_no_slash)

    def test_build_links(self):

        self.mock_object(versions.ViewBuilder,
                         '_generate_href',
                         return_value=FAKE_HREF)

        result = self._get_builder()._build_links(FAKE_VERSIONS['v1.0'])
        result_no_slash = self._get_builder_no_slash()._build_links(
            FAKE_VERSIONS['v1.0'])

        self.assertEqual(FAKE_LINKS, result)
        self.assertEqual(FAKE_LINKS, result_no_slash)

    def test_generate_href_defaults(self):

        result = self._get_builder()._generate_href()
        result_no_slash = self._get_builder_no_slash()._generate_href()

        self.assertEqual(URL_BASE + 'v3/', result)
        self.assertEqual(URL_BASE + 'v3/', result_no_slash)

    @ddt.data(
        ('v2', None, URL_BASE + 'v2/'),
        ('/v2/', None, URL_BASE + 'v2/'),
        ('/v2/', 'fake_path', URL_BASE + 'v2/fake_path'),
        ('/v2/', '/fake_path/', URL_BASE + 'v2/fake_path/'),
    )
    @ddt.unpack
    def test_generate_href_no_path(self, version, path, expected):

        result = self._get_builder()._generate_href(version=version,
                                                    path=path)
        result_no_slash = self._get_builder_no_slash()._generate_href(
            version=version, path=path)

        self.assertEqual(expected, result)
        self.assertEqual(expected, result_no_slash)

    @ddt.data(
        ('http://1.1.1.1/', 'http://1.1.1.1/'),
        ('http://localhost/', 'http://localhost/'),
        ('http://localhost/volume/', 'http://localhost/volume/'),
        ('http://1.1.1.1/v1/', 'http://1.1.1.1/'),
        ('http://1.1.1.1/volume/v1/', 'http://1.1.1.1/volume/'),
        ('http://1.1.1.1/v1', 'http://1.1.1.1/'),
        ('http://1.1.1.1/v11', 'http://1.1.1.1/'),
    )
    @ddt.unpack
    def test_get_base_url_without_version(self, base_url, base_url_no_version):

        request = FakeRequest(base_url)
        builder = versions.get_view_builder(request)

        result = builder._get_base_url_without_version()

        self.assertEqual(base_url_no_version, result)
