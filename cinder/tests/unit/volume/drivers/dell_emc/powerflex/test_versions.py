# Copyright (C) 2017 Dell Inc. or its subsidiaries.
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

from cinder import exception
from cinder.tests.unit.volume.drivers.dell_emc import powerflex


@ddt.ddt
class TestMultipleVersions(powerflex.TestPowerFlexDriver):

    version = '1.2.3.4'
    good_versions = ['1.2.3.4',
                     '101.102.103.104.105.106.107',
                     '1.0'
                     ]
    bad_versions = ['bad',
                    'bad.version.number',
                    '1.0b',
                    '.6'
                    ]

    # Test cases for ``PowerFlexDriver._get_server_api_version()``
    def setUp(self):
        """Setup a test case environment."""
        super(TestMultipleVersions, self).setUp()

        self.HTTPS_MOCK_RESPONSES = {
            self.RESPONSE_MODE.Valid: {
                'version': '"{}"'.format(self.version),
            },
            self.RESPONSE_MODE.Invalid: {
                'version': None,
            },
            self.RESPONSE_MODE.BadStatus: {
                'version': self.BAD_STATUS_RESPONSE,
            },
        }

    def test_version_api_fails(self):
        """version api returns a non-200 response."""
        self.set_https_response_mode(self.RESPONSE_MODE.Invalid)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.test_version)

    def test_version(self):
        """Valid version request."""
        self.driver.primary_client.query_rest_api_version(False)

    def test_version_badstatus_response(self):
        """Version api returns a bad response."""
        self.set_https_response_mode(self.RESPONSE_MODE.BadStatus)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.test_version)

    def setup_response(self):
        self.HTTPS_MOCK_RESPONSES = {
            self.RESPONSE_MODE.Valid: {
                'version': '"{}"'.format(self.version),
            },
        }

    def test_version_badversions(self):
        """Version api returns an invalid version number."""
        for vers in self.bad_versions:
            self.version = vers
            self.setup_response()
            self.assertRaises(exception.VolumeBackendAPIException,
                              self.test_version)

    def test_version_goodversions(self):
        """Version api returns a valid version number."""
        for vers in self.good_versions:
            self.version = vers
            self.setup_response()
            self.driver.primary_client.query_rest_api_version(False)
            self.assertEqual(
                self.driver.primary_client.query_rest_api_version(False),
                vers
            )
