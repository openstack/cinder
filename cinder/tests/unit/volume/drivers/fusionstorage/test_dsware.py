# Copyright (c) 2018 Huawei Technologies Co., Ltd.
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
import ddt
import json

import mock
import uuid

from cinder import exception
from cinder import objects
from cinder import test
from cinder.volume import configuration as config
from cinder.volume.drivers.fusionstorage import dsware
from cinder.volume.drivers.fusionstorage import fs_client
from cinder.volume.drivers.fusionstorage import fs_conf
from cinder.volume import utils as volume_utils


class FakeDSWAREDriver(dsware.DSWAREDriver):
    def __init__(self):
        self.configuration = config.Configuration(None)
        self.conf = fs_conf.FusionStorageConf(self.configuration, "cinder@fs")
        self.client = None


@ddt.ddt
class TestDSWAREDriver(test.TestCase):

    def setUp(self):
        super(TestDSWAREDriver, self).setUp()
        self.fake_driver = FakeDSWAREDriver()
        self.client = fs_client.RestCommon(None, None, None)

    def tearDown(self):
        super(TestDSWAREDriver, self).tearDown()

    @mock.patch.object(fs_client.RestCommon, 'login')
    def test_do_setup(self, mock_login):
        self.fake_driver.client = fs_client.RestCommon(
            'https://fake_rest_site', 'user', 'password')
        update_mocker = self.mock_object(
            self.fake_driver.conf, 'update_config_value')
        self.fake_driver.configuration.san_address = 'https://fake_rest_site'
        self.fake_driver.configuration.san_user = 'fake_san_user'
        self.fake_driver.configuration.san_password = 'fake_san_password'

        self.fake_driver.do_setup('context')
        update_mocker.assert_called_once_with()
        mock_login.assert_called_once_with()

    @mock.patch.object(fs_client.RestCommon, 'query_pool_info')
    def test_check_for_setup_error(self, mock_query_pool_info):
        self.fake_driver.configuration.pools_name = ['fake_pool_name']
        self.fake_driver.client = fs_client.RestCommon(
            'https://fake_rest_site', 'user', 'password')
        result1 = [{'poolName': 'fake_pool_name'},
                   {'poolName': 'fake_pool_name1'}]
        result2 = [{'poolName': 'fake_pool_name1'},
                   {'poolName': 'fake_pool_name2'}]

        mock_query_pool_info.return_value = result1
        retval = self.fake_driver.check_for_setup_error()
        self.assertIsNone(retval)

        mock_query_pool_info.return_value = result2
        try:
            self.fake_driver.check_for_setup_error()
        except Exception as e:
            self.assertEqual(exception.InvalidInput, type(e))

    @mock.patch.object(fs_client.RestCommon, 'query_pool_info')
    def test__update_pool_stats(self, mock_query_pool_info):
        self.fake_driver.configuration.pools_name = ['fake_pool_name']
        self.fake_driver.client = fs_client.RestCommon(
            'https://fake_rest_site', 'user', 'password')
        result = [{'poolName': 'fake_pool_name',
                   'totalCapacity': 2048, 'usedCapacity': 1024},
                  {'poolName': 'fake_pool_name1',
                   'totalCapacity': 2048, 'usedCapacity': 1024}]

        mock_query_pool_info.return_value = result
        retval = self.fake_driver._update_pool_stats()
        self.assertDictEqual(
            {"volume_backend_name": 'FakeDSWAREDriver',
             "driver_version": "2.0.9",
             "QoS_support": False,
             "thin_provisioning_support": False,
             "vendor_name": "Huawei",
             "pools":
                 [{"pool_name": 'fake_pool_name', "total_capacity_gb": 2,
                   "free_capacity_gb": 1}]}, retval)
        mock_query_pool_info.assert_called_once_with()

    @mock.patch.object(fs_client.RestCommon, 'keep_alive')
    @mock.patch.object(dsware.DSWAREDriver, '_update_pool_stats')
    def test_get_volume_stats(self, mock__update_pool_stats, mock_keep_alive):
        self.fake_driver.client = fs_client.RestCommon(
            'https://fake_rest_site', 'user', 'password')
        result = {"success"}
        mock__update_pool_stats.return_value = result
        retval = self.fake_driver.get_volume_stats()
        self.assertEqual(result, retval)
        mock_keep_alive.assert_called_once_with()

    @mock.patch.object(fs_client.RestCommon, 'query_volume_by_name')
    def test__check_volume_exist(self, mock_query_volume_by_name):
        self.fake_driver.client = fs_client.RestCommon(
            'https://fake_rest_site', 'user', 'password')
        volume = objects.Volume(_name_id=uuid.uuid4())
        result1 = {'volName': 'fake_name'}
        result2 = None

        mock_query_volume_by_name.return_value = result1
        retval = self.fake_driver._check_volume_exist(volume)
        self.assertEqual(retval, result1)

        mock_query_volume_by_name.return_value = result2
        retval = self.fake_driver._check_volume_exist(volume)
        self.assertIsNone(retval)

    @mock.patch.object(volume_utils, 'extract_host')
    @mock.patch.object(fs_client.RestCommon, 'query_pool_info')
    def test__get_pool_id(self, mock_query_pool_info, mock_extract_host):
        self.fake_driver.client = fs_client.RestCommon(
            'https://fake_rest_site', 'user', 'password')
        volume = objects.Volume(host='host')
        pool_name1 = 'fake_pool_name1'
        pool_name2 = 'fake_pool_name2'
        pool_info = [{'poolName': 'fake_pool_name', 'poolId': 'fake_id'},
                     {'poolName': 'fake_pool_name1', 'poolId': 'fake_id1'}]

        mock_query_pool_info.return_value = pool_info
        mock_extract_host.return_value = pool_name1
        retval = self.fake_driver._get_pool_id(volume)
        self.assertEqual('fake_id1', retval)

        mock_extract_host.return_value = pool_name2
        try:
            self.fake_driver._get_pool_id(volume)
        except Exception as e:
            self.assertEqual(exception.InvalidInput, type(e))

    def test__get_vol_name(self):
        volume1 = objects.Volume(_name_id=uuid.uuid4())
        volume1.update(
            {"provider_location": json.dumps({"name": "fake_name"})})
        volume2 = objects.Volume(_name_id=uuid.uuid4())

        retval = self.fake_driver._get_vol_name(volume1)
        self.assertEqual("fake_name", retval)

        retval = self.fake_driver._get_vol_name(volume2)
        self.assertEqual(volume2.name, retval)

    @mock.patch.object(fs_client.RestCommon, 'create_volume')
    @mock.patch.object(dsware.DSWAREDriver, '_get_pool_id')
    def test_create_volume(self, mock__get_pool_id, mock_create_volume):
        self.fake_driver.client = fs_client.RestCommon(
            'https://fake_rest_site', 'user', 'password')
        volume = objects.Volume(_name_id=uuid.uuid4(), size=1)
        mock__get_pool_id.return_value = 'fake_poolID'
        mock_create_volume.return_value = {'result': 0}

        retval = self.fake_driver.create_volume(volume)
        self.assertIsNone(retval)

    @mock.patch.object(dsware.DSWAREDriver, '_check_volume_exist')
    @mock.patch.object(fs_client.RestCommon, 'delete_volume')
    def test_delete_volume(self, mock_delete_volume, mock__check_volume_exist):
        result = True
        self.fake_driver.client = fs_client.RestCommon(
            'https://fake_rest_site', 'user', 'password')
        volume = objects.Volume(_name_id=uuid.uuid4())
        mock_delete_volume.return_value = {'result': 0}

        mock__check_volume_exist.return_value = result
        retval = self.fake_driver.delete_volume(volume)
        self.assertIsNone(retval)

        mock__check_volume_exist.return_value = False
        retval = self.fake_driver.delete_volume(volume)
        self.assertIsNone(retval)

    @mock.patch.object(dsware.DSWAREDriver, '_check_volume_exist')
    @mock.patch.object(fs_client.RestCommon, 'expand_volume')
    def test_extend_volume(self, mock_expand_volume, mock__check_volume_exist):
        result1 = True
        result2 = False
        self.fake_driver.client = fs_client.RestCommon(
            'https://fake_rest_site', 'user', 'password')
        volume = objects.Volume(_name_id=uuid.uuid4(), size=2)
        mock_expand_volume.return_value = {
            'volName': 'fake_name', 'size': 'new_size'}

        mock__check_volume_exist.return_value = result1
        retval = self.fake_driver.extend_volume(volume=volume, new_size=3)
        self.assertIsNone(retval)

        mock__check_volume_exist.return_value = result2
        try:
            self.fake_driver.extend_volume(volume=volume, new_size=3)
        except Exception as e:
            self.assertEqual(exception.VolumeBackendAPIException, type(e))

    @mock.patch.object(dsware.DSWAREDriver, '_check_volume_exist')
    @mock.patch.object(dsware.DSWAREDriver, '_check_snapshot_exist')
    @mock.patch.object(fs_client.RestCommon, 'create_volume_from_snapshot')
    def test_create_volume_from_snapshot(
            self, mock_create_volume_from_snapshot,
            mock_check_snapshot_exist, mock_check_volume_exist):
        result1 = True
        result2 = False
        self.fake_driver.client = fs_client.RestCommon(
            'https://fake_rest_site', 'user', 'password')
        volume = objects.Volume(_name_id=uuid.uuid4())
        snapshot = objects.Snapshot(
            id=uuid.uuid4(), volume_size=2, volume=volume)

        volume1 = objects.Volume(_name_id=uuid.uuid4(), size=2)
        volume2 = objects.Volume(_name_id=uuid.uuid4(), size=1)
        mock_create_volume_from_snapshot.return_value = {'result': 0}

        mock_check_volume_exist.return_value = result2
        mock_check_snapshot_exist.return_value = result1
        retval = self.fake_driver.create_volume_from_snapshot(
            volume1, snapshot)
        self.assertIsNone(retval)

        mock_check_volume_exist.return_value = result1
        try:
            self.fake_driver.create_volume_from_snapshot(volume1, snapshot)
        except Exception as e:
            self.assertEqual(exception.VolumeBackendAPIException, type(e))

        mock_check_volume_exist.return_value = result2
        mock_check_snapshot_exist.return_value = result2
        try:
            self.fake_driver.create_volume_from_snapshot(volume1, snapshot)
        except Exception as e:
            self.assertEqual(exception.VolumeBackendAPIException, type(e))

        mock_check_volume_exist.return_value = result2
        mock_check_snapshot_exist.return_value = result1
        try:
            self.fake_driver.create_volume_from_snapshot(volume2, snapshot)
        except Exception as e:
            self.assertEqual(exception.VolumeBackendAPIException, type(e))

    @mock.patch.object(dsware.DSWAREDriver, '_check_volume_exist')
    @mock.patch.object(fs_client.RestCommon, 'create_volume_from_volume')
    def test_cloned_volume(
            self, mock_create_volume_from_volume, mock__check_volume_exist):
        self.fake_driver.client = fs_client.RestCommon(
            'https://fake_rest_site', 'user', 'password')
        volume = objects.Volume(_name_id=uuid.uuid4(), size=1)
        src_volume = objects.Volume(_name_id=uuid.uuid4())
        result1 = True
        result2 = False

        mock__check_volume_exist.return_value = result1
        retval = self.fake_driver.create_cloned_volume(volume, src_volume)
        self.assertIsNone(retval)
        mock_create_volume_from_volume.assert_called_once_with(
            vol_name=volume.name, vol_size=volume.size * 1024,
            src_vol_name=src_volume.name)

        mock__check_volume_exist.return_value = result2
        try:
            self.fake_driver.create_cloned_volume(volume, src_volume)
        except Exception as e:
            self.assertEqual(exception.VolumeBackendAPIException, type(e))

    def test__get_snapshot_name(self):
        snapshot1 = objects.Snapshot(id=uuid.uuid4())
        snapshot1.update(
            {"provider_location": json.dumps({"name": "fake_name"})})
        snapshot2 = objects.Snapshot(id=uuid.uuid4())

        retval = self.fake_driver._get_snapshot_name(snapshot1)
        self.assertEqual("fake_name", retval)

        retval = self.fake_driver._get_snapshot_name(snapshot2)
        self.assertEqual(snapshot2.name, retval)

    @mock.patch.object(fs_client.RestCommon, 'query_snapshot_by_name')
    @mock.patch.object(dsware.DSWAREDriver, '_get_pool_id')
    def test__check_snapshot_exist(
            self, mock_get_pool_id, mock_query_snapshot_by_name):
        self.fake_driver.client = fs_client.RestCommon(
            'https://fake_rest_site', 'user', 'password')
        volume = objects.Volume(_name_id=uuid.uuid4())
        snapshot = objects.Snapshot(id=uuid.uuid4())
        result1 = {'name': 'fake_name', 'totalNum': 1}
        result2 = {'name': 'fake_name', 'totalNum': 0}
        mock_get_pool_id.return_value = "fake_pool_id"

        mock_query_snapshot_by_name.return_value = result1
        retval = self.fake_driver._check_snapshot_exist(volume, snapshot)
        self.assertEqual({'name': 'fake_name', 'totalNum': 1}, retval)

        mock_query_snapshot_by_name.return_value = result2
        retval = self.fake_driver._check_snapshot_exist(volume, snapshot)
        self.assertIsNone(retval)

    @mock.patch.object(fs_client.RestCommon, 'create_snapshot')
    def test_create_snapshot(self, mock_create_snapshot):
        self.fake_driver.client = fs_client.RestCommon(
            'https://fake_rest_site', 'user', 'password')
        volume = objects.Volume(_name_id=uuid.uuid4())
        snapshot = objects.Snapshot(id=uuid.uuid4(),
                                    volume_id=uuid.uuid4(), volume=volume)

        retval = self.fake_driver.create_snapshot(snapshot)
        self.assertIsNone(retval)
        mock_create_snapshot.assert_called_once_with(
            snapshot_name=snapshot.name, vol_name=volume.name)

    @mock.patch.object(dsware.DSWAREDriver, '_check_snapshot_exist')
    @mock.patch.object(fs_client.RestCommon, 'delete_snapshot')
    def test_delete_snapshot(self, mock_delete_snapshot,
                             mock_check_snapshot_exist):
        self.fake_driver.client = fs_client.RestCommon(
            'https://fake_rest_site', 'user', 'password')
        volume = objects.Volume(id=uuid.uuid4())
        snapshot = objects.Snapshot(id=uuid.uuid4(), volume=volume)
        result = True
        mock_delete_snapshot.return_valume = {'result': 0}

        mock_check_snapshot_exist.return_value = result
        retval = self.fake_driver.delete_snapshot(snapshot)
        self.assertIsNone(retval)

        mock_check_snapshot_exist.return_value = False
        retval = self.fake_driver.delete_snapshot(snapshot)
        self.assertIsNone(retval)

    def test__get_manager_ip(self):
        context = {'host': 'host1'}
        host1 = {'host1': '1.1.1.1'}
        host2 = {'host2': '1.1.1.1'}

        self.fake_driver.configuration.manager_ips = host1
        retval = self.fake_driver._get_manager_ip(context)
        self.assertEqual('1.1.1.1', retval)

        self.fake_driver.configuration.manager_ips = host2
        try:
            self.fake_driver._get_manager_ip(context)
        except Exception as e:
            self.assertEqual(exception.VolumeBackendAPIException, type(e))

    @mock.patch.object(dsware.DSWAREDriver, '_check_volume_exist')
    @mock.patch.object(dsware.DSWAREDriver, '_get_manager_ip')
    @mock.patch.object(fs_client.RestCommon, 'attach_volume')
    def test__attach_volume(self, mock_attach_volume,
                            mock__get_manager_ip, mock__check_volume_exist):
        self.fake_driver.client = fs_client.RestCommon(
            'https://fake_rest_site', 'user', 'password')
        volume = objects.Volume(_name_id=uuid.uuid4())
        attach_result1 = {volume.name: [{'devName': 'fake_path'}]}
        attach_result2 = {volume.name: [{'devName': ''}]}
        result1 = True
        result2 = False
        mock__get_manager_ip.return_value = 'fake_ip'

        mock__check_volume_exist.return_value = result1
        mock_attach_volume.return_value = attach_result1
        retval, vol = self.fake_driver._attach_volume(
            "context", volume, "properties")
        self.assertEqual(
            ({'device': {'path': b'fake_path'}}, volume), (retval, vol))
        mock__get_manager_ip.assert_called_once_with("properties")
        mock__check_volume_exist.assert_called_once_with(volume)
        mock_attach_volume.assert_called_once_with(volume.name, 'fake_ip')

        mock__check_volume_exist.return_value = result2
        try:
            self.fake_driver._attach_volume("context", volume, "properties")
        except Exception as e:
            self.assertEqual(exception.VolumeBackendAPIException, type(e))

        mock__check_volume_exist.return_value = result1
        mock_attach_volume.return_value = attach_result2
        try:
            self.fake_driver._attach_volume("context", volume, "properties")
        except Exception as e:
            self.assertEqual(exception.VolumeBackendAPIException, type(e))

    @mock.patch.object(dsware.DSWAREDriver, '_check_volume_exist')
    @mock.patch.object(dsware.DSWAREDriver, '_get_manager_ip')
    @mock.patch.object(fs_client.RestCommon, 'detach_volume')
    def test__detach_volume(self, mock_detach_volume,
                            mock__get_manager_ip, mock__check_volume_exist):
        self.fake_driver.client = fs_client.RestCommon(
            'https://fake_rest_site', 'user', 'password')
        volume = objects.Volume(_name_id=uuid.uuid4())
        result1 = True
        result2 = False

        mock__get_manager_ip.return_value = 'fake_ip'
        mock_detach_volume.return_value = {'result': 0}

        mock__check_volume_exist.return_value = result1
        retval = self.fake_driver._detach_volume(
            'context', 'attach_info', volume, 'properties')
        self.assertIsNone(retval)

        mock__check_volume_exist.return_value = result2
        retval = self.fake_driver._detach_volume(
            'context', 'attach_info', volume, 'properties')
        self.assertIsNone(retval)

    @mock.patch.object(dsware.DSWAREDriver, '_check_volume_exist')
    @mock.patch.object(dsware.DSWAREDriver, '_get_manager_ip')
    @mock.patch.object(fs_client.RestCommon, 'attach_volume')
    @mock.patch.object(fs_client.RestCommon, 'query_volume_by_name')
    def test_initialize_connection(self, mock_query_volume_by_name,
                                   mock_attach_volume,
                                   mock__get_manager_ip,
                                   mock__check_volume_exist):
        self.fake_driver.client = fs_client.RestCommon(
            'https://fake_rest_site', 'user', 'password')
        volume = objects.Volume(_name_id=uuid.uuid4())
        attach_result = {volume.name: [{'devName': 'fake_path'}]}

        result1 = True
        result2 = False
        mock__get_manager_ip.return_value = 'fake_ip'
        mock_query_volume_by_name.return_value = {'wwn': 'fake_wwn',
                                                  'volName': 'fake_name'}
        mock_attach_volume.return_value = attach_result

        mock__check_volume_exist.return_value = result1
        retval = self.fake_driver.initialize_connection(volume, 'connector')
        self.assertDictEqual(
            {'driver_volume_type': 'local',
             'data': {'device_path': '/dev/disk/by-id/wwn-0xfake_wwn'}},
            retval)

        mock__check_volume_exist.return_value = result2
        try:
            self.fake_driver.initialize_connection(volume, 'connector')
        except Exception as e:
            self.assertEqual(exception.VolumeBackendAPIException, type(e))

    @mock.patch.object(dsware.DSWAREDriver, '_check_volume_exist')
    @mock.patch.object(dsware.DSWAREDriver, '_get_manager_ip')
    @mock.patch.object(fs_client.RestCommon, 'detach_volume')
    def test_terminate_connection(self, mock_detach_volume,
                                  mock__get_manager_ip,
                                  mock__check_volume_exist):
        self.fake_driver.client = fs_client.RestCommon(
            'https://fake_rest_site', 'user', 'password')
        volume = objects.Volume(_name_id=uuid.uuid4())
        result1 = True
        result2 = False
        mock__get_manager_ip.return_value = 'fake_ip'

        mock__check_volume_exist.return_value = result1
        retval = self.fake_driver.terminate_connection(volume, 'connector')
        self.assertIsNone(retval)
        mock_detach_volume.assert_called_once_with(volume.name, 'fake_ip')

        mock__check_volume_exist.return_value = result2
        retval = self.fake_driver.terminate_connection('volume', 'connector')
        self.assertIsNone(retval)
