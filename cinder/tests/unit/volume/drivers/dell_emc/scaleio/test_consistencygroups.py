# Copyright (c) 2013 - 2016 EMC Corporation.
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
from cinder.tests.unit.consistencygroup import fake_consistencygroup
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume
from cinder.tests.unit.volume.drivers.dell_emc import scaleio
from cinder.tests.unit.volume.drivers.dell_emc.scaleio import mocks


class TestConsistencyGroups(scaleio.TestScaleIODriver):
    """Test cases for ``ScaleIODriver consistency groups support``"""

    def setUp(self):
        """Setup a test case environment.

        Creates a fake volume object and sets up the required API responses.
        """
        super(TestConsistencyGroups, self).setUp()
        self.ctx = context.RequestContext('fake', 'fake', auth_token=True)
        self.consistency_group = (
            fake_consistencygroup.fake_consistencyobject_obj(
                self.ctx, **{'id': fake.CONSISTENCY_GROUP_ID}))
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

    def _fake_cgsnapshot(self):
        cgsnap = {'id': 'cgsid', 'name': 'testsnap',
                  'consistencygroup_id': fake.CONSISTENCY_GROUP_ID,
                  'status': 'available'}
        return cgsnap

    def test_create_consistencygroup(self):
        result = self.driver.create_consistencygroup(self.ctx,
                                                     self.consistency_group)
        self.assertEqual('available', result['status'])

    def test_delete_consistencygroup_valid(self):
        self.set_https_response_mode(self.RESPONSE_MODE.Valid)
        self.driver.configuration.set_override(
            'sio_unmap_volume_before_deletion',
            override=True)
        result_model_update, result_volumes_update = (
            self.driver.delete_consistencygroup(self.ctx,
                                                self.consistency_group,
                                                self.volumes))
        self.assertTrue(all(volume['status'] == 'deleted' for volume in
                            result_volumes_update))
        self.assertEqual('deleted', result_model_update['status'])

    def test_delete_consistency_group_fail(self):
        self.set_https_response_mode(self.RESPONSE_MODE.BadStatus)
        result_model_update, result_volumes_update = (
            self.driver.delete_consistencygroup(self.ctx,
                                                self.consistency_group,
                                                self.volumes))
        self.assertTrue(any(volume['status'] == 'error_deleting' for volume in
                            result_volumes_update))
        self.assertIn(result_model_update['status'],
                      ['error_deleting', 'error'])

    def test_create_consistencygroup_from_cg(self):
        self.set_https_response_mode(self.RESPONSE_MODE.Valid)
        result_model_update, result_volumes_model_update = (
            self.driver.create_consistencygroup_from_src(
                self.ctx, self.consistency_group, self.volumes2,
                source_cg=self.consistency_group, source_vols=self.volumes))
        self.assertEqual('available', result_model_update['status'])
        get_pid = lambda snapshot: snapshot['provider_id']
        volume_provider_list = list(map(get_pid, result_volumes_model_update))
        self.assertListEqual(volume_provider_list, ['sid1', 'sid2'])

    def test_create_consistencygroup_from_cgs(self):
        self.snapshots[0]['provider_id'] = fake.PROVIDER_ID
        self.snapshots[1]['provider_id'] = fake.PROVIDER2_ID
        self.set_https_response_mode(self.RESPONSE_MODE.Valid)
        result_model_update, result_volumes_model_update = (
            self.driver.create_consistencygroup_from_src(
                self.ctx, self.consistency_group, self.volumes2,
                cgsnapshot=self._fake_cgsnapshot(),
                snapshots=self.snapshots))
        self.assertEqual('available', result_model_update['status'])
        get_pid = lambda snapshot: snapshot['provider_id']
        volume_provider_list = list(map(get_pid, result_volumes_model_update))
        self.assertListEqual(['sid1', 'sid2'], volume_provider_list)

    @mock.patch('cinder.objects.snapshot')
    @mock.patch('cinder.objects.snapshot')
    def test_create_cgsnapshots(self, snapshot1, snapshot2):
        type(snapshot1).volume = mock.PropertyMock(
            return_value=self.volumes[0])
        type(snapshot2).volume = mock.PropertyMock(
            return_value=self.volumes[1])
        snapshots = [snapshot1, snapshot2]
        self.set_https_response_mode(self.RESPONSE_MODE.Valid)
        result_model_update, result_snapshot_model_update = (
            self.driver.create_cgsnapshot(
                self.ctx,
                self._fake_cgsnapshot(),
                snapshots
            ))
        self.assertEqual('available', result_model_update['status'])
        self.assertTrue(all(snapshot['status'] == 'available' for snapshot in
                            result_snapshot_model_update))
        get_pid = lambda snapshot: snapshot['provider_id']
        snapshot_provider_list = list(map(get_pid,
                                          result_snapshot_model_update))
        self.assertListEqual(['sid1', 'sid2'], snapshot_provider_list)

    @mock.patch('cinder.objects.snapshot')
    @mock.patch('cinder.objects.snapshot')
    def test_delete_cgsnapshots(self, snapshot1, snapshot2):
        type(snapshot1).volume = mock.PropertyMock(
            return_value=self.volumes[0])
        type(snapshot2).volume = mock.PropertyMock(
            return_value=self.volumes[1])
        type(snapshot1).provider_id = mock.PropertyMock(
            return_value=fake.PROVIDER_ID)
        type(snapshot2).provider_id = mock.PropertyMock(
            return_value=fake.PROVIDER2_ID)
        snapshots = [snapshot1, snapshot2]
        self.set_https_response_mode(self.RESPONSE_MODE.Valid)
        result_model_update, result_snapshot_model_update = (
            self.driver.delete_cgsnapshot(
                self.ctx,
                self._fake_cgsnapshot(),
                snapshots
            ))
        self.assertEqual('deleted', result_model_update['status'])
        self.assertTrue(all(snapshot['status'] == 'deleted' for snapshot in
                            result_snapshot_model_update))
