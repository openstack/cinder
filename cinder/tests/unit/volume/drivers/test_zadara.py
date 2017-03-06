# Copyright (c) 2016 Zadara Storage, Inc.
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
"""
Tests for Zadara VPSA volume driver
"""
import copy
import mock
import requests
from six.moves.urllib import parse

from cinder import exception
from cinder import test
from cinder.volume import configuration as conf
from cinder.volume.drivers import zadara


DEFAULT_RUNTIME_VARS = {
    'status': 200,
    'user': 'test',
    'password': 'test_password',
    'access_key': '0123456789ABCDEF',
    'volumes': [],
    'servers': [],
    'controllers': [('active_ctrl', {'display-name': 'test_ctrl'})],
    'counter': 1000,

    'login': """
            <hash>
                <user>
                    <updated-at type="datetime">2012-04-30...</updated-at>
                    <access-key>%s</access-key>
                    <id type="integer">1</id>
                    <created-at type="datetime">2012-02-21...</created-at>
                    <email>jsmith@example.com</email>
                    <username>jsmith</username>
                </user>
                <status type="integer">0</status>
            </hash>""",

    'good': """
            <hash>
              <status type="integer">0</status>
            </hash>""",

    'bad_login': """
            <hash>
              <status type="integer">5</status>
              <status-msg>Some message...</status-msg>
            </hash>""",

    'bad_volume': """
            <hash>
              <status type="integer">10081</status>
              <status-msg>Virtual volume xxx not found</status-msg>
            </hash>""",

    'bad_server': """
            <hash>
              <status type="integer">10086</status>
              <status-msg>Server xxx not found</status-msg>
            </hash>""",

    'server_created': """
            <create-server-response>
                <server-name>%s</server-name>
                <status type='integer'>0</status>
            </create-server-response>""",
}

RUNTIME_VARS = None


