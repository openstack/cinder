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
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume
from cinder.tests.unit.volume.drivers.dell_emc import powerflex
from cinder.tests.unit.volume.drivers.dell_emc.powerflex import mocks
from cinder.volume.drivers.dell_emc.powerflex import utils as flex_utils


class TestCreateVolumeFromSnapShot(powerflex.TestPowerFlexDriver):
    """Test cases for ``PowerFlexDriver.create_volume_from_snapshot()``"""
    def setUp(self):
        """Setup a test case environment.

        Creates fake volume and snapshot objects and sets up the required
        API responses.
        """
        super(TestCreateVolumeFromSnapShot, self).setUp()
        ctx = context.RequestContext('fake', 'fake', auth_token=True)

        self.snapshot = fake_snapshot.fake_snapshot_obj(ctx)
        self.snapshot_name_2x_enc = urllib.parse.quote(
            urllib.parse.quote(flex_utils.id_to_base64(self.snapshot.id))
        )
        self.volume = fake_volume.fake_volume_obj(ctx)
        self.volume_name_2x_enc = urllib.parse.quote(
            urllib.parse.quote(flex_utils.id_to_base64(self.volume.id))
        )

        self.snapshot_reply = json.dumps(
            {
                'volumeIdList': [self.volume.id],
                'snapshotGroupId': 'snap_group'
            }
        )

        self.HTTPS_MOCK_RESPONSES = {
            self.RESPONSE_MODE.Valid: {
                'types/Volume/instances/getByName::' +
                self.snapshot_name_2x_enc: self.snapshot.id,
                'instances/System/action/snapshotVolumes':
                    self.snapshot_reply,
                'instances/Volume::{}/action/setVolumeSize'.format(
                    self.volume.id): None,
            },
            self.RESPONSE_MODE.BadStatus: {
                'instances/System/action/snapshotVolumes':
                    self.BAD_STATUS_RESPONSE,
                'types/Volume/instances/getByName::' +
                self.snapshot_name_2x_enc: self.BAD_STATUS_RESPONSE,
            },
            self.RESPONSE_MODE.Invalid: {
                'instances/System/action/snapshotVolumes':
                    mocks.MockHTTPSResponse(
                        {
                            'errorCode': self.OLD_VOLUME_NOT_FOUND_ERROR,
                            'message': 'BadStatus Volume Test',
                        }, 400
                    ),
                'types/Volume/instances/getByName::' +
                self.snapshot_name_2x_enc: None,
            },
        }

    def test_bad_login(self):
        self.set_https_response_mode(self.RESPONSE_MODE.BadStatus)
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.driver.create_volume_from_snapshot,
            self.volume,
            self.snapshot
        )

    def test_invalid_snapshot(self):
        self.set_https_response_mode(self.RESPONSE_MODE.Invalid)
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.driver.create_volume_from_snapshot,
            self.volume,
            self.snapshot
        )

    def test_create_volume_from_snapshot(self):
        self.set_https_response_mode(self.RESPONSE_MODE.Valid)
        self.driver.create_volume_from_snapshot(self.volume, self.snapshot)

    def test_create_volume_from_snapshot_larger(self):
        self.set_https_response_mode(self.RESPONSE_MODE.Valid)
        self.volume.size = 2
        self.driver.create_volume_from_snapshot(self.volume, self.snapshot)
