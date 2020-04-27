# Copyright (c) 2019 SandStone data Technologies Co., Ltd
# All Rights Reserved
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
"""Unittest for sds_client."""

import json
from unittest import mock

import requests

from cinder.tests.unit import test
from cinder.tests.unit.volume.drivers.sandstone import test_utils
from cinder.volume.drivers.sandstone import sds_client


class FakeSession(test_utils.FakeBaseSession):
    """Fake request session."""

    method_map = {
        'post': {
            'capacity': {'data': {'capacity_bytes': 1024, 'free_bytes': 1024}},
            'pool/list': {'data': [{'status': {'progress': 100},
                                    'pool_name': 'fake_pool',
                                    'realname': 'fake_pool',
                                    'storage_policy': 'fake_replicate',
                                    'domain_name': 'fake_domain',
                                    'pool_id': 3,
                                    'policy_type': 'replicated',
                                    'size': 2}]},
            'resource/initiator/list': {'data': {
                'results': [{'iqn': 'fake_iqn',
                             'type': 'iscsi'}]}},
            'resource/target/get_target_acl_list': {'data': {
                'results': [{'autodiscovery': 'yes',
                             'name': 'fake_iqn',
                             'approved': 'yes',
                             'manual': 'no',
                             'ip': ''}]}},
            'block/gateway/server/list': {'data': [{
                'networks': [{'hostid': 'node0001',
                              'address': '1.1.1.1',
                              'type': 'iSCSI'}]}]},
            'resource/target/list': {'data': {
                'results': [{'status': 'fake_state',
                             'node': ['node0001'],
                             'name': 'fake_target',
                             'type': 'iSCSI',
                             'gateway': [{
                                 'hostid': 'node0001',
                                 'networks': [{
                                     'hostid': 'node0001',
                                     'type': 'iSCSI',
                                     'address': 'fake_address'}],
                                 'hostip': 'fake_hostip'}]}]}},
            'resource/target/get_chap_list': {'data': [{
                'user': 'fake_chapuser',
                'level': 'level1'}]},
            'resource/target/get_luns': {'data': {
                'results': [{'lid': 1,
                             'name': 'fake_lun',
                             'pool_id': 1}]}},
            'resource/lun/list': {'data': {
                'results': [{'volumeName': 'fake_lun',
                             'pool_id': 1,
                             'capacity_bytes': 1024}]}},
            'delaytask/list': {'data': {
                'results': [{'status': 'completed',
                             'run_status': 'completed',
                             'executor': 'LunFlatten',
                             'progress': 100,
                             'parameter': {'pool_id': 1,
                                           'lun_name': 'fake_lun'}}]}},
            'resource/snapshot/list': {'data': {
                'results': [{'snapName': 'fake_snapshot',
                             'lunName': 'fake_lun'}]}},
        }
    }


