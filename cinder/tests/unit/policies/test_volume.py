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

from cinder.tests.unit import fake_constants
from cinder.tests.unit.policies import test_base
from cinder.volume import api as volume_api


# TODO(yikun): The below policy test cases should be added:
# * HOST_ATTRIBUTE_POLICY
# * MIG_ATTRIBUTE_POLICY
# * ENCRYPTION_METADATA_POLICY
# * MULTIATTACH_POLICY
class VolumePolicyTests(test_base.CinderPolicyTests):

    def test_admin_can_create_volume(self):
        admin_context = self.admin_context

        path = '/v3/%(project_id)s/volumes' % {
            'project_id': admin_context.project_id
        }
        body = {"volume": {"size": 1}}
        response = self._get_request_response(admin_context, path, 'POST',
                                              body=body)

        self.assertEqual(http_client.ACCEPTED, response.status_int)

    def test_nonadmin_user_can_create_volume(self):
        user_context = self.user_context

        path = '/v3/%(project_id)s/volumes' % {
            'project_id': user_context.project_id
        }
        body = {"volume": {"size": 1}}
        response = self._get_request_response(user_context, path, 'POST',
                                              body=body)

        self.assertEqual(http_client.ACCEPTED, response.status_int)

    def test_admin_can_create_volume_from_image(self):
        admin_context = self.admin_context

        path = '/v3/%(project_id)s/volumes' % {
            'project_id': admin_context.project_id
        }
        body = {"volume": {"size": 1, "image_id": fake_constants.IMAGE_ID}}
        response = self._get_request_response(admin_context, path, 'POST',
                                              body=body)

        self.assertEqual(http_client.ACCEPTED, response.status_int)

    def test_nonadmin_user_can_create_volume_from_image(self):
        user_context = self.user_context

        path = '/v3/%(project_id)s/volumes' % {
            'project_id': user_context.project_id
        }
        body = {"volume": {"size": 1, "image_id": fake_constants.IMAGE_ID}}
        response = self._get_request_response(user_context, path, 'POST',
                                              body=body)

        self.assertEqual(http_client.ACCEPTED, response.status_int)

    @mock.patch.object(volume_api.API, 'get_volume')
    def test_admin_can_show_volumes(self, mock_volume):
        # Make sure administrators are authorized to list volumes
        admin_context = self.admin_context

        volume = self._create_fake_volume(admin_context)
        mock_volume.return_value = volume
        path = '/v3/%(project_id)s/volumes/%(volume_id)s' % {
            'project_id': admin_context.project_id, 'volume_id': volume.id
        }

        response = self._get_request_response(admin_context, path, 'GET')

        self.assertEqual(http_client.OK, response.status_int)
        self.assertEqual(response.json_body['volume']['id'], volume.id)

    @mock.patch.object(volume_api.API, 'get_volume')
    def test_owner_can_show_volumes(self, mock_volume):
        # Make sure owners are authorized to list their volumes
        user_context = self.user_context

        volume = self._create_fake_volume(user_context)
        mock_volume.return_value = volume
        path = '/v3/%(project_id)s/volumes/%(volume_id)s' % {
            'project_id': user_context.project_id, 'volume_id': volume.id
        }

        response = self._get_request_response(user_context, path, 'GET')

        self.assertEqual(http_client.OK, response.status_int)
        self.assertEqual(response.json_body['volume']['id'], volume.id)

    @mock.patch.object(volume_api.API, 'get_volume')
    def test_owner_cannot_show_volumes_for_others(self, mock_volume):
        # Make sure volumes are only exposed to their owners
        owner_context = self.user_context
        non_owner_context = self.other_user_context

        volume = self._create_fake_volume(owner_context)
        mock_volume.return_value = volume

        path = '/v3/%(project_id)s/volumes/%(volume_id)s' % {
            'project_id': non_owner_context.project_id, 'volume_id': volume.id
        }

        response = self._get_request_response(non_owner_context, path, 'GET')
        # NOTE(lbragstad): Technically, this user isn't supposed to see this
        # volume, because they didn't create it and it lives in a different
        # project. Does cinder return a 404 in cases like this? Or is a 403
        # expected?
        self.assertEqual(http_client.NOT_FOUND, response.status_int)

    def test_admin_can_get_all_volumes_detail(self):
        # Make sure administrators are authorized to list volumes
        admin_context = self.admin_context

        volume = self._create_fake_volume(admin_context)
        path = '/v3/%(project_id)s/volumes/detail' % {
            'project_id': admin_context.project_id, 'volume_id': volume.id
        }

        response = self._get_request_response(admin_context, path, 'GET')

        self.assertEqual(http_client.OK, response.status_int)
        res_vol = response.json_body['volumes'][0]

        self.assertEqual(volume.id, res_vol['id'])

    def test_owner_can_get_all_volumes_detail(self):
        # Make sure owners are authorized to list volumes
        user_context = self.user_context

        volume = self._create_fake_volume(user_context)
        path = '/v3/%(project_id)s/volumes/detail' % {
            'project_id': user_context.project_id, 'volume_id': volume.id
        }

        response = self._get_request_response(user_context, path, 'GET')

        self.assertEqual(http_client.OK, response.status_int)
        res_vol = response.json_body['volumes'][0]

        self.assertEqual(volume.id, res_vol['id'])

    @mock.patch.object(volume_api.API, 'get')
    def test_admin_can_update_volumes(self, mock_volume):
        admin_context = self.admin_context

        volume = self._create_fake_volume(admin_context)
        mock_volume.return_value = volume
        path = '/v3/%(project_id)s/volumes/%(volume_id)s' % {
            'project_id': admin_context.project_id, 'volume_id': volume.id
        }

        body = {"volume": {"name": "update_name"}}
        response = self._get_request_response(admin_context, path, 'PUT',
                                              body=body)
        self.assertEqual(http_client.OK, response.status_int)

    @mock.patch.object(volume_api.API, 'get')
    def test_owner_can_update_volumes(self, mock_volume):
        user_context = self.user_context

        volume = self._create_fake_volume(user_context)
        mock_volume.return_value = volume
        path = '/v3/%(project_id)s/volumes/%(volume_id)s' % {
            'project_id': user_context.project_id, 'volume_id': volume.id
        }

        body = {"volume": {"name": "update_name"}}
        response = self._get_request_response(user_context, path, 'PUT',
                                              body=body)
        self.assertEqual(http_client.OK, response.status_int)

    @mock.patch.object(volume_api.API, 'get')
    def test_owner_cannot_update_volumes_for_others(self, mock_volume):
        owner_context = self.user_context
        non_owner_context = self.other_user_context

        volume = self._create_fake_volume(owner_context)
        mock_volume.return_value = volume

        path = '/v3/%(project_id)s/volumes/%(volume_id)s' % {
            'project_id': non_owner_context.project_id, 'volume_id': volume.id
        }

        body = {"volume": {"name": "update_name"}}
        response = self._get_request_response(non_owner_context, path, 'PUT',
                                              body=body)
        self.assertEqual(http_client.FORBIDDEN, response.status_int)

    @mock.patch.object(volume_api.API, 'get')
    def test_owner_can_delete_volumes(self, mock_volume):
        user_context = self.user_context

        volume = self._create_fake_volume(user_context)
        mock_volume.return_value = volume
        path = '/v3/%(project_id)s/volumes/%(volume_id)s' % {
            'project_id': user_context.project_id, 'volume_id': volume.id
        }

        response = self._get_request_response(user_context, path, 'DELETE')
        self.assertEqual(http_client.ACCEPTED, response.status_int)

    @mock.patch.object(volume_api.API, 'get')
    def test_admin_can_delete_volumes(self, mock_volume):
        admin_context = self.admin_context

        volume = self._create_fake_volume(admin_context)
        mock_volume.return_value = volume
        path = '/v3/%(project_id)s/volumes/%(volume_id)s' % {
            'project_id': admin_context.project_id, 'volume_id': volume.id
        }

        response = self._get_request_response(admin_context, path, 'DELETE')
        self.assertEqual(http_client.ACCEPTED, response.status_int)

    @mock.patch.object(volume_api.API, 'get')
    def test_owner_cannot_delete_volumes_for_others(self, mock_volume):
        owner_context = self.user_context
        non_owner_context = self.other_user_context

        volume = self._create_fake_volume(owner_context)
        mock_volume.return_value = volume

        path = '/v3/%(project_id)s/volumes/%(volume_id)s' % {
            'project_id': non_owner_context.project_id, 'volume_id': volume.id
        }

        response = self._get_request_response(non_owner_context, path,
                                              'DELETE')
        self.assertEqual(http_client.FORBIDDEN, response.status_int)

    @mock.patch.object(volume_api.API, 'get_volume')
    def test_admin_can_show_tenant_id_in_volume(self, mock_volume):
        # Make sure administrators are authorized to show tenant_id
        admin_context = self.admin_context

        volume = self._create_fake_volume(admin_context)
        mock_volume.return_value = volume
        path = '/v3/%(project_id)s/volumes/%(volume_id)s' % {
            'project_id': admin_context.project_id, 'volume_id': volume.id
        }

        response = self._get_request_response(admin_context, path, 'GET')

        self.assertEqual(http_client.OK, response.status_int)
        res_vol = response.json_body['volume']
        self.assertEqual(admin_context.project_id,
                         res_vol['os-vol-tenant-attr:tenant_id'])

    @mock.patch.object(volume_api.API, 'get_volume')
    def test_owner_can_show_tenant_id_in_volume(self, mock_volume):
        # Make sure owners are authorized to show tenant_id in volume
        user_context = self.user_context

        volume = self._create_fake_volume(user_context)
        mock_volume.return_value = volume
        path = '/v3/%(project_id)s/volumes/%(volume_id)s' % {
            'project_id': user_context.project_id, 'volume_id': volume.id
        }

        response = self._get_request_response(user_context, path, 'GET')

        self.assertEqual(http_client.OK, response.status_int)
        res_vol = response.json_body['volume']
        self.assertEqual(user_context.project_id,
                         res_vol['os-vol-tenant-attr:tenant_id'])

    def test_admin_can_show_tenant_id_in_volume_detail(self):
        # Make sure admins are authorized to show tenant_id in volume detail
        admin_context = self.admin_context

        volume = self._create_fake_volume(admin_context)
        path = '/v3/%(project_id)s/volumes/detail' % {
            'project_id': admin_context.project_id, 'volume_id': volume.id
        }

        response = self._get_request_response(admin_context, path, 'GET')

        self.assertEqual(http_client.OK, response.status_int)
        res_vol = response.json_body['volumes'][0]
        # Make sure owners are authorized to show tenant_id
        self.assertEqual(admin_context.project_id,
                         res_vol['os-vol-tenant-attr:tenant_id'])

    def test_owner_can_show_tenant_id_in_volume_detail(self):
        # Make sure owners are authorized to show tenant_id in volume detail
        user_context = self.user_context

        volume = self._create_fake_volume(user_context)
        path = '/v3/%(project_id)s/volumes/detail' % {
            'project_id': user_context.project_id, 'volume_id': volume.id
        }

        response = self._get_request_response(user_context, path, 'GET')

        self.assertEqual(http_client.OK, response.status_int)
        res_vol = response.json_body['volumes'][0]
        # Make sure owners are authorized to show tenant_id
        self.assertEqual(user_context.project_id,
                         res_vol['os-vol-tenant-attr:tenant_id'])

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

    def test_admin_can_delete_metadata(self):
        admin_context = self.admin_context

        volume = self._create_fake_volume(admin_context, metadata={"k": "v"})

        path = '/v3/%(project_id)s/volumes/%(volume_id)s/metadata/%(key)s' % {
            'project_id': admin_context.project_id, 'volume_id': volume.id,
            'key': 'k'
        }
        response = self._get_request_response(admin_context, path, 'DELETE')
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
