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
    'Backup': '1.1-f2e7befd20d3bb388700f17c4f386b28',
    'BackupImport': '1.1-f2e7befd20d3bb388700f17c4f386b28',
    'BackupList': '1.0-db44728c8d21bb23bba601a5499550f8',
    'CGSnapshot': '1.0-d50e9480cee2abcb2222997f2bb85656',
    'CGSnapshotList': '1.0-3361be608f396c5ae045b6d94f901346',
    'ConsistencyGroup': '1.0-98714c3d8f83914fd7a17317c3c29e01',
    'ConsistencyGroupList': '1.0-a906318d3e69d847f31df561d12540b3',
    'Service': '1.0-b81a04373ce0ad2d07de525eb534afd6',
    'ServiceList': '1.0-1911175eadd43fb6eafbefd18c802f2c',
    'Snapshot': '1.0-54a2726a282cbdb47ddd326107e821ce',
    'SnapshotList': '1.0-46abf2a1e65ef55dad4f36fe787f9a78',
    'Volume': '1.1-adc26d52b646723bd0633b0771ad2598',
    'VolumeAttachment': '1.0-4fd93dbfa57d048a4859f5bb1ca66bed',
    'VolumeAttachmentList': '1.0-829c18b1d929ea1f8a451b3c4e0a0289',
    'VolumeList': '1.1-d41f3a850be5fbaa94eb4cc955c7ca60',
    'VolumeType': '1.0-8cb7daad27570133543c2c359d85c658',
    'VolumeTypeList': '1.0-980f0b518aed9df0beb55cc533eff632'
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
