
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

import ddt
import mock

from cinder import context
from cinder import exception
from cinder.scheduler import rpcapi as scheduler_rpcapi
from cinder import test
from cinder.tests.unit import fake_constants
from cinder.tests.unit import fake_volume


@ddt.ddt
class SchedulerRpcAPITestCase(test.TestCase):

    def setUp(self):
        super(SchedulerRpcAPITestCase, self).setUp()
        self.context = context.RequestContext('fake_user', 'fake_project')
        self.volume_id = fake_constants.VOLUME_ID

    def _test_scheduler_api(self, method, rpc_method,
                            fanout=False, **kwargs):
        ctxt = self.context
        rpcapi = scheduler_rpcapi.SchedulerAPI()
        expected_retval = 'foo' if rpc_method == 'call' else None

        target = {
            "fanout": fanout,
            "version": kwargs.pop('version', rpcapi.RPC_API_VERSION)
        }

        expected_msg = kwargs.copy()

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
                retval = getattr(rpcapi, method)(ctxt, **kwargs)
                self.assertEqual(expected_retval, retval)
                expected_args = [ctxt, method, expected_msg]
                for arg, expected_arg in zip(self.fake_args, expected_args):
                    self.assertEqual(expected_arg, arg)

                for kwarg, value in self.fake_kwargs.items():
                    self.assertEqual(expected_msg[kwarg], value)

    @ddt.data('3.0', '3.3')
    @mock.patch('oslo_messaging.RPCClient.can_send_version')
    def test_update_service_capabilities(self, version, can_send_version):
        can_send_version.side_effect = lambda x: x == version
        self._test_scheduler_api('update_service_capabilities',
                                 rpc_method='cast',
                                 service_name='fake_name',
                                 host='fake_host',
                                 cluster_name='cluster_name',
                                 capabilities={},
                                 fanout=True,
                                 version=version,
                                 timestamp='123')
        can_send_version.assert_called_once_with('3.3')

    def test_create_volume(self):
        volume = fake_volume.fake_volume_obj(self.context)
        create_worker_mock = self.mock_object(volume, 'create_worker')
        self._test_scheduler_api('create_volume',
                                 rpc_method='cast',
                                 snapshot_id='snapshot_id',
                                 image_id='image_id',
                                 request_spec='fake_request_spec',
                                 filter_properties='filter_properties',
                                 volume=volume,
                                 version='3.0')
        create_worker_mock.assert_called_once()

    @mock.patch('oslo_messaging.RPCClient.can_send_version', return_value=True)
    def test_notify_service_capabilities(self, can_send_version_mock):
        capabilities = {'host': 'fake_host',
                        'total': '10.01', }
        self._test_scheduler_api('notify_service_capabilities',
                                 rpc_method='cast',
                                 service_name='fake_name',
                                 host='fake_host',
                                 capabilities=capabilities,
                                 version='3.1')

    @mock.patch('oslo_messaging.RPCClient.can_send_version',
                return_value=False)
    def test_notify_service_capabilities_capped(self, can_send_version_mock):
        capabilities = {'host': 'fake_host',
                        'total': '10.01', }
        self.assertRaises(exception.ServiceTooOld,
                          self._test_scheduler_api,
                          'notify_service_capabilities',
                          rpc_method='cast',
                          service_name='fake_name',
                          host='fake_host',
                          capabilities=capabilities,
                          version='3.1')

    def test_create_volume_serialization(self):
        volume = fake_volume.fake_volume_obj(self.context)
        create_worker_mock = self.mock_object(volume, 'create_worker')
        self._test_scheduler_api('create_volume',
                                 rpc_method='cast',
                                 snapshot_id='snapshot_id',
                                 image_id='image_id',
                                 request_spec={'volume_type': {}},
                                 filter_properties='filter_properties',
                                 volume=volume,
                                 version='3.0')
        create_worker_mock.assert_called_once()

    @mock.patch('oslo_messaging.RPCClient.can_send_version')
    def test_migrate_volume(self, can_send_version):
        volume = fake_volume.fake_volume_obj(self.context)
        create_worker_mock = self.mock_object(volume, 'create_worker')
        self._test_scheduler_api('migrate_volume',
                                 rpc_method='cast',
                                 backend='host',
                                 force_copy=True,
                                 request_spec='fake_request_spec',
                                 filter_properties='filter_properties',
                                 volume=volume,
                                 version='3.3')
        create_worker_mock.assert_not_called()

    def test_retype(self):
        volume = fake_volume.fake_volume_obj(self.context)
        create_worker_mock = self.mock_object(volume, 'create_worker')
        self._test_scheduler_api('retype',
                                 rpc_method='cast',
                                 request_spec='fake_request_spec',
                                 filter_properties='filter_properties',
                                 volume=volume,
                                 version='3.0')
        create_worker_mock.assert_not_called()

    def test_manage_existing(self):
        volume = fake_volume.fake_volume_obj(self.context)
        create_worker_mock = self.mock_object(volume, 'create_worker')
        self._test_scheduler_api('manage_existing',
                                 rpc_method='cast',
                                 request_spec='fake_request_spec',
                                 filter_properties='filter_properties',
                                 volume=volume,
                                 version='3.0')
        create_worker_mock.assert_not_called()

    @mock.patch('oslo_messaging.RPCClient.can_send_version',
                return_value=False)
    def test_extend_volume_capped(self, can_send_version_mock):
        new_size = 4
        volume = fake_volume.fake_volume_obj(self.context)
        self.assertRaises(exception.ServiceTooOld,
                          self._test_scheduler_api,
                          'extend_volume',
                          rpc_method='cast',
                          request_spec='fake_request_spec',
                          filter_properties='filter_properties',
                          volume=volume,
                          new_size=new_size,
                          reservations=['RESERVATIONS'],
                          version='3.0')

    @mock.patch('oslo_messaging.RPCClient.can_send_version', return_value=True)
    def test_extend_volume(self, can_send_version_mock):
        new_size = 4
        volume = fake_volume.fake_volume_obj(self.context)
        create_worker_mock = self.mock_object(volume, 'create_worker')
        self._test_scheduler_api('extend_volume',
                                 rpc_method='cast',
                                 request_spec='fake_request_spec',
                                 filter_properties='filter_properties',
                                 volume=volume,
                                 new_size=new_size,
                                 reservations=['RESERVATIONS'],
                                 version='3.0')
        create_worker_mock.assert_not_called()

    def test_get_pools(self):
        self._test_scheduler_api('get_pools',
                                 rpc_method='call',
                                 filters=None,
                                 version='3.0')

    def test_create_group(self):
        self._test_scheduler_api('create_group',
                                 rpc_method='cast',
                                 group='group',
                                 group_spec='group_spec_p',
                                 request_spec_list=['fake_request_spec_list'],
                                 group_filter_properties=
                                 'fake_group_filter_properties',
                                 filter_properties_list=
                                 ['fake_filter_properties_list'],
                                 version='3.0')
