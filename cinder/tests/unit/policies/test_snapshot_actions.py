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

import ddt

from cinder.api.contrib import admin_actions
from cinder.api.contrib import snapshot_actions
from cinder.api import microversions as mv
from cinder import exception
from cinder.policies import snapshot_actions as policy
from cinder.policies import snapshots as snapshots_policy
from cinder.tests.unit.api import fakes as fake_api
from cinder.tests.unit.policies import base
from cinder.tests.unit import utils as test_utils


@ddt.ddt
class SnapshotActionsPolicyTest(base.BasePolicyTest):
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
        self.controller = snapshot_actions.SnapshotActionsController()
        self.admin_controller = admin_actions.SnapshotAdminController()
        self.api_path = '/v3/%s/snapshots' % (self.project_id)
        self.api_version = mv.BASE_VERSION
        # Relax the snapshots GET_POLICY in order to get past that check.
        self.policy.set_rules({snapshots_policy.GET_POLICY: ""},
                              overwrite=False)

    def _create_snapshot(self, **kwargs):
        vol_type = test_utils.create_volume_type(self.project_admin_context,
                                                 name='fake_vol_type',
                                                 testcase_instance=self)

        volume = test_utils.create_volume(self.project_member_context,
                                          volume_type_id=vol_type.id,
                                          testcase_instance=self)

        snapshot = test_utils.create_snapshot(self.project_member_context,
                                              volume_id=volume.id,
                                              testcase_instance=self, **kwargs)
        return snapshot

    @ddt.data(*base.all_users)
    def test_reset_status_policy(self, user_id):
        snapshot = self._create_snapshot(status='error')
        rule_name = policy.RESET_STATUS_POLICY
        url = '%s/%s/action' % (self.api_path, snapshot.id)
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)
        req.method = 'POST'
        body = {
            "os-reset_status": {
                "status": "available",
            }
        }

        self.common_policy_check(user_id, self.authorized_admins,
                                 self.unauthorized_admins,
                                 self.unauthorized_exceptions,
                                 rule_name,
                                 self.admin_controller._reset_status, req,
                                 id=snapshot.id, body=body)

    @ddt.data(*base.all_users)
    def test_update_status_policy(self, user_id):
        snapshot = self._create_snapshot(status='creating')
        rule_name = policy.UPDATE_STATUS_POLICY
        url = '%s/%s/action' % (self.api_path, snapshot.id)
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)
        req.method = 'POST'
        body = {
            "os-update_snapshot_status": {
                "status": "error"
            }
        }

        self.common_policy_check(user_id, self.authorized_members,
                                 self.unauthorized_members,
                                 self.unauthorized_exceptions,
                                 rule_name,
                                 self.controller._update_snapshot_status, req,
                                 id=snapshot.id, body=body)

    @ddt.data(*base.all_users)
    def test_force_delete_policy(self, user_id):
        snapshot = self._create_snapshot(status='error')
        rule_name = policy.FORCE_DELETE_POLICY
        url = '%s/%s/action' % (self.api_path, snapshot.id)
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)
        req.method = 'POST'
        body = {
            "os-force_delete": {}
        }

        self.common_policy_check(user_id, self.authorized_admins,
                                 self.unauthorized_admins,
                                 self.unauthorized_exceptions,
                                 rule_name,
                                 self.admin_controller._force_delete, req,
                                 id=snapshot.id, body=body)


class SnapshotActionsPolicySecureRbacTest(SnapshotActionsPolicyTest):
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
