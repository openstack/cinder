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
import uuid

from cinder import quota
from cinder.tests.functional.api import client
from cinder.tests.functional import functional_helpers
from cinder.volume import configuration


class NestedQuotasTest(functional_helpers._FunctionalTestBase):
    _vol_type_name = 'functional_test_type'

    def setUp(self):
        super(NestedQuotasTest, self).setUp()
        self.api.create_type(self._vol_type_name)
        self._create_project_hierarchy()
        # Need to mock out Keystone so the functional tests don't require other
        # services
        _keystone_client = mock.MagicMock()
        _keystone_client.version = 'v3'
        _keystone_client.projects.get.side_effect = self._get_project
        _keystone_client_get = mock.patch(
            'cinder.quota_utils._keystone_client',
            lambda *args, **kwargs: _keystone_client)
        _keystone_client_get.start()
        self.addCleanup(_keystone_client_get.stop)
        # The QUOTA engine in Cinder is a global variable that lazy loads the
        # quota driver, so even if we change the config for the quota driver,
        # we won't reliably change the driver being used (or change it back)
        # unless the global variables get cleaned up, so using mock instead to
        # simulate this change
        nested_driver = quota.NestedDbQuotaDriver()
        _driver_patcher = mock.patch(
            'cinder.quota.QuotaEngine._driver', new=nested_driver)
        _driver_patcher.start()
        self.addCleanup(_driver_patcher.stop)
        # Default to using the top parent in the hierarchy
        self._update_project(self.A.id)

    def _get_flags(self):
        f = super(NestedQuotasTest, self)._get_flags()
        f['volume_driver'] = (
            {'v': 'cinder.tests.fake_driver.FakeLoggingVolumeDriver',
             'g': configuration.SHARED_CONF_GROUP})
        f['default_volume_type'] = {'v': self._vol_type_name}
        return f

    # Currently we use 413 error for over quota
    over_quota_exception = client.OpenStackApiException413

    def _create_project_hierarchy(self):
        """Sets up the nested hierarchy show below.

        +-----------+
        |     A     |
        |    / \    |
        |   B   C   |
        |  /        |
        | D         |
        +-----------+
        """
        self.A = self.FakeProject()
        self.B = self.FakeProject(parent_id=self.A.id)
        self.C = self.FakeProject(parent_id=self.A.id)
        self.D = self.FakeProject(parent_id=self.B.id)

        self.B.subtree = {self.D.id: self.D.subtree}
        self.A.subtree = {self.B.id: self.B.subtree, self.C.id: self.C.subtree}

        self.A.parents = None
        self.B.parents = {self.A.id: None}
        self.C.parents = {self.A.id: None}
        self.D.parents = {self.B.id: self.B.parents}

        # project_by_id attribute is used to recover a project based on its id.
        self.project_by_id = {self.A.id: self.A, self.B.id: self.B,
                              self.C.id: self.C, self.D.id: self.D}

    class FakeProject(object):
        _dom_id = uuid.uuid4().hex

        def __init__(self, parent_id=None):
            self.id = uuid.uuid4().hex
            self.parent_id = parent_id
            self.domain_id = self._dom_id
            self.subtree = None
            self.parents = None

    def _get_project(self, project_id, *args, **kwargs):
        return self.project_by_id[project_id]

    def _create_volume(self):
        return self.api.post_volume({'volume': {'size': 1}})

    def test_default_quotas_enforced(self):
        # Should be able to create volume on parent project by default
        created_vol = self._create_volume()
        self._poll_volume_while(created_vol['id'], ['creating'], 'available')
        self._update_project(self.B.id)
        # Shouldn't be able to create volume on child project by default
        self.assertRaises(self.over_quota_exception, self._create_volume)

    def test_update_child_with_parent_default_quota(self):
        # Make sure we can update to a reasonable value
        self.api.quota_set(self.B.id, {'volumes': 5})
        # Ensure that the update took and we can create a volume
        self._poll_volume_while(
            self._create_volume()['id'], ['creating'], 'available')

    def test_quota_update_child_greater_than_parent(self):
        self.assertRaises(
            client.OpenStackApiException400,
            self.api.quota_set, self.B.id, {'volumes': 11})

    def test_child_soft_limit_propagates_to_parent(self):
        self.api.quota_set(self.B.id, {'volumes': 0})
        self.api.quota_set(self.D.id, {'volumes': -1})
        self._update_project(self.D.id)
        self.assertRaises(self.over_quota_exception, self._create_volume)

    def test_child_quota_hard_limits_affects_parents_allocated(self):
        self.api.quota_set(self.B.id, {'volumes': 5})
        self.api.quota_set(self.C.id, {'volumes': 3})
        alloc = self.api.quota_get(self.A.id)['volumes']['allocated']
        self.assertEqual(8, alloc)
        self.assertRaises(client.OpenStackApiException400,
                          self.api.quota_set, self.C.id, {'volumes': 6})

    def _update_quota_and_def_type(self, project_id, quota):
        self.api.quota_set(project_id, quota)
        type_updates = {'%s_%s' % (key, self._vol_type_name): val for key, val
                        in quota.items() if key != 'per_volume_gigabytes'}
        return self.api.quota_set(project_id, type_updates)

    def test_grandchild_soft_limit_propagates_up(self):
        quota = {'volumes': -1, 'gigabytes': -1, 'per_volume_gigabytes': -1}
        self._update_quota_and_def_type(self.B.id, quota)
        self._update_quota_and_def_type(self.D.id, quota)
        self._update_project(self.D.id)
        # Create two volumes in the grandchild project and ensure grandparent's
        # allocated is updated accordingly
        vol = self._create_volume()
        self._create_volume()
        self._update_project(self.A.id)
        alloc = self.api.quota_get(self.A.id)['volumes']['allocated']
        self.assertEqual(2, alloc)
        alloc = self.api.quota_get(self.B.id)['volumes']['allocated']
        self.assertEqual(2, alloc)
        # Ensure delete reduces the quota
        self._update_project(self.D.id)
        self.api.delete_volume(vol['id'])
        self._poll_volume_while(vol['id'], ['deleting'])
        self._update_project(self.A.id)
        alloc = self.api.quota_get(self.A.id)['volumes']['allocated']
        self.assertEqual(1, alloc)
        alloc = self.api.quota_get(self.B.id)['volumes']['allocated']
        self.assertEqual(1, alloc)
