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

import ddt

from cinder.api.contrib import volume_encryption_metadata
from cinder.api.contrib import volume_tenant_attribute
from cinder.api.v3 import volumes
from cinder import exception
from cinder.policies import volumes as volume_policies
from cinder.tests.unit.api import fakes as fake_api
from cinder.tests.unit import fake_constants
from cinder.tests.unit.policies import base
from cinder.tests.unit.policies import test_base
from cinder.tests.unit import utils as test_utils
from cinder.volume import api as volume_api


# TODO(yikun): The below policy test cases should be added:
# * HOST_ATTRIBUTE_POLICY
# * MIG_ATTRIBUTE_POLICY
class VolumePolicyTests(test_base.CinderPolicyTests):

    def test_admin_can_create_volume(self):
        admin_context = self.admin_context

        path = '/v3/%(project_id)s/volumes' % {
            'project_id': admin_context.project_id
        }
        body = {"volume": {"size": 1}}
        response = self._get_request_response(admin_context, path, 'POST',
                                              body=body)

        self.assertEqual(HTTPStatus.ACCEPTED, response.status_int)

    def test_nonadmin_user_can_create_volume(self):
        user_context = self.user_context

        path = '/v3/%(project_id)s/volumes' % {
            'project_id': user_context.project_id
        }
        body = {"volume": {"size": 1}}
        response = self._get_request_response(user_context, path, 'POST',
                                              body=body)

        self.assertEqual(HTTPStatus.ACCEPTED, response.status_int)

    def test_admin_can_create_volume_from_image(self):
        admin_context = self.admin_context

        path = '/v3/%(project_id)s/volumes' % {
            'project_id': admin_context.project_id
        }
        body = {"volume": {"size": 1, "image_id": fake_constants.IMAGE_ID}}
        response = self._get_request_response(admin_context, path, 'POST',
                                              body=body)

        self.assertEqual(HTTPStatus.ACCEPTED, response.status_int)

    def test_nonadmin_user_can_create_volume_from_image(self):
        user_context = self.user_context

        path = '/v3/%(project_id)s/volumes' % {
            'project_id': user_context.project_id
        }
        body = {"volume": {"size": 1, "image_id": fake_constants.IMAGE_ID}}
        response = self._get_request_response(user_context, path, 'POST',
                                              body=body)

        self.assertEqual(HTTPStatus.ACCEPTED, response.status_int)

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

        self.assertEqual(HTTPStatus.OK, response.status_int)
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

        self.assertEqual(HTTPStatus.OK, response.status_int)
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
        self.assertEqual(HTTPStatus.NOT_FOUND, response.status_int)

    def test_admin_can_get_all_volumes_detail(self):
        # Make sure administrators are authorized to list volumes
        admin_context = self.admin_context

        volume = self._create_fake_volume(admin_context)
        path = '/v3/%(project_id)s/volumes/detail' % {
            'project_id': admin_context.project_id
        }

        response = self._get_request_response(admin_context, path, 'GET')

        self.assertEqual(HTTPStatus.OK, response.status_int)
        res_vol = response.json_body['volumes'][0]

        self.assertEqual(volume.id, res_vol['id'])

    def test_owner_can_get_all_volumes_detail(self):
        # Make sure owners are authorized to list volumes
        user_context = self.user_context

        volume = self._create_fake_volume(user_context)
        path = '/v3/%(project_id)s/volumes/detail' % {
            'project_id': user_context.project_id
        }

        response = self._get_request_response(user_context, path, 'GET')

        self.assertEqual(HTTPStatus.OK, response.status_int)
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
        self.assertEqual(HTTPStatus.OK, response.status_int)

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
        self.assertEqual(HTTPStatus.OK, response.status_int)

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
        self.assertEqual(HTTPStatus.FORBIDDEN, response.status_int)

    @mock.patch.object(volume_api.API, 'get')
    def test_owner_can_delete_volumes(self, mock_volume):
        user_context = self.user_context

        volume = self._create_fake_volume(user_context)
        mock_volume.return_value = volume
        path = '/v3/%(project_id)s/volumes/%(volume_id)s' % {
            'project_id': user_context.project_id, 'volume_id': volume.id
        }

        response = self._get_request_response(user_context, path, 'DELETE')
        self.assertEqual(HTTPStatus.ACCEPTED, response.status_int)

    @mock.patch.object(volume_api.API, 'get')
    def test_admin_can_delete_volumes(self, mock_volume):
        admin_context = self.admin_context

        volume = self._create_fake_volume(admin_context)
        mock_volume.return_value = volume
        path = '/v3/%(project_id)s/volumes/%(volume_id)s' % {
            'project_id': admin_context.project_id, 'volume_id': volume.id
        }

        response = self._get_request_response(admin_context, path, 'DELETE')
        self.assertEqual(HTTPStatus.ACCEPTED, response.status_int)

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
        self.assertEqual(HTTPStatus.FORBIDDEN, response.status_int)

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

        self.assertEqual(HTTPStatus.OK, response.status_int)
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

        self.assertEqual(HTTPStatus.OK, response.status_int)
        res_vol = response.json_body['volume']
        self.assertEqual(user_context.project_id,
                         res_vol['os-vol-tenant-attr:tenant_id'])

    def test_admin_can_show_tenant_id_in_volume_detail(self):
        # Make sure admins are authorized to show tenant_id in volume detail
        admin_context = self.admin_context

        self._create_fake_volume(admin_context)
        path = '/v3/%(project_id)s/volumes/detail' % {
            'project_id': admin_context.project_id
        }

        response = self._get_request_response(admin_context, path, 'GET')

        self.assertEqual(HTTPStatus.OK, response.status_int)
        res_vol = response.json_body['volumes'][0]
        # Make sure owners are authorized to show tenant_id
        self.assertEqual(admin_context.project_id,
                         res_vol['os-vol-tenant-attr:tenant_id'])

    def test_owner_can_show_tenant_id_in_volume_detail(self):
        # Make sure owners are authorized to show tenant_id in volume detail
        user_context = self.user_context

        self._create_fake_volume(user_context)
        path = '/v3/%(project_id)s/volumes/detail' % {
            'project_id': user_context.project_id
        }

        response = self._get_request_response(user_context, path, 'GET')

        self.assertEqual(HTTPStatus.OK, response.status_int)
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
        self.assertEqual(HTTPStatus.OK, response.status_int)

    def test_admin_can_get_metadata(self):
        admin_context = self.admin_context

        volume = self._create_fake_volume(admin_context, metadata={"k": "v"})
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/metadata' % {
            'project_id': admin_context.project_id, 'volume_id': volume.id
        }

        response = self._get_request_response(admin_context, path, 'GET')
        self.assertEqual(HTTPStatus.OK, response.status_int)
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
        self.assertEqual(HTTPStatus.OK, response.status_int)
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
        self.assertEqual(HTTPStatus.OK, response.status_int)

    def test_owner_can_create_metadata(self):
        user_context = self.user_context

        volume = self._create_fake_volume(user_context, metadata={"k": "v"})
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/metadata' % {
            'project_id': user_context.project_id, 'volume_id': volume.id
        }

        body = {"metadata": {"k1": "v1"}}
        response = self._get_request_response(user_context, path, 'POST',
                                              body=body)
        self.assertEqual(HTTPStatus.OK, response.status_int)

    def test_owner_can_get_metadata(self):
        user_context = self.user_context

        volume = self._create_fake_volume(user_context, metadata={"k": "v"})
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/metadata' % {
            'project_id': user_context.project_id, 'volume_id': volume.id
        }

        response = self._get_request_response(user_context, path, 'GET')
        self.assertEqual(HTTPStatus.OK, response.status_int)
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
        self.assertEqual(HTTPStatus.OK, response.status_int)
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
        self.assertEqual(HTTPStatus.OK, response.status_int)

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
        self.assertEqual(HTTPStatus.FORBIDDEN, response.status_int)

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
        self.assertEqual(HTTPStatus.FORBIDDEN, response.status_int)

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
        self.assertEqual(HTTPStatus.FORBIDDEN, response.status_int)

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
        self.assertEqual(HTTPStatus.FORBIDDEN, response.status_int)


