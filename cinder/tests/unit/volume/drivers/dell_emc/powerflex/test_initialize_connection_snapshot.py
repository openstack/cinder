# Copyright (c) 2017 Dell Inc. or its subsidiaries.
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

from unittest import mock

from cinder import context
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume
from cinder.tests.unit.volume.drivers.dell_emc import powerflex
from cinder.tests.unit.volume.drivers.dell_emc.powerflex import mocks


class TestInitializeConnectionSnapshot(powerflex.TestPowerFlexDriver):

    def setUp(self):
        super(TestInitializeConnectionSnapshot, self).setUp()
        self.snapshot_id = 'SNAPID'
        self.ctx = context.RequestContext('fake', 'fake', auth_token=True)
        self.fake_path = '/fake/path/vol-xx'
        self.volume = fake_volume.fake_volume_obj(
            self.ctx, **{'provider_id': fake.PROVIDER_ID})
        self.connector = {'sdc_guid': 'fake_guid'}

        self.sdc = {
            "id": "sdc1",
        }
        self.HTTPS_MOCK_RESPONSES = {
            self.RESPONSE_MODE.Valid: {
                'types/Sdc/instances':
                [{'id': "sdc1", 'sdcGuid': 'fake_guid'}],
                'instances/Volume::{}/action/setMappedSdcLimits'.format(
                    self.snapshot_id
                ): mocks.MockHTTPSResponse({}, 200),
            },
        }

    def test_backup_can_use_snapshots(self):
        """Make sure the driver can use snapshots for backup."""
        use_snaps = self.driver.backup_use_temp_snapshot()
        self.assertTrue(use_snaps)

    def test_initialize_connection_without_size(self):
        """Test initializing when we do not know the snapshot size.

        ScaleIO can determine QOS specs based upon volume/snapshot size
        The QOS keys should not be returned
        """
        snapshot = fake_snapshot.fake_snapshot_obj(
            self.ctx, **{'volume': self.volume,
                         'provider_id': self.snapshot_id})
        self.driver._attach_volume_to_host = mock.MagicMock(
            return_value=None
        )
        self.driver._check_volume_mapped = mock.MagicMock(
            return_value=None
        )
        props = self.driver.initialize_connection_snapshot(
            snapshot,
            self.connector)
        # validate the volume type
        self.assertEqual(props['driver_volume_type'], 'scaleio')
        # make sure a volume name and id exist
        self.assertIsNotNone(props['data']['scaleIO_volname'])
        self.assertEqual(self.snapshot_id,
                         props['data']['scaleIO_volume_id'])
        # make sure QOS properties are not set
        self.assertNotIn('iopsLimit', props['data'])

    def test_initialize_connection_with_size(self):
        """Test initializing when we know the snapshot size.

        PowerFlex can determine QOS specs based upon volume/snapshot size
        The QOS keys should not be returned
        """
        snapshot = fake_snapshot.fake_snapshot_obj(
            self.ctx, **{'volume': self.volume,
                         'provider_id': self.snapshot_id,
                         'volume_size': 8})
        self.driver._attach_volume_to_host = mock.MagicMock(
            return_value=None
        )
        self.driver._check_volume_mapped = mock.MagicMock(
            return_value=None
        )
        props = self.driver.initialize_connection_snapshot(
            snapshot,
            self.connector)
        # validate the volume type
        self.assertEqual(props['driver_volume_type'], 'scaleio')
        # make sure a volume name and id exist
        self.assertIsNotNone(props['data']['scaleIO_volname'])
        self.assertEqual(self.snapshot_id,
                         props['data']['scaleIO_volume_id'])
        # make sure QOS properties are not set
        self.assertNotIn('iopsLimit', props['data'])

    def test_qos_specs(self):
        """Ensure QOS specs are honored if present."""
        qos = {'maxIOPS': 1000, 'maxBWS': 2048}
        snapshot = fake_snapshot.fake_snapshot_obj(
            self.ctx, **{'volume': self.volume,
                         'provider_id': self.snapshot_id,
                         'volume_size': 8})
        extraspecs = {}
        self.driver._get_volumetype_qos = mock.MagicMock()
        self.driver._get_volumetype_qos.return_value = qos
        self.driver._get_volumetype_extraspecs = mock.MagicMock()
        self.driver._get_volumetype_extraspecs.return_value = extraspecs
        self.driver._attach_volume_to_host = mock.MagicMock(
            return_value=None
        )
        self.driver._check_volume_mapped = mock.MagicMock(
            return_value=None
        )
        self.driver.primary_client.set_sdc_limits = mock.MagicMock()
        self.driver.initialize_connection_snapshot(
            snapshot,
            self.connector)

        self.driver.primary_client.set_sdc_limits.assert_called_once_with(
            self.snapshot_id, self.sdc["id"], '2048', '1000')
