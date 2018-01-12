# Copyright (c) 2017 Huawei.
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

from tempest.common import waiters
from tempest import config
from tempest.lib import decorators

from cinder.tests.tempest.api.volume import base
from cinder.tests.tempest import cinder_clients

CONF = config.CONF


class VolumeRevertTests(base.BaseVolumeTest):
    min_microversion = '3.40'

    @classmethod
    def setup_clients(cls):
        cls._api_version = 3
        super(VolumeRevertTests, cls).setup_clients()

        manager = cinder_clients.Manager(cls.os_primary)
        cls.volume_revert_client = manager.volume_revet_client

    def setUp(self):
        super(VolumeRevertTests, self).setUp()
        # Create volume
        self.volume = self.create_volume(size=1)
        # Create snapshot
        self.snapshot = self.create_snapshot(self.volume['id'])

    @decorators.idempotent_id('87b7dcb7-4950-4a3a-802c-ece55491846d')
    def test_volume_revert_to_snapshot(self):
        """Test revert to snapshot"""
        # Revert to snapshot
        self.volume_revert_client.revert_to_snapshot(self.volume,
                                                     self.snapshot['id'])
        waiters.wait_for_volume_resource_status(
            self.volumes_client,
            self.volume['id'], 'available')
        waiters.wait_for_volume_resource_status(
            self.snapshots_client,
            self.snapshot['id'], 'available')
        volume = self.volumes_client.show_volume(self.volume['id'])['volume']

        self.assertEqual(1, volume['size'])

    @decorators.idempotent_id('4e8b0788-87fe-430d-be7a-444d7f8e0347')
    def test_volume_revert_to_snapshot_after_extended(self):
        """Test revert to snapshot after extended"""
        # Extend the volume
        self.volumes_client.extend_volume(self.volume['id'], new_size=2)
        waiters.wait_for_volume_resource_status(self.volumes_client,
                                                self.volume['id'], 'available')
        # Revert to snapshot
        self.volume_revert_client.revert_to_snapshot(self.volume,
                                                     self.snapshot['id'])
        waiters.wait_for_volume_resource_status(
            self.volumes_client,
            self.volume['id'], 'available')
        waiters.wait_for_volume_resource_status(
            self.snapshots_client,
            self.snapshot['id'], 'available')
        volume = self.volumes_client.show_volume(self.volume['id'])['volume']
        self.assertEqual(2, volume['size'])
