# Copyright 2015 Datera
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

import mock
from oslo_log import log as logging

from cinder import context
from cinder import exception
from cinder import test
from cinder.volume import configuration as conf
from cinder.volume.drivers import datera


LOG = logging.getLogger(__name__)


class DateraVolumeTestCase(test.TestCase):
    def setUp(self):
        super(DateraVolumeTestCase, self).setUp()

        self.cfg = mock.Mock(spec=conf.Configuration)
        self.cfg.san_ip = '127.0.0.1'
        self.cfg.san_is_local = True
        self.cfg.datera_api_token = 'secret'
        self.cfg.datera_api_port = '7717'
        self.cfg.datera_api_version = '1'
        self.cfg.datera_num_replicas = '2'
        self.cfg.san_login = 'user'
        self.cfg.san_password = 'pass'

        mock_exec = mock.Mock()
        mock_exec.return_value = ('', '')

        self.driver = datera.DateraDriver(execute=mock_exec,
                                          configuration=self.cfg)
        self.driver.set_initialized()
        self.volume = _stub_volume()
        self.api_patcher = mock.patch('cinder.volume.drivers.datera.'
                                      'DateraDriver._issue_api_request')
        self.mock_api = self.api_patcher.start()

        self.addCleanup(self.api_patcher.stop)

    def test_volume_create_success(self):
        self.mock_api.return_value = {
            'uuid': 'c20aba21-6ef6-446b-b374-45733b4883ba',
            'size': '1073741824',
            'name': 'volume-00000001',
            'parent': '00000000-0000-0000-0000-000000000000',
            'numReplicas': '2',
            'subType': 'IS_ORIGINAL'
        }
        self.assertIsNone(self.driver.create_volume(self.volume))

    def test_volume_create_fails(self):
        self.mock_api.side_effect = exception.DateraAPIException
        self.assertRaises(exception.DateraAPIException,
                          self.driver.create_volume, self.volume)

    def test_create_cloned_volume_success(self):
        self.mock_api.return_value = {
            'uuid': 'c20aba21-6ef6-446b-b374-45733b4883ba',
            'size': '1073741824',
            'name': 'volume-00000001',
            'parent': '7f91abfa-7964-41ed-88fc-207c3a290b4f',
            'numReplicas': '2',
            'subType': 'IS_CLONE'
        }
        source_volume = _stub_volume(
            id='7f91abfa-7964-41ed-88fc-207c3a290b4f',
            display_name='foo'
        )
        self.assertIsNone(self.driver.create_cloned_volume(self.volume,
                                                           source_volume))

    def test_create_cloned_volume_fails(self):
        self.mock_api.side_effect = exception.DateraAPIException
        source_volume = _stub_volume(
            id='7f91abfa-7964-41ed-88fc-207c3a290b4f',
            display_name='foo'
        )
        self.assertRaises(exception.DateraAPIException,
                          self.driver.create_cloned_volume, self.volume,
                          source_volume)

    def test_delete_volume_success(self):
        self.mock_api.return_value = {
            'uuid': 'c20aba21-6ef6-446b-b374-45733b4883ba',
            'size': '1073741824',
            'name': 'volume-00000001',
            'parent': '00000000-0000-0000-0000-000000000000',
            'numReplicas': '2',
            'subType': 'IS_ORIGINAL',
            'target': None
        }
        self.assertIsNone(self.driver.delete_volume(self.volume))

    def test_delete_volume_not_found(self):
        self.mock_api.side_effect = exception.NotFound
        self.assertIsNone(self.driver.delete_volume(self.volume))

    def test_delete_volume_fails(self):
        self.mock_api.side_effect = exception.DateraAPIException
        self.assertRaises(exception.DateraAPIException,
                          self.driver.delete_volume, self.volume)

    def test_ensure_export_success(self):
        self.mock_api.return_value = stub_export
        ctxt = context.get_admin_context()
        expected = {
            'provider_location': u'172.28.121.10:3260 iqn.2013-05.com.daterain'
                                 'c::01:sn:fc372bc0490b2dbe 1'
        }
        self.assertEqual(expected, self.driver.ensure_export(ctxt,
                                                             self.volume))

    def test_ensure_export_fails(self):
        self.mock_api.side_effect = exception.DateraAPIException
        ctxt = context.get_admin_context()
        self.assertRaises(exception.DateraAPIException,
                          self.driver.ensure_export, ctxt, self.volume)

    def test_create_export_success(self):
        self.mock_api.return_value = stub_export
        ctxt = context.get_admin_context()
        expected = {
            'provider_location': u'172.28.121.10:3260 iqn.2013-05.com.daterain'
                                 'c::01:sn:fc372bc0490b2dbe 1'
        }
        self.assertEqual(expected, self.driver.create_export(ctxt,
                                                             self.volume))

    def test_create_export_fails(self):
        self.mock_api.side_effect = exception.DateraAPIException
        ctxt = context.get_admin_context()
        self.assertRaises(exception.DateraAPIException,
                          self.driver.create_export, ctxt, self.volume)

    def test_detach_volume_success(self):
        self.mock_api.return_value = {}
        ctxt = context.get_admin_context()
        volume = _stub_volume(status='in-use')
        self.assertIsNone(self.driver.detach_volume(ctxt, volume))

    def test_detach_volume_fails(self):
        self.mock_api.side_effect = exception.DateraAPIException
        ctxt = context.get_admin_context()
        volume = _stub_volume(status='in-use')
        self.assertRaises(exception.DateraAPIException,
                          self.driver.detach_volume, ctxt, volume)

    def test_detach_volume_not_found(self):
        self.mock_api.side_effect = exception.NotFound
        ctxt = context.get_admin_context()
        volume = _stub_volume(status='in-use')
        self.assertIsNone(self.driver.detach_volume(ctxt, volume))

    def test_create_snapshot_success(self):
        self.mock_api.return_value = {
            u'uuid': u'0bb34f0c-fea4-48e0-bf96-591120ac7e3c',
            u'parent': u'c20aba21-6ef6-446b-b374-45733b4883ba',
            u'subType': u'IS_SNAPSHOT',
            u'numReplicas': 2,
            u'size': u'1073741824',
            u'name': u'snapshot-00000001'
        }
        snapshot = _stub_snapshot(volume_id=self.volume['id'])
        self.assertIsNone(self.driver.create_snapshot(snapshot))

    def test_create_snapshot_fails(self):
        self.mock_api.side_effect = exception.DateraAPIException
        snapshot = _stub_snapshot(volume_id=self.volume['id'])
        self.assertRaises(exception.DateraAPIException,
                          self.driver.create_snapshot, snapshot)

    def test_delete_snapshot_success(self):
        self.mock_api.return_value = {
            u'uuid': u'0bb34f0c-fea4-48e0-bf96-591120ac7e3c',
            u'parent': u'c20aba21-6ef6-446b-b374-45733b4883ba',
            u'subType': u'IS_SNAPSHOT',
            u'numReplicas': 2,
            u'size': u'1073741824',
            u'name': u'snapshot-00000001'
        }
        snapshot = _stub_snapshot(volume_id=self.volume['id'])
        self.assertIsNone(self.driver.delete_snapshot(snapshot))

    def test_delete_snapshot_not_found(self):
        self.mock_api.side_effect = exception.NotFound
        snapshot = _stub_snapshot(self.volume['id'])
        self.assertIsNone(self.driver.delete_snapshot(snapshot))

    def test_delete_snapshot_fails(self):
        self.mock_api.side_effect = exception.DateraAPIException
        snapshot = _stub_snapshot(volume_id=self.volume['id'])
        self.assertRaises(exception.DateraAPIException,
                          self.driver.delete_snapshot, snapshot)

    def test_create_volume_from_snapshot_success(self):
        self.mock_api.return_value = {
            u'uuid': u'c20aba21-6ef6-446b-b374-45733b4883ba',
            u'parent': u'0bb34f0c-fea4-48e0-bf96-591120ac7e3c',
            u'subType': u'IS_ORIGINAL',
            u'numReplicas': 2,
            u'size': u'1073741824',
            u'name': u'volume-00000001'
        }
        snapshot = _stub_snapshot(volume_id=self.volume['id'])
        self.assertIsNone(
            self.driver.create_volume_from_snapshot(self.volume, snapshot))

    def test_create_volume_from_snapshot_fails(self):
        self.mock_api.side_effect = exception.DateraAPIException
        snapshot = _stub_snapshot(volume_id=self.volume['id'])
        self.assertRaises(exception.DateraAPIException,
                          self.driver.create_volume_from_snapshot, self.volume,
                          snapshot)

    def test_extend_volume_success(self):
        self.mock_api.return_value = {
            u'uuid': u'c20aba21-6ef6-446b-b374-45733b4883ba',
            u'parent': u'00000000-0000-0000-0000-000000000000',
            u'subType': u'IS_ORIGINAL',
            u'numReplicas': 2,
            u'size': u'2147483648',
            u'name': u'volume-00000001'
        }
        volume = _stub_volume(size=1)
        self.assertIsNone(self.driver.extend_volume(volume, 2))

    def test_extend_volume_fails(self):
        self.mock_api.side_effect = exception.DateraAPIException
        volume = _stub_volume(size=1)
        self.assertRaises(exception.DateraAPIException,
                          self.driver.extend_volume, volume, 2)

    def test_login_successful(self):
        self.mock_api.return_value = {
            'key': 'dd2469de081346c28ac100e071709403'
        }
        self.assertIsNone(self.driver._login())
        self.assertEqual(1, self.mock_api.call_count)

    def test_login_unsuccessful(self):
        self.mock_api.side_effect = exception.NotAuthorized
        self.assertRaises(exception.NotAuthorized, self.driver._login)
        self.assertEqual(1, self.mock_api.call_count)