@ddt.ddt
class VolumesPolicyTest(base.BasePolicyTest):

    authorized_readers = [
        'legacy_admin',
        'legacy_owner',
        'system_admin',
        'project_admin',
        'project_member',
        'project_reader',
        'project_foo',
    ]
    unauthorized_readers = [
        'system_member',
        'system_reader',
        'system_foo',
        'other_project_member',
        'other_project_reader',
    ]
    authorized_members = [
        'legacy_admin',
        'legacy_owner',
        'system_admin',
        'project_admin',
        'project_member',
        'project_reader',
        'project_foo',
    ]
    unauthorized_members = [
        'system_member',
        'system_reader',
        'system_foo',
        'other_project_member',
        'other_project_reader',
    ]

    create_authorized_users = [
        'legacy_admin',
        'legacy_owner',
        'system_admin',
        'project_admin',
        'project_member',
        'project_reader',
        'project_foo',
        # The other_* users are allowed because we don't have any check
        # mechanism in the code to validate this, these are validated on
        # the WSGI layer
        'other_project_member',
        'other_project_reader',
    ]

    create_unauthorized_users = [
        'system_member',
        'system_reader',
        'system_foo',
    ]

    # Basic policy test is without enforcing scope (which cinder doesn't
    # yet support) and deprecated rules enabled.
    def setUp(self, enforce_scope=False, enforce_new_defaults=False,
              *args, **kwargs):
        super().setUp(enforce_scope, enforce_new_defaults, *args, **kwargs)
        self.controller = volumes.VolumeController(mock.MagicMock())
        self.api_path = '/v3/%s/volumes' % (self.project_id)

    def _create_volume(self):
        vol_type = test_utils.create_volume_type(self.project_admin_context,
                                                 name='fake_vol_type',
                                                 testcase_instance=self)
        volume = test_utils.create_volume(self.project_member_context,
                                          volume_type_id=vol_type.id,
                                          testcase_instance=self)
        return volume

    @ddt.data(*base.all_users)
    def test_create_volume_policy(self, user_id):
        rule_name = volume_policies.CREATE_POLICY
        url = self.api_path
        req = fake_api.HTTPRequest.blank(url)
        req.method = 'POST'
        body = {"volume": {"size": 1}}
        unauthorized_exceptions = []
        self.common_policy_check(user_id, self.create_authorized_users,
                                 self.create_unauthorized_users,
                                 unauthorized_exceptions,
                                 rule_name, self.controller.create, req,
                                 body=body)

    @ddt.data(*base.all_users)
    @mock.patch('cinder.api.v3.volumes.VolumeController._image_uuid_from_ref',
                return_value=fake_constants.IMAGE_ID)
    @mock.patch('cinder.api.v3.volumes.VolumeController._get_image_snapshot',
                return_value=None)
    @mock.patch('cinder.volume.flows.api.create_volume.'
                'ExtractVolumeRequestTask._get_image_metadata',
                return_value=None)
    def test_create_volume_from_image_policy(
            self, user_id, mock_image_from_ref, mock_image_snap,
            mock_img_meta):
        rule_name = volume_policies.CREATE_FROM_IMAGE_POLICY
        url = self.api_path
        req = fake_api.HTTPRequest.blank(url)
        req.method = 'POST'
        body = {"volume": {"size": 1, "image_id": fake_constants.IMAGE_ID}}
        unauthorized_exceptions = []
        self.common_policy_check(user_id, self.create_authorized_users,
                                 self.create_unauthorized_users,
                                 unauthorized_exceptions,
                                 rule_name, self.controller.create, req,
                                 body=body)

    @ddt.data(*base.all_users)
    def test_create_multiattach_volume_policy(self, user_id):
        vol_type = test_utils.create_volume_type(
            self.project_admin_context, name='multiattach_type',
            extra_specs={'multiattach': '<is> True'})
        rule_name = volume_policies.MULTIATTACH_POLICY
        url = self.api_path
        req = fake_api.HTTPRequest.blank(url)
        req.method = 'POST'
        body = {"volume": {"size": 1, "volume_type": vol_type.id}}

        # Relax the CREATE_POLICY in order to get past that check.
        self.policy.set_rules({volume_policies.CREATE_POLICY: ""},
                              overwrite=False)

        unauthorized_exceptions = []
        self.common_policy_check(user_id, self.create_authorized_users,
                                 self.create_unauthorized_users,
                                 unauthorized_exceptions,
                                 rule_name, self.controller.create, req,
                                 body=body)

    @ddt.data(*base.all_users)
    def test_get_volume_policy(self, user_id):
        volume = self._create_volume()
        rule_name = volume_policies.GET_POLICY
        url = '%s/%s' % (self.api_path, volume.id)
        req = fake_api.HTTPRequest.blank(url)
        unauthorized_exceptions = [
            exception.VolumeNotFound,
        ]
        self.common_policy_check(user_id,
                                 self.authorized_readers,
                                 self.unauthorized_readers,
                                 unauthorized_exceptions,
                                 rule_name, self.controller.show, req,
                                 id=volume.id)

    @ddt.data(*base.all_users)
    def test_get_all_volumes_policy(self, user_id):
        self._create_volume()
        rule_name = volume_policies.GET_ALL_POLICY
        url = self.api_path
        req = fake_api.HTTPRequest.blank(url)
        # Generally, any logged in user can list all volumes.
        authorized_users = [user_id]
        unauthorized_users = []
        # The exception is when deprecated rules are disabled, in which case
        # roles are enforced. Users without the 'reader' role should be
        # blocked.
        if self.enforce_new_defaults:
            context = self.create_context(user_id)
            if 'reader' not in context.roles:
                authorized_users = []
                unauthorized_users = [user_id]
        response = self.common_policy_check(user_id, authorized_users,
                                            unauthorized_users, [],
                                            rule_name,
                                            self.controller.index, req)
        # For some users, even if they're authorized, the list of volumes
        # will be empty if they are not in the volume's project.
        empty_response_users = [
            *self.unauthorized_readers,
            # legacy_admin and system_admin do not have a project_id, and
            # so the list of volumes returned will be empty.
            'legacy_admin',
            'system_admin',
        ]
        volumes = response['volumes'] if response else []
        volume_count = 0 if user_id in empty_response_users else 1
        self.assertEqual(volume_count, len(volumes))

    @ddt.data(*base.all_users)
    @mock.patch('cinder.db.volume_encryption_metadata_get')
    def test_get_volume_encryption_meta_policy(self, user_id,
                                               mock_encrypt_meta):
        encryption_key_id = fake_constants.ENCRYPTION_KEY_ID
        mock_encrypt_meta.return_value = (
            {'encryption_key_id': encryption_key_id})
        controller = (
            volume_encryption_metadata.VolumeEncryptionMetadataController())
        volume = self._create_volume()
        rule_name = volume_policies.ENCRYPTION_METADATA_POLICY
        url = '%s/%s/encryption' % (self.api_path, volume.id)
        req = fake_api.HTTPRequest.blank(url)
        unauthorized_exceptions = [
            exception.VolumeNotFound,
        ]
        resp = self.common_policy_check(
            user_id, self.authorized_readers,
            self.unauthorized_readers,
            unauthorized_exceptions,
            rule_name, controller.index, req,
            volume.id)
        if user_id in self.authorized_readers:
            self.assertEqual(encryption_key_id, resp['encryption_key_id'])

    @ddt.data(*base.all_users)
    def test_get_volume_tenant_attr_policy(self, user_id):
        controller = volume_tenant_attribute.VolumeTenantAttributeController()
        volume = self._create_volume()
        volume = volume.obj_to_primitive()['versioned_object.data']
        rule_name = volume_policies.TENANT_ATTRIBUTE_POLICY
        url = '%s/%s' % (self.api_path, volume['id'])
        req = fake_api.HTTPRequest.blank(url)
        req.get_db_volume = mock.MagicMock()
        req.get_db_volume.return_value = volume
        resp_obj = mock.MagicMock(obj={'volume': volume})
        unauthorized_exceptions = [
            exception.VolumeNotFound,
        ]
        self.assertNotIn('os-vol-tenant-attr:tenant_id', volume.keys())

        self.common_policy_check(
            user_id, self.authorized_readers,
            self.unauthorized_readers,
            unauthorized_exceptions,
            rule_name, controller.show, req,
            resp_obj, volume['id'], fatal=False)

        if user_id in self.authorized_readers:
            self.assertIn('os-vol-tenant-attr:tenant_id', volume.keys())

    @ddt.data(*base.all_users)
    def test_update_volume_policy(self, user_id):
        volume = self._create_volume()
        rule_name = volume_policies.UPDATE_POLICY
        url = '%s/%s' % (self.api_path, volume.id)
        body = {"volume": {"name": "update_name"}}
        req = fake_api.HTTPRequest.blank(url)
        req.method = 'PUT'
        unauthorized_exceptions = [
            exception.VolumeNotFound,
        ]
        self.common_policy_check(
            user_id, self.authorized_members,
            self.unauthorized_members,
            unauthorized_exceptions,
            rule_name, self.controller.update, req,
            id=volume.id, body=body)

    @ddt.data(*base.all_users)
    def test_delete_volume_policy(self, user_id):
        volume = self._create_volume()
        rule_name = volume_policies.DELETE_POLICY
        url = '%s/%s' % (self.api_path, volume.id)
        req = fake_api.HTTPRequest.blank(url)
        req.method = 'DELETE'
        unauthorized_exceptions = [
            exception.VolumeNotFound,
        ]
        self.common_policy_check(
            user_id, self.authorized_members,
            self.unauthorized_members,
            unauthorized_exceptions,
            rule_name, self.controller.delete, req,
            id=volume.id)


class VolumesPolicySecureRbacTest(VolumesPolicyTest):
    create_authorized_users = [
        'legacy_admin',
        'system_admin',
        'project_admin',
        'project_member',
        'other_project_member',
    ]

    create_unauthorized_users = [
        'legacy_owner',
        'system_member',
        'system_reader',
        'system_foo',
        'other_project_reader',
        'project_foo',
        'project_reader',
    ]

    authorized_readers = [
        'legacy_admin',
        'system_admin',
        'project_admin',
        'project_member',
        'project_reader',
    ]
    unauthorized_readers = [
        'legacy_owner',
        'system_member',
        'system_reader',
        'system_foo',
        'project_foo',
        'other_project_member',
        'other_project_reader',
    ]

    authorized_members = [
        'legacy_admin',
        'system_admin',
        'project_admin',
        'project_member',
    ]
    unauthorized_members = [
        'legacy_owner',
        'system_member',
        'system_reader',
        'system_foo',
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
