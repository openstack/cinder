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

import mock

from cinder import context
from cinder import exception
from cinder import quota_utils
from cinder import test

from keystoneclient import exceptions

from oslo_config import cfg
from oslo_config import fixture as config_fixture

CONF = cfg.CONF


class QuotaUtilsTest(test.TestCase):
    class FakeProject(object):
        def __init__(self, id='foo', parent_id=None):
            self.id = id
            self.parent_id = parent_id
            self.subtree = None
            self.parents = None
            self.domain_id = 'default'

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
        quota_utils._keystone_client(self.context)
        ksclient_class.assert_called_once_with(auth_url=self.auth_url,
                                               session=ksclient_session(),
                                               version=(3, 0))

    @mock.patch('keystoneclient.client.Client')
    def test_get_project_keystoneclient_v2(self, ksclient_class):
        keystoneclient = ksclient_class.return_value
        keystoneclient.version = 'v2.0'
        expected_project = quota_utils.GenericProjectInfo(
            self.context.project_id, 'v2.0')
        project = quota_utils.get_project_hierarchy(
            self.context, self.context.project_id)
        self.assertEqual(expected_project.__dict__, project.__dict__)

    @mock.patch('keystoneclient.client.Client')
    def test_get_project_keystoneclient_v3(self, ksclient_class):
        keystoneclient = ksclient_class.return_value
        keystoneclient.version = 'v3'
        returned_project = self.FakeProject(self.context.project_id, 'bar')
        del returned_project.subtree
        keystoneclient.projects.get.return_value = returned_project
        expected_project = quota_utils.GenericProjectInfo(
            self.context.project_id, 'v3', 'bar')
        project = quota_utils.get_project_hierarchy(
            self.context, self.context.project_id)
        self.assertEqual(expected_project.__dict__, project.__dict__)

    @mock.patch('keystoneclient.client.Client')
    def test_get_project_keystoneclient_v3_with_subtree(self, ksclient_class):
        keystoneclient = ksclient_class.return_value
        keystoneclient.version = 'v3'
        returned_project = self.FakeProject(self.context.project_id, 'bar')
        subtree_dict = {'baz': {'quux': None}}
        returned_project.subtree = subtree_dict
        keystoneclient.projects.get.return_value = returned_project
        expected_project = quota_utils.GenericProjectInfo(
            self.context.project_id, 'v3', 'bar', subtree_dict)
        project = quota_utils.get_project_hierarchy(
            self.context, self.context.project_id, subtree_as_ids=True)
        keystoneclient.projects.get.assert_called_once_with(
            self.context.project_id, parents_as_ids=False, subtree_as_ids=True)
        self.assertEqual(expected_project.__dict__, project.__dict__)

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

    @mock.patch('keystoneclient.client.Client')
    def test__filter_domain_id_from_parents_domain_as_parent(
            self, mock_client):
        # Test with a top level project (domain is direct parent)
        self._setup_mock_ksclient(mock_client, parents={'default': None})
        project = quota_utils.get_project_hierarchy(
            self.context, self.context.project_id, parents_as_ids=True)
        self.assertIsNone(project.parent_id)
        self.assertIsNone(project.parents)

    @mock.patch('keystoneclient.client.Client')
    def test__filter_domain_id_from_parents_domain_as_grandparent(
            self, mock_client):
        # Test with a child project (domain is more than a parent)
        self._setup_mock_ksclient(mock_client,
                                  parents={'bar': {'default': None}})
        project = quota_utils.get_project_hierarchy(
            self.context, self.context.project_id, parents_as_ids=True)
        self.assertEqual('bar', project.parent_id)
        self.assertEqual({'bar': None}, project.parents)

    @mock.patch('keystoneclient.client.Client')
    def test__filter_domain_id_from_parents_no_domain_in_parents(
            self, mock_client):
        # Test that if top most parent is not a domain (to simulate an older
        # keystone version) nothing gets removed from the tree
        parents = {'bar': {'foo': None}}
        self._setup_mock_ksclient(mock_client, parents=parents)
        project = quota_utils.get_project_hierarchy(
            self.context, self.context.project_id, parents_as_ids=True)
        self.assertEqual('bar', project.parent_id)
        self.assertEqual(parents, project.parents)

    @mock.patch('keystoneclient.client.Client')
    def test__filter_domain_id_from_parents_no_parents(
            self, mock_client):
        # Test that if top no parents are present (to simulate an older
        # keystone version) things don't blow up
        self._setup_mock_ksclient(mock_client)
        project = quota_utils.get_project_hierarchy(
            self.context, self.context.project_id, parents_as_ids=True)
        self.assertIsNone(project.parent_id)
        self.assertIsNone(project.parents)

    @mock.patch('cinder.quota_utils._keystone_client')
    def test_validate_nested_projects_with_keystone_v2(self, _keystone_client):
        _keystone_client.side_effect = exceptions.VersionNotAvailable

        self.assertRaises(exception.CinderException,
                          quota_utils.validate_setup_for_nested_quota_use,
                          self.context, [], None)

    @mock.patch('cinder.quota_utils._keystone_client')
    def test_validate_nested_projects_non_cloud_admin(self, _keystone_client):
        # Covers not cloud admin or using old policy.json
        _keystone_client.side_effect = exceptions.Forbidden

        self.assertRaises(exception.CinderException,
                          quota_utils.validate_setup_for_nested_quota_use,
                          self.context, [], None)

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
