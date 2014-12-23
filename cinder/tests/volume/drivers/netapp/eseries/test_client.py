# Copyright (c) 2014 Alex Meade
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

import mock

from cinder import test
from cinder.volume.drivers.netapp.eseries import client


class NetAppEseriesClientDriverTestCase(test.TestCase):
    """Test case for NetApp e-series client."""

    def setUp(self):
        super(NetAppEseriesClientDriverTestCase, self).setUp()
        self.mock_log = mock.Mock()
        self.mock_object(client, 'LOG', self.mock_log)
        self.fake_password = 'mysecret'
        self.my_client = client.RestClient('http', 'host', '80', '/test',
                                           'user', self.fake_password,
                                           system_id='fake_sys_id')
        self.my_client.invoke_service = mock.Mock()

    def test_register_storage_system_does_not_log_password(self):
        self.my_client.register_storage_system([], password=self.fake_password)
        for call in self.mock_log.debug.mock_calls:
            __, args, __ = call
            self.assertNotIn(self.fake_password, args[0])

    def test_update_stored_system_password_does_not_log_password(self):
        self.my_client.update_stored_system_password(
            password=self.fake_password)
        for call in self.mock_log.debug.mock_calls:
            __, args, __ = call
            self.assertNotIn(self.fake_password, args[0])
