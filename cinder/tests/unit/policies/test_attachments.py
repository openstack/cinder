# Copyright 2021 Red Hat, Inc.
# All Rights Reserved.
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

import ddt

from cinder.api import microversions as mv
from cinder.api.v3 import attachments
from cinder import exception
from cinder.policies import attachments as attachments_policies
from cinder.tests.unit.api import fakes as fake_api
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit.policies import base
from cinder.tests.unit import utils as test_utils
from cinder.volume import manager as volume_manager


@ddt.ddt
class AttachmentsPolicyTest(base.BasePolicyTest):
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

    # Basic policy test is without enforcing scope (which cinder doesn't
    # yet support) and deprecated rules enabled.
    def setUp(self, enforce_scope=False, enforce_new_defaults=False,
              *args, **kwargs):
        super().setUp(enforce_scope, enforce_new_defaults, *args, **kwargs)

        self.controller = attachments.AttachmentsController()
        self.manager = volume_manager.VolumeManager()
        self.manager.driver = mock.MagicMock()
        self.manager.driver.initialize_connection = mock.MagicMock()
        self.manager.driver.initialize_connection.side_effect = (
            self._initialize_connection)

        self.api_path = '/v3/%s/attachments' % (self.project_id)
        self.api_version = mv.NEW_ATTACH

    def _initialize_connection(self, volume, connector):
        return {'data': connector}

    def _create_attachment(self):
        vol_type = test_utils.create_volume_type(self.project_admin_context,
                                                 name='fake_vol_type',
                                                 testcase_instance=self)
        volume = test_utils.create_volume(self.project_member_context,
                                          volume_type_id=vol_type.id,
                                          admin_metadata={
                                              'attached_mode': 'ro'
                                          },
                                          testcase_instance=self)
        volume = test_utils.attach_volume(self.project_member_context,
                                          volume.id,
                                          fake.INSTANCE_ID,
                                          'fake_host',
                                          'fake_mountpoint')
        return volume.volume_attachment[0].id

    @ddt.data(*base.all_users)
    def test_create_attachment_policy(self, user_id):
        volume = test_utils.create_volume(self.project_member_context,
                                          testcase_instance=self)
        rule_name = attachments_policies.CREATE_POLICY
        url = self.api_path
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)
        req.method = 'POST'
        body = {
            "attachment": {
                "instance_uuid": fake.INSTANCE_ID,
                "volume_uuid": volume.id,
            }
        }

        # Some context return HTTP 404 (rather than 403).
        unauthorized_exceptions = [
            exception.VolumeNotFound,
        ]

        self.common_policy_check(user_id, self.authorized_users,
                                 self.unauthorized_users,
                                 unauthorized_exceptions,
                                 rule_name, self.controller.create, req,
                                 body=body)

    @ddt.data(*base.all_users)
    @mock.patch('cinder.volume.rpcapi.VolumeAPI.attachment_update')
    def test_update_attachment_policy(self, user_id, mock_attachment_update):
        # Redirect the RPC call directly to the volume manager.
        def attachment_update(*args):
            return self.manager.attachment_update(*args)

        mock_attachment_update.side_effect = attachment_update

        rule_name = attachments_policies.UPDATE_POLICY
        attachment_id = self._create_attachment()
        url = '%s/%s' % (self.api_path, attachment_id)
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)
        req.method = 'PUT'
        body = {
            "attachment": {
                "connector": {
                    "initiator": "iqn.1993-08.org.debian: 01: cad181614cec",
                    "ip": "192.168.1.20",
                    "platform": "x86_64",
                    "host": "tempest-1",
                    "os_type": "linux2",
                    "multipath": False,
                    "mountpoint": "/dev/vdb",
                    "mode": "ro"
                }
            }
        }

        unauthorized_exceptions = []

        self.common_policy_check(user_id, self.authorized_users,
                                 self.unauthorized_users,
                                 unauthorized_exceptions,
                                 rule_name, self.controller.update, req,
                                 id=attachment_id, body=body)

    @ddt.data(*base.all_users)
    @mock.patch('cinder.volume.rpcapi.VolumeAPI.attachment_delete')
    def test_delete_attachment_policy(self, user_id, mock_attachment_delete):
        # Redirect the RPC call directly to the volume manager.
        def attachment_delete(*args):
            return self.manager.attachment_delete(*args)

        mock_attachment_delete.side_effect = attachment_delete

        rule_name = attachments_policies.DELETE_POLICY
        attachment_id = self._create_attachment()
        url = '%s/%s' % (self.api_path, attachment_id)
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)
        req.method = 'DELETE'

        unauthorized_exceptions = []

        self.common_policy_check(user_id, self.authorized_users,
                                 self.unauthorized_users,
                                 unauthorized_exceptions,
                                 rule_name, self.controller.delete, req,
                                 id=attachment_id)

    @ddt.data(*base.all_users)
    def test_complete_attachment_policy(self, user_id):
        rule_name = attachments_policies.COMPLETE_POLICY
        attachment_id = self._create_attachment()
        url = '%s/%s/action' % (self.api_path, attachment_id)
        req = fake_api.HTTPRequest.blank(url, version=mv.NEW_ATTACH_COMPLETION)
        req.method = 'POST'
        body = {
            "os-complete": {}
        }

        unauthorized_exceptions = [
            exception.VolumeNotFound,
        ]

        self.common_policy_check(user_id, self.authorized_users,
                                 self.unauthorized_users,
                                 unauthorized_exceptions,
                                 rule_name, self.controller.complete, req,
                                 id=attachment_id, body=body)

    @ddt.data(*base.all_users)
    def test_multiattach_bootable_volume_policy(self, user_id):
        volume = test_utils.create_volume(self.project_member_context,
                                          multiattach=True,
                                          status='in-use',
                                          bootable=True,
                                          testcase_instance=self)
        rule_name = attachments_policies.MULTIATTACH_BOOTABLE_VOLUME_POLICY
        url = self.api_path
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)
        req.method = 'POST'
        body = {
            "attachment": {
                "instance_uuid": fake.INSTANCE_ID,
                "volume_uuid": volume.id,
            }
        }

        # Relax the CREATE_POLICY in order to get past that check, which takes
        # place prior to checking the MULTIATTACH_BOOTABLE_VOLUME_POLICY.
        self.policy.set_rules({attachments_policies.CREATE_POLICY: ""},
                              overwrite=False)

        unauthorized_exceptions = [
            exception.VolumeNotFound,
        ]

        self.common_policy_check(user_id, self.authorized_users,
                                 self.unauthorized_users,
                                 unauthorized_exceptions,
                                 rule_name, self.controller.create, req,
                                 body=body)


class AttachmentsPolicySecureRbacTest(AttachmentsPolicyTest):
    authorized_users = [
        'legacy_admin',
        'system_admin',
        'project_admin',
        'project_member',
    ]

    unauthorized_users = [
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
