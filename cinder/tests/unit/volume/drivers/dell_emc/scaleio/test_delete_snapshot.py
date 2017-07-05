# Copyright (c) 2013 - 2015 EMC Corporation.
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
from six.moves import urllib

from cinder import context
from cinder import exception
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit.fake_snapshot import fake_snapshot_obj
from cinder.tests.unit.volume.drivers.dell_emc import scaleio
from cinder.tests.unit.volume.drivers.dell_emc.scaleio import mocks
from cinder.volume import configuration


class TestDeleteSnapShot(scaleio.TestScaleIODriver):
    """Test cases for ``ScaleIODriver.delete_snapshot()``"""
    def setUp(self):
        """Setup a test case environment.

        Creates fake volume and snapshot objects and sets up the required
        API responses.
        """
        super(TestDeleteSnapShot, self).setUp()
        ctx = context.RequestContext('fake', 'fake', auth_token=True)

        self.snapshot = fake_snapshot_obj(
            ctx, **{'provider_id': fake.SNAPSHOT_ID})
        self.snapshot_name_2x_enc = urllib.parse.quote(
            urllib.parse.quote(
                self.driver._id_to_base64(self.snapshot.id)
            )
        )

        self.HTTPS_MOCK_RESPONSES = {
            self.RESPONSE_MODE.Valid: {
                'types/Volume/instances/getByName::' +
                self.snapshot_name_2x_enc: self.snapshot.id,
                'instances/Volume::{}/action/removeMappedSdc'.format(
                    self.snapshot.provider_id
                ): self.snapshot.id,
                'instances/Volume::{}/action/removeVolume'.format(
                    self.snapshot.provider_id
                ): self.snapshot.id,
            },
            self.RESPONSE_MODE.BadStatus: {
                'types/Volume/instances/getByName::' +
                self.snapshot_name_2x_enc: self.BAD_STATUS_RESPONSE,
                'instances/Volume::{}/action/removeVolume'.format(
                    self.snapshot.provider_id
                ): self.BAD_STATUS_RESPONSE,
            },
            self.RESPONSE_MODE.Invalid: {
                'types/Volume/instances/getByName::' +
                self.snapshot_name_2x_enc: mocks.MockHTTPSResponse(
                    {
                        'errorCode': self.OLD_VOLUME_NOT_FOUND_ERROR,
                        'message': 'Test Delete Invalid Snapshot',
                    }, 400
                ),
                'instances/Volume::{}/action/removeVolume'.format(
                    self.snapshot.provider_id): mocks.MockHTTPSResponse(
                    {
                        'errorCode': self.OLD_VOLUME_NOT_FOUND_ERROR,
                        'message': 'Test Delete Invalid Snapshot',
                    }, 400,
                )
            },
        }

    def test_bad_login(self):
        self.set_https_response_mode(self.RESPONSE_MODE.BadStatus)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.delete_snapshot, self.snapshot)

    def test_delete_invalid_snapshot(self):
        self.set_https_response_mode(self.RESPONSE_MODE.Valid)
        self.driver.delete_snapshot(self.snapshot)

    def test_delete_snapshot(self):
        """Setting the unmap volume before delete flag for tests """
        self.override_config('sio_unmap_volume_before_deletion', True,
                             configuration.SHARED_CONF_GROUP)
        self.set_https_response_mode(self.RESPONSE_MODE.Valid)
        self.driver.delete_snapshot(self.snapshot)
