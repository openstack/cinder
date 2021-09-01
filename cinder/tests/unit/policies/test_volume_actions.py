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

from cinder.api.contrib import admin_actions
from cinder.api.contrib import volume_actions
from cinder.api import extensions
from cinder.api import microversions as mv
from cinder.api.v3 import volumes
from cinder import exception
from cinder.objects import fields
from cinder.policies import volume_actions as policy
from cinder.policies import volumes as volume_policy
from cinder.tests.unit.api import fakes as fake_api
from cinder.tests.unit import fake_constants
from cinder.tests.unit.policies import base
from cinder.tests.unit.policies import test_base
from cinder.tests.unit import utils as test_utils
from cinder.volume import api as volume_api
from cinder.volume import manager as volume_manager


@ddt.ddt
class VolumeActionsPolicyTest(base.BasePolicyTest):
    authorized_users = [
        'legacy_admin',
        'legacy_owner',
        'system_admin',
        'project_admin',
        'project_member',
        'project_reader',
        'project_foo',
    ]
    unauthorized_users = [
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

    # Basic policy test is without enforcing scope (which cinder doesn't
    # yet support) and deprecated rules enabled.
    def setUp(self, enforce_scope=False, enforce_new_defaults=False,
              *args, **kwargs):
        super().setUp(enforce_scope, enforce_new_defaults, *args, **kwargs)

        self.ext_mgr = extensions.ExtensionManager()
        self.controller = volume_actions.VolumeActionsController(self.ext_mgr)
        self.admin_controller = admin_actions.VolumeAdminController(
            self.ext_mgr)
        self.volume_controller = volumes.VolumeController(self.ext_mgr)
        self.manager = volume_manager.VolumeManager()
        self.manager.driver = mock.MagicMock()
        self.manager.driver.initialize_connection = mock.MagicMock()
        self.manager.driver.initialize_connection.side_effect = (
            self._initialize_connection)
        self.api_path = '/v3/%s/volumes' % (self.project_id)
        self.api_version = mv.BASE_VERSION

    def _initialize_connection(self, volume, connector):
        return {'data': connector}

    def _create_volume(self, attached=False, **kwargs):
        vol_type = test_utils.create_volume_type(self.project_admin_context,
                                                 name='fake_vol_type',
                                                 testcase_instance=self)
        volume = test_utils.create_volume(self.project_member_context,
                                          volume_type_id=vol_type.id,
                                          testcase_instance=self, **kwargs)

        if attached:
            volume = test_utils.attach_volume(self.project_member_context,
                                              volume.id,
                                              fake_constants.INSTANCE_ID,
                                              'fake_host',
                                              'fake_mountpoint')
        return volume

    @ddt.data(*base.all_users)
    def test_extend_policy(self, user_id):
        volume = self._create_volume()
        rule_name = policy.EXTEND_POLICY
        url = '%s/%s/action' % (self.api_path, volume.id)
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)
        req.method = 'POST'
        body = {
            "os-extend": {
                "new_size": 3
            }
        }

        # DB validations will throw VolumeNotFound for some contexts
        unauthorized_exceptions = [
            exception.VolumeNotFound,
        ]

        self.common_policy_check(user_id, self.authorized_users,
                                 self.unauthorized_users,
                                 unauthorized_exceptions,
                                 rule_name, self.controller._extend, req,
                                 id=volume.id, body=body)

    @ddt.data(*base.all_users)
    def test_extend_attached_policy(self, user_id):
        volume = self._create_volume(attached=True)
        rule_name = policy.EXTEND_ATTACHED_POLICY
        url = '%s/%s/action' % (self.api_path, volume.id)
        req = fake_api.HTTPRequest.blank(url, version=mv.VOLUME_EXTEND_INUSE)
        req.method = 'POST'
        body = {
            "os-extend": {
                "new_size": 3
            }
        }

        unauthorized_exceptions = [
            exception.VolumeNotFound,
        ]

        self.common_policy_check(user_id, self.authorized_users,
                                 self.unauthorized_users,
                                 unauthorized_exceptions,
                                 rule_name, self.controller._extend, req,
                                 id=volume.id, body=body)

    @ddt.data(*base.all_users)
    def test_revert_policy(self, user_id):
        volume = self._create_volume()
        snap = test_utils.create_snapshot(
            self.project_member_context,
            volume.id,
            status=fields.SnapshotStatus.AVAILABLE,
            testcase_instance=self)
        rule_name = policy.REVERT_POLICY
        url = '%s/%s/action' % (self.api_path, volume.id)
        req = fake_api.HTTPRequest.blank(url, version=mv.VOLUME_REVERT)
        req.method = 'POST'
        body = {
            "revert": {
                "snapshot_id": snap.id
            }
        }

        # Relax the volume:GET_POLICY in order to get past that check.
        self.policy.set_rules({volume_policy.GET_POLICY: ""},
                              overwrite=False)

        unauthorized_exceptions = [
            exception.VolumeNotFound,
        ]

        self.common_policy_check(user_id, self.authorized_users,
                                 self.unauthorized_users,
                                 unauthorized_exceptions,
                                 rule_name, self.volume_controller.revert, req,
                                 id=volume.id, body=body)

    @ddt.data(*base.all_users)
    def test_reset_policy(self, user_id):
        volume = self._create_volume(attached=True)
        rule_name = policy.RESET_STATUS
        url = '%s/%s/action' % (self.api_path, volume.id)
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)
        req.method = 'POST'
        body = {
            "os-reset_status": {
                "status": "available",
                "attach_status": "detached",
            }
        }

        unauthorized_exceptions = [
            exception.VolumeNotFound,
        ]

        self.common_policy_check(user_id, self.authorized_admins,
                                 self.unauthorized_admins,
                                 unauthorized_exceptions,
                                 rule_name,
                                 self.admin_controller._reset_status, req,
                                 id=volume.id, body=body)

    @ddt.data(*base.all_users)
    def test_retype_policy(self, user_id):
        volume = self._create_volume()
        test_utils.create_volume_type(self.project_admin_context,
                                      name='another_vol_type',
                                      testcase_instance=self)
        rule_name = policy.RETYPE_POLICY
        url = '%s/%s/action' % (self.api_path, volume.id)
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)
        req.method = 'POST'
        body = {
            "os-retype": {
                "new_type": "another_vol_type",
            }
        }

        unauthorized_exceptions = [
            exception.VolumeNotFound,
        ]

        self.common_policy_check(user_id, self.authorized_users,
                                 self.unauthorized_users,
                                 unauthorized_exceptions,
                                 rule_name, self.controller._retype, req,
                                 id=volume.id, body=body)

    @ddt.data(*base.all_users)
    def test_update_readonly_policy(self, user_id):
        volume = self._create_volume()
        rule_name = policy.UPDATE_READONLY_POLICY
        url = '%s/%s/action' % (self.api_path, volume.id)
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)
        req.method = 'POST'
        body = {
            "os-update_readonly_flag": {
                "readonly": True
            }
        }

        unauthorized_exceptions = [
            exception.VolumeNotFound,
        ]

        self.common_policy_check(user_id, self.authorized_users,
                                 self.unauthorized_users,
                                 unauthorized_exceptions,
                                 rule_name,
                                 self.controller._volume_readonly_update, req,
                                 id=volume.id, body=body)

    @ddt.data(*base.all_users)
    def test_force_delete_policy(self, user_id):
        volume = self._create_volume()
        rule_name = policy.FORCE_DELETE_POLICY
        url = '%s/%s/action' % (self.api_path, volume.id)
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)
        req.method = 'POST'
        body = {
            "os-force_delete": {}
        }

        unauthorized_exceptions = [
            exception.VolumeNotFound,
        ]

        self.common_policy_check(user_id, self.authorized_admins,
                                 self.unauthorized_admins,
                                 unauthorized_exceptions,
                                 rule_name,
                                 self.admin_controller._force_delete, req,
                                 id=volume.id, body=body)

    @ddt.data(*base.all_users)
    @mock.patch('cinder.volume.rpcapi.VolumeAPI.detach_volume')
    @mock.patch('cinder.volume.rpcapi.VolumeAPI.terminate_connection')
    def test_force_detach_policy(self, user_id,
                                 mock_terminate_connection,
                                 mock_detach_volume):
        # Redirect the RPC calls directly to the volume manager.
        # The volume manager needs the volume.id, not the volume.
        def detach_volume(ctxt, volume, connector, force=False):
            return self.manager.detach_volume(ctxt, volume.id,
                                              attachment_id=None,
                                              volume=None)

        def terminate_connection(ctxt, volume, connector, force=False):
            return self.manager.terminate_connection(ctxt, volume.id,
                                                     connector, force)

        mock_detach_volume.side_effect = detach_volume
        mock_terminate_connection.side_effect = terminate_connection

        volume = self._create_volume(attached=True)
        rule_name = policy.FORCE_DETACH_POLICY
        url = '%s/%s/action' % (self.api_path, volume.id)
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)
        req.method = 'POST'
        body = {
            "os-force_detach": {}
        }

        unauthorized_exceptions = [
            exception.VolumeNotFound,
        ]

        self.common_policy_check(user_id, self.authorized_admins,
                                 self.unauthorized_admins,
                                 unauthorized_exceptions,
                                 rule_name,
                                 self.admin_controller._force_detach, req,
                                 id=volume.id, body=body)

    @ddt.data(*base.all_users)
    @mock.patch('cinder.volume.rpcapi.VolumeAPI.copy_volume_to_image')
    @mock.patch('cinder.image.glance.GlanceImageService.create')
    def test_upload_image_policy(self, user_id,
                                 mock_image_create,
                                 mock_copy_volume_to_image):
        # Redirect the RPC calls directly to the volume manager.
        # The volume manager needs the volume.id, not the volume.
        def copy_volume_to_image(ctxt, volume, image_meta):
            return self.manager.copy_volume_to_image(ctxt, volume.id,
                                                     image_meta)

        mock_copy_volume_to_image.side_effect = copy_volume_to_image

        volume = self._create_volume(status='available')
        rule_name = policy.UPLOAD_IMAGE_POLICY
        url = '%s/%s/action' % (self.api_path, volume.id)
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)
        req.method = 'POST'
        body = {
            "os-volume_upload_image": {
                "image_name": "test",
            }
        }

        unauthorized_exceptions = [
            exception.VolumeNotFound,
        ]

        self.common_policy_check(user_id, self.authorized_users,
                                 self.unauthorized_users,
                                 unauthorized_exceptions,
                                 rule_name,
                                 self.controller._volume_upload_image, req,
                                 id=volume.id, body=body)

    @ddt.data(*base.all_users)
    @mock.patch('cinder.volume.rpcapi.VolumeAPI.copy_volume_to_image')
    @mock.patch('cinder.image.glance.GlanceImageService.create')
    def test_upload_public_policy(self, user_id,
                                  mock_image_create,
                                  mock_copy_volume_to_image):
        # Redirect the RPC calls directly to the volume manager.
        # The volume manager needs the volume.id, not the volume.
        def copy_volume_to_image(ctxt, volume, image_meta):
            return self.manager.copy_volume_to_image(ctxt, volume.id,
                                                     image_meta)

        mock_copy_volume_to_image.side_effect = copy_volume_to_image

        volume = self._create_volume(status='available')
        rule_name = policy.UPLOAD_PUBLIC_POLICY
        url = '%s/%s/action' % (self.api_path, volume.id)
        req = fake_api.HTTPRequest.blank(url, version=mv.UPLOAD_IMAGE_PARAMS)
        req.method = 'POST'
        body = {
            "os-volume_upload_image": {
                "image_name": "test",
                "visibility": "public",
            }
        }

        # Relax the UPLOAD_IMAGE_POLICY in order to get past that check.
        self.policy.set_rules({policy.UPLOAD_IMAGE_POLICY: ""},
                              overwrite=False)

        unauthorized_exceptions = [
            exception.VolumeNotFound,
        ]

        self.common_policy_check(user_id, self.authorized_admins,
                                 self.unauthorized_admins,
                                 unauthorized_exceptions,
                                 rule_name,
                                 self.controller._volume_upload_image, req,
                                 id=volume.id, body=body)

    @ddt.data(*base.all_users)
    @mock.patch('cinder.objects.Service.get_by_id')
    def test_migrate_policy(self, user_id, mock_get_service_by_id):
        volume = self._create_volume()
        rule_name = policy.MIGRATE_POLICY
        url = '%s/%s/action' % (self.api_path, volume.id)
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)
        req.method = 'POST'
        body = {
            "os-migrate_volume": {
                "host": "node1@lvm"
            }
        }

        unauthorized_exceptions = [
            exception.VolumeNotFound,
        ]

        self.common_policy_check(user_id, self.authorized_admins,
                                 self.unauthorized_admins,
                                 unauthorized_exceptions,
                                 rule_name,
                                 self.admin_controller._migrate_volume, req,
                                 id=volume.id, body=body)

    @ddt.data(*base.all_users)
    def test_migrate_complete_policy(self, user_id):
        volume = self._create_volume()
        # Can't use self._create_volume() because it would fail when
        # trying to create the volume type a second time.
        new_volume = test_utils.create_volume(self.project_member_context,
                                              testcase_instance=self)
        rule_name = policy.MIGRATE_COMPLETE_POLICY
        url = '%s/%s/action' % (self.api_path, volume.id)
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)
        req.method = 'POST'
        body = {
            "os-migrate_volume_completion": {
                "new_volume": new_volume.id
            }
        }

        unauthorized_exceptions = [
            exception.VolumeNotFound,
        ]

        self.common_policy_check(
            user_id, self.authorized_admins, self.unauthorized_admins,
            unauthorized_exceptions, rule_name,
            self.admin_controller._migrate_volume_completion, req,
            id=volume.id, body=body)

    @ddt.data(*base.all_users)
    @mock.patch('cinder.volume.rpcapi.VolumeAPI.attach_volume')
    def test_attach_policy(self, user_id, mock_attach_volume):
        def attach_volume(context, volume, instance_uuid, host_name,
                          mountpoint, mode):
            return self.manager.attach_volume(context, volume.id,
                                              instance_uuid, host_name,
                                              mountpoint, mode)

        mock_attach_volume.side_effect = attach_volume

        volume = self._create_volume(status='available')
        rule_name = policy.ATTACH_POLICY
        url = '%s/%s/action' % (self.api_path, volume.id)
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)
        req.method = 'POST'
        body = {
            "os-attach": {
                "instance_uuid": fake_constants.INSTANCE_ID,
                "mountpoint": "/dev/vdc"
            }
        }

        unauthorized_exceptions = [
            exception.VolumeNotFound,
        ]

        self.common_policy_check(user_id, self.authorized_users,
                                 self.unauthorized_users,
                                 unauthorized_exceptions,
                                 rule_name, self.controller._attach, req,
                                 id=volume.id, body=body)

    @ddt.data(*base.all_users)
    @mock.patch('cinder.volume.rpcapi.VolumeAPI.detach_volume')
    @mock.patch('cinder.volume.rpcapi.VolumeAPI.terminate_connection')
    def test_detach_policy(self, user_id,
                           mock_terminate_connection,
                           mock_detach_volume):
        # Redirect the RPC calls directly to the volume manager.
        # The volume manager needs the volume.id, not the volume.
        def detach_volume(ctxt, volume, connector, force=False):
            return self.manager.detach_volume(ctxt, volume.id,
                                              attachment_id=None,
                                              volume=None)

        def terminate_connection(ctxt, volume, connector, force=False):
            return self.manager.terminate_connection(ctxt, volume.id,
                                                     connector, force)

        mock_detach_volume.side_effect = detach_volume
        mock_terminate_connection.side_effect = terminate_connection

        volume = self._create_volume(attached=True)
        rule_name = policy.DETACH_POLICY
        url = '%s/%s/action' % (self.api_path, volume.id)
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)
        req.method = 'POST'
        body = {
            "os-detach": {
                "attachment_id": volume.volume_attachment[0].id
            }
        }

        unauthorized_exceptions = [
            exception.VolumeNotFound,
        ]

        self.common_policy_check(user_id, self.authorized_users,
                                 self.unauthorized_users,
                                 unauthorized_exceptions,
                                 rule_name, self.controller._detach, req,
                                 id=volume.id, body=body)

    @ddt.data(*base.all_users)
    def test_begin_detaching_policy(self, user_id):
        volume = self._create_volume(status='in-use', attach_status='attached')
        rule_name = policy.BEGIN_DETACHING_POLICY
        url = '%s/%s/action' % (self.api_path, volume.id)
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)
        req.method = 'POST'
        body = {
            "os-begin_detaching": {}
        }

        unauthorized_exceptions = [
            exception.VolumeNotFound,
        ]

        self.common_policy_check(user_id, self.authorized_users,
                                 self.unauthorized_users,
                                 unauthorized_exceptions,
                                 rule_name, self.controller._begin_detaching,
                                 req, id=volume.id, body=body)

    @ddt.data(*base.all_users)
    def test_reserve_policy(self, user_id):
        volume = self._create_volume(status='available')
        rule_name = policy.RESERVE_POLICY
        url = '%s/%s/action' % (self.api_path, volume.id)
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)
        req.method = 'POST'
        body = {
            "os-reserve": {}
        }

        unauthorized_exceptions = [
            exception.VolumeNotFound,
        ]

        self.common_policy_check(user_id, self.authorized_users,
                                 self.unauthorized_users,
                                 unauthorized_exceptions,
                                 rule_name, self.controller._reserve, req,
                                 id=volume.id, body=body)

    @ddt.data(*base.all_users)
    def test_unreserve_policy(self, user_id):
        volume = self._create_volume(status='reserved')
        rule_name = policy.UNRESERVE_POLICY
        url = '%s/%s/action' % (self.api_path, volume.id)
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)
        req.method = 'POST'
        body = {
            "os-unreserve": {}
        }

        unauthorized_exceptions = [
            exception.VolumeNotFound,
        ]

        self.common_policy_check(user_id, self.authorized_users,
                                 self.unauthorized_users,
                                 unauthorized_exceptions,
                                 rule_name, self.controller._unreserve, req,
                                 id=volume.id, body=body)

    @ddt.data(*base.all_users)
    def test_roll_detaching_policy(self, user_id):
        volume = self._create_volume(status='detaching')
        rule_name = policy.ROLL_DETACHING_POLICY
        url = '%s/%s/action' % (self.api_path, volume.id)
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)
        req.method = 'POST'
        body = {
            "os-roll_detaching": {}
        }

        unauthorized_exceptions = [
            exception.VolumeNotFound,
        ]

        self.common_policy_check(user_id, self.authorized_users,
                                 self.unauthorized_users,
                                 unauthorized_exceptions,
                                 rule_name, self.controller._roll_detaching,
                                 req, id=volume.id, body=body)

    @ddt.data(*base.all_users)
    @mock.patch('cinder.volume.rpcapi.VolumeAPI.initialize_connection')
    def test_initialize_policy(self, user_id, mock_initialize_connection):
        def initialize_connection(*args):
            return self.manager.initialize_connection(*args)

        mock_initialize_connection.side_effect = initialize_connection

        volume = self._create_volume()
        rule_name = policy.INITIALIZE_POLICY
        url = '%s/%s/action' % (self.api_path, volume.id)
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)
        req.method = 'POST'
        body = {
            "os-initialize_connection": {
                "connector": {
                    "platform": "x86_64",
                    "host": "node2",
                    "do_local_attach": False,
                    "ip": "192.168.13.101",
                    "os_type": "linux2",
                    "multipath": False,
                    "initiator": "iqn.1994-05.com.redhat:d16cbb5d31e5"
                }
            }
        }

        unauthorized_exceptions = [
            exception.VolumeNotFound,
        ]

        self.common_policy_check(user_id, self.authorized_users,
                                 self.unauthorized_users,
                                 unauthorized_exceptions,
                                 rule_name,
                                 self.controller._initialize_connection,
                                 req, id=volume.id, body=body)

    @ddt.data(*base.all_users)
    @mock.patch('cinder.volume.rpcapi.VolumeAPI.terminate_connection')
    def test_terminate_policy(self, user_id, mock_terminate_connection):
        def terminate_connection(ctxt, volume, connector, force=False):
            return self.manager.terminate_connection(ctxt, volume.id,
                                                     connector, force=False)

        mock_terminate_connection.side_effect = terminate_connection

        volume = self._create_volume()
        rule_name = policy.TERMINATE_POLICY
        url = '%s/%s/action' % (self.api_path, volume.id)
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)
        req.method = 'POST'
        body = {
            "os-terminate_connection": {
                "connector": {
                    "platform": "x86_64",
                    "host": "node2",
                    "do_local_attach": False,
                    "ip": "192.168.13.101",
                    "os_type": "linux2",
                    "multipath": False,
                    "initiator": "iqn.1994-05.com.redhat:d16cbb5d31e5"
                }
            }
        }

        unauthorized_exceptions = [
            exception.VolumeNotFound,
        ]

        self.common_policy_check(user_id, self.authorized_users,
                                 self.unauthorized_users,
                                 unauthorized_exceptions,
                                 rule_name,
                                 self.controller._terminate_connection,
                                 req, id=volume.id, body=body)


