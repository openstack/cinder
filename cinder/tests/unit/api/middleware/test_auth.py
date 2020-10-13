# Copyright (c) 2012 OpenStack Foundation
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

from oslo_middleware import request_id
import webob

import cinder.api.middleware.auth
from cinder.tests.unit import test


class TestCinderKeystoneContextMiddleware(test.TestCase):

    def setUp(self):
        super(TestCinderKeystoneContextMiddleware, self).setUp()

        @webob.dec.wsgify()
        def fake_app(req):
            self.context = req.environ['cinder.context']
            return webob.Response()

        self.context = None
        self.middleware = (cinder.api.middleware.auth
                           .CinderKeystoneContext(fake_app))
        self.request = webob.Request.blank('/')
        self.request.headers['X_TENANT_ID'] = 'testtenantid'
        self.request.headers['X_AUTH_TOKEN'] = 'testauthtoken'

    def test_no_user_or_user_id(self):
        response = self.request.get_response(self.middleware)
        self.assertEqual(HTTPStatus.UNAUTHORIZED, response.status_int)

    def test_user_only(self):
        self.request.headers['X_USER'] = 'testuser'
        response = self.request.get_response(self.middleware)
        self.assertEqual(HTTPStatus.OK, response.status_int)
        self.assertEqual('testuser', self.context.user_id)

    def test_user_id_only(self):
        self.request.headers['X_USER_ID'] = 'testuserid'
        response = self.request.get_response(self.middleware)
        self.assertEqual(HTTPStatus.OK, response.status_int)
        self.assertEqual('testuserid', self.context.user_id)

    def test_user_id_trumps_user(self):
        self.request.headers['X_USER_ID'] = 'testuserid'
        self.request.headers['X_USER'] = 'testuser'
        response = self.request.get_response(self.middleware)
        self.assertEqual(HTTPStatus.OK, response.status_int)
        self.assertEqual('testuserid', self.context.user_id)

    def test_tenant_id_name(self):
        self.request.headers['X_USER_ID'] = 'testuserid'
        self.request.headers['X_TENANT_NAME'] = 'testtenantname'
        response = self.request.get_response(self.middleware)
        self.assertEqual(HTTPStatus.OK, response.status_int)
        self.assertEqual('testtenantid', self.context.project_id)
        self.assertEqual('testtenantname', self.context.project_name)

    def test_request_id_extracted_from_env(self):
        req_id = 'dummy-request-id'
        self.request.headers['X_PROJECT_ID'] = 'testtenantid'
        self.request.headers['X_USER_ID'] = 'testuserid'
        self.request.environ[request_id.ENV_REQUEST_ID] = req_id
        self.request.get_response(self.middleware)
        self.assertEqual(req_id, self.context.request_id)

    def test_request_project_domain_id(self):
        self.request.headers['X_USER_ID'] = 'testuserid'
        self.request.headers['X_PROJECT_DOMAIN_ID'] = 'domain1'

        self.request.get_response(self.middleware)

        self.assertEqual('domain1', self.context.project_domain_id)

    def test_request_project_domain_name(self):
        self.request.headers['X_USER_ID'] = 'testuserid'
        self.request.headers['X_PROJECT_DOMAIN_NAME'] = 'mydomain'

        self.request.get_response(self.middleware)

        self.assertEqual('mydomain', self.context.project_domain_name)

    def test_request_user_domain_id(self):
        self.request.headers['X_USER_ID'] = 'testuserid'
        self.request.headers['X_USER_DOMAIN_ID'] = 'domain2'

        self.request.get_response(self.middleware)

        self.assertEqual('domain2', self.context.user_domain_id)

    def test_request_user_domain_name(self):
        self.request.headers['X_USER_ID'] = 'testuserid'
        self.request.headers['X_USER_DOMAIN_NAME'] = 'mydomain2'

        self.request.get_response(self.middleware)

        self.assertEqual('mydomain2', self.context.user_domain_name)
