# Copyright (c) 2020 Dell Inc. or its subsidiaries.
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
from cinder.volume import configuration


@ddt.ddt
class TestReplication(powerflex.TestPowerFlexDriver):
    """Test cases for PowerFlex replication support."""

    def setUp(self):
        super(TestReplication, self).setUp()

        self.replication_backend_id = 'powerflex_repl'
        replication_device = [
            {
                'backend_id': self.replication_backend_id,
                'san_ip': '127.0.0.2',
                'san_login': 'test',
                'san_password': 'pass'
            }
        ]
        self.override_config('replication_device',
                             override=replication_device,
                             group=configuration.SHARED_CONF_GROUP)

        self.HTTPS_MOCK_RESPONSES = {
            self.RESPONSE_MODE.Valid: {
                'types/Domain/instances/getByName::' + self.PROT_DOMAIN_NAME:
                    '"{}"'.format(self.PROT_DOMAIN_ID),
                'types/Pool/instances/getByName::{},{}'.format(
                    self.PROT_DOMAIN_ID, self.STORAGE_POOL_NAME):
                    '"{}"'.format(self.STORAGE_POOL_ID),
                'instances/ProtectionDomain::{}'.format(self.PROT_DOMAIN_ID):
                    {'id': self.PROT_DOMAIN_ID},
                'instances/StoragePool::{}'.format(self.STORAGE_POOL_ID):
                    {'id': self.STORAGE_POOL_ID, 'zeroPaddingEnabled': True},
            },
        }

    def test_do_setup_replication_configured(self):
        super(powerflex.mocks.PowerFlexDriver, self.driver).do_setup({})
        self.driver.check_for_setup_error()
        self.assertTrue(self.driver.secondary_client.is_configured)
        self.assertTrue(self.driver.replication_enabled)

    @ddt.data(
        [
            {
                'backend_id': 'powerflex_repl1'
            },
            {
                'backend_id': 'powerflex_repl2'
            }
        ],
        [
            {
                'backend_id': 'powerflex_repl1',
                'san_ip': '127.0.0.2'
            },
        ]
    )
    def test_do_setup_replication_bad_configuration(self, replication_device):
        self.override_config('replication_device',
                             override=replication_device,
                             group=configuration.SHARED_CONF_GROUP)
        self.assertRaises(exception.InvalidInput,
                          super(powerflex.mocks.PowerFlexDriver,
                                self.driver).do_setup,
                          {})

    def test_do_setup_already_failed_over(self):
        self.driver.active_backend_id = 'powerflex_repl'
        super(powerflex.mocks.PowerFlexDriver, self.driver).do_setup({})
        self.driver.check_for_setup_error()
        self.assertFalse(self.driver.replication_enabled)

    def test_failover_host(self):
        self.test_do_setup_replication_configured()
        self.driver.failover_host({}, [], self.replication_backend_id)
        self.assertEqual(self.replication_backend_id,
                         self.driver.active_backend_id)

    def test_failover_host_failback(self):
        self.test_do_setup_already_failed_over()
        self.driver.failover_host({}, [], 'default')
        self.assertEqual('default', self.driver.active_backend_id)

    @ddt.data("not_valid_target", None)
    def test_failover_host_secondary_id_invalid(self, secondary_id):
        self.test_do_setup_replication_configured()
        self.assertRaises(exception.InvalidReplicationTarget,
                          self.driver.failover_host,
                          context={},
                          volumes=[],
                          secondary_id=secondary_id)
