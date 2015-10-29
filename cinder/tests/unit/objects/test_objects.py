# Copyright 2015 IBM Corp.
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

from oslo_versionedobjects import fixture

from cinder.objects import base
from cinder import test


# NOTE: The hashes in this list should only be changed if they come with a
# corresponding version bump in the affected objects.
object_data = {
    'Backup': '1.1-cd077ec037f5ad1f5409fd660bd59f53',
    'BackupImport': '1.1-cd077ec037f5ad1f5409fd660bd59f53',
    'BackupList': '1.0-24591dabe26d920ce0756fe64cd5f3aa',
    'CGSnapshot': '1.0-190da2a2aa9457edc771d888f7d225c4',
    'CGSnapshotList': '1.0-e8c3f4078cd0ee23487b34d173eec776',
    'ConsistencyGroup': '1.0-b9bad093daee0b259edddb3993c60c31',
    'ConsistencyGroupList': '1.0-09d0aad5491e762ecfdf66bef02ceb8d',
    'Service': '1.0-64baeb4911dbab1153064dd1c87edb9f',
    'ServiceList': '1.0-d242d3384b68e5a5a534e090ff1d5161',
    'Snapshot': '1.0-a6c33eefeadefb324d79f72f66c54e9a',
    'SnapshotList': '1.0-71661e7180ef6cc51501704a9bea4bf1',
    'Volume': '1.2-97c3977846dae6588381e7bd3e6e6558',
    'VolumeAttachment': '1.0-f14a7c03ffc5b93701d496251a5263aa',
    'VolumeAttachmentList': '1.0-307d2b6c8dd55ef854f6386898e9e98e',
    'VolumeList': '1.1-03ba6cb8c546683e64e15c50042cb1a3',
    'VolumeType': '1.0-bf8abbbea2e852ed2e9bac5a9f5f70f2',
    'VolumeTypeList': '1.0-09b01f4526266c1a58cb206ba509d6d2',
}


class TestObjectVersions(test.TestCase):

    def test_versions(self):
        checker = fixture.ObjectVersionChecker(
            base.CinderObjectRegistry.obj_classes())
        expected, actual = checker.test_hashes(object_data)
        self.assertEqual(expected, actual,
                         'Some objects have changed; please make sure the '
                         'versions have been bumped, and then update their '
                         'hashes in the object_data map in this test module.')
