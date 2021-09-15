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
from cinder.api.v3 import backups
from cinder import exception
from cinder.objects import fields
from cinder.policies import backups as backups_policies
from cinder.tests.unit.api import fakes as fake_api
from cinder.tests.unit.policies import base
from cinder.tests.unit import utils as test_utils


@ddt.ddt
class BackupsPolicyTest(base.BasePolicyTest):

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

    def setUp(self, enforce_scope=False, enforce_new_defaults=False, *args,
              **kwargs):
        super().setUp(enforce_scope, enforce_new_defaults, *args, **kwargs)

        self.override_config('backup_use_same_host', True)

        self.controller = backups.BackupsController()

        self.api_path = '/v3/%s/backups' % (self.project_id)
        self.api_version = mv.BASE_VERSION

    def _create_backup(self):
        backup = test_utils.create_backup(self.project_member_context,
                                          status=fields.BackupStatus.AVAILABLE,
                                          size=1)
        self.addCleanup(backup.destroy)
        return backup

    @ddt.data(*base.all_users)
    def test_get_all_backups_policy(self, user_id):
        self._create_backup()
        rule_name = backups_policies.GET_ALL_POLICY
        url = self.api_path
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)

        # Generally, any logged in user can list all backups.
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

        # For some users, even if they're authorized, the list of backups
        # will be empty if they are not in the backup's project.
        empty_response_users = [
            *self.unauthorized_readers,
            # legacy_admin and system_admin do not have a project_id, and
            # so the list of backups returned will be empty.
            'legacy_admin',
            'system_admin',
        ]
        backups = response['backups'] if response else []
        backup_count = 0 if user_id in empty_response_users else 1
        self.assertEqual(backup_count, len(backups))

    @ddt.data(*base.all_users)
    def test_get_backup_policy(self, user_id):
        backup_id = self._create_backup().id
        rule_name = backups_policies.GET_POLICY
        url = '%s/%s' % (self.api_path, backup_id)
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)

        unauthorized_exceptions = [
            exception.BackupNotFound,
        ]

        self.common_policy_check(user_id, self.authorized_readers,
                                 self.unauthorized_readers,
                                 unauthorized_exceptions,
                                 rule_name, self.controller.show, req,
                                 id=backup_id)

    @ddt.data(*base.all_users)
    def test_create_backup_policy(self, user_id):
        volume = test_utils.create_volume(self.project_member_context,
                                          testcase_instance=self)
        rule_name = backups_policies.CREATE_POLICY
        url = self.api_path
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)
        req.method = 'POST'
        body = {
            "backup": {
                "container": None,
                "description": None,
                "name": "backup001",
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
    def test_update_backup_policy(self, user_id):
        backup_id = self._create_backup().id
        rule_name = backups_policies.UPDATE_POLICY
        url = '%s/%s' % (self.api_path, backup_id)
        req = fake_api.HTTPRequest.blank(url, version=mv.BACKUP_UPDATE)
        req.method = 'PUT'
        body = {
            "backup": {
                "name": "backup666",
            }
        }

        # Relax the GET_POLICY in order to get past that check.
        self.policy.set_rules({backups_policies.GET_POLICY: ""},
                              overwrite=False)

        unauthorized_exceptions = [
            exception.BackupNotFound,
        ]

        self.common_policy_check(user_id, self.authorized_members,
                                 self.unauthorized_members,
                                 unauthorized_exceptions,
                                 rule_name, self.controller.update, req,
                                 id=backup_id, body=body)

    @ddt.data(*base.all_users)
    @mock.patch('cinder.backup.api.API._is_backup_service_enabled',
                return_value=True)
    def test_delete_backup_policy(self, user_id, mock_backup_service_enabled):
        backup_id = self._create_backup().id
        rule_name = backups_policies.DELETE_POLICY
        url = '%s/%s' % (self.api_path, backup_id)
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)
        req.method = 'DELETE'

        # Relax the GET_POLICY in order to get past that check.
        self.policy.set_rules({backups_policies.GET_POLICY: ""},
                              overwrite=False)

        unauthorized_exceptions = [
            exception.BackupNotFound,
        ]

        self.common_policy_check(user_id, self.authorized_members,
                                 self.unauthorized_members,
                                 unauthorized_exceptions,
                                 rule_name, self.controller.delete, req,
                                 id=backup_id)

    @ddt.data(*base.all_users)
    @mock.patch('cinder.backup.api.API._is_backup_service_enabled',
                return_value=True)
    @mock.patch('cinder.backup.rpcapi.BackupAPI.restore_backup')
    def test_restore_backup_policy(self, user_id,
                                   mock_backup_restore,
                                   mock_backup_service_enabled):
        backup_id = self._create_backup().id
        volume = test_utils.create_volume(self.project_member_context,
                                          testcase_instance=self)
        rule_name = backups_policies.RESTORE_POLICY
        url = '%s/%s' % (self.api_path, backup_id)
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)
        req.method = 'POST'
        body = {
            "restore": {
                "volume_id": volume.id
            }
        }

        # Relax the GET_POLICY in order to get past that check.
        self.policy.set_rules({backups_policies.GET_POLICY: ""},
                              overwrite=False)

        unauthorized_exceptions = [
            exception.BackupNotFound,
        ]

        self.common_policy_check(user_id, self.authorized_members,
                                 self.unauthorized_members,
                                 unauthorized_exceptions,
                                 rule_name, self.controller.restore, req,
                                 id=backup_id, body=body)

    @ddt.data(*base.all_users)
    @mock.patch('cinder.backup.api.API._list_backup_hosts')
    @mock.patch('cinder.backup.api.API._get_import_backup')
    @mock.patch('cinder.backup.rpcapi.BackupAPI.import_record')
    def test_import_backup_policy(self, user_id,
                                  mock_import_record,
                                  mock_get_import_backup,
                                  mock_list_backup_hosts):
        def _list_backup_hosts(*args):
            return ['backup-host']

        def _get_import_backup(*args):
            return self._create_backup()

        mock_list_backup_hosts.side_effect = _list_backup_hosts
        mock_get_import_backup.side_effect = _get_import_backup

        rule_name = backups_policies.IMPORT_POLICY
        url = '%s/import_record' % (self.api_path)
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)
        req.method = 'PUT'
        body = {
            "backup-record": {
                "backup_service": "backup-host",
                "backup_url": "eyJzdGF0"
            }
        }

        unauthorized_exceptions = []

        self.common_policy_check(user_id, self.authorized_admins,
                                 self.unauthorized_admins,
                                 unauthorized_exceptions,
                                 rule_name, self.controller.import_record, req,
                                 body=body)

    @ddt.data(*base.all_users)
    @mock.patch('cinder.backup.api.API._get_available_backup_service_host',
                return_value='backup-host')
    @mock.patch('cinder.backup.rpcapi.BackupAPI.export_record',
                return_value={
                    "backup_service": "backup-host",
                    "backup_url": "eyJzdGF0"
                })
    def test_export_backup_policy(self, user_id,
                                  mock_export_record,
                                  mock_get_backup_service_host):
        backup_id = self._create_backup().id
        rule_name = backups_policies.EXPORT_POLICY
        url = '%s/%s/export_record' % (self.api_path, backup_id)
        req = fake_api.HTTPRequest.blank(url, version=self.api_version)

        # Relax the GET_POLICY in order to get past that check.
        self.policy.set_rules({backups_policies.GET_POLICY: ""},
                              overwrite=False)

        unauthorized_exceptions = [
            exception.BackupNotFound,
        ]

        self.common_policy_check(user_id, self.authorized_admins,
                                 self.unauthorized_admins,
                                 unauthorized_exceptions,
                                 rule_name, self.controller.export_record, req,
                                 id=backup_id)

    @ddt.data(*base.all_users)
    def test_backup_attributes_policy(self, user_id):
        backup_id = self._create_backup().id
        # Although we're testing the BACKUP_ATTRIBUTES_POLICY, unauthorized
        # readers will (correctly) fail on the GET_POLICY. For authorized
        # readers, later we'll test the response to verify the
        # BACKUP_ATTRIBUTES_POLICY is properly enforced.
        rule_name = backups_policies.GET_POLICY
        url = '%s/%s' % (self.api_path, backup_id)
        req = fake_api.HTTPRequest.blank(url,
                                         version=mv.BACKUP_PROJECT_USER_ID)

        unauthorized_exceptions = [
            exception.BackupNotFound,
        ]

        response = self.common_policy_check(user_id, self.authorized_readers,
                                            self.unauthorized_readers,
                                            unauthorized_exceptions,
                                            rule_name, self.controller.show,
                                            req, id=backup_id)

        if user_id in self.authorized_readers:
            # Check whether the backup record includes a user_id. Only
            # authorized_admins should see one.
            backup_user_id = response['backup'].get('user_id', None)
            if user_id in self.authorized_admins:
                self.assertIsNotNone(backup_user_id)
            else:
                self.assertIsNone(backup_user_id)


class BackupsPolicySecureRbacTest(BackupsPolicyTest):
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

    # NOTE(Xena): The authorized_admins and unauthorized_admins are the same
    # as the BackupsPolicyTest's. This is because in Xena the "admin only"
    # rules are the legacy RULE_ADMIN_API. This will change in Yoga, when
    # RULE_ADMIN_API will be deprecated in favor of the SYSTEM_ADMIN rule that
    # is scope based.
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

    def setUp(self, *args, **kwargs):
        # Test secure RBAC by disabling deprecated policy rules (scope
        # is still not enabled).
        super().setUp(enforce_scope=False, enforce_new_defaults=True,
                      *args, **kwargs)
