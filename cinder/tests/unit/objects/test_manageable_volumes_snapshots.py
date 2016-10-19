#   Copyright 2016 Intel Corporation
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

import ddt

from cinder import objects
from cinder.tests.unit import objects as test_objects


@ddt.ddt
class TestManageableResources(test_objects.BaseObjectsTestCase):

    def resource_test(self, resource, resource_type):
        if resource_type == "manageable_volume_obj":
            resource.manageable_volume_obj.wrong_key
        elif resource_type == "manageable_snapshot_obj":
            resource.manageable_snapshot_obj.wrong_key

    def setUp(self):
        super(TestManageableResources, self).setUp()
        self.manageable_volume_dict = [
            {'cinder_id':
             'e334aab4-c987-4eb0-9c81-d4a773b4f7a6',
             'extra_info': None,
             'reason_not_safe': 'already managed',
             'reference':
             {'source-name':
              'volume-e334aab4-c987-4eb0-9c81-d4a773b4f7a6'},
             'safe_to_manage': False,
             'size': 1,
             'foo': 'bar'},
            {'cinder_id':
             'da25ac53-3fe0-4f56-9369-4d289d8902fd',
             'extra_info': None,
             'reason_not_safe': 'already managed',
             'reference':
             {'source-name':
              'volume-da25ac53-3fe0-4f56-9369-4d289d8902fd'},
             'safe_to_manage': False,
             'size': 2}
        ]

        self.manageable_snapshot_dict = [
            {'cinder_id':
             'e334aab4-c987-4eb0-9c81-d4a773b4f7a6',
             'reference':
             {'source-name':
              'volume-e334aab4-c987-4eb0-9c81-d4a773b4f7a6'},
             'extra_info': None,
             'reason_not_safe': 'already managed',
             'source_reference':
             {'source-name':
              'volume-e334aab4-c987-4eb0-9c81-d4a773b4f7a6'},
             'safe_to_manage': False,
             'size': 1,
             'foo': 'bar'},
            {'cinder_id':
             'da25ac53-3fe0-4f56-9369-4d289d8902fd',
             'reference':
             {'source-name':
              'volume-da25ac53-3fe0-4f56-9369-4d289d8902fd'},
             'extra_info': None,
             'reason_not_safe': 'already managed',
             'source_reference':
             {'source-name':
              'da25ac53-3fe0-4f56-9369-4d289d8902fd'},
             'safe_to_manage': False,
             'size': 2}
        ]

        vol_mang_list = (objects.ManageableVolumeList.from_primitives
                         (self.context, self.manageable_volume_dict))
        self.manageable_volume_obj_list = vol_mang_list

        snap_mang_list = (objects.ManageableSnapshotList.from_primitives
                          (self.context, self.manageable_snapshot_dict))
        self.manageable_snapshot_obj_list = snap_mang_list

        self.manageable_volume_obj = self.manageable_volume_obj_list[0]
        self.manageable_snapshot_obj = self.manageable_snapshot_obj_list[0]

    @ddt.data('manageable_volume_obj', 'manageable_snapshot_obj')
    def test_extra_info(self, obj):
        # Making sure that any new key assignment gets stored in extra_info
        # field of manageable_volume_object & manageable_snapshot_object
        self.assertEqual(
            'bar',
            getattr(self, obj).extra_info['foo'])

    @ddt.data('manageable_volume_obj', 'manageable_snapshot_obj')
    def test_extra_info_wrong_key(self, obj):
        # Making sure referring an attribute before setting it raises an
        # Attribute Error for manageable_volume_object &
        # manageable_snapshot_object
        getattr(self, obj).foo = "test"
        self.assertRaises(AttributeError, self.resource_test, self, obj)
