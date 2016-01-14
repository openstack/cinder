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
    'Backup': '1.3-2e63492190bbbc85c0e5bea328cd38f7',
    'BackupImport': '1.3-2e63492190bbbc85c0e5bea328cd38f7',
    'BackupList': '1.0-24591dabe26d920ce0756fe64cd5f3aa',
    'CGSnapshot': '1.0-190da2a2aa9457edc771d888f7d225c4',
    'CGSnapshotList': '1.0-e8c3f4078cd0ee23487b34d173eec776',
    'ConsistencyGroup': '1.2-ed7f90a6871991a19af716ade7337fc9',
    'ConsistencyGroupList': '1.1-73916823b697dfa0c7f02508d87e0f28',
    'Service': '1.2-4d3dd6c9906da364739fbf3f90c80505',
    'ServiceList': '1.1-cb758b200f0a3a90efabfc5aa2ffb627',
    'Snapshot': '1.0-a6c33eefeadefb324d79f72f66c54e9a',
    'SnapshotList': '1.0-71661e7180ef6cc51501704a9bea4bf1',
    'Volume': '1.3-97c3977846dae6588381e7bd3e6e6558',
    'VolumeAttachment': '1.0-f14a7c03ffc5b93701d496251a5263aa',
    'VolumeAttachmentList': '1.0-307d2b6c8dd55ef854f6386898e9e98e',
    'VolumeList': '1.1-03ba6cb8c546683e64e15c50042cb1a3',
    'VolumeType': '1.0-bf8abbbea2e852ed2e9bac5a9f5f70f2',
    'VolumeTypeList': '1.1-8a1016c03570dc13b9a33fe04a6acb2c',
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

    def test_versions_history(self):
        classes = base.CinderObjectRegistry.obj_classes()
        versions = base.OBJ_VERSIONS.get_current_versions()
        expected = {}
        actual = {}
        for name, cls in classes.items():
            if name not in versions:
                expected[name] = cls[0].VERSION
            elif cls[0].VERSION != versions[name]:
                expected[name] = cls[0].VERSION
                actual[name] = versions[name]

        self.assertEqual(expected, actual,
                         'Some objects versions have changed; please make '
                         'sure a new objects history version was added in '
                         'cinder.objects.base.OBJ_VERSIONS.')
