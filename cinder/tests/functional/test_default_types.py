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

from unittest import mock
import uuid

from cinder import context
from cinder.tests.functional.api import client
from cinder.tests.functional import functional_helpers


class DefaultVolumeTypesTest(functional_helpers._FunctionalTestBase):
    _vol_type_name = 'functional_test_type'
    _osapi_version = '3.62'

    def setUp(self):
        super(DefaultVolumeTypesTest, self).setUp()
        self.volume_type = self.api.create_type(self._vol_type_name)
        self.project = self.FakeProject()
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

    class FakeProject(object):
        def __init__(self, name=None):
            self.id = uuid.uuid4().hex
            self.name = name
            self.description = 'fake project description'
            self.domain_id = 'default'

    @mock.patch.object(context.RequestContext, 'authorize')
    def test_default_type_set(self, mock_authorize):
        default_type = self.api.set_default_type(
            self.project.id, {'volume_type': self._vol_type_name})
        self.assertEqual(self.project.id, default_type['project_id'])
        self.assertEqual(self.volume_type['id'],
                         default_type['volume_type_id'])

    @mock.patch.object(context.RequestContext, 'authorize')
    def test_default_type_get(self, mock_authorize):
        self.api.set_default_type(self.project.id,
                                  {'volume_type': self._vol_type_name})
        default_type = self.api.get_default_type(project_id=self.project.id)

        self.assertEqual(self.project.id, default_type['project_id'])
        self.assertEqual(self.volume_type['id'],
                         default_type['volume_type_id'])

    @mock.patch.object(context.RequestContext, 'authorize')
    def test_default_type_get_all(self, mock_authorize):
        self.api.set_default_type(self.project.id,
                                  {'volume_type': self._vol_type_name})
        default_types = self.api.get_default_type()

        self.assertEqual(1, len(default_types))
        self.assertEqual(self.project.id, default_types[0]['project_id'])
        self.assertEqual(self.volume_type['id'],
                         default_types[0]['volume_type_id'])

    @mock.patch.object(context.RequestContext, 'authorize')
    def test_default_type_unset(self, mock_authorize):
        self.api.set_default_type(self.project.id,
                                  {'volume_type': self._vol_type_name})

        default_types = self.api.get_default_type()
        self.assertEqual(1, len(default_types))
        self.api.unset_default_type(self.project.id)
        default_types = self.api.get_default_type()
        self.assertEqual(0, len(default_types))

    @mock.patch.object(context.RequestContext, 'authorize')
    def test_default_type_set_volume_type_not_found(self, mock_authorize):
        self.assertRaises(client.OpenStackApiException400,
                          self.api.set_default_type,
                          self.project.id,
                          {'volume_type': 'fake_type'})

    @mock.patch.object(context.RequestContext, 'authorize')
    def test_cannot_delete_project_default_type(self, mock_authorize):
        default_type = self.api.set_default_type(
            self.project.id, {'volume_type': self._vol_type_name})
        self.assertRaises(client.OpenStackApiException400,
                          self.api.delete_type,
                          default_type['volume_type_id'])
