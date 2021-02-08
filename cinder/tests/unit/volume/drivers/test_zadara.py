# Copyright (c) 2019 Zadara Storage, Inc.
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
from unittest import mock

import requests
from six.moves.urllib import parse

from cinder import exception
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume
from cinder.tests.unit import test
from cinder.volume import configuration as conf
from cinder.volume.drivers.zadara import common
from cinder.volume.drivers.zadara import exception as zadara_exception
from cinder.volume.drivers.zadara import zadara


def check_access_key(func):
    """A decorator for all operations that needed an API before executing"""
    def wrap(self, *args, **kwargs):
        if not self._is_correct_access_key():
            return RUNTIME_VARS['bad_login']
        return func(self, *args, **kwargs)

    return wrap


DEFAULT_RUNTIME_VARS = {
    'status': 200,
    'user': 'test',
    'password': 'test_password',
    'access_key': '0123456789ABCDEF',
    'volumes': [],
    'servers': [],
    'controllers': [('active_ctrl', {'display-name': 'test_ctrl'})],
    'counter': 1000,

    "login": """
        {
         "response": {
                      "user": {
                               "updated-at": "2021-01-22",
                               "access-key": "%s",
                               "id": 1,
                               "created-at": "2021-01-22",
                               "email": "jsmith@example.com",
                               "username": "jsmith"
                              },
                      "status": 0
                     }
        }""",
    "good": """
         {
          "response": {
                       "status": 0
                      }
         }""",
    "bad_login": """
        {
         "response": {
                      "status": 5,
                      "status-msg": "Some message..."
                     }
        }""",
    "bad_volume": """
        {
         "response": {
                      "status": 10081,
                      "status-msg": "Virtual volume xxx should be found"
                     }
        }""",
    "fake_volume": """
        {
         "response": {
                      "volumes": [],
                      "status": 0,
                      "status-msg": "Virtual volume xxx doesn't exist"
                     }
        }""",
    "bad_server": """
        {
         "response": {
                      "status": 10086,
                      "status-msg": "Server xxx not found"
                     }
        }""",
    "server_created": """
        {
         "response": {
                      "server_name": "%s",
                      "status": 0
                     }
        }""",
}

RUNTIME_VARS = None


