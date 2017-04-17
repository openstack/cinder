# Copyright (C) 2017 Dell Inc. or its subsidiaries.
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

import json
import mock

from cinder import context
from cinder.objects import fields

from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_group
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume
from cinder.tests.unit.volume.drivers.dell_emc import scaleio
from cinder.tests.unit.volume.drivers.dell_emc.scaleio import mocks


class TestGroups(scaleio.TestScaleIODriver):
    """Test cases for ``ScaleIODriver groups support``"""

    def setUp(self):
        """Setup a test case environment.

        Creates a fake volume object and sets up the required API responses.
        """
        super(TestGroups, self).setUp()
        self.ctx = context.RequestContext('fake', 'fake', auth_token=True)
        self.fake_grp_snap = {'id': 'group_snap_id',
                              'name': 'test_group_snapshot',
                              'group_id': fake.GROUP_ID,
                              'status': fields.GroupSnapshotStatus.AVAILABLE
                              }
        self.group = (
            fake_group.fake_group_obj(
                self.ctx, **{'id': fake.GROUP_ID}))
        fake_volume1 = fake_volume.fake_volume_obj(
            self.ctx,
            **{'id': fake.VOLUME_ID, 'provider_id': fake.PROVIDER_ID})
        fake_volume2 = fake_volume.fake_volume_obj(
            self.ctx,
            **{'id': fake.VOLUME2_ID, 'provider_id': fake.PROVIDER2_ID})
        fake_volume3 = fake_volume.fake_volume_obj(
            self.ctx,
            **{'id': fake.VOLUME3_ID, 'provider_id': fake.PROVIDER3_ID})
        fake_volume4 = fake_volume.fake_volume_obj(
            self.ctx,
            **{'id': fake.VOLUME4_ID, 'provider_id': fake.PROVIDER4_ID})
        self.volumes = [fake_volume1, fake_volume2]
        self.volumes2 = [fake_volume3, fake_volume4]
        fake_snapshot1 = fake_snapshot.fake_snapshot_obj(
            self.ctx,
            **{'id': fake.SNAPSHOT_ID, 'volume_id': fake.VOLUME_ID,
               'volume': fake_volume1})
        fake_snapshot2 = fake_snapshot.fake_snapshot_obj(
            self.ctx,
            **{'id': fake.SNAPSHOT2_ID, 'volume_id': fake.VOLUME2_ID, 'volume':
                fake_volume2})
        self.snapshots = [fake_snapshot1, fake_snapshot2]
        self.snapshot_reply = json.dumps({
            'volumeIdList': ['sid1', 'sid2'],
            'snapshotGroupId': 'sgid1'})
        self.HTTPS_MOCK_RESPONSES = {
            self.RESPONSE_MODE.Valid: {
                'instances/Volume::{}/action/removeVolume'.format(
                    fake_volume1['provider_id']
                ): fake_volume1['provider_id'],
                'instances/Volume::{}/action/removeVolume'.format(
                    fake_volume2['provider_id']
                ): fake_volume2['provider_id'],
                'instances/Volume::{}/action/removeMappedSdc'.format(
                    fake_volume1['provider_id']
                ): fake_volume1['provider_id'],
                'instances/Volume::{}/action/removeMappedSdc'.format(
                    fake_volume2['provider_id']
                ): fake_volume2['provider_id'],
                'instances/System/action/snapshotVolumes':
                    self.snapshot_reply,
            },
            self.RESPONSE_MODE.BadStatus: {
                'instances/Volume::{}/action/removeVolume'.format(
                    fake_volume1['provider_id']
                ): mocks.MockHTTPSResponse(
                    {
                        'errorCode': 401,
                        'message': 'BadStatus Volume Test',
                    }, 401
                ),
                'instances/Volume::{}/action/removeVolume'.format(
                    fake_volume2['provider_id']
                ): mocks.MockHTTPSResponse(
                    {
                        'errorCode': 401,
                        'message': 'BadStatus Volume Test',
                    }, 401
                ),
                'instances/System/action/snapshotVolumes':
                    self.BAD_STATUS_RESPONSE
            },
        }

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type')
    def test_create_group(self, is_group_a_cg_snapshot_type):
        """Test group create.

        should throw NotImplementedError, is_group_a_cg_snapshot_type=False
        otherwise returns status of 'available'
        """
        is_group_a_cg_snapshot_type.side_effect = [False, True]

        self.assertRaises(NotImplementedError,
                          self.driver.create_group, self.ctx, self.group)

        model_update = self.driver.create_group(self.ctx, self.group)
        self.assertEqual(fields.GroupStatus.AVAILABLE,
                         model_update['status'])

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type')
    def test_delete_group(self, is_group_a_cg_snapshot_type):
        """Test group deletion.

        should throw NotImplementedError, is_group_a_cg_snapshot_type=False
        otherwise returns status of 'deleted'
        """
        is_group_a_cg_snapshot_type.side_effect = [False, True]

        self.assertRaises(NotImplementedError,
                          self.driver.delete_group,
                          self.ctx, self.group, self.volumes)

        model_update = self.driver.delete_group(self.ctx,
                                                self.group,
                                                self.volumes)
        self.assertEqual(fields.GroupStatus.DELETED,
                         model_update[0]['status'])

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type')
    def test_update_group(self, is_group_a_cg_snapshot_type):
        """Test updating a group

        should throw NotImplementedError, is_group_a_cg_snapshot_type=False
        otherwise returns 'None' for each of the updates
        """
        is_group_a_cg_snapshot_type.side_effect = [False, True]

        self.assertRaises(NotImplementedError,
                          self.driver.update_group, self.ctx, self.group)

        mod_up, add_up, remove_up = self.driver.update_group(self.ctx,
                                                             self.group)
        self.assertIsNone(mod_up)
        self.assertIsNone(add_up)
        self.assertIsNone(remove_up)

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type')
    def test_create_group_from_src_group(self, is_group_a_cg_snapshot_type):
        """Test creating group from source group

        should throw NotImplementedError, is_group_a_cg_snapshot_type=False
        otherwise returns list of volumes in 'available' state
        """
        self.set_https_response_mode(self.RESPONSE_MODE.Valid)

        is_group_a_cg_snapshot_type.side_effect = [False, True]

        self.assertRaises(NotImplementedError,
                          self.driver.create_group_from_src,
                          self.ctx, self.group, self.volumes,
                          source_group=self.group, source_vols=self.volumes)

        result_model_update, result_volumes_model_update = (
            self.driver.create_group_from_src(
                self.ctx, self.group, self.volumes,
                source_group=self.group, source_vols=self.volumes))
        self.assertEqual(fields.GroupStatus.AVAILABLE,
                         result_model_update['status'])
        get_pid = lambda snapshot: snapshot['provider_id']
        volume_provider_list = list(map(get_pid, result_volumes_model_update))
        self.assertListEqual(volume_provider_list, ['sid1', 'sid2'])

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type')
    def test_create_group_from_src_snapshot(self, is_group_a_cg_snapshot_type):
        """Test creating group from snapshot

        """
        self.set_https_response_mode(self.RESPONSE_MODE.Valid)
        is_group_a_cg_snapshot_type.side_effect = [False, True]

        self.assertRaises(NotImplementedError,
                          self.driver.create_group_from_src,
                          self.ctx, self.group, self.volumes,
                          group_snapshot=self.fake_grp_snap,
                          snapshots=self.snapshots)

        result_model_update, result_volumes_model_update = (
            self.driver.create_group_from_src(
                self.ctx, self.group, self.volumes,
                group_snapshot=self.fake_grp_snap,
                snapshots=self.snapshots))
        self.assertEqual(fields.GroupStatus.AVAILABLE,
                         result_model_update['status'])
        get_pid = lambda snapshot: snapshot['provider_id']
        volume_provider_list = list(map(get_pid, result_volumes_model_update))
        self.assertListEqual(volume_provider_list, ['sid1', 'sid2'])

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type')
    def test_delete_group_snapshot(self, is_group_a_cg_snapshot_type):
        """Test deleting group snapshot

        should throw NotImplementedError, is_group_a_cg_snapshot_type=False
        otherwise returns model updates
        """
        is_group_a_cg_snapshot_type.side_effect = [False, True]
        self.set_https_response_mode(self.RESPONSE_MODE.Valid)

        self.snapshots[0].volume = self.volumes[0]
        self.snapshots[1].volume = self.volumes[1]
        self.snapshots[0].provider_id = fake.PROVIDER_ID
        self.snapshots[1].provider_id = fake.PROVIDER2_ID

        self.assertRaises(NotImplementedError,
                          self.driver.delete_group_snapshot,
                          self.ctx,
                          self.group,
                          self.snapshots)

        result_model_update, result_snapshot_model_update = (
            self.driver.delete_group_snapshot(
                self.ctx,
                self.group,
                self.snapshots
            ))
        self.assertEqual(fields.GroupSnapshotStatus.DELETED,
                         result_model_update['status'])
        self.assertTrue(all(snapshot['status'] == 'deleted' for snapshot in
                            result_snapshot_model_update))

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type')
    def test_create_group_snapshot(self, is_group_a_cg_snapshot_type):
        """Test creating group snapshot

        should throw NotImplementedError, is_group_a_cg_snapshot_type=False
        otherwise returns model updates
        """
        is_group_a_cg_snapshot_type.side_effect = [False, True]
        self.set_https_response_mode(self.RESPONSE_MODE.Valid)

        self.assertRaises(NotImplementedError,
                          self.driver.create_group_snapshot,
                          self.ctx,
                          self.group,
                          self.snapshots)

        result_model_update, result_snapshot_model_update = (
            self.driver.create_group_snapshot(
                self.ctx,
                self.group,
                self.snapshots
            ))
        self.assertEqual(fields.GroupSnapshotStatus.AVAILABLE,
                         result_model_update['status'])
        self.assertTrue(all(snapshot['status'] == 'available' for snapshot in
                            result_snapshot_model_update))
        get_pid = lambda snapshot: snapshot['provider_id']
        snapshot_provider_list = list(map(get_pid,
                                          result_snapshot_model_update))

        self.assertListEqual(['sid1', 'sid2'], snapshot_provider_list)
