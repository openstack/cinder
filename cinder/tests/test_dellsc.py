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

from oslo_log import log as logging

from cinder import context
from cinder import exception
from cinder import test
from cinder.volume.drivers.dell import dell_storagecenter_api
from cinder.volume.drivers.dell import dell_storagecenter_iscsi

import mock

import uuid


LOG = logging.getLogger(__name__)

# We patch these here as they are used by every test to keep
# from trying to contact a Dell Storage Center.


@mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                   '__init__',
                   return_value=None)
@mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                   'open_connection')
@mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                   'close_connection')
class DellSCSanISCSIDriverTestCase(test.TestCase):

    VOLUME = {u'instanceId': u'64702.3494',
              u'scSerialNumber': 64702,
              u'replicationSource': False,
              u'liveVolume': False,
              u'vpdId': 3496,
              u'objectType': u'ScVolume',
              u'index': 3494,
              u'volumeFolderPath': u'devstackvol/fcvm/',
              u'hostCacheEnabled': False,
              u'usedByLegacyFluidFsNasVolume': False,
              u'inRecycleBin': False,
              u'volumeFolderIndex': 17,
              u'instanceName': u'volume-37883deb-85cd-426a-9a98-62eaad8671ea',
              u'statusMessage': u'',
              u'status': u'Up',
              u'storageType': {u'instanceId': u'64702.1',
                               u'instanceName': u'Assigned - Redundant - 2 MB',
                               u'objectType': u'ScStorageType'},
              u'cmmDestination': False,
              u'replicationDestination': False,
              u'volumeFolder': {u'instanceId': u'64702.17',
                                u'instanceName': u'fcvm',
                                u'objectType': u'ScVolumeFolder'},
              u'deviceId': u'6000d31000fcbe000000000000000da8',
              u'active': True,
              u'portableVolumeDestination': False,
              u'deleteAllowed': True,
              u'name': u'volume-37883deb-85cd-426a-9a98-62eaad8671ea',
              u'scName': u'Storage Center 64702',
              u'secureDataUsed': False,
              u'serialNumber': u'0000fcbe-00000da8',
              u'replayAllowed': True,
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
                u'serverFolderPath': u'devstacksrv/',
                u'portType': [u'FibreChannel'],
                u'type': u'Physical',
                u'statusMessage': u'Only 5 of 6 expected paths are up',
                u'status': u'Degraded',
                u'scSerialNumber': 64702,
                u'serverFolder': {u'instanceId': u'64702.4',
                                  u'instanceName': u'devstacksrv',
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

    MAPPINGS = [{u'profile': {u'instanceId': u'64702.104',
                              u'instanceName': u'92-30',
                              u'objectType': u'ScMappingProfile'},
                 u'status': u'Down',
                 u'statusMessage': u'',
                 u'instanceId': u'64702.969.64702',
                 u'scName': u'Storage Center 64702',
                 u'scSerialNumber': 64702,
                 u'controller': {u'instanceId': u'64702.64702',
                                 u'instanceName': u'SN 64702',
                                 u'objectType': u'ScController'},
                 u'server': {u'instanceId': u'64702.30',
                             u'instanceName':
                             u'Server_iqn.1993-08.org.debian:01:3776df826e4f',
                             u'objectType': u'ScPhysicalServer'},
                 u'volume': {u'instanceId': u'64702.92',
                             u'instanceName':
                             u'volume-74a21934-60ad-4cf2-b89b-1f0dda309ddf',
                             u'objectType': u'ScVolume'},
                 u'readOnly': False,
                 u'lun': 1,
                 u'lunUsed': [1],
                 u'serverHba': {u'instanceId': u'64702.3454975614',
                                u'instanceName':
                                u'iqn.1993-08.org.debian:01:3776df826e4f',
                                u'objectType': u'ScServerHba'},
                 u'path': {u'instanceId': u'64702.64702.64702.31.8',
                           u'instanceName':
                           u'iqn.1993-08.org.debian:'
                           '01:3776df826e4f-5000D31000FCBE43',
                           u'objectType': u'ScServerHbaPath'},
                 u'controllerPort': {u'instanceId':
                                     u'64702.5764839588723736131.91',
                                     u'instanceName': u'5000D31000FCBE43',
                                     u'objectType': u'ScControllerPort'},
                 u'instanceName': u'64702-969',
                 u'transport': u'Iscsi',
                 u'objectType': u'ScMapping'}]

    RPLAY = {u'scSerialNumber': 64702,
             u'globalIndex': u'64702-46-250',
             u'description': u'Cinder Clone Replay',
             u'parent': {u'instanceId': u'64702.46.249',
                         u'instanceName': u'64702-46-249',
                         u'objectType': u'ScReplay'},
             u'instanceId': u'64702.46.250',
             u'scName': u'Storage Center 64702',
             u'consistent': False,
             u'expires': True,
             u'freezeTime': u'12/09/2014 03:52:08 PM',
             u'createVolume': {u'instanceId': u'64702.46',
                               u'instanceName':
                               u'volume-ff9589d3-2d41-48d5-9ef5-2713a875e85b',
                               u'objectType': u'ScVolume'},
             u'expireTime': u'12/09/2014 04:52:08 PM',
             u'source': u'Manual',
             u'spaceRecovery': False,
             u'writesHeldDuration': 7910,
             u'active': False,
             u'markedForExpiration': False,
             u'objectType': u'ScReplay',
             u'instanceName': u'12/09/2014 03:52:08 PM',
             u'size': u'0.0 Bytes'
             }

    IQN = 'iqn.2002-03.com.compellent:5000D31000000001'

    ISCSI_PROPERTIES = {'access_mode': 'rw',
                        'target_discovered': False,
                        'target_iqns':
                        [u'iqn.2002-03.com.compellent:5000d31000fcbe43'],
                        'target_luns': [1],
                        'target_portals': [u'192.168.0.21:3260']}

    ISCSI_PROPERTIES_EMPTY = {'access_mode': 'rw',
                              'target_discovered': False,
                              'target_iqns': [],
                              'target_luns': [],
                              'target_portals': []}

    def setUp(self):
        super(DellSCSanISCSIDriverTestCase, self).setUp()

        # configuration is a mock.  A mock is pretty much a blank
        # slate.  I believe mock's done in setup are not happy time
        # mocks.  So we just do a few things like driver config here.
        self.configuration = mock.Mock()

        self.configuration.san_is_local = False
        self.configuration.san_ip = "192.168.0.1"
        self.configuration.san_login = "admin"
        self.configuration.san_password = "mmm"
        self.configuration.dell_sc_ssn = 12345
        self.configuration.dell_sc_server_folder = 'opnstktst'
        self.configuration.dell_sc_volume_folder = 'opnstktst'
        self.configuration.dell_sc_api_port = 3033
        self.configuration.iscsi_ip_address = '192.168.1.1'
        self.configuration.iscsi_port = 3260
        self._context = context.get_admin_context()

        self.driver = dell_storagecenter_iscsi.DellStorageCenterISCSIDriver(
            configuration=self.configuration)

        self.driver.do_setup(None)

        self.driver._stats = {'QoS_support': False,
                              'volume_backend_name': 'dell-1',
                              'free_capacity_gb': 12123,
                              'driver_version': '1.0.1',
                              'total_capacity_gb': 12388,
                              'reserved_percentage': 0,
                              'vendor_name': 'Dell',
                              'storage_protocol': 'iSCSI'}

        self.volid = str(uuid.uuid4())
        self.volume_name = "volume" + self.volid
        self.connector = {
            'ip': '10.0.0.2',
            'initiator': 'iqn.1993-08.org.debian:01:2227dab76162',
            'host': 'fakehost'}
        self.connector_multipath = {
            'ip': '10.0.0.2',
            'initiator': 'iqn.1993-08.org.debian:01:2227dab76162',
            'host': 'fakehost',
            'multipath': True}
        self.access_record_output = [
            "ID  Initiator       Ipaddress     AuthMethod UserName   Apply-To",
            "--- --------------- ------------- ---------- ---------- --------",
            "1   iqn.1993-08.org.debian:01:222 *.*.*.*       none        both",
            "       7dab76162"]

        self.fake_iqn = 'iqn.2002-03.com.compellent:5000D31000000001'
        self.properties = {
            'target_discoverd': True,
            'target_portal': '%s:3260'
            % self.driver.configuration.dell_sc_iscsi_ip,
            'target_iqn': self.fake_iqn,
            'volume_id': 1}
        self._model_update = {
            'provider_location': "%s:3260,1 %s 0"
            % (self.driver.configuration.dell_sc_iscsi_ip,
               self.fake_iqn)
            #                              ,
            #            'provider_auth': 'CHAP %s %s' % (
            #                self.configuration.eqlx_chap_login,
            #                self.configuration.eqlx_chap_password)
        }

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'create_volume',
                       return_value=VOLUME)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_sc',
                       return_value=12345)
    def test_create_volume(self,
                           mock_find_sc,
                           mock_create_volume,
                           mock_close_connection,
                           mock_open_connection,
                           mock_init):
        volume = {'id': self.volume_name, 'size': 1}
        self.driver.create_volume(volume)
        mock_create_volume.assert_called_once_with(self.volume_name,
                                                   1,
                                                   12345,
                                                   u'opnstktst')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'create_volume',
                       return_value=None)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_sc',
                       return_value=12345)
    def test_create_volume_failure(self,
                                   mock_find_sc,
                                   mock_create_volume,
                                   mock_close_connection,
                                   mock_open_connection,
                                   mock_init):
        volume = {'id': self.volume_name, 'size': 1}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume, volume)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'delete_volume',
                       return_value=True)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_sc',
                       return_value=12345)
    def test_delete_volume(self,
                           mock_find_sc,
                           mock_delete_volume,
                           mock_close_connection,
                           mock_open_connection,
                           mock_init):
        volume = {'id': self.volume_name, 'size': 1}
        self.driver.delete_volume(volume)
        mock_delete_volume.assert_called_once_with(12345, self.volume_name)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'delete_volume',
                       return_value=False)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_sc',
                       return_value=12345)
    def test_delete_volume_failure(self,
                                   mock_find_sc,
                                   mock_delete_volume,
                                   mock_close_connection,
                                   mock_open_connection,
                                   mock_init):
        volume = {'id': self.volume_name, 'size': 1}
        self.assertRaises(exception.VolumeIsBusy,
                          self.driver.delete_volume,
                          volume)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_sc',
                       return_value=12345)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_server',
                       return_value=None)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'create_server',
                       return_value=SCSERVER)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'map_volume',
                       return_value=MAPPINGS[0])
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_iscsi_properties',
                       return_value=(0, ISCSI_PROPERTIES))
    def test_initialize_connection(self,
                                   mock_find_iscsi_props,
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
        data = self.driver.initialize_connection(volume, connector)
        self.assertEqual(data['driver_volume_type'], 'iscsi')
        # verify find_volume has been called and that is has been called twice
        mock_find_volume.assert_any_call(12345, self.volume_name)
        assert mock_find_volume.call_count == 2
        expected = {'data':
                    {'access_mode': 'rw',
                        'target_discovered': False,
                        'target_iqn':
                            u'iqn.2002-03.com.compellent:5000d31000fcbe43',
                        'target_lun': 1,
                        'target_portal': u'192.168.0.21:3260'},
                    'driver_volume_type': 'iscsi'}
        self.assertEqual(expected, data, 'Unexpected return value')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_sc',
                       return_value=12345)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_server',
                       return_value=None)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'create_server',
                       return_value=SCSERVER)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'map_volume',
                       return_value=MAPPINGS[0])
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_iscsi_properties',
                       return_value=(0, ISCSI_PROPERTIES))
    def test_initialize_connection_multi_path(self,
                                              mock_find_iscsi_props,
                                              mock_map_volume,
                                              mock_find_volume,
                                              mock_create_server,
                                              mock_find_server,
                                              mock_find_sc,
                                              mock_close_connection,
                                              mock_open_connection,
                                              mock_init):
        # Test case where connection is multipath
        volume = {'id': self.volume_name}
        connector = self.connector_multipath

        data = self.driver.initialize_connection(volume, connector)
        self.assertEqual(data['driver_volume_type'], 'iscsi')
        # verify find_volume has been called and that is has been called twice
        mock_find_volume.assert_any_call(12345, self.volume_name)
        assert mock_find_volume.call_count == 2
        expected = {'data':
                    {'access_mode': 'rw',
                     'target_discovered': False,
                     'target_iqns':
                        [u'iqn.2002-03.com.compellent:5000d31000fcbe43'],
                     'target_luns': [1],
                     'target_portals': [u'192.168.0.21:3260']},
                    'driver_volume_type': 'iscsi'}
        self.assertEqual(expected, data, 'Unexpected return value')

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
                       return_value=MAPPINGS)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_iscsi_properties',
                       return_value=(0, ISCSI_PROPERTIES_EMPTY))
    def test_initialize_connection_no_iqn(self,
                                          mock_find_iscsi_properties,
                                          mock_map_volume,
                                          mock_find_volume,
                                          mock_find_server,
                                          mock_find_sc,
                                          mock_close_connection,
                                          mock_open_connection,
                                          mock_init):
        volume = {'id': self.volume_name}
        connector = {}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.initialize_connection,
                          volume,
                          connector)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_sc',
                       return_value=12345)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_server',
                       return_value=None)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'create_server',
                       return_value=None)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'map_volume',
                       return_value=MAPPINGS)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_iscsi_properties',
                       return_value=(0, ISCSI_PROPERTIES_EMPTY))
    def test_initialize_connection_no_server(self,
                                             mock_find_iscsi_properties,
                                             mock_map_volume,
                                             mock_find_volume,
                                             mock_create_server,
                                             mock_find_server,
                                             mock_find_sc,
                                             mock_close_connection,
                                             mock_open_connection,
                                             mock_init):
        volume = {'id': self.volume_name}
        connector = {}
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
                       return_value=None)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'map_volume',
                       return_value=MAPPINGS)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_iscsi_properties',
                       return_value=(0, ISCSI_PROPERTIES_EMPTY))
    def test_initialize_connection_vol_not_found(self,
                                                 mock_find_iscsi_properties,
                                                 mock_map_volume,
                                                 mock_find_volume,
                                                 mock_find_server,
                                                 mock_find_sc,
                                                 mock_close_connection,
                                                 mock_open_connection,
                                                 mock_init):
        volume = {'name': self.volume_name}
        connector = {}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.initialize_connection,
                          volume,
                          connector)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_sc',
                       return_value=12345)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_server',
                       return_value=None)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'create_server',
                       return_value=SCSERVER)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'map_volume',
                       return_value=None)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_iscsi_properties',
                       return_value=(0, ISCSI_PROPERTIES))
    def test_initialize_connection_map_vol_fail(self,
                                                mock_find_iscsi_props,
                                                mock_map_volume,
                                                mock_find_volume,
                                                mock_create_server,
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
                       return_value=12345)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_server',
                       return_value=SCSERVER)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'unmap_volume',
                       return_value=True)
    def test_terminate_connection(self,
                                  mock_unmap_volume,
                                  mock_find_volume,
                                  mock_find_server,
                                  mock_find_sc,
                                  mock_close_connection,
                                  mock_open_connection,
                                  mock_init):
        volume = {'id': self.volume_name}
        connector = self.connector
        self.driver.terminate_connection(volume, connector)
        mock_unmap_volume.assert_called_once_with(self.VOLUME, self.SCSERVER)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_sc',
                       return_value=12345)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_server',
                       return_value=None)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'unmap_volume',
                       return_value=True)
    def test_terminate_connection_no_server(self,
                                            mock_unmap_volume,
                                            mock_find_volume,
                                            mock_find_server,
                                            mock_find_sc,
                                            mock_close_connection,
                                            mock_open_connection,
                                            mock_init):
        volume = {'name': self.volume_name}
        connector = {'initiator': ''}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.terminate_connection,
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
                       return_value=None)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'unmap_volume',
                       return_value=True)
    def test_terminate_connection_no_volume(self,
                                            mock_unmap_volume,
                                            mock_find_volume,
                                            mock_find_server,
                                            mock_find_sc,
                                            mock_close_connection,
                                            mock_open_connection,
                                            mock_init):
        volume = {'name': self.volume_name}
        connector = {'initiator': ''}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.terminate_connection,
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
                       'unmap_volume',
                       return_value=False)
    def test_terminate_connection_failure(self,
                                          mock_unmap_volume,
                                          mock_find_volume,
                                          mock_find_server,
                                          mock_find_sc,
                                          mock_close_connection,
                                          mock_open_connection,
                                          mock_init):
        volume = {'name': self.volume_name}
        connector = {'initiator': ''}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.terminate_connection,
                          volume,
                          connector)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_sc',
                       return_value=12345)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'create_replay',
                       return_value='fake')
    def test_create_snapshot(self,
                             mock_create_replay,
                             mock_find_volume,
                             mock_find_sc,
                             mock_close_connection,
                             mock_open_connection,
                             mock_init):
        snapshot = {'volume_id': self.volume_name,
                    'id': self.volume_name}
        self.driver.create_snapshot(snapshot)
        self.assertEqual('available', snapshot['status'])

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_sc',
                       return_value=12345)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_volume',
                       return_value=None)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'create_replay',
                       return_value=None)
    def test_create_snapshot_no_volume(self,
                                       mock_create_replay,
                                       mock_find_volume,
                                       mock_find_sc,
                                       mock_close_connection,
                                       mock_open_connection,
                                       mock_init):
        snapshot = {'volume_id': self.volume_name,
                    'id': self.volume_name}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_snapshot,
                          snapshot)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_sc',
                       return_value=12345)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'create_replay',
                       return_value=None)
    def test_create_snapshot_failure(self,
                                     mock_create_replay,
                                     mock_find_volume,
                                     mock_find_sc,
                                     mock_close_connection,
                                     mock_open_connection,
                                     mock_init):
        snapshot = {'volume_id': self.volume_name,
                    'id': self.volume_name}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_snapshot,
                          snapshot)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_sc',
                       return_value=12345)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_replay',
                       return_value='fake')
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'create_view_volume',
                       return_value=VOLUME)
    def test_create_volume_from_snapshot(self,
                                         mock_create_view_volume,
                                         mock_find_replay,
                                         mock_find_volume,
                                         mock_find_sc,
                                         mock_close_connection,
                                         mock_open_connection,
                                         mock_init):
        volume = {'id': 'fake'}
        snapshot = {'id': 'fake', 'volume_id': 'fake'}
        self.driver.create_volume_from_snapshot(volume, snapshot)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_sc',
                       return_value=12345)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_replay',
                       return_value='fake')
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'create_view_volume',
                       return_value=None)
    def test_create_volume_from_snapshot_failed(self,
                                                mock_create_view_volume,
                                                mock_find_replay,
                                                mock_find_volume,
                                                mock_find_sc,
                                                mock_close_connection,
                                                mock_open_connection,
                                                mock_init):
        volume = {'id': 'fake'}
        snapshot = {'id': 'fake', 'volume_id': 'fake'}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume_from_snapshot,
                          volume, snapshot)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_sc',
                       return_value=12345)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_replay',
                       return_value=None)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'create_view_volume',
                       return_value=VOLUME)
    def test_create_volume_from_snapshot_no_replay(self,
                                                   mock_create_view_volume,
                                                   mock_find_replay,
                                                   mock_find_volume,
                                                   mock_find_sc,
                                                   mock_close_connection,
                                                   mock_open_connection,
                                                   mock_init):
        volume = {'id': 'fake'}
        snapshot = {'id': 'fake', 'volume_id': 'fake'}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume_from_snapshot,
                          volume, snapshot)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_sc',
                       return_value=12345)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_replay',
                       return_value='fake')
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'create_cloned_volume',
                       return_value=VOLUME)
    def test_create_cloned_volume(self,
                                  mock_create_cloned_volume,
                                  mock_find_volume,
                                  mock_find_replay,
                                  mock_find_sc,
                                  mock_close_connection,
                                  mock_open_connection,
                                  mock_init):
        volume = {'id': self.volume_name + '_clone'}
        src_vref = {'id': self.volume_name}
        self.driver.create_cloned_volume(volume, src_vref)
        mock_create_cloned_volume. \
            assert_called_once_with(self.volume_name + '_clone',
                                    self.configuration.dell_sc_volume_folder,
                                    self.VOLUME)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_sc',
                       return_value=12345)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_volume',
                       return_value=None)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_replay',
                       return_value='fake')
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'create_cloned_volume',
                       return_value=VOLUME)
    def test_create_cloned_volume_no_volume(self,
                                            mock_create_cloned_volume,
                                            mock_find_volume,
                                            mock_find_replay,
                                            mock_find_sc,
                                            mock_close_connection,
                                            mock_open_connection,
                                            mock_init):
        volume = {'id': self.volume_name + '_clone'}
        src_vref = {'id': self.volume_name}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_cloned_volume,
                          volume, src_vref)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_sc',
                       return_value=12345)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'delete_replay',
                       return_value=True)
    def test_delete_snapshot(self,
                             mock_delete_replay,
                             mock_find_volume,
                             mock_find_sc,
                             mock_close_connection,
                             mock_open_connection,
                             mock_init):
        snapshot = {'volume_id': self.volume_name,
                    'id': self.volume_name}
        self.driver.delete_snapshot(snapshot)
        mock_delete_replay.assert_called_once_with(
            self.VOLUME, self.volume_name)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_sc',
                       return_value=12345)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_volume',
                       return_value=None)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'delete_replay',
                       return_value=True)
    def test_delete_snapshot_no_volume(self,
                                       mock_delete_replay,
                                       mock_find_volume,
                                       mock_find_sc,
                                       mock_close_connection,
                                       mock_open_connection,
                                       mock_init):
        snapshot = {'volume_id': self.volume_name,
                    'id': self.volume_name}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.delete_snapshot,
                          snapshot)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_sc',
                       return_value=12345)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_volume',
                       return_value=VOLUME)
    def test_ensure_export(self,
                           mock_find_volume,
                           mock_find_sc,
                           mock_close_connection,
                           mock_open_connection,
                           mock_init):
        context = {}
        volume = {'id': self.VOLUME.get(u'name')}
        self.driver.ensure_export(context, volume)
        mock_find_volume.assert_called_once_with(
            12345, self.VOLUME.get(u'name'))

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_sc',
                       return_value=12345)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_volume',
                       return_value=None)
    def test_ensure_export_failed(self,
                                  mock_find_volume,
                                  mock_find_sc,
                                  mock_close_connection,
                                  mock_open_connection,
                                  mock_init):
        context = {}
        volume = {'id': self.VOLUME.get(u'name')}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.ensure_export,
                          context, volume)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_sc',
                       return_value=12345)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_volume',
                       return_value=None)
    def test_ensure_export_no_volume(self,
                                     mock_find_volume,
                                     mock_find_sc,
                                     mock_close_connection,
                                     mock_open_connection,
                                     mock_init):
        context = {}
        volume = {'id': self.VOLUME.get(u'name')}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.ensure_export,
                          context,
                          volume)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_sc',
                       return_value=12345)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'expand_volume',
                       return_value=VOLUME)
    def test_extend_volume(self,
                           mock_expand_volume,
                           mock_find_volume,
                           mock_find_sc,
                           mock_close_connection,
                           mock_open_connection,
                           mock_init):
        volume = {'name': self.volume_name, 'size': 1}
        new_size = 2
        self.driver.extend_volume(volume, new_size)
        mock_expand_volume.assert_called_once_with(self.VOLUME, new_size)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_sc',
                       return_value=12345)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_volume',
                       return_value=None)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'expand_volume',
                       return_value=None)
    def test_extend_volume_no_volume(self,
                                     mock_expand_volume,
                                     mock_find_volume,
                                     mock_find_sc,
                                     mock_close_connection,
                                     mock_open_connection,
                                     mock_init):
        volume = {'name': self.volume_name, 'size': 1}
        new_size = 2
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.extend_volume,
                          volume, new_size)

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
        self.assertEqual(stats['storage_protocol'], 'iSCSI')
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
        self.assertEqual(stats['storage_protocol'], 'iSCSI')
        assert mock_get_storage_usage.called is False

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_sc',
                       return_value=12345)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'rename_volume',
                       return_value=True)
    def test_update_migrated_volume(self,
                                    mock_rename_volume,
                                    mock_find_volume,
                                    mock_find_sc,
                                    mock_close_connection,
                                    mock_open_connection,
                                    mock_init):
        volume = {'id': 111}
        backend_volume = {'id': 112}
        model_update = {'_name_id': None}
        rt = self.driver.update_migrated_volume(None, volume, backend_volume)
        mock_rename_volume.assert_called_once_with(self.VOLUME,
                                                   volume['id'])
        self.assertEqual(model_update, rt)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_sc',
                       return_value=12345)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'rename_volume',
                       return_value=False)
    def test_update_migrated_volume_rename_fail(self,
                                                mock_rename_volume,
                                                mock_find_volume,
                                                mock_find_sc,
                                                mock_close_connection,
                                                mock_open_connection,
                                                mock_init):
        volume = {'id': 111}
        backend_volume = {'id': 112}
        rt = self.driver.update_migrated_volume(None, volume, backend_volume)
        mock_rename_volume.assert_called_once_with(self.VOLUME,
                                                   volume['id'])
        self.assertEqual(None, rt)

    def test_update_migrated_volume_no_volume_id(self,
                                                 mock_close_connection,
                                                 mock_open_connection,
                                                 mock_init):
        volume = {'id': None}
        backend_volume = {'id': 112}
        rt = self.driver.update_migrated_volume(None, volume, backend_volume)
        self.assertEqual(None, rt)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_sc',
                       return_value=12345)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_volume',
                       return_value=None)
    def test_update_migrated_volume_no_backend_id(self,
                                                  mock_find_volume,
                                                  mock_find_sc,
                                                  mock_close_connection,
                                                  mock_open_connection,
                                                  mock_init):
        volume = {'id': 111}
        backend_volume = {'id': None}
        rt = self.driver.update_migrated_volume(None, volume, backend_volume)
        mock_find_sc.assert_called_once_with(12345)
        mock_find_volume.assert_called_once_with(12345, None)
        self.assertEqual(None, rt)