class FakeResponse(object):
    def __init__(self, method, url, body):
        self.method = method
        self.url = url
        self.body = body
        self.status = RUNTIME_VARS['status']

    def read(self):
        ops = {'POST': [('/api/users/login.xml', self._login),
                        ('/api/volumes.xml', self._create_volume),
                        ('/api/servers.xml', self._create_server),
                        ('/api/servers/*/volumes.xml', self._attach),
                        ('/api/volumes/*/detach.xml', self._detach),
                        ('/api/volumes/*/expand.xml', self._expand),
                        ('/api/consistency_groups/*/snapshots.xml',
                         self._create_snapshot),
                        ('/api/consistency_groups/*/clone.xml',
                         self._create_clone)],
               'DELETE': [('/api/volumes/*', self._delete),
                          ('/api/snapshots/*', self._delete_snapshot)],
               'GET': [('/api/volumes.xml', self._list_volumes),
                       ('/api/pools.xml', self._list_pools),
                       ('/api/vcontrollers.xml', self._list_controllers),
                       ('/api/servers.xml', self._list_servers),
                       ('/api/consistency_groups/*/snapshots.xml',
                        self._list_vol_snapshots),
                       ('/api/volumes/*/servers.xml',
                        self._list_vol_attachments)]
               }

        ops_list = ops[self.method]
        modified_url = self.url.split('?')[0]
        for (templ_url, func) in ops_list:
            if self._compare_url(modified_url, templ_url):
                result = func()
                return result

    def _compare_url(self, url, template_url):
        items = url.split('/')
        titems = template_url.split('/')
        for (i, titem) in enumerate(titems):
            if titem != '*' and titem != items[i]:
                return False
        return True

    def _get_parameters(self, data):
        items = data.split('&')
        params = {}
        for item in items:
            if item:
                (k, v) = item.split('=')
                params[k] = v
        return params

    def _get_counter(self):
        cnt = RUNTIME_VARS['counter']
        RUNTIME_VARS['counter'] += 1
        return cnt

    def _login(self):
        params = self._get_parameters(self.body)
        if (params['user'] == RUNTIME_VARS['user'] and
                params['password'] == RUNTIME_VARS['password']):
            return RUNTIME_VARS['login'] % RUNTIME_VARS['access_key']
        else:
            return RUNTIME_VARS['bad_login']

    def _incorrect_access_key(self, params):
        return (params['access_key'] != RUNTIME_VARS['access_key'])

    def _create_volume(self):
        params = self._get_parameters(self.body)
        if self._incorrect_access_key(params):
            return RUNTIME_VARS['bad_login']

        params['display-name'] = params['name']
        params['cg-name'] = params['name']
        params['snapshots'] = []
        params['attachments'] = []
        vpsa_vol = 'volume-%07d' % self._get_counter()
        RUNTIME_VARS['volumes'].append((vpsa_vol, params))
        return RUNTIME_VARS['good']

    def _create_server(self):
        params = self._get_parameters(self.body)
        if self._incorrect_access_key(params):
            return RUNTIME_VARS['bad_login']

        params['display-name'] = params['display_name']
        vpsa_srv = 'srv-%07d' % self._get_counter()
        RUNTIME_VARS['servers'].append((vpsa_srv, params))
        return RUNTIME_VARS['server_created'] % vpsa_srv

    def _attach(self):
        params = self._get_parameters(self.body)
        if self._incorrect_access_key(params):
            return RUNTIME_VARS['bad_login']

        srv = self.url.split('/')[3]
        vol = params['volume_name[]']

        for (vol_name, params) in RUNTIME_VARS['volumes']:
            if vol_name == vol:
                attachments = params['attachments']
                if srv in attachments:
                    # already attached - ok
                    return RUNTIME_VARS['good']
                else:
                    attachments.append(srv)
                    return RUNTIME_VARS['good']

        return RUNTIME_VARS['bad_volume']

    def _detach(self):
        params = self._get_parameters(self.body)
        if self._incorrect_access_key(params):
            return RUNTIME_VARS['bad_login']

        vol = self.url.split('/')[3]
        srv = params['server_name[]']

        for (vol_name, params) in RUNTIME_VARS['volumes']:
            if vol_name == vol:
                attachments = params['attachments']
                if srv not in attachments:
                    return RUNTIME_VARS['bad_server']
                else:
                    attachments.remove(srv)
                    return RUNTIME_VARS['good']

        return RUNTIME_VARS['bad_volume']

    def _expand(self):
        params = self._get_parameters(self.body)
        if self._incorrect_access_key(params):
            return RUNTIME_VARS['bad_login']

        vol = self.url.split('/')[3]
        capacity = params['capacity']

        for (vol_name, params) in RUNTIME_VARS['volumes']:
            if vol_name == vol:
                params['capacity'] = capacity
                return RUNTIME_VARS['good']

        return RUNTIME_VARS['bad_volume']

    def _create_snapshot(self):
        params = self._get_parameters(self.body)
        if self._incorrect_access_key(params):
            return RUNTIME_VARS['bad_login']

        cg_name = self.url.split('/')[3]
        snap_name = params['display_name']

        for (vol_name, params) in RUNTIME_VARS['volumes']:
            if params['cg-name'] == cg_name:
                snapshots = params['snapshots']
                if snap_name in snapshots:
                    # already attached
                    return RUNTIME_VARS['bad_volume']
                else:
                    snapshots.append(snap_name)
                    return RUNTIME_VARS['good']

        return RUNTIME_VARS['bad_volume']

    def _delete_snapshot(self):
        snap = self.url.split('/')[3].split('.')[0]

        for (vol_name, params) in RUNTIME_VARS['volumes']:
            if snap in params['snapshots']:
                params['snapshots'].remove(snap)
                return RUNTIME_VARS['good']

        return RUNTIME_VARS['bad_volume']

    def _create_clone(self):
        params = self._get_parameters(self.body)
        if self._incorrect_access_key(params):
            return RUNTIME_VARS['bad_login']

        params['display-name'] = params['name']
        params['cg-name'] = params['name']
        params['capacity'] = 1
        params['snapshots'] = []
        params['attachments'] = []
        vpsa_vol = 'volume-%07d' % self._get_counter()
        RUNTIME_VARS['volumes'].append((vpsa_vol, params))
        return RUNTIME_VARS['good']

    def _delete(self):
        vol = self.url.split('/')[3].split('.')[0]

        for (vol_name, params) in RUNTIME_VARS['volumes']:
            if vol_name == vol:
                if params['attachments']:
                    # there are attachments - should be volume busy error
                    return RUNTIME_VARS['bad_volume']
                else:
                    RUNTIME_VARS['volumes'].remove((vol_name, params))
                    return RUNTIME_VARS['good']

        return RUNTIME_VARS['bad_volume']

    def _generate_list_resp(self, header, footer, body, lst, vol):
        resp = header
        for (obj, params) in lst:
            if vol:
                resp += body % (obj,
                                params['display-name'],
                                params['cg-name'],
                                params['capacity'])
            else:
                resp += body % (obj, params['display-name'])
        resp += footer
        return resp

    def _list_volumes(self):
        header = """<show-volumes-response>
                    <status type='integer'>0</status>
                    <volumes type='array'>"""
        footer = "</volumes></show-volumes-response>"
        body = """<volume>
                    <name>%s</name>
                    <display-name>%s</display-name>
                    <cg-name>%s</cg-name>
                    <status>Available</status>
                    <virtual-capacity type='integer'>%s</virtual-capacity>
                    <allocated-capacity type='integer'>1</allocated-capacity>
                    <raid-group-name>r5</raid-group-name>
                    <cache>write-through</cache>
                    <created-at type='datetime'>2012-01-28...</created-at>
                    <modified-at type='datetime'>2012-01-28...</modified-at>
                </volume>"""
        return self._generate_list_resp(header,
                                        footer,
                                        body,
                                        RUNTIME_VARS['volumes'],
                                        True)

    def _list_controllers(self):
        header = """<show-vcontrollers-response>
                    <status type='integer'>0</status>
                    <vcontrollers type='array'>"""
        footer = "</vcontrollers></show-vcontrollers-response>"
        body = """<vcontroller>
                    <name>%s</name>
                    <display-name>%s</display-name>
                    <state>active</state>
                    <target>iqn.2011-04.com.zadarastorage:vsa-xxx:1</target>
                    <iscsi-ip>1.1.1.1</iscsi-ip>
                    <mgmt-ip>1.1.1.1</mgmt-ip>
                    <software-ver>0.0.09-05.1--77.7</software-ver>
                    <heartbeat1>ok</heartbeat1>
                    <heartbeat2>ok</heartbeat2>
                    <vpsa-chap-user>test_chap_user</vpsa-chap-user>
                    <vpsa-chap-secret>test_chap_secret</vpsa-chap-secret>
                </vcontroller>"""
        return self._generate_list_resp(header,
                                        footer,
                                        body,
                                        RUNTIME_VARS['controllers'],
                                        False)

    def _list_pools(self):
        header = """<show-pools-response>
                     <status type="integer">0</status>
                     <pools type="array">
                 """
        footer = "</pools></show-pools-response>"
        return header + footer

    def _list_servers(self):
        header = """<show-servers-response>
                    <status type='integer'>0</status>
                    <servers type='array'>"""
        footer = "</servers></show-servers-response>"
        body = """<server>
                    <name>%s</name>
                    <display-name>%s</display-name>
                    <iqn>%s</iqn>
                    <status>Active</status>
                    <created-at type='datetime'>2012-01-28...</created-at>
                    <modified-at type='datetime'>2012-01-28...</modified-at>
                </server>"""

        resp = header
        for (obj, params) in RUNTIME_VARS['servers']:
            resp += body % (obj, params['display-name'], params['iqn'])
        resp += footer
        return resp

    def _get_server_obj(self, name):
        for (srv_name, params) in RUNTIME_VARS['servers']:
            if srv_name == name:
                return params

    def _list_vol_attachments(self):
        vol = self.url.split('/')[3]

        header = """<show-servers-response>
                    <status type="integer">0</status>
                    <servers type="array">"""
        footer = "</servers></show-servers-response>"
        body = """<server>
                    <name>%s</name>
                    <display-name>%s</display-name>
                    <iqn>%s</iqn>
                    <target>iqn.2011-04.com.zadarastorage:vsa-xxx:1</target>
                    <lun>0</lun>
                </server>"""

        for (vol_name, params) in RUNTIME_VARS['volumes']:
            if vol_name == vol:
                attachments = params['attachments']
                resp = header
                for server in attachments:
                    srv_params = self._get_server_obj(server)
                    resp += body % (server,
                                    srv_params['display-name'],
                                    srv_params['iqn'])
                resp += footer
                return resp

        return RUNTIME_VARS['bad_volume']

    def _list_vol_snapshots(self):
        cg_name = self.url.split('/')[3]

        header = """<show-snapshots-on-cg-response>
                    <status type="integer">0</status>
                    <snapshots type="array">"""
        footer = "</snapshots></show-snapshots-on-cg-response>"

        body = """<snapshot>
                    <name>%s</name>
                    <display-name>%s</display-name>
                    <status>normal</status>
                    <cg-name>%s</cg-name>
                    <pool-name>pool-00000001</pool-name>
                </snapshot>"""

        for (vol_name, params) in RUNTIME_VARS['volumes']:
            if params['cg-name'] == cg_name:
                snapshots = params['snapshots']
                resp = header
                for snap in snapshots:
                    resp += body % (snap, snap, cg_name)
                resp += footer
                return resp

        return RUNTIME_VARS['bad_volume']


