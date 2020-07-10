# Copyright (c) 2016 EMC Corporation.
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

from unittest.mock import patch

from six.moves import urllib

from cinder import context
from cinder import exception
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_volume
from cinder.tests.unit.volume.drivers.dell_emc import powerflex
from cinder.tests.unit.volume.drivers.dell_emc.powerflex import mocks
from cinder.volume.drivers.dell_emc.powerflex import utils as flex_utils
from cinder.volume import volume_types


class TestManageExisting(powerflex.TestPowerFlexDriver):
    """Test cases for ``PowerFlexDriver.manage_existing()``"""

    def setUp(self):
        """Setup a test case environment.

        Creates a fake volume object and sets up the required API responses.
        """
        super(TestManageExisting, self).setUp()
        ctx = context.RequestContext('fake', 'fake', auth_token=True)
        self.volume = fake_volume.fake_volume_obj(
            ctx, **{'provider_id': fake.PROVIDER_ID})
        self.volume_attached = fake_volume.fake_volume_obj(
            ctx, **{'provider_id': fake.PROVIDER2_ID})
        self.volume_no_provider_id = fake_volume.fake_volume_obj(ctx)
        self.volume_name_2x_enc = urllib.parse.quote(
            urllib.parse.quote(flex_utils.id_to_base64(self.volume.id))
        )

        self.HTTPS_MOCK_RESPONSES = {
            self.RESPONSE_MODE.Valid: {
                'instances/Volume::' + self.volume['provider_id']:
                    mocks.MockHTTPSResponse({
                        'id': fake.PROVIDER_ID,
                        'sizeInKb': 8000000,
                        'mappedSdcInfo': None
                    }, 200)
            },
            self.RESPONSE_MODE.BadStatus: {
                'instances/Volume::' + self.volume['provider_id']:
                    mocks.MockHTTPSResponse({
                        'errorCode': 401,
                        'message': 'BadStatus Volume Test',
                    }, 401),
                'instances/Volume::' + self.volume_attached['provider_id']:
                    mocks.MockHTTPSResponse({
                        'id': fake.PROVIDER2_ID,
                        'sizeInKb': 8388608,
                        'mappedSdcInfo': 'Mapped'
                    }, 200)
            }
        }

    def test_no_source_id(self):
        existing_ref = {'source-name': 'scaleioVolName'}
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing, self.volume,
                          existing_ref)

    def test_no_type_id(self):
        self.volume['volume_type_id'] = None
        existing_ref = {'source-id': fake.PROVIDER_ID}
        self.assertRaises(exception.ManageExistingVolumeTypeMismatch,
                          self.driver.manage_existing, self.volume,
                          existing_ref)

    @patch.object(
        volume_types,
        'get_volume_type',
        return_value={'extra_specs': {'volume_backend_name': 'ScaleIO'}})
    def test_volume_not_found(self, _mock_volume_type):
        self.volume['volume_type_id'] = fake.VOLUME_TYPE_ID
        existing_ref = {'source-id': fake.PROVIDER_ID}
        self.set_https_response_mode(self.RESPONSE_MODE.BadStatus)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.manage_existing, self.volume,
                          existing_ref)

    @patch.object(
        volume_types,
        'get_volume_type',
        return_value={'extra_specs': {'volume_backend_name': 'ScaleIO'}})
    def test_volume_attached(self, _mock_volume_type):
        self.volume_attached['volume_type_id'] = fake.VOLUME_TYPE_ID
        existing_ref = {'source-id': fake.PROVIDER2_ID}
        self.set_https_response_mode(self.RESPONSE_MODE.BadStatus)
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing, self.volume_attached,
                          existing_ref)

    @patch.object(
        volume_types,
        'get_volume_type',
        return_value={'extra_specs': {'volume_backend_name': 'ScaleIO'}})
    def test_manage_get_size_calc(self, _mock_volume_type):
        self.volume['volume_type_id'] = fake.VOLUME_TYPE_ID
        existing_ref = {'source-id': fake.PROVIDER_ID}
        self.set_https_response_mode(self.RESPONSE_MODE.Valid)
        result = self.driver.manage_existing_get_size(self.volume,
                                                      existing_ref)
        self.assertEqual(8, result)

    @patch.object(
        volume_types,
        'get_volume_type',
        return_value={'extra_specs': {'volume_backend_name': 'ScaleIO'}})
    def test_manage_existing_valid(self, _mock_volume_type):
        self.volume['volume_type_id'] = fake.VOLUME_TYPE_ID
        existing_ref = {'source-id': fake.PROVIDER_ID}
        result = self.driver.manage_existing(self.volume, existing_ref)
        self.assertEqual(fake.PROVIDER_ID, result['provider_id'])
