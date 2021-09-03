# Copyright 2021 Red Hat, Inc.
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

import ddt

from cinder.api import microversions as mv
from cinder.api.v3 import groups
from cinder.objects import group as group_obj
from cinder.policies import groups as group_policies
from cinder.tests.unit.api import fakes as fake_api
from cinder.tests.unit import fake_constants
from cinder.tests.unit.policies import base
from cinder.tests.unit import utils as test_utils


@ddt.ddt
class GroupsPolicyTest(base.BasePolicyTest):

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
        'other_project_member',
        'other_project_reader',
        'system_member',
        'system_reader',
        'system_foo',
    ]

    authorized_show = authorized_members
    unauthorized_show = unauthorized_members

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

    def setUp(self, enforce_scope=False, enforce_new_defaults=False, *args,
              **kwargs):
        super().setUp(enforce_scope, enforce_new_defaults, *args, **kwargs)
        self.controller = groups.GroupsController()
        self.api_path = '/v3/%s/groups' % (self.project_id)
        self.api_version = mv.GROUP_VOLUME

    def _create_volume_type(self):
        vol_type = test_utils.create_volume_type(self.project_admin_context,
                                                 name='fake_vol_type')
        return vol_type

    @ddt.data(*base.all_users)
    @mock.patch('cinder.group.api.GROUP_QUOTAS')
    @mock.patch('cinder.db.group_type_get')
    def test_create_group_policy(self, user_id, mock_get_type, mock_quotas):
        vol_type = self._create_volume_type()
        grp_type = {'id': fake_constants.GROUP_TYPE_ID, 'name': 'group_type'}
        mock_get_type.return_value = grp_type
        rule_name = group_policies.CREATE_POLICY
        url = self.api_path
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)
        req.method = 'POST'
        body = {"group": {"group_type": fake_constants.GROUP_TYPE_ID,
                          "volume_types": [vol_type.id],
                          "name": "test-group"}}
        unauthorized_exceptions = []
        self.common_policy_check(user_id, self.create_authorized_users,
                                 self.create_unauthorized_users,
                                 unauthorized_exceptions,
                                 rule_name, self.controller.create, req,
                                 body=body)

    @ddt.data(*base.all_users)
    @mock.patch('cinder.group.api.GROUP_QUOTAS')
    @mock.patch.object(group_obj.Group, 'get_by_id')
    def test_get_group_policy(self, user_id, mock_get, mock_quotas):
        group = test_utils.create_group(
            self.project_admin_context,
            group_type_id=fake_constants.GROUP_TYPE_ID)
        mock_get.return_value = group
        rule_name = group_policies.GET_POLICY
        url = '%s/%ss' % (self.api_path, group.id)
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)
        unauthorized_exceptions = []
        self.common_policy_check(user_id,
                                 self.authorized_show,
                                 self.unauthorized_show,
                                 unauthorized_exceptions,
                                 rule_name,
                                 self.controller.show,
                                 req,
                                 id=group.id)

    @ddt.data(*base.all_users)
    def test_get_all_groups_policy(self, user_id):
        test_utils.create_group(
            self.project_admin_context,
            group_type_id=fake_constants.GROUP_TYPE_ID)
        rule_name = group_policies.GET_ALL_POLICY
        url = self.api_path
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)
        # Generally, any logged in user can list all groups.
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
        groups = response['groups'] if response else []
        group_count = 0 if user_id in empty_response_users else 1
        self.assertEqual(group_count, len(groups))

    @ddt.data(*base.all_users)
    @mock.patch('cinder.group.api.GROUP_QUOTAS')
    @mock.patch.object(group_obj.Group, 'get_by_id')
    def test_delete_group_policy(self, user_id, mock_get, mock_quotas):
        group = test_utils.create_group(
            self.project_admin_context,
            group_type_id=fake_constants.GROUP_TYPE_ID)
        mock_get.return_value = group
        rule_name = group_policies.UPDATE_POLICY
        url = '%s/%s' % (self.api_path, group.id)
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)
        req.method = 'PUT'
        body = {"group": {"name": "test-update-group"}}
        unauthorized_exceptions = []

        # need to get past the GET_POLICY check
        self.policy.set_rules({group_policies.GET_POLICY: ""},
                              overwrite=False)

        self.common_policy_check(user_id, self.authorized_members,
                                 self.unauthorized_members,
                                 unauthorized_exceptions,
                                 rule_name, self.controller.update, req,
                                 id=group.id, body=body)


class GroupsPolicySecureRbacTest(GroupsPolicyTest):

    unauthorized_readers = [
        'legacy_owner',
        'system_member',
        'system_reader',
        'system_foo',
        'other_project_member',
        'other_project_reader',
        'project_foo',
    ]
    authorized_show = [
        'legacy_admin',
        'system_admin',
        'project_admin',
        'project_member',
        'project_reader',
    ]
    unauthorized_show = [
        'legacy_owner',
        'project_foo',
        'system_member',
        'system_reader',
        'system_foo',
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
        'project_reader',
        'project_foo',
        'system_member',
        'system_reader',
        'system_foo',
        'other_project_member',
        'other_project_reader',
    ]

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

    def setUp(self, *args, **kwargs):
        # Test secure RBAC by disabling deprecated policy rules (scope
        # is still not enabled).
        super().setUp(enforce_scope=False, enforce_new_defaults=True,
                      *args, **kwargs)
