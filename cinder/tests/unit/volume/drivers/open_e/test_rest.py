#    Copyright (c) 2020 Open-E, Inc.
#    All Rights Reserved.
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

from unittest import mock

from oslo_utils import units as o_units

from cinder import context
from cinder import exception
from cinder.tests.unit import test
from cinder.volume.drivers.open_e.jovian_common import exception as jexc
from cinder.volume.drivers.open_e.jovian_common import jdss_common as jcom
from cinder.volume.drivers.open_e.jovian_common import rest

UUID_1 = '12345678-1234-1234-1234-000000000001'
UUID_2 = '12345678-1234-1234-1234-000000000002'
UUID_3 = '12345678-1234-1234-1234-000000000003'

CONFIG_OK = {
    'san_hosts': ['192.168.0.2'],
    'san_api_port': 82,
    'driver_use_ssl': 'true',
    'jovian_rest_send_repeats': 3,
    'jovian_recovery_delay': 60,
    'san_login': 'admin',
    'san_password': 'password',
    'jovian_ignore_tpath': [],
    'target_port': 3260,
    'jovian_pool': 'Pool-0',
    'iscsi_target_prefix': 'iqn.2020-04.com.open-e.cinder:',
    'chap_password_len': 12,
    'san_thin_provision': False,
    'jovian_block_size': '128K'
}


