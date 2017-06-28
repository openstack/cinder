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

import ddt
import mock

from cinder import context
from cinder import exception
from cinder.tests.unit import fake_volume
from cinder.tests.unit.volume.drivers.dell_emc import scaleio


@ddt.ddt
class TestCreateVolume(scaleio.TestScaleIODriver):
    """Test cases for ``ScaleIODriver.create_volume()``"""
    def setUp(self):
        """Setup a test case environment.

        Creates a fake volume object and sets up the required API responses.
        """
        super(TestCreateVolume, self).setUp()
        ctx = context.RequestContext('fake', 'fake', auth_token=True)

        self.volume = fake_volume.fake_volume_obj(ctx)
        host = 'host@backend#{}:{}'.format(
            self.PROT_DOMAIN_NAME,
            self.STORAGE_POOL_NAME)
        self.volume.host = host

        self.HTTPS_MOCK_RESPONSES = {
            self.RESPONSE_MODE.Valid: {
                'types/Volume/instances/getByName::' +
                self.volume.name: '"{}"'.format(self.volume.id),
                'types/Volume/instances': {'id': self.volume.id},
                'types/Domain/instances/getByName::' +
                self.PROT_DOMAIN_NAME:
                    '"{}"'.format(self.PROT_DOMAIN_ID),
                'types/Pool/instances/getByName::{},{}'.format(
                    self.PROT_DOMAIN_ID,
                    self.STORAGE_POOL_NAME
                ): '"{}"'.format(self.STORAGE_POOL_ID),
            },
            self.RESPONSE_MODE.Invalid: {
                'types/Domain/instances/getByName::' +
                self.PROT_DOMAIN_NAME: None,
                'types/Pool/instances/getByName::{},{}'.format(
                    self.PROT_DOMAIN_ID,
                    self.STORAGE_POOL_NAME
                ): None,
            },
            self.RESPONSE_MODE.BadStatus: {
                'types/Volume/instances': self.BAD_STATUS_RESPONSE,
                'types/Domain/instances/getByName::' +
                self.PROT_DOMAIN_NAME: self.BAD_STATUS_RESPONSE,
                'types/Pool/instances/getByName::{},{}'.format(
                    self.PROT_DOMAIN_ID,
                    self.STORAGE_POOL_NAME
                ): self.BAD_STATUS_RESPONSE,
            },
        }

    def test_no_domain(self):
        """No protection domain name or ID provided."""
        self.driver.configuration.sio_protection_domain_name = None
        self.driver.configuration.sio_protection_domain_id = None
        self.driver.storage_pools = None
        self.volume.host = "host@backend"
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.test_create_volume)

    def test_no_domain_id(self):
        """Only protection domain name provided."""
        self.driver.protection_domain_id = None
        self.driver.protection_domain_name = self.PROT_DOMAIN_NAME
        self.driver.storage_pool_name = None
        self.driver.storage_pool_id = self.STORAGE_POOL_ID
        self.test_create_volume()

    def test_no_domain_id_invalid_response(self):
        self.set_https_response_mode(self.RESPONSE_MODE.Invalid)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.test_no_domain_id)

    def test_no_domain_id_badstatus_response(self):
        self.set_https_response_mode(self.RESPONSE_MODE.BadStatus)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.test_no_domain_id)

    def test_no_storage_id(self):
        """Only protection domain name provided."""
        self.driver.storage_pool_id = None
        self.driver.storage_pool_name = self.STORAGE_POOL_NAME
        self.driver.protection_domain_id = self.PROT_DOMAIN_ID
        self.driver.protection_domain_name = None
        self.test_create_volume()

    def test_no_storage_id_invalid_response(self):
        self.set_https_response_mode(self.RESPONSE_MODE.Invalid)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.test_no_storage_id)

    def test_no_storage_id_badstatus_response(self):
        self.set_https_response_mode(self.RESPONSE_MODE.BadStatus)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.test_no_storage_id)

    def test_create_volume(self):
        """Valid create volume parameters"""
        self.driver.create_volume(self.volume)

    def test_create_volume_non_8_gran(self):
        self.volume.size = 14
        model_update = self.driver.create_volume(self.volume)
        self.assertEqual(16, model_update['size'])

    def test_create_volume_badstatus_response(self):
        self.set_https_response_mode(self.RESPONSE_MODE.BadStatus)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.test_create_volume)

    @ddt.data({'provisioning:type': 'thin'}, {'provisioning:type': 'thin'})
    def test_create_thin_thick_volume(self, extraspecs):
        self.driver._get_volumetype_extraspecs = mock.MagicMock()
        self.driver._get_volumetype_extraspecs.return_value = extraspecs
        self.driver.create_volume(self.volume)

    def test_create_volume_bad_provisioning_type(self):
        extraspecs = {'provisioning:type': 'other'}
        self.driver._get_volumetype_extraspecs = mock.MagicMock()
        self.driver._get_volumetype_extraspecs.return_value = extraspecs
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.test_create_volume)
