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

from cinder.api.contrib import extended_snapshot_attributes as snapshot_attr
from cinder.api import microversions as mv
from cinder.api.v3 import snapshots
from cinder import exception
from cinder.policies import snapshots as policy
from cinder.tests.unit.api import fakes as fake_api
from cinder.tests.unit.policies import base
from cinder.tests.unit import utils as test_utils


@ddt.ddt
class SnapshotsPolicyTest(base.BasePolicyTest):
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

    # DB validations will throw SnapshotNotFound for some contexts
    unauthorized_exceptions = [
        exception.SnapshotNotFound,
    ]

    # Basic policy test is without enforcing scope (which cinder doesn't
    # yet support) and deprecated rules enabled.
    def setUp(self, enforce_scope=False, enforce_new_defaults=False,
              *args, **kwargs):
        super().setUp(enforce_scope, enforce_new_defaults, *args, **kwargs)
        self.controller = snapshots.SnapshotsController()
        self.api_path = '/v3/%s/snapshots' % (self.project_id)
        self.api_version = mv.BASE_VERSION
        self.vol_type = test_utils.create_volume_type(
            self.project_admin_context,
            name='fake_vol_type', testcase_instance=self)

    def _create_volume(self, **kwargs):
        volume = test_utils.create_volume(self.project_member_context,
                                          volume_type_id=self.vol_type.id,
                                          testcase_instance=self, **kwargs)
        return volume

    def _create_snapshot(self, **kwargs):
        volume = self._create_volume(**kwargs)
        snapshot = test_utils.create_snapshot(self.project_member_context,
                                              volume_id=volume.id,
                                              testcase_instance=self, **kwargs)
        return snapshot

    @ddt.data(*base.all_users)
    def test_get_all_policy(self, user_id):
        self._create_snapshot()
        rule_name = policy.GET_ALL_POLICY
        url = self.api_path
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)

        # Generally, any logged in user can list all volumes.
        authorized_readers = [user_id]
        unauthorized_readers = []

        # The exception is when deprecated rules are disabled, in which case
        # roles are enforced. Users without the 'reader' role should be
        # blocked.
        if self.enforce_new_defaults:
            context = self.create_context(user_id)
            if 'reader' not in context.roles:
                authorized_readers = []
                unauthorized_readers = [user_id]

        response = self.common_policy_check(user_id, authorized_readers,
                                            unauthorized_readers,
                                            self.unauthorized_exceptions,
                                            rule_name, self.controller.index,
                                            req)

        # For some users, even if they're authorized, the list of snapshots
        # will be empty if they are not in the snapshots's project.
        empty_response_users = [
            *self.unauthorized_readers,
            # legacy_admin and system_admin do not have a project_id, and
            # so the list of snapshots returned will be empty.
            'legacy_admin',
            'system_admin',
        ]
        snapshots = response['snapshots'] if response else []
        snapshot_count = 0 if user_id in empty_response_users else 1
        self.assertEqual(snapshot_count, len(snapshots))

    @ddt.data(*base.all_users)
    def test_get_policy(self, user_id):
        snapshot = self._create_snapshot()
        rule_name = policy.GET_POLICY
        url = '%s/%s' % (self.api_path, snapshot.id)
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)

        self.common_policy_check(user_id, self.authorized_readers,
                                 self.unauthorized_readers,
                                 self.unauthorized_exceptions,
                                 rule_name, self.controller.show, req,
                                 id=snapshot.id)

    @ddt.data(*base.all_users)
    def test_extend_attribute_policy(self, user_id):
        snapshot = self._create_snapshot()
        rule_name = policy.EXTEND_ATTRIBUTE
        url = '%s/%s' % (self.api_path, snapshot.id)
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)

        snapshot_dict = snapshot.obj_to_primitive()['versioned_object.data']
        req.get_db_snapshot = mock.MagicMock()
        req.get_db_snapshot.return_value = snapshot_dict
        resp_obj = mock.MagicMock(obj={'snapshot': snapshot_dict})
        self.assertNotIn('os-extended-snapshot-attributes:project_id',
                         snapshot_dict.keys())

        controller = snapshot_attr.ExtendedSnapshotAttributesController()

        self.common_policy_check(user_id, self.authorized_readers,
                                 self.unauthorized_readers,
                                 self.unauthorized_exceptions,
                                 rule_name, controller.show, req,
                                 resp_obj=resp_obj,
                                 id=snapshot.id, fatal=False)

        if user_id in self.authorized_readers:
            self.assertIn('os-extended-snapshot-attributes:project_id',
                          snapshot_dict.keys())

    @ddt.data(*base.all_users)
    def test_create_policy(self, user_id):
        volume = self._create_volume()
        rule_name = policy.CREATE_POLICY
        url = self.api_path
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)
        req.method = 'POST'
        body = {
            "snapshot": {
                "name": "snap-001",
                "volume_id": volume.id,
            }
        }

        unauthorized_exceptions = [
            exception.VolumeNotFound,
        ]

        self.common_policy_check(user_id, self.authorized_members,
                                 self.unauthorized_members,
                                 unauthorized_exceptions,
                                 rule_name, self.controller.create, req,
                                 body=body)

    @ddt.data(*base.all_users)
    def test_update_policy(self, user_id):
        snapshot = self._create_snapshot()
        rule_name = policy.UPDATE_POLICY
        url = '%s/%s' % (self.api_path, snapshot.id)
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)
        req.method = 'PUT'
        body = {
            "snapshot": {
                "description": "This is yet another snapshot."
            }
        }

        # Relax the GET_POLICY in order to get past that check.
        self.policy.set_rules({policy.GET_POLICY: ""},
                              overwrite=False)

        self.common_policy_check(user_id, self.authorized_members,
                                 self.unauthorized_members,
                                 self.unauthorized_exceptions,
                                 rule_name, self.controller.update, req,
                                 id=snapshot.id, body=body)

    @ddt.data(*base.all_users)
    def test_delete_policy(self, user_id):
        snapshot = self._create_snapshot(status='available')
        rule_name = policy.DELETE_POLICY
        url = '%s/%s' % (self.api_path, snapshot.id)
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)
        req.method = 'DELETE'

        # Relax the GET_POLICY in order to get past that check.
        self.policy.set_rules({policy.GET_POLICY: ""},
                              overwrite=False)

        self.common_policy_check(user_id, self.authorized_members,
                                 self.unauthorized_members,
                                 self.unauthorized_exceptions,
                                 rule_name, self.controller.delete, req,
                                 id=snapshot.id)


class SnapshotsPolicySecureRbacTest(SnapshotsPolicyTest):
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
