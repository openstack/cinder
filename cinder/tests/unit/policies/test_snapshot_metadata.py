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

from cinder.api import microversions as mv
from cinder.api.v3 import snapshot_metadata
from cinder import exception
from cinder.policies import snapshot_metadata as policy
from cinder.policies import snapshots as snapshots_policy
from cinder.tests.unit.api import fakes as fake_api
from cinder.tests.unit.policies import base
from cinder.tests.unit import utils as test_utils


@ddt.ddt
class SnapshotMetadataPolicyTest(base.BasePolicyTest):
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

    # DB validations will throw SnapshotNotFound for some contexts
    unauthorized_exceptions = [
        exception.SnapshotNotFound,
    ]

    # Basic policy test is without enforcing scope (which cinder doesn't
    # yet support) and deprecated rules enabled.
    def setUp(self, enforce_scope=False, enforce_new_defaults=False,
              *args, **kwargs):
        super().setUp(enforce_scope, enforce_new_defaults, *args, **kwargs)
        self.controller = snapshot_metadata.Controller()
        self.api_path = '/v3/%s/snapshots' % (self.project_id)
        self.api_version = mv.BASE_VERSION
        self.vol_type = test_utils.create_volume_type(
            self.project_admin_context,
            name='fake_vol_type', testcase_instance=self)
        # Relax the snapshots GET_POLICY in order to get past that check.
        self.policy.set_rules({snapshots_policy.GET_POLICY: ""},
                              overwrite=False)

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
    def test_get_policy(self, user_id):
        metadata = {'inside': 'out'}
        snapshot = self._create_snapshot(metadata=metadata)
        rule_name = policy.GET_POLICY
        url = '%s/%s/metadata' % (self.api_path, snapshot.id)
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)

        response = self.common_policy_check(
            user_id, self.authorized_readers,
            self.unauthorized_readers,
            self.unauthorized_exceptions,
            rule_name, self.controller.show,
            req, snapshot_id=snapshot.id, id='inside')

        if user_id in self.authorized_readers:
            self.assertDictEqual(metadata, response['meta'])

    @ddt.data(*base.all_users)
    def test_update_policy(self, user_id):
        snapshot = self._create_snapshot()
        rule_name = policy.UPDATE_POLICY
        url = '%s/%s/metadata' % (self.api_path, snapshot.id)
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)
        req.method = 'POST'
        metadata = {
            'inside': 'out',
            'outside': 'in'
        }
        body = {
            "metadata": {**metadata}
        }

        response = self.common_policy_check(
            user_id, self.authorized_members,
            self.unauthorized_members,
            self.unauthorized_exceptions,
            rule_name, self.controller.update_all,
            req, snapshot_id=snapshot.id, body=body)

        if user_id in self.authorized_members:
            self.assertDictEqual(metadata, response['metadata'])

    @ddt.data(*base.all_users)
    def test_delete_policy(self, user_id):
        metadata = {'inside': 'out'}
        snapshot = self._create_snapshot(metadata=metadata)
        rule_name = policy.DELETE_POLICY
        url = '%s/%s/metadata/inside' % (self.api_path, snapshot.id)
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)
        req.method = 'DELETE'

        # Relax the GET_POLICY in order to get past that check.
        self.policy.set_rules({policy.GET_POLICY: ""},
                              overwrite=False)

        self.common_policy_check(user_id, self.authorized_members,
                                 self.unauthorized_members,
                                 self.unauthorized_exceptions,
                                 rule_name, self.controller.delete, req,
                                 snapshot_id=snapshot.id, id='inside')


class SnapshotMetadataPolicySecureRbacTest(SnapshotMetadataPolicyTest):
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
