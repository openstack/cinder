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

import json

from six.moves import urllib

from cinder import context
from cinder import exception
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_volume
from cinder.tests.unit.volume.drivers.dell_emc import powerflex
from cinder.tests.unit.volume.drivers.dell_emc.powerflex import mocks
from cinder.volume.drivers.dell_emc.powerflex import utils as flex_utils


class TestCreateClonedVolume(powerflex.TestPowerFlexDriver):
    """Test cases for ``PowerFlexDriver.create_cloned_volume()``"""
    def setUp(self):
        """Setup a test case environment.

        Creates fake volume objects and sets up the required API responses.
        """
        super(TestCreateClonedVolume, self).setUp()
        ctx = context.RequestContext('fake', 'fake', auth_token=True)

        self.src_volume = fake_volume.fake_volume_obj(
            ctx, **{'provider_id': fake.PROVIDER_ID})

        self.src_volume_name_2x_enc = urllib.parse.quote(
            urllib.parse.quote(
                flex_utils.id_to_base64(self.src_volume.id)
            )
        )

        self.new_volume_extras = {
            'volumeIdList': ['cloned'],
            'snapshotGroupId': 'cloned_snapshot'
        }

        self.new_volume = fake_volume.fake_volume_obj(
            ctx, **self.new_volume_extras
        )

        self.new_volume_name_2x_enc = urllib.parse.quote(
            urllib.parse.quote(
                flex_utils.id_to_base64(self.new_volume.id)
            )
        )
        self.HTTPS_MOCK_RESPONSES = {
            self.RESPONSE_MODE.Valid: {
                'types/Volume/instances/getByName::' +
                self.src_volume_name_2x_enc: self.src_volume.id,
                'instances/System/action/snapshotVolumes': '{}'.format(
                    json.dumps(self.new_volume_extras)),
                'instances/Volume::cloned/action/setVolumeSize': None
            },
            self.RESPONSE_MODE.BadStatus: {
                'instances/System/action/snapshotVolumes':
                    self.BAD_STATUS_RESPONSE,
                'types/Volume/instances/getByName::' +
                    self.src_volume['provider_id']: self.BAD_STATUS_RESPONSE,
            },
            self.RESPONSE_MODE.Invalid: {
                'types/Volume/instances/getByName::' +
                    self.src_volume_name_2x_enc: None,
                'instances/System/action/snapshotVolumes':
                    mocks.MockHTTPSResponse(
                        {
                            'errorCode': 400,
                            'message': 'Invalid Volume Snapshot Test'
                        }, 400
                    ),
            },
        }

    def test_bad_login(self):
        self.set_https_response_mode(self.RESPONSE_MODE.BadStatus)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_cloned_volume,
                          self.new_volume, self.src_volume)

    def test_invalid_source_volume(self):
        self.set_https_response_mode(self.RESPONSE_MODE.Invalid)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_cloned_volume,
                          self.new_volume, self.src_volume)

    def test_create_cloned_volume(self):
        self.set_https_response_mode(self.RESPONSE_MODE.Valid)
        self.driver.create_cloned_volume(self.new_volume, self.src_volume)

    def test_create_cloned_volume_larger_size(self):
        self.set_https_response_mode(self.RESPONSE_MODE.Valid)
        self.new_volume.size = 2
        self.driver.create_cloned_volume(self.new_volume, self.src_volume)
