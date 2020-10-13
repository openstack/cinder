# Copyright 2020 Red Hat, Inc.
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
from unittest import mock

from cinder.api import microversions as mv
from cinder import db
from cinder.tests.unit import fake_constants
from cinder.tests.unit.policies import test_base


class DefaultVolumeTypesPolicyTests(test_base.CinderPolicyTests):

    class FakeDefaultType:
        project_id = fake_constants.PROJECT_ID
        volume_type_id = fake_constants.VOLUME_TYPE_ID

    def setUp(self):
        super(DefaultVolumeTypesPolicyTests, self).setUp()
        self.volume_type = self._create_fake_type(self.admin_context)
        self.project = self.FakeProject()
        # Need to mock out Keystone so the functional tests don't require other
        # services
        _keystone_client = mock.MagicMock()
        _keystone_client.version = 'v3'
        _keystone_client.projects.get.side_effect = self._get_project
        _keystone_client_get = mock.patch(
            'cinder.quota_utils._keystone_client',
            lambda *args, **kwargs: _keystone_client)
        _keystone_client_get.start()
        self.addCleanup(_keystone_client_get.stop)

    def _get_project(self, project_id, *args, **kwargs):
        return self.project

    class FakeProject(object):
        _dom_id = fake_constants.DOMAIN_ID

        def __init__(self, parent_id=None):
            self.id = fake_constants.PROJECT_ID
            self.parent_id = parent_id
            self.domain_id = self._dom_id
            self.subtree = None
            self.parents = None

    def test_system_admin_can_set_default(self):
        system_admin_context = self.system_admin_context

        path = '/v3/default-types/%s' % system_admin_context.project_id
        body = {
            'default_type':
                {"volume_type": self.volume_type.id}
        }
        response = self._get_request_response(system_admin_context,
                                              path, 'PUT', body=body,
                                              microversion=
                                              mv.DEFAULT_TYPE_OVERRIDES)

        self.assertEqual(HTTPStatus.OK, response.status_int)

    def test_project_admin_can_set_default(self):
        admin_context = self.admin_context

        path = '/v3/default-types/%s' % admin_context.project_id
        body = {
            'default_type':
                {"volume_type": self.volume_type.id}
        }
        response = self._get_request_response(admin_context,
                                              path, 'PUT', body=body,
                                              microversion=
                                              mv.DEFAULT_TYPE_OVERRIDES)

        self.assertEqual(HTTPStatus.OK, response.status_int)

    def test_project_admin_cannot_set_default_for_other_project(self):
        admin_context = self.admin_context

        path = '/v3/default-types/%s' % admin_context.project_id
        body = {
            'default_type':
                {"volume_type": self.volume_type.id}
        }
        response = self._get_request_response(self.other_admin_context,
                                              path, 'PUT', body=body,
                                              microversion=
                                              mv.DEFAULT_TYPE_OVERRIDES)

        self.assertEqual(HTTPStatus.FORBIDDEN, response.status_int)

    @mock.patch.object(db, 'project_default_volume_type_get',
                       return_value=FakeDefaultType())
    def test_system_admin_can_get_default(self, mock_default_get):
        system_admin_context = self.system_admin_context

        path = '/v3/default-types/%s' % system_admin_context.project_id
        response = self._get_request_response(system_admin_context,
                                              path, 'GET',
                                              microversion=
                                              mv.DEFAULT_TYPE_OVERRIDES)

        self.assertEqual(HTTPStatus.OK, response.status_int)

    def test_project_admin_can_get_default(self):
        admin_context = self.admin_context

        path = '/v3/default-types/%s' % admin_context.project_id
        body = {
            'default_type':
                {"volume_type": self.volume_type.id}
        }
        self._get_request_response(admin_context,
                                   path, 'PUT', body=body,
                                   microversion=
                                   mv.DEFAULT_TYPE_OVERRIDES)

        path = '/v3/default-types/%s' % admin_context.project_id
        response = self._get_request_response(admin_context,
                                              path, 'GET',
                                              microversion=
                                              mv.DEFAULT_TYPE_OVERRIDES)

        self.assertEqual(HTTPStatus.OK, response.status_int)

    def test_project_admin_cannot_get_default_for_other_project(self):
        admin_context = self.admin_context

        path = '/v3/default-types/%s' % admin_context.project_id
        response = self._get_request_response(self.other_admin_context,
                                              path, 'GET',
                                              microversion=
                                              mv.DEFAULT_TYPE_OVERRIDES)

        self.assertEqual(HTTPStatus.FORBIDDEN, response.status_int)

    def test_system_admin_can_get_all_default(self):
        system_admin_context = self.system_admin_context

        path = '/v3/default-types'
        response = self._get_request_response(system_admin_context,
                                              path, 'GET',
                                              microversion=
                                              mv.DEFAULT_TYPE_OVERRIDES)

        self.assertEqual(HTTPStatus.OK, response.status_int)

    def test_project_admin_cannot_get_all_default(self):
        admin_context = self.admin_context

        path = '/v3/default-types'
        response = self._get_request_response(admin_context,
                                              path, 'GET',
                                              microversion=
                                              mv.DEFAULT_TYPE_OVERRIDES)

        self.assertEqual(HTTPStatus.FORBIDDEN, response.status_int)

    def test_system_admin_can_unset_default(self):
        system_admin_context = self.system_admin_context

        path = '/v3/default-types/%s' % system_admin_context.project_id
        response = self._get_request_response(system_admin_context,
                                              path, 'DELETE',
                                              microversion=
                                              mv.DEFAULT_TYPE_OVERRIDES)

        self.assertEqual(HTTPStatus.NO_CONTENT, response.status_int)

    def test_project_admin_can_unset_default(self):
        admin_context = self.admin_context

        path = '/v3/default-types/%s' % admin_context.project_id
        response = self._get_request_response(admin_context,
                                              path, 'DELETE',
                                              microversion=
                                              mv.DEFAULT_TYPE_OVERRIDES)

        self.assertEqual(HTTPStatus.NO_CONTENT, response.status_int)

    def test_project_admin_cannot_unset_default_for_other_project(self):
        admin_context = self.admin_context

        path = '/v3/default-types/%s' % admin_context.project_id
        response = self._get_request_response(self.other_admin_context,
                                              path, 'DELETE',
                                              microversion=
                                              mv.DEFAULT_TYPE_OVERRIDES)

        self.assertEqual(HTTPStatus.FORBIDDEN, response.status_int)
