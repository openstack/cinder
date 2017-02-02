#    Copyright 2015 Intel Corp.
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
import mock

from cinder.objects import base
from cinder import rpc
from cinder import test


class FakeAPI(rpc.RPCAPI):
    RPC_API_VERSION = '1.5'
    TOPIC = 'cinder-scheduler-topic'
    BINARY = 'cinder-scheduler'


@ddt.ddt
class RPCAPITestCase(test.TestCase):
    """Tests RPCAPI mixin aggregating stuff related to RPC compatibility."""

    def setUp(self):
        super(RPCAPITestCase, self).setUp()
        # Reset cached version pins
        rpc.LAST_RPC_VERSIONS = {}
        rpc.LAST_OBJ_VERSIONS = {}

    @mock.patch('cinder.objects.Service.get_minimum_rpc_version',
                return_value='1.2')
    @mock.patch('cinder.objects.Service.get_minimum_obj_version',
                return_value='1.4')
    @mock.patch('cinder.rpc.get_client')
    def test_init(self, get_client, get_min_obj, get_min_rpc):
        def fake_get_client(target, version_cap, serializer):
            self.assertEqual(FakeAPI.TOPIC, target.topic)
            self.assertEqual(FakeAPI.RPC_API_VERSION, target.version)
            self.assertEqual('1.2', version_cap)
            self.assertEqual('1.4', serializer.version_cap)

        get_client.side_effect = fake_get_client
        FakeAPI()

    @mock.patch('cinder.objects.Service.get_minimum_rpc_version',
                return_value=None)
    @mock.patch('cinder.objects.Service.get_minimum_obj_version',
                return_value=None)
    @mock.patch('cinder.objects.base.CinderObjectSerializer')
    @mock.patch('cinder.rpc.get_client')
    def test_init_none_caps(self, get_client, serializer, get_min_obj,
                            get_min_rpc):
        """Test that with no service latest versions are selected."""
        FakeAPI()
        serializer.assert_called_once_with(base.OBJ_VERSIONS.get_current())
        get_client.assert_called_once_with(mock.ANY,
                                           version_cap=FakeAPI.RPC_API_VERSION,
                                           serializer=serializer.return_value)
        self.assertTrue(get_min_obj.called)
        self.assertTrue(get_min_rpc.called)

    @mock.patch('cinder.objects.Service.get_minimum_rpc_version')
    @mock.patch('cinder.objects.Service.get_minimum_obj_version')
    @mock.patch('cinder.rpc.get_client')
    @mock.patch('cinder.rpc.LAST_RPC_VERSIONS', {'cinder-scheduler': '1.4'})
    @mock.patch('cinder.rpc.LAST_OBJ_VERSIONS', {'cinder-scheduler': '1.3'})
    def test_init_cached_caps(self, get_client, get_min_obj, get_min_rpc):
        def fake_get_client(target, version_cap, serializer):
            self.assertEqual(FakeAPI.TOPIC, target.topic)
            self.assertEqual(FakeAPI.RPC_API_VERSION, target.version)
            self.assertEqual('1.4', version_cap)
            self.assertEqual('1.3', serializer.version_cap)

        get_client.side_effect = fake_get_client
        FakeAPI()

        self.assertFalse(get_min_obj.called)
        self.assertFalse(get_min_rpc.called)

    @ddt.data([], ['noop'], ['noop', 'noop'])
    @mock.patch('oslo_messaging.JsonPayloadSerializer', wraps=True)
    def test_init_no_notifications(self, driver, serializer_mock):
        """Test short-circuiting notifications with default and noop driver."""
        self.override_config('driver', driver,
                             group='oslo_messaging_notifications')
        rpc.init(test.CONF)
        self.assertEqual(rpc.utils.DO_NOTHING, rpc.NOTIFIER)
        serializer_mock.assert_not_called()

    @mock.patch.object(rpc, 'messaging')
    def test_init_notifications(self, messaging_mock):
        rpc.init(test.CONF)
        self.assertTrue(messaging_mock.JsonPayloadSerializer.called)
        self.assertTrue(messaging_mock.Notifier.called)
        self.assertEqual(rpc.NOTIFIER, messaging_mock.Notifier.return_value)
