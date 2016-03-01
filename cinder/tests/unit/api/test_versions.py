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

import ddt
import mock
from oslo_serialization import jsonutils

from cinder.api.openstack import api_version_request
from cinder.api.openstack import wsgi
from cinder.api.v1 import router
from cinder.api import versions
from cinder import exception
from cinder import test
from cinder.tests.unit.api import fakes


VERSION_HEADER_NAME = 'OpenStack-API-Version'
VOLUME_SERVICE = 'volume '


@ddt.ddt
class VersionsControllerTestCase(test.TestCase):

    def setUp(self):
        super(VersionsControllerTestCase, self).setUp()
        self.wsgi_apps = (versions.Versions(), router.APIRouter())

    def build_request(self, base_url='http://localhost/v3',
                      header_version=None):
        req = fakes.HTTPRequest.blank('/', base_url=base_url)
        req.method = 'GET'
        req.content_type = 'application/json'
        if header_version:
            req.headers = {VERSION_HEADER_NAME: VOLUME_SERVICE +
                           header_version}

        return req

    def check_response(self, response, version):
        self.assertEqual(VOLUME_SERVICE + version,
                         response.headers[VERSION_HEADER_NAME])
        self.assertEqual(VOLUME_SERVICE + version,
                         response.headers[VERSION_HEADER_NAME])
        self.assertEqual(VERSION_HEADER_NAME, response.headers['Vary'])

    @ddt.data('1.0', '2.0', '3.0')
    def test_versions_root(self, version):
        req = self.build_request(base_url='http://localhost')

        response = req.get_response(versions.Versions())
        self.assertEqual(300, response.status_int)
        body = jsonutils.loads(response.body)
        version_list = body['versions']

        ids = [v['id'] for v in version_list]
        self.assertEqual({'v1.0', 'v2.0', 'v3.0'}, set(ids))

        v1 = [v for v in version_list if v['id'] == 'v1.0'][0]
        self.assertEqual('', v1.get('min_version'))
        self.assertEqual('', v1.get('version'))

        v2 = [v for v in version_list if v['id'] == 'v2.0'][0]
        self.assertEqual('', v2.get('min_version'))
        self.assertEqual('', v2.get('version'))

        v3 = [v for v in version_list if v['id'] == 'v3.0'][0]
        self.assertEqual(api_version_request._MAX_API_VERSION,
                         v3.get('version'))
        self.assertEqual(api_version_request._MIN_API_VERSION,
                         v3.get('min_version'))

    def test_versions_v1_no_header(self):
        req = self.build_request(base_url='http://localhost/v1')

        response = req.get_response(router.APIRouter())
        self.assertEqual(200, response.status_int)

    def test_versions_v2_no_header(self):
        req = self.build_request(base_url='http://localhost/v2')

        response = req.get_response(router.APIRouter())
        self.assertEqual(200, response.status_int)

    @ddt.data('1.0')
    def test_versions_v1(self, version):
        req = self.build_request(base_url='http://localhost/v1',
                                 header_version=version)
        if version is not None:
            req.headers = {VERSION_HEADER_NAME: VOLUME_SERVICE + version}

        response = req.get_response(router.APIRouter())
        self.assertEqual(200, response.status_int)
        body = jsonutils.loads(response.body)
        version_list = body['versions']

        ids = [v['id'] for v in version_list]
        self.assertEqual({'v1.0'}, set(ids))

        self.check_response(response, version)

        self.assertEqual('', version_list[0].get('min_version'))
        self.assertEqual('', version_list[0].get('version'))

    @ddt.data('2.0')
    def test_versions_v2(self, version):
        req = self.build_request(base_url='http://localhost/v2',
                                 header_version=version)

        response = req.get_response(router.APIRouter())
        self.assertEqual(200, response.status_int)
        body = jsonutils.loads(response.body)
        version_list = body['versions']

        ids = [v['id'] for v in version_list]
        self.assertEqual({'v2.0'}, set(ids))

        self.check_response(response, version)

        self.assertEqual('', version_list[0].get('min_version'))
        self.assertEqual('', version_list[0].get('version'))

    @ddt.data('3.0', 'latest')
    def test_versions_v3_0_and_latest(self, version):
        req = self.build_request(header_version=version)

        response = req.get_response(router.APIRouter())
        self.assertEqual(200, response.status_int)
        body = jsonutils.loads(response.body)
        version_list = body['versions']

        ids = [v['id'] for v in version_list]
        self.assertEqual({'v3.0'}, set(ids))
        self.check_response(response, '3.0')

        self.assertEqual(api_version_request._MAX_API_VERSION,
                         version_list[0].get('version'))
        self.assertEqual(api_version_request._MIN_API_VERSION,
                         version_list[0].get('min_version'))

    def test_versions_version_latest(self):
        req = self.build_request(header_version='latest')

        response = req.get_response(router.APIRouter())

        self.assertEqual(200, response.status_int)

    def test_versions_version_invalid(self):
        req = self.build_request(header_version='2.0.1')

        for app in self.wsgi_apps:
            response = req.get_response(app)

            self.assertEqual(400, response.status_int)

    def test_versions_version_not_found(self):
        api_version_request_4_0 = api_version_request.APIVersionRequest('4.0')
        self.mock_object(api_version_request,
                         'max_api_version',
                         mock.Mock(return_value=api_version_request_4_0))

        class Controller(wsgi.Controller):

            @wsgi.Controller.api_version('3.0', '3.0')
            def index(self, req):
                return 'off'

        req = self.build_request(header_version='3.5')
        app = fakes.TestRouter(Controller())

        response = req.get_response(app)

        self.assertEqual(404, response.status_int)

    def test_versions_version_not_acceptable(self):
        req = self.build_request(header_version='4.0')

        response = req.get_response(router.APIRouter())

        self.assertEqual(406, response.status_int)
        self.assertEqual('4.0', response.headers[VERSION_HEADER_NAME])
        self.assertEqual(VERSION_HEADER_NAME, response.headers['Vary'])

    @ddt.data(['volume 3.0, compute 2.22', True],
              ['volume 3.0, compute 2.22, identity 2.3', True],
              ['compute 2.22, identity 2.3', False])
    @ddt.unpack
    def test_versions_multiple_services_header(
            self, service_list, should_pass):
        req = self.build_request()
        req.headers = {VERSION_HEADER_NAME: service_list}

        try:
            response = req.get_response(router.APIRouter())
        except exception.VersionNotFoundForAPIMethod:
            if should_pass:
                raise
            elif not should_pass:
                return

        self.assertEqual(200, response.status_int)
        body = jsonutils.loads(response.body)
        version_list = body['versions']

        ids = [v['id'] for v in version_list]
        self.assertEqual({'v3.0'}, set(ids))
        self.check_response(response, '3.0')

        self.assertEqual(api_version_request._MAX_API_VERSION,
                         version_list[0].get('version'))
        self.assertEqual(api_version_request._MIN_API_VERSION,
                         version_list[0].get('min_version'))
