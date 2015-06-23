
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

import mock
from oslo_config import cfg

from cinder import context
from cinder.scheduler import rpcapi as scheduler_rpcapi
from cinder import test


CONF = cfg.CONF


class SchedulerRpcAPITestCase(test.TestCase):

    def setUp(self):
        super(SchedulerRpcAPITestCase, self).setUp()

    def tearDown(self):
        super(SchedulerRpcAPITestCase, self).tearDown()

    def _test_scheduler_api(self, method, rpc_method,
                            fanout=False, **kwargs):
        ctxt = context.RequestContext('fake_user', 'fake_project')
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
                                 fanout=True)

    def test_create_volume(self):
        self._test_scheduler_api('create_volume',
                                 rpc_method='cast',
                                 topic='topic',
                                 volume_id='volume_id',
                                 snapshot_id='snapshot_id',
                                 image_id='image_id',
                                 request_spec='fake_request_spec',
                                 filter_properties='filter_properties',
                                 version='1.2')

    def test_migrate_volume_to_host(self):
        self._test_scheduler_api('migrate_volume_to_host',
                                 rpc_method='cast',
                                 topic='topic',
                                 volume_id='volume_id',
                                 host='host',
                                 force_host_copy=True,
                                 request_spec='fake_request_spec',
                                 filter_properties='filter_properties',
                                 version='1.3')

    def test_retype(self):
        self._test_scheduler_api('retype',
                                 rpc_method='cast',
                                 topic='topic',
                                 volume_id='volume_id',
                                 request_spec='fake_request_spec',
                                 filter_properties='filter_properties',
                                 version='1.4')

    def test_manage_existing(self):
        self._test_scheduler_api('manage_existing',
                                 rpc_method='cast',
                                 topic='topic',
                                 volume_id='volume_id',
                                 request_spec='fake_request_spec',
                                 filter_properties='filter_properties',
                                 version='1.5')

    def test_get_pools(self):
        self._test_scheduler_api('get_pools',
                                 rpc_method='call',
                                 filters=None,
                                 version='1.7')
