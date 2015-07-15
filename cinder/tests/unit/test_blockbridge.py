# Copyright 2015 Blockbridge Networks, LLC.
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
Blockbridge EPS iSCSI Volume Driver Tests
"""

import base64

try:
    from unittest import mock
except ImportError:
    import mock
from oslo_serialization import jsonutils
from oslo_utils import units
import six
from six.moves import http_client
from six.moves import urllib

from cinder import context
from cinder import exception
from cinder import test
from cinder.volume import configuration as conf
import cinder.volume.drivers.blockbridge as bb


DEFAULT_POOL_NAME = "OpenStack"
DEFAULT_POOL_QUERY = "+openstack"

FIXTURE_VOL_EXPORT_OK = """{
  "target_ip":"127.0.0.1",
  "target_port":3260,
  "target_iqn":"iqn.2009-12.com.blockbridge:t-pjxczxh-t001",
  "target_lun":0,
  "initiator_login":"mock-user-abcdef123456"
}
"""

POOL_STATS_WITHOUT_USAGE = {
    'driver_version': '1.3.0',
    'pools': [{
        'filter_function': None,
        'free_capacity_gb': 'unknown',
        'goodness_function': None,
        'location_info': 'BlockbridgeDriver:unknown:OpenStack',
        'max_over_subscription_ratio': None,
        'pool_name': 'OpenStack',
        'thin_provisioning_support': True,
        'reserved_percentage': 0,
        'total_capacity_gb': 'unknown'},
    ],
    'storage_protocol': 'iSCSI',
    'vendor_name': 'Blockbridge',
    'volume_backend_name': 'BlockbridgeISCSIDriver',
}


def common_mocks(f):
    """Decorator to set mocks common to all tests.

    The point of doing these mocks here is so that we don't accidentally set
    mocks that can't/don't get unset.
    """
    def _common_inner_inner1(inst, *args, **kwargs):
        @mock.patch("six.moves.http_client.HTTPSConnection", autospec=True)
        def _common_inner_inner2(mock_conn):
            inst.mock_httplib = mock_conn
            inst.mock_conn = mock_conn.return_value
            inst.mock_response = mock.Mock()

            inst.mock_response.read.return_value = '{}'
            inst.mock_response.status = 200

            inst.mock_conn.request.return_value = True
            inst.mock_conn.getresponse.return_value = inst.mock_response

            return f(inst, *args, **kwargs)

        return _common_inner_inner2()

    return _common_inner_inner1


class BlockbridgeISCSIDriverTestCase(test.TestCase):

    def setUp(self):
        super(BlockbridgeISCSIDriverTestCase, self).setUp()

        self.cfg = mock.Mock(spec=conf.Configuration)
        self.cfg.blockbridge_api_host = 'ut-api.blockbridge.com'
        self.cfg.blockbridge_api_port = None
        self.cfg.blockbridge_auth_scheme = 'token'
        self.cfg.blockbridge_auth_token = '0//kPIw7Ck7PUkPSKY...'
        self.cfg.blockbridge_pools = {DEFAULT_POOL_NAME: DEFAULT_POOL_QUERY}
        self.cfg.blockbridge_default_pool = None
        self.cfg.filter_function = None
        self.cfg.goodness_function = None

        def _cfg_safe_get(arg):
            return getattr(self.cfg, arg, None)

        self.cfg.safe_get.side_effect = _cfg_safe_get

        mock_exec = mock.Mock()
        mock_exec.return_value = ('', '')

        self.real_client = bb.BlockbridgeAPIClient(configuration=self.cfg)
        self.mock_client = mock.Mock(wraps=self.real_client)

        self.driver = bb.BlockbridgeISCSIDriver(execute=mock_exec,
                                                client=self.mock_client,
                                                configuration=self.cfg)

        self.user_id = '2c13bc8ef717015fda1e12e70dab24654cb6a6da'
        self.project_id = '62110b9d37f1ff3ea1f51e75812cb92ed9a08b28'

        self.volume_name = u'testvol-1'
        self.volume_id = '6546b9e9-1980-4241-a4e9-0ad9d382c032'
        self.volume_size = 1
        self.volume = dict(
            name=self.volume_name,
            size=self.volume_size,
            id=self.volume_id,
            user_id=self.user_id,
            project_id=self.project_id,
            host='fake-host')

        self.snapshot_name = u'testsnap-1'
        self.snapshot_id = '207c12af-85a7-4da6-8d39-a7457548f965'
        self.snapshot = dict(
            volume_name=self.volume_name,
            name=self.snapshot_name,
            id=self.snapshot_id,
            volume_id='55ff8a46-c35f-4ca3-9991-74e1697b220e',
            user_id=self.user_id,
            project_id=self.project_id)

        self.connector = dict(
            initiator='iqn.1994-05.com.redhat:6a528422b61')

        self.driver.do_setup(context.get_admin_context())

    @common_mocks
    def test_http_mock_success(self):
        self.mock_response.read.return_value = '{}'
        self.mock_response.status = 200

        conn = http_client.HTTPSConnection('whatever', None)
        conn.request('GET', '/blah', '{}', {})
        rsp = conn.getresponse()

        self.assertEqual('{}', rsp.read())
        self.assertEqual(200, rsp.status)

    @common_mocks
    def test_http_mock_failure(self):
        mock_body = '{"error": "no results matching query", "status": 413}'

        self.mock_response.read.return_value = mock_body
        self.mock_response.status = 413

        conn = http_client.HTTPSConnection('whatever', None)
        conn.request('GET', '/blah', '{}', {})
        rsp = conn.getresponse()

        self.assertEqual(mock_body, rsp.read())
        self.assertEqual(413, rsp.status)

    @common_mocks
    def test_cfg_api_host(self):
        with mock.patch.object(self.cfg, 'blockbridge_api_host', 'test.host'):
            self.driver.get_volume_stats(True)
        self.mock_httplib.assert_called_once_with('test.host', None)

    @common_mocks
    def test_cfg_api_port(self):
        with mock.patch.object(self.cfg, 'blockbridge_api_port', 1234):
            self.driver.get_volume_stats(True)
        self.mock_httplib.assert_called_once_with(
            self.cfg.blockbridge_api_host, 1234)

    @common_mocks
    def test_cfg_api_auth_scheme_password(self):
        self.cfg.blockbridge_auth_scheme = 'password'
        self.cfg.blockbridge_auth_user = 'mock-user'
        self.cfg.blockbridge_auth_password = 'mock-password'
        with mock.patch.object(self.driver, 'hostname', 'mock-hostname'):
            self.driver.get_volume_stats(True)

        creds = "%s:%s" % (self.cfg.blockbridge_auth_user,
                           self.cfg.blockbridge_auth_password)
        if six.PY3:
            creds = creds.encode('utf-8')
            b64_creds = base64.encodestring(creds).decode('ascii')
        else:
            b64_creds = base64.encodestring(creds)

        params = dict(
            hostname='mock-hostname',
            version=self.driver.VERSION,
            backend_name='BlockbridgeISCSIDriver',
            pool='OpenStack',
            query='+openstack')

        headers = {
            'Accept': 'application/vnd.blockbridge-3+json',
            'Authorization': "Basic %s" % b64_creds.replace("\n", ""),
            'User-Agent': "cinder-volume/%s" % self.driver.VERSION,
        }

        self.mock_conn.request.assert_called_once_with(
            'GET', mock.ANY, None, headers)
        # Parse the URL instead of comparing directly both URLs.
        # On Python 3, parameters are formatted in a random order because
        # of the hash randomization.
        conn_url = self.mock_conn.request.call_args[0][1]
        conn_params = dict(urllib.parse.parse_qsl(conn_url.split("?", 1)[1]))
        self.assertTrue(conn_url.startswith("/api/cinder/status?"),
                        repr(conn_url))
        self.assertEqual(params, conn_params)

    @common_mocks
    def test_create_volume(self):
        self.driver.create_volume(self.volume)

        url = "/volumes/%s" % self.volume_id
        create_params = dict(
            name=self.volume_name,
            query=DEFAULT_POOL_QUERY,
            capacity=self.volume_size * units.Gi)

        kwargs = dict(
            method='PUT',
            params=create_params,
            user_id=self.user_id,
            project_id=self.project_id)

        self.mock_client.submit.assert_called_once_with(url, **kwargs)

        full_url = "/api/cinder" + url
        raw_body = jsonutils.dumps(create_params)
        tsk_header = "ext_auth=keystone/%(project_id)s/%(user_id)s" % kwargs
        authz_header = "Bearer %s" % self.cfg.blockbridge_auth_token
        headers = {
            'X-Blockbridge-Task': tsk_header,
            'Accept': 'application/vnd.blockbridge-3+json',
            'Content-Type': 'application/json',
            'Authorization': authz_header,
            'User-Agent': "cinder-volume/%s" % self.driver.VERSION,
        }

        self.mock_conn.request.assert_called_once_with(
            'PUT', full_url, raw_body, headers)

    @common_mocks
    def test_create_volume_no_results(self):
        mock_body = '{"message": "no results matching query", "status": 413}'

        self.mock_response.read.return_value = mock_body
        self.mock_response.status = 413

        self.assertRaisesRegex(exception.VolumeBackendAPIException,
                               "no results matching query",
                               self.driver.create_volume,
                               self.volume)

        create_params = dict(
            name=self.volume_name,
            query=DEFAULT_POOL_QUERY,
            capacity=self.volume_size * units.Gi)

        kwargs = dict(
            method='PUT',
            params=create_params,
            user_id=self.user_id,
            project_id=self.project_id)

        self.mock_client.submit.assert_called_once_with(
            "/volumes/%s" % self.volume_id, **kwargs)

    @common_mocks
    def test_create_volume_from_snapshot(self):
        self.driver.create_volume_from_snapshot(self.volume, self.snapshot)

        vol_src = dict(
            snapshot_id=self.snapshot_id,
            volume_id=self.snapshot['volume_id'])
        create_params = dict(
            name=self.volume_name,
            src=vol_src)
        kwargs = dict(
            method='PUT',
            params=create_params,
            user_id=self.user_id,
            project_id=self.project_id)

        self.mock_client.submit.assert_called_once_with(
            "/volumes/%s" % self.volume_id, **kwargs)

    @common_mocks
    def test_create_volume_from_snapshot_overquota(self):
        mock_body = '{"message": "over quota", "status": 413}'

        self.mock_response.read.return_value = mock_body
        self.mock_response.status = 413

        self.assertRaisesRegex(exception.VolumeBackendAPIException,
                               "over quota",
                               self.driver.create_volume_from_snapshot,
                               self.volume,
                               self.snapshot)

        vol_src = dict(
            snapshot_id=self.snapshot_id,
            volume_id=self.snapshot['volume_id'])
        create_params = dict(
            name=self.volume_name,
            src=vol_src)
        kwargs = dict(
            method='PUT',
            params=create_params,
            user_id=self.user_id,
            project_id=self.project_id)

        self.mock_client.submit.assert_called_once_with(
            "/volumes/%s" % self.volume_id, **kwargs)

    @common_mocks
    def test_create_cloned_volume(self):
        src_vref = dict(
            name='cloned_volume_source',
            size=self.volume_size,
            id='5d734467-5d77-461c-b5ac-5009dbeaa5d5',
            user_id=self.user_id,
            project_id=self.project_id)

        self.driver.create_cloned_volume(self.volume, src_vref)

        create_params = dict(
            name=self.volume_name,
            src=dict(volume_id=src_vref['id']))
        kwargs = dict(
            method='PUT',
            params=create_params,
            user_id=self.user_id,
            project_id=self.project_id)

        self.mock_client.submit.assert_called_once_with(
            "/volumes/%s" % self.volume_id, **kwargs)

    @common_mocks
    def test_create_cloned_volume_overquota(self):
        mock_body = '{"message": "over quota", "status": 413}'

        self.mock_response.read.return_value = mock_body
        self.mock_response.status = 413

        src_vref = dict(
            name='cloned_volume_source',
            size=self.volume_size,
            id='5d734467-5d77-461c-b5ac-5009dbeaa5d5',
            user_id=self.user_id,
            project_id=self.project_id)

        self.assertRaisesRegex(exception.VolumeBackendAPIException,
                               "over quota",
                               self.driver.create_cloned_volume,
                               self.volume,
                               src_vref)

        create_params = dict(
            name=self.volume_name,
            src=dict(volume_id=src_vref['id']))
        kwargs = dict(
            method='PUT',
            params=create_params,
            user_id=self.user_id,
            project_id=self.project_id)

        self.mock_client.submit.assert_called_once_with(
            "/volumes/%s" % self.volume_id, **kwargs)

    @common_mocks
    def test_extend_volume(self):
        self.driver.extend_volume(self.volume, 2)

        url = "/volumes/%s" % self.volume_id
        kwargs = dict(
            action='grow',
            method='POST',
            params=dict(capacity=(2 * units.Gi)),
            user_id=self.user_id,
            project_id=self.project_id)

        self.mock_client.submit.assert_called_once_with(url, **kwargs)

    @common_mocks
    def test_extend_volume_overquota(self):
        mock_body = '{"message": "over quota", "status": 413}'
        self.mock_response.read.return_value = mock_body
        self.mock_response.status = 413

        self.assertRaisesRegex(exception.VolumeBackendAPIException,
                               "over quota",
                               self.driver.extend_volume,
                               self.volume,
                               2)

        url = "/volumes/%s" % self.volume_id
        kwargs = dict(
            action='grow',
            method='POST',
            params=dict(capacity=(2 * units.Gi)),
            user_id=self.user_id,
            project_id=self.project_id)

        self.mock_client.submit.assert_called_once_with(url, **kwargs)

    @common_mocks
    def test_delete_volume(self):
        self.driver.delete_volume(self.volume)

        url = "/volumes/%s" % self.volume_id
        kwargs = dict(
            method='DELETE',
            user_id=self.user_id,
            project_id=self.project_id)

        self.mock_client.submit.assert_called_once_with(url, **kwargs)

    @common_mocks
    def test_create_snapshot(self):
        self.driver.create_snapshot(self.snapshot)

        url = "/volumes/%s/snapshots/%s" % (self.snapshot['volume_id'],
                                            self.snapshot['id'])
        create_params = dict(
            name=self.snapshot_name)
        kwargs = dict(
            method='PUT',
            params=create_params,
            user_id=self.user_id,
            project_id=self.project_id)

        self.mock_client.submit.assert_called_once_with(url, **kwargs)

    @common_mocks
    def test_create_snapshot_overquota(self):
        mock_body = '{"message": "over quota", "status": 413}'
        self.mock_response.read.return_value = mock_body
        self.mock_response.status = 413

        self.assertRaisesRegex(exception.VolumeBackendAPIException,
                               "over quota",
                               self.driver.create_snapshot,
                               self.snapshot)

        url = "/volumes/%s/snapshots/%s" % (self.snapshot['volume_id'],
                                            self.snapshot['id'])
        create_params = dict(
            name=self.snapshot_name)
        kwargs = dict(
            method='PUT',
            params=create_params,
            user_id=self.user_id,
            project_id=self.project_id)

        self.mock_client.submit.assert_called_once_with(url, **kwargs)

    @common_mocks
    def test_delete_snapshot(self):
        self.driver.delete_snapshot(self.snapshot)

        url = "/volumes/%s/snapshots/%s" % (self.snapshot['volume_id'],
                                            self.snapshot['id'])
        kwargs = dict(
            method='DELETE',
            user_id=self.user_id,
            project_id=self.project_id)

        self.mock_client.submit.assert_called_once_with(url, **kwargs)

    @common_mocks
    @mock.patch('cinder.volume.utils.generate_username')
    @mock.patch('cinder.volume.utils.generate_password')
    def test_initialize_connection(self,
                                   mock_generate_password,
                                   mock_generate_username):
        mock_generate_username.return_value = 'mock-user-abcdef123456'
        mock_generate_password.return_value = 'mock-password-abcdef123456'

        self.mock_response.read.return_value = FIXTURE_VOL_EXPORT_OK
        self.mock_response.status = 200

        props = self.driver.initialize_connection(self.volume, self.connector)

        expected_props = dict(
            driver_volume_type="iscsi",
            data=dict(
                auth_method="CHAP",
                auth_username='mock-user-abcdef123456',
                auth_password='mock-password-abcdef123456',
                target_discovered=False,
                target_iqn="iqn.2009-12.com.blockbridge:t-pjxczxh-t001",
                target_lun=0,
                target_portal="127.0.0.1:3260",
                volume_id=self.volume_id))

        self.assertEqual(expected_props, props)

        ini_name = urllib.parse.quote(self.connector["initiator"], "")
        url = "/volumes/%s/exports/%s" % (self.volume_id, ini_name)
        params = dict(
            chap_user="mock-user-abcdef123456",
            chap_secret="mock-password-abcdef123456")
        kwargs = dict(
            method='PUT',
            params=params,
            user_id=self.user_id,
            project_id=self.project_id)

        self.mock_client.submit.assert_called_once_with(url, **kwargs)

    @common_mocks
    def test_terminate_connection(self):
        self.driver.terminate_connection(self.volume, self.connector)

        ini_name = urllib.parse.quote(self.connector["initiator"], "")
        url = "/volumes/%s/exports/%s" % (self.volume_id, ini_name)
        kwargs = dict(
            method='DELETE',
            user_id=self.user_id,
            project_id=self.project_id)

        self.mock_client.submit.assert_called_once_with(url, **kwargs)

    @common_mocks
    def test_get_volume_stats_without_usage(self):
        with mock.patch.object(self.driver, 'hostname', 'mock-hostname'):
            self.driver.get_volume_stats(True)

        p = {
            'query': '+openstack',
            'pool': 'OpenStack',
            'hostname': 'mock-hostname',
            'version': '1.3.0',
            'backend_name': 'BlockbridgeISCSIDriver',
        }

        self.mock_client.submit.assert_called_once_with('/status', params=p)
        self.assertEqual(POOL_STATS_WITHOUT_USAGE, self.driver._stats)

    @common_mocks
    def test_get_volume_stats_forbidden(self):
        self.mock_response.status = 403
        self.assertRaisesRegex(exception.NotAuthorized,
                               "Insufficient privileges",
                               self.driver.get_volume_stats,
                               True)

    @common_mocks
    def test_get_volume_stats_unauthorized(self):
        self.mock_response.status = 401
        self.assertRaisesRegex(exception.NotAuthorized,
                               "Invalid credentials",
                               self.driver.get_volume_stats,
                               True)
