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
from mock import patch

from cinder import context
from cinder import exception
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume
from cinder.tests.unit.volume.drivers.dell_emc import scaleio
from cinder.tests.unit.volume.drivers.dell_emc.scaleio import mocks
from cinder.volume import volume_types


class TestManageExistingSnapshot(scaleio.TestScaleIODriver):
    """Test cases for ``ScaleIODriver.manage_existing_snapshot()``"""

    def setUp(self):
        """Setup a test case environment.

        Creates a fake volume object and sets up the required API responses.
        """
        super(TestManageExistingSnapshot, self).setUp()
        ctx = context.RequestContext('fake', 'fake', auth_token=True)
        self.volume = fake_volume.fake_volume_obj(
            ctx, **{'provider_id': fake.PROVIDER_ID})
        self.snapshot = fake_snapshot.fake_snapshot_obj(
            ctx, **{'provider_id': fake.PROVIDER2_ID})
        self.snapshot2 = fake_snapshot.fake_snapshot_obj(
            ctx, **{'provider_id': fake.PROVIDER3_ID})
        self.snapshot.volume = self.snapshot2.volume = self.volume
        self.snapshot['volume_type_id'] = fake.VOLUME_TYPE_ID
        self.snapshot2['volume_type_id'] = fake.VOLUME_TYPE_ID
        self.snapshot_attached = fake_snapshot.fake_snapshot_obj(
            ctx, **{'provider_id': fake.PROVIDER3_ID})

        self.HTTPS_MOCK_RESPONSES = {
            self.RESPONSE_MODE.Valid: {
                'instances/Volume::' + self.volume['provider_id']:
                    mocks.MockHTTPSResponse({
                        'id': fake.PROVIDER_ID,
                        'sizeInKb': 8388608,
                        'mappedSdcInfo': None,
                        'ancestorVolumeId': None
                    }, 200),
                'instances/Volume::' + self.snapshot['provider_id']:
                    mocks.MockHTTPSResponse({
                        'id': fake.PROVIDER2_ID,
                        'sizeInKb': 8000000,
                        'mappedSdcInfo': None,
                        'ancestorVolumeId': fake.PROVIDER_ID
                    }, 200),
                'instances/Volume::' + self.snapshot2['provider_id']:
                    mocks.MockHTTPSResponse({
                        'id': fake.PROVIDER3_ID,
                        'sizeInKb': 8388608,
                        'mappedSdcInfo': None,
                        'ancestorVolumeId': fake.PROVIDER2_ID
                    }, 200)
            },
            self.RESPONSE_MODE.BadStatus: {
                'instances/Volume::' + self.snapshot['provider_id']:
                    mocks.MockHTTPSResponse({
                        'errorCode': 401,
                        'message': 'BadStatus Volume Test',
                    }, 401),
                'instances/Volume::' + self.snapshot2['provider_id']:
                    mocks.MockHTTPSResponse({
                        'id': fake.PROVIDER3_ID,
                        'sizeInKb': 8388608,
                        'ancestorVolumeId': fake.PROVIDER2_ID
                    }, 200),
                'instances/Volume::' + self.snapshot_attached['provider_id']:
                    mocks.MockHTTPSResponse({
                        'id': fake.PROVIDER3_ID,
                        'sizeInKb': 8388608,
                        'mappedSdcInfo': 'Mapped',
                        'ancestorVolumeId': fake.PROVIDER_ID
                    }, 200)
            }
        }

    def test_no_source_id(self):
        existing_ref = {'source-name': 'scaleioSnapName'}
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_snapshot, self.snapshot,
                          existing_ref)

    @patch.object(
        volume_types,
        'get_volume_type',
        return_value={'extra_specs': {'volume_backend_name': 'ScaleIO'}})
    def test_snapshot_not_found(self, _mock_volume_type):
        existing_ref = {'source-id': fake.PROVIDER2_ID}
        self.set_https_response_mode(self.RESPONSE_MODE.BadStatus)
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_snapshot, self.snapshot,
                          existing_ref)

    @patch.object(
        volume_types,
        'get_volume_type',
        return_value={'extra_specs': {'volume_backend_name': 'ScaleIO'}})
    def test_snapshot_attached(self, _mock_volume_type):
        self.snapshot_attached['volume_type_id'] = fake.VOLUME_TYPE_ID
        existing_ref = {'source-id': fake.PROVIDER2_ID}
        self.set_https_response_mode(self.RESPONSE_MODE.BadStatus)
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_snapshot,
                          self.snapshot_attached, existing_ref)

    @patch.object(
        volume_types,
        'get_volume_type',
        return_value={'extra_specs': {'volume_backend_name': 'ScaleIO'}})
    def test_different_ancestor(self, _mock_volume_type):
        existing_ref = {'source-id': fake.PROVIDER3_ID}
        self.set_https_response_mode(self.RESPONSE_MODE.Valid)
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_snapshot,
                          self.snapshot2, existing_ref)

    @patch.object(
        volume_types,
        'get_volume_type',
        return_value={'extra_specs': {'volume_backend_name': 'ScaleIO'}})
    def test_manage_snapshot_get_size_calc(self, _mock_volume_type):
        existing_ref = {'source-id': fake.PROVIDER2_ID}
        self.set_https_response_mode(self.RESPONSE_MODE.Valid)
        result = self.driver.manage_existing_snapshot_get_size(
            self.snapshot, existing_ref)
        self.assertEqual(8, result)

    @patch.object(
        volume_types,
        'get_volume_type',
        return_value={'extra_specs': {'volume_backend_name': 'ScaleIO'}})
    def test_manage_existing_snapshot_valid(self, _mock_volume_type):
        existing_ref = {'source-id': fake.PROVIDER2_ID}
        result = self.driver.manage_existing_snapshot(
            self.snapshot, existing_ref)
        self.assertEqual(fake.PROVIDER2_ID, result['provider_id'])