class FakeRequests(object):
    """A fake requests for zadara volume driver tests."""
    def __init__(self, method, api_url, data, verify):
        url = parse.urlparse(api_url).path
        res = FakeResponse(method, url, data)
        self.content = res.read()
        self.status_code = res.status


class ZadaraVPSADriverTestCase(test.TestCase):
    """Test case for Zadara VPSA volume driver."""
    @mock.patch.object(requests, 'request', FakeRequests)
    def setUp(self):
        super(ZadaraVPSADriverTestCase, self).setUp()

        global RUNTIME_VARS
        RUNTIME_VARS = copy.deepcopy(DEFAULT_RUNTIME_VARS)
        self.configuration = mock.Mock(conf.Configuration(None))
        self.configuration.append_config_values(zadara.zadara_opts)
        self.configuration.reserved_percentage = 10
        self.configuration.zadara_use_iser = True
        self.configuration.zadara_vpsa_host = '192.168.5.5'
        self.configuration.zadara_vpsa_port = '80'
        self.configuration.zadara_user = 'test'
        self.configuration.zadara_password = 'test_password'
        self.configuration.zadara_vpsa_poolname = 'pool-0001'
        self.configuration.zadara_vol_encrypt = False
        self.configuration.zadara_vol_name_template = 'OS_%s'
        self.configuration.zadara_vpsa_use_ssl = False
        self.configuration.zadara_ssl_cert_verify = False
        self.configuration.zadara_default_snap_policy = False
        self.driver = (zadara.ZadaraVPSAISCSIDriver(
                       configuration=self.configuration))
        self.driver.do_setup(None)

    @mock.patch.object(requests, 'request', FakeRequests)
    def test_create_destroy(self):
        """Create/Delete volume."""
        volume = {'name': 'test_volume_01', 'size': 1}
        self.driver.create_volume(volume)
        self.driver.delete_volume(volume)

    @mock.patch.object(requests, 'request', FakeRequests)
    def test_create_destroy_multiple(self):
        """Create/Delete multiple volumes."""
        self.driver.create_volume({'name': 'test_volume_01', 'size': 1})
        self.driver.create_volume({'name': 'test_volume_02', 'size': 2})
        self.driver.create_volume({'name': 'test_volume_03', 'size': 3})
        self.driver.delete_volume({'name': 'test_volume_02'})
        self.driver.delete_volume({'name': 'test_volume_03'})
        self.driver.delete_volume({'name': 'test_volume_01'})
        self.driver.delete_volume({'name': 'test_volume_04'})

    @mock.patch.object(requests, 'request', FakeRequests)
    def test_destroy_non_existent(self):
        """Delete non-existent volume."""
        volume = {'name': 'test_volume_02', 'size': 1}
        self.driver.delete_volume(volume)

    @mock.patch.object(requests, 'request', FakeRequests)
    def test_empty_apis(self):
        """Test empty func (for coverage only)."""
        context = None
        volume = {'name': 'test_volume_01', 'size': 1}
        self.driver.create_export(context, volume)
        self.driver.ensure_export(context, volume)
        self.driver.remove_export(context, volume)
        self.assertRaises(NotImplementedError,
                          self.driver.local_path,
                          None)
        self.driver.check_for_setup_error()

    @mock.patch.object(requests, 'request', FakeRequests)
    def test_volume_attach_detach(self):
        """Test volume attachment and detach."""
        volume = {'name': 'test_volume_01', 'size': 1, 'id': 123}
        connector = dict(initiator='test_iqn.1')
        self.driver.create_volume(volume)
        props = self.driver.initialize_connection(volume, connector)
        self.assertEqual('iser', props['driver_volume_type'])
        data = props['data']
        self.assertEqual('1.1.1.1:3260', data['target_portal'])
        self.assertEqual('iqn.2011-04.com.zadarastorage:vsa-xxx:1',
                         data['target_iqn'])
        self.assertEqual(int('0'), data['target_lun'])
        self.assertEqual(123, data['volume_id'])
        self.assertEqual('CHAP', data['auth_method'])
        self.assertEqual('test_chap_user', data['auth_username'])
        self.assertEqual('test_chap_secret', data['auth_password'])
        self.driver.terminate_connection(volume, connector)
        self.driver.delete_volume(volume)

    @mock.patch.object(requests, 'request', FakeRequests)
    def test_volume_attach_multiple_detach(self):
        """Test multiple volume attachment and detach."""
        volume = {'name': 'test_volume_01', 'size': 1, 'id': 123}
        connector1 = dict(initiator='test_iqn.1')
        connector2 = dict(initiator='test_iqn.2')
        connector3 = dict(initiator='test_iqn.3')

        self.driver.create_volume(volume)
        self.driver.initialize_connection(volume, connector1)
        self.driver.initialize_connection(volume, connector2)
        self.driver.initialize_connection(volume, connector3)

        self.driver.terminate_connection(volume, connector1)
        self.driver.terminate_connection(volume, connector3)
        self.driver.terminate_connection(volume, connector2)
        self.driver.delete_volume(volume)

    @mock.patch.object(requests, 'request', FakeRequests)
    def test_wrong_attach_params(self):
        """Test different wrong attach scenarios."""
        volume1 = {'name': 'test_volume_01', 'size': 1, 'id': 101}
        connector1 = dict(initiator='test_iqn.1')
        self.assertRaises(exception.VolumeNotFound,
                          self.driver.initialize_connection,
                          volume1, connector1)

    @mock.patch.object(requests, 'request', FakeRequests)
    def test_wrong_detach_params(self):
        """Test different wrong detachment scenarios."""
        volume1 = {'name': 'test_volume_01', 'size': 1, 'id': 101}
        volume2 = {'name': 'test_volume_02', 'size': 1, 'id': 102}
        volume3 = {'name': 'test_volume_03', 'size': 1, 'id': 103}
        connector1 = dict(initiator='test_iqn.1')
        connector2 = dict(initiator='test_iqn.2')
        connector3 = dict(initiator='test_iqn.3')
        self.driver.create_volume(volume1)
        self.driver.create_volume(volume2)
        self.driver.initialize_connection(volume1, connector1)
        self.driver.initialize_connection(volume2, connector2)
        self.assertRaises(exception.ZadaraServerNotFound,
                          self.driver.terminate_connection,
                          volume1, connector3)
        self.assertRaises(exception.VolumeNotFound,
                          self.driver.terminate_connection,
                          volume3, connector1)
        self.assertRaises(exception.FailedCmdWithDump,
                          self.driver.terminate_connection,
                          volume1, connector2)

    @mock.patch.object(requests, 'request', FakeRequests)
    def test_wrong_login_reply(self):
        """Test wrong login reply."""

        RUNTIME_VARS['login'] = """<hash>
                    <access-key>%s</access-key>
                    <status type="integer">0</status>
                </hash>"""
        self.assertRaises(exception.MalformedResponse,
                          self.driver.do_setup, None)

        RUNTIME_VARS['login'] = """
            <hash>
                <user>
                    <updated-at type="datetime">2012-04-30...</updated-at>
                    <id type="integer">1</id>
                    <created-at type="datetime">2012-02-21...</created-at>
                    <email>jsmith@example.com</email>
                    <username>jsmith</username>
                </user>
                <access-key>%s</access-key>
                <status type="integer">0</status>
            </hash>"""
        self.assertRaises(exception.MalformedResponse,
                          self.driver.do_setup, None)

    @mock.patch.object(requests, 'request')
    def test_ssl_use(self, request):
        """Coverage test for SSL connection."""
        self.configuration.zadara_ssl_cert_verify = True
        self.configuration.zadara_vpsa_use_ssl = True
        self.configuration.driver_ssl_cert_path = '/path/to/cert'

        good_response = mock.MagicMock()
        good_response.status_code = RUNTIME_VARS['status']
        good_response.content = RUNTIME_VARS['login']

        def request_verify_cert(*args, **kwargs):
            self.assertEqual(kwargs['verify'], '/path/to/cert')
            return good_response

        request.side_effect = request_verify_cert
        self.driver.do_setup(None)

    @mock.patch.object(requests, 'request', FakeRequests)
    def test_bad_http_response(self):
        """Coverage test for non-good HTTP response."""
        RUNTIME_VARS['status'] = 400

        volume = {'name': 'test_volume_01', 'size': 1}
        self.assertRaises(exception.BadHTTPResponseStatus,
                          self.driver.create_volume, volume)

    @mock.patch.object(requests, 'request', FakeRequests)
    def test_delete_without_detach(self):
        """Test volume deletion without detach."""

        volume1 = {'name': 'test_volume_01', 'size': 1, 'id': 101}
        connector1 = dict(initiator='test_iqn.1')
        connector2 = dict(initiator='test_iqn.2')
        connector3 = dict(initiator='test_iqn.3')
        self.driver.create_volume(volume1)
        self.driver.initialize_connection(volume1, connector1)
        self.driver.initialize_connection(volume1, connector2)
        self.driver.initialize_connection(volume1, connector3)
        self.driver.delete_volume(volume1)

    @mock.patch.object(requests, 'request', FakeRequests)
    def test_no_active_ctrl(self):

        RUNTIME_VARS['controllers'] = []
        volume = {'name': 'test_volume_01', 'size': 1, 'id': 123}
        connector = dict(initiator='test_iqn.1')
        self.driver.create_volume(volume)
        self.assertRaises(exception.ZadaraVPSANoActiveController,
                          self.driver.initialize_connection,
                          volume, connector)

    @mock.patch.object(requests, 'request', FakeRequests)
    def test_create_destroy_snapshot(self):
        """Create/Delete snapshot test."""
        volume = {'name': 'test_volume_01', 'size': 1}
        snapshot = {'name': 'snap_01',
                    'volume_name': volume['name']}

        self.driver.create_volume(volume)
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.create_snapshot,
                          {'name': snapshot['name'],
                           'volume_name': 'wrong_vol'})

        self.driver.create_snapshot(snapshot)

        # Deleted should succeed for missing volume
        self.driver.delete_snapshot({'name': snapshot['name'],
                                     'volume_name': 'wrong_vol'})
        # Deleted should succeed for missing snap
        self.driver.delete_snapshot({'name': 'wrong_snap',
                                     'volume_name': volume['name']})

        self.driver.delete_snapshot(snapshot)
        self.driver.delete_volume(volume)

    @mock.patch.object(requests, 'request', FakeRequests)
    def test_expand_volume(self):
        """Expand volume test."""
        volume = {'name': 'test_volume_01', 'size': 10}
        volume2 = {'name': 'test_volume_02', 'size': 10}

        self.driver.create_volume(volume)

        self.assertRaises(exception.ZadaraVolumeNotFound,
                          self.driver.extend_volume,
                          volume2, 15)
        self.assertRaises(exception.InvalidInput,
                          self.driver.extend_volume,
                          volume, 5)

        self.driver.extend_volume(volume, 15)
        self.driver.delete_volume(volume)

    @mock.patch.object(requests, 'request', FakeRequests)
    def test_create_destroy_clones(self):
        """Create/Delete clones test."""
        volume1 = {'name': 'test_volume_01', 'id': '01', 'size': 1}
        volume2 = {'name': 'test_volume_02', 'id': '02', 'size': 2}
        volume3 = {'name': 'test_volume_03', 'id': '03', 'size': 1}
        snapshot = {'name': 'snap_01',
                    'id': '01',
                    'volume_name': volume1['name'],
                    'volume_size': 1}

        self.driver.create_volume(volume1)
        self.driver.create_snapshot(snapshot)

        # Test invalid vol reference
        self.assertRaises(exception.VolumeNotFound,
                          self.driver.create_volume_from_snapshot,
                          volume2,
                          {'name': snapshot['name'],
                           'id': snapshot['id'],
                           'volume_name': 'wrong_vol'})
        # Test invalid snap reference
        self.assertRaises(exception.SnapshotNotFound,
                          self.driver.create_volume_from_snapshot,
                          volume2,
                          {'name': 'wrong_snap',
                           'id': 'wrong_id',
                           'volume_name': snapshot['volume_name']})
        # Test invalid src_vref for volume clone
        self.assertRaises(exception.VolumeNotFound,
                          self.driver.create_cloned_volume,
                          volume3, volume2)
        self.driver.create_volume_from_snapshot(volume2, snapshot)
        self.driver.create_cloned_volume(volume3, volume1)
        self.driver.delete_volume(volume3)
        self.driver.delete_volume(volume2)
        self.driver.delete_snapshot(snapshot)
        self.driver.delete_volume(volume1)

    @mock.patch.object(requests, 'request', FakeRequests)
    def test_get_volume_stats(self):
        """Get stats test."""
        self.configuration.safe_get.return_value = 'ZadaraVPSAISCSIDriver'
        data = self.driver.get_volume_stats(True)
        self.assertEqual('Zadara Storage', data['vendor_name'])
        self.assertEqual('unknown', data['total_capacity_gb'])
        self.assertEqual('unknown', data['free_capacity_gb'])
        self.assertEqual({'total_capacity_gb': 'unknown',
                          'free_capacity_gb': 'unknown',
                          'reserved_percentage':
                          self.configuration.reserved_percentage,
                          'QoS_support': False,
                          'vendor_name': 'Zadara Storage',
                          'driver_version': self.driver.VERSION,
                          'storage_protocol': 'iSER',
                          'volume_backend_name': 'ZadaraVPSAISCSIDriver'},
                         data)