class TestOpenEJovianRESTAPI(test.TestCase):

    def get_rest(self, config):
        ctx = context.get_admin_context()

        cfg = mock.Mock()
        cfg.append_config_values.return_value = None
        cfg.safe_get = lambda val: config[val]
        cfg.get = lambda val, default: config.get(val, default)
        jdssr = rest.JovianRESTAPI(config)
        jdssr.rproxy = mock.Mock()
        return jdssr, ctx

    def test_get_active_host(self):

        jrest, ctx = self.get_rest(CONFIG_OK)

        jrest.rproxy.get_active_host.return_value = "test_data"

        ret = jrest.get_active_host()

        self.assertEqual("test_data", ret)

    def test_is_pool_exists(self):
        jrest, ctx = self.get_rest(CONFIG_OK)
        resp = {'code': 200,
                'error': None}

        jrest.rproxy.pool_request.return_value = resp
        self.assertTrue(jrest.is_pool_exists())

        err = {'errorid': 12}
        resp = {'code': 404,
                'error': err}
        jrest.rproxy.pool_request.return_value = resp
        self.assertFalse(jrest.is_pool_exists())

        pool_request_expected = [
            mock.call('GET', ''),
            mock.call('GET', '')]

        jrest.rproxy.pool_request.assert_has_calls(pool_request_expected)

    def get_iface_info(self):

        jrest, ctx = self.get_rest(CONFIG_OK)
        resp = {
            'code': 200,
            'error': None}
        jrest.rproxy.pool_request.return_value = resp
        self.assertTrue(jrest.is_pool_exists())

    def test_get_luns(self):

        jrest, ctx = self.get_rest(CONFIG_OK)
        resp = {'data': [{
                'vscan': None,
                'full_name': 'Pool-0/' + UUID_1,
                'userrefs': None,
                'primarycache': 'all',
                'logbias': 'latency',
                'creation': '1591543140',
                'sync': 'always',
                'is_clone': False,
                'dedup': 'off',
                'sharenfs': None,
                'receive_resume_token': None,
                'volsize': '1073741824'}],
                'error': None,
                'code': 200}
        jrest.rproxy.pool_request.return_value = resp
        self.assertEqual(resp['data'], jrest.get_luns())

        err = {'errorid': 12, 'message': 'test failure'}
        resp = {'code': 404,
                'data': None,
                'error': err}
        jrest.rproxy.pool_request.return_value = resp
        self.assertRaises(jexc.JDSSRESTException, jrest.get_luns)

        get_luns_expected = [
            mock.call('GET', "/volumes"),
            mock.call('GET', "/volumes")]

        jrest.rproxy.pool_request.assert_has_calls(get_luns_expected)

    def test_create_lun(self):

        jrest, ctx = self.get_rest(CONFIG_OK)
        resp = {'data': {
                'vscan': None,
                'full_name': 'Pool-0/' + jcom.vname(UUID_1),
                'userrefs': None,
                'primarycache': 'all',
                'logbias': 'latency',
                'creation': '1591543140',
                'sync': 'always',
                'is_clone': False,
                'dedup': 'off',
                'sharenfs': None,
                'receive_resume_token': None,
                'volsize': '1073741824'},
                'error': None,
                'code': 200}

        jbody = {
            'name': jcom.vname(UUID_1),
            'size': "1073741824",
            'sparse': False
        }

        jbody_sparse = {
            'name': jcom.vname(UUID_1),
            'size': "1073741824",
            'sparse': True
        }

        jrest.rproxy.pool_request.return_value = resp
        self.assertIsNone(jrest.create_lun(jcom.vname(UUID_1), o_units.Gi))

        err = {'errno': '5', 'message': 'test failure'}
        resp = {'code': 404,
                'data': None,
                'error': err}
        jrest.rproxy.pool_request.return_value = resp
        self.assertRaises(jexc.JDSSRESTException,
                          jrest.create_lun,
                          jcom.vname(UUID_1),
                          o_units.Gi,
                          sparse=True)

        addr = "/volumes"
        create_lun_expected = [
            mock.call('POST', addr, json_data=jbody),
            mock.call('POST', addr, json_data=jbody_sparse)]

        jrest.rproxy.pool_request.assert_has_calls(create_lun_expected)

    def test_extend_lun(self):

        jrest, ctx = self.get_rest(CONFIG_OK)
        resp = {'data': None,
                'error': None,
                'code': 201}

        jbody = {
            'size': "2147483648",
        }

        jrest.rproxy.pool_request.return_value = resp
        self.assertIsNone(jrest.extend_lun(jcom.vname(UUID_1), 2 * o_units.Gi))

        err = {'message': 'test failure'}
        resp = {'code': 500,
                'data': None,
                'error': err}
        jrest.rproxy.pool_request.return_value = resp
        self.assertRaises(jexc.JDSSRESTException,
                          jrest.extend_lun,
                          jcom.vname(UUID_1),
                          2 * o_units.Gi)

        addr = "/volumes/" + jcom.vname(UUID_1)
        create_lun_expected = [
            mock.call('PUT', addr, json_data=jbody),
            mock.call('PUT', addr, json_data=jbody)]

        jrest.rproxy.pool_request.assert_has_calls(create_lun_expected)

    def test_is_lun(self):

        jrest, ctx = self.get_rest(CONFIG_OK)
        resp = {'data': {
                "vscan": None,
                "full_name": "Pool-0/" + jcom.vname(UUID_1),
                "userrefs": None,
                "primarycache": "all",
                "logbias": "latency",
                "creation": "1591543140",
                "sync": "always",
                "is_clone": False,
                "dedup": "off",
                "sharenfs": None,
                "receive_resume_token": None,
                "volsize": "1073741824"},
                'error': None,
                'code': 200}

        jrest.rproxy.pool_request.return_value = resp
        self.assertTrue(jrest.is_lun(jcom.vname(UUID_1)))

        err = {'errno': 1,
               'message': ('Zfs resource: Pool-0/' + jcom.vname(UUID_1) +
                           ' not found in this collection.')}
        resp = {'code': 500,
                'data': None,
                'error': err}

        jrest.rproxy.pool_request.return_value = resp
        self.assertEqual(False, jrest.is_lun(jcom.vname(UUID_1)))

        jrest.rproxy.pool_request.side_effect = (
            jexc.JDSSRESTProxyException(host='test_host', reason='test'))

        self.assertRaises(jexc.JDSSRESTProxyException,
                          jrest.is_lun,
                          'v_' + UUID_1)

    def test_get_lun(self):
        jrest, ctx = self.get_rest(CONFIG_OK)
        resp = {'data': {"vscan": None,
                         "full_name": "Pool-0/v_" + UUID_1,
                         "userrefs": None,
                         "primarycache": "all",
                         "logbias": "latency",
                         "creation": "1591543140",
                         "sync": "always",
                         "is_clone": False,
                         "dedup": "off",
                         "sharenfs": None,
                         "receive_resume_token": None,
                         "volsize": "1073741824"},
                'error': None,
                'code': 200}

        jrest.rproxy.pool_request.return_value = resp
        self.assertEqual(resp['data'], jrest.get_lun('v_' + UUID_1))

        err = {'errno': 1,
               'message': ('Zfs resource: Pool-0/v_' + UUID_1 +
                           ' not found in this collection.')}
        resp = {'code': 500,
                'data': None,
                'error': err}

        jrest.rproxy.pool_request.return_value = resp
        self.assertRaises(jexc.JDSSResourceNotFoundException,
                          jrest.get_lun,
                          'v_' + UUID_1)

        jrest.rproxy.pool_request.return_value = resp
        self.assertRaises(jexc.JDSSResourceNotFoundException,
                          jrest.get_lun,
                          'v_' + UUID_1)

        err = {'errno': 10,
               'message': ('Test error')}
        resp = {'code': 500,
                'data': None,
                'error': err}

        jrest.rproxy.pool_request.return_value = resp
        self.assertRaises(jexc.JDSSException, jrest.get_lun, 'v_' + UUID_1)

    def test_modify_lun(self):

        jrest, ctx = self.get_rest(CONFIG_OK)
        resp = {'data': None,
                'error': None,
                'code': 201}
        req = {'name': 'v_' + UUID_2}

        jrest.rproxy.pool_request.return_value = resp
        self.assertIsNone(jrest.modify_lun('v_' + UUID_1, prop=req))

        err = {'errno': 1,
               'message': ('Zfs resource: Pool-0/v_' + UUID_1 +
                           ' not found in this collection.')}
        resp = {'code': 500,
                'data': None,
                'error': err}

        jrest.rproxy.pool_request.return_value = resp
        self.assertRaises(jexc.JDSSResourceNotFoundException,
                          jrest.modify_lun,
                          'v_' + UUID_1,
                          prop=req)

        err = {'errno': 10,
               'message': ('Test error')}
        resp = {'code': 500,
                'data': None,
                'error': err}

        jrest.rproxy.pool_request.return_value = resp
        self.assertRaises(jexc.JDSSException,
                          jrest.modify_lun,
                          'v_' + UUID_1,
                          prop=req)

        addr = "/volumes/v_" + UUID_1
        modify_lun_expected = [
            mock.call('PUT', addr, json_data=req),
            mock.call('PUT', addr, json_data=req),
            mock.call('PUT', addr, json_data=req)]

        jrest.rproxy.pool_request.assert_has_calls(modify_lun_expected)

    def test_make_readonly_lun(self):

        jrest, ctx = self.get_rest(CONFIG_OK)
        resp = {'data': None,
                'error': None,
                'code': 201}
        req = {'property_name': 'readonly', 'property_value': 'on'}

        jrest.rproxy.pool_request.return_value = resp
        self.assertIsNone(jrest.modify_lun('v_' + UUID_1, prop=req))

        addr = "/volumes/v_" + UUID_1
        modify_lun_expected = [mock.call('PUT', addr, json_data=req)]

        jrest.rproxy.pool_request.assert_has_calls(modify_lun_expected)

    def test_delete_lun(self):

        jrest, ctx = self.get_rest(CONFIG_OK)

        # Delete OK
        resp = {'data': None,
                'error': None,
                'code': 204}

        jrest.rproxy.pool_request.return_value = resp
        self.assertIsNone(jrest.delete_lun('v_' + UUID_1))
        addr = "/volumes/v_" + UUID_1
        delete_lun_expected = [mock.call('DELETE', addr)]
        jrest.rproxy.pool_request.assert_has_calls(delete_lun_expected)
        # No volume to delete
        err = {'errno': 1,
               'message': ('Zfs resource: Pool-0/v_' + UUID_1 +
                           ' not found in this collection.')}
        resp = {'code': 500,
                'data': None,
                'error': err}

        jrest.rproxy.pool_request.return_value = resp
        self.assertIsNone(jrest.delete_lun('v_' + UUID_1))

        delete_lun_expected += [mock.call('DELETE', addr)]

        jrest.rproxy.pool_request.assert_has_calls(delete_lun_expected)

        # Volume has snapshots
        msg = ("cannot destroy 'Pool-0/{vol}': volume has children\nuse '-r'"
               " to destroy the following datasets:\nPool-0/{vol}@s1")
        msg = msg.format(vol='v_' + UUID_1)

        url = "http://192.168.0.2:82/api/v3/pools/Pool-0/volumes/" + UUID_1
        err = {"class": "zfslib.wrap.zfs.ZfsCmdError",
               "errno": 1000,
               "message": msg,
               "url": url}

        resp = {
            'code': 500,
            'data': None,
            'error': err}

        delete_lun_expected += [mock.call('DELETE', addr)]
        jrest.rproxy.pool_request.return_value = resp
        self.assertRaises(
            exception.VolumeIsBusy,
            jrest.delete_lun,
            'v_' + UUID_1)

        jrest.rproxy.pool_request.assert_has_calls(delete_lun_expected)

    def test_delete_lun_args(self):

        jrest, ctx = self.get_rest(CONFIG_OK)
        addr = "/volumes/v_" + UUID_1

        # Delete OK
        resp = {'data': None,
                'error': None,
                'code': 204}
        req = {'recursively_children': True,
               'recursively_dependents': True,
               'force_umount': True}

        delete_lun_expected = [mock.call('DELETE', addr, json_data=req)]
        jrest.rproxy.pool_request.return_value = resp
        self.assertIsNone(
            jrest.delete_lun('v_' + UUID_1,
                             recursively_children=True,
                             recursively_dependents=True,
                             force_umount=True))

        jrest.rproxy.pool_request.assert_has_calls(delete_lun_expected)

    def test_is_target(self):

        jrest, ctx = self.get_rest(CONFIG_OK)

        tname = CONFIG_OK['iscsi_target_prefix'] + UUID_1
        addr = '/san/iscsi/targets/{}'.format(tname)
        data = {'incoming_users_active': True,
                'name': tname,
                'allow_ip': [],
                'outgoing_user': None,
                'active': True,
                'conflicted': False,
                'deny_ip': []}

        resp = {'data': data,
                'error': None,
                'code': 200}

        is_target_expected = [mock.call('GET', addr)]
        jrest.rproxy.pool_request.return_value = resp
        self.assertTrue(jrest.is_target(tname))

        msg = "Target {} not exists.".format(tname)
        url = ("http://{addr}:{port}/api/v3/pools/Pool-0/"
               "san/iscsi/targets/{target}")
        url = url.format(addr=CONFIG_OK['san_hosts'][0],
                         port=CONFIG_OK['san_api_port'],
                         target=tname)
        err = {"class": "opene.exceptions.ItemNotFoundError",
               "message": msg,
               "url": url}

        resp = {'data': None,
                'error': err,
                'code': 404}

        is_target_expected += [mock.call('GET', addr)]
        jrest.rproxy.pool_request.return_value = resp
        self.assertEqual(False, jrest.is_target(tname))

        jrest.rproxy.pool_request.assert_has_calls(is_target_expected)

    def test_create_target(self):

        jrest, ctx = self.get_rest(CONFIG_OK)
        # Create OK
        tname = CONFIG_OK['iscsi_target_prefix'] + UUID_1
        addr = '/san/iscsi/targets'
        data = {'incoming_users_active': True,
                'name': tname,
                'allow_ip': [],
                'outgoing_user': None,
                'active': True,
                'conflicted': False,
                'deny_ip': []}

        resp = {'data': data,
                'error': None,
                'code': 201}

        req = {'name': tname,
               'active': True,
               'incoming_users_active': True}

        jrest.rproxy.pool_request.return_value = resp
        create_target_expected = [mock.call('POST', addr, json_data=req)]
        self.assertIsNone(jrest.create_target(tname))

        # Target exists
        tname = CONFIG_OK['iscsi_target_prefix'] + UUID_1
        addr = '/san/iscsi/targets'
        data = {'incoming_users_active': True,
                'name': tname,
                'allow_ip': [],
                'outgoing_user': None,
                'active': True,
                'conflicted': False,
                'deny_ip': []}

        resp = {'data': data,
                'error': None,
                'code': 201}

        url = ("http://{addr}:{port}/api/v3/pools/Pool-0/"
               "san/iscsi/targets")
        url = url.format(addr=CONFIG_OK['san_hosts'][0],
                         port=CONFIG_OK['san_api_port'])
        msg = "Target with name {} is already present on Pool-0.".format(tname)

        err = {"class": "opene.san.target.base.iscsi.TargetNameConflictError",
               "message": msg,
               "url": url}

        resp = {'data': None,
                'error': err,
                'code': 409}

        jrest.rproxy.pool_request.return_value = resp
        create_target_expected += [mock.call('POST', addr, json_data=req)]

        self.assertRaises(jexc.JDSSResourceExistsException,
                          jrest.create_target, tname)

        # Unknown error
        tname = CONFIG_OK['iscsi_target_prefix'] + UUID_1
        addr = "/san/iscsi/targets"

        resp = {'data': data,
                'error': None,
                'code': 500}

        url = ("http://{addr}:{port}/api/v3/pools/Pool-0/"
               "san/iscsi/targets")
        url = url.format(addr=CONFIG_OK['san_hosts'][0],
                         port=CONFIG_OK['san_api_port'])

        msg = "Target with name {} faced some fatal failure.".format(tname)

        err = {"class": "some test error",
               "message": msg,
               "url": url,
               "errno": 123}

        resp = {'data': None,
                'error': err,
                'code': 500}

        jrest.rproxy.pool_request.return_value = resp
        create_target_expected += [mock.call('POST', addr, json_data=req)]

        self.assertRaises(jexc.JDSSException,
                          jrest.create_target, tname)

        jrest.rproxy.pool_request.assert_has_calls(create_target_expected)

    def test_delete_target(self):

        jrest, ctx = self.get_rest(CONFIG_OK)
        # Delete OK
        tname = CONFIG_OK['iscsi_target_prefix'] + UUID_1
        addr = '/san/iscsi/targets/{}'.format(tname)

        resp = {'data': None,
                'error': None,
                'code': 204}

        jrest.rproxy.pool_request.return_value = resp
        delete_target_expected = [mock.call('DELETE', addr)]
        self.assertIsNone(jrest.delete_target(tname))

        # Delete no such target

        url = ("http://{addr}:{port}/api/v3/pools/Pool-0/"
               "san/iscsi/targets")
        url = url.format(addr=CONFIG_OK['san_hosts'][0],
                         port=CONFIG_OK['san_api_port'])
        err = {"class": "opene.exceptions.ItemNotFoundError",
               "message": "Target {} not exists.".format(tname),
               "url": url}

        resp = {'data': None,
                'error': err,
                'code': 404}

        jrest.rproxy.pool_request.return_value = resp
        delete_target_expected += [mock.call('DELETE', addr)]

        self.assertRaises(jexc.JDSSResourceNotFoundException,
                          jrest.delete_target, tname)
        # Delete unknown error
        err = {"class": "some test error",
               "message": "test error message",
               "url": url,
               "errno": 123}

        resp = {'data': None,
                'error': err,
                'code': 500}

        jrest.rproxy.pool_request.return_value = resp
        delete_target_expected += [mock.call('DELETE', addr)]

        self.assertRaises(jexc.JDSSException,
                          jrest.delete_target, tname)

        jrest.rproxy.pool_request.assert_has_calls(delete_target_expected)

    def test_create_target_user(self):

        jrest, ctx = self.get_rest(CONFIG_OK)
        # Modify OK
        tname = CONFIG_OK['iscsi_target_prefix'] + UUID_1
        addr = '/san/iscsi/targets/{}/incoming-users'.format(tname)

        chap_cred = {"name": "chapuser",
                     "password": "123456789012"}
        resp = {'data': None,
                'error': None,
                'code': 201}

        jrest.rproxy.pool_request.return_value = resp
        expected = [mock.call('POST', addr, json_data=chap_cred)]
        self.assertIsNone(jrest.create_target_user(tname, chap_cred))

        # No such target

        url = ("http://{addr}:{port}/api/v3/pools/Pool-0/"
               "san/iscsi/targets")
        url = url.format(addr=CONFIG_OK['san_hosts'][0],
                         port=CONFIG_OK['san_api_port'])
        err = {"class": "opene.exceptions.ItemNotFoundError",
               "message": "Target {} not exists.".format(tname),
               "url": url}

        resp = {'data': None,
                'error': err,
                'code': 404}

        jrest.rproxy.pool_request.return_value = resp
        expected += [mock.call('POST', addr, json_data=chap_cred)]

        self.assertRaises(jexc.JDSSResourceNotFoundException,
                          jrest.create_target_user, tname, chap_cred)
        # Unknown error
        err = {"class": "some test error",
               "message": "test error message",
               "url": url,
               "errno": 123}

        resp = {'data': None,
                'error': err,
                'code': 500}

        jrest.rproxy.pool_request.return_value = resp
        expected += [mock.call('POST', addr, json_data=chap_cred)]

        self.assertRaises(jexc.JDSSException,
                          jrest.create_target_user, tname, chap_cred)

        jrest.rproxy.pool_request.assert_has_calls(expected)

    def test_get_target_user(self):

        jrest, ctx = self.get_rest(CONFIG_OK)
        # Get OK
        tname = CONFIG_OK['iscsi_target_prefix'] + UUID_1
        addr = '/san/iscsi/targets/{}/incoming-users'.format(tname)

        chap_users = {"name": "chapuser"}

        resp = {'data': chap_users,
                'error': None,
                'code': 200}

        jrest.rproxy.pool_request.return_value = resp
        get_target_user_expected = [mock.call('GET', addr)]
        self.assertEqual(chap_users, jrest.get_target_user(tname))

        # No such target

        url = ("http://{addr}:{port}/api/v3/pools/Pool-0/"
               "san/iscsi/targets")
        url = url.format(addr=CONFIG_OK['san_hosts'][0],
                         port=CONFIG_OK['san_api_port'])
        err = {"class": "opene.exceptions.ItemNotFoundError",
               "message": "Target {} not exists.".format(tname),
               "url": url}

        resp = {'data': None,
                'error': err,
                'code': 404}

        jrest.rproxy.pool_request.return_value = resp
        get_target_user_expected += [mock.call('GET', addr)]

        self.assertRaises(jexc.JDSSResourceNotFoundException,
                          jrest.get_target_user, tname)
        # Unknown error
        err = {"class": "some test error",
               "message": "test error message",
               "url": url,
               "errno": 123}

        resp = {'data': None,
                'error': err,
                'code': 500}

        jrest.rproxy.pool_request.return_value = resp
        get_target_user_expected += [mock.call('GET', addr)]

        self.assertRaises(jexc.JDSSException,
                          jrest.get_target_user, tname)

        jrest.rproxy.pool_request.assert_has_calls(get_target_user_expected)

    def test_delete_target_user(self):

        jrest, ctx = self.get_rest(CONFIG_OK)
        # Delete OK
        tname = CONFIG_OK['iscsi_target_prefix'] + UUID_1
        user = "chapuser"
        addr = '/san/iscsi/targets/{}/incoming-users/chapuser'.format(tname)

        resp = {'data': None,
                'error': None,
                'code': 204}

        jrest.rproxy.pool_request.return_value = resp
        delete_target_user_expected = [mock.call('DELETE', addr)]
        self.assertIsNone(jrest.delete_target_user(tname, user))

        # No such user

        url = ("http://{addr}:{port}/api/v3/pools/Pool-0/"
               "san/iscsi/targets/{tname}/incoming-user/{chapuser}")
        url = url.format(addr=CONFIG_OK['san_hosts'][0],
                         port=CONFIG_OK['san_api_port'],
                         tname=tname,
                         chapuser=user)
        err = {"class": "opene.exceptions.ItemNotFoundError",
               "message": "User {} not exists.".format(user),
               "url": url}

        resp = {'data': None,
                'error': err,
                'code': 404}

        jrest.rproxy.pool_request.return_value = resp
        delete_target_user_expected += [mock.call('DELETE', addr)]

        self.assertRaises(jexc.JDSSResourceNotFoundException,
                          jrest.delete_target_user, tname, user)
        # Unknown error
        err = {"class": "some test error",
               "message": "test error message",
               "url": url,
               "errno": 123}

        resp = {'data': None,
                'error': err,
                'code': 500}

        jrest.rproxy.pool_request.return_value = resp
        delete_target_user_expected += [mock.call('DELETE', addr)]

        self.assertRaises(jexc.JDSSException,
                          jrest.delete_target_user, tname, user)

        jrest.rproxy.pool_request.assert_has_calls(delete_target_user_expected)

    def test_is_target_lun(self):

        jrest, ctx = self.get_rest(CONFIG_OK)
        # lun present
        tname = CONFIG_OK['iscsi_target_prefix'] + UUID_1
        vname = jcom.vname(UUID_1)
        addr = '/san/iscsi/targets/{target}/luns/{lun}'.format(
            target=tname, lun=vname)
        data = {
            "block_size": 512,
            "device_handler": "vdisk_fileio",
            "lun": 0,
            "mode": "wt",
            "name": vname,
            "prod_id": "Storage",
            "scsi_id": "99e2c883331edf87"}
        resp = {'data': data,
                'error': None,
                'code': 200}

        jrest.rproxy.pool_request.return_value = resp
        is_target_lun_expected = [mock.call('GET', addr)]
        self.assertTrue(jrest.is_target_lun(tname, vname))

        url = "http://{ip}:{port}/api/v3/pools/Pool-0{addr}"
        url = url.format(ip=CONFIG_OK['san_hosts'][0],
                         port=CONFIG_OK['san_api_port'],
                         tname=tname,
                         addr=addr)
        msg = "volume name {lun} is not attached to target {target}"
        msg = msg.format(lun=vname, target=tname)
        err = {"class": "opene.exceptions.ItemNotFoundError",
               "message": msg,
               "url": url}

        resp = {'data': None,
                'error': err,
                'code': 404}

        jrest.rproxy.pool_request.return_value = resp
        is_target_lun_expected += [mock.call('GET', addr)]

        self.assertEqual(False, jrest.is_target_lun(tname, vname))

        err = {"class": "some test error",
               "message": "test error message",
               "url": url,
               "errno": 123}

        resp = {'data': None,
                'error': err,
                'code': 500}

        jrest.rproxy.pool_request.return_value = resp
        is_target_lun_expected += [mock.call('GET', addr)]

        self.assertRaises(jexc.JDSSException,
                          jrest.is_target_lun, tname, vname)

        jrest.rproxy.pool_request.assert_has_calls(is_target_lun_expected)

    def test_attach_target_vol(self):

        jrest, ctx = self.get_rest(CONFIG_OK)
        # attach ok
        tname = CONFIG_OK['iscsi_target_prefix'] + UUID_1
        vname = jcom.vname(UUID_1)

        addr = '/san/iscsi/targets/{}/luns'.format(tname)
        jbody = {"name": vname, "lun": 0}

        data = {"block_size": 512,
                "device_handler": "vdisk_fileio",
                "lun": 0,
                "mode": "wt",
                "name": vname,
                "prod_id": "Storage",
                "scsi_id": "99e2c883331edf87"}

        resp = {'data': data,
                'error': None,
                'code': 201}

        jrest.rproxy.pool_request.return_value = resp
        attach_target_vol_expected = [
            mock.call('POST', addr, json_data=jbody)]
        self.assertIsNone(jrest.attach_target_vol(tname, vname))

        # lun attached already
        url = 'http://85.14.118.246:11582/api/v3/pools/Pool-0/{}'.format(addr)
        msg = 'Volume /dev/Pool-0/{} is already used.'.format(vname)
        err = {"class": "opene.exceptions.ItemConflictError",
               "message": msg,
               "url": url}

        resp = {'data': None,
                'error': err,
                'code': 409}

        jrest.rproxy.pool_request.return_value = resp
        attach_target_vol_expected += [
            mock.call('POST', addr, json_data=jbody)]
        self.assertRaises(jexc.JDSSResourceExistsException,
                          jrest.attach_target_vol, tname, vname)

        # no such target
        url = 'http://85.14.118.246:11582/api/v3/pools/Pool-0/{}'.format(addr)
        msg = 'Target {} not exists.'.format(vname)
        err = {"class": "opene.exceptions.ItemNotFoundError",
               "message": msg,
               "url": url}

        resp = {'data': None,
                'error': err,
                'code': 404}

        jrest.rproxy.pool_request.return_value = resp
        attach_target_vol_expected += [
            mock.call('POST', addr, json_data=jbody)]
        self.assertRaises(jexc.JDSSResourceNotFoundException,
                          jrest.attach_target_vol, tname, vname)

        # error unknown
        url = 'http://85.14.118.246:11582/api/v3/pools/Pool-0/{}'.format(addr)
        msg = 'Target {} not exists.'.format(vname)

        err = {"class": "some test error",
               "message": "test error message",
               "url": url,
               "errno": 123}

        resp = {'data': None,
                'error': err,
                'code': 500}

        jrest.rproxy.pool_request.return_value = resp
        attach_target_vol_expected += [
            mock.call('POST', addr, json_data=jbody)]
        self.assertRaises(jexc.JDSSException,
                          jrest.attach_target_vol, tname, vname)
        jrest.rproxy.pool_request.assert_has_calls(attach_target_vol_expected)

    def test_detach_target_vol(self):

        jrest, ctx = self.get_rest(CONFIG_OK)
        # detach target vol ok
        tname = CONFIG_OK['iscsi_target_prefix'] + UUID_1
        vname = jcom.vname(UUID_1)

        addr = '/san/iscsi/targets/{tar}/luns/{vol}'.format(
            tar=tname, vol=vname)

        resp = {'data': None,
                'error': None,
                'code': 204}

        jrest.rproxy.pool_request.return_value = resp
        detach_target_vol_expected = [
            mock.call('DELETE', addr)]
        self.assertIsNone(jrest.detach_target_vol(tname, vname))

        # no such target
        url = 'http://85.14.118.246:11582/api/v3/pools/Pool-0/{}'.format(addr)
        msg = 'Target {} not exists.'.format(vname)
        err = {"class": "opene.exceptions.ItemNotFoundError",
               "message": msg,
               "url": url}

        resp = {'data': None,
                'error': err,
                'code': 404}

        jrest.rproxy.pool_request.return_value = resp
        detach_target_vol_expected += [
            mock.call('DELETE', addr)]
        self.assertRaises(jexc.JDSSResourceNotFoundException,
                          jrest.detach_target_vol, tname, vname)

        # error unknown
        url = 'http://85.14.118.246:11582/api/v3/pools/Pool-0/{}'.format(addr)
        msg = 'Target {} not exists.'.format(vname)

        err = {"class": "some test error",
               "message": "test error message",
               "url": url,
               "errno": 125}

        resp = {'data': None,
                'error': err,
                'code': 500}

        jrest.rproxy.pool_request.return_value = resp
        detach_target_vol_expected += [
            mock.call('DELETE', addr)]
        self.assertRaises(jexc.JDSSException,
                          jrest.detach_target_vol, tname, vname)
        jrest.rproxy.pool_request.assert_has_calls(detach_target_vol_expected)

    def test_create_snapshot(self):

        jrest, ctx = self.get_rest(CONFIG_OK)
        vname = jcom.vname(UUID_1)
        sname = jcom.sname(UUID_2)

        data = {'name': jcom.sname(UUID_2)}
        resp = {'data': data,
                'error': None,
                'code': 201}

        jrest.rproxy.pool_request.return_value = resp
        self.assertIsNone(jrest.create_snapshot(vname, sname))

    def test_create_snapshot_exception(self):

        jrest, ctx = self.get_rest(CONFIG_OK)
        vname = jcom.vname(UUID_1)
        sname = jcom.sname(UUID_2)

        addr = '/volumes/{vol}/snapshots'.format(vol=vname)
        req = {'snapshot_name': sname}

        url = ('http://192.168.0.2:82/api/v3/pools/Pool-0/volumes/{vol}/'
               'snapshots').format(vol=UUID_1)
        resp = {'data': None,
                'error': {
                    'class': "zfslib.zfsapi.resources.ZfsResourceError",
                    'errno': 1,
                    'message': ('Zfs resource: Pool-0/{vol} not found in '
                                'this collection.'.format(vol=vname)),
                    "url": url},
                'code': 500}

        jrest.rproxy.pool_request.return_value = resp
        create_snapshot_expected = [
            mock.call('POST', addr, json_data=req)]

        self.assertRaises(jexc.JDSSVolumeNotFoundException,
                          jrest.create_snapshot,
                          vname,
                          sname)

        # snapshot exists
        resp = {'data': None,
                'error': {
                    'class': "zfslib.zfsapi.resources.ZfsResourceError",
                    'errno': 5,
                    'message': 'Resource Pool-0/{vol}@{snap} already exists.',
                    'url': url},
                'code': 500}

        jrest.rproxy.pool_request.return_value = resp
        create_snapshot_expected += [mock.call('POST', addr, json_data=req)]
        self.assertRaises(jexc.JDSSSnapshotExistsException,
                          jrest.create_snapshot,
                          vname,
                          sname)

        # error unknown
        err = {"class": "some test error",
               "message": "test error message",
               "url": url,
               "errno": 123}

        resp = {'data': None,
                'error': err,
                'code': 500}

        jrest.rproxy.pool_request.return_value = resp
        create_snapshot_expected += [mock.call('POST', addr, json_data=req)]
        self.assertRaises(jexc.JDSSException,
                          jrest.create_snapshot,
                          vname,
                          sname)
        jrest.rproxy.pool_request.assert_has_calls(create_snapshot_expected)

    def test_create_volume_from_snapshot(self):

        jrest, ctx = self.get_rest(CONFIG_OK)
        vname = jcom.vname(UUID_1)
        sname = jcom.sname(UUID_2)
        cname = jcom.vname(UUID_3)

        addr = '/volumes/{vol}/clone'.format(vol=vname)
        jbody = {
            'name': cname,
            'snapshot': sname,
            'sparse': False
        }

        data = {
            "origin": "Pool-0/{vol}@{snap}".format(vol=vname, snap=sname),
            "is_clone": True,
            "full_name": "Pool-0/{}".format(cname),
            "name": cname
        }

        resp = {'data': data,
                'error': None,
                'code': 201}

        jrest.rproxy.pool_request.return_value = resp
        create_volume_from_snapshot_expected = [
            mock.call('POST', addr, json_data=jbody)]
        self.assertIsNone(jrest.create_volume_from_snapshot(cname,
                                                            sname,
                                                            vname))

        jrest.rproxy.pool_request.assert_has_calls(
            create_volume_from_snapshot_expected)

    def test_create_volume_from_snapshot_exception(self):

        jrest, ctx = self.get_rest(CONFIG_OK)
        vname = jcom.vname(UUID_1)
        sname = jcom.sname(UUID_2)
        cname = jcom.vname(UUID_3)

        addr = '/volumes/{vol}/clone'.format(vol=vname)
        jbody = {
            'name': cname,
            'snapshot': sname,
            'sparse': False
        }

        # volume DNE
        url = ('http://192.168.0.2:82/api/v3/pools/Pool-0/volumes/{vol}/'
               'clone').format(vol=UUID_1)
        resp = {'data': None,
                'error': {
                    'class': "zfslib.zfsapi.resources.ZfsResourceError",
                    'errno': 1,
                    'message': ('Zfs resource: Pool-0/{vol} not found in '
                                'this collection.'.format(vol=vname)),
                    "url": url},
                'code': 500}

        jrest.rproxy.pool_request.return_value = resp
        create_volume_from_snapshot_expected = [
            mock.call('POST', addr, json_data=jbody)]

        self.assertRaises(jexc.JDSSResourceNotFoundException,
                          jrest.create_volume_from_snapshot,
                          cname,
                          sname,
                          vname)

        # clone exists
        resp = {'data': None,
                'error': {
                    "class": "zfslib.wrap.zfs.ZfsCmdError",
                    "errno": 100,
                    "message": ("cannot create 'Pool-0/{}': "
                                "dataset already exists").format(vname),
                    'url': url},
                'code': 500}

        jrest.rproxy.pool_request.return_value = resp
        create_volume_from_snapshot_expected += [
            mock.call('POST', addr, json_data=jbody)]
        self.assertRaises(jexc.JDSSResourceExistsException,
                          jrest.create_volume_from_snapshot,
                          cname,
                          sname,
                          vname)

        # error unknown
        err = {"class": "some test error",
               "message": "test error message",
               "url": url,
               "errno": 123}

        resp = {'data': None,
                'error': err,
                'code': 500}

        jrest.rproxy.pool_request.return_value = resp
        create_volume_from_snapshot_expected += [
            mock.call('POST', addr, json_data=jbody)]
        self.assertRaises(jexc.JDSSException,
                          jrest.create_volume_from_snapshot,
                          cname,
                          sname,
                          vname)
        jrest.rproxy.pool_request.assert_has_calls(
            create_volume_from_snapshot_expected)

    def test_rollback_volume_to_snapshot(self):

        jrest, ctx = self.get_rest(CONFIG_OK)
        vname = jcom.vname(UUID_1)
        sname = jcom.sname(UUID_2)

        req = ('/volumes/{vol}/snapshots/'
               '{snap}/rollback').format(vol=vname, snap=sname)

        resp = {'data': None,
                'error': None,
                'code': 200}

        jrest.rproxy.pool_request.return_value = resp
        rollback_volume_to_snapshot_expected = [
            mock.call('POST', req)]
        self.assertIsNone(jrest.rollback_volume_to_snapshot(vname, sname))

        jrest.rproxy.pool_request.assert_has_calls(
            rollback_volume_to_snapshot_expected)

    def test_rollback_volume_to_snapshot_exception(self):

        jrest, ctx = self.get_rest(CONFIG_OK)
        vname = jcom.vname(UUID_1)
        sname = jcom.sname(UUID_2)

        req = ('/volumes/{vol}/snapshots/'
               '{snap}/rollback').format(vol=vname,
                                         snap=sname)

        # volume DNE
        msg = ('Zfs resource: Pool-0/{vname}'
               ' not found in this collection.').format(vname=vname)

        url = ('http://192.168.0.2:82/api/v3/pools/Pool-0/volumes/{vol}/'
               'snapshots/{snap}/rollback').format(vol=vname, snap=sname)
        err = {"class": "zfslib.zfsapi.resources.ZfsResourceError",
               "message": msg,
               "url": url,
               "errno": 123}

        resp = {'data': None,
                'error': err,
                'code': 500}

        jrest.rproxy.pool_request.return_value = resp
        rollback_volume_to_snapshot_expected = [
            mock.call('POST', req)]
        self.assertRaises(jexc.JDSSException,
                          jrest.rollback_volume_to_snapshot,
                          vname,
                          sname)
        jrest.rproxy.pool_request.assert_has_calls(
            rollback_volume_to_snapshot_expected)

        # error unknown
        err = {"class": "some test error",
               "message": "test error message",
               "url": url,
               "errno": 123}

        resp = {'data': None,
                'error': err,
                'code': 500}

        jrest.rproxy.pool_request.return_value = resp
        rollback_volume_to_snapshot_expected += [
            mock.call('POST', req)]
        self.assertRaises(jexc.JDSSException,
                          jrest.rollback_volume_to_snapshot,
                          vname,
                          sname)
        jrest.rproxy.pool_request.assert_has_calls(
            rollback_volume_to_snapshot_expected)

    def test_delete_snapshot(self):

        jrest, ctx = self.get_rest(CONFIG_OK)
        vname = jcom.vname(UUID_1)
        sname = jcom.sname(UUID_2)

        addr = '/volumes/{vol}/snapshots/{snap}'.format(vol=vname, snap=sname)

        jbody = {
            'recursively_children': True,
            'recursively_dependents': True,
            'force_umount': True
        }

        resp = {'data': None,
                'error': None,
                'code': 204}

        jrest.rproxy.pool_request.return_value = resp
        delete_snapshot_expected = [mock.call('DELETE', addr)]
        self.assertIsNone(jrest.delete_snapshot(vname, sname))

        delete_snapshot_expected += [
            mock.call('DELETE', addr, json_data=jbody)]
        self.assertIsNone(jrest.delete_snapshot(vname,
                                                sname,
                                                recursively_children=True,
                                                recursively_dependents=True,
                                                force_umount=True))

        jrest.rproxy.pool_request.assert_has_calls(delete_snapshot_expected)

    def test_delete_snapshot_exception(self):

        jrest, ctx = self.get_rest(CONFIG_OK)
        vname = jcom.vname(UUID_1)
        sname = jcom.sname(UUID_2)
        cname = jcom.sname(UUID_3)

        addr = '/volumes/{vol}/snapshots/{snap}'.format(vol=vname, snap=sname)

        # snapshot busy
        url = ('http://192.168.0.2:82/api/v3/pools/Pool-0/volumes/{vol}/'
               'snapshots/{snap}').format(vol=vname, snap=sname)
        msg = ('cannot destroy "Pool-0/{vol}@{snap}": snapshot has dependent '
               'clones use "-R" to destroy the following datasets: '
               'Pool-0/{clone}').format(vol=vname, snap=sname, clone=cname)
        err = {'class': 'zfslib.wrap.zfs.ZfsCmdError',
               'message': msg,
               'url': url,
               'errno': 1000}

        resp = {'data': None,
                'error': err,
                'code': 500}

        jrest.rproxy.pool_request.return_value = resp
        delete_snapshot_expected = [
            mock.call('DELETE', addr)]

        self.assertRaises(jexc.JDSSSnapshotIsBusyException,
                          jrest.delete_snapshot,
                          vname,
                          sname)

        # error unknown
        err = {"class": "some test error",
               "message": "test error message",
               "url": url,
               "errno": 123}

        resp = {'data': None,
                'error': err,
                'code': 500}

        jrest.rproxy.pool_request.return_value = resp
        delete_snapshot_expected += [mock.call('DELETE', addr)]
        self.assertRaises(jexc.JDSSException,
                          jrest.delete_snapshot, vname, sname)

        jrest.rproxy.pool_request.assert_has_calls(delete_snapshot_expected)

    def test_get_snapshots(self):

        jrest, ctx = self.get_rest(CONFIG_OK)
        vname = jcom.vname(UUID_1)

        addr = '/volumes/{vol}/snapshots'.format(vol=vname)

        data = {"results": 2,
                "entries": {"referenced": "65536",
                            "name": jcom.sname(UUID_2),
                            "defer_destroy": "off",
                            "userrefs": "0",
                            "primarycache": "all",
                            "type": "snapshot",
                            "creation": "2015-5-27 16:8:35",
                            "refcompressratio": "1.00x",
                            "compressratio": "1.00x",
                            "written": "65536",
                            "used": "0",
                            "clones": "",
                            "mlslabel": "none",
                            "secondarycache": "all"}}

        resp = {'data': data,
                'error': None,
                'code': 200}

        jrest.rproxy.pool_request.return_value = resp
        get_snapshots_expected = [mock.call('GET', addr)]
        self.assertEqual(data['entries'], jrest.get_snapshots(vname))

        jrest.rproxy.pool_request.assert_has_calls(get_snapshots_expected)

    def test_get_snapshots_exception(self):

        jrest, ctx = self.get_rest(CONFIG_OK)
        vname = jcom.vname(UUID_1)

        addr = '/volumes/{vol}/snapshots'.format(vol=vname)

        url = ('http://192.168.0.2:82/api/v3/pools/Pool-0/volumes/{vol}/'
               'snapshots').format(vol=vname)

        err = {"class": "zfslib.zfsapi.resources.ZfsResourceError",
               "message": ('Zfs resource: Pool-0/{vol} not found in '
                           'this collection.').format(vol=vname),
               "url": url,
               "errno": 1}

        resp = {'data': None,
                'error': err,
                'code': 500}

        jrest.rproxy.pool_request.return_value = resp
        get_snapshots_expected = [mock.call('GET', addr)]
        self.assertRaises(jexc.JDSSResourceNotFoundException,
                          jrest.get_snapshots,
                          vname)

        # error unknown
        err = {"class": "some test error",
               "message": "test error message",
               "url": url,
               "errno": 123}

        resp = {'data': None,
                'error': err,
                'code': 500}

        jrest.rproxy.pool_request.return_value = resp
        get_snapshots_expected += [
            mock.call('GET', addr)]
        self.assertRaises(jexc.JDSSException, jrest.get_snapshots, vname)

        jrest.rproxy.pool_request.assert_has_calls(get_snapshots_expected)

    def test_get_pool_stats(self):

        jrest, ctx = self.get_rest(CONFIG_OK)

        addr = ''

        data = {"available": "950040707072",
                "status": 26,
                "name": "Pool-0",
                "scan": None,
                "encryption": {"enabled": False},
                "iostats": {
                    "read": "0",
                    "write": "0",
                    "chksum": "0"},
                "vdevs": [{"name": "wwn-0x5000cca3a8cddb2f",
                           "iostats": {"read": "0",
                                       "write": "0",
                                       "chksum": "0"},
                           "disks": [{"origin": "local",
                                      "led": "off",
                                      "name": "sdc",
                                      "iostats": {"read": "0",
                                                  "write": "0",
                                                  "chksum": "0"},
                                      "health": "ONLINE",
                                      "sn": "JPW9K0N20ZGXWE",
                                      "path": None,
                                      "model": "Hitachi HUA72201",
                                      "id": "wwn-0x5000cca3a8cddb2f",
                                      "size": 1000204886016}],
                           "health": "ONLINE",
                           "vdev_replacings": [],
                           "vdev_spares": [],
                           "type": ""}],
                "health": "ONLINE",
                "operation": "none",
                "id": "12413634663904564349",
                "size": "996432412672"}

        resp = {'data': data,
                'error': None,
                'code': 200}

        jrest.rproxy.pool_request.return_value = resp
        get_pool_stats_expected = [mock.call('GET', addr)]
        self.assertEqual(data, jrest.get_pool_stats())

        jrest.rproxy.pool_request.assert_has_calls(get_pool_stats_expected)

    def test_get_pool_stats_exception(self):

        jrest, ctx = self.get_rest(CONFIG_OK)

        addr = ''

        url = 'http://192.168.0.2:82/api/v3/pools/Pool-0/'

        err = {'class': 'zfslib.zfsapi.zpool.ZpoolError',
               'message': "Given zpool 'Pool-0' doesn't exists.",
               "url": url,
               "errno": 1}

        resp = {'data': None,
                'error': err,
                'code': 500}

        jrest.rproxy.pool_request.return_value = resp
        get_pool_stats_expected = [mock.call('GET', addr)]
        self.assertRaises(jexc.JDSSException, jrest.get_pool_stats)

        jrest.rproxy.pool_request.assert_has_calls(get_pool_stats_expected)