class VolumeActionsPolicySecureRbacTest(VolumeActionsPolicyTest):
    authorized_users = [
        'legacy_admin',
        'system_admin',
        'project_admin',
        'project_member',
    ]
    unauthorized_users = [
        'legacy_owner',
        'system_member',
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


class VolumeProtectionTests(test_base.CinderPolicyTests):
    def test_admin_can_extend_volume(self):
        admin_context = self.admin_context

        volume = self._create_fake_volume(admin_context)
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/action' % {
            'project_id': admin_context.project_id, 'volume_id': volume.id
        }

        body = {"os-extend": {"new_size": "2"}}
        response = self._get_request_response(admin_context, path, 'POST',
                                              body=body)
        self.assertEqual(HTTPStatus.ACCEPTED, response.status_int)

    def test_owner_can_extend_volume(self):
        user_context = self.user_context

        volume = self._create_fake_volume(user_context)
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/action' % {
            'project_id': user_context.project_id, 'volume_id': volume.id
        }

        body = {"os-extend": {"new_size": "2"}}
        response = self._get_request_response(user_context, path, 'POST',
                                              body=body)
        self.assertEqual(HTTPStatus.ACCEPTED, response.status_int)

    @mock.patch.object(volume_api.API, 'get')
    def test_owner_cannot_extend_volume_for_others(self, mock_volume):
        user_context = self.user_context
        non_owner_context = self.other_user_context

        volume = self._create_fake_volume(user_context)
        mock_volume.return_value = volume
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/action' % {
            'project_id': non_owner_context.project_id, 'volume_id': volume.id
        }

        body = {"os-extend": {"new_size": "2"}}
        response = self._get_request_response(non_owner_context, path, 'POST',
                                              body=body)
        self.assertEqual(HTTPStatus.FORBIDDEN, response.status_int)

    def test_admin_can_extend_attached_volume(self):
        admin_context = self.admin_context

        volume = self._create_fake_volume(admin_context)
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/action' % {
            'project_id': admin_context.project_id, 'volume_id': volume.id
        }

        body = {"os-extend": {"new_size": "2"}}
        response = self._get_request_response(
            admin_context, path, 'POST', body=body,
            microversion=mv.VOLUME_EXTEND_INUSE)
        self.assertEqual(HTTPStatus.ACCEPTED, response.status_int)

    def test_owner_can_extend_attached_volume(self):
        user_context = self.user_context

        volume = self._create_fake_volume(user_context)
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/action' % {
            'project_id': user_context.project_id, 'volume_id': volume.id
        }

        body = {"os-extend": {"new_size": "2"}}
        response = self._get_request_response(
            user_context, path, 'POST', body=body,
            microversion=mv.VOLUME_EXTEND_INUSE)
        self.assertEqual(HTTPStatus.ACCEPTED, response.status_int)

    @mock.patch.object(volume_api.API, 'get')
    def test_owner_cannot_extend_attached_volume_for_others(self, mock_volume):
        user_context = self.user_context
        non_owner_context = self.other_user_context

        volume = self._create_fake_volume(user_context)
        mock_volume.return_value = volume
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/action' % {
            'project_id': non_owner_context.project_id, 'volume_id': volume.id
        }

        body = {"os-extend": {"new_size": "2"}}
        response = self._get_request_response(
            non_owner_context, path, 'POST', body=body,
            microversion=mv.VOLUME_EXTEND_INUSE)
        self.assertEqual(HTTPStatus.FORBIDDEN, response.status_int)

    def test_admin_can_retype_volume(self):
        admin_context = self.admin_context

        volume = self._create_fake_volume(admin_context)
        vol_type = self._create_fake_type(admin_context)
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/action' % {
            'project_id': admin_context.project_id, 'volume_id': volume.id
        }

        body = {"os-retype": {"new_type": "%s" % vol_type.name,
                              "migration_policy": "never"}}
        response = self._get_request_response(
            admin_context, path, 'POST', body=body)
        self.assertEqual(HTTPStatus.ACCEPTED, response.status_int)

    def test_owner_can_retype_volume(self):
        user_context = self.user_context

        volume = self._create_fake_volume(user_context)
        vol_type = self._create_fake_type(user_context)
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/action' % {
            'project_id': user_context.project_id, 'volume_id': volume.id
        }

        body = {"os-retype": {"new_type": "%s" % vol_type.name,
                              "migration_policy": "never"}}
        response = self._get_request_response(
            user_context, path, 'POST', body=body)
        self.assertEqual(HTTPStatus.ACCEPTED, response.status_int)

    @mock.patch.object(volume_api.API, 'get')
    def test_owner_cannot_retype_volume_for_others(self, mock_volume):
        user_context = self.user_context
        non_owner_context = self.other_user_context

        volume = self._create_fake_volume(user_context)
        mock_volume.return_value = volume
        vol_type = self._create_fake_type(user_context)
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/action' % {
            'project_id': non_owner_context.project_id, 'volume_id': volume.id
        }

        body = {"os-retype": {"new_type": "%s" % vol_type.name,
                              "migration_policy": "never"}}
        response = self._get_request_response(
            non_owner_context, path, 'POST', body=body)
        self.assertEqual(HTTPStatus.FORBIDDEN, response.status_int)

    def test_admin_can_update_readonly(self):
        admin_context = self.admin_context

        volume = self._create_fake_volume(
            admin_context, admin_metadata={"readonly": "False"})

        path = '/v3/%(project_id)s/volumes/%(volume_id)s/action' % {
            'project_id': admin_context.project_id, 'volume_id': volume.id
        }

        body = {"os-update_readonly_flag": {"readonly": "True"}}
        response = self._get_request_response(
            admin_context, path, 'POST', body=body)
        self.assertEqual(HTTPStatus.ACCEPTED, response.status_int)

    def test_owner_can_update_readonly(self):
        user_context = self.user_context

        volume = self._create_fake_volume(
            user_context, admin_metadata={"readonly": "False"})

        path = '/v3/%(project_id)s/volumes/%(volume_id)s/action' % {
            'project_id': user_context.project_id, 'volume_id': volume.id
        }

        body = {"os-update_readonly_flag": {"readonly": "True"}}
        response = self._get_request_response(
            user_context, path, 'POST', body=body)
        self.assertEqual(HTTPStatus.ACCEPTED, response.status_int)

    @mock.patch.object(volume_api.API, 'get')
    def test_owner_cannot_update_readonly_for_others(self, mock_volume):
        user_context = self.user_context
        non_owner_context = self.other_user_context

        volume = self._create_fake_volume(
            user_context, admin_metadata={"readonly": "False"})
        mock_volume.return_value = volume
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/action' % {
            'project_id': non_owner_context.project_id, 'volume_id': volume.id
        }

        body = {"os-update_readonly_flag": {"readonly": "True"}}
        response = self._get_request_response(
            non_owner_context, path, 'POST', body=body)
        self.assertEqual(HTTPStatus.FORBIDDEN, response.status_int)

    @mock.patch.object(volume_api.API, 'get_volume')
    def test_admin_can_force_delete_volumes(self, mock_volume):
        # Make sure administrators are authorized to force delete volumes
        admin_context = self.admin_context

        volume = self._create_fake_volume(admin_context)
        mock_volume.return_value = volume
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/action' % {
            'project_id': admin_context.project_id, 'volume_id': volume.id
        }
        body = {"os-force_delete": {}}
        response = self._get_request_response(admin_context, path, 'POST',
                                              body=body)

        self.assertEqual(HTTPStatus.ACCEPTED, response.status_int)

    @mock.patch.object(volume_api.API, 'get_volume')
    def test_nonadmin_cannot_force_delete_volumes(self, mock_volume):
        # Make sure volumes only can be force deleted by admin
        user_context = self.user_context

        volume = self._create_fake_volume(user_context)
        mock_volume.return_value = volume
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/action' % {
            'project_id': user_context.project_id, 'volume_id': volume.id
        }
        body = {"os-force_delete": {}}
        response = self._get_request_response(user_context, path, 'POST',
                                              body=body)

        self.assertEqual(HTTPStatus.FORBIDDEN, response.status_int)

    @mock.patch.object(volume_api.volume_rpcapi.VolumeAPI, 'attach_volume')
    @mock.patch.object(volume_api.volume_rpcapi.VolumeAPI, 'detach_volume')
    def test_admin_can_attach_detach_volume(self, mock_detach, mock_attach):
        admin_context = self.admin_context

        volume = self._create_fake_volume(admin_context)
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/action' % {
            'project_id': admin_context.project_id, 'volume_id': volume.id
        }

        body = {"os-attach": {"instance_uuid": fake_constants.UUID1,
                              "mountpoint": "/dev/vdc"}}
        response = self._get_request_response(admin_context, path, 'POST',
                                              body=body)
        self.assertEqual(HTTPStatus.ACCEPTED, response.status_int)

        body = {"os-detach": {}}
        response = self._get_request_response(admin_context, path, 'POST',
                                              body=body)
        self.assertEqual(HTTPStatus.ACCEPTED, response.status_int)

    @mock.patch.object(volume_api.volume_rpcapi.VolumeAPI, 'attach_volume')
    @mock.patch.object(volume_api.volume_rpcapi.VolumeAPI, 'detach_volume')
    def test_owner_can_attach_detach_volume(self, mock_detach, mock_attach):
        user_context = self.user_context

        volume = self._create_fake_volume(user_context)
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/action' % {
            'project_id': user_context.project_id, 'volume_id': volume.id
        }

        body = {"os-attach": {"instance_uuid": fake_constants.UUID1,
                              "mountpoint": "/dev/vdc"}}
        response = self._get_request_response(user_context, path, 'POST',
                                              body=body)
        self.assertEqual(HTTPStatus.ACCEPTED, response.status_int)

        body = {"os-detach": {}}
        response = self._get_request_response(user_context, path, 'POST',
                                              body=body)
        self.assertEqual(HTTPStatus.ACCEPTED, response.status_int)

    @mock.patch.object(volume_api.volume_rpcapi.VolumeAPI, 'attach_volume')
    @mock.patch.object(volume_api.volume_rpcapi.VolumeAPI, 'detach_volume')
    @mock.patch.object(volume_api.API, 'get')
    def test_owner_cannot_attach_detach_volume_for_others(self, mock_volume,
                                                          mock_detach,
                                                          mock_attach):
        user_context = self.user_context
        non_owner_context = self.other_user_context

        volume = self._create_fake_volume(user_context)
        mock_volume.return_value = volume
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/action' % {
            'project_id': non_owner_context.project_id, 'volume_id': volume.id
        }

        body = {"os-attach": {"instance_uuid": fake_constants.UUID1,
                              "mountpoint": "/dev/vdc"}}
        response = self._get_request_response(non_owner_context, path, 'POST',
                                              body=body)
        self.assertEqual(HTTPStatus.FORBIDDEN, response.status_int)

        body = {"os-detach": {}}
        response = self._get_request_response(non_owner_context, path, 'POST',
                                              body=body)
        self.assertEqual(HTTPStatus.FORBIDDEN, response.status_int)

    def test_admin_can_reserve_unreserve_volume(self):
        admin_context = self.admin_context

        volume = self._create_fake_volume(admin_context)
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/action' % {
            'project_id': admin_context.project_id, 'volume_id': volume.id
        }

        body = {"os-reserve": {}}
        response = self._get_request_response(admin_context, path, 'POST',
                                              body=body)
        self.assertEqual(HTTPStatus.ACCEPTED, response.status_int)

        body = {"os-unreserve": {}}
        response = self._get_request_response(admin_context, path, 'POST',
                                              body=body)
        self.assertEqual(HTTPStatus.ACCEPTED, response.status_int)

    def test_owner_can_reserve_unreserve_volume(self):
        user_context = self.user_context

        volume = self._create_fake_volume(user_context)
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/action' % {
            'project_id': user_context.project_id, 'volume_id': volume.id
        }

        body = {"os-reserve": {}}
        response = self._get_request_response(user_context, path, 'POST',
                                              body=body)
        self.assertEqual(HTTPStatus.ACCEPTED, response.status_int)

        body = {"os-unreserve": {}}
        response = self._get_request_response(user_context, path, 'POST',
                                              body=body)
        self.assertEqual(HTTPStatus.ACCEPTED, response.status_int)

    @mock.patch.object(volume_api.API, 'get')
    def test_owner_cannot_reserve_unreserve_volume_for_others(self,
                                                              mock_volume):
        user_context = self.user_context
        non_owner_context = self.other_user_context

        volume = self._create_fake_volume(user_context)
        mock_volume.return_value = volume
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/action' % {
            'project_id': non_owner_context.project_id, 'volume_id': volume.id
        }

        body = {"os-attach": {"instance_uuid": fake_constants.UUID1,
                              "mountpoint": "/dev/vdc"}}
        response = self._get_request_response(non_owner_context, path, 'POST',
                                              body=body)
        self.assertEqual(HTTPStatus.FORBIDDEN, response.status_int)

        body = {"os-detach": {}}
        response = self._get_request_response(non_owner_context, path, 'POST',
                                              body=body)
        self.assertEqual(HTTPStatus.FORBIDDEN, response.status_int)

    @mock.patch.object(volume_api.volume_rpcapi.VolumeAPI,
                       'initialize_connection')
    @mock.patch.object(volume_api.volume_rpcapi.VolumeAPI,
                       'terminate_connection')
    def test_admin_can_initialize_terminate_conn(self, mock_t, mock_i):
        admin_context = self.admin_context

        volume = self._create_fake_volume(admin_context)
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/action' % {
            'project_id': admin_context.project_id, 'volume_id': volume.id
        }

        body = {"os-initialize_connection": {'connector': {}}}
        response = self._get_request_response(admin_context, path, 'POST',
                                              body=body)
        self.assertEqual(HTTPStatus.OK, response.status_int)

        body = {"os-terminate_connection": {'connector': {}}}
        response = self._get_request_response(admin_context, path, 'POST',
                                              body=body)
        self.assertEqual(HTTPStatus.ACCEPTED, response.status_int)

    @mock.patch.object(volume_api.volume_rpcapi.VolumeAPI,
                       'initialize_connection')
    @mock.patch.object(volume_api.volume_rpcapi.VolumeAPI,
                       'terminate_connection')
    def test_owner_can_initialize_terminate_conn(self, mock_t, mock_i):
        user_context = self.user_context

        volume = self._create_fake_volume(user_context)
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/action' % {
            'project_id': user_context.project_id, 'volume_id': volume.id
        }

        body = {"os-initialize_connection": {'connector': {}}}
        response = self._get_request_response(user_context, path, 'POST',
                                              body=body)
        self.assertEqual(HTTPStatus.OK, response.status_int)

        body = {"os-terminate_connection": {'connector': {}}}
        response = self._get_request_response(user_context, path, 'POST',
                                              body=body)
        self.assertEqual(HTTPStatus.ACCEPTED, response.status_int)

    @mock.patch.object(volume_api.volume_rpcapi.VolumeAPI,
                       'initialize_connection')
    @mock.patch.object(volume_api.volume_rpcapi.VolumeAPI,
                       'terminate_connection')
    @mock.patch.object(volume_api.API, 'get')
    def test_owner_cannot_initialize_terminate_conn_for_others(self,
                                                               mock_volume,
                                                               mock_t,
                                                               mock_i):
        user_context = self.user_context
        non_owner_context = self.other_user_context

        volume = self._create_fake_volume(user_context)
        mock_volume.return_value = volume
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/action' % {
            'project_id': non_owner_context.project_id, 'volume_id': volume.id
        }

        body = {"os-initialize_connection": {'connector': {}}}
        response = self._get_request_response(non_owner_context, path, 'POST',
                                              body=body)
        self.assertEqual(HTTPStatus.FORBIDDEN, response.status_int)

        body = {"os-terminate_connection": {'connector': {}}}
        response = self._get_request_response(non_owner_context, path, 'POST',
                                              body=body)
        self.assertEqual(HTTPStatus.FORBIDDEN, response.status_int)

    def test_admin_can_begin_roll_detaching(self):
        admin_context = self.admin_context

        volume = self._create_fake_volume(admin_context, status='in-use',
                                          attach_status='attached')
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/action' % {
            'project_id': admin_context.project_id, 'volume_id': volume.id
        }

        body = {"os-begin_detaching": {}}
        response = self._get_request_response(admin_context, path, 'POST',
                                              body=body)
        self.assertEqual(HTTPStatus.ACCEPTED, response.status_int)

        body = {"os-roll_detaching": {}}
        response = self._get_request_response(admin_context, path, 'POST',
                                              body=body)
        self.assertEqual(HTTPStatus.ACCEPTED, response.status_int)

    def test_owner_can_begin_roll_detaching(self):
        user_context = self.user_context

        volume = self._create_fake_volume(user_context, status='in-use',
                                          attach_status='attached')
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/action' % {
            'project_id': user_context.project_id, 'volume_id': volume.id
        }

        body = {"os-begin_detaching": {}}
        response = self._get_request_response(user_context, path, 'POST',
                                              body=body)
        self.assertEqual(HTTPStatus.ACCEPTED, response.status_int)

        body = {"os-roll_detaching": {}}
        response = self._get_request_response(user_context, path, 'POST',
                                              body=body)
        self.assertEqual(HTTPStatus.ACCEPTED, response.status_int)

    @mock.patch.object(volume_api.API, 'get')
    def test_owner_cannot_begin_roll_detaching_for_others(self, mock_volume):
        user_context = self.user_context
        non_owner_context = self.other_user_context

        volume = self._create_fake_volume(user_context, status='in-use',
                                          attach_status='attached')
        mock_volume.return_value = volume
        path = '/v3/%(project_id)s/volumes/%(volume_id)s/action' % {
            'project_id': non_owner_context.project_id, 'volume_id': volume.id
        }

        body = {"os-begin_detaching": {}}
        response = self._get_request_response(non_owner_context, path, 'POST',
                                              body=body)
        self.assertEqual(HTTPStatus.FORBIDDEN, response.status_int)

        body = {"os-roll_detaching": {}}
        response = self._get_request_response(non_owner_context, path, 'POST',
                                              body=body)
        self.assertEqual(HTTPStatus.FORBIDDEN, response.status_int)
