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
from cinder.tests.unit import fake_volume
from cinder.tests.unit.volume.drivers.emc import scaleio
from cinder.tests.unit.volume.drivers.emc.scaleio import mocks


class TestDeleteVolume(scaleio.TestScaleIODriver):
    """Test cases for ``ScaleIODriver.delete_volume()``"""
    def setUp(self):
        """Setup a test case environment.

        Creates a fake volume object and sets up the required API responses.
        """
        super(TestDeleteVolume, self).setUp()
        ctx = context.RequestContext('fake', 'fake', auth_token=True)

        self.volume = fake_volume.fake_volume_obj(
            ctx, **{'provider_id': 'pid_1'})

        self.volume_name_2x_enc = urllib.parse.quote(
            urllib.parse.quote(self.driver._id_to_base64(self.volume.id))
        )

        self.HTTPS_MOCK_RESPONSES = {
            self.RESPONSE_MODE.Valid: {
                'types/Volume/instances/getByName::' +
                self.volume_name_2x_enc: self.volume.id,
                'instances/Volume::{}/action/removeMappedSdc'.format(
                    self.volume.provider_id): self.volume.provider_id,
                'instances/Volume::{}/action/removeVolume'.format(
                    self.volume.provider_id
                ): self.volume.provider_id,
            },
            self.RESPONSE_MODE.BadStatus: {
                'types/Volume/instances/getByName::' +
                self.volume_name_2x_enc: mocks.MockHTTPSResponse(
                    {
                        'errorCode': 401,
                        'message': 'BadStatus Volume Test',
                    }, 401
                ),
                'instances/Volume::{}/action/removeVolume'.format(
                    self.volume.provider_id
                ): mocks.MockHTTPSResponse(
                    {
                        'errorCode': 401,
                        'message': 'BadStatus Volume Test',
                    }, 401
                ),
            },
        }

    def test_bad_login_and_volume(self):
        self.set_https_response_mode(self.RESPONSE_MODE.BadStatus)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.delete_volume,
                          self.volume)

    def test_delete_volume(self):
        """Setting the unmap volume before delete flag for tests """
        self.driver.configuration.set_override(
            'sio_unmap_volume_before_deletion',
            override=True)
        self.driver.delete_volume(self.volume)