class FakeResponse(object):
    def __init__(self, method, url, params, body, headers, **kwargs):
        # kwargs include: verify, timeout
        self.method = method
        self.url = url
        self.body = body
        self.params = params
        self.headers = headers
        self.status = RUNTIME_VARS['status']

    @property
    def access_key(self):
        """Returns Response Access Key"""
        return self.headers["X-Access-Key"]

    def read(self):
        ops = {'POST': [('/api/users/login.json', self._login),
                        ('/api/volumes.json', self._create_volume),
                        ('/api/servers.json', self._create_server),
                        ('/api/servers/*/volumes.json', self._attach),
                        ('/api/volumes/*/detach.json', self._detach),
                        ('/api/volumes/*/expand.json', self._expand),
                        ('/api/volumes/*/rename.json', self._rename),
                        ('/api/consistency_groups/*/snapshots.json',
                         self._create_snapshot),
                        ('/api/snapshots/*/rename.json',
                         self._rename_snapshot),
                        ('/api/consistency_groups/*/clone.json',
                         self._create_clone)],
               'DELETE': [('/api/volumes/*', self._delete),
                          ('/api/snapshots/*', self._delete_snapshot)],
               'GET': [('/api/volumes.json?showonlyblock=YES',
                        self._list_volumes),
                       ('/api/volumes.json?display_name=*',
                           self._get_volume_by_name),
                       ('/api/pools/*.json', self._get_pool),
                       ('/api/vcontrollers.json', self._list_controllers),
                       ('/api/servers.json', self._list_servers),
                       ('/api/consistency_groups/*/snapshots.json',
                        self._list_vol_snapshots),
                       ('/api/snapshots.json', self._list_snapshots),
                       ('/api/volumes/*/servers.json',
                        self._list_vol_attachments)]
               }

        ops_list = ops[self.method]
        for (templ_url, func) in ops_list:
            if self._compare_url(self.url, templ_url):
                result = func()
                return result

    @staticmethod
    def _compare_url(url, template_url):
        items = url.split('/')
        titems = template_url.split('/')
        for (i, titem) in enumerate(titems):
            if '*' not in titem and titem != items[i]:
                return False
            if '?' in titem and titem.split('=')[0] != items[i].split('=')[0]:
                return False

        return True

    @staticmethod
    def _get_counter():
        cnt = RUNTIME_VARS['counter']
        RUNTIME_VARS['counter'] += 1
        return cnt

    def _login(self):
        params = self.body
        if (params['user'] == RUNTIME_VARS['user'] and
                params['password'] == RUNTIME_VARS['password']):
            return RUNTIME_VARS['login'] % RUNTIME_VARS['access_key']
        else:
            return RUNTIME_VARS['bad_login']

    def _is_correct_access_key(self):
        return self.access_key == RUNTIME_VARS['access_key']

    @check_access_key
    def _create_volume(self):
        params = self.body
        params['display-name'] = params['name']
        params['cg_name'] = params['name']
        params['snapshots'] = []
        params['server_ext_names'] = ''
        params['pool'] = 'pool-0001'
        params['provider_location'] = params['name']
        vpsa_vol = 'volume-%07d' % self._get_counter()
        RUNTIME_VARS['volumes'].append((vpsa_vol, params))
        return RUNTIME_VARS['good']

    @check_access_key
    def _create_server(self):
        params = self.body

        params['display-name'] = params['display_name']
        vpsa_srv = 'srv-%07d' % self._get_counter()
        RUNTIME_VARS['servers'].append((vpsa_srv, params))
        return RUNTIME_VARS['server_created'] % vpsa_srv

    @check_access_key
    def _attach(self):
        srv = self.url.split('/')[3]

        params = self.body

        vol = params['volume_name[]']

        for (vol_name, params) in RUNTIME_VARS['volumes']:
            if params['name'] == vol:
                attachments = params['server_ext_names'].split(',')
                if srv in attachments:
                    # already attached - ok
                    return RUNTIME_VARS['good']
                else:
                    if not attachments[0]:
                        params['server_ext_names'] = srv
                    else:
                        params['server_ext_names'] += ',' + srv
                    return RUNTIME_VARS['good']

        return RUNTIME_VARS['bad_volume']

    @check_access_key
    def _detach(self):
        params = self.body
        vol = self.url.split('/')[3]
        srv = params['server_name[]']

        for (vol_name, params) in RUNTIME_VARS['volumes']:
            if params['name'] == vol:
                attachments = params['server_ext_names'].split(',')
                if srv not in attachments:
                    return RUNTIME_VARS['bad_server']
                else:
                    attachments.remove(srv)
                    params['server_ext_names'] = (','.join([str(elem)
                                                  for elem in attachments]))
                    return RUNTIME_VARS['good']

        return RUNTIME_VARS['bad_volume']

    @check_access_key
    def _expand(self):
        params = self.body
        vol = self.url.split('/')[3]
        capacity = params['capacity']

        for (vol_name, params) in RUNTIME_VARS['volumes']:
            if params['name'] == vol:
                params['capacity'] = capacity
                return RUNTIME_VARS['good']

        return RUNTIME_VARS['bad_volume']

    @check_access_key
    def _rename(self):
        params = self.body
        vol = self.url.split('/')[3]

        for (vol_name, vol_params) in RUNTIME_VARS['volumes']:
            if vol_params['name'] == vol:
                vol_params['name'] = params['new_name']
                vol_params['display-name'] = params['new_name']
                vol_params['cg_name'] = params['new_name']
                return RUNTIME_VARS['good']

        return RUNTIME_VARS['bad_volume']

    @check_access_key
    def _rename_snapshot(self):
        params = self.body
        vpsa_snapshot = self.url.split('/')[3]

        for (vol_name, vol_params) in RUNTIME_VARS['volumes']:
            for snapshot in vol_params['snapshots']:
                if vpsa_snapshot == snapshot:
                    vol_params['snapshots'].remove(snapshot)
                    vol_params['snapshots'].append(params['newname'])
                    return RUNTIME_VARS['good']

        return RUNTIME_VARS['bad_volume']

    @check_access_key
    def _create_snapshot(self):
        params = self.body
        cg_name = self.url.split('/')[3]
        snap_name = params['display_name']

        for (vol_name, vol_params) in RUNTIME_VARS['volumes']:
            if vol_params['cg_name'] == cg_name:
                snapshots = vol_params['snapshots']
                if snap_name in snapshots:
                    # already attached
                    return RUNTIME_VARS['bad_volume']
                else:
                    snapshots.append(snap_name)
                    vol_params['has_snapshots'] = 'YES'
                    return RUNTIME_VARS['good']

        return RUNTIME_VARS['bad_volume']

    @check_access_key
    def _delete_snapshot(self):
        snap = self.url.split('/')[3].split('.')[0]

        for (vol_name, params) in RUNTIME_VARS['volumes']:
            if snap in params['snapshots']:
                params['snapshots'].remove(snap)
                return RUNTIME_VARS['good']

        return RUNTIME_VARS['bad_volume']

    @check_access_key
    def _create_clone(self):
        params = self.body
        params['display-name'] = params['name']
        params['cg_name'] = params['name']
        params['capacity'] = 1
        params['snapshots'] = []
        params['server_ext_names'] = ''
        params['pool'] = 'pool-0001'
        vpsa_vol = 'volume-%07d' % self._get_counter()
        RUNTIME_VARS['volumes'].append((vpsa_vol, params))
        return RUNTIME_VARS['good']

    def _delete(self):
        vol = self.url.split('/')[3].split('.')[0]

        for (vol_name, params) in RUNTIME_VARS['volumes']:
            if params['name'] == vol:
                if params['server_ext_names']:
                    # there are attachments - should be volume busy error
                    return RUNTIME_VARS['bad_volume']
                else:
                    RUNTIME_VARS['volumes'].remove((vol_name, params))
                    return RUNTIME_VARS['good']

        return RUNTIME_VARS['bad_volume']

    def _generate_list_resp(self, null_body, body, lst, vol):
        resp = ''
        for (obj, params) in lst:
            if vol:
                resp += body % (obj,
                                params['display-name'],
                                params['cg_name'],
                                params['capacity'],
                                params['pool'])
            else:
                resp += body % (obj, params['display-name'])
        if resp:
            return resp
        else:
            return null_body

    def _list_volumes(self):
        null_body = """
        {
         "response": {
                      "volumes": [
                                 ],
                      "status": 0
                     }
        }"""
        body = """
        {
         "response": {
                      "volumes": %s,
                      "status": 0
                     }
        }"""

        volume_obj = """
                     {
                      "name": "%s",
                      "display_name": "%s",
                      "cg_name": "%s",
                      "status": "%s",
                      "virtual_capacity": %d,
                      "pool_name": "%s",
                      "allocated-capacity": 1,
                      "raid-group-name": "r5",
                      "cache": "write-through",
                      "created-at": "2021-01-22",
                      "modified-at": "2021-01-22",
                      "has_snapshots": "%s"
                     }
                     """
        if len(RUNTIME_VARS['volumes']) == 0:
            return null_body
        resp = ''
        volume_list = ''
        count = 0
        for (vol_name, params) in RUNTIME_VARS['volumes']:
            vol_status = (params.get('status') if params.get('status')
                          else 'Available')
            has_snapshots = 'YES' if params.get('has_snapshots') else 'NO'
            volume_dict = volume_obj % (params['name'],
                                        params['display-name'],
                                        params['cg_name'],
                                        vol_status,
                                        params['capacity'],
                                        params['pool'],
                                        has_snapshots)
            if count == 0:
                volume_list += volume_dict
                count += 1
            elif count != len(RUNTIME_VARS['volumes']):
                volume_list = volume_list + ',' + volume_dict
                count += 1
        if volume_list:
            volume_list = '[' + volume_list + ']'
            resp = body % volume_list
            return resp

        return RUNTIME_VARS['bad_volume']

    def _get_volume_by_name(self):
        volume_name = self.url.split('=')[1]
        body = """
        {
         "response": {
                      "volumes": [
                                  {
                                   "name": "%s",
                                   "display_name": "%s",
                                   "cg_name": "%s",
                                   "provider_location": "%s",
                                   "status": "%s",
                                   "virtual_capacity": %d,
                                   "pool_name": "%s",
                                   "allocated-capacity": 1,
                                   "raid-group-name": "r5",
                                   "cache": "write-through",
                                   "created-at": "2021-01-22",
                                   "modified-at": "2021-01-22",
                                   "has_snapshots": "%s",
                                   "server_ext_names": "%s"
                                  }
                                 ],
                      "status": 0
                     }
        }"""
        for (vol_name, params) in RUNTIME_VARS['volumes']:
            if params['name'] == volume_name:
                vol_status = (params.get('status') if params.get('status')
                              else 'Available')
                has_snapshots = 'YES' if params.get('has_snapshots') else 'NO'
                resp = body % (volume_name, params['display-name'],
                               params['cg_name'],
                               params['cg_name'],
                               vol_status,
                               params['capacity'],
                               params['pool'],
                               has_snapshots,
                               params['server_ext_names'])
                return resp

        return RUNTIME_VARS['fake_volume']

    def _list_controllers(self):
        null_body = """
        {
         "response": {
                      "vcontrollers": [
                                      ],
                      "status": 0
                     }
        }"""
        body = """
        {
         "response": {
                      "vcontrollers": [
                                       {
                                        "name": "%s",
                                        "display-name": "%s",
                                        "state": "active",
                                        "target":
                                        "iqn.2011-04.zadarastorage:vsa-xxx:1",
                                        "iscsi_ip": "1.1.1.1",
                                        "iscsi_ipv6": "",
                                        "mgmt-ip": "1.1.1.1",
                                        "software-ver": "0.0.09-05.1--77.7",
                                        "heartbeat1": "ok",
                                        "heartbeat2": "ok",
                                        "vpsa_chap_user": "test_chap_user",
                                        "vpsa_chap_secret": "test_chap_secret"
                                       }
                                      ],
                      "status": 0
                     }
        }"""
        return self._generate_list_resp(null_body,
                                        body,
                                        RUNTIME_VARS['controllers'],
                                        False)

    def _get_pool(self):
        response = """
        {
         "response": {
                      "pool": {
                               "name": "pool-0001",
                               "capacity": 100,
                               "available_capacity": 99,
                               "provisioned_capacity": 1
                              },
                      "status": 0
                     }
        }"""
        return response

    def _list_servers(self):
        null_body = """
        {
         "response": {
                      "servers": [
                                 ],
                      "status": 0
                     }
        }"""
        body = """
        {
         "response": {
                      "servers": %s,
                      "status": 0
                     }
        }"""

        server_obj = """
                     {
                      "name": "%s",
                      "display_name": "%s",
                      "iqn": "%s",
                      "target":
                      "iqn.2011-04.zadarastorage:vsa-xxx:1",
                      "lun": 0
                     }
                     """

        resp = ''
        server_list = ''
        count = 0
        for (obj, params) in RUNTIME_VARS['servers']:
            server_dict = server_obj % (obj,
                                        params['display_name'],
                                        params['iqn'])
            if count == 0:
                server_list += server_dict
                count += 1
            elif count != len(RUNTIME_VARS['servers']):
                server_list = server_list + ',' + server_dict
                count += 1
        server_list = '[' + server_list + ']'
        resp = body % server_list
        if resp:
            return resp
        else:
            return null_body

    def _list_snapshots(self):
        null_body = """
        {
         "response": {
                      "snapshots": [
                                 ],
                      "status": 0
                     }
        }"""
        body = """
        {
         "response": {
                      "snapshots": %s,
                      "status": 0
                     }
        }"""

        snapshot_obj = """
                       {
                        "name": "%s",
                        "display_name": "%s",
                        "volume_display_name": "%s",
                        "volume_capacity_mb": %d,
                        "volume_ext_name": "%s",
                        "cg_name": "%s",
                        "pool_name": "pool-0001"
                     }
                     """

        resp = ''
        snapshot_list = ''
        count = 0
        for (obj, params) in RUNTIME_VARS['volumes']:
            snapshots = params['snapshots']
            if len(snapshots) == 0:
                continue
            for snapshot in snapshots:
                snapshot_dict = snapshot_obj % (snapshot, snapshot,
                                                params['provider_location'],
                                                params['capacity'] * 1024,
                                                params['display-name'],
                                                params['cg_name'])
                if count == 0:
                    snapshot_list += snapshot_dict
                    count += 1
                else:
                    snapshot_list = snapshot_list + ',' + snapshot_dict
                    count += 1
        snapshot_list = '[' + snapshot_list + ']'
        resp = body % snapshot_list
        if resp:
            return resp
        else:
            return null_body

    def _get_server_obj(self, name):
        for (srv_name, params) in RUNTIME_VARS['servers']:
            if srv_name == name:
                return params

    def _list_vol_attachments(self):
        vol = self.url.split('/')[3]

        null_body = """
        {
         "response": {
                      "servers": [
                                 ],
                      "status": 0
                     }
        }"""
        body = """
        {
         "response": {
                      "servers": %s,
                      "status": 0
                     }
        }"""

        server_obj = """
                     {
                      "name": "%s",
                      "display_name": "%s",
                      "iqn": "%s",
                      "target":
                      "iqn.2011-04.zadarastorage:vsa-xxx:1",
                      "lun": 0
                     }
                     """
        for (vol_name, params) in RUNTIME_VARS['volumes']:
            if params['name'] == vol:
                attachments = params['server_ext_names'].split(',')
                if not attachments[0]:
                    return null_body
                resp = ''
                server_list = ''
                count = 0
                for server in attachments:
                    srv_params = self._get_server_obj(server)
                    server_dict = (server_obj % (server,
                                   srv_params['display_name'],
                                   srv_params['iqn']))
                    if count == 0:
                        server_list += server_dict
                        count += 1
                    elif count != len(attachments):
                        server_list = server_list + ',' + server_dict
                        count += 1
                server_list = '[' + server_list + ']'
                resp = body % server_list
                return resp

        return RUNTIME_VARS['bad_volume']

    def _list_vol_snapshots(self):
        cg_name = self.url.split('/')[3]

        null_body = """
        {
         "response": {
                      "snapshots": [
                                   ],
                      "status": 0
                     }
        }"""

        body = """
        {
         "response": {
                      "snapshots": %s,
                      "status": 0
                     }
        }"""

        snapshot_obj = """
                       {
                        "name": "%s",
                        "display_name": "%s",
                        "cg_name": "%s",
                        "pool_name": "pool-0001"
                       }
                       """
        for (vol_name, params) in RUNTIME_VARS['volumes']:
            if params['cg_name'] == cg_name:
                snapshots = params['snapshots']
                if len(snapshots) == 0:
                    return null_body
                resp = ''
                snapshot_list = ''
                count = 0

                for snapshot in snapshots:
                    snapshot_dict = snapshot_obj % (snapshot, snapshot,
                                                    cg_name)
                    if count == 0:
                        snapshot_list += snapshot_dict
                        count += 1
                    elif count != len(snapshots):
                        snapshot_list = snapshot_list + ',' + snapshot_dict
                        count += 1
                snapshot_list = '[' + snapshot_list + ']'
                resp = body % snapshot_list
                return resp

        return RUNTIME_VARS['bad_volume']


