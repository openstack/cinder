# Copyright (c) 2018 Huawei Technologies Co., Ltd
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

import json
import mock
import requests

from cinder import test
from cinder.tests.unit.volume.drivers.fusionstorage import test_utils
from cinder.volume.drivers.fusionstorage import fs_client


class FakeSession(test_utils.FakeBaseSession):
    method_map = {
        'get': {
            'rest/version':
                {'currentVersion': 'fake_version'},
            '/storagePool$':
                {'storagePools': [{'poolName': 'fake_pool_name',
                                   'poolId': 'fake_pool_id'}]},
            '/storagePool\?poolId=0':
                {'storagePools': [{'poolName': 'fake_pool_name1',
                                   'poolId': 0}]},
            '/volume/queryByName\?volName=fake_name':
                {'errorCode': 0, 'lunDetailInfo':
                    [{'volume_id': 'fake_id',
                      'volume_name': 'fake_name'}]},
            '/volume/queryById\?volId=fake_id':
                {'errorCode': 0, 'lunDetailInfo':
                    [{'volume_id': 'fake_id',
                      'volume_name': 'fake_name'}]},
            '/lun/wwn/list\?wwn=fake_wwn':
                {'errorCode': 0, 'lunDetailInfo':
                    [{'volume_id': 'fake_id',
                      'volume_wwn': 'fake_wwn'}]},
        },
        'post': {
            '/sec/login': {},
            '/sec/logout': {'res': 'fake_logout'},
            '/sec/keepAlive': {'res': 'fake_keepAlive'},
            '/volume/list': {'errorCode': 0, 'volumeList': [
                {'volName': 'fake_name1', 'volId': 'fake_id1'},
                {'volName': 'fake_name2', 'volId': 'fake_id2'}]},
            '/volume/create': {'ID': 'fake_volume_create_id'},
            '/volume/delete': {'ID': 'fake_volume_delete_id'},
            '/volume/attach':
                {'fake_name': [{'errorCode': '0', 'ip': 'fake_ip'}]},
            '/volume/detach/': {'ID': 'fake_volume_detach_id'},
            '/volume/expand': {'ID': 'fake_volume_expend_id'},
            '/volume/snapshot/list':
                {"snapshotList": [{"snapshot": "fake_name",
                                   "size": "fake_size"}]},
            '/snapshot/list': {'totalNum': 'fake_snapshot_num',
                               'snapshotList':
                                   [{'snapName': 'fake_snapName'}]},
            '/snapshot/create/': {'ID': 'fake_snapshot_create_id'},
            '/snapshot/delete/': {'ID': 'fake_snapshot_delete_id'},
            '/snapshot/rollback': {'ID': 'fake_snapshot_delete_id'},
            '/snapshot/volume/create/': {'ID': 'fake_vol_from_snap_id'},
        }
    }


