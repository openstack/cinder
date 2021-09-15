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
from cinder import exception
from cinder.objects import fields
from cinder.policies import group_actions as group_policies
from cinder.tests.unit.api import fakes as fake_api
from cinder.tests.unit.policies import base
from cinder.tests.unit import utils as test_utils
from cinder.volume import group_types


@ddt.ddt
class GroupActionPolicyTest(base.BasePolicyTest):
    sysadmins = [
        'legacy_admin',
        'project_admin',
        'system_admin',
    ]
    non_sysadmins = [
        'legacy_owner',
        'project_member',
        'project_reader',
        'project_foo',
        'system_member',
        'system_reader',
        'system_foo',
        'other_project_member',
        'other_project_reader',
    ]

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
    # Basic policy test is without enforcing scope (which cinder doesn't
    # yet support) and deprecated rules enabled.

    def setUp(self, enforce_scope=False, enforce_new_defaults=False,
              *args, **kwargs):
        super().setUp(enforce_scope, enforce_new_defaults, *args, **kwargs)
        self.controller = groups.GroupsController()
        self.api_path = '/v3/%s/groups' % (self.project_id)
        self.api_version = mv.GROUP_REPLICATION
        self.group_type = group_types.create(self.project_admin_context,
                                             'group_type_name',
                                             {'key3': 'value3'},
                                             is_public=True)
        # not surprisingly, to do a group action you need to get a
        # group, so relax the group:get policy so that these tests
        # will check the group action policy we're interested in
        self.policy.set_rules({"group:get": ""},
                              overwrite=False)

    def _create_group(self, group_status=fields.GroupStatus.AVAILABLE):
        volume_type = test_utils.create_volume_type(self.project_admin_context,
                                                    name="test")
        group = test_utils.create_group(self.project_admin_context,
                                        status=group_status,
                                        group_type_id=self.group_type.id,
                                        volume_type_ids=[volume_type.id])

        test_utils.create_volume(self.project_member_context,
                                 group_id=group.id,
                                 testcase_instance=self,
                                 volume_type_id=volume_type.id)
        return group.id

    @ddt.data(*base.all_users)
    @mock.patch('cinder.group.api.API.enable_replication')
    def test_enable_group_replication_policy(self, user_id,
                                             mock_enable_replication):
        """Test enable group replication policy."""

        # FIXME: this is a very fragile approach
        def fake_enable_rep(context, group):
            context.authorize(group_policies.ENABLE_REP, target_obj=group)

        volume_type = test_utils.create_volume_type(self.project_admin_context,
                                                    name='test_group_policy')

        group = test_utils.create_group(self.project_admin_context,
                                        status=fields.GroupStatus.AVAILABLE,
                                        group_type_id=self.group_type.id,
                                        volume_type_ids=[volume_type.id])

        test_utils.create_volume(self.project_member_context,
                                 group_id=group.id,
                                 testcase_instance=self,
                                 volume_type_id=volume_type.id)

        mock_enable_replication.side_effect = fake_enable_rep
        self.group_type.status = 'enabled'
        rule_name = group_policies.ENABLE_REP
        version = mv.GROUP_REPLICATION
        url = '%s/%s/action' % (self.api_path, group.id)
        req = fake_api.HTTPRequest.blank(url, version=version)
        req.method = 'POST'
        body = {
            "enable_replication": {}
        }
        unauthorized_exceptions = [exception.GroupNotFound]
        self.common_policy_check(user_id, self.authorized_members,
                                 self.unauthorized_members,
                                 unauthorized_exceptions,
                                 rule_name,
                                 self.controller.enable_replication,
                                 req, id=group.id, body=body)
        group.destroy()

    @ddt.data(*base.all_users)
    @mock.patch('cinder.group.api.API.disable_replication')
    def test_disable_group_replication_policy(self, user_id,
                                              mock_disable_replication):
        """Test disable group replication policy."""

        # FIXME: this is a very fragile approach
        def fake_disable_rep(context, group):
            context.authorize(group_policies.DISABLE_REP, target_obj=group)

        volume_type = test_utils.create_volume_type(self.project_admin_context,
                                                    name='test_group_policy')

        group = test_utils.create_group(self.project_admin_context,
                                        status=fields.GroupStatus.AVAILABLE,
                                        group_type_id=self.group_type.id,
                                        volume_type_ids=[volume_type.id])

        test_utils.create_volume(self.project_member_context,
                                 group_id=group.id,
                                 testcase_instance=self,
                                 volume_type_id=volume_type.id)

        mock_disable_replication.side_effect = fake_disable_rep
        rule_name = group_policies.DISABLE_REP
        version = mv.GROUP_REPLICATION
        url = '%s/%s/action' % (self.api_path, group.id)
        req = fake_api.HTTPRequest.blank(url, version=version)
        req.method = 'POST'
        body = {
            "disable_replication": {}
        }
        unauthorized_exceptions = [exception.GroupNotFound]

        self.common_policy_check(user_id, self.authorized_members,
                                 self.unauthorized_members,
                                 unauthorized_exceptions,
                                 rule_name,
                                 self.controller.disable_replication,
                                 req, id=group.id, body=body)
        group.destroy()

    @ddt.data(*base.all_users)
    def test_reset_status_group_policy(self, user_id):
        """Test reset status of group policy."""
        rule_name = group_policies.RESET_STATUS
        group_id = self._create_group(group_status=fields.GroupStatus.ERROR)
        url = '%s/%s/action' % (self.api_path, group_id)
        version = mv.GROUP_VOLUME_RESET_STATUS
        req = fake_api.HTTPRequest.blank(url, version=version)
        req.method = 'POST'
        body = {
            "reset_status": {
                "status": "available"
            }
        }
        unauthorized_exceptions = [exception.GroupNotFound]
        self.common_policy_check(user_id,
                                 self.sysadmins,
                                 self.non_sysadmins,
                                 unauthorized_exceptions,
                                 rule_name,
                                 self.controller.reset_status,
                                 req,
                                 id=group_id,
                                 body=body)

    @ddt.data(*base.all_users)
    def test_delete_group_policy(self, user_id):
        """Test delete group policy."""
        volume_type = test_utils.create_volume_type(self.project_admin_context,
                                                    name='test_group_policy')

        group_1 = test_utils.create_group(self.project_admin_context,
                                          status=fields.GroupStatus.AVAILABLE,
                                          group_type_id=self.group_type.id,
                                          volume_type_ids=[volume_type.id])

        rule_name = group_policies.DELETE_POLICY
        url = '%s/%s' % (self.api_path, group_1.id)
        req = fake_api.HTTPRequest.blank(url, version=mv.GROUP_VOLUME)
        req.method = 'POST'
        body = {
            "delete": {
                "delete-volumes": "false"
            }
        }
        unauthorized_exceptions = [exception.GroupNotFound]
        self.common_policy_check(user_id, self.authorized_members,
                                 self.unauthorized_members,
                                 unauthorized_exceptions,
                                 rule_name, self.controller.delete_group,
                                 req, id=group_1.id, body=body)

    @ddt.data(*base.all_users)
    @mock.patch('cinder.group.api.API.failover_replication')
    def test_fail_over_replication_group_policy(self, user_id,
                                                mock_failover_replication):
        """Test fail over replication group policy."""

        # FIXME: this is a very fragile approach
        def fake_failover_rep(context, group,
                              allow_attached_volume=False,
                              secondary_backend_id=None):
            context.authorize(group_policies.FAILOVER_REP, target_obj=group)

        volume_type = test_utils.create_volume_type(self.project_admin_context,
                                                    name='test_group_policy')

        group_2 = test_utils.create_group(self.project_admin_context,
                                          status=fields.GroupStatus.AVAILABLE,
                                          group_type_id=self.group_type.id,
                                          volume_type_ids=[volume_type.id])

        mock_failover_replication.side_effect = fake_failover_rep
        rule_name = group_policies.FAILOVER_REP
        url = '%s/%s' % (self.api_path, group_2.id)
        req = fake_api.HTTPRequest.blank(url, version=mv.GROUP_REPLICATION)
        req.method = 'POST'
        body = {
            "failover_replication": {
                "allow_attached_volume": "true",
                "secondary_backend_id": "vendor-id-1"
            }
        }
        unauthorized_exceptions = [exception.GroupNotFound]
        self.common_policy_check(user_id, self.authorized_members,
                                 self.unauthorized_members,
                                 unauthorized_exceptions,
                                 rule_name,
                                 self.controller.failover_replication,
                                 req, id=group_2.id, body=body)

    @ddt.data(*base.all_users)
    @mock.patch('cinder.group.api.API.list_replication_targets')
    def test_list_replication_targets_group_policy(self, user_id,
                                                   mock_list_targets):
        """Test list replication targets for a group policy."""

        # FIXME: this is a very fragile approach
        def fake_list_targets(context, group):
            context.authorize(group_policies.LIST_REP, target_obj=group)

        volume_type = test_utils.create_volume_type(self.project_admin_context,
                                                    name='test_group_policy')

        group_2 = test_utils.create_group(self.project_admin_context,
                                          status=fields.GroupStatus.AVAILABLE,
                                          group_type_id=self.group_type.id,
                                          volume_type_ids=[volume_type.id])

        mock_list_targets.side_effect = fake_list_targets
        rule_name = group_policies.LIST_REP
        url = '%s/%s/action' % (self.api_path, group_2.id)
        req = fake_api.HTTPRequest.blank(url, version=mv.GROUP_REPLICATION)
        req.method = 'POST'
        body = {"list_replication_targets": {}}
        unauthorized_exceptions = [exception.GroupNotFound]
        self.common_policy_check(user_id, self.authorized_members,
                                 self.unauthorized_members,
                                 unauthorized_exceptions,
                                 rule_name,
                                 self.controller.list_replication_targets,
                                 req, id=group_2.id, body=body)
        group_2.destroy()


class GroupActionPolicySecureRbacTest(GroupActionPolicyTest):
    sysadmins = [
        'legacy_admin',
        'system_admin',
        'project_admin',
    ]
    non_sysadmins = [
        'legacy_owner',
        'project_member',
        'system_member',
        'system_reader',
        'system_foo',
        'project_reader',
        'project_foo',
        'other_project_member',
        'other_project_reader',
    ]
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

    authorized_members = authorized_users
    unauthorized_members = unauthorized_users

    def setUp(self, *args, **kwargs):
        # Test secure RBAC by disabling deprecated policy rules (scope
        # is still not enabled).
        super().setUp(enforce_scope=False, enforce_new_defaults=True,
                      *args, **kwargs)
