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

from cinder.api.contrib import volume_image_metadata as image_metadata
from cinder.api import microversions as mv
from cinder.api.v3 import volume_metadata
from cinder import db
from cinder import exception
from cinder.policies import volume_metadata as policy
from cinder.tests.unit.api import fakes as fake_api
from cinder.tests.unit.policies import base
from cinder.tests.unit.policies import test_base
from cinder.tests.unit import utils as test_utils
from cinder.volume import api as volume_api


@ddt.ddt
class VolumeMetadataPolicyTest(base.BasePolicyTest):
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

    # DB validations will throw VolumeNotFound for some contexts
    unauthorized_exceptions = [
        exception.VolumeNotFound,
    ]

    # Basic policy test is without enforcing scope (which cinder doesn't
    # yet support) and deprecated rules enabled.
    def setUp(self, enforce_scope=False, enforce_new_defaults=False,
              *args, **kwargs):
        super().setUp(enforce_scope, enforce_new_defaults, *args, **kwargs)
        self.controller = volume_metadata.Controller()
        self.image_controller = image_metadata.VolumeImageMetadataController()
        self.api_path = '/v3/%s/volumes' % (self.project_id)
        self.api_version = mv.BASE_VERSION

    def _create_volume(self, image_metadata=None, **kwargs):
        vol_type = test_utils.create_volume_type(self.project_admin_context,
                                                 name='fake_vol_type',
                                                 testcase_instance=self)

        volume = test_utils.create_volume(self.project_member_context,
                                          volume_type_id=vol_type.id,
                                          testcase_instance=self, **kwargs)

        for (k, v) in (image_metadata.items() if image_metadata else []):
            db.volume_glance_metadata_create(self.project_admin_context,
                                             volume.id, k, v)
        return volume

    @ddt.data(*base.all_users)
    def test_get_policy(self, user_id):
        volume = self._create_volume()
        rule_name = policy.GET_POLICY
        url = '%s/%s/metadata' % (self.api_path, volume.id)
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)

        self.common_policy_check(user_id, self.authorized_readers,
                                 self.unauthorized_readers,
                                 self.unauthorized_exceptions,
                                 rule_name, self.controller.index, req,
                                 volume_id=volume.id)

    @ddt.data(*base.all_users)
    def test_create_policy(self, user_id):
        volume = self._create_volume()
        rule_name = policy.CREATE_POLICY
        url = '%s/%s/metadata' % (self.api_path, volume.id)
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)
        req.method = 'POST'
        body = {
            "metadata": {
                "name": "metadata0"
            }
        }

        self.common_policy_check(user_id, self.authorized_members,
                                 self.unauthorized_members,
                                 self.unauthorized_exceptions,
                                 rule_name, self.controller.create, req,
                                 volume_id=volume.id, body=body)

    @ddt.data(*base.all_users)
    def test_update_policy(self, user_id):
        volume = self._create_volume(metadata={"foo": "bar"})
        rule_name = policy.UPDATE_POLICY
        url = '%s/%s/metadata' % (self.api_path, volume.id)
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)
        req.method = 'PUT'
        body = {
            # Not sure why, but the API code expects the body to contain
            # a "meta" (not "metadata") dict.
            "meta": {
                "foo": "zap"
            }
        }

        self.common_policy_check(user_id, self.authorized_members,
                                 self.unauthorized_members,
                                 self.unauthorized_exceptions,
                                 rule_name, self.controller.update, req,
                                 volume_id=volume.id, id='foo', body=body)

    @ddt.data(*base.all_users)
    def test_delete_policy(self, user_id):
        volume = self._create_volume(metadata={"foo": "bar"})
        rule_name = policy.DELETE_POLICY
        url = '%s/%s/metadata/foo' % (self.api_path, volume.id)
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)
        req.method = 'DELETE'

        # Relax the GET_POLICY in order to get past that check.
        self.policy.set_rules({policy.GET_POLICY: ""},
                              overwrite=False)

        self.common_policy_check(user_id, self.authorized_members,
                                 self.unauthorized_members,
                                 self.unauthorized_exceptions,
                                 rule_name, self.controller.delete, req,
                                 volume_id=volume.id, id='foo')

    @ddt.data(*base.all_users)
    def test_image_metadata_show_policy(self, user_id):
        image_metadata = {
            "up": "down",
            "left": "right"
        }
        volume = self._create_volume(image_metadata)
        volume = volume.obj_to_primitive()['versioned_object.data']
        rule_name = policy.IMAGE_METADATA_SHOW_POLICY
        url = '%s/%s' % (self.api_path, volume['id'])
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)
        req.get_db_volume = mock.MagicMock()
        req.get_db_volume.return_value = volume
        resp_obj = mock.MagicMock(obj={'volume': volume})

        self.assertNotIn('volume_image_metadata', volume.keys())

        self.common_policy_check(user_id, self.authorized_readers,
                                 self.unauthorized_readers,
                                 self.unauthorized_exceptions,
                                 rule_name,
                                 self.image_controller.show, req,
                                 resp_obj, id=volume['id'], fatal=False)

        if user_id in self.authorized_readers:
            self.assertDictEqual(image_metadata,
                                 volume['volume_image_metadata'])

    @ddt.data(*base.all_users)
    def test_image_metadata_set_policy(self, user_id):
        volume = self._create_volume()
        rule_name = policy.IMAGE_METADATA_SET_POLICY
        url = '%s/%s/action' % (self.api_path, volume.id)
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)
        req.method = 'POST'
        body = {
            "os-set_image_metadata": {
                "metadata": {
                    "image_name": "my_image",
                }
            }
        }

        self.common_policy_check(user_id, self.authorized_members,
                                 self.unauthorized_members,
                                 self.unauthorized_exceptions,
                                 rule_name,
                                 self.image_controller.create, req,
                                 id=volume.id, body=body)

    @ddt.data(*base.all_users)
    def test_image_metadata_remove_policy(self, user_id):
        volume = self._create_volume(image_metadata={"foo": "bar"})
        rule_name = policy.IMAGE_METADATA_REMOVE_POLICY
        url = '%s/%s/action' % (self.api_path, volume.id)
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)
        req.method = 'POST'
        body = {
            "os-unset_image_metadata": {
                "key": "foo"
            }
        }

        self.common_policy_check(user_id, self.authorized_members,
                                 self.unauthorized_members,
                                 self.unauthorized_exceptions,
                                 rule_name,
                                 self.image_controller.delete, req,
                                 id=volume.id, body=body)

    # NOTE(abishop):
    # The following code is a work in progress, and work is deferred until
    # Yoga. This is because the UPDATE_ADMIN_METADATA_POLICY rule is
    # unchanged in Xena (it's RULE_ADMIN_API). This test will be necessary
    # when RULE_ADMIN_API is deprecated in Yoga.
    #
    # @ddt.data(*base.all_users)
    # def test_update_admin_metadata_policy(self, user_id):
    #     volume = self._create_volume()
    #     rule_name = policy.UPDATE_ADMIN_METADATA_POLICY
    #     url = '%s/%s/action' % (self.api_path, volume.id)
    #     req = fake_api.HTTPRequest.blank(url, version=self.api_version)
    #     req.method = 'POST'
    #     body = {
    #         "os-update_readonly_flag": {
    #             "readonly": True
    #         }
    #     }
    #
    #     # Only this test needs a VolumeActionsController
    #     ext_mgr = extensions.ExtensionManager()
    #     controller = volume_actions.VolumeActionsController(ext_mgr)
    #
    #     # Relax the UPDATE_READONLY_POLICY in order to get past that check.
    #     self.policy.set_rules({va_policy.UPDATE_READONLY_POLICY: ""},
    #                           overwrite=False)
    #
    #     self.common_policy_check(user_id, self.authorized_admins,
    #                              self.unauthorized_admins,
    #                              self.unauthorized_exceptions,
    #                              rule_name,
    #                              controller._volume_readonly_update, req,
    #                              id=volume.id, body=body)


class VolumeMetadataPolicySecureRbacTest(VolumeMetadataPolicyTest):
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


class VolumePolicyTests(test_base.CinderPolicyTests):
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

    def test_admin_can_delete_metadata(self):
        admin_context = self.admin_context

        volume = self._create_fake_volume(admin_context, metadata={"k": "v"})

        path = '/v3/%(project_id)s/volumes/%(volume_id)s/metadata/%(key)s' % {
            'project_id': admin_context.project_id, 'volume_id': volume.id,
            'key': 'k'
        }
        response = self._get_request_response(admin_context, path, 'DELETE')
        self.assertEqual(HTTPStatus.OK, response.status_int)

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
