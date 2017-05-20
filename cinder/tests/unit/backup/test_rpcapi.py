#    Copyright (c) 2015 Intel Corporation
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

"""
Unit Tests for cinder.backup.rpcapi
"""

import mock

from cinder.backup import rpcapi as backup_rpcapi
from cinder import objects
from cinder import test
from cinder.tests.unit.backup import fake_backup
from cinder.tests.unit import fake_constants as fake


class BackupRPCAPITestCase(test.RPCAPITestCase):
    def setUp(self):
        super(BackupRPCAPITestCase, self).setUp()
        self.rpcapi = backup_rpcapi.BackupAPI
        self.fake_backup_obj = fake_backup.fake_backup_obj(self.context)

    def test_create_backup(self):
        self._test_rpc_api('create_backup',
                           rpc_method='cast',
                           server=self.fake_backup_obj.host,
                           backup=self.fake_backup_obj)

    def test_restore_backup(self):
        self._test_rpc_api('restore_backup',
                           rpc_method='cast',
                           server='fake_volume_host',
                           volume_host='fake_volume_host',
                           backup=self.fake_backup_obj,
                           volume_id=fake.VOLUME_ID)

    def test_delete_backup(self):
        self._test_rpc_api('delete_backup',
                           rpc_method='cast',
                           server=self.fake_backup_obj.host,
                           backup=self.fake_backup_obj)

    def test_export_record(self):
        self._test_rpc_api('export_record',
                           rpc_method='call',
                           server=self.fake_backup_obj.host,
                           backup=self.fake_backup_obj,
                           retval={'backup_service': 'fake_backup_driver',
                                   'backup_url': 'http://fake_url'})

    def test_import_record(self):
        self._test_rpc_api('import_record',
                           rpc_method='cast',
                           server='fake_volume_host',
                           host='fake_volume_host',
                           backup=self.fake_backup_obj,
                           backup_service='fake_service',
                           backup_url='fake_url',
                           backup_hosts=['fake_host1', 'fake_host2'])

    def test_reset_status(self):
        self._test_rpc_api('reset_status',
                           rpc_method='cast',
                           server=self.fake_backup_obj.host,
                           backup=self.fake_backup_obj,
                           status='error')

    def test_check_support_to_force_delete(self):
        self._test_rpc_api('check_support_to_force_delete',
                           rpc_method='call',
                           server='fake_volume_host',
                           host='fake_volume_host',
                           retval=True)

    @mock.patch('oslo_messaging.RPCClient.can_send_version', mock.Mock())
    def test_set_log_levels(self):
        service = objects.Service(self.context, host='host1')
        self._test_rpc_api('set_log_levels',
                           rpc_method='cast',
                           server=service.host,
                           service=service,
                           log_request='log_request',
                           version='2.1')

    @mock.patch('oslo_messaging.RPCClient.can_send_version', mock.Mock())
    def test_get_log_levels(self):
        service = objects.Service(self.context, host='host1')
        self._test_rpc_api('get_log_levels',
                           rpc_method='call',
                           server=service.host,
                           service=service,
                           log_request='log_request',
                           version='2.1')