class FakeRequests(object):
    """A fake requests for zadara volume driver tests."""
    def __init__(self, method, api_url, params=None, data=None,
                 headers=None, **kwargs):
        apiurl_items = parse.urlparse(api_url)
        if apiurl_items.query:
            url = apiurl_items.path + '?' + apiurl_items.query
        else:
            url = apiurl_items.path
        res = FakeResponse(method, url, params, data, headers, **kwargs)
        self.content = res.read()
        self.status_code = res.status


class ZadaraVPSADriverTestCase(test.TestCase):

    def __init__(self, *args, **kwargs):
        super(ZadaraVPSADriverTestCase, self).__init__(*args, **kwargs)

        self.configuration = None
        self.driver = None

    """Test case for Zadara VPSA volume driver."""
    @mock.patch.object(requests.Session, 'request', FakeRequests)
    def setUp(self):
        super(ZadaraVPSADriverTestCase, self).setUp()

        global RUNTIME_VARS
        RUNTIME_VARS = copy.deepcopy(DEFAULT_RUNTIME_VARS)
        self.configuration = mock.Mock(conf.Configuration(None))
        self.configuration.append_config_values(common.zadara_opts)
        self.configuration.reserved_percentage = 10
        self.configuration.zadara_use_iser = True
        self.configuration.zadara_vpsa_host = '192.168.5.5'
        self.configuration.zadara_vpsa_port = '80'
        self.configuration.zadara_user = 'test'
        self.configuration.zadara_password = 'test_password'
        self.configuration.zadara_access_key = '0123456789ABCDEF'
        self.configuration.zadara_vpsa_poolname = 'pool-0001'
        self.configuration.zadara_vol_encrypt = False
        self.configuration.zadara_vol_name_template = 'OS_%s'
        self.configuration.zadara_vpsa_use_ssl = False
        self.configuration.zadara_ssl_cert_verify = False
        self.configuration.driver_ssl_cert_path = '/path/to/cert'
        self.configuration.zadara_default_snap_policy = False
        self.configuration.zadara_gen3_vol_compress = False
        self.configuration.zadara_gen3_vol_dedupe = False
        self.driver = (zadara.ZadaraVPSAISCSIDriver(
                       configuration=self.configuration))
        self.driver.do_setup(None)

    @mock.patch.object(requests.Session, 'request', FakeRequests)
    def test_create_destroy(self):
        """Create/Delete volume."""
        vol_args = {'display_name': 'test_volume_01', 'size': 1, 'id': 1}
        volume = fake_volume.fake_volume_obj(None, **vol_args)
        self.driver.create_volume(volume)
        self.driver.delete_volume(volume)

    @mock.patch.object(requests.Session, 'request', FakeRequests)
    def test_create_destroy_multiple(self):
        """Create/Delete multiple volumes."""
        vol1_args = {'display_name': 'test_volume_01', 'size': 1, 'id': 1}
        vol2_args = {'display_name': 'test_volume_02', 'size': 2, 'id': 2}
        vol3_args = {'display_name': 'test_volume_03', 'size': 3, 'id': 3}
        vol4_args = {'display_name': 'test_volume_04', 'size': 4, 'id': 4}
        volume1 = fake_volume.fake_volume_obj(None, **vol1_args)
        volume2 = fake_volume.fake_volume_obj(None, **vol2_args)
        volume3 = fake_volume.fake_volume_obj(None, **vol3_args)
        volume4 = fake_volume.fake_volume_obj(None, **vol4_args)

        self.driver.create_volume(volume1)
        self.driver.create_volume(volume2)
        self.driver.create_volume(volume3)
        self.driver.delete_volume(volume1)
        self.driver.delete_volume(volume2)
        self.driver.delete_volume(volume3)
        self.driver.delete_volume(volume4)

    @mock.patch.object(requests.Session, 'request', FakeRequests)
    def test_destroy_non_existent(self):
        """Delete non-existent volume."""
        vol_args = {'display_name': 'test_volume_01', 'size': 1, 'id': 1}
        volume = fake_volume.fake_volume_obj(None, **vol_args)
        self.driver.delete_volume(volume)

    @mock.patch.object(requests.Session, 'request', FakeRequests)
    def test_empty_apis(self):
        """Test empty func (for coverage only)."""
        context = None
        vol_args = {'display_name': 'test_volume_01', 'size': 1, 'id': 1}
        volume = fake_volume.fake_volume_obj(None, **vol_args)
        self.driver.create_export(context, volume)
        self.driver.ensure_export(context, volume)
        self.driver.remove_export(context, volume)
        self.assertRaises(NotImplementedError,
                          self.driver.local_path,
                          None)
        self.driver.check_for_setup_error()

    @mock.patch.object(requests.Session, 'request', FakeRequests)
    def test_volume_attach_detach(self):
        """Test volume attachment and detach."""
        vol_args = {'display_name': 'test_volume_01', 'size': 1, 'id': '123'}
        volume = fake_volume.fake_volume_obj(None, **vol_args)
        connector = dict(initiator='test_iqn.1')
        self.driver.create_volume(volume)
        props = self.driver.initialize_connection(volume, connector)
        self.assertEqual('iser', props['driver_volume_type'])
        data = props['data']
        self.assertEqual('1.1.1.1:3260', data['target_portal'])
        self.assertEqual('iqn.2011-04.zadarastorage:vsa-xxx:1',
                         data['target_iqn'])
        self.assertEqual(int('0'), data['target_lun'])
        self.assertEqual(volume['id'], data['volume_id'])
        self.assertEqual('CHAP', data['auth_method'])
        self.assertEqual('test_chap_user', data['auth_username'])
        self.assertEqual('test_chap_secret', data['auth_password'])
        self.driver.terminate_connection(volume, connector)
        self.driver.delete_volume(volume)

    @mock.patch.object(requests.Session, 'request', FakeRequests)
    def test_wrong_attach_params(self):
        """Test different wrong attach scenarios."""
        vol1_args = {'display_name': 'test_volume_01', 'size': 1, 'id': 101}
        volume1 = fake_volume.fake_volume_obj(None, **vol1_args)
        connector1 = dict(initiator='test_iqn.1')
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.initialize_connection,
                          volume1, connector1)

    @mock.patch.object(requests.Session, 'request', FakeRequests)
    def test_wrong_detach_params(self):
        """Test different wrong detachment scenarios."""
        vol1_args = {'display_name': 'test_volume_01', 'size': 1, 'id': 101}
        volume1 = fake_volume.fake_volume_obj(None, **vol1_args)
        # Volume is not created.
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.terminate_connection,
                          volume1, None)

        self.driver.create_volume(volume1)
        connector1 = dict(initiator='test_iqn.1')
        # Server is not found. Volume is found
        self.assertRaises(zadara_exception.ZadaraServerNotFound,
                          self.driver.terminate_connection,
                          volume1, connector1)

        vol2_args = {'display_name': 'test_volume_02', 'size': 1, 'id': 102}
        vol3_args = {'display_name': 'test_volume_03', 'size': 1, 'id': 103}
        volume2 = fake_volume.fake_volume_obj(None, **vol2_args)
        volume3 = fake_volume.fake_volume_obj(None, **vol3_args)
        connector2 = dict(initiator='test_iqn.2')
        connector3 = dict(initiator='test_iqn.3')
        self.driver.create_volume(volume2)
        self.driver.initialize_connection(volume1, connector1)
        self.driver.initialize_connection(volume2, connector2)
        # volume is found. Server not found
        self.assertRaises(zadara_exception.ZadaraServerNotFound,
                          self.driver.terminate_connection,
                          volume1, connector3)
        # Server is found. volume not found
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.terminate_connection,
                          volume3, connector1)
        # Server and volume exits but not attached
        self.assertRaises(common.exception.FailedCmdWithDump,
                          self.driver.terminate_connection,
                          volume1, connector2)

        self.driver.terminate_connection(volume1, connector1)
        self.driver.terminate_connection(volume2, connector2)

    @mock.patch.object(requests.Session, 'request')
    def test_ssl_use(self, request):
        """Coverage test for SSL connection."""
        self.configuration.zadara_ssl_cert_verify = True
        self.configuration.zadara_vpsa_use_ssl = True
        self.configuration.driver_ssl_cert_path = '/path/to/cert'

        fake_request_ctrls = FakeRequests("GET", "/api/vcontrollers.json")
        raw_controllers = fake_request_ctrls.content
        good_response = mock.MagicMock()
        good_response.status_code = RUNTIME_VARS['status']
        good_response.content = raw_controllers

        def request_verify_cert(*args, **kwargs):
            self.assertEqual(kwargs['verify'], '/path/to/cert')
            return good_response

        request.side_effect = request_verify_cert
        self.driver.do_setup(None)

    @mock.patch.object(requests.Session, 'request')
    def test_wrong_access_key(self, request):
        """Wrong Access Key"""
        fake_ak = 'FAKEACCESSKEY'
        self.configuration.zadara_access_key = fake_ak

        bad_response = mock.MagicMock()
        bad_response.status_code = RUNTIME_VARS['status']
        bad_response.content = RUNTIME_VARS['bad_login']

        def request_verify_access_key(*args, **kwargs):
            # Checks if the fake access_key was sent to driver
            token = kwargs['headers']['X-Access-Key']
            self.assertEqual(token, fake_ak, "access_key wasn't delivered")
            return bad_response

        request.side_effect = request_verify_access_key
        # when access key is invalid, driver will raise
        # ZadaraInvalidAccessKey exception
        self.assertRaises(zadara_exception.ZadaraCinderInvalidAccessKey,
                          self.driver.do_setup,
                          None)

    @mock.patch.object(requests.Session, 'request', FakeRequests)
    def test_bad_http_response(self):
        """Coverage test for non-good HTTP response."""
        RUNTIME_VARS['status'] = 400

        vol_args = {'display_name': 'test_volume_03', 'size': 1, 'id': 1}
        volume = fake_volume.fake_volume_obj(None, **vol_args)
        self.assertRaises(exception.BadHTTPResponseStatus,
                          self.driver.create_volume, volume)

    @mock.patch.object(requests.Session, 'request', FakeRequests)
    def test_terminate_connection_force_detach(self):
        """Test terminate connection for os-force_detach """
        vol_args = {'display_name': 'test_volume_01', 'size': 1, 'id': 101}
        volume = fake_volume.fake_volume_obj(None, **vol_args)
        connector = dict(initiator='test_iqn.1')

        self.driver.create_volume(volume)
        self.driver.initialize_connection(volume, connector)

        # connector is None - force detach - detach all mappings
        self.driver.terminate_connection(volume, None)

        self.assertRaises(common.exception.FailedCmdWithDump,
                          self.driver.terminate_connection,
                          volume, connector)

        self.driver.delete_volume(volume)

    @mock.patch.object(requests.Session, 'request', FakeRequests)
    def test_delete_without_detach(self):
        """Test volume deletion without detach."""

        vol1_args = {'display_name': 'test_volume_01', 'size': 1, 'id': 101}
        volume1 = fake_volume.fake_volume_obj(None, **vol1_args)
        connector1 = dict(initiator='test_iqn.1')
        connector2 = dict(initiator='test_iqn.2')
        connector3 = dict(initiator='test_iqn.3')
        self.driver.create_volume(volume1)
        self.driver.initialize_connection(volume1, connector1)
        self.driver.initialize_connection(volume1, connector2)
        self.driver.initialize_connection(volume1, connector3)
        self.driver.delete_volume(volume1)

    @mock.patch.object(requests.Session, 'request', FakeRequests)
    def test_no_active_ctrl(self):

        vol_args = {'display_name': 'test_volume_01', 'size': 1, 'id': 123}
        volume = fake_volume.fake_volume_obj(None, **vol_args)
        connector = dict(initiator='test_iqn.1')
        self.driver.create_volume(volume)

        RUNTIME_VARS['controllers'] = []
        self.assertRaises(zadara_exception.ZadaraVPSANoActiveController,
                          self.driver.initialize_connection,
                          volume, connector)

    @mock.patch.object(requests.Session, 'request', FakeRequests)
    def test_create_destroy_snapshot(self):
        """Create/Delete snapshot test."""
        wrong_vol_args = {'display_name': 'wrong_vol_01', 'size': 1, 'id': 2}
        wrong_volume = fake_volume.fake_volume_obj(None, **wrong_vol_args)
        wrong_snap_args = {'display_name': 'snap_01', 'volume': wrong_volume}
        wrong_snapshot = fake_snapshot.fake_snapshot_obj(None,
                                                         **wrong_snap_args)
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.create_snapshot,
                          wrong_snapshot)

        # Create cinder volume and snapshot
        vol_args = {'display_name': 'test_volume_01', 'size': 1, 'id': 1}
        volume = fake_volume.fake_volume_obj(None, **vol_args)
        snap_args = {'display_name': 'test_snap_01', 'id': 1, 'volume': volume}
        snapshot = fake_snapshot.fake_snapshot_obj(None, **snap_args)
        self.driver.create_volume(volume)
        self.driver.create_snapshot(snapshot)

        # Deleted should succeed for missing volume
        self.driver.delete_snapshot(wrong_snapshot)

        # Deleted should succeed for missing snap
        fake_snap_args = {'display_name': 'test_snap_02',
                          'id': 2, 'volume': volume}
        fake_snap = fake_snapshot.fake_snapshot_obj(None, **fake_snap_args)
        self.driver.delete_snapshot(fake_snap)

        self.driver.delete_snapshot(snapshot)
        self.driver.delete_volume(volume)

    @mock.patch.object(requests.Session, 'request', FakeRequests)
    def test_expand_volume(self):
        """Expand volume test."""
        vol_args = {'display_name': 'test_volume_01', 'id': 1, 'size': 10}
        vol2_args = {'display_name': 'test_volume_02', 'id': 2, 'size': 10}
        volume = fake_volume.fake_volume_obj(None, **vol_args)
        volume2 = fake_volume.fake_volume_obj(None, **vol2_args)

        self.driver.create_volume(volume)

        self.assertRaises(exception.VolumeDriverException,
                          self.driver.extend_volume,
                          volume2, 15)
        self.assertRaises(exception.InvalidInput,
                          self.driver.extend_volume,
                          volume, 5)

        self.driver.extend_volume(volume, 15)
        self.driver.delete_volume(volume)

    @mock.patch.object(requests.Session, 'request', FakeRequests)
    def test_create_destroy_clones(self):
        """Create/Delete clones test."""
        vol1_args = {'display_name': 'test_volume_01', 'id': 1, 'size': 1}
        vol2_args = {'display_name': 'test_volume_02', 'id': 2, 'size': 2}
        vol3_args = {'display_name': 'test_volume_03', 'id': 3, 'size': 1}
        volume1 = fake_volume.fake_volume_obj(None, **vol1_args)
        volume2 = fake_volume.fake_volume_obj(None, **vol2_args)
        volume3 = fake_volume.fake_volume_obj(None, **vol3_args)

        snap_args = {'display_name': 'test_snap_01',
                     'id': 1, 'volume': volume1}
        snapshot = fake_snapshot.fake_snapshot_obj(None, **snap_args)
        self.driver.create_volume(volume1)
        self.driver.create_snapshot(snapshot)

        # Test invalid vol reference
        wrong_vol_args = {'display_name': 'wrong_volume_01',
                          'id': 4, 'size': 1}
        wrong_volume = fake_volume.fake_volume_obj(None, **wrong_vol_args)
        wrong_snap_args = {'display_name': 'test_wrong_snap',
                           'id': 2, 'volume': wrong_volume}
        wrong_snapshot = fake_snapshot.fake_snapshot_obj(None,
                                                         **wrong_snap_args)
        self.assertRaises(exception.SnapshotNotFound,
                          self.driver.create_volume_from_snapshot,
                          wrong_volume,
                          wrong_snapshot)

        wrong_snap_args = {'display_name': 'test_wrong_snap',
                           'id': 4, 'volume': volume1}
        wrong_snapshot = fake_snapshot.fake_snapshot_obj(None,
                                                         **wrong_snap_args)
        # Test invalid snap reference
        self.assertRaises(exception.SnapshotNotFound,
                          self.driver.create_volume_from_snapshot,
                          volume1,
                          wrong_snapshot)
        # Test invalid src_vref for volume clone
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.create_cloned_volume,
                          volume3, volume2)
        self.driver.create_volume_from_snapshot(volume2, snapshot)
        self.driver.create_cloned_volume(volume3, volume1)
        self.driver.delete_volume(volume3)
        self.driver.delete_volume(volume2)
        self.driver.delete_snapshot(snapshot)
        self.driver.delete_volume(volume1)

    @mock.patch.object(requests.Session, 'request', FakeRequests)
    def test_get_volume_stats(self):
        """Get stats test."""
        self.configuration.safe_get.return_value = 'ZadaraVPSAISCSIDriver'
        data = self.driver.get_volume_stats(True)
        self.assertEqual('Zadara Storage', data['vendor_name'])
        self.assertEqual(100, data['total_capacity_gb'])
        self.assertEqual(99, data['free_capacity_gb'])
        self.assertEqual({'total_capacity_gb': 100,
                          'free_capacity_gb': 99,
                          'multiattach': True,
                          'reserved_percentage':
                          self.configuration.reserved_percentage,
                          'QoS_support': False,
                          'vendor_name': 'Zadara Storage',
                          'driver_version': self.driver.VERSION,
                          'storage_protocol': 'iSER',
                          'volume_backend_name': 'ZadaraVPSAISCSIDriver'},
                         data)

    def create_vpsa_backend_volume(self, vol_id, vol_name, vol_size,
                                   vol_status, has_snapshots):
        vol_params = {}
        vol_params['id'] = vol_id
        vol_params['name'] = vol_name
        vol_params['display-name'] = vol_name
        vol_params['cg_name'] = vol_name
        vol_params['provider_location'] = vol_name
        vol_params['status'] = vol_status
        vol_params['capacity'] = vol_size
        vol_params['pool'] = 'pool-0001'
        vol_params['has_snapshots'] = has_snapshots
        vol_params['server_ext_names'] = ''
        vol_params['snapshots'] = []
        volname = 'fake-volume'
        vpsa_volume = (volname, vol_params)
        RUNTIME_VARS['volumes'].append(vpsa_volume)
        return vpsa_volume

    @mock.patch.object(requests.Session, 'request', FakeRequests)
    def test_manage_existing_volume(self):
        vol_args = {'id': 'manage-name',
                    'display_name': 'manage-name',
                    'size': 1}
        volume = fake_volume.fake_volume_obj(None, **vol_args)
        vpsa_volume = self.create_vpsa_backend_volume('fake_id',
                                                      'fake_name', 1,
                                                      'Available', 'NO')
        # Check the failure with an empty reference for volume
        identifier = {}
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing,
                          volume, identifier)

        # Check the failure with an invalid reference for volume
        identifier['name'] = 'fake_identifier'
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing,
                          volume, identifier)

        identifier['name'] = 'fake_name'
        self.driver.manage_existing(volume, identifier)
        # Check the new volume renamed accordingly
        self.assertEqual(vpsa_volume[1]['display-name'],
                         'OS_%s' % volume['name'])
        self.driver.delete_volume(volume)

    @mock.patch.object(requests.Session, 'request', FakeRequests)
    def test_manage_existing_snapshot(self):
        vol_args = {'display_name': 'fake_name', 'size': 1, 'id': 1}
        volume = fake_volume.fake_volume_obj(None, **vol_args)
        self.driver.create_volume(volume)

        # Create a backend snapshot that will be managed by cinder volume
        (vol_name, vol_params) = RUNTIME_VARS['volumes'][0]
        vol_params['snapshots'].append('fakesnapname')

        # Check the failure with wrong volume for snapshot
        wrong_vol_args = {'display_name': 'wrong_volume_01',
                          'size': 1, 'id': 2}
        wrong_volume = fake_volume.fake_volume_obj(None, **wrong_vol_args)
        wrong_snap_args = {'display_name': 'snap_01', 'volume': wrong_volume}
        wrong_snapshot = fake_snapshot.fake_snapshot_obj(None,
                                                         **wrong_snap_args)
        identifier = {}
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_snapshot,
                          wrong_snapshot, identifier)

        identifier['name'] = 'fake_identifier'
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_snapshot,
                          wrong_snapshot, identifier)

        # Check the failure with wrong identifier for the snapshot
        snap_args = {'display_name': 'manage_snapname',
                     'id': 'manage_snapname', 'volume': volume}
        snapshot = fake_snapshot.fake_snapshot_obj(None, **snap_args)
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_snapshot,
                          snapshot, identifier)

        identifier['name'] = 'fakesnapname'
        self.driver.manage_existing_snapshot(snapshot, identifier)
        # Check that the backend snapshot has been renamed
        (vol_name, vol_params) = RUNTIME_VARS['volumes'][0]
        self.assertEqual(vol_params['snapshots'][0], snapshot['name'])
        self.driver.delete_snapshot(snapshot)
        self.driver.delete_volume(volume)

    @mock.patch.object(requests.Session, 'request', FakeRequests)
    def test_get_manageable_volumes(self):
        vpsa_volume1 = self.create_vpsa_backend_volume('manage_vol_id1',
                                                       'manage_vol1', 1,
                                                       'Available', 'NO')
        vpsa_volume2 = self.create_vpsa_backend_volume('manage_vol_id2',
                                                       'manage_vol2', 2,
                                                       'Available', 'NO')

        cinder_vol1_args = {'display_name': 'fake-volume1',
                            'size': 3, 'id': 'fake-volume1'}
        cinder_vol2_args = {'display_name': 'fake-volume2',
                            'size': 4, 'id': 'fake-volume2'}
        cinder_vol1 = fake_volume.fake_volume_obj(None, **cinder_vol1_args)
        cinder_vol2 = fake_volume.fake_volume_obj(None, **cinder_vol2_args)
        self.driver.create_volume(cinder_vol1)
        self.driver.create_volume(cinder_vol2)

        cinder_vols = [cinder_vol1, cinder_vol2]
        manageable_vols = (self.driver.get_manageable_volumes(
                           cinder_vols, None, 10, 0, ['size'], ['asc']))
        # Check the volumes are returned in the sorted order
        self.assertEqual(len(manageable_vols), 4)
        self.assertGreater(manageable_vols[1]['size'],
                           manageable_vols[0]['size'])
        self.assertGreater(manageable_vols[3]['size'],
                           manageable_vols[2]['size'])
        self.driver.delete_volume(cinder_vol1)
        self.driver.delete_volume(cinder_vol2)

        # Try to manage the volume and delete it
        vol1_args = {'display_name': 'manage-name1',
                     'size': 1, 'id': 'manage-name1'}
        volume1 = fake_volume.fake_volume_obj(None, **vol1_args)
        identifier = {'name': 'manage_vol1'}
        self.driver.manage_existing(volume1, identifier)
        self.assertEqual(vpsa_volume1[1]['display-name'],
                         'OS_%s' % volume1['name'])
        self.driver.delete_volume(volume1)

        # Manage and delete the volume
        vol2_args = {'display_name': 'manage-name2',
                     'size': 1, 'id': 'manage-name2'}
        volume2 = fake_volume.fake_volume_obj(None, **vol2_args)
        identifier = {'name': 'manage_vol2'}
        self.driver.manage_existing(volume2, identifier)
        self.assertEqual(vpsa_volume2[1]['display-name'],
                         'OS_%s' % volume2['name'])
        self.driver.delete_volume(volume2)

    @mock.patch.object(requests.Session, 'request', FakeRequests)
    def test_get_manageable_snapshots(self):
        # Create a cinder volume and a snapshot
        vol_args = {'display_name': 'test_volume_01', 'size': 1, 'id': 1}
        volume = fake_volume.fake_volume_obj(None, **vol_args)
        snap_args = {'display_name': 'test_snap_01',
                     'id': 1, 'volume': volume}
        snapshot = fake_snapshot.fake_snapshot_obj(None, **snap_args)
        self.driver.create_volume(volume)
        self.driver.create_snapshot(snapshot)

        # Create backend snapshots for the volume
        vpsa_volume = self.create_vpsa_backend_volume('manage_vol_id',
                                                      'manage_vol', 1,
                                                      'Available', 'YES')
        snapshot1 = {'name': 'manage_snap_01',
                     'volume_name': vpsa_volume[1]['name'],
                     'provider_location': 'manage_snap_01'}
        snapshot2 = {'name': 'manage_snap_02',
                     'volume_name': vpsa_volume[1]['name'],
                     'provider_location': 'manage_snap_02'}
        vpsa_volume[1]['snapshots'].append(snapshot1['name'])
        vpsa_volume[1]['snapshots'].append(snapshot2['name'])

        cinder_snapshots = [snapshot]
        manageable_snapshots = (self.driver.get_manageable_snapshots(
            cinder_snapshots, None, 10, 0, ['reference'], ['asc']))
        # Check the returned manageable snapshot names
        self.assertEqual(snapshot1['name'],
                         manageable_snapshots[0]['reference']['name'])
        self.assertEqual(snapshot2['name'],
                         manageable_snapshots[1]['reference']['name'])

        # Verify the safety of the snapshots to manage
        self.assertEqual(manageable_snapshots[0]['safe_to_manage'], True)
        self.assertEqual(manageable_snapshots[1]['safe_to_manage'], True)

        # Verify the refernce of the source volume of the snapshots
        source_vol = manageable_snapshots[0]['source_reference']
        self.assertEqual(vpsa_volume[1]['name'], source_vol['name'])
        source_vol = manageable_snapshots[1]['source_reference']
        self.assertEqual(vpsa_volume[1]['name'], source_vol['name'])
        self.driver.delete_volume(volume)

    @mock.patch.object(requests.Session, 'request', FakeRequests)
    def test_manage_existing_volume_get_size(self):
        vol_args = {'display_name': 'fake_name', 'id': 1, 'size': 1}
        volume = fake_volume.fake_volume_obj(None, **vol_args)
        self.driver.create_volume(volume)

        # Check the failure with empty reference of the volume
        identifier = {}
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_get_size,
                          volume, identifier)

        # Check the failure with invalid volume reference
        identifier = {'name': 'fake_identifiter'}
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_get_size,
                          volume, identifier)

        # Verify the volume size
        identifier = {'name': 'OS_volume-%s' % volume['id']}
        vol_size = self.driver.manage_existing_get_size(volume, identifier)
        self.assertEqual(vol_size, volume.size)
        self.driver.delete_volume(volume)

    @mock.patch.object(requests.Session, 'request', FakeRequests)
    def test_manage_existing_snapshot_get_size(self):
        # Create a cinder volume and a snapshot
        vol_args = {'display_name': 'fake_name', 'id': 1, 'size': 1}
        volume = fake_volume.fake_volume_obj(None, **vol_args)
        self.driver.create_volume(volume)
        snap_args = {'display_name': 'fake_snap',
                     'id': 1, 'volume': volume}
        snapshot = fake_snapshot.fake_snapshot_obj(None, **snap_args)
        self.driver.create_snapshot(snapshot)

        # Check with the wrong volume of the snapshot
        wrong_vol_args = {'display_name': 'wrong_volume_01',
                          'size': 1, 'id': 2}
        wrong_volume = fake_volume.fake_volume_obj(None, **wrong_vol_args)
        wrong_snap_args = {'display_name': 'wrong_snap',
                           'volume': wrong_volume}
        wrong_snapshot = fake_snapshot.fake_snapshot_obj(None,
                                                         **wrong_snap_args)
        identifier = {}
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_snapshot_get_size,
                          wrong_snapshot, identifier)

        identifier = {'name': 'fake_identifiter'}
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_snapshot_get_size,
                          wrong_snapshot, identifier)

        # Check with the invalid reference of the snapshot
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_snapshot_get_size,
                          snapshot, identifier)

        # Verify the snapshot size same as the volume
        identifier = {'name': 'snapshot-%s' % snapshot['id']}
        snap_size = (self.driver.manage_existing_snapshot_get_size(
                     snapshot, identifier))
        self.assertEqual(snap_size, volume['size'])
        self.driver.delete_volume(volume)