class TestFsclient(test.TestCase):
    def setUp(self):
        super(TestFsclient, self).setUp()
        self.mock_object(requests, 'Session', FakeSession)
        self.client = fs_client.RestCommon('https://fake_rest_site',
                                           'fake_user',
                                           'fake_password')
        self.client.login()

    def tearDown(self):
        super(TestFsclient, self).tearDown()

    def test_login(self):
        self.assertEqual('fake_version',
                         self.client.version)
        self.assertEqual('fake_token',
                         self.client.session.headers['X-Auth-Token'])

    def test_keep_alive(self):
        retval = self.client.keep_alive()
        self.assertIsNone(retval)

    def test_logout(self):
        self.assertIsNone(self.client.logout())

    def test_query_all_pool_info(self):
        with mock.patch.object(self.client.session, 'get',
                               wraps=self.client.session.get) as mocker:
            retval = self.client.query_pool_info()
            mocker.assert_called_once_with(
                'https://fake_rest_site/dsware/service/'
                'fake_version/storagePool', timeout=50)
            self.assertListEqual(
                [{'poolName': 'fake_pool_name',
                  'poolId': 'fake_pool_id'}], retval)

    def test_query_pool_info(self):
        with mock.patch.object(self.client.session, 'get',
                               wraps=self.client.session.get) as mocker:
            retval = self.client.query_pool_info(pool_id=0)
            mocker.assert_called_once_with(
                'https://fake_rest_site/dsware/service/'
                'fake_version/storagePool?poolId=0', timeout=50)
            self.assertListEqual(
                [{'poolName': 'fake_pool_name1', 'poolId': 0}], retval)

    def test_query_volume_by_name(self):
        with mock.patch.object(self.client.session, 'get',
                               wraps=self.client.session.get) as mocker:
            retval = self.client.query_volume_by_name(vol_name='fake_name')
            mocker.assert_called_once_with(
                'https://fake_rest_site/dsware/service/fake_version/'
                'volume/queryByName?volName=fake_name', timeout=50)
            self.assertListEqual(
                [{'volume_id': 'fake_id', 'volume_name': 'fake_name'}], retval)

    def test_query_volume_by_id(self):
        with mock.patch.object(self.client.session, 'get',
                               wraps=self.client.session.get) as mocker:
            retval = self.client.query_volume_by_id(vol_id='fake_id')
            mocker.assert_called_once_with(
                'https://fake_rest_site/dsware/service/fake_version/'
                'volume/queryById?volId=fake_id', timeout=50)
            self.assertListEqual(
                [{'volume_id': 'fake_id', 'volume_name': 'fake_name'}], retval)

    def test_create_volume(self):
        with mock.patch.object(self.client.session, 'post',
                               wraps=self.client.session.post) as mocker:
            retval = self.client.create_volume(
                vol_name='fake_name', vol_size=1, pool_id='fake_id')
            except_data = json.dumps(
                {"volName": "fake_name", "volSize": 1, "poolId": "fake_id"})
            mocker.assert_called_once_with(
                'https://fake_rest_site/dsware/service/fake_version/'
                'volume/create', data=except_data, timeout=50)
            self.assertIsNone(retval)

    def test_delete_volume(self):
        with mock.patch.object(self.client.session, 'post',
                               wraps=self.client.session.post) as mocker:
            retval = self.client.delete_volume(vol_name='fake_name')
            except_data = json.dumps({"volNames": ['fake_name']})
            mocker.assert_called_once_with(
                'https://fake_rest_site/dsware/service/fake_version/'
                'volume/delete', data=except_data, timeout=50)
            self.assertIsNone(retval)

    def test_attach_volume(self):
        with mock.patch.object(self.client.session, 'post',
                               wraps=self.client.session.post) as mocker:
            retval = self.client.attach_volume(
                vol_name='fake_name', manage_ip='fake_ip')
            except_data = json.dumps(
                {"volName": ['fake_name'], "ipList": ['fake_ip']})
            mocker.assert_called_once_with(
                'https://fake_rest_site/dsware/service/fake_version/'
                'volume/attach', data=except_data, timeout=50)
            self.assertDictEqual(
                {'result': 0,
                 'fake_name': [{'errorCode': '0', 'ip': 'fake_ip'}]},
                retval)

    def test_detach_volume(self):
        with mock.patch.object(self.client.session, 'post',
                               wraps=self.client.session.post) as mocker:
            retval = self.client.detach_volume(
                vol_name='fake_name', manage_ip='fake_ip')
            except_data = json.dumps(
                {"volName": ['fake_name'], "ipList": ['fake_ip']})
            mocker.assert_called_once_with(
                'https://fake_rest_site/dsware/service/fake_version/'
                'volume/detach/', data=except_data, timeout=50)
            self.assertIsNone(retval)

    def test_expand_volume(self):
        with mock.patch.object(self.client.session, 'post',
                               wraps=self.client.session.post) as mocker:
            retval = self.client.expand_volume(
                vol_name='fake_name', new_vol_size=2)
            except_data = json.dumps({"volName": 'fake_name', "newVolSize": 2})
            mocker.assert_called_once_with(
                'https://fake_rest_site/dsware/service/fake_version/'
                'volume/expand', data=except_data, timeout=50)
            self.assertIsNone(retval)

    def test_query_snapshot_by_name(self):
        with mock.patch.object(self.client.session, 'post',
                               wraps=self.client.session.post) as mocker:
            retval = self.client.query_snapshot_by_name(
                pool_id='fake_id', snapshot_name='fake_name')
            except_data = json.dumps(
                {"poolId": 'fake_id', "pageNum": 1,
                 "pageSize": 1000, "filters": {"volumeName": 'fake_name'}})
            mocker.assert_called_once_with(
                'https://fake_rest_site/dsware/service/fake_version/'
                'snapshot/list', data=except_data, timeout=50)
            self.assertDictEqual(
                {'result': 0, 'totalNum': 'fake_snapshot_num',
                 'snapshotList': [{'snapName': 'fake_snapName'}]}, retval)

    def test_create_snapshot(self):
        with mock.patch.object(self.client.session, 'post',
                               wraps=self.client.session.post) as mocker:
            retval = self.client.create_snapshot(
                snapshot_name='fake_snap', vol_name='fake_name')
            except_data = json.dumps(
                {"volName": "fake_name", "snapshotName": "fake_snap"})
            mocker.assert_called_once_with(
                'https://fake_rest_site/dsware/service/fake_version/'
                'snapshot/create/', data=except_data, timeout=50)
            self.assertIsNone(retval)

    def test_delete_snapshot(self):
        with mock.patch.object(self.client.session, 'post',
                               wraps=self.client.session.post) as mocker:
            retval = self.client.delete_snapshot(snapshot_name='fake_snap')
            except_data = json.dumps({"snapshotName": "fake_snap"})
            mocker.assert_called_once_with(
                'https://fake_rest_site/dsware/service/fake_version/'
                'snapshot/delete/', data=except_data, timeout=50)
            self.assertIsNone(retval)

    def test_create_volume_from_snapshot(self):
        with mock.patch.object(self.client.session, 'post',
                               wraps=self.client.session.post) as mocker:
            retval = self.client.create_volume_from_snapshot(
                snapshot_name='fake_snap', vol_name='fake_name', vol_size=2)
            except_data = json.dumps({"src": 'fake_snap',
                                      "volName": 'fake_name',
                                      "volSize": 2})
            mocker.assert_called_once_with(
                'https://fake_rest_site/dsware/service/fake_version/'
                'snapshot/volume/create/', data=except_data, timeout=50)
            self.assertIsNone(retval)

    @mock.patch.object(fs_client.RestCommon, 'create_snapshot')
    @mock.patch.object(fs_client.RestCommon, 'create_volume_from_snapshot')
    @mock.patch.object(fs_client.RestCommon, 'delete_snapshot')
    def test_create_volume_from_volume(
            self, mock_delete_snapshot, mock_volume_from_snapshot,
            mock_create_snapshot):
        vol_name = 'fake_name'
        vol_size = 3
        src_vol_name = 'src_fake_name'
        temp_snapshot_name = "temp" + src_vol_name + "clone" + vol_name

        retval = self.client.create_volume_from_volume(
            vol_name, vol_size, src_vol_name)
        mock_create_snapshot.assert_called_once_with(
            vol_name=src_vol_name, snapshot_name=temp_snapshot_name)
        mock_volume_from_snapshot.assert_called_once_with(
            snapshot_name=temp_snapshot_name,
            vol_name=vol_name, vol_size=vol_size)
        mock_delete_snapshot.assert_called_once_with(
            snapshot_name=temp_snapshot_name)
        self.assertIsNone(retval)