stub_export = {
    '_ipColl': ['172.28.121.10'],
    'active_servers': {'44454c4c-4d00-1048-8031-b4c04f4d4e31': True},
    'auth': {
        'atype': 'T_AUTH_NONE',
        'info': {
            'mpassword': '',
            'muserid': '',
            'password': '',
            'userid': ''
        }
    },
    'endpoint_addrs': {'172.28.121.10': True},
    'endpoint_idents': {
        'iqn.2013-05.com.daterainc::01:sn:fc372bc0490b2dbe': True},
    'name': 'OpenStack-a4e692e8-7f95-4f87-8fe6-cbcbab624012',
    'server_allocation': 'TS_ALLOC_COMPLETED',
    'servers': {'44454c4c-4d00-1048-8031-b4c04f4d4e31': True},
    'targetIds': {
        u'4594953e-f97f-e111-ad85-001e6738c0f0': {
            u'ids': [{
                u'dev': None,
                u'id': u'iqn.2013-05.com.daterainc::01:sn:fc372bc0490b2dbe'
            }]
        }
    },
    'target_allocation': 'TS_ALLOC_COMPLETED',
    'target_ids': {'44454c4c-4d00-1048-8031-b4c04f4d4e31': True},
    'type': 'iscsi',
    'uuid': 'f11c2386-71d4-4352-a718-71c3e22f5888',
    'volumes': {'a4e692e8-7f95-4f87-8fe6-cbcbab624012': True}
}


def _stub_volume(*args, **kwargs):
    uuid = u'c20aba21-6ef6-446b-b374-45733b4883ba'
    name = u'volume-00000001'
    size = 1
    volume = {}
    volume['id'] = kwargs.get('id', uuid)
    volume['display_name'] = kwargs.get('display_name', name)
    volume['size'] = kwargs.get('size', size)
    volume['provider_location'] = kwargs.get('provider_location', None)
    return volume


def _stub_snapshot(*args, **kwargs):
    uuid = u'0bb34f0c-fea4-48e0-bf96-591120ac7e3c'
    name = u'snapshot-00000001'
    volume = {}
    volume['id'] = kwargs.get('id', uuid)
    volume['display_name'] = kwargs.get('display_name', name)
    volume['volume_id'] = kwargs.get('volume_id', None)
    return volume
