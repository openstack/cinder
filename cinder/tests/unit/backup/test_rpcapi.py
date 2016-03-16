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

import copy

import mock

from cinder.backup import rpcapi as backup_rpcapi
from cinder import context
from cinder import objects
from cinder import test
from cinder.tests.unit import fake_backup
from cinder.tests.unit import fake_constants as fake


class BackupRpcAPITestCase(test.TestCase):
    def setUp(self):
        super(BackupRpcAPITestCase, self).setUp()
        self.context = context.RequestContext(fake.user_id, fake.project_id)
        self.fake_backup_obj = fake_backup.fake_backup_obj(self.context)

    def _test_backup_api(self, method, rpc_method, server=None, fanout=False,
                         **kwargs):
        rpcapi = backup_rpcapi.BackupAPI()
        expected_retval = 'foo' if rpc_method == 'call' else None

        target = {
            "server": server,
            "fanout": fanout,
            "version": kwargs.pop('version', rpcapi.RPC_API_VERSION)
        }

        expected_msg = copy.deepcopy(kwargs)

        self.fake_args = None
        self.fake_kwargs = None

        def _fake_prepare_method(*args, **kwds):
            for kwd in kwds:
                self.assertEqual(target[kwd], kwds[kwd])
            return rpcapi.client

        def _fake_rpc_method(*args, **kwargs):
            self.fake_args = args
            self.fake_kwargs = kwargs
            if expected_retval:
                return expected_retval

        with mock.patch.object(rpcapi.client, "prepare") as mock_prepared:
            mock_prepared.side_effect = _fake_prepare_method

            with mock.patch.object(rpcapi.client, rpc_method) as mock_method:
                mock_method.side_effect = _fake_rpc_method
                retval = getattr(rpcapi, method)(self.context, **kwargs)
                self.assertEqual(expected_retval, retval)
                expected_args = [self.context, method, expected_msg]
                for arg, expected_arg in zip(self.fake_args, expected_args):
                    self.assertEqual(expected_arg, arg)

                for kwarg, value in self.fake_kwargs.items():
                    if isinstance(value, objects.Backup):
                        expected_back = expected_msg[kwarg].obj_to_primitive()
                        backup = value.obj_to_primitive()
                        self.assertEqual(expected_back, backup)
                    else:
                        self.assertEqual(expected_msg[kwarg], value)

    @mock.patch('oslo_messaging.RPCClient.can_send_version', return_value=True)
    def test_create_backup(self, can_send_version):
        self._test_backup_api('create_backup',
                              rpc_method='cast',
                              server=self.fake_backup_obj.host,
                              backup=self.fake_backup_obj,
                              version='2.0')

        can_send_version.return_value = False
        self._test_backup_api('create_backup',
                              rpc_method='cast',
                              server=self.fake_backup_obj.host,
                              backup=self.fake_backup_obj,
                              version='1.1')

    @mock.patch('oslo_messaging.RPCClient.can_send_version', return_value=True)
    def test_restore_backup(self, can_send_version):
        self._test_backup_api('restore_backup',
                              rpc_method='cast',
                              server='fake_volume_host',
                              volume_host='fake_volume_host',
                              backup=self.fake_backup_obj,
                              volume_id='fake_volume_id',
                              version='2.0')

        can_send_version.return_value = False
        self._test_backup_api('restore_backup',
                              rpc_method='cast',
                              server='fake_volume_host',
                              volume_host='fake_volume_host',
                              backup=self.fake_backup_obj,
                              volume_id=fake.volume_id,
                              version='1.1')

    @mock.patch('oslo_messaging.RPCClient.can_send_version', return_value=True)
    def test_delete_backup(self, can_send_version):
        self._test_backup_api('delete_backup',
                              rpc_method='cast',
                              server=self.fake_backup_obj.host,
                              backup=self.fake_backup_obj,
                              version='2.0')

        can_send_version.return_value = False
        self._test_backup_api('delete_backup',
                              rpc_method='cast',
                              server=self.fake_backup_obj.host,
                              backup=self.fake_backup_obj,
                              version='1.1')

    @mock.patch('oslo_messaging.RPCClient.can_send_version', return_value=True)
    def test_export_record(self, can_send_version):
        self._test_backup_api('export_record',
                              rpc_method='call',
                              server=self.fake_backup_obj.host,
                              backup=self.fake_backup_obj,
                              version='2.0')

        can_send_version.return_value = False
        self._test_backup_api('export_record',
                              rpc_method='call',
                              server=self.fake_backup_obj.host,
                              backup=self.fake_backup_obj,
                              version='1.1')

    @mock.patch('oslo_messaging.RPCClient.can_send_version', return_value=True)
    def test_import_record(self, can_send_version):
        self._test_backup_api('import_record',
                              rpc_method='cast',
                              server='fake_volume_host',
                              host='fake_volume_host',
                              backup=self.fake_backup_obj,
                              backup_service='fake_service',
                              backup_url='fake_url',
                              backup_hosts=['fake_host1', 'fake_host2'],
                              version='2.0')

        can_send_version.return_value = False
        self._test_backup_api('import_record',
                              rpc_method='cast',
                              server='fake_volume_host',
                              host='fake_volume_host',
                              backup=self.fake_backup_obj,
                              backup_service='fake_service',
                              backup_url='fake_url',
                              backup_hosts=['fake_host1', 'fake_host2'],
                              version='1.1')

    @mock.patch('oslo_messaging.RPCClient.can_send_version', return_value=True)
    def test_reset_status(self, can_send_version):
        self._test_backup_api('reset_status',
                              rpc_method='cast',
                              server=self.fake_backup_obj.host,
                              backup=self.fake_backup_obj,
                              status='error',
                              version='2.0')

        can_send_version.return_value = False
        self._test_backup_api('reset_status',
                              rpc_method='cast',
                              server=self.fake_backup_obj.host,
                              backup=self.fake_backup_obj,
                              status='error',
                              version='1.1')

    @mock.patch('oslo_messaging.RPCClient.can_send_version', return_value=True)
    def test_check_support_to_force_delete(self, can_send_version):
        self._test_backup_api('check_support_to_force_delete',
                              rpc_method='call',
                              server='fake_volume_host',
                              host='fake_volume_host',
                              version='2.0')

        can_send_version.return_value = False
        self._test_backup_api('check_support_to_force_delete',
                              rpc_method='call',
                              server='fake_volume_host',
                              host='fake_volume_host',
                              version='1.1')
