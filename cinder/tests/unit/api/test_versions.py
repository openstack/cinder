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
from http import HTTPStatus

import ddt
from oslo_config import cfg
from oslo_serialization import jsonutils
from oslo_utils import encodeutils
import webob

from cinder.api.openstack import api_version_request
from cinder.api.openstack import wsgi
from cinder.api.v3 import router
from cinder.api import versions
from cinder import exception
from cinder.tests.unit.api import fakes
from cinder.tests.unit import test


CONF = cfg.CONF
VERSION_HEADER_NAME = 'OpenStack-API-Version'
VOLUME_SERVICE = 'volume '


@ddt.ddt
class VersionsControllerTestCase(test.TestCase):

    def setUp(self):
        super(VersionsControllerTestCase, self).setUp()
        self.wsgi_apps = (versions.Versions(), router.APIRouter())

    def build_request(self, base_dir=None, base_url='http://localhost/v3',
                      header_version=None):
        if base_dir:
            req = fakes.HTTPRequest.blank(base_dir, base_url=base_url)
        else:
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
        self.assertEqual(VERSION_HEADER_NAME, response.headers['Vary'])

    def test_versions_root(self):
        req = self.build_request(base_url='http://localhost')

        response = req.get_response(versions.Versions())
        self.assertEqual(HTTPStatus.MULTIPLE_CHOICES, response.status_int)
        body = jsonutils.loads(response.body)
        version_list = body['versions']

        ids = [v['id'] for v in version_list]
        self.assertEqual(1, len(ids))
        self.assertIn('v3.0', ids)

        v3 = [v for v in version_list if v['id'] == 'v3.0'][0]
        self.assertEqual(api_version_request._MAX_API_VERSION,
                         v3.get('version'))
        self.assertEqual(api_version_request._MIN_API_VERSION,
                         v3.get('min_version'))

    def test_versions(self):
        version = '3.0'
        req = self.build_request(
            base_url='http://localhost/v{}'.format(version[0]),
            header_version=version)

        response = req.get_response(router.APIRouter())
        self.assertEqual(HTTPStatus.OK, response.status_int)
        body = jsonutils.loads(response.body)
        version_list = body['versions']

        ids = [v['id'] for v in version_list]
        self.assertEqual(1, len(ids))
        self.assertIn('v{}'.format(version), ids)

        self.check_response(response, version)
        self.assertEqual(api_version_request._MAX_API_VERSION,
                         version_list[0].get('version'))
        self.assertEqual(api_version_request._MIN_API_VERSION,
                         version_list[0].get('min_version'))

    def test_versions_version_latest(self):
        req = self.build_request(header_version='latest')

        response = req.get_response(router.APIRouter())

        self.assertEqual(HTTPStatus.OK, response.status_int)
        self.check_response(response, api_version_request._MAX_API_VERSION)

    def test_versions_version_invalid(self):
        req = self.build_request(header_version='2.0.1')

        for app in self.wsgi_apps:
            response = req.get_response(app)

            self.assertEqual(HTTPStatus.BAD_REQUEST, response.status_int)

    def test_versions_response_fault(self):
        version = '3.0'
        req = self.build_request(header_version=version)
        req.api_version_request = (
            api_version_request.APIVersionRequest(version))

        app = wsgi.Fault(webob.exc.HTTPBadRequest(explanation='what?'))
        response = req.get_response(app)

        self.assertEqual(HTTPStatus.BAD_REQUEST, response.status_int)
        self.check_response(response, '3.0')

    def test_versions_inheritance_internals_of_non_base_controller(self):
        """Test ControllerMetaclass works inheriting from non base class."""
        def _get_str_version(version):
            return "%s.%s" % (version._ver_major, version._ver_minor)

        def assert_method_equal(expected, observed):
            self.assertEqual(expected, observed)

        class ControllerParent(wsgi.Controller):
            @wsgi.Controller.api_version('3.0')
            def index(self, req):
                pass

        # We create this class in between to confirm that we don't leave
        # undesired versioned methods in the wsgi.Controller class.
        class Controller(wsgi.Controller):
            @wsgi.Controller.api_version('2.0')
            def index(self, req):
                pass

        class ControllerChild(ControllerParent):
            @wsgi.Controller.api_version('3.1')
            def index(self, req):
                pass

            @wsgi.Controller.api_version('3.2')
            def new_method(self, req):
                pass

        # ControllerParent will only have its own index method
        self.assertSetEqual({'index'}, set(ControllerParent.versioned_methods))
        self.assertEqual(1, len(ControllerParent.versioned_methods['index']))
        index = ControllerParent.versioned_methods['index'][0]
        assert_method_equal(ControllerParent.index, index.func)
        self.assertEqual('index', index.name)
        self.assertEqual('3.0', _get_str_version(index.start_version))
        self.assertEqual('None.None', _get_str_version(index.end_version))

        # Same thing will happen with the Controller class, thus confirming
        # that we don't cross pollinate our classes with undesired methods.
        self.assertSetEqual({'index'}, set(Controller.versioned_methods))
        self.assertEqual(1, len(Controller.versioned_methods['index']))
        index = Controller.versioned_methods['index'][0]
        assert_method_equal(Controller.index, index.func)
        self.assertEqual('index', index.name)
        self.assertEqual('2.0', _get_str_version(index.start_version))
        self.assertEqual('None.None', _get_str_version(index.end_version))

        # ControllerChild will inherit index method from ControllerParent and
        # add its own version as well as add a new method
        self.assertSetEqual({'index', 'new_method'},
                            set(ControllerChild.versioned_methods))
        self.assertEqual(2, len(ControllerChild.versioned_methods['index']))

        # The methods are ordered from newest version to oldest version
        index = ControllerChild.versioned_methods['index'][0]
        assert_method_equal(ControllerChild.index, index.func)
        self.assertEqual('index', index.name)
        self.assertEqual('3.1', _get_str_version(index.start_version))
        self.assertEqual('None.None', _get_str_version(index.end_version))

        index = ControllerChild.versioned_methods['index'][1]
        assert_method_equal(ControllerParent.index, index.func)
        self.assertEqual('index', index.name)
        self.assertEqual('3.0', _get_str_version(index.start_version))
        self.assertEqual('None.None', _get_str_version(index.end_version))

        # New method also gets added even if it didn't exist in any of the base
        # classes.
        self.assertEqual(1,
                         len(ControllerChild.versioned_methods['new_method']))
        new_method = ControllerChild.versioned_methods['new_method'][0]
        assert_method_equal(ControllerChild.new_method, new_method.func)
        self.assertEqual('new_method', new_method.name)
        self.assertEqual('3.2', _get_str_version(new_method.start_version))
        self.assertEqual('None.None', _get_str_version(new_method.end_version))

    @ddt.data(
        ('2.0', 'index', HTTPStatus.NOT_ACCEPTABLE, 'ControllerParent'),
        ('2.0', 'show', HTTPStatus.NOT_ACCEPTABLE, 'ControllerParent'),
        ('3.0', 'index', HTTPStatus.NOT_FOUND, 'ControllerParent'),
        ('3.0', 'show', HTTPStatus.NOT_FOUND, 'ControllerParent'),
        ('3.1', 'index', 'parent', 'ControllerParent'),
        ('3.1', 'show', HTTPStatus.NOT_FOUND, 'ControllerParent'),
        ('3.2', 'index', 'parent', 'ControllerParent'),
        ('3.2', 'show', HTTPStatus.NOT_FOUND, 'ControllerParent'),

        ('2.0', 'index', HTTPStatus.NOT_ACCEPTABLE, 'Controller'),
        ('2.0', 'show', HTTPStatus.NOT_ACCEPTABLE, 'Controller'),
        ('3.0', 'index', HTTPStatus.NOT_FOUND, 'Controller'),
        ('3.0', 'show', HTTPStatus.NOT_FOUND, 'Controller'),
        ('3.1', 'index', 'single', 'Controller'),
        ('3.1', 'show', HTTPStatus.NOT_FOUND, 'Controller'),
        ('3.2', 'index', 'single', 'Controller'),
        ('3.2', 'show', HTTPStatus.NOT_FOUND, 'Controller'),

        ('2.0', 'index', HTTPStatus.NOT_ACCEPTABLE, 'ControllerChild'),
        ('2.0', 'show', HTTPStatus.NOT_ACCEPTABLE, 'ControllerChild'),
        ('3.0', 'index', HTTPStatus.NOT_FOUND, 'ControllerChild'),
        ('3.0', 'show', HTTPStatus.NOT_FOUND, 'ControllerChild'),
        ('3.1', 'index', 'parent', 'ControllerChild'),
        ('3.1', 'show', HTTPStatus.NOT_FOUND, 'ControllerChild'),
        ('3.2', 'index', 'child 3.2', 'ControllerChild'),
        ('3.2', 'show', HTTPStatus.NOT_FOUND, 'ControllerChild'),
        ('3.3', 'index', 'child 3.3', 'ControllerChild'),
        ('3.3', 'show', 'show', 'ControllerChild'),
        ('3.4', 'index', 'child 3.4', 'ControllerChild'))
    @ddt.unpack
    def test_versions_inheritance_of_non_base_controller(self, version, call,
                                                         expected, controller):
        """Test ControllerMetaclass works inheriting from non base class."""
        class ControllerParent(wsgi.Controller):
            @wsgi.Controller.api_version('3.1')
            def index(self, req):
                return 'parent'

        # We create this class in between to confirm that we don't leave
        # undesired versioned methods in the wsgi.Controller class.
        class Controller(wsgi.Controller):
            @wsgi.Controller.api_version('3.1')
            def index(self, req):
                return 'single'

        class ControllerChild(ControllerParent):
            # We don't add max version to confirm that once we set a newer
            # version it doesn't really matter because the newest one will be
            # called.
            @wsgi.Controller.api_version('3.2')
            def index(self, req):
                return 'child 3.2'

            @index.api_version('3.3')
            def index(self, req):
                return 'child 3.3'

            @index.api_version('3.4')
            def index(self, req):
                return 'child 3.4'

            @wsgi.Controller.api_version('3.3')
            def show(self, req, *args, **kwargs):
                return 'show'

        base_dir = '/tests' if call == 'index' else '/tests/123'
        req = self.build_request(base_dir=base_dir, header_version=version)
        app = fakes.TestRouter(locals()[controller]())

        response = req.get_response(app)
        resp = encodeutils.safe_decode(response.body, incoming='utf-8')

        if isinstance(expected, str):
            self.assertEqual(HTTPStatus.OK, response.status_int)
            self.assertEqual(expected, resp)
        else:
            self.assertEqual(expected, response.status_int)

    def test_versions_version_not_found(self):
        api_version_request_4_0 = api_version_request.APIVersionRequest('4.0')
        self.mock_object(api_version_request,
                         'max_api_version',
                         return_value=api_version_request_4_0)

        class Controller(wsgi.Controller):

            @wsgi.Controller.api_version('3.0', '3.0')
            def index(self, req):
                return 'off'

        req = self.build_request(header_version='3.5')
        app = fakes.TestRouter(Controller())

        response = req.get_response(app)

        self.assertEqual(HTTPStatus.NOT_FOUND, response.status_int)

    def test_versions_version_not_acceptable(self):
        req = self.build_request(header_version='4.0')

        response = req.get_response(router.APIRouter())

        self.assertEqual(HTTPStatus.NOT_ACCEPTABLE, response.status_int)

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

        self.assertEqual(HTTPStatus.OK, response.status_int)
        body = jsonutils.loads(response.body)
        version_list = body['versions']

        ids = [v['id'] for v in version_list]
        self.assertEqual({'v3.0'}, set(ids))
        self.check_response(response, '3.0')

        self.assertEqual(api_version_request._MAX_API_VERSION,
                         version_list[0].get('version'))
        self.assertEqual(api_version_request._MIN_API_VERSION,
                         version_list[0].get('min_version'))

    @ddt.data(['3.5', HTTPStatus.OK], ['3.55', HTTPStatus.NOT_FOUND])
    @ddt.unpack
    def test_req_version_matches(self, version, HTTP_ret):
        version_request = api_version_request.APIVersionRequest(version)
        self.mock_object(api_version_request,
                         'max_api_version',
                         return_value=version_request)

        class Controller(wsgi.Controller):

            @wsgi.Controller.api_version('3.0', '3.6')
            def index(self, req):
                return 'off'

        req = self.build_request(base_dir='/tests', header_version=version)
        app = fakes.TestRouter(Controller())

        response = req.get_response(app)
        resp = encodeutils.safe_decode(response.body, incoming='utf-8')

        if HTTP_ret == HTTPStatus.OK:
            self.assertEqual('off', resp)
        elif HTTP_ret == HTTPStatus.NOT_FOUND:
            self.assertNotEqual('off', resp)
        self.assertEqual(HTTP_ret, response.status_int)

    @ddt.data(['3.5', 'older'], ['3.37', 'newer'])
    @ddt.unpack
    def test_req_version_matches_with_if(self, version, ret_val):
        version_request = api_version_request.APIVersionRequest(version)
        self.mock_object(api_version_request,
                         'max_api_version',
                         return_value=version_request)

        class Controller(wsgi.Controller):

            def index(self, req):
                req_version = req.api_version_request
                if req_version.matches('3.1', '3.8'):
                    return 'older'
                if req_version.matches('3.9', '8.8'):
                    return 'newer'

        req = self.build_request(base_dir='/tests', header_version=version)
        app = fakes.TestRouter(Controller())

        response = req.get_response(app)

        resp = encodeutils.safe_decode(response.body, incoming='utf-8')
        self.assertEqual(ret_val, resp)
        self.assertEqual(HTTPStatus.OK, response.status_int)

    @ddt.data(['3.5', 'older'], ['3.37', 'newer'])
    @ddt.unpack
    def test_req_version_matches_with_None(self, version, ret_val):
        version_request = api_version_request.APIVersionRequest(version)
        self.mock_object(api_version_request,
                         'max_api_version',
                         return_value=version_request)

        class Controller(wsgi.Controller):

            def index(self, req):
                req_version = req.api_version_request
                if req_version.matches(None, '3.8'):
                    return 'older'
                if req_version.matches('3.9', None):
                    return 'newer'

        req = self.build_request(base_dir='/tests', header_version=version)
        app = fakes.TestRouter(Controller())

        response = req.get_response(app)

        resp = encodeutils.safe_decode(response.body, incoming='utf-8')
        self.assertEqual(ret_val, resp)
        self.assertEqual(HTTPStatus.OK, response.status_int)

    def test_req_version_matches_with_None_None(self):
        version_request = api_version_request.APIVersionRequest('3.39')
        self.mock_object(api_version_request,
                         'max_api_version',
                         return_value=version_request)

        class Controller(wsgi.Controller):

            def index(self, req):
                req_version = req.api_version_request
                # This case is artificial, and will return True
                if req_version.matches(None, None):
                    return "Pass"

        req = self.build_request(base_dir='/tests', header_version='3.39')
        app = fakes.TestRouter(Controller())

        response = req.get_response(app)

        resp = encodeutils.safe_decode(response.body, incoming='utf-8')
        self.assertEqual("Pass", resp)
        self.assertEqual(HTTPStatus.OK, response.status_int)
