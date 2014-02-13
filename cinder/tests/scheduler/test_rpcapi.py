
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


import mock

from oslo.config import cfg

from cinder import context
from cinder.scheduler import rpcapi as scheduler_rpcapi
from cinder import test


CONF = cfg.CONF


class SchedulerRpcAPITestCase(test.TestCase):

    def setUp(self):
        super(SchedulerRpcAPITestCase, self).setUp()

    def tearDown(self):
        super(SchedulerRpcAPITestCase, self).tearDown()

    def _test_scheduler_api(self, method, rpc_method, _mock_method, **kwargs):
        ctxt = context.RequestContext('fake_user', 'fake_project')
        rpcapi = scheduler_rpcapi.SchedulerAPI()
        expected_retval = 'foo' if rpc_method == 'call' else None
        expected_version = kwargs.pop('version', rpcapi.RPC_API_VERSION)
        expected_msg = rpcapi.make_msg(method, **kwargs)
        expected_msg['version'] = expected_version

        self.fake_args = None
        self.fake_kwargs = None

        def _fake_rpc_method(*args, **kwargs):
            self.fake_args = args
            self.fake_kwargs = kwargs
            if expected_retval:
                return expected_retval

        _mock_method.side_effect = _fake_rpc_method

        retval = getattr(rpcapi, method)(ctxt, **kwargs)

        self.assertEqual(retval, expected_retval)
        expected_args = [ctxt, CONF.scheduler_topic, expected_msg]
        for arg, expected_arg in zip(self.fake_args, expected_args):
            self.assertEqual(arg, expected_arg)

    @mock.patch('cinder.openstack.common.rpc.fanout_cast')
    def test_update_service_capabilities(self, _mock_rpc_method):
        self._test_scheduler_api('update_service_capabilities',
                                 rpc_method='fanout_cast',
                                 _mock_method=_mock_rpc_method,
                                 service_name='fake_name',
                                 host='fake_host',
                                 capabilities='fake_capabilities')

    @mock.patch('cinder.openstack.common.rpc.cast')
    def test_create_volume(self, _mock_rpc_method):
        self._test_scheduler_api('create_volume',
                                 rpc_method='cast',
                                 _mock_method=_mock_rpc_method,
                                 topic='topic',
                                 volume_id='volume_id',
                                 snapshot_id='snapshot_id',
                                 image_id='image_id',
                                 request_spec='fake_request_spec',
                                 filter_properties='filter_properties',
                                 version='1.2')

    @mock.patch('cinder.openstack.common.rpc.cast')
    def test_migrate_volume_to_host(self, _mock_rpc_method):
        self._test_scheduler_api('migrate_volume_to_host',
                                 rpc_method='cast',
                                 _mock_method=_mock_rpc_method,
                                 topic='topic',
                                 volume_id='volume_id',
                                 host='host',
                                 force_host_copy=True,
                                 request_spec='fake_request_spec',
                                 filter_properties='filter_properties',
                                 version='1.3')

    @mock.patch('cinder.openstack.common.rpc.cast')
    def test_retype(self, _mock_rpc_method):
        self._test_scheduler_api('retype',
                                 rpc_method='cast',
                                 _mock_method=_mock_rpc_method,
                                 topic='topic',
                                 volume_id='volume_id',
                                 request_spec='fake_request_spec',
                                 filter_properties='filter_properties',
                                 version='1.4')

    @mock.patch('cinder.openstack.common.rpc.cast')
    def test_manage_existing(self, _mock_rpc_method):
        self._test_scheduler_api('manage_existing',
                                 rpc_method='cast',
                                 _mock_method=_mock_rpc_method,
                                 topic='topic',
                                 volume_id='volume_id',
                                 request_spec='fake_request_spec',
                                 filter_properties='filter_properties',
                                 version='1.5')
