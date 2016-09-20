
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

import copy

import ddt
import mock

from cinder import context
from cinder.scheduler import rpcapi as scheduler_rpcapi
from cinder import test
from cinder.tests.unit import fake_constants
from cinder.tests.unit import fake_volume


@ddt.ddt
class SchedulerRpcAPITestCase(test.TestCase):

    def setUp(self):
        super(SchedulerRpcAPITestCase, self).setUp()
        self.patch('oslo_messaging.RPCClient.can_send_version',
                   return_value=True)
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
                retval = getattr(rpcapi, method)(ctxt, **kwargs)
                self.assertEqual(expected_retval, retval)
                expected_args = [ctxt, method, expected_msg]
                for arg, expected_arg in zip(self.fake_args, expected_args):
                    self.assertEqual(expected_arg, arg)

                for kwarg, value in self.fake_kwargs.items():
                    self.assertEqual(expected_msg[kwarg], value)

    def test_update_service_capabilities(self):
        self._test_scheduler_api('update_service_capabilities',
                                 rpc_method='cast',
                                 service_name='fake_name',
                                 host='fake_host',
                                 capabilities='fake_capabilities',
                                 fanout=True,
                                 version='3.0')

    @mock.patch('oslo_messaging.RPCClient.can_send_version', return_value=True)
    def test_create_volume(self, can_send_version):
        self._test_scheduler_api('create_volume',
                                 rpc_method='cast',
                                 topic='topic',
                                 volume_id=self.volume_id,
                                 snapshot_id='snapshot_id',
                                 image_id='image_id',
                                 request_spec='fake_request_spec',
                                 filter_properties='filter_properties',
                                 volume=fake_volume.fake_volume_obj(
                                     self.context),
                                 version='3.0')
        can_send_version.assert_has_calls([mock.call('3.0')])

    @mock.patch('oslo_messaging.RPCClient.can_send_version',
                return_value=False)
    def test_create_volume_serialization(self, can_send_version):
        self._test_scheduler_api('create_volume',
                                 rpc_method='cast',
                                 topic='topic',
                                 volume_id=self.volume_id,
                                 snapshot_id='snapshot_id',
                                 image_id='image_id',
                                 request_spec={'volume_type': {}},
                                 filter_properties='filter_properties',
                                 volume=fake_volume.fake_volume_obj(
                                     self.context),
                                 version='2.0')
        can_send_version.assert_has_calls([mock.call('3.0'), mock.call('2.2')])

    def test_migrate_volume_to_host(self):
        self._test_scheduler_api('migrate_volume_to_host',
                                 rpc_method='cast',
                                 topic='topic',
                                 volume_id=self.volume_id,
                                 host='host',
                                 force_host_copy=True,
                                 request_spec='fake_request_spec',
                                 filter_properties='filter_properties',
                                 volume=fake_volume.fake_volume_obj(
                                     self.context),
                                 version='3.0')

    def test_retype(self):
        self._test_scheduler_api('retype',
                                 rpc_method='cast',
                                 topic='topic',
                                 volume_id=self.volume_id,
                                 request_spec='fake_request_spec',
                                 filter_properties='filter_properties',
                                 volume=fake_volume.fake_volume_obj(
                                     self.context),
                                 version='3.0')

    @ddt.data('2.0', '2.1')
    @mock.patch('oslo_messaging.RPCClient.can_send_version')
    def test_manage_existing(self, version, can_send_version):
        can_send_version.side_effect = lambda x: x == version
        self._test_scheduler_api('manage_existing',
                                 rpc_method='cast',
                                 topic='topic',
                                 volume_id=self.volume_id,
                                 request_spec='fake_request_spec',
                                 filter_properties='filter_properties',
                                 volume=fake_volume.fake_volume_obj(
                                     self.context),
                                 version=version)
        can_send_version.assert_has_calls([mock.call('3.0'), mock.call('2.1')])

    def test_get_pools(self):
        self._test_scheduler_api('get_pools',
                                 rpc_method='call',
                                 filters=None,
                                 version='3.0')

    def test_create_group(self):
        self._test_scheduler_api('create_group',
                                 rpc_method='cast',
                                 topic='topic',
                                 group='group',
                                 group_spec='group_spec_p',
                                 request_spec_list=['fake_request_spec_list'],
                                 group_filter_properties=
                                 'fake_group_filter_properties',
                                 filter_properties_list=
                                 ['fake_filter_properties_list'],
                                 version='3.0')
