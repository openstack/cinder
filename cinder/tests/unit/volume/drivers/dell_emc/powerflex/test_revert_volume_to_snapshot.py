# Copyright (c) 2020 Dell Inc. or its subsidiaries.
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
from cinder import exception
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume
from cinder.tests.unit.volume.drivers.dell_emc import powerflex


class TestRevertVolume(powerflex.TestPowerFlexDriver):
    """Test cases for ``PowerFlexDriver.revert_to_snapshot()``"""

    def setUp(self):
        """Setup a test case environment.

        Creates a fake volume object and sets up the required API responses.
        """

        super(TestRevertVolume, self).setUp()
        ctx = context.RequestContext('fake', 'fake', auth_token=True)
        host = 'host@backend#{}:{}'.format(
            self.PROT_DOMAIN_NAME,
            self.STORAGE_POOL_NAME)
        self.volume = fake_volume.fake_volume_obj(
            ctx, **{'provider_id': fake.PROVIDER_ID, 'host': host,
                    'volume_type_id': fake.VOLUME_TYPE_ID,
                    'size': 8})
        self.snapshot = fake_snapshot.fake_snapshot_obj(
            ctx, **{'volume_id': self.volume.id,
                    'volume_size': self.volume.size}
        )
        self.HTTPS_MOCK_RESPONSES = {
            self.RESPONSE_MODE.Valid: {
                'instances/Volume::{}/action/overwriteVolumeContent'.format(
                    self.volume.provider_id
                ): {},
            },
            self.RESPONSE_MODE.Invalid: {
                'version': "2.6",
            },
            self.RESPONSE_MODE.BadStatus: {
                'instances/Volume::{}/action/overwriteVolumeContent'.format(
                    self.volume.provider_id
                ): self.BAD_STATUS_RESPONSE
            },
        }

        self.volume_is_replicated_mock = self.mock_object(
            self.volume, 'is_replicated',
            return_value=False
        )

    def test_revert_to_snapshot(self):
        self.driver.revert_to_snapshot(None, self.volume, self.snapshot)

    def test_revert_to_snapshot_badstatus_response(self):
        self.set_https_response_mode(self.RESPONSE_MODE.BadStatus)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.revert_to_snapshot,
                          None, self.volume, self.snapshot)

    def test_revert_to_snapshot_use_generic(self):
        self.set_https_response_mode(self.RESPONSE_MODE.Invalid)
        self.assertRaises(NotImplementedError,
                          self.driver.revert_to_snapshot,
                          None, self.volume, self.snapshot)

    def test_revert_to_snapshot_replicated_volume(self):
        self.volume_is_replicated_mock.return_value = True
        self.assertRaisesRegex(
            exception.InvalidVolume,
            'Reverting replicated volume is not allowed.',
            self.driver.revert_to_snapshot,
            None, self.volume, self.snapshot
        )

    def test_revert_to_snapshot_size_not_equal(self):
        patched_volume = mock.MagicMock()
        patched_volume.id = self.volume.id
        patched_volume.size = 16
        patched_volume.is_replicated.return_value = False
        self.assertRaisesRegex(
            exception.InvalidVolume,
            ('Volume %s size is not equal to snapshot %s size.' %
             (self.volume.id, self.snapshot.id)),
            self.driver.revert_to_snapshot,
            None, patched_volume, self.snapshot
        )
