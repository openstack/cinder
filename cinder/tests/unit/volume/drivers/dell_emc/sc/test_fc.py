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
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_volume
from cinder.volume.drivers.dell_emc.sc import storagecenter_api
from cinder.volume.drivers.dell_emc.sc import storagecenter_fc


# We patch these here as they are used by every test to keep
# from trying to contact a Dell Storage Center.
@mock.patch.object(storagecenter_api.HttpClient,
                   '__init__',
                   return_value=None)
@mock.patch.object(storagecenter_api.SCApi,
                   'open_connection')
@mock.patch.object(storagecenter_api.SCApi,
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
                u'notes': u'Created by Dell EMC Cinder Driver',
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
        self.configuration.excluded_domain_ip = None
        self.configuration.excluded_domain_ips = []
        self._context = context.get_admin_context()

        self.driver = storagecenter_fc.SCFCDriver(
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

        # Start with none.  Add in the specific tests later.
        # Mock tests bozo this.
        self.driver.backends = None
        self.driver.replication_enabled = False

        self.volid = '5729f1db-4c45-416c-bc15-c8ea13a4465d'
        self.volume_name = "volume" + self.volid
        self.connector = {'ip': '192.168.0.77',
                          'host': 'cinderfc-vm',
                          'wwnns': ['20000024ff30441c', '20000024ff30441d'],
                          'initiator': 'iqn.1993-08.org.debian:01:e1b1312f9e1',
                          'wwpns': ['21000024ff30441c', '21000024ff30441d']}

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_server',
                       return_value=None)
    @mock.patch.object(storagecenter_api.SCApi,
                       'create_server',
                       return_value=SCSERVER)
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(storagecenter_api.SCApi,
                       'get_volume',
                       return_value=VOLUME)
    @mock.patch.object(storagecenter_api.SCApi,
                       'map_volume',
                       return_value=MAPPING)
    @mock.patch.object(storagecenter_api.SCApi,
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
                                   mock_get_volume,
                                   mock_find_volume,
                                   mock_create_server,
                                   mock_find_server,
                                   mock_close_connection,
                                   mock_open_connection,
                                   mock_init):
        volume = {'id': fake.VOLUME_ID}
        connector = self.connector
        res = self.driver.initialize_connection(volume, connector)
        expected = {'data':
                    {'discard': True,
                     'initiator_target_map':
                     {u'21000024FF30441C': [u'5000D31000FCBE35'],
                      u'21000024FF30441D': [u'5000D31000FCBE3D']},
                     'target_discovered': True,
                     'target_lun': 1,
                     'target_wwn':
                     [u'5000D31000FCBE3D', u'5000D31000FCBE35']},
                    'driver_volume_type': 'fibre_channel'}

        self.assertEqual(expected, res, 'Unexpected return data')
        # verify find_volume has been called and that is has been called twice
        mock_find_volume.assert_called_once_with(fake.VOLUME_ID, None, False)
        mock_get_volume.assert_called_once_with(self.VOLUME[u'instanceId'])

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_server',
                       return_value=SCSERVER)
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(storagecenter_api.SCApi,
                       'get_volume',
                       return_value=VOLUME)
    @mock.patch.object(storagecenter_api.SCApi,
                       'map_volume',
                       return_value=MAPPING)
    @mock.patch.object(storagecenter_fc.SCFCDriver,
                       '_is_live_vol')
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_wwns')
    @mock.patch.object(storagecenter_fc.SCFCDriver,
                       'initialize_secondary')
    @mock.patch.object(storagecenter_api.SCApi,
                       'get_live_volume')
    def test_initialize_connection_live_vol(self,
                                            mock_get_live_volume,
                                            mock_initialize_secondary,
                                            mock_find_wwns,
                                            mock_is_live_volume,
                                            mock_map_volume,
                                            mock_get_volume,
                                            mock_find_volume,
                                            mock_find_server,
                                            mock_close_connection,
                                            mock_open_connection,
                                            mock_init):
        volume = {'id': fake.VOLUME_ID}
        connector = self.connector
        sclivevol = {'instanceId': '101.101',
                     'secondaryVolume': {'instanceId': '102.101',
                                         'instanceName': fake.VOLUME_ID},
                     'secondaryScSerialNumber': 102,
                     'secondaryRole': 'Secondary'}
        mock_is_live_volume.return_value = True
        mock_find_wwns.return_value = (
            1, [u'5000D31000FCBE3D', u'5000D31000FCBE35'],
            {u'21000024FF30441C': [u'5000D31000FCBE35'],
             u'21000024FF30441D': [u'5000D31000FCBE3D']})
        mock_initialize_secondary.return_value = (
            1, [u'5000D31000FCBE3E', u'5000D31000FCBE36'],
            {u'21000024FF30441E': [u'5000D31000FCBE36'],
             u'21000024FF30441F': [u'5000D31000FCBE3E']})
        mock_get_live_volume.return_value = sclivevol
        res = self.driver.initialize_connection(volume, connector)
        expected = {'data':
                    {'discard': True,
                     'initiator_target_map':
                     {u'21000024FF30441C': [u'5000D31000FCBE35'],
                      u'21000024FF30441D': [u'5000D31000FCBE3D'],
                      u'21000024FF30441E': [u'5000D31000FCBE36'],
                      u'21000024FF30441F': [u'5000D31000FCBE3E']},
                     'target_discovered': True,
                     'target_lun': 1,
                     'target_wwn': [u'5000D31000FCBE3D', u'5000D31000FCBE35',
                                    u'5000D31000FCBE3E', u'5000D31000FCBE36']},
                    'driver_volume_type': 'fibre_channel'}

        self.assertEqual(expected, res, 'Unexpected return data')
        # verify find_volume has been called and that is has been called twice
        mock_find_volume.assert_called_once_with(fake.VOLUME_ID, None, True)
        mock_get_volume.assert_called_once_with(self.VOLUME[u'instanceId'])

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_server',
                       return_value=SCSERVER)
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume')
    @mock.patch.object(storagecenter_api.SCApi,
                       'get_volume')
    @mock.patch.object(storagecenter_api.SCApi,
                       'map_volume',
                       return_value=MAPPING)
    @mock.patch.object(storagecenter_fc.SCFCDriver,
                       '_is_live_vol')
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_wwns')
    @mock.patch.object(storagecenter_fc.SCFCDriver,
                       'initialize_secondary')
    @mock.patch.object(storagecenter_api.SCApi,
                       'get_live_volume')
    def test_initialize_connection_live_vol_afo(self,
                                                mock_get_live_volume,
                                                mock_initialize_secondary,
                                                mock_find_wwns,
                                                mock_is_live_volume,
                                                mock_map_volume,
                                                mock_get_volume,
                                                mock_find_volume,
                                                mock_find_server,
                                                mock_close_connection,
                                                mock_open_connection,
                                                mock_init):
        volume = {'id': fake.VOLUME_ID, 'provider_id': '101.101'}
        scvol = {'instanceId': '102.101'}
        mock_find_volume.return_value = scvol
        mock_get_volume.return_value = scvol
        connector = self.connector
        sclivevol = {'instanceId': '101.10001',
                     'primaryVolume': {'instanceId': '102.101',
                                       'instanceName': fake.VOLUME_ID},
                     'primaryScSerialNumber': 102,
                     'secondaryVolume': {'instanceId': '101.101',
                                         'instanceName': fake.VOLUME_ID},
                     'secondaryScSerialNumber': 101,
                     'secondaryRole': 'Activated'}

        mock_is_live_volume.return_value = True
        mock_find_wwns.return_value = (
            1, [u'5000D31000FCBE3D', u'5000D31000FCBE35'],
            {u'21000024FF30441C': [u'5000D31000FCBE35'],
             u'21000024FF30441D': [u'5000D31000FCBE3D']})
        mock_get_live_volume.return_value = sclivevol
        res = self.driver.initialize_connection(volume, connector)
        expected = {'data':
                    {'discard': True,
                     'initiator_target_map':
                     {u'21000024FF30441C': [u'5000D31000FCBE35'],
                      u'21000024FF30441D': [u'5000D31000FCBE3D']},
                     'target_discovered': True,
                     'target_lun': 1,
                     'target_wwn': [u'5000D31000FCBE3D', u'5000D31000FCBE35']},
                    'driver_volume_type': 'fibre_channel'}

        self.assertEqual(expected, res, 'Unexpected return data')
        # verify find_volume has been called and that is has been called twice
        self.assertFalse(mock_initialize_secondary.called)
        mock_find_volume.assert_called_once_with(
            fake.VOLUME_ID, '101.101', True)
        mock_get_volume.assert_called_once_with('102.101')

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_server',
                       return_value=SCSERVER)
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(storagecenter_api.SCApi,
                       'get_volume',
                       return_value=VOLUME)
    @mock.patch.object(storagecenter_api.SCApi,
                       'map_volume',
                       return_value=MAPPING)
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_wwns',
                       return_value=(None, [], {}))
    def test_initialize_connection_no_wwns(self,
                                           mock_find_wwns,
                                           mock_map_volume,
                                           mock_get_volume,
                                           mock_find_volume,
                                           mock_find_server,
                                           mock_close_connection,
                                           mock_open_connection,
                                           mock_init):
        volume = {'id': fake.VOLUME_ID}
        connector = self.connector
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.initialize_connection,
                          volume,
                          connector)

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_server',
                       return_value=None)
    @mock.patch.object(storagecenter_api.SCApi,
                       'create_server',
                       return_value=None)
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(storagecenter_api.SCApi,
                       'map_volume',
                       return_value=MAPPING)
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_wwns',
                       return_value=(None, [], {}))
    def test_initialize_connection_no_server(self,
                                             mock_find_wwns,
                                             mock_map_volume,
                                             mock_find_volume,
                                             mock_create_server,
                                             mock_find_server,
                                             mock_close_connection,
                                             mock_open_connection,
                                             mock_init):
        volume = {'id': fake.VOLUME_ID}
        connector = self.connector
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.initialize_connection,
                          volume,
                          connector)

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_server',
                       return_value=SCSERVER)
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume',
                       return_value=None)
    @mock.patch.object(storagecenter_api.SCApi,
                       'map_volume',
                       return_value=MAPPING)
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_wwns',
                       return_value=(None, [], {}))
    def test_initialize_connection_vol_not_found(self,
                                                 mock_find_wwns,
                                                 mock_map_volume,
                                                 mock_find_volume,
                                                 mock_find_server,
                                                 mock_close_connection,
                                                 mock_open_connection,
                                                 mock_init):
        volume = {'id': fake.VOLUME_ID}
        connector = self.connector
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.initialize_connection,
                          volume,
                          connector)

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_server',
                       return_value=SCSERVER)
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(storagecenter_api.SCApi,
                       'map_volume',
                       return_value=None)
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_wwns',
                       return_value=(None, [], {}))
    def test_initialize_connection_map_vol_fail(self,
                                                mock_find_wwns,
                                                mock_map_volume,
                                                mock_find_volume,
                                                mock_find_server,
                                                mock_close_connection,
                                                mock_open_connection,
                                                mock_init):
        # Test case where map_volume returns None (no mappings)
        volume = {'id': fake.VOLUME_ID}
        connector = self.connector
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.initialize_connection,
                          volume,
                          connector)

    def test_initialize_secondary(self,
                                  mock_close_connection,
                                  mock_open_connection,
                                  mock_init):
        sclivevol = {'instanceId': '101.101',
                     'secondaryVolume': {'instanceId': '102.101',
                                         'instanceName': fake.VOLUME_ID},
                     'secondaryScSerialNumber': 102}

        mock_api = mock.MagicMock()
        mock_api.find_server = mock.MagicMock(return_value=self.SCSERVER)
        mock_api.map_secondary_volume = mock.MagicMock(
            return_value=self.VOLUME)
        find_wwns_ret = (1, [u'5000D31000FCBE3D', u'5000D31000FCBE35'],
                         {u'21000024FF30441C': [u'5000D31000FCBE35'],
                          u'21000024FF30441D': [u'5000D31000FCBE3D']})
        mock_api.find_wwns = mock.MagicMock(return_value=find_wwns_ret)
        mock_api.get_volume = mock.MagicMock(return_value=self.VOLUME)
        ret = self.driver.initialize_secondary(mock_api, sclivevol,
                                               ['wwn1', 'wwn2'])

        self.assertEqual(find_wwns_ret, ret)

    def test_initialize_secondary_create_server(self,
                                                mock_close_connection,
                                                mock_open_connection,
                                                mock_init):
        sclivevol = {'instanceId': '101.101',
                     'secondaryVolume': {'instanceId': '102.101',
                                         'instanceName': fake.VOLUME_ID},
                     'secondaryScSerialNumber': 102}
        mock_api = mock.MagicMock()
        mock_api.find_server = mock.MagicMock(return_value=None)
        mock_api.create_server = mock.MagicMock(return_value=self.SCSERVER)
        mock_api.map_secondary_volume = mock.MagicMock(
            return_value=self.VOLUME)
        find_wwns_ret = (1, [u'5000D31000FCBE3D', u'5000D31000FCBE35'],
                         {u'21000024FF30441C': [u'5000D31000FCBE35'],
                          u'21000024FF30441D': [u'5000D31000FCBE3D']})
        mock_api.find_wwns = mock.MagicMock(return_value=find_wwns_ret)
        mock_api.get_volume = mock.MagicMock(return_value=self.VOLUME)
        ret = self.driver.initialize_secondary(mock_api, sclivevol,
                                               ['wwn1', 'wwn2'])
        self.assertEqual(find_wwns_ret, ret)

    def test_initialize_secondary_no_server(self,
                                            mock_close_connection,
                                            mock_open_connection,
                                            mock_init):
        sclivevol = {'instanceId': '101.101',
                     'secondaryVolume': {'instanceId': '102.101',
                                         'instanceName': fake.VOLUME_ID},
                     'secondaryScSerialNumber': 102}
        mock_api = mock.MagicMock()
        mock_api.find_server = mock.MagicMock(return_value=None)
        mock_api.create_server = mock.MagicMock(return_value=None)
        ret = self.driver.initialize_secondary(mock_api, sclivevol,
                                               ['wwn1', 'wwn2'])
        expected = (None, [], {})
        self.assertEqual(expected, ret)

    def test_initialize_secondary_map_fail(self,
                                           mock_close_connection,
                                           mock_open_connection,
                                           mock_init):
        sclivevol = {'instanceId': '101.101',
                     'secondaryVolume': {'instanceId': '102.101',
                                         'instanceName': fake.VOLUME_ID},
                     'secondaryScSerialNumber': 102}
        mock_api = mock.MagicMock()
        mock_api.find_server = mock.MagicMock(return_value=self.SCSERVER)
        mock_api.map_secondary_volume = mock.MagicMock(return_value=None)
        ret = self.driver.initialize_secondary(mock_api, sclivevol,
                                               ['wwn1', 'wwn2'])
        expected = (None, [], {})
        self.assertEqual(expected, ret)

    def test_initialize_secondary_vol_not_found(self,
                                                mock_close_connection,
                                                mock_open_connection,
                                                mock_init):
        sclivevol = {'instanceId': '101.101',
                     'secondaryVolume': {'instanceId': '102.101',
                                         'instanceName': fake.VOLUME_ID},
                     'secondaryScSerialNumber': 102}
        mock_api = mock.MagicMock()
        mock_api.find_server = mock.MagicMock(return_value=self.SCSERVER)
        mock_api.map_secondary_volume = mock.MagicMock(
            return_value=self.VOLUME)
        mock_api.get_volume = mock.MagicMock(return_value=None)
        ret = self.driver.initialize_secondary(mock_api, sclivevol,
                                               ['wwn1', 'wwn2'])
        expected = (None, [], {})
        self.assertEqual(expected, ret)

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume')
    @mock.patch.object(storagecenter_api.SCApi,
                       'unmap_all')
    @mock.patch.object(storagecenter_fc.SCFCDriver,
                       '_is_live_vol')
    def test_force_detach(self, mock_is_live_vol, mock_unmap_all,
                          mock_find_volume, mock_close_connection,
                          mock_open_connection, mock_init):
        mock_is_live_vol.return_value = False
        scvol = {'instandId': '12345.1'}
        mock_find_volume.return_value = scvol
        mock_unmap_all.return_value = True
        volume = {'id': fake.VOLUME_ID}
        res = self.driver.force_detach(volume)
        mock_unmap_all.assert_called_once_with(scvol)
        expected = {'driver_volume_type': 'fibre_channel',
                    'data': {}}
        self.assertEqual(expected, res)
        mock_unmap_all.assert_called_once_with(scvol)

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume')
    @mock.patch.object(storagecenter_api.SCApi,
                       'unmap_all')
    @mock.patch.object(storagecenter_fc.SCFCDriver,
                       '_is_live_vol')
    def test_force_detach_fail(self, mock_is_live_vol, mock_unmap_all,
                               mock_find_volume, mock_close_connection,
                               mock_open_connection, mock_init):
        mock_is_live_vol.return_value = False
        scvol = {'instandId': '12345.1'}
        mock_find_volume.return_value = scvol
        mock_unmap_all.return_value = False
        volume = {'id': fake.VOLUME_ID}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.force_detach, volume)
        mock_unmap_all.assert_called_once_with(scvol)

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume')
    @mock.patch.object(storagecenter_api.SCApi,
                       'unmap_all')
    @mock.patch.object(storagecenter_fc.SCFCDriver,
                       '_is_live_vol')
    @mock.patch.object(storagecenter_fc.SCFCDriver,
                       'terminate_secondary')
    @mock.patch.object(storagecenter_api.SCApi,
                       'get_live_volume')
    def test_force_detach_lv(self, mock_get_live_volume,
                             mock_terminate_secondary, mock_is_live_vol,
                             mock_unmap_all, mock_find_volume,
                             mock_close_connection, mock_open_connection,
                             mock_init):
        mock_is_live_vol.return_value = True
        scvol = {'instandId': '12345.1'}
        mock_find_volume.return_value = scvol
        sclivevol = {'instandId': '12345.1.0'}
        mock_get_live_volume.return_value = sclivevol
        mock_terminate_secondary.return_value = True
        volume = {'id': fake.VOLUME_ID}
        mock_unmap_all.return_value = True
        res = self.driver.force_detach(volume)
        mock_unmap_all.assert_called_once_with(scvol)
        expected = {'driver_volume_type': 'fibre_channel', 'data': {}}
        self.assertEqual(expected, res)
        self.assertEqual(1, mock_terminate_secondary.call_count)
        mock_unmap_all.assert_called_once_with(scvol)

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume')
    @mock.patch.object(storagecenter_fc.SCFCDriver,
                       '_is_live_vol')
    def test_force_detach_vol_not_found(self,
                                        mock_is_live_vol, mock_find_volume,
                                        mock_close_connection,
                                        mock_open_connection, mock_init):
        mock_is_live_vol.return_value = False
        mock_find_volume.return_value = None
        volume = {'id': fake.VOLUME_ID}
        res = self.driver.force_detach(volume)
        expected = {'driver_volume_type': 'fibre_channel', 'data': {}}
        self.assertEqual(expected, res)

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_server',
                       return_value=SCSERVER)
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(storagecenter_api.SCApi,
                       'unmap_volume',
                       return_value=True)
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_wwns',
                       return_value=(1,
                                     [u'5000D31000FCBE3D',
                                      u'5000D31000FCBE35'],
                                     {u'21000024FF30441C':
                                      [u'5000D31000FCBE35'],
                                      u'21000024FF30441D':
                                      [u'5000D31000FCBE3D']}))
    @mock.patch.object(storagecenter_api.SCApi,
                       'get_volume_count',
                       return_value=1)
    def test_terminate_connection(self,
                                  mock_get_volume_count,
                                  mock_find_wwns,
                                  mock_unmap_volume,
                                  mock_find_volume,
                                  mock_find_server,
                                  mock_close_connection,
                                  mock_open_connection,
                                  mock_init):
        volume = {'id': fake.VOLUME_ID}
        connector = self.connector
        res = self.driver.terminate_connection(volume, connector)
        mock_unmap_volume.assert_called_once_with(self.VOLUME, self.SCSERVER)
        expected = {'driver_volume_type': 'fibre_channel',
                    'data': {}}
        self.assertEqual(expected, res, 'Unexpected return data')

    @mock.patch.object(storagecenter_fc.SCFCDriver,
                       'force_detach')
    def test_terminate_connection_none_connector(self, mock_force_detach,
                                                 mock_close_connection,
                                                 mock_open_connection,
                                                 mock_init):
        volume = {'id': fake.VOLUME_ID}
        self.driver.terminate_connection(volume, None)
        mock_force_detach.assert_called_once_with(volume)

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_server',
                       return_value=SCSERVER)
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(storagecenter_api.SCApi,
                       'unmap_volume',
                       return_value=True)
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_wwns',
                       return_value=(1,
                                     [u'5000D31000FCBE3D',
                                      u'5000D31000FCBE35'],
                                     {u'21000024FF30441C':
                                      [u'5000D31000FCBE35'],
                                      u'21000024FF30441D':
                                      [u'5000D31000FCBE3D']}))
    @mock.patch.object(storagecenter_api.SCApi,
                       'get_volume_count',
                       return_value=1)
    @mock.patch.object(storagecenter_fc.SCFCDriver,
                       '_is_live_vol')
    @mock.patch.object(storagecenter_fc.SCFCDriver,
                       'terminate_secondary')
    def test_terminate_connection_live_vol(self,
                                           mock_terminate_secondary,
                                           mock_is_live_vol,
                                           mock_get_volume_count,
                                           mock_find_wwns,
                                           mock_unmap_volume,
                                           mock_find_volume,
                                           mock_find_server,
                                           mock_close_connection,
                                           mock_open_connection,
                                           mock_init):
        volume = {'id': fake.VOLUME_ID}
        connector = self.connector
        mock_terminate_secondary.return_value = (None, [], {})
        mock_is_live_vol.return_value = True
        res = self.driver.terminate_connection(volume, connector)
        mock_unmap_volume.assert_called_once_with(self.VOLUME, self.SCSERVER)
        expected = {'driver_volume_type': 'fibre_channel',
                    'data': {}}
        self.assertEqual(expected, res, 'Unexpected return data')

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_server',
                       return_value=None)
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(storagecenter_api.SCApi,
                       'unmap_volume',
                       return_value=True)
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_wwns',
                       return_value=(1,
                                     [u'5000D31000FCBE3D',
                                      u'5000D31000FCBE35'],
                                     {u'21000024FF30441C':
                                      [u'5000D31000FCBE35'],
                                      u'21000024FF30441D':
                                      [u'5000D31000FCBE3D']}))
    @mock.patch.object(storagecenter_api.SCApi,
                       'get_volume_count',
                       return_value=1)
    def test_terminate_connection_no_server(self,
                                            mock_get_volume_count,
                                            mock_find_wwns,
                                            mock_unmap_volume,
                                            mock_find_volume,
                                            mock_find_server,
                                            mock_close_connection,
                                            mock_open_connection,
                                            mock_init):
        volume = {'id': fake.VOLUME_ID}
        connector = self.connector
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.terminate_connection,
                          volume,
                          connector)

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_server',
                       return_value=SCSERVER)
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume',
                       return_value=None)
    @mock.patch.object(storagecenter_api.SCApi,
                       'unmap_volume',
                       return_value=True)
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_wwns',
                       return_value=(1,
                                     [u'5000D31000FCBE3D',
                                      u'5000D31000FCBE35'],
                                     {u'21000024FF30441C':
                                      [u'5000D31000FCBE35'],
                                      u'21000024FF30441D':
                                      [u'5000D31000FCBE3D']}))
    @mock.patch.object(storagecenter_api.SCApi,
                       'get_volume_count',
                       return_value=1)
    def test_terminate_connection_no_volume(self,
                                            mock_get_volume_count,
                                            mock_find_wwns,
                                            mock_unmap_volume,
                                            mock_find_volume,
                                            mock_find_server,
                                            mock_close_connection,
                                            mock_open_connection,
                                            mock_init):
        volume = {'id': fake.VOLUME_ID}
        connector = self.connector
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.terminate_connection,
                          volume,
                          connector)

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_server',
                       return_value=SCSERVER)
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(storagecenter_api.SCApi,
                       'unmap_volume',
                       return_value=True)
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_wwns',
                       return_value=(None,
                                     [],
                                     {}))
    @mock.patch.object(storagecenter_api.SCApi,
                       'get_volume_count',
                       return_value=1)
    def test_terminate_connection_no_wwns(self,
                                          mock_get_volume_count,
                                          mock_find_wwns,
                                          mock_unmap_volume,
                                          mock_find_volume,
                                          mock_find_server,
                                          mock_close_connection,
                                          mock_open_connection,
                                          mock_init):
        volume = {'id': fake.VOLUME_ID}
        connector = self.connector
        res = self.driver.terminate_connection(volume, connector)
        expected = {'driver_volume_type': 'fibre_channel',
                    'data': {}}
        self.assertEqual(expected, res, 'Unexpected return data')

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_server',
                       return_value=SCSERVER)
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(storagecenter_api.SCApi,
                       'unmap_volume',
                       return_value=False)
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_wwns',
                       return_value=(1,
                                     [u'5000D31000FCBE3D',
                                      u'5000D31000FCBE35'],
                                     {u'21000024FF30441C':
                                      [u'5000D31000FCBE35'],
                                      u'21000024FF30441D':
                                      [u'5000D31000FCBE3D']}))
    @mock.patch.object(storagecenter_api.SCApi,
                       'get_volume_count',
                       return_value=1)
    def test_terminate_connection_failure(self,
                                          mock_get_volume_count,
                                          mock_find_wwns,
                                          mock_unmap_volume,
                                          mock_find_volume,
                                          mock_find_server,
                                          mock_close_connection,
                                          mock_open_connection,
                                          mock_init):
        volume = {'id': fake.VOLUME_ID}
        connector = self.connector
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.terminate_connection,
                          volume,
                          connector)

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_server',
                       return_value=SCSERVER)
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(storagecenter_api.SCApi,
                       'unmap_volume',
                       return_value=True)
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_wwns',
                       return_value=(1,
                                     [u'5000D31000FCBE3D',
                                      u'5000D31000FCBE35'],
                                     {u'21000024FF30441C':
                                      [u'5000D31000FCBE35'],
                                      u'21000024FF30441D':
                                      [u'5000D31000FCBE3D']}))
    @mock.patch.object(storagecenter_api.SCApi,
                       'get_volume_count',
                       return_value=0)
    def test_terminate_connection_vol_count_zero(self,
                                                 mock_get_volume_count,
                                                 mock_find_wwns,
                                                 mock_unmap_volume,
                                                 mock_find_volume,
                                                 mock_find_server,
                                                 mock_close_connection,
                                                 mock_open_connection,
                                                 mock_init):
        # Test case where get_volume_count is zero
        volume = {'id': fake.VOLUME_ID}
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

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_server',
                       return_value=SCSERVER)
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(storagecenter_api.SCApi,
                       'unmap_volume',
                       return_value=True)
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_wwns',
                       return_value=(1,
                                     [u'5000D31000FCBE3D',
                                      u'5000D31000FCBE35'],
                                     {u'21000024FF30441C':
                                      [u'5000D31000FCBE35'],
                                      u'21000024FF30441D':
                                      [u'5000D31000FCBE3D']}))
    @mock.patch.object(storagecenter_api.SCApi,
                       'get_volume_count',
                       return_value=1)
    def test_terminate_connection_multiattached_host(self,
                                                     mock_get_volume_count,
                                                     mock_find_wwns,
                                                     mock_unmap_volume,
                                                     mock_find_volume,
                                                     mock_find_server,
                                                     mock_close_connection,
                                                     mock_open_connection,
                                                     mock_init):
        connector = self.connector

        attachment1 = fake_volume.volume_attachment_ovo(self._context)
        attachment1.connector = connector
        attachment1.attached_host = connector['host']
        attachment1.attach_status = 'attached'

        attachment2 = fake_volume.volume_attachment_ovo(self._context)
        attachment2.connector = connector
        attachment2.attached_host = connector['host']
        attachment2.attach_status = 'attached'

        vol = fake_volume.fake_volume_obj(self._context)
        vol.multiattach = True
        vol.volume_attachment.objects.append(attachment1)
        vol.volume_attachment.objects.append(attachment2)

        self.driver.terminate_connection(vol, connector)
        mock_unmap_volume.assert_not_called()

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_server',
                       return_value=SCSERVER)
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(storagecenter_api.SCApi,
                       'unmap_volume',
                       return_value=True)
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_wwns',
                       return_value=(1,
                                     [u'5000D31000FCBE3D',
                                      u'5000D31000FCBE35'],
                                     {u'21000024FF30441C':
                                      [u'5000D31000FCBE35'],
                                      u'21000024FF30441D':
                                      [u'5000D31000FCBE3D']}))
    @mock.patch.object(storagecenter_api.SCApi,
                       'get_volume_count',
                       return_value=1)
    def test_terminate_connection_multiattached_diffhost(self,
                                                         mock_get_volume_count,
                                                         mock_find_wwns,
                                                         mock_unmap_volume,
                                                         mock_find_volume,
                                                         mock_find_server,
                                                         mock_close_connection,
                                                         mock_open_connection,
                                                         mock_init):
        connector = self.connector

        attachment1 = fake_volume.volume_attachment_ovo(self._context)
        attachment1.connector = connector
        attachment1.attached_host = connector['host']
        attachment1.attach_status = 'attached'

        attachment2 = fake_volume.volume_attachment_ovo(self._context)
        attachment2.connector = connector
        attachment2.attached_host = 'host2'
        attachment2.attach_status = 'attached'

        vol = fake_volume.fake_volume_obj(self._context)
        vol.multiattach = True
        vol.volume_attachment.objects.append(attachment1)
        vol.volume_attachment.objects.append(attachment2)

        self.driver.terminate_connection(vol, connector)
        mock_unmap_volume.assert_called_once_with(self.VOLUME, self.SCSERVER)

    def test_terminate_secondary(self,
                                 mock_close_connection,
                                 mock_open_connection,
                                 mock_init):
        mock_api = mock.MagicMock()
        mock_api.find_server = mock.MagicMock(return_value=self.SCSERVER)
        mock_api.get_volume = mock.MagicMock(return_value=self.VOLUME)
        mock_api.find_wwns = mock.MagicMock(return_value=(None, [], {}))
        mock_api.unmap_volume = mock.MagicMock(return_value=True)
        sclivevol = {'instanceId': '101.101',
                     'secondaryVolume': {'instanceId': '102.101',
                                         'instanceName': fake.VOLUME_ID},
                     'secondaryScSerialNumber': 102}
        ret = self.driver.terminate_secondary(mock_api, sclivevol,
                                              ['wwn1', 'wwn2'])
        expected = (None, [], {})
        self.assertEqual(expected, ret)

    @mock.patch.object(storagecenter_api.SCApi,
                       'get_storage_usage',
                       return_value={'availableSpace': 100, 'freeSpace': 50})
    def test_update_volume_stats_with_refresh(self,
                                              mock_get_storage_usage,
                                              mock_close_connection,
                                              mock_open_connection,
                                              mock_init):
        stats = self.driver.get_volume_stats(True)
        self.assertEqual('FC', stats['storage_protocol'])
        mock_get_storage_usage.assert_called_once_with()

    @mock.patch.object(storagecenter_api.SCApi,
                       'get_storage_usage',
                       return_value={'availableSpace': 100, 'freeSpace': 50})
    def test_get_volume_stats_no_refresh(self,
                                         mock_get_storage_usage,
                                         mock_close_connection,
                                         mock_open_connection,
                                         mock_init):
        stats = self.driver.get_volume_stats(False)
        self.assertEqual('FC', stats['storage_protocol'])
        mock_get_storage_usage.assert_not_called()
