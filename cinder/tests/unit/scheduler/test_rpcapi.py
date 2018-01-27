
# Copyright 2012, Red Hat, Inc.
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
Unit Tests for cinder.scheduler.rpcapi
"""

from datetime import datetime

import ddt
import mock

from cinder import exception
from cinder import objects
from cinder.scheduler import rpcapi as scheduler_rpcapi
from cinder import test
from cinder.tests.unit import fake_constants
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume


@ddt.ddt
class SchedulerRPCAPITestCase(test.RPCAPITestCase):
    def setUp(self):
        super(SchedulerRPCAPITestCase, self).setUp()
        self.rpcapi = scheduler_rpcapi.SchedulerAPI
        self.base_version = '3.0'
        self.volume_id = fake_constants.VOLUME_ID
        self.fake_volume = fake_volume.fake_volume_obj(
            self.context, expected_attrs=['metadata', 'admin_metadata',
                                          'glance_metadata'])
        self.fake_snapshot = fake_snapshot.fake_snapshot_obj(
            self.context)
        self.fake_rs_obj = objects.RequestSpec.from_primitives({})
        self.fake_rs_dict = {'volume_id': self.volume_id}
        self.fake_fp_dict = {'availability_zone': 'fake_az'}

    @ddt.data('3.0', '3.3')
    @mock.patch('oslo_messaging.RPCClient.can_send_version')
    def test_update_service_capabilities(self, version, can_send_version):
        can_send_version.side_effect = lambda x: x == version
        self._test_rpc_api('update_service_capabilities',
                           rpc_method='cast',
                           service_name='fake_name',
                           host='fake_host',
                           cluster_name='cluster_name',
                           capabilities={},
                           fanout=True,
                           version=version,
                           timestamp='123')
        can_send_version.assert_called_once_with('3.3')

    @ddt.data('3.0', '3.10')
    @mock.patch('oslo_messaging.RPCClient.can_send_version')
    def test_create_volume(self, version, can_send_version):
        can_send_version.side_effect = lambda x: x == version
        create_worker_mock = self.mock_object(self.fake_volume,
                                              'create_worker')
        self._test_rpc_api('create_volume',
                           rpc_method='cast',
                           volume=self.fake_volume,
                           snapshot_id=fake_constants.SNAPSHOT_ID,
                           image_id=fake_constants.IMAGE_ID,
                           backup_id=fake_constants.BACKUP_ID,
                           request_spec=self.fake_rs_obj,
                           filter_properties=self.fake_fp_dict)
        create_worker_mock.assert_called_once()
        can_send_version.assert_called_once_with('3.10')

    @mock.patch('oslo_messaging.RPCClient.can_send_version',
                return_value=True)
    def test_create_snapshot(self, can_send_version_mock):
        self._test_rpc_api('create_snapshot',
                           rpc_method='cast',
                           volume='fake_volume',
                           snapshot='fake_snapshot',
                           backend='fake_backend',
                           request_spec={'snapshot_id': self.fake_snapshot.id},
                           filter_properties=None)

    @mock.patch('oslo_messaging.RPCClient.can_send_version',
                return_value=False)
    def test_create_snapshot_capped(self, can_send_version_mock):
        self.assertRaises(exception.ServiceTooOld,
                          self._test_rpc_api,
                          'create_snapshot',
                          rpc_method='cast',
                          volume=self.fake_volume,
                          snapshot=self.fake_snapshot,
                          backend='fake_backend',
                          request_spec=self.fake_rs_obj,
                          version='3.5')

    @mock.patch('oslo_messaging.RPCClient.can_send_version',
                return_value=True)
    def test_manage_existing_snapshot(self, can_send_version_mock):
        self._test_rpc_api('manage_existing_snapshot',
                           rpc_method='cast',
                           volume='fake_volume',
                           snapshot='fake_snapshot',
                           ref='fake_ref',
                           request_spec={'snapshot_id': self.fake_snapshot.id},
                           filter_properties=None)

    @mock.patch('oslo_messaging.RPCClient.can_send_version',
                return_value=False)
    def test_manage_existing_snapshot_capped(self, can_send_version_mock):
        self.assertRaises(exception.ServiceTooOld,
                          self._test_rpc_api,
                          'manage_existing_snapshot',
                          rpc_method='cast',
                          volume=self.fake_volume,
                          snapshot=self.fake_snapshot,
                          ref='fake_ref',
                          request_spec={'snapshot_id': self.fake_snapshot.id,
                                        'ref': 'fake_ref'},
                          filter_properties=None,
                          version='3.10')

    @mock.patch('oslo_messaging.RPCClient.can_send_version', return_value=True)
    def test_notify_service_capabilities_backend(self, can_send_version_mock):
        """Test sending new backend by RPC instead of old host parameter."""
        capabilities = {'host': 'fake_host',
                        'total': '10.01', }
        with mock.patch('oslo_utils.timeutils.utcnow',
                        return_value=datetime(1970, 1, 1)):
            self._test_rpc_api('notify_service_capabilities',
                               rpc_method='cast',
                               service_name='fake_name',
                               backend='fake_host',
                               capabilities=capabilities,
                               timestamp='1970-01-01T00:00:00.000000',
                               version='3.5')

    @mock.patch('oslo_messaging.RPCClient.can_send_version',
                side_effect=(True, False))
    def test_notify_service_capabilities_host(self, can_send_version_mock):
        """Test sending old host RPC parameter instead of backend."""
        capabilities = {'host': 'fake_host',
                        'total': '10.01', }
        self._test_rpc_api('notify_service_capabilities',
                           rpc_method='cast',
                           service_name='fake_name',
                           server='fake_host',
                           expected_kwargs_diff={'host': 'fake_host'},
                           backend='fake_host',
                           capabilities=capabilities,
                           version='3.1')

    @mock.patch('oslo_messaging.RPCClient.can_send_version',
                return_value=False)
    def test_notify_service_capabilities_capped(self, can_send_version_mock):
        capabilities = {'host': 'fake_host',
                        'total': '10.01', }
        self.assertRaises(exception.ServiceTooOld,
                          self._test_rpc_api,
                          'notify_service_capabilities',
                          rpc_method='cast',
                          service_name='fake_name',
                          backend='fake_host',
                          server='fake_host',
                          # ignore_for_method=['host'],
                          # ignore_for_rpc=['backend'],
                          capabilities=capabilities,
                          version='3.1')

    @mock.patch('oslo_messaging.RPCClient.can_send_version')
    def test_migrate_volume(self, can_send_version):
        create_worker_mock = self.mock_object(self.fake_volume,
                                              'create_worker')
        self._test_rpc_api('migrate_volume',
                           rpc_method='cast',
                           backend='host',
                           force_copy=True,
                           request_spec='fake_request_spec',
                           filter_properties='filter_properties',
                           volume=self.fake_volume,
                           version='3.3')
        create_worker_mock.assert_not_called()

    def test_retype(self):
        self._test_rpc_api('retype',
                           rpc_method='cast',
                           request_spec=self.fake_rs_dict,
                           filter_properties=self.fake_fp_dict,
                           volume=self.fake_volume)

    def test_manage_existing(self):
        self._test_rpc_api('manage_existing',
                           rpc_method='cast',
                           request_spec=self.fake_rs_dict,
                           filter_properties=self.fake_fp_dict,
                           volume=self.fake_volume)

    @mock.patch('oslo_messaging.RPCClient.can_send_version',
                return_value=False)
    def test_extend_volume_capped(self, can_send_version_mock):
        self.assertRaises(exception.ServiceTooOld,
                          self._test_rpc_api,
                          'extend_volume',
                          rpc_method='cast',
                          request_spec='fake_request_spec',
                          filter_properties='filter_properties',
                          volume=self.fake_volume,
                          new_size=4,
                          reservations=['RESERVATIONS'],
                          version='3.0')

    @mock.patch('oslo_messaging.RPCClient.can_send_version', return_value=True)
    def test_extend_volume(self, can_send_version_mock):
        create_worker_mock = self.mock_object(self.fake_volume,
                                              'create_worker')
        self._test_rpc_api('extend_volume',
                           rpc_method='cast',
                           request_spec='fake_request_spec',
                           filter_properties='filter_properties',
                           volume=self.fake_volume,
                           new_size=4,
                           reservations=['RESERVATIONS'])
        create_worker_mock.assert_not_called()

    def test_get_pools(self):
        self._test_rpc_api('get_pools',
                           rpc_method='call',
                           filters=None,
                           retval=[{
                               'name': 'fake_pool',
                               'capabilities': {},
                           }])

    def test_create_group(self):
        self._test_rpc_api('create_group',
                           rpc_method='cast',
                           group='group',
                           group_spec=self.fake_rs_dict,
                           request_spec_list=[self.fake_rs_dict],
                           group_filter_properties=[self.fake_fp_dict],
                           filter_properties_list=[self.fake_fp_dict])

    @ddt.data(('work_cleanup', 'myhost', None),
              ('work_cleanup', 'myhost', 'mycluster'),
              ('do_cleanup', 'myhost', None),
              ('do_cleanup', 'myhost', 'mycluster'))
    @ddt.unpack
    @mock.patch('cinder.rpc.get_client')
    def test_cleanup(self, method, host, cluster, get_client):
        cleanup_request = objects.CleanupRequest(self.context,
                                                 host=host,
                                                 cluster_name=cluster)
        rpcapi = scheduler_rpcapi.SchedulerAPI()
        getattr(rpcapi, method)(self.context, cleanup_request)

        prepare = get_client.return_value.prepare

        prepare.assert_called_once_with(
            version='3.4')
        rpc_call = 'cast' if method == 'do_cleanup' else 'call'
        getattr(prepare.return_value, rpc_call).assert_called_once_with(
            self.context, method, cleanup_request=cleanup_request)

    @ddt.data('do_cleanup', 'work_cleanup')
    def test_cleanup_too_old(self, method):
        cleanup_request = objects.CleanupRequest(self.context)
        rpcapi = scheduler_rpcapi.SchedulerAPI()
        with mock.patch.object(rpcapi.client, 'can_send_version',
                               return_value=False) as can_send_mock:
            self.assertRaises(exception.ServiceTooOld,
                              getattr(rpcapi, method),
                              self.context,
                              cleanup_request)
            can_send_mock.assert_called_once_with('3.4')

    @mock.patch('oslo_messaging.RPCClient.can_send_version', mock.Mock())
    def test_set_log_levels(self):
        service = objects.Service(self.context, host='host1')
        self._test_rpc_api('set_log_levels',
                           rpc_method='cast',
                           server=service.host,
                           service=service,
                           log_request='log_request',
                           version='3.7')

    @mock.patch('oslo_messaging.RPCClient.can_send_version', mock.Mock())
    def test_get_log_levels(self):
        service = objects.Service(self.context, host='host1')
        self._test_rpc_api('get_log_levels',
                           rpc_method='call',
                           server=service.host,
                           service=service,
                           log_request='log_request',
                           version='3.7')
