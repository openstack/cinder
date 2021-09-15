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
from cinder.api.v3 import group_snapshots
from cinder import exception
from cinder.group import api as group_api
from cinder.objects import fields
from cinder.policies import group_snapshots as group_snap_policies
from cinder.policies import groups as group_policies
from cinder.tests.unit.api import fakes as fake_api
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit.policies import base
from cinder.tests.unit import utils as test_utils
from cinder.volume import manager as volume_manager


@ddt.ddt
class GroupSnapshotsPolicyTest(base.BasePolicyTest):
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

    authorized_members = authorized_users
    unauthorized_members = unauthorized_users

    authorized_readers = authorized_users
    unauthorized_readers = unauthorized_users

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

    # Basic policy test is without enforcing scope (which cinder doesn't
    # yet support) and deprecated rules enabled.
    def setUp(self, enforce_scope=False, enforce_new_defaults=False,
              *args, **kwargs):
        super().setUp(enforce_scope, enforce_new_defaults, *args, **kwargs)
        self.controller = group_snapshots.GroupSnapshotsController()
        self.manager = volume_manager.VolumeManager()
        self.api_path = '/v3/%s/group_snapshots' % (self.project_id)
        self.api_version = mv.GROUP_GROUPSNAPSHOT_PROJECT_ID

    def _create_group_snapshot(
            self, snap_status=fields.GroupSnapshotStatus.AVAILABLE):
        volume_type = test_utils.create_volume_type(self.project_admin_context,
                                                    name="test")

        group = test_utils.create_group(self.project_admin_context,
                                        status=fields.GroupStatus.AVAILABLE,
                                        group_type_id=fake.GROUP_TYPE_ID,
                                        volume_type_ids=[volume_type.id])

        test_utils.create_volume(self.project_member_context,
                                 group_id=group.id,
                                 testcase_instance=self,
                                 volume_type_id=volume_type.id)

        return test_utils.create_group_snapshot(
            self.project_admin_context,
            group_id=group.id,
            status=snap_status,
            group_type_id=group.group_type_id)

    def _create_group_snap_array(self):
        group = test_utils.create_group(self.project_admin_context,
                                        status=fields.GroupStatus.AVAILABLE,
                                        group_type_id=fake.GROUP_TYPE_ID,
                                        volume_type_ids=[fake.VOLUME_TYPE_ID])

        test_utils.create_volume(self.project_member_context,
                                 group_id=group.id,
                                 volume_type_id=fake.VOLUME_TYPE_ID)
        g_snapshots_array = [
            test_utils.create_group_snapshot(
                self.project_admin_context,
                group_id=group.id,
                group_type_id=group.group_type_id) for _ in range(3)]

        return g_snapshots_array

    @ddt.data(*base.all_users)
    def test_create_group_snapshot_policy(self, user_id):
        """Test create a group snapshot."""
        volume_type = test_utils.create_volume_type(self.project_admin_context,
                                                    name='test')

        group = test_utils.create_group(self.project_admin_context,
                                        status=fields.GroupStatus.AVAILABLE,
                                        group_type_id=fake.GROUP_TYPE_ID,
                                        volume_type_ids=[volume_type.id])

        test_utils.create_volume(self.project_member_context,
                                 group_id=group.id,
                                 testcase_instance=self,
                                 volume_type_id=volume_type.id)

        rule_name = group_snap_policies.CREATE_POLICY
        version = mv.GROUP_GROUPSNAPSHOT_PROJECT_ID
        url = self.api_path
        req = fake_api.HTTPRequest.blank(url, version=version)
        req.method = 'POST'
        body = {
            "group_snapshot": {
                "name": "my_group_snapshot",
                "description": "My group snapshot",
                "group_id": group.id,
            }
        }
        unauthorized_exceptions = [exception.GroupNotFound]

        # Relax the group:get policy in order to get past that check.
        self.policy.set_rules({group_policies.GET_POLICY: ""},
                              overwrite=False)

        self.common_policy_check(user_id,
                                 self.authorized_users,
                                 self.unauthorized_users,
                                 unauthorized_exceptions,
                                 rule_name,
                                 self.controller.create,
                                 req,
                                 body=body)
        group.destroy()

    @ddt.data(*base.all_users)
    def test_update_group_snapshot_policy(self, user_id):
        # This call is not implemented in the Block Storage API v3
        # so we need to test group_snap_policies.UPDATE_POLICY directly
        # against the group API
        group_snapshot = self._create_group_snapshot()
        api = group_api.API()
        ctxt = self.create_context(user_id)
        if user_id in self.authorized_members:
            api.update_group_snapshot(ctxt, group_snapshot, {})
        elif user_id in self.unauthorized_members:
            self.assertRaises(exception.PolicyNotAuthorized,
                              api.update_group_snapshot,
                              ctxt,
                              group_snapshot,
                              {})
        else:
            self.fail(f'{user_id} not in authorized or unauthorized members')

    @ddt.data(*base.all_users)
    def test_delete_group_snapshot_policy(self, user_id):
        """Delete group snapshot."""
        # Redirect the RPC call directly to the volume manager.
        rule_name = group_snap_policies.DELETE_POLICY
        group_snapshot = self._create_group_snapshot()
        url = '%s/%s' % (self.api_path, group_snapshot.id)
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)
        req.method = 'DELETE'
        unauthorized_exceptions = [exception.GroupSnapshotNotFound,
                                   exception.InvalidGroupSnapshot]

        # Relax the GET_POLICY in order to get past that check.
        self.policy.set_rules({group_snap_policies.GET_POLICY: ""},
                              overwrite=False)

        self.common_policy_check(user_id,
                                 self.authorized_members,
                                 self.unauthorized_members,
                                 unauthorized_exceptions,
                                 rule_name,
                                 self.controller.delete,
                                 req,
                                 id=group_snapshot.id)

    @ddt.data(*base.all_users)
    def test_get_all_group_snapshot_policy(self, user_id):
        """List group snapshots."""
        self._create_group_snap_array()
        rule_name = group_snap_policies.GET_ALL_POLICY
        url = '%s/detail' % (self.api_path)
        version = mv.GROUP_SNAPSHOTS
        req = fake_api.HTTPRequest.blank(url, version=version)
        unauthorized_exceptions = []

        # NOTE: we intentionally don't use the un/authorized_readers
        # lists in this function because get-all doesn't have a target
        # to authorize against
        #
        # legacy: any logged in user can list all group snapshots
        # (project-specific filtering happens later)
        authorized_users = [user_id]
        unauthorized_users = []
        # ... unless deprecated rules are not allowed, then you
        # must have the 'reader' role to read
        if self.enforce_new_defaults:
            context = self.create_context(user_id)
            if 'reader' not in context.roles:
                authorized_users = []
                unauthorized_users = [user_id]
        self.common_policy_check(user_id,
                                 authorized_users,
                                 unauthorized_users,
                                 unauthorized_exceptions,
                                 rule_name,
                                 self.controller.detail,
                                 req)

    @ddt.data(*base.all_users)
    def test_get_group_snapshot_policy(self, user_id):
        """Show group snapshot."""

        group_snapshot = self._create_group_snapshot()
        rule_name = group_snap_policies.GET_POLICY
        url = '%s/%s' % (self.api_path, group_snapshot.id)
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)
        unauthorized_exceptions = [exception.GroupSnapshotNotFound]
        self.common_policy_check(user_id,
                                 self.authorized_readers,
                                 self.unauthorized_readers,
                                 unauthorized_exceptions,
                                 rule_name,
                                 self.controller.show,
                                 req,
                                 id=group_snapshot.id)

    @ddt.data(*base.all_users)
    @mock.patch('cinder.api.v3.views.group_snapshots.ViewBuilder.detail')
    @mock.patch('cinder.group.api.API.get_group_snapshot')
    def test_group_snapshot_project_attribute_policy(self, user_id,
                                                     mock_api,
                                                     mock_view):
        """Test show group snapshot with project attributes."""

        # FIXME: kind of fragile, but I'm beginning to like this approach
        def mock_view_detail(request, group_snapshot):
            context = request.environ['cinder.context']
            context.authorize(
                group_snap_policies.GROUP_SNAPSHOT_ATTRIBUTES_POLICY)

        group_snapshot = self._create_group_snapshot()
        group_snapshot_id = group_snapshot.id
        mock_api.return_value = group_snapshot
        mock_view.side_effect = mock_view_detail

        rule_name = group_snap_policies.GROUP_SNAPSHOT_ATTRIBUTES_POLICY
        url = '%s/%s' % (self.api_path, group_snapshot_id)
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)

        unauthorized_exceptions = [exception.GroupSnapshotNotFound]
        self.common_policy_check(user_id,
                                 self.sysadmins,
                                 self.non_sysadmins,
                                 unauthorized_exceptions,
                                 rule_name,
                                 self.controller.show,
                                 req,
                                 id=group_snapshot_id)


class GroupSnapshotsPolicySecureRbacTest(GroupSnapshotsPolicyTest):
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
