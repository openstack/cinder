#    Copyright 2015 OpenStack Foundation
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
#

import mock

from cinder import test
from cinder.volume import configuration
from cinder.volume.drivers.san import san


class SanDriverTestCase(test.TestCase):
    """Tests for SAN driver"""

    def __init__(self, *args, **kwargs):
        super(SanDriverTestCase, self).__init__(*args, **kwargs)

    def setUp(self):
        super(SanDriverTestCase, self).setUp()
        self.configuration = mock.Mock(spec=configuration.Configuration)
        self.configuration.san_is_local = False
        self.configuration.san_ip = "10.0.0.1"
        self.configuration.san_login = "admin"
        self.configuration.san_password = "password"
        self.configuration.san_ssh_port = 22
        self.configuration.san_thin_provision = True
        self.configuration.san_private_key = 'private_key'
        self.configuration.ssh_min_pool_conn = 1
        self.configuration.ssh_max_pool_conn = 5
        self.configuration.ssh_conn_timeout = 30

    class fake_san_driver(san.SanDriver):
        def initialize_connection():
            pass

        def create_volume():
            pass

        def delete_volume():
            pass

        def terminate_connection():
            pass

    @mock.patch.object(san.processutils, 'ssh_execute')
    @mock.patch.object(san.ssh_utils, 'SSHPool')
    @mock.patch.object(san.utils, 'check_ssh_injection')
    def test_ssh_formatted_command(self, mock_check_ssh_injection,
                                   mock_ssh_pool, mock_ssh_execute):
        driver = self.fake_san_driver(configuration=self.configuration)
        cmd_list = ['uname', '-s']
        expected_cmd = 'uname -s'
        driver.san_execute(*cmd_list)
        # get the same used mocked item from the pool
        with driver.sshpool.item() as ssh_item:
            mock_ssh_execute.assert_called_with(ssh_item, expected_cmd,
                                                check_exit_code=None)
