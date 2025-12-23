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

"""Unit tests for VMstore utility functions."""

from unittest import mock

from cinder.tests.unit import test
from cinder.tests.unit.volume.drivers.vmstore import set_vmstore_overrides
from cinder.volume.drivers.vmstore import utils

UTILS_MODULE = 'cinder.volume.drivers.vmstore.utils'


class GetKeystoneHostnameTestCase(test.TestCase):
    """Test cases for get_keystone_hostname function."""

    def setUp(self):
        set_vmstore_overrides()
        super(GetKeystoneHostnameTestCase, self).setUp()
        # Reset cached hostname before each test
        utils._cached_hostname = None
        utils._keystone_opts_registered = False

    @mock.patch(UTILS_MODULE + '._ensure_keystone_opts')
    @mock.patch(UTILS_MODULE + '.session')
    @mock.patch(UTILS_MODULE + '.v3')
    @mock.patch(UTILS_MODULE + '.CONF')
    def test_get_keystone_hostname_from_catalog(
            self, mock_conf, mock_v3, mock_session, mock_ensure_opts):
        """Test getting hostname from catalog when available."""
        mock_keystone_auth = mock.Mock()
        mock_keystone_auth.auth_url = 'http://keystone:5000/v3'
        mock_keystone_auth.username = 'cinder'
        mock_keystone_auth.password = 'secret'
        mock_keystone_auth.user_domain_name = 'Default'
        mock_keystone_auth.project_name = 'service'
        mock_keystone_auth.project_domain_name = 'Default'
        mock_conf.keystone_authtoken = mock_keystone_auth

        mock_sess = mock.Mock()
        mock_session.Session.return_value = mock_sess
        endpoint = 'http://keystone.example.com:5000'
        mock_sess.get_endpoint.return_value = endpoint

        hostname = utils.get_keystone_hostname()

        self.assertEqual('keystone.example.com', hostname)
        mock_ensure_opts.assert_called_once()

    @mock.patch(UTILS_MODULE + '._ensure_keystone_opts')
    @mock.patch(UTILS_MODULE + '.session')
    @mock.patch(UTILS_MODULE + '.v3')
    @mock.patch(UTILS_MODULE + '.CONF')
    def test_get_keystone_hostname_fallback_to_config(
            self, mock_conf, mock_v3, mock_session, mock_ensure_opts):
        """Test fallback to config parsing when catalog fails."""
        mock_keystone_auth = mock.Mock()
        mock_keystone_auth.auth_url = 'http://keystone.local:5000/v3'
        mock_keystone_auth.username = 'cinder'
        mock_keystone_auth.password = 'secret'
        mock_keystone_auth.user_domain_name = 'Default'
        mock_keystone_auth.project_name = 'service'
        mock_keystone_auth.project_domain_name = 'Default'
        mock_conf.keystone_authtoken = mock_keystone_auth

        mock_sess = mock.Mock()
        mock_session.Session.return_value = mock_sess
        mock_sess.get_endpoint.side_effect = Exception('Connection failed')

        hostname = utils.get_keystone_hostname()

        self.assertEqual('keystone.local', hostname)

    @mock.patch(UTILS_MODULE + '._ensure_keystone_opts')
    @mock.patch(UTILS_MODULE + '.session')
    @mock.patch(UTILS_MODULE + '.v3')
    @mock.patch(UTILS_MODULE + '.CONF')
    def test_get_keystone_hostname_returns_none(
            self, mock_conf, mock_v3, mock_session, mock_ensure_opts):
        """Test returning None when neither method works."""
        mock_keystone_auth = mock.Mock()
        mock_keystone_auth.auth_url = None
        mock_conf.keystone_authtoken = mock_keystone_auth

        mock_sess = mock.Mock()
        mock_session.Session.return_value = mock_sess
        mock_sess.get_endpoint.side_effect = Exception('Connection failed')

        hostname = utils.get_keystone_hostname()

        self.assertIsNone(hostname)

    @mock.patch(UTILS_MODULE + '._ensure_keystone_opts')
    @mock.patch(UTILS_MODULE + '.CONF')
    def test_get_keystone_hostname_uses_cache(
            self, mock_conf, mock_ensure_opts):
        """Test that cached hostname is returned on subsequent calls."""
        utils._cached_hostname = 'cached.example.com'

        hostname = utils.get_keystone_hostname()

        self.assertEqual('cached.example.com', hostname)
        # CONF should not be accessed when cache is used
        mock_conf.keystone_authtoken.auth_url.assert_not_called()


class EnsureKeystoneOptsTestCase(test.TestCase):
    """Test cases for _ensure_keystone_opts function."""

    def setUp(self):
        set_vmstore_overrides()
        super(EnsureKeystoneOptsTestCase, self).setUp()
        utils._keystone_opts_registered = False

    @mock.patch(UTILS_MODULE + '.CONF')
    def test_ensure_keystone_opts_registers_options(self, mock_conf):
        """Test that keystone options are registered."""
        utils._ensure_keystone_opts()

        self.assertTrue(utils._keystone_opts_registered)
        # Should have called register_opt for each option
        self.assertTrue(mock_conf.register_opt.called)

    @mock.patch(UTILS_MODULE + '.CONF')
    def test_ensure_keystone_opts_skips_if_registered(self, mock_conf):
        """Test that options are not re-registered."""
        utils._keystone_opts_registered = True

        utils._ensure_keystone_opts()

        mock_conf.register_opt.assert_not_called()
