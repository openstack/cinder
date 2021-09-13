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

from cinder.api.v3 import volume_transfer
from cinder import context
from cinder import exception
from cinder.objects import volume as volume_obj
from cinder.policies import volume_transfer as vol_transfer_policies
from cinder.tests.unit.api import fakes as fake_api
from cinder.tests.unit.policies import base
from cinder.tests.unit import utils as test_utils
import cinder.transfer
from cinder.volume import api as vol_api
from cinder.volume import volume_utils


@ddt.ddt
class VolumeTransferPolicyTest(base.BasePolicyTest):
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
    accept_authorized_users = [
        'legacy_admin',
        'legacy_owner',
        'system_admin',
        'project_admin',
        'project_member',
        'project_reader',
        'project_foo',
        'other_project_member',
        'other_project_reader',
    ]
    accept_unauthorized_users = [
        'system_member',
        'system_reader',
        'system_foo',
    ]

    # Basic policy test is without enforcing scope (which cinder doesn't
    # yet support) and deprecated rules enabled.
    def setUp(self, enforce_scope=False, enforce_new_defaults=False,
              *args, **kwargs):
        super().setUp(enforce_scope, enforce_new_defaults, *args, **kwargs)
        self.controller = volume_transfer.VolumeTransferController()
        self.api_path = '/v3/%s/os-volume-transfer' % (self.project_id)
        self.volume_transfer_api = cinder.transfer.API()

    def _create_volume(self):
        vol_type = test_utils.create_volume_type(self.project_admin_context,
                                                 name='fake_vol_type',
                                                 testcase_instance=self)
        volume = test_utils.create_volume(self.project_member_context,
                                          volume_type_id=vol_type.id,
                                          testcase_instance=self)
        return volume

    @mock.patch.object(volume_obj.Volume, 'get_by_id')
    def _create_volume_transfer(self, mock_get_vol, volume=None):
        if not volume:
            volume = self._create_volume()
        mock_get_vol.return_value = volume
        return self.volume_transfer_api.create(context.get_admin_context(),
                                               volume.id, 'test-transfer')

    @ddt.data(*base.all_users)
    @mock.patch.object(volume_obj.Volume, 'get_by_id')
    def test_create_volume_transfer_policy(self, user_id, mock_get_vol):
        volume = self._create_volume()
        mock_get_vol.return_value = volume
        rule_name = vol_transfer_policies.CREATE_POLICY
        url = self.api_path
        req = fake_api.HTTPRequest.blank(url)
        req.method = 'POST'
        body = {"transfer": {'volume_id': volume.id}}
        unauthorized_exceptions = [
            exception.VolumeNotFound
        ]
        self.common_policy_check(user_id, self.authorized_members,
                                 self.unauthorized_members,
                                 unauthorized_exceptions,
                                 rule_name, self.controller.create, req,
                                 body=body)

    @ddt.data(*base.all_users)
    @mock.patch.object(volume_obj.Volume, 'get_by_id')
    def test_get_volume_transfer_policy(self, user_id, mock_get_vol):
        vol_transfer = self._create_volume_transfer()
        rule_name = vol_transfer_policies.GET_POLICY
        url = '%s/%s' % (self.api_path, vol_transfer['id'])
        req = fake_api.HTTPRequest.blank(url)
        unauthorized_exceptions = [
            exception.TransferNotFound
        ]
        self.common_policy_check(user_id, self.authorized_readers,
                                 self.unauthorized_readers,
                                 unauthorized_exceptions,
                                 rule_name, self.controller.show, req,
                                 id=vol_transfer['id'])

    @ddt.data(*base.all_users)
    def test_get_all_volumes_policy(self, user_id):
        self._create_volume_transfer()
        rule_name = vol_transfer_policies.GET_ALL_POLICY
        url = self.api_path
        req = fake_api.HTTPRequest.blank(url)
        # Generally, any logged in user can list all transfers.
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
            # so the list of backups returned will be empty.
            'legacy_admin',
            'system_admin',
        ]
        transfers = response['transfers'] if response else []
        transfer_count = 0 if user_id in empty_response_users else 1
        self.assertEqual(transfer_count, len(transfers))

    @ddt.data(*base.all_users)
    @mock.patch.object(volume_obj.Volume, 'get_by_id')
    @mock.patch.object(volume_utils, 'notify_about_volume_usage')
    def test_delete_volume_transfer_policy(self, user_id, mock_get_vol,
                                           mock_notify):
        vol_transfer = self._create_volume_transfer()
        rule_name = vol_transfer_policies.DELETE_POLICY
        url = '%s/%s' % (self.api_path, vol_transfer['id'])
        req = fake_api.HTTPRequest.blank(url)
        req.method = 'DELETE'
        unauthorized_exceptions = [
            exception.TransferNotFound
        ]
        self.common_policy_check(user_id, self.authorized_members,
                                 self.unauthorized_members,
                                 unauthorized_exceptions,
                                 rule_name, self.controller.delete, req,
                                 id=vol_transfer['id'])

    @ddt.data(*base.all_users)
    @mock.patch('cinder.transfer.api.QUOTAS')
    @mock.patch.object(volume_obj.Volume, 'get_by_id')
    @mock.patch.object(volume_utils, 'notify_about_volume_usage')
    def test_accept_volume_transfer_policy(self, user_id, mock_notify,
                                           mock_get_vol, mock_quotas):
        volume = self._create_volume()
        vol_transfer = self._create_volume_transfer(volume=volume)
        mock_get_vol.return_value = volume
        rule_name = vol_transfer_policies.ACCEPT_POLICY
        url = '%s/%s/accept' % (self.api_path, vol_transfer['id'])
        req = fake_api.HTTPRequest.blank(url)
        req.method = 'POST'
        body = {"accept": {'auth_key': vol_transfer['auth_key']}}
        unauthorized_exceptions = [
            exception.TransferNotFound
        ]
        with mock.patch.object(vol_api.API, 'accept_transfer'):
            self.common_policy_check(user_id, self.accept_authorized_users,
                                     self.accept_unauthorized_users,
                                     unauthorized_exceptions,
                                     rule_name, self.controller.accept, req,
                                     id=vol_transfer['id'], body=body)


class VolumeTransferPolicySecureRbacTest(VolumeTransferPolicyTest):
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
    # This is a special case since other project member should be
    # allowed to accept the transfer of a volume
    accept_authorized_users = authorized_members.copy()
    accept_authorized_users.append('other_project_member')
    accept_unauthorized_users = unauthorized_members.copy()
    accept_unauthorized_users.remove('other_project_member')

    def setUp(self, *args, **kwargs):
        # Test secure RBAC by disabling deprecated policy rules (scope
        # is still not enabled).
        super().setUp(enforce_scope=False, enforce_new_defaults=True,
                      *args, **kwargs)