class TestSdsclient(test.TestCase):
    """Testcase sds client."""

    def setUp(self):
        """Setup."""
        super(TestSdsclient, self).setUp()
        self.mock_object(requests, 'Session', FakeSession)
        self.client = sds_client.RestCmd('192.168.200.100',
                                         'fake_user',
                                         'fake_password',
                                         True)
        self.client.login()

    def test_login(self):
        """Test login and check headers."""
        self.assertEqual('https://192.168.200.100',
                         self.client.session.headers['Referer'])
        self.assertEqual('fake_token',
                         self.client.session.headers['X-XSRF-Token'])
        self.assertEqual('XSRF-TOKEN=fake_token; username=fake_user; '
                         'sdsom_sessionid=fake_session',
                         self.client.session.headers['Cookie'])

    def test_logout(self):
        """Test logout."""
        retval = self.client.logout()
        self.assertIsNone(retval)

    def test_query_capacity_info(self):
        """Test query cluster capacity."""
        with mock.patch.object(self.client.session, 'post',
                               wraps=self.client.session.post) as mocker:
            retval = self.client.query_capacity_info()
            mocker.assert_called_once_with(
                'https://192.168.200.100/api/storage/'
                'capacity')
            self.assertDictEqual({'capacity_bytes': 1024, 'free_bytes': 1024},
                                 retval)

    def test_query_pool_info(self):
        """Test query pool status."""
        with mock.patch.object(self.client.session, 'post',
                               wraps=self.client.session.post) as mocker:
            retval = self.client.query_pool_info()
            mocker.assert_called_once_with(
                'https://192.168.200.100/api/storage/'
                'pool/list')
            self.assertListEqual([{'status': {'progress': 100},
                                   'realname': 'fake_pool',
                                   'pool_name': 'fake_pool',
                                   'storage_policy': 'fake_replicate',
                                   'domain_name': 'fake_domain',
                                   'pool_id': 3,
                                   'policy_type': 'replicated',
                                   'size': 2}], retval)

    def test_create_initiator(self):
        """Test create initiator."""
        with mock.patch.object(self.client.session, 'post',
                               wraps=self.client.session.post) as mocker:
            retval = self.client.create_initiator(
                initiator_name='fake_iqn')
            data = json.dumps(
                {'iqn': 'fake_iqn', 'type': 'iSCSI',
                 'remark': 'Cinder iSCSI'})
            mocker.assert_called_with(
                'https://192.168.200.100/api/storage/'
                'resource/initiator/create', data=data)
            self.assertIsNone(retval)

    @mock.patch.object(sds_client.RestCmd,
                       "_judge_delaytask_status")
    def test_add_initiator_to_target(self,
                                     mock__judge_delaytask_status):
        """Test add initiator to target."""
        with mock.patch.object(self.client.session, 'post',
                               wraps=self.client.session.post) as mocker:
            mock__judge_delaytask_status.return_value = None
            retval = self.client.add_initiator_to_target(
                target_name='fake_target',
                initiator_name='fake_iqn')
            data = json.dumps(
                {'targetName': 'fake_target',
                 'iqns': [{'ip': '', 'iqn': 'fake_iqn'}]})
            mocker.assert_called_with(
                'https://192.168.200.100/api/storage/'
                'resource/target/add_initiator_to_target', data=data)
            self.assertIsNone(retval)

    def test_query_initiator_by_name(self):
        """Test query initiator exist or not."""
        with mock.patch.object(self.client.session, 'post',
                               wraps=self.client.session.post) as mocker:
            retval = self.client.query_initiator_by_name(
                initiator_name='fake_iqn')
            data = json.dumps(
                {'initiatorMark': '', 'pageno': 1,
                 'pagesize': 1000, 'type': 'iSCSI'})
            mocker.assert_called_once_with(
                'https://192.168.200.100/api/storage/'
                'resource/initiator/list', data=data)
            self.assertDictEqual({'iqn': 'fake_iqn',
                                  'type': 'iscsi'}, retval)

    def test_query_target_initiatoracl(self):
        """Test query target related initiator info."""
        with mock.patch.object(self.client.session, 'post',
                               wraps=self.client.session.post) as mocker:
            retval = self.client.query_target_initiatoracl(
                target_name='fake_target',
                initiator_name='fake_iqn')
            data = json.dumps(
                {'pageno': 1, 'pagesize': 1000,
                 'targetName': 'fake_target'})
            mocker.assert_called_once_with(
                'https://192.168.200.100/api/storage/'
                'resource/target/get_target_acl_list', data=data)
            self.assertListEqual([{'autodiscovery': 'yes',
                                   'name': 'fake_iqn',
                                   'approved': 'yes',
                                   'manual': 'no',
                                   'ip': ''}], retval)

    def test_query_node_by_targetips(self):
        """Test query node id and node ip, relation dict."""
        with mock.patch.object(self.client.session, 'post',
                               wraps=self.client.session.post) as mocker:
            retval = self.client.query_node_by_targetips(
                target_ips=['1.1.1.1'])
            mocker.assert_called_once_with(
                'https://192.168.200.100/api/storage/'
                'block/gateway/server/list')
            self.assertDictEqual({'1.1.1.1': 'node0001'}, retval)

    def test_query_target_by_name(self):
        """Test query target exist or not."""
        with mock.patch.object(self.client.session, 'post',
                               wraps=self.client.session.post) as mocker:
            retval = self.client.query_target_by_name(
                target_name='fake_target')
            data = json.dumps(
                {'pageno': 1, 'pagesize': 1000,
                 "thirdParty": [0, 1],
                 "targetMark": ""})
            mocker.assert_called_once_with(
                'https://192.168.200.100/api/storage/'
                'resource/target/list', data=data)
            self.assertDictEqual({
                'status': 'fake_state',
                'node': ['node0001'],
                'name': 'fake_target',
                'type': 'iSCSI',
                'gateway': [{'hostid': 'node0001',
                             'networks': [{'hostid': 'node0001',
                                           'type': 'iSCSI',
                                           'address': 'fake_address'}],
                             'hostip': 'fake_hostip'}]}, retval)

    def test_create_target(self):
        """Test create target."""
        with mock.patch.object(self.client.session, 'post',
                               wraps=self.client.session.post) as mocker:
            retval = self.client.create_target(target_name='fake_target',
                                               targetip_to_hostid=
                                               {'1.1.1.1': 'node0001',
                                                '1.1.1.2': 'node0002',
                                                '1.1.1.3': 'node0003'})
            tip_to_hid = {'1.1.1.1': 'node0001',
                          '1.1.1.2': 'node0002',
                          '1.1.1.3': 'node0003'}
            data = json.dumps(
                {"type": "iSCSI", "readOnly": 0,
                 "thirdParty": 1, "targetName": "fake_target",
                 "networks": [{"hostid": host_id, "address": address}
                              for address, host_id
                              in tip_to_hid.items()]})
            mocker.assert_called_with(
                'https://192.168.200.100/api/storage/'
                'resource/target/create', data=data)
            self.assertIsNone(retval)

    def test_add_chap_by_target(self):
        """Test add chap to target."""
        with mock.patch.object(self.client.session, 'post',
                               wraps=self.client.session.post) as mocker:
            retval = self.client.add_chap_by_target(
                target_name='fake_target',
                username='fake_chapuser',
                password='fake_chappassword')
            data = json.dumps(
                {"password": "fake_chappassword",
                 "user": "fake_chapuser", "targetName": "fake_target"})
            mocker.assert_called_once_with(
                'https://192.168.200.100/api/storage/'
                'resource/target/add_chap', data=data)
            self.assertIsNone(retval)

    def test_query_chapinfo_by_target(self):
        """Test query target chap info."""
        with mock.patch.object(self.client.session, 'post',
                               wraps=self.client.session.post) as mocker:
            retval = self.client.query_chapinfo_by_target(
                target_name='fake_target',
                username='fake_chapuser')
            data = json.dumps({"targetName": "fake_target"})
            mocker.assert_called_once_with(
                'https://192.168.200.100/api/storage/'
                'resource/target/get_chap_list', data=data)
            self.assertDictEqual({'user': 'fake_chapuser',
                                  'level': 'level1'}, retval)

    def test_create_lun(self):
        """Test create lun."""
        with mock.patch.object(self.client.session, 'post',
                               wraps=self.client.session.post) as mocker:
            retval = self.client.create_lun(capacity_bytes=1024,
                                            poolid=1,
                                            volume_name='fake_lun')
            data = json.dumps({"capacity_bytes": 1024,
                               "poolId": 1, "priority": "normal",
                               "qosSettings": {}, "volumeName": 'fake_lun'})
            mocker.assert_called_with(
                'https://192.168.200.100/api/storage/'
                'resource/lun/add', data=data)
            self.assertIsNone(retval)

    def test_delete_lun(self):
        """Test delete lun."""
        with mock.patch.object(self.client.session, 'post',
                               wraps=self.client.session.post) as mocker:
            retval = self.client.delete_lun(poolid=1,
                                            volume_name='fake_lun')
            data = json.dumps({"delayTime": 0, "volumeNameList": [{
                               "poolId": 1,
                               "volumeName": "fake_lun"}]})
            mocker.assert_called_once_with(
                'https://192.168.200.100/api/storage/'
                'resource/lun/batch_delete', data=data)
            self.assertIsNone(retval)

    def test_extend_lun(self):
        """Test resize lun."""
        with mock.patch.object(self.client.session, 'post',
                               wraps=self.client.session.post) as mocker:
            retval = self.client.extend_lun(capacity_bytes=2048,
                                            poolid=1,
                                            volume_name='fake_lun')
            data = json.dumps({"capacity_bytes": 2048,
                               "poolId": 1,
                               "volumeName": 'fake_lun'})
            mocker.assert_called_once_with(
                'https://192.168.200.100/api/storage/'
                'resource/lun/resize', data=data)
            self.assertIsNone(retval)

    @mock.patch.object(sds_client.RestCmd, "_judge_delaytask_status")
    @mock.patch.object(sds_client.RestCmd, "query_lun_by_name")
    def test_unmap_lun(self, mock_query_lun_by_name,
                       mock__judge_delaytask_status):
        """Test unmap lun from target."""
        with mock.patch.object(self.client.session, 'post',
                               wraps=self.client.session.post) as mocker:
            mock__judge_delaytask_status.return_value = None
            lun_uuid = "c5c8533c-4ce0-11ea-bc01-005056a736f8"
            mock_query_lun_by_name.return_value = {'uuid': lun_uuid}
            retval = self.client.unmap_lun(target_name='fake_target',
                                           poolid=1,
                                           volume_name='fake_lun',
                                           pool_name='fake_pool')
            data = json.dumps({"targetName": "fake_target",
                               "targetLunList": [lun_uuid],
                               "targetSnapList": []})
            mocker.assert_called_once_with(
                'https://192.168.200.100/api/storage/'
                'resource/target/unmap_luns', data=data)
            self.assertIsNone(retval)

    @mock.patch.object(sds_client.RestCmd, "_judge_delaytask_status")
    @mock.patch.object(sds_client.RestCmd, "query_lun_by_name")
    def test_mapping_lun(self, mock_query_lun_by_name,
                         mock__judge_delaytask_status):
        """Test map lun to target."""
        with mock.patch.object(self.client.session, 'post',
                               wraps=self.client.session.post) as mocker:
            mock__judge_delaytask_status.return_value = None
            lun_uuid = "c5c8533c-4ce0-11ea-bc01-005056a736f8"
            mock_query_lun_by_name.return_value = {'uuid': lun_uuid}
            retval = self.client.mapping_lun(
                target_name='fake_target',
                poolid=1,
                volume_name='fake_lun',
                pool_name='fake_pool')
            data = json.dumps(
                {"targetName": 'fake_target',
                 "targetLunList": [lun_uuid],
                 "targetSnapList": []})
            mocker.assert_called_with(
                'https://192.168.200.100/api/storage/'
                'resource/target/map_luns', data=data)
            self.assertIsNone(retval)

    def test_query_target_lunacl(self):
        """Test query target related lun info."""
        with mock.patch.object(self.client.session, 'post',
                               wraps=self.client.session.post) as mocker:
            retval = self.client.query_target_lunacl(target_name='fake_target',
                                                     poolid=1,
                                                     volume_name='fake_lun')
            data = json.dumps({"pageno": 1, "pagesize": 1000,
                               "pools": [1],
                               "targetName": "fake_target"})
            mocker.assert_called_once_with(
                'https://192.168.200.100/api/storage/'
                'resource/target/get_luns', data=data)
            self.assertEqual(1, retval)

    def test_query_lun_by_name(self):
        """Test query lun exist or not."""
        with mock.patch.object(self.client.session, 'post',
                               wraps=self.client.session.post) as mocker:
            retval = self.client.query_lun_by_name(
                volume_name='fake_lun',
                poolid=1)
            data = json.dumps(
                {"pageno": 1, "pagesize": 1000, "volumeMark": "fake_lun",
                 "sortType": "time", "sortOrder": "desc",
                 "pools": [1],
                 "thirdParty": [0, 1]})
            mocker.assert_called_once_with(
                'https://192.168.200.100/api/storage/'
                'resource/lun/list', data=data)
            self.assertDictEqual({'volumeName': 'fake_lun',
                                  'pool_id': 1,
                                  'capacity_bytes': 1024}, retval)

    @mock.patch.object(sds_client.RestCmd, "_judge_delaytask_status")
    def test_create_snapshot(self, mock__judge_delaytask_status):
        """Test create snapshot."""
        with mock.patch.object(self.client.session, 'post',
                               wraps=self.client.session.post) as mocker:
            mock__judge_delaytask_status.return_value = None
            retval = self.client.create_snapshot(poolid=1,
                                                 volume_name='fake_lun',
                                                 snapshot_name='fake_snapshot')
            data = json.dumps(
                {"lunName": "fake_lun",
                 "poolId": 1,
                 "remark": "Cinder iSCSI snapshot.",
                 "snapName": "fake_snapshot"})
            mocker.assert_called_with(
                'https://192.168.200.100/api/storage/'
                'resource/snapshot/add', data=data)
            self.assertIsNone(retval)

    @mock.patch.object(sds_client.RestCmd, "_judge_delaytask_status")
    def test_delete_snapshot(self, mock__judge_delaytask_status):
        """Test delete snapshot."""
        with mock.patch.object(self.client.session, 'post',
                               wraps=self.client.session.post) as mocker:
            mock__judge_delaytask_status.return_value = None
            retval = self.client.delete_snapshot(poolid=1,
                                                 volume_name='fake_lun',
                                                 snapshot_name='fake_snapshot')
            data = json.dumps(
                {"lunName": "fake_lun", "poolId": 1,
                 "snapName": "fake_snapshot"})
            mocker.assert_called_once_with(
                'https://192.168.200.100/api/storage/'
                'resource/snapshot/delete', data=data)
            self.assertIsNone(retval)

    @mock.patch.object(sds_client.RestCmd, "flatten_lun")
    @mock.patch.object(sds_client.RestCmd, "_judge_delaytask_status")
    def test_create_lun_from_snapshot(self, mock__judge_delaytask_status,
                                      mock_flatten_lun):
        """Test create lun from snapshot."""
        with mock.patch.object(self.client.session, 'post',
                               wraps=self.client.session.post) as mocker:
            mock__judge_delaytask_status.return_value = None
            mock_flatten_lun.return_value = None
            retval = self.client.create_lun_from_snapshot(
                snapshot_name='fake_snapshot',
                src_volume_name='fake_src_lun',
                poolid=1,
                dst_volume_name='fake_dst_lun')
            data = json.dumps(
                {"snapshot": {"poolId": 1,
                              "lunName": "fake_src_lun",
                              "snapName": "fake_snapshot"},
                 "cloneLun": {"lunName": "fake_dst_lun",
                              "poolId": 1}})
            mocker.assert_called_once_with(
                'https://192.168.200.100/api/storage/'
                'resource/snapshot/clone', data=data)
            self.assertIsNone(retval)

    @mock.patch.object(sds_client.RestCmd, "_judge_delaytask_status")
    def test_flatten_lun(self, mock__judge_delaytask_status):
        """Test flatten lun."""
        with mock.patch.object(self.client.session, 'post',
                               wraps=self.client.session.post) as mocker:
            mock__judge_delaytask_status.return_value = None
            retval = self.client.flatten_lun(volume_name='fake_lun',
                                             poolid=1)
            data = json.dumps(
                {"poolId": 1,
                 "volumeName": "fake_lun"})
            mocker.assert_called_once_with(
                'https://192.168.200.100/api/storage/'
                'resource/lun/flatten', data=data)
            self.assertIsNone(retval)

    def test_query_flatten_lun_process(self):
        """Test query flatten process."""
        with mock.patch.object(self.client.session, 'post',
                               wraps=self.client.session.post) as mocker:
            retval = self.client.query_flatten_lun_process(
                poolid=1,
                volume_name='fake_lun')
            data = json.dumps({"pageno": 1, "pagesize": 20})
            mocker.assert_called_once_with(
                'https://192.168.200.100/api/om/'
                'delaytask/list', data=data)
            self.assertDictEqual({'status': 'completed',
                                  'run_status': 'completed',
                                  'executor': 'LunFlatten',
                                  'progress': 100,
                                  'parameter': {'pool_id': 1,
                                                'lun_name': 'fake_lun'}},
                                 retval)

    @mock.patch.object(sds_client.RestCmd, "create_snapshot")
    @mock.patch.object(sds_client.RestCmd, "create_lun_from_snapshot")
    @mock.patch.object(sds_client.RestCmd, "flatten_lun")
    @mock.patch.object(sds_client.RestCmd, "delete_snapshot")
    def test_create_lun_from_lun(self, mock_delete_snapshot,
                                 mock_flatten_lun,
                                 mock_create_lun_from_snapshot,
                                 mock_create_snapshot):
        """Test create clone lun."""
        self.client = sds_client.RestCmd(
            "https://192.168.200.100",
            "fake_user", "fake_password", True)
        mock_create_snapshot.return_value = {'success': 1}
        mock_create_lun_from_snapshot.return_value = {'success': 1}
        mock_flatten_lun.return_value = {'success': 1}
        mock_delete_snapshot.return_value = {'success': 1}
        retval = self.client.create_lun_from_lun(
            dst_volume_name='fake_dst_lun',
            poolid=1,
            src_volume_name='fake_src_lun')
        self.assertIsNone(retval)

    def test_query_snapshot_by_name(self):
        """Test query snapshot exist or not."""
        with mock.patch.object(self.client.session, 'post',
                               wraps=self.client.session.post) as mocker:
            retval = self.client.query_snapshot_by_name(
                volume_name='fake_lun',
                poolid=1,
                snapshot_name='fake_snapshot')
            data = json.dumps(
                {"lunName": "fake_lun", "pageno": 1,
                 "pagesize": 1000, "poolId": 1,
                 "snapMark": ""})
            mocker.assert_called_once_with(
                'https://192.168.200.100/api/storage/'
                'resource/snapshot/list', data=data)
            self.assertListEqual([{'snapName': 'fake_snapshot',
                                   'lunName': 'fake_lun'}], retval)
