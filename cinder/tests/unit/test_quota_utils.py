# Copyright 2016 OpenStack Foundation
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

from oslo_config import cfg
from oslo_config import fixture as config_fixture

from cinder.api import api_utils
from cinder import context
from cinder import exception
from cinder import quota_utils
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import test


CONF = cfg.CONF


class QuotaUtilsTest(test.TestCase):

    def setUp(self):
        super(QuotaUtilsTest, self).setUp()

        self.auth_url = 'http://localhost:5000'
        self.context = context.RequestContext('fake_user', 'fake_proj_id')
        self.fixture = self.useFixture(config_fixture.Config(CONF))
        self.fixture.config(auth_url=self.auth_url, group='keystone_authtoken')

    @mock.patch('keystoneclient.client.Client')
    @mock.patch('keystoneauth1.session.Session')
    def test_keystone_client_instantiation(self, ksclient_session,
                                           ksclient_class):
        api_utils._keystone_client(self.context)
        ksclient_class.assert_called_once_with(auth_url=self.auth_url,
                                               session=ksclient_session(),
                                               version=(3, 0))

    @mock.patch('keystoneclient.client.Client')
    @mock.patch('keystoneauth1.session.Session')
    @mock.patch('keystoneauth1.identity.Token')
    def test_keystone_client_instantiation_system_scope(
            self, ks_token, ksclient_session, ksclient_class):
        system_context = context.RequestContext(
            'fake_user', 'fake_proj_id', system_scope='all')
        api_utils._keystone_client(system_context)
        ks_token.assert_called_once_with(
            auth_url=self.auth_url, token=system_context.auth_token,
            system_scope=system_context.system_scope)

    @mock.patch('keystoneclient.client.Client')
    @mock.patch('keystoneauth1.session.Session')
    @mock.patch('keystoneauth1.identity.Token')
    def test_keystone_client_instantiation_domain_scope(
            self, ks_token, ksclient_session, ksclient_class):
        domain_context = context.RequestContext(
            'fake_user', 'fake_proj_id', domain_id='default')
        api_utils._keystone_client(domain_context)
        ks_token.assert_called_once_with(
            auth_url=self.auth_url, token=domain_context.auth_token,
            domain_id=domain_context.domain_id)

    @mock.patch('keystoneclient.client.Client')
    @mock.patch('keystoneauth1.session.Session')
    @mock.patch('keystoneauth1.identity.Token')
    def test_keystone_client_instantiation_project_scope(
            self, ks_token, ksclient_session, ksclient_class):
        project_context = context.RequestContext(
            'fake_user', project_id=fake.PROJECT_ID)
        api_utils._keystone_client(project_context)
        ks_token.assert_called_once_with(
            auth_url=self.auth_url, token=project_context.auth_token,
            project_id=project_context.project_id)

    def _setup_mock_ksclient(self, mock_client, version='v3',
                             subtree=None, parents=None):
        keystoneclient = mock_client.return_value
        keystoneclient.version = version
        proj = self.FakeProject(self.context.project_id)
        proj.subtree = subtree
        if parents:
            proj.parents = parents
            proj.parent_id = next(iter(parents.keys()))
        keystoneclient.projects.get.return_value = proj

    def _process_reserve_over_quota(self, overs, usages, quotas,
                                    expected_ex,
                                    resource='volumes'):
        ctxt = context.get_admin_context()
        ctxt.project_id = 'fake'
        size = 1
        kwargs = {'overs': overs,
                  'usages': usages,
                  'quotas': quotas}
        exc = exception.OverQuota(**kwargs)

        self.assertRaises(expected_ex,
                          quota_utils.process_reserve_over_quota,
                          ctxt, exc,
                          resource=resource,
                          size=size)

    def test_volume_size_exceed_quota(self):
        overs = ['gigabytes']
        usages = {'gigabytes': {'reserved': 1, 'in_use': 9}}
        quotas = {'gigabytes': 10, 'snapshots': 10}
        self._process_reserve_over_quota(
            overs, usages, quotas,
            exception.VolumeSizeExceedsAvailableQuota)

    def test_snapshot_limit_exceed_quota(self):
        overs = ['snapshots']
        usages = {'snapshots': {'reserved': 1, 'in_use': 9}}
        quotas = {'gigabytes': 10, 'snapshots': 10}
        self._process_reserve_over_quota(
            overs, usages, quotas,
            exception.SnapshotLimitExceeded,
            resource='snapshots')

    def test_backup_gigabytes_exceed_quota(self):
        overs = ['backup_gigabytes']
        usages = {'backup_gigabytes': {'reserved': 1, 'in_use': 9}}
        quotas = {'backup_gigabytes': 10}
        self._process_reserve_over_quota(
            overs, usages, quotas,
            exception.VolumeBackupSizeExceedsAvailableQuota,
            resource='backups')

    def test_backup_limit_quota(self):
        overs = ['backups']
        usages = {'backups': {'reserved': 1, 'in_use': 9}}
        quotas = {'backups': 9}
        self._process_reserve_over_quota(
            overs, usages, quotas,
            exception.BackupLimitExceeded,
            resource='backups')

    def test_volumes_limit_quota(self):
        overs = ['volumes']
        usages = {'volumes': {'reserved': 1, 'in_use': 9}}
        quotas = {'volumes': 9}
        self._process_reserve_over_quota(
            overs, usages, quotas,
            exception.VolumeLimitExceeded)

    def test_groups_limit_quota(self):
        overs = ['groups']
        usages = {'groups': {'reserved': 1, 'in_use': 9}}
        quotas = {'groups': 9}
        self._process_reserve_over_quota(
            overs, usages, quotas,
            exception.GroupLimitExceeded,
            resource='groups')

    def test_unknown_quota(self):
        overs = ['unknown']
        usages = {'volumes': {'reserved': 1, 'in_use': 9}}
        quotas = {'volumes': 9}
        self._process_reserve_over_quota(
            overs, usages, quotas,
            exception.UnexpectedOverQuota)

    def test_unknown_quota2(self):
        overs = ['volumes']
        usages = {'volumes': {'reserved': 1, 'in_use': 9}}
        quotas = {'volumes': 9}
        self._process_reserve_over_quota(
            overs, usages, quotas,
            exception.UnexpectedOverQuota,
            resource='snapshots')
