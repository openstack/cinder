# Copyright 2016 OpenStack Foundation
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

import mock

from cinder import context
from cinder import exception
from cinder import quota_utils
from cinder import test

from keystoneclient import exceptions
from keystonemiddleware import auth_token

from oslo_config import cfg
from oslo_config import fixture as config_fixture

CONF = cfg.CONF


class QuotaUtilsTest(test.TestCase):
    class FakeProject(object):
        def __init__(self, id='foo', parent_id=None):
            self.id = id
            self.parent_id = parent_id
            self.subtree = None

    def setUp(self):
        super(QuotaUtilsTest, self).setUp()

        self.auth_url = 'http://localhost:5000'
        self.context = context.RequestContext('fake_user', 'fake_proj_id')
        self.fixture = self.useFixture(config_fixture.Config(auth_token.CONF))
        self.fixture.config(auth_uri=self.auth_url, group='keystone_authtoken')

    @mock.patch('keystoneclient.client.Client')
    @mock.patch('keystoneclient.session.Session')
    def test_keystone_client_instantiation(self, ksclient_session,
                                           ksclient_class):
        quota_utils._keystone_client(self.context)
        ksclient_class.assert_called_once_with(auth_url=self.auth_url,
                                               session=ksclient_session(),
                                               version=(3, 0))

    @mock.patch('keystoneclient.client.Client')
    def test_get_project_keystoneclient_v2(self, ksclient_class):
        keystoneclient = ksclient_class.return_value
        keystoneclient.version = 'v2.0'
        expected_project = quota_utils.GenericProjectInfo(
            self.context.project_id, 'v2.0')
        project = quota_utils.get_project_hierarchy(
            self.context, self.context.project_id)
        self.assertEqual(expected_project.__dict__, project.__dict__)

    @mock.patch('keystoneclient.client.Client')
    def test_get_project_keystoneclient_v3(self, ksclient_class):
        keystoneclient = ksclient_class.return_value
        keystoneclient.version = 'v3'
        returned_project = self.FakeProject(self.context.project_id, 'bar')
        del returned_project.subtree
        keystoneclient.projects.get.return_value = returned_project
        expected_project = quota_utils.GenericProjectInfo(
            self.context.project_id, 'v3', 'bar')
        project = quota_utils.get_project_hierarchy(
            self.context, self.context.project_id)
        self.assertEqual(expected_project.__dict__, project.__dict__)

    @mock.patch('keystoneclient.client.Client')
    def test_get_project_keystoneclient_v3_with_subtree(self, ksclient_class):
        keystoneclient = ksclient_class.return_value
        keystoneclient.version = 'v3'
        returned_project = self.FakeProject(self.context.project_id, 'bar')
        subtree_dict = {'baz': {'quux': None}}
        returned_project.subtree = subtree_dict
        keystoneclient.projects.get.return_value = returned_project
        expected_project = quota_utils.GenericProjectInfo(
            self.context.project_id, 'v3', 'bar', subtree_dict)
        project = quota_utils.get_project_hierarchy(
            self.context, self.context.project_id, subtree_as_ids=True)
        keystoneclient.projects.get.assert_called_once_with(
            self.context.project_id, subtree_as_ids=True)
        self.assertEqual(expected_project.__dict__, project.__dict__)

    @mock.patch('cinder.quota_utils._keystone_client')
    def test_validate_nested_projects_with_keystone_v2(self, _keystone_client):
        _keystone_client.side_effect = exceptions.VersionNotAvailable

        self.assertRaises(exception.CinderException,
                          quota_utils.validate_setup_for_nested_quota_use,
                          self.context, [], None)

    @mock.patch('cinder.quota_utils._keystone_client')
    def test_validate_nested_projects_non_cloud_admin(self, _keystone_client):
        # Covers not cloud admin or using old policy.json
        _keystone_client.side_effect = exceptions.Forbidden

        self.assertRaises(exception.CinderException,
                          quota_utils.validate_setup_for_nested_quota_use,
                          self.context, [], None)
