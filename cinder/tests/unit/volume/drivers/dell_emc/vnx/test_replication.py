# Copyright (c) 2017 Dell Inc. or its subsidiaries.
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import mock

from cinder.objects import fields
from cinder.tests.unit.volume.drivers.dell_emc.vnx import res_mock
from cinder.tests.unit.volume.drivers.dell_emc.vnx import test_base
from cinder.tests.unit.volume.drivers.dell_emc.vnx import utils
from cinder.volume.drivers.dell_emc.vnx import utils as vnx_utils


class TestReplicationAdapter(test_base.TestCase):

    def setUp(self):
        super(TestReplicationAdapter, self).setUp()
        vnx_utils.init_ops(self.configuration)

    @utils.patch_group_specs({
        'consistent_group_replication_enabled': '<is> True'})
    @res_mock.mock_driver_input
    @res_mock.patch_common_adapter
    def test_enable_replication(self, common_adapter, mocked_res,
                                mocked_input):
        group = mocked_input['group']
        volumes = [mocked_input['volume1'],
                   mocked_input['volume2']]
        volumes[0].group = group
        volumes[1].group = group
        common_adapter.enable_replication(self.ctxt, group, volumes)

    @utils.patch_group_specs({
        'consistent_group_replication_enabled': '<is> True'})
    @res_mock.mock_driver_input
    @res_mock.patch_common_adapter
    def test_disable_replication(self, common_adapter, mocked_res,
                                 mocked_input):
        group = mocked_input['group']
        volumes = [mocked_input['volume1'],
                   mocked_input['volume2']]
        volumes[0].group = group
        volumes[1].group = group
        common_adapter.disable_replication(self.ctxt, group, volumes)

    @utils.patch_group_specs({
        'consistent_group_replication_enabled': '<is> True'})
    @res_mock.mock_driver_input
    @res_mock.patch_common_adapter
    def test_failover_replication(self, common_adapter, mocked_res,
                                  mocked_input):
        device = utils.get_replication_device()
        common_adapter.config.replication_device = [device]
        group = mocked_input['group']
        volumes = [mocked_input['volume1'], mocked_input['volume2']]
        lun1 = mocked_res['lun1']
        volumes[0].group = group
        volumes[1].group = group
        secondary_backend_id = 'fake_serial'
        with mock.patch.object(common_adapter,
                               'build_mirror_view') as fake:
            fake_mirror = utils.build_fake_mirror_view()
            fake_mirror.secondary_client.get_lun.return_value = lun1
            fake_mirror.secondary_client.get_serial.return_value = (
                device['backend_id'])
            fake.return_value = fake_mirror
            model_update, volume_updates = common_adapter.failover_replication(
                self.ctxt, group, volumes, secondary_backend_id)

            fake_mirror.promote_mirror_group.assert_called_with(
                group.id.replace('-', ''))
            self.assertEqual(fields.ReplicationStatus.FAILED_OVER,
                             model_update['replication_status'])
            for update in volume_updates:
                self.assertEqual(fields.ReplicationStatus.FAILED_OVER,
                                 update['replication_status'])
