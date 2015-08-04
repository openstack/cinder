#    Copyright (c) 2014 Dell Inc.
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
from cinder.volume.drivers.dell import dell_storagecenter_api
from cinder.volume.drivers.dell import dell_storagecenter_fc


# We patch these here as they are used by every test to keep
# from trying to contact a Dell Storage Center.
@mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                   '__init__',
                   return_value=None)
@mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                   'open_connection')
@mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                   'close_connection')
class DellSCSanFCDriverTestCase(test.TestCase):

    VOLUME = {u'instanceId': u'64702.4829',
              u'scSerialNumber': 64702,
              u'replicationSource': False,
              u'liveVolume': False,
              u'vpdId': 4831,
              u'objectType': u'ScVolume',
              u'index': 4829,
              u'volumeFolderPath': u'dopnstktst/',
              u'hostCacheEnabled': False,
              u'usedByLegacyFluidFsNasVolume': False,
              u'inRecycleBin': False,
              u'volumeFolderIndex': 17,
              u'instanceName': u'5729f1db-4c45-416c-bc15-c8ea13a4465d',
              u'statusMessage': u'',
              u'status': u'Down',
              u'storageType': {u'instanceId': u'64702.1',
                               u'instanceName': u'Assigned - Redundant - 2 MB',
                               u'objectType': u'ScStorageType'},
              u'cmmDestination': False,
              u'replicationDestination': False,
              u'volumeFolder': {u'instanceId': u'64702.17',
                                u'instanceName': u'opnstktst',
                                u'objectType': u'ScVolumeFolder'},
              u'deviceId': u'6000d31000fcbe0000000000000012df',
              u'active': False,
              u'portableVolumeDestination': False,
              u'deleteAllowed': True,
              u'name': u'5729f1db-4c45-416c-bc15-c8ea13a4465d',
              u'scName': u'Storage Center 64702',
              u'secureDataUsed': False,
              u'serialNumber': u'0000fcbe-000012df',
              u'replayAllowed': False,
              u'flashOptimized': False,
              u'configuredSize': u'1.073741824E9 Bytes',
              u'mapped': False,
              u'cmmSource': False}

    SCSERVER = {u'scName': u'Storage Center 64702',
                u'volumeCount': 0,
                u'removeHbasAllowed': True,
                u'legacyFluidFs': False,
                u'serverFolderIndex': 4,
                u'alertOnConnectivity': True,
                u'objectType': u'ScPhysicalServer',
                u'instanceName': u'Server_21000024ff30441d',
                u'instanceId': u'64702.47',
                u'serverFolderPath': u'opnstktst/',
                u'portType': [u'FibreChannel'],
                u'type': u'Physical',
                u'statusMessage': u'Only 5 of 6 expected paths are up',
                u'status': u'Degraded',
                u'scSerialNumber': 64702,
                u'serverFolder': {u'instanceId': u'64702.4',
                                  u'instanceName': u'opnstktst',
                                  u'objectType': u'ScServerFolder'},
                u'parentIndex': 0,
                u'connectivity': u'Partial',
                u'hostCacheIndex': 0,
                u'deleteAllowed': True,
                u'pathCount': 5,
                u'name': u'Server_21000024ff30441d',
                u'hbaPresent': True,
                u'hbaCount': 2,
                u'notes': u'Created by Dell Cinder Driver',
                u'mapped': False,
                u'operatingSystem': {u'instanceId': u'64702.38',
                                     u'instanceName': u'Red Hat Linux 6.x',
                                     u'objectType': u'ScServerOperatingSystem'}
                }

    MAPPING = {u'instanceId': u'64702.2183',
               u'scName': u'Storage Center 64702',
               u'scSerialNumber': 64702,
               u'controller': {u'instanceId': u'64702.64702',
                               u'instanceName': u'SN 64702',
                               u'objectType': u'ScController'},
               u'lunUsed': [1],
               u'server': {u'instanceId': u'64702.47',
                           u'instanceName': u'Server_21000024ff30441d',
                           u'objectType': u'ScPhysicalServer'},
               u'volume': {u'instanceId': u'64702.4829',
                           u'instanceName':
                           u'5729f1db-4c45-416c-bc15-c8ea13a4465d',
                           u'objectType': u'ScVolume'},
               u'connectivity': u'Up',
               u'readOnly': False,
               u'objectType': u'ScMappingProfile',
               u'hostCache': False,
               u'mappedVia': u'Server',
               u'mapCount': 2,
               u'instanceName': u'4829-47',
               u'lunRequested': u'N/A'
               }

    def setUp(self):
        super(DellSCSanFCDriverTestCase, self).setUp()

        # configuration is a mock.  A mock is pretty much a blank
        # slate.  I believe mock's done in setup are not happy time
        # mocks.  So we just do a few things like driver config here.
        self.configuration = mock.Mock()

        self.configuration.san_is_local = False
        self.configuration.san_ip = "192.168.0.1"
        self.configuration.san_login = "admin"
        self.configuration.san_password = "pwd"
        self.configuration.dell_sc_ssn = 64702
        self.configuration.dell_sc_server_folder = 'opnstktst'
        self.configuration.dell_sc_volume_folder = 'opnstktst'
        self.configuration.dell_sc_api_port = 3033
        self._context = context.get_admin_context()

        self.driver = dell_storagecenter_fc.DellStorageCenterFCDriver(
            configuration=self.configuration)

        self.driver.do_setup(None)

        self.driver._stats = {'QoS_support': False,
                              'volume_backend_name': 'dell-1',
                              'free_capacity_gb': 12123,
                              'driver_version': '1.0.1',
                              'total_capacity_gb': 12388,
                              'reserved_percentage': 0,
                              'vendor_name': 'Dell',
                              'storage_protocol': 'FC'}

        self.volid = '5729f1db-4c45-416c-bc15-c8ea13a4465d'
        self.volume_name = "volume" + self.volid
        self.connector = {'ip': '192.168.0.77',
                          'host': 'cinderfc-vm',
                          'wwnns': ['20000024ff30441c', '20000024ff30441d'],
                          'initiator': 'iqn.1993-08.org.debian:01:e1b1312f9e1',
                          'wwpns': ['21000024ff30441c', '21000024ff30441d']}

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_sc',
                       return_value=64702)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_server',
                       return_value=None)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'create_server_multiple_hbas',
                       return_value=SCSERVER)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'map_volume',
                       return_value=MAPPING)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_wwns',
                       return_value=(1,
                                     [u'5000D31000FCBE3D',
                                      u'5000D31000FCBE35'],
                                     {u'21000024FF30441C':
                                      [u'5000D31000FCBE35'],
                                      u'21000024FF30441D':
                                      [u'5000D31000FCBE3D']}))
    def test_initialize_connection(self,
                                   mock_find_wwns,
                                   mock_map_volume,
                                   mock_find_volume,
                                   mock_create_server,
                                   mock_find_server,
                                   mock_find_sc,
                                   mock_close_connection,
                                   mock_open_connection,
                                   mock_init):
        volume = {'id': self.volume_name}
        connector = self.connector
        res = self.driver.initialize_connection(volume, connector)
        expected = {'data':
                    {'initiator_target_map':
                     {u'21000024FF30441C': [u'5000D31000FCBE35'],
                      u'21000024FF30441D': [u'5000D31000FCBE3D']},
                     'target_discovered': True,
                     'target_lun': 1,
                     'target_wwn':
                     [u'5000D31000FCBE3D', u'5000D31000FCBE35']},
                    'driver_volume_type': 'fibre_channel'}

        self.assertEqual(expected, res, 'Unexpected return data')
        # verify find_volume has been called and that is has been called twice
        mock_find_volume.assert_any_call(self.volume_name)
        assert mock_find_volume.call_count == 2

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_sc',
                       return_value=64702)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_server',
                       return_value=SCSERVER)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'map_volume',
                       return_value=MAPPING)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_wwns',
                       return_value=(None, [], {}))
    def test_initialize_connection_no_wwns(self,
                                           mock_find_wwns,
                                           mock_map_volume,
                                           mock_find_volume,
                                           mock_find_server,
                                           mock_find_sc,
                                           mock_close_connection,
                                           mock_open_connection,
                                           mock_init):
        volume = {'id': self.volume_name}
        connector = self.connector
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.initialize_connection,
                          volume,
                          connector)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_sc',
                       return_value=64702)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_server',
                       return_value=None)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'create_server_multiple_hbas',
                       return_value=None)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'map_volume',
                       return_value=MAPPING)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_wwns',
                       return_value=(None, [], {}))
    def test_initialize_connection_no_server(self,
                                             mock_find_wwns,
                                             mock_map_volume,
                                             mock_find_volume,
                                             mock_create_server,
                                             mock_find_server,
                                             mock_find_sc,
                                             mock_close_connection,
                                             mock_open_connection,
                                             mock_init):
        volume = {'id': self.volume_name}
        connector = self.connector
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.initialize_connection,
                          volume,
                          connector)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_sc',
                       return_value=64702)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_server',
                       return_value=SCSERVER)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_volume',
                       return_value=None)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'map_volume',
                       return_value=MAPPING)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_wwns',
                       return_value=(None, [], {}))
    def test_initialize_connection_vol_not_found(self,
                                                 mock_find_wwns,
                                                 mock_map_volume,
                                                 mock_find_volume,
                                                 mock_find_server,
                                                 mock_find_sc,
                                                 mock_close_connection,
                                                 mock_open_connection,
                                                 mock_init):
        volume = {'name': self.volume_name}
        connector = self.connector
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.initialize_connection,
                          volume,
                          connector)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_sc',
                       return_value=12345)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_server',
                       return_value=SCSERVER)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'map_volume',
                       return_value=None)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_wwns',
                       return_value=(None, [], {}))
    def test_initialize_connection_map_vol_fail(self,
                                                mock_find_wwns,
                                                mock_map_volume,
                                                mock_find_volume,
                                                mock_find_server,
                                                mock_find_sc,
                                                mock_close_connection,
                                                mock_open_connection,
                                                mock_init):
        # Test case where map_volume returns None (no mappings)
        volume = {'id': self.volume_name}
        connector = self.connector
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.initialize_connection,
                          volume,
                          connector)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_sc',
                       return_value=64702)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_server',
                       return_value=SCSERVER)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'unmap_volume',
                       return_value=True)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_wwns',
                       return_value=(1,
                                     [u'5000D31000FCBE3D',
                                      u'5000D31000FCBE35'],
                                     {u'21000024FF30441C':
                                      [u'5000D31000FCBE35'],
                                      u'21000024FF30441D':
                                      [u'5000D31000FCBE3D']}))
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'get_volume_count',
                       return_value=1)
    def test_terminate_connection(self,
                                  mock_get_volume_count,
                                  mock_find_wwns,
                                  mock_unmap_volume,
                                  mock_find_volume,
                                  mock_find_server,
                                  mock_find_sc,
                                  mock_close_connection,
                                  mock_open_connection,
                                  mock_init):
        volume = {'id': self.volume_name}
        connector = self.connector
        res = self.driver.terminate_connection(volume, connector)
        mock_unmap_volume.assert_called_once_with(self.VOLUME, self.SCSERVER)
        expected = {'driver_volume_type': 'fibre_channel',
                    'data': {}}
        self.assertEqual(expected, res, 'Unexpected return data')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_sc',
                       return_value=64702)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_server',
                       return_value=None)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'unmap_volume',
                       return_value=True)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_wwns',
                       return_value=(1,
                                     [u'5000D31000FCBE3D',
                                      u'5000D31000FCBE35'],
                                     {u'21000024FF30441C':
                                      [u'5000D31000FCBE35'],
                                      u'21000024FF30441D':
                                      [u'5000D31000FCBE3D']}))
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'get_volume_count',
                       return_value=1)
    def test_terminate_connection_no_server(self,
                                            mock_get_volume_count,
                                            mock_find_wwns,
                                            mock_unmap_volume,
                                            mock_find_volume,
                                            mock_find_server,
                                            mock_find_sc,
                                            mock_close_connection,
                                            mock_open_connection,
                                            mock_init):
        volume = {'name': self.volume_name}
        connector = self.connector
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.terminate_connection,
                          volume,
                          connector)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_sc',
                       return_value=64702)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_server',
                       return_value=SCSERVER)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_volume',
                       return_value=None)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'unmap_volume',
                       return_value=True)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_wwns',
                       return_value=(1,
                                     [u'5000D31000FCBE3D',
                                      u'5000D31000FCBE35'],
                                     {u'21000024FF30441C':
                                      [u'5000D31000FCBE35'],
                                      u'21000024FF30441D':
                                      [u'5000D31000FCBE3D']}))
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'get_volume_count',
                       return_value=1)
    def test_terminate_connection_no_volume(self,
                                            mock_get_volume_count,
                                            mock_find_wwns,
                                            mock_unmap_volume,
                                            mock_find_volume,
                                            mock_find_server,
                                            mock_find_sc,
                                            mock_close_connection,
                                            mock_open_connection,
                                            mock_init):
        volume = {'name': self.volume_name}
        connector = self.connector
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.terminate_connection,
                          volume,
                          connector)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_sc',
                       return_value=64702)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_server',
                       return_value=SCSERVER)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'unmap_volume',
                       return_value=True)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_wwns',
                       return_value=(None,
                                     [],
                                     {}))
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'get_volume_count',
                       return_value=1)
    def test_terminate_connection_no_wwns(self,
                                          mock_get_volume_count,
                                          mock_find_wwns,
                                          mock_unmap_volume,
                                          mock_find_volume,
                                          mock_find_server,
                                          mock_find_sc,
                                          mock_close_connection,
                                          mock_open_connection,
                                          mock_init):
        volume = {'name': self.volume_name}
        connector = self.connector
        # self.assertRaises(exception.VolumeBackendAPIException,
        #                  self.driver.terminate_connection,
        #                  volume,
        #                  connector)
        res = self.driver.terminate_connection(volume, connector)
        expected = {'driver_volume_type': 'fibre_channel',
                    'data': {}}
        self.assertEqual(expected, res, 'Unexpected return data')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_sc',
                       return_value=64702)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_server',
                       return_value=SCSERVER)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'unmap_volume',
                       return_value=False)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_wwns',
                       return_value=(1,
                                     [u'5000D31000FCBE3D',
                                      u'5000D31000FCBE35'],
                                     {u'21000024FF30441C':
                                      [u'5000D31000FCBE35'],
                                      u'21000024FF30441D':
                                      [u'5000D31000FCBE3D']}))
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'get_volume_count',
                       return_value=1)
    def test_terminate_connection_failure(self,
                                          mock_get_volume_count,
                                          mock_find_wwns,
                                          mock_unmap_volume,
                                          mock_find_volume,
                                          mock_find_server,
                                          mock_find_sc,
                                          mock_close_connection,
                                          mock_open_connection,
                                          mock_init):
        volume = {'name': self.volume_name}
        connector = self.connector
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.terminate_connection,
                          volume,
                          connector)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_sc',
                       return_value=64702)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_server',
                       return_value=SCSERVER)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'unmap_volume',
                       return_value=True)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_wwns',
                       return_value=(1,
                                     [u'5000D31000FCBE3D',
                                      u'5000D31000FCBE35'],
                                     {u'21000024FF30441C':
                                      [u'5000D31000FCBE35'],
                                      u'21000024FF30441D':
                                      [u'5000D31000FCBE3D']}))
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'get_volume_count',
                       return_value=0)
    def test_terminate_connection_vol_count_zero(self,
                                                 mock_get_volume_count,
                                                 mock_find_wwns,
                                                 mock_unmap_volume,
                                                 mock_find_volume,
                                                 mock_find_server,
                                                 mock_find_sc,
                                                 mock_close_connection,
                                                 mock_open_connection,
                                                 mock_init):
        # Test case where get_volume_count is zero
        volume = {'id': self.volume_name}
        connector = self.connector
        res = self.driver.terminate_connection(volume, connector)
        mock_unmap_volume.assert_called_once_with(self.VOLUME, self.SCSERVER)
        expected = {'data':
                    {'initiator_target_map':
                     {u'21000024FF30441C': [u'5000D31000FCBE35'],
                      u'21000024FF30441D': [u'5000D31000FCBE3D']},
                     'target_wwn':
                     [u'5000D31000FCBE3D', u'5000D31000FCBE35']},
                    'driver_volume_type': 'fibre_channel'}
        self.assertEqual(expected, res, 'Unexpected return data')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_sc',
                       return_value=64702)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'get_storage_usage',
                       return_value={'availableSpace': 100, 'freeSpace': 50})
    def test_update_volume_stats_with_refresh(self,
                                              mock_get_storage_usage,
                                              mock_find_sc,
                                              mock_close_connection,
                                              mock_open_connection,
                                              mock_init):
        stats = self.driver.get_volume_stats(True)
        self.assertEqual('FC', stats['storage_protocol'])
        mock_get_storage_usage.called_once_with(64702)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_sc',
                       return_value=64702)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'get_storage_usage',
                       return_value={'availableSpace': 100, 'freeSpace': 50})
    def test_get_volume_stats_no_refresh(self,
                                         mock_get_storage_usage,
                                         mock_find_sc,
                                         mock_close_connection,
                                         mock_open_connection,
                                         mock_init):
        stats = self.driver.get_volume_stats(False)
        self.assertEqual('FC', stats['storage_protocol'])
        assert mock_get_storage_usage.called is False
