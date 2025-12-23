# Copyright 2026 DDN, Inc. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""Unit tests for VMstore API client."""

from unittest import mock

from cinder.tests.unit import test
from cinder.tests.unit.volume.drivers.vmstore import set_vmstore_overrides
from cinder.volume.drivers.vmstore import api


class VmstoreExceptionTestCase(test.TestCase):
    """Test cases for VmstoreException class."""

    def setUp(self):
        set_vmstore_overrides()
        super(VmstoreExceptionTestCase, self).setUp()

    def test_exception_with_dict_data(self):
        """Test exception initialization with dict data."""
        data = {
            'typeId': 'TestError',
            'code': 'TEST_ERROR',
            'source': 'TestSource',
            'message': 'Test message',
            'causeDetails': 'Test cause details'
        }
        exc = api.VmstoreException(data)
        self.assertEqual('TEST_ERROR', exc.code)
        self.assertIn('Test cause details', str(exc))
        self.assertIn('TestSource', str(exc))
        self.assertIn('TestError', str(exc))

    def test_exception_with_string_data(self):
        """Test exception initialization with string data."""
        exc = api.VmstoreException('Simple error message')
        self.assertEqual('ERR_API', exc.code)
        self.assertIn('Simple error message', str(exc))

    def test_exception_with_kwargs(self):
        """Test exception initialization with keyword arguments."""
        exc = api.VmstoreException(
            code='CUSTOM_CODE',
            causeDetails='Custom details',
            source='CustomSource'
        )
        self.assertEqual('CUSTOM_CODE', exc.code)
        self.assertIn('Custom details', str(exc))
        self.assertIn('CustomSource', str(exc))

    def test_exception_defaults(self):
        """Test exception with default values."""
        exc = api.VmstoreException()
        self.assertEqual('ERR_API', exc.code)
        self.assertIn('No details', str(exc))
        self.assertIn('CinderDriver', str(exc))


class VmstoreRequestTestCase(test.TestCase):
    """Test cases for VmstoreRequest class."""

    def setUp(self):
        set_vmstore_overrides()
        super(VmstoreRequestTestCase, self).setUp()
        self.mock_proxy = mock.Mock()
        self.mock_proxy.retries = 3
        self.mock_proxy.refresh_retries = 2

    def test_request_initialization(self):
        """Test request initialization."""
        request = api.VmstoreRequest(self.mock_proxy, 'GET')
        self.assertEqual(self.mock_proxy, request.proxy)
        self.assertEqual('GET', request.method)
        self.assertEqual(4, request.attempts)
        self.assertEqual(3, request.refresh_attempts)
        self.assertIsNone(request.payload)
        self.assertIsNone(request.error)


class VmstoreCollectionsTestCase(test.TestCase):
    """Test cases for VmstoreCollections class."""

    def setUp(self):
        set_vmstore_overrides()
        super(VmstoreCollectionsTestCase, self).setUp()
        self.mock_proxy = mock.Mock()
        self.collections = api.VmstoreCollections(self.mock_proxy)

    def test_path_generation(self):
        """Test path generation with special characters."""
        name = 'volume with spaces'
        path = self.collections.path(name)
        self.assertIn('volume+with+spaces', path)

    def test_key_generation(self):
        """Test key generation for coordination."""
        self.collections.namespace = 'test_ns'
        self.collections.prefix = 'test_prefix'
        key = self.collections.key('test_name')
        self.assertEqual('test_ns:test_prefix_test_name', key)

    def test_delete_not_found_returns_success(self):
        """Test that delete returns success when resource not found."""
        error = api.VmstoreException(code='RESOURCE_NOT_FOUND')
        self.mock_proxy.delete.side_effect = error
        # Should not raise
        result = self.collections.delete('test_resource')
        self.assertIsNone(result)

    def test_delete_other_error_raises(self):
        """Test that delete raises on other errors."""
        error = api.VmstoreException(code='OTHER_ERROR')
        self.mock_proxy.delete.side_effect = error
        self.assertRaises(
            api.VmstoreException,
            self.collections.delete,
            'test_resource'
        )


class VmstoreProxyTestCase(test.TestCase):
    """Test cases for VmstoreProxy class."""

    def setUp(self):
        set_vmstore_overrides()
        super(VmstoreProxyTestCase, self).setUp()
        # VmstoreProxy takes (proto, backend, conf) where conf is a
        # configuration object with vmstore_* attributes
        self.mock_conf = mock.Mock()
        self.mock_conf.vmstore_rest_protocol = 'https'
        self.mock_conf.vmstore_rest_address = '192.168.1.1'
        self.mock_conf.vmstore_rest_port = 443
        self.mock_conf.vmstore_user = 'admin'
        self.mock_conf.vmstore_password = 'secret'
        self.mock_conf.vmstore_rest_retry_count = 3
        self.mock_conf.vmstore_refresh_retry_count = 2
        self.mock_conf.vmstore_rest_backoff_factor = 1
        self.mock_conf.vmstore_rest_connect_timeout = 30
        self.mock_conf.vmstore_rest_read_timeout = 300
        self.mock_conf.driver_ssl_cert_verify = False
        self.mock_conf.driver_ssl_cert_path = None

    @mock.patch('requests.Session')
    def test_proxy_initialization(self, mock_session):
        """Test proxy initialization."""
        proxy = api.VmstoreProxy('nfs', 'backend1', self.mock_conf)
        self.assertEqual('192.168.1.1', proxy.host)
        self.assertEqual(443, proxy.port)
        self.assertEqual('https', proxy.scheme)
        self.assertEqual(3, proxy.retries)

    @mock.patch('requests.Session')
    def test_url_generation(self, mock_session):
        """Test URL generation."""
        proxy = api.VmstoreProxy('nfs', 'backend1', self.mock_conf)
        url = proxy.url('/test/path')
        self.assertEqual('https://192.168.1.1:443/api/v310/test/path', url)
