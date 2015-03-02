
# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

"""Tests for the testing base code."""

import mock
from oslo_config import cfg
import oslo_messaging as messaging

from cinder import rpc
from cinder import test


class IsolationTestCase(test.TestCase):
    """Ensure that things are cleaned up after failed tests.

    These tests don't really do much here, but if isolation fails a bunch
    of other tests should fail.

    """
    def test_service_isolation(self):
        self.start_service('volume')

    def test_rpc_consumer_isolation(self):
        class NeverCalled(object):

            def __getattribute__(*args):
                assert False, "I should never get called."

        server = rpc.get_server(messaging.Target(topic='volume',
                                                 server=cfg.CONF.host),
                                endpoints=[NeverCalled()])
        server.start()


class MockAssertTestCase(test.TestCase):
    """Ensure that valid mock assert methods are used."""
    def test_assert_has_calls(self):
        mock_call = mock.MagicMock(return_value=None)
        mock_call(1)
        mock_call(2)
        mock_call.assert_has_calls([mock.call(1), mock.call(2)])

    def test_assert_any_calls(self):
        mock_call = mock.MagicMock(return_value=None)
        mock_call(1)
        mock_call(2)
        mock_call(3)
        mock_call.assert_any_calls([mock.call(1)])

    def test_assert_called_with(self):
        mock_call = mock.MagicMock(return_value=None)
        mock_call(1, 'foo', a='123')
        mock_call.assert_called_with(1, 'foo', a='123')

    def test_assert_called_once_with(self):
        mock_call = mock.MagicMock(return_value=None)
        mock_call(1, 'foobar', a='123')
        mock_call.assert_called_once_with(1, 'foobar', a='123')

    def test_invalid_assert_calls(self):
        mock_call = mock.MagicMock()
        self.assertRaises(AttributeError, lambda: mock_call.assert_called)
        self.assertRaises(AttributeError,
                          lambda: mock_call.assert_once_called_with)
