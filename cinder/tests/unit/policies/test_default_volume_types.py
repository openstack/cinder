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
import uuid

import ddt
from webob import exc

from cinder.api import api_utils
from cinder.api import microversions as mv
from cinder.api.v3 import default_types
from cinder import db
from cinder.policies import default_types as default_type_policies
from cinder.tests.unit.api import fakes as fake_api
from cinder.tests.unit import fake_constants
from cinder.tests.unit.policies import base
from cinder.tests.unit.policies import test_base
from cinder.tests.unit import utils as test_utils


class FakeProject(object):
    def __init__(self, id=None, name=None):
        if id:
            self.id = id
        else:
            self.id = uuid.uuid4().hex
        self.name = name
        self.description = 'fake project description'
        self.domain_id = 'default'


class DefaultVolumeTypesPolicyTests(test_base.CinderPolicyTests):

    class FakeDefaultType:
        project_id = fake_constants.PROJECT_ID
        volume_type_id = fake_constants.VOLUME_TYPE_ID

    def setUp(self):
        super(DefaultVolumeTypesPolicyTests, self).setUp()
        self.volume_type = self._create_fake_type(self.admin_context)
        self.project = FakeProject()
        # Need to mock out Keystone so the functional tests don't require other
        # services
        _keystone_client = mock.MagicMock()
        _keystone_client.version = 'v3'
        _keystone_client.projects.get.side_effect = self._get_project
        _keystone_client_get = mock.patch(
            'cinder.api.api_utils._keystone_client',
            lambda *args, **kwargs: _keystone_client)
        _keystone_client_get.start()
        self.addCleanup(_keystone_client_get.stop)

    def _get_project(self, project_id, *args, **kwargs):
        return self.project

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

    def test_system_admin_can_get_all_default(self):
        system_admin_context = self.system_admin_context

        path = '/v3/default-types'
        response = self._get_request_response(system_admin_context,
                                              path, 'GET',
                                              microversion=
                                              mv.DEFAULT_TYPE_OVERRIDES)

        self.assertEqual(HTTPStatus.OK, response.status_int)

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


@ddt.ddt
class DefaultVolumeTypesPolicyTest(base.BasePolicyTest):

    authorized_admins = [
        'system_admin',
        'legacy_admin',
        'project_admin',
    ]
    unauthorized_admins = [
        'legacy_owner',
        'system_member',
        'system_reader',
        'system_foo',
        'project_member',
        'project_reader',
        'project_foo',
        'other_project_member',
        'other_project_reader',
    ]

    # Basic policy test is without enforcing scope (which cinder doesn't
    # yet support) and deprecated rules enabled.
    def setUp(self, enforce_scope=False, enforce_new_defaults=False,
              *args, **kwargs):
        super().setUp(enforce_scope, enforce_new_defaults, *args, **kwargs)
        self.controller = default_types.DefaultTypesController()
        self.api_path = '/v3/default-types/%s' % (self.project_id)
        self.api_version = mv.DEFAULT_TYPE_OVERRIDES

    def _create_volume_type(self):
        vol_type = test_utils.create_volume_type(self.project_admin_context,
                                                 name='fake_vol_type',
                                                 testcase_instance=self)
        return vol_type

    @ddt.data(*base.all_users)
    @mock.patch.object(api_utils, 'get_project')
    def test_default_type_set_policy(self, user_id, fake_project):
        vol_type = self._create_volume_type()
        fake_project.return_value = FakeProject(id=self.project_id)
        rule_name = default_type_policies.CREATE_UPDATE_POLICY
        url = self.api_path
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)
        req.method = 'POST'
        body = {"default_type": {"volume_type": vol_type.id}}
        unauthorized_exceptions = [exc.HTTPForbidden]
        self.common_policy_check(user_id, self.authorized_admins,
                                 self.unauthorized_admins,
                                 unauthorized_exceptions,
                                 rule_name, self.controller.create_update, req,
                                 id=vol_type.id, body=body)

    @ddt.data(*base.all_users)
    @mock.patch.object(default_types.db, 'project_default_volume_type_get')
    @mock.patch.object(api_utils, 'get_project')
    def test_default_type_get_policy(self, user_id, fake_project,
                                     mock_default_get):
        fake_project.return_value = FakeProject(id=self.project_id)
        rule_name = default_type_policies.GET_POLICY
        url = self.api_path
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)
        unauthorized_exceptions = [exc.HTTPForbidden]
        self.common_policy_check(user_id, self.authorized_admins,
                                 self.unauthorized_admins,
                                 unauthorized_exceptions,
                                 rule_name, self.controller.detail, req,
                                 id=self.project_id)

    @ddt.data(*base.all_users)
    @mock.patch.object(default_types.db, 'project_default_volume_type_get')
    def test_default_type_get_all_policy(self, user_id, mock_default_get):
        rule_name = default_type_policies.GET_ALL_POLICY
        url = self.api_path
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)
        unauthorized_exceptions = [exc.HTTPForbidden]
        # NOTE: The users 'legacy_admin' and 'project_admin' pass for
        # GET_ALL_POLICY since with enforce_new_defaults=False, we have
        # a logical OR between old policy and new one hence RULE_ADMIN_API
        # allows them to pass
        self.common_policy_check(user_id, self.authorized_admins,
                                 self.unauthorized_admins,
                                 unauthorized_exceptions,
                                 rule_name, self.controller.index, req)

    @ddt.data(*base.all_users)
    @mock.patch.object(api_utils, 'get_project')
    @mock.patch.object(default_types.db, 'project_default_volume_type_get')
    def test_default_type_unset_policy(self, user_id, mock_default_unset,
                                       fake_project):
        fake_project.return_value = FakeProject(id=self.project_id)
        rule_name = default_type_policies.DELETE_POLICY
        url = self.api_path
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)
        req.method = 'DELETE'
        unauthorized_exceptions = [exc.HTTPForbidden]
        self.common_policy_check(user_id, self.authorized_admins,
                                 self.unauthorized_admins,
                                 unauthorized_exceptions,
                                 rule_name, self.controller.delete, req,
                                 id=self.project_id)


class DefaultVolumeTypesPolicySecureRbacTest(DefaultVolumeTypesPolicyTest):

    authorized_admins = [
        'legacy_admin',
        'system_admin',
        'project_admin',
    ]
    unauthorized_admins = [
        'legacy_owner',
        'system_member',
        'system_reader',
        'system_foo',
        'project_member',
        'project_reader',
        'project_foo',
        'other_project_member',
        'other_project_reader',
    ]

    def setUp(self, *args, **kwargs):
        # Test secure RBAC by disabling deprecated policy rules (scope
        # is still not enabled).
        super().setUp(enforce_scope=False, enforce_new_defaults=True,
                      *args, **kwargs)
