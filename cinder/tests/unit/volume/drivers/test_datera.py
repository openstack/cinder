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

from cinder import context
from cinder import exception
from cinder import test
from cinder.volume import configuration as conf
from cinder.volume.drivers import datera
from cinder.volume import volume_types


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
            u'status': u'available',
            u'name': u'volume-00000001',
            u'parent': u'00000000-0000-0000-0000-000000000000',
            u'uuid': u'c20aba21-6ef6-446b-b374-45733b4883ba',
            u'snapshots': {},
            u'targets': {},
            u'num_replicas': u'2',
            u'sub_type': u'IS_ORIGINAL',
            u'size': u'1073741824'
        }
        self.assertIsNone(self.driver.create_volume(self.volume))

    def test_volume_create_fails(self):
        self.mock_api.side_effect = exception.DateraAPIException
        self.assertRaises(exception.DateraAPIException,
                          self.driver.create_volume, self.volume)

    def test_volume_create_delay(self):
        """Verify after 1st retry volume becoming available is a success."""

        def _progress_api_return(mock_api):
            if mock_api.retry_count == 1:
                return {
                    u'status': u'unavailable',
                    u'name': u'test',
                    u'parent': u'00000000-0000-0000-0000-000000000000',
                    u'uuid': u'9c1666fe-4f1a-4891-b33d-e710549527fe',
                    u'snapshots': {},
                    u'targets': {},
                    u'num_replicas': u'2',
                    u'sub_type': u'IS_ORIGINAL',
                    u'size': u'1073741824'
                }
            else:
                self.mock_api.retry_count += 1
                return {
                    u'status': u'available',
                    u'name': u'test',
                    u'parent': u'00000000-0000-0000-0000-000000000000',
                    u'uuid': u'9c1666fe-4f1a-4891-b33d-e710549527fe',
                    u'snapshots': {},
                    u'targets': {},
                    u'num_replicas': u'2',
                    u'sub_type': u'IS_ORIGINAL',
                    u'size': u'1073741824'
                }

        self.mock_api.retry_count = 0
        self.mock_api.return_value = _progress_api_return(self.mock_api)
        self.assertEqual(1, self.mock_api.retry_count)
        self.assertIsNone(self.driver.create_volume(self.volume))

    @mock.patch.object(volume_types, 'get_volume_type')
    def test_create_volume_with_extra_specs(self, mock_get_type):
        self.mock_api.return_value = {
            u'status': u'available',
            u'name': u'volume-00000001',
            u'parent': u'00000000-0000-0000-0000-000000000000',
            u'uuid': u'c20aba21-6ef6-446b-b374-45733b4883ba',
            u'snapshots': {},
            u'targets': {},
            u'num_replicas': u'2',
            u'sub_type': u'IS_ORIGINAL',
            u'size': u'1073741824'
        }

        mock_get_type.return_value = {
            'name': u'The Best',
            'qos_specs_id': None,
            'deleted': False,
            'created_at': '2015-08-14 04:18:11',
            'updated_at': None,
            'extra_specs': {
                u'volume_backend_name': u'datera',
                u'qos:max_iops_read': u'2000',
                u'qos:max_iops_write': u'4000',
                u'qos:max_iops_total': u'4000'
            },
            'is_public': True,
            'deleted_at': None,
            'id': u'dffb4a83-b8fb-4c19-9f8c-713bb75db3b1',
            'description': None
        }

        mock_volume = _stub_volume(
            volume_type_id='dffb4a83-b8fb-4c19-9f8c-713bb75db3b1'
        )

        assert_body = {
            u'max_iops_read': u'2000',
            'numReplicas': '2',
            'uuid': u'c20aba21-6ef6-446b-b374-45733b4883ba',
            'size': '1073741824',
            u'max_iops_write': u'4000',
            u'max_iops_total': u'4000',
            'name': u'volume-00000001'
        }

        self.assertIsNone(self.driver.create_volume(mock_volume))
        self.mock_api.assert_called_once_with('volumes', 'post',
                                              body=assert_body)
        self.assertTrue(mock_get_type.called)

    def test_create_cloned_volume_success(self):
        self.mock_api.return_value = {
            'status': 'available',
            'uuid': 'c20aba21-6ef6-446b-b374-45733b4883ba',
            'size': '1073741824',
            'name': 'volume-00000001',
            'parent': '7f91abfa-7964-41ed-88fc-207c3a290b4f',
            'snapshots': {},
            'targets': {},
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
        self.mock_api.side_effect = self._generate_fake_api_request()
        ctxt = context.get_admin_context()
        expected = {
            'provider_location': '172.28.121.10:3260 iqn.2013-05.com.daterain'
                                 'c::01:sn:fc372bc0490b2dbe 0'
        }
        self.assertEqual(expected, self.driver.ensure_export(ctxt,
                                                             self.volume))

    def test_ensure_export_fails(self):
        self.mock_api.side_effect = exception.DateraAPIException
        ctxt = context.get_admin_context()
        self.assertRaises(exception.DateraAPIException,
                          self.driver.ensure_export, ctxt, self.volume)

    def test_create_export_target_does_not_exist_success(self):
        self.mock_api.side_effect = self._generate_fake_api_request(
            targets_exist=False)
        ctxt = context.get_admin_context()
        expected = {
            'provider_location': '172.28.121.10:3260 iqn.2013-05.com.daterainc'
                                 '::01:sn:fc372bc0490b2dbe 0'
        }

        self.assertEqual(expected, self.driver.create_export(ctxt,
                                                             self.volume,
                                                             {}))

    def test_create_export_fails(self):
        self.mock_api.side_effect = exception.DateraAPIException
        ctxt = context.get_admin_context()
        self.assertRaises(exception.DateraAPIException,
                          self.driver.create_export, ctxt, self.volume, {})

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
            u'status': u'available',
            u'uuid': u'0bb34f0c-fea4-48e0-bf96-591120ac7e3c',
            u'parent': u'c20aba21-6ef6-446b-b374-45733b4883ba',
            u'subType': u'IS_SNAPSHOT',
            u'snapshots': {},
            u'targets': {},
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
            u'status': u'available',
            u'uuid': u'c20aba21-6ef6-446b-b374-45733b4883ba',
            u'parent': u'0bb34f0c-fea4-48e0-bf96-591120ac7e3c',
            u'snapshots': {},
            u'targets': {},
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

    def _generate_fake_api_request(self, targets_exist=True):
        fake_volume = None
        if not targets_exist:
            fake_volume = _stub_datera_volume(targets={})
        else:
            fake_volume = _stub_datera_volume()

        def _fake_api_request(resource_type, method='get', resource=None,
                              body=None, action=None, sensitive=False):
            if resource_type == 'volumes' and action is None:
                return fake_volume
            elif resource_type == 'volume' and action == 'export':
                return stub_create_export
            elif resource_type == 'export_configs':
                return stub_get_export

        return _fake_api_request


stub_create_export = {
    u'_ipColl': [u'172.28.121.10', u'172.28.120.10'],
    u'active_initiators': [],
    u'activeServers': [u'4594953e-f97f-e111-ad85-001e6738c0f0'],
    u'admin_state': u'online',
    u'atype': u'none',
    u'creation_type': u'system_explicit',
    u'endpoint_addrs': [u'172.30.128.2'],
    u'endpoint_idents': [u'iqn.2013-05.com.daterainc::01:sn:fc372bc0490b2dbe'],
    u'initiators': [],
    u'name': u'OS-a8b4d666',
    u'server_allocation': u'TS_ALLOC_COMPLETED',

    u'servers': [u'4594953e-f97f-e111-ad85-001e6738c0f0'],
    u'targetIds': {
        u'4594953e-f97f-e111-ad85-001e6738c0f0': {
            u'ids': [{
                u'dev': None,
                u'id': u'iqn.2013-05.com.daterainc::01:sn:fc372bc0490b2dbe'
            }]
        }
    },

    u'target_allocation': u'TS_ALLOC_COMPLETED',
    u'type': u'iscsi',
    u'uuid': u'7071efd7-9f22-4996-8f68-47e9ab19d0fd',
    u'volumes': []
}

stub_get_export = {
    "uuid": "744e1bd8-d741-4919-86cd-806037d98c8a",
    "active_initiators": [],
    "active_servers": [
        "472764aa-584b-4c1d-a7b7-e50cf7f5518f"
    ],
    "endpoint_addrs": [
        "172.28.121.10",
        "172.28.120.10"
    ],
    "endpoint_idents": [
        "iqn.2013-05.com.daterainc::01:sn:fc372bc0490b2dbe"
    ],
    "initiators": [],
    "servers": [
        "472764aa-584b-4c1d-a7b7-e50cf7f5518f"
    ],
    "volumes": [
        "10305aa4-1343-4363-86fe-f49eb421a48c"
    ],
    "type": "iscsi",
    "creation_type": "system_explicit",
    "server_allocation": "TS_ALLOC_COMPLETED",
    "admin_state": "online",
    "target_allocation": "TS_ALLOC_COMPLETED",
    "atype": "none",
    "name": "OS-10305aa4",
    "targetIds": {
        "472764aa-584b-4c1d-a7b7-e50cf7f5518f": {
            "ids": [{
                "dev": "",
                "id": ("iqn.2013-05.com.daterainc::01:sn:fc372bc0490b2dbe")
            }]
        }
    }
}


def _stub_datera_volume(*args, **kwargs):
    return {
        "status": "available",
        "name": "test",
        "num_replicas": "2",
        "parent": "00000000-0000-0000-0000-000000000000",
        "size": "1024",
        "sub_type": "IS_ORIGINAL",
        "uuid": "10305aa4-1343-4363-86fe-f49eb421a48c",
        "snapshots": [],
        "snapshot_configs": [],
        "targets": [
            kwargs.get('targets', "744e1bd8-d741-4919-86cd-806037d98c8a"),
        ]
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
    volume['volume_type_id'] = kwargs.get('volume_type_id', None)
    return volume


def _stub_snapshot(*args, **kwargs):
    uuid = u'0bb34f0c-fea4-48e0-bf96-591120ac7e3c'
    name = u'snapshot-00000001'
    volume = {}
    volume['id'] = kwargs.get('id', uuid)
    volume['display_name'] = kwargs.get('display_name', name)
    volume['volume_id'] = kwargs.get('volume_id', None)
    return volume
