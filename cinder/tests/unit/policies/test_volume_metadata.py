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
from six.moves import http_client

from cinder.tests.unit.policies import test_base
from cinder.volume import api as volume_api


# TODO(yikun): The below policy test cases should be added:
# * IMAGE_METADATA_POLICY
class VolumePolicyTests(test_base.CinderPolicyTests):

    def test_admin_can_get_metadata(self):
        admin_context = self.admin_context

        volume = self._create_fake_volume(admin_context, metadata={"k": "v"})
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/metadata' % {
            'project_id': admin_context.project_id, 'volume_id': volume.id
        }

        response = self._get_request_response(admin_context, path, 'GET')
        self.assertEqual(http_client.OK, response.status_int)
        res_meta = response.json_body['metadata']
        self.assertIn('k', res_meta)
        self.assertEqual('v', res_meta['k'])

    def test_owner_can_get_metadata(self):
        user_context = self.user_context

        volume = self._create_fake_volume(user_context, metadata={"k": "v"})
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/metadata' % {
            'project_id': user_context.project_id, 'volume_id': volume.id
        }

        response = self._get_request_response(user_context, path, 'GET')
        self.assertEqual(http_client.OK, response.status_int)
        res_meta = response.json_body['metadata']
        self.assertIn('k', res_meta)
        self.assertEqual('v', res_meta['k'])

    @mock.patch.object(volume_api.API, 'get')
    def test_owner_cannot_get_metadata_for_others(self, mock_volume):
        owner_context = self.user_context
        non_owner_context = self.other_user_context

        volume = self._create_fake_volume(owner_context, metadata={"k": "v"})
        mock_volume.return_value = volume
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/metadata' % {
            'project_id': non_owner_context.project_id, 'volume_id': volume.id
        }

        response = self._get_request_response(non_owner_context, path, 'GET')
        self.assertEqual(http_client.FORBIDDEN, response.status_int)

    def test_admin_can_create_metadata(self):
        admin_context = self.admin_context

        volume = self._create_fake_volume(admin_context, metadata={"k": "v"})
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/metadata' % {
            'project_id': admin_context.project_id, 'volume_id': volume.id
        }

        body = {"metadata": {"k1": "v1"}}
        response = self._get_request_response(admin_context, path, 'POST',
                                              body=body)
        self.assertEqual(http_client.OK, response.status_int)

    def test_owner_can_create_metadata(self):
        user_context = self.user_context

        volume = self._create_fake_volume(user_context, metadata={"k": "v"})
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/metadata' % {
            'project_id': user_context.project_id, 'volume_id': volume.id
        }

        body = {"metadata": {"k1": "v1"}}
        response = self._get_request_response(user_context, path, 'POST',
                                              body=body)
        self.assertEqual(http_client.OK, response.status_int)

    @mock.patch.object(volume_api.API, 'get')
    def test_owner_cannot_create_metadata_for_others(self, mock_volume):
        owner_context = self.user_context
        non_owner_context = self.other_user_context

        volume = self._create_fake_volume(owner_context, metadata={"k": "v"})
        mock_volume.return_value = volume
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/metadata' % {
            'project_id': non_owner_context.project_id, 'volume_id': volume.id
        }

        body = {"metadata": {"k1": "v1"}}
        response = self._get_request_response(non_owner_context, path, 'POST',
                                              body=body)
        self.assertEqual(http_client.FORBIDDEN, response.status_int)

    def test_admin_can_delete_metadata(self):
        admin_context = self.admin_context

        volume = self._create_fake_volume(admin_context, metadata={"k": "v"})

        path = '/v3/%(project_id)s/volumes/%(volume_id)s/metadata/%(key)s' % {
            'project_id': admin_context.project_id, 'volume_id': volume.id,
            'key': 'k'
        }
        response = self._get_request_response(admin_context, path, 'DELETE')
        self.assertEqual(http_client.OK, response.status_int)

    def test_owner_can_delete_metadata(self):
        user_context = self.user_context

        volume = self._create_fake_volume(user_context, metadata={"k": "v"})

        path = '/v3/%(project_id)s/volumes/%(volume_id)s/metadata/%(key)s' % {
            'project_id': user_context.project_id, 'volume_id': volume.id,
            'key': 'k'
        }
        response = self._get_request_response(user_context, path, 'DELETE')
        self.assertEqual(http_client.OK, response.status_int)

    @mock.patch.object(volume_api.API, 'get')
    def test_owner_cannot_delete_metadata_for_others(self, mock_volume):
        owner_context = self.user_context
        non_owner_context = self.other_user_context

        volume = self._create_fake_volume(owner_context, metadata={"k": "v"})
        mock_volume.return_value = volume
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/metadata/%(key)s' % {
            'project_id': non_owner_context.project_id,
            'volume_id': volume.id,
            'key': 'k'
        }
        response = self._get_request_response(non_owner_context, path,
                                              'DELETE')
        self.assertEqual(http_client.FORBIDDEN, response.status_int)

    def test_admin_can_update_metadata(self):
        admin_context = self.admin_context

        volume = self._create_fake_volume(admin_context, metadata={"k": "v"})
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/metadata' % {
            'project_id': admin_context.project_id, 'volume_id': volume.id
        }

        body = {"metadata": {"k": "v2"}}
        response = self._get_request_response(admin_context, path, 'PUT',
                                              body=body)
        self.assertEqual(http_client.OK, response.status_int)
        res_meta = response.json_body['metadata']
        self.assertIn('k', res_meta)
        self.assertEqual('v2', res_meta['k'])

    def test_owner_can_update_metadata(self):
        user_context = self.user_context

        volume = self._create_fake_volume(user_context, metadata={"k": "v"})
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/metadata' % {
            'project_id': user_context.project_id, 'volume_id': volume.id
        }

        body = {"metadata": {"k": "v2"}}
        response = self._get_request_response(user_context, path, 'PUT',
                                              body=body)
        self.assertEqual(http_client.OK, response.status_int)
        res_meta = response.json_body['metadata']
        self.assertIn('k', res_meta)
        self.assertEqual('v2', res_meta['k'])

    @mock.patch.object(volume_api.API, 'get')
    def test_owner_cannot_update_metadata_for_others(self, mock_volume):
        owner_context = self.user_context
        non_owner_context = self.other_user_context

        volume = self._create_fake_volume(owner_context, metadata={"k": "v"})
        mock_volume.return_value = volume
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/metadata' % {
            'project_id': non_owner_context.project_id, 'volume_id': volume.id
        }

        body = {"metadata": {"k": "v2"}}
        response = self._get_request_response(non_owner_context, path, 'PUT',
                                              body=body)
        self.assertEqual(http_client.FORBIDDEN, response.status_int)
