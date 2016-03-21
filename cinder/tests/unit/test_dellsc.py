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
import uuid

from cinder import context
from cinder import exception
from cinder.objects import fields
from cinder import test
from cinder.volume.drivers.dell import dell_storagecenter_api
from cinder.volume.drivers.dell import dell_storagecenter_iscsi
from cinder.volume import volume_types


# We patch these here as they are used by every test to keep
# from trying to contact a Dell Storage Center.
@mock.patch.object(dell_storagecenter_api.HttpClient,
                   '__init__',
                   return_value=None)
@mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                   'open_connection',
                   return_value=mock.MagicMock())
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

    SCRPLAYPROFILE = {u'ruleCount': 0,
                      u'name': u'fc8f2fec-fab2-4e34-9148-c094c913b9a3',
                      u'volumeCount': 0,
                      u'scName': u'Storage Center 64702',
                      u'notes': u'Created by Dell Cinder Driver',
                      u'scSerialNumber': 64702,
                      u'userCreated': True,
                      u'instanceName': u'fc8f2fec-fab2-4e34-9148-c094c913b9a3',
                      u'instanceId': u'64702.11',
                      u'enforceReplayCreationTimeout': False,
                      u'replayCreationTimeout': 20,
                      u'objectType': u'ScReplayProfile',
                      u'type': u'Consistent',
                      u'expireIncompleteReplaySets': True}

    IQN = 'iqn.2002-03.com.compellent:5000D31000000001'

    ISCSI_PROPERTIES = {'access_mode': 'rw',
                        'target_discovered': False,
                        'target_iqn':
                        u'iqn.2002-03.com.compellent:5000d31000fcbe43',
                        'target_iqns':
                        [u'iqn.2002-03.com.compellent:5000d31000fcbe43',
                         u'iqn.2002-03.com.compellent:5000d31000fcbe44'],
                        'target_lun': 1,
                        'target_luns': [1, 1],
                        'target_portal': u'192.168.0.21:3260',
                        'target_portals': [u'192.168.0.21:3260',
                                           u'192.168.0.22:3260']}

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

        # Start with none.  Add in the specific tests later.
        # Mock tests bozo this.
        self.driver.backends = None
        self.driver.replication_enabled = False

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
            'target_discovered': True,
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

    @mock.patch.object(dell_storagecenter_iscsi.DellStorageCenterISCSIDriver,
                       '_get_volume_extra_specs')
    def test__create_replications(self,
                                  mock_get_volume_extra_specs,
                                  mock_close_connection,
                                  mock_open_connection,
                                  mock_init):
        backends = self.driver.backends
        mock_get_volume_extra_specs.return_value = {
            'replication_enabled': '<is> True'}
        model_update = {'replication_status': 'enabled',
                        'replication_driver_data': '12345,67890'}

        vol = {'id': 'guid', 'replication_driver_data': ''}
        scvol = {'name': 'guid'}
        self.driver.backends = [{'target_device_id': '12345',
                                 'managed_backend_name': 'host@dell1',
                                 'qosnode': 'cinderqos'},
                                {'target_device_id': '67890',
                                 'managed_backend_name': 'host@dell2',
                                 'qosnode': 'otherqos'}]
        mock_api = mock.MagicMock()
        mock_api.create_replication = mock.MagicMock(
            return_value={'instanceId': '1'})
        # Create regular replication test.
        res = self.driver._create_replications(mock_api, vol, scvol)
        mock_api.create_replication.assert_any_call(
            scvol, '12345', 'cinderqos', False, None, False)
        mock_api.create_replication.assert_any_call(
            scvol, '67890', 'otherqos', False, None, False)
        self.assertEqual(model_update, res)
        # Create replication with activereplay set.
        mock_get_volume_extra_specs.return_value = {
            'replication:activereplay': '<is> True',
            'replication_enabled': '<is> True'}
        res = self.driver._create_replications(mock_api, vol, scvol)
        mock_api.create_replication.assert_any_call(
            scvol, '12345', 'cinderqos', False, None, True)
        mock_api.create_replication.assert_any_call(
            scvol, '67890', 'otherqos', False, None, True)
        self.assertEqual(model_update, res)
        # Create replication with sync set.
        mock_get_volume_extra_specs.return_value = {
            'replication:activereplay': '<is> True',
            'replication_enabled': '<is> True',
            'replication_type': '<in> sync'}
        res = self.driver._create_replications(mock_api, vol, scvol)
        mock_api.create_replication.assert_any_call(
            scvol, '12345', 'cinderqos', True, None, True)
        mock_api.create_replication.assert_any_call(
            scvol, '67890', 'otherqos', True, None, True)
        self.assertEqual(model_update, res)
        # Create replication with disk folder set.
        self.driver.backends = [{'target_device_id': '12345',
                                 'managed_backend_name': 'host@dell1',
                                 'qosnode': 'cinderqos',
                                 'diskfolder': 'ssd'},
                                {'target_device_id': '67890',
                                 'managed_backend_name': 'host@dell2',
                                 'qosnode': 'otherqos',
                                 'diskfolder': 'ssd'}]
        mock_get_volume_extra_specs.return_value = {
            'replication:activereplay': '<is> True',
            'replication_enabled': '<is> True',
            'replication_type': '<in> sync'}
        res = self.driver._create_replications(mock_api, vol, scvol)
        mock_api.create_replication.assert_any_call(
            scvol, '12345', 'cinderqos', True, 'ssd', True)
        mock_api.create_replication.assert_any_call(
            scvol, '67890', 'otherqos', True, 'ssd', True)
        self.assertEqual(model_update, res)
        # Failed to create replication test.
        mock_api.create_replication.return_value = None
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver._create_replications,
                          mock_api,
                          vol,
                          scvol)
        # Replication not enabled test
        mock_get_volume_extra_specs.return_value = {}
        res = self.driver._create_replications(mock_api, vol, scvol)
        self.assertEqual({}, res)
        self.driver.backends = backends

    @mock.patch.object(dell_storagecenter_iscsi.DellStorageCenterISCSIDriver,
                       '_get_volume_extra_specs')
    def test__delete_replications(self,
                                  mock_get_volume_extra_specs,
                                  mock_close_connection,
                                  mock_open_connection,
                                  mock_init):
        backends = self.driver.backends
        vol = {'id': 'guid'}
        scvol = {'instanceId': '1'}
        mock_api = mock.MagicMock()
        mock_api.delete_replication = mock.MagicMock()
        mock_api.find_volume = mock.MagicMock(return_value=scvol)
        # Start replication disabled. Should fail immediately.
        mock_get_volume_extra_specs.return_value = {}
        self.driver._delete_replications(mock_api, vol)
        self.assertFalse(mock_api.delete_replication.called)
        # Replication enabled. No replications listed.
        mock_get_volume_extra_specs.return_value = {
            'replication_enabled': '<is> True'}
        vol = {'id': 'guid', 'replication_driver_data': ''}
        self.driver._delete_replications(mock_api, vol)
        self.assertFalse(mock_api.delete_replication.called)
        # Something to call.
        vol = {'id': 'guid', 'replication_driver_data': '12345,67890'}
        self.driver._delete_replications(mock_api, vol)
        mock_api.delete_replication.assert_any_call(scvol, 12345)
        mock_api.delete_replication.assert_any_call(scvol, 67890)
        self.driver.backends = backends

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
                                                   None,
                                                   None)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_replay_profile',
                       return_value='fake')
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'update_cg_volumes')
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'create_volume',
                       return_value=VOLUME)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_sc',
                       return_value=12345)
    def test_create_volume_consistency_group(self,
                                             mock_find_sc,
                                             mock_create_volume,
                                             mock_update_cg_volumes,
                                             mock_find_replay_profile,
                                             mock_close_connection,
                                             mock_open_connection,
                                             mock_init):
        volume = {'id': self.volume_name, 'size': 1,
                  'consistencygroup_id': 'guid'}
        self.driver.create_volume(volume)
        mock_create_volume.assert_called_once_with(self.volume_name,
                                                   1,
                                                   None,
                                                   None)
        self.assertTrue(mock_find_replay_profile.called)
        self.assertTrue(mock_update_cg_volumes.called)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'create_volume',
                       return_value=VOLUME)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_sc',
                       return_value=12345)
    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'storagetype:storageprofile': 'HighPriority'})
    def test_create_volume_storage_profile(self,
                                           mock_extra,
                                           mock_find_sc,
                                           mock_create_volume,
                                           mock_close_connection,
                                           mock_open_connection,
                                           mock_init):
        volume = {'id': self.volume_name, 'size': 1, 'volume_type_id': 'abc'}
        self.driver.create_volume(volume)
        mock_create_volume.assert_called_once_with(self.volume_name,
                                                   1,
                                                   "HighPriority",
                                                   None)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'create_volume',
                       return_value=VOLUME)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_sc',
                       return_value=12345)
    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'storagetype:replayprofiles': 'Daily'})
    def test_create_volume_replay_profiles(self,
                                           mock_extra,
                                           mock_find_sc,
                                           mock_create_volume,
                                           mock_close_connection,
                                           mock_open_connection,
                                           mock_init):
        volume = {'id': self.volume_name, 'size': 1, 'volume_type_id': 'abc'}
        self.driver.create_volume(volume)
        mock_create_volume.assert_called_once_with(self.volume_name,
                                                   1,
                                                   None,
                                                   'Daily')

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'create_volume',
                       return_value=VOLUME)
    @mock.patch.object(dell_storagecenter_iscsi.DellStorageCenterISCSIDriver,
                       '_create_replications',
                       return_value={'replication_status': 'enabled',
                                     'replication_driver_data': 'ssn'})
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_sc',
                       return_value=12345)
    def test_create_volume_replication(self,
                                       mock_find_sc,
                                       mock_create_replications,
                                       mock_create_volume,
                                       mock_close_connection,
                                       mock_open_connection,
                                       mock_init):
        volume = {'id': self.volume_name, 'size': 1}
        ret = self.driver.create_volume(volume)
        self.assertEqual({'replication_status': 'enabled',
                          'replication_driver_data': 'ssn'}, ret)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'create_volume',
                       return_value=VOLUME)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'delete_volume')
    @mock.patch.object(dell_storagecenter_iscsi.DellStorageCenterISCSIDriver,
                       '_create_replications')
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_sc',
                       return_value=12345)
    def test_create_volume_replication_raises(self,
                                              mock_find_sc,
                                              mock_create_replications,
                                              mock_delete_volume,
                                              mock_create_volume,
                                              mock_close_connection,
                                              mock_open_connection,
                                              mock_init):
        volume = {'id': self.volume_name, 'size': 1}
        mock_create_replications.side_effect = (
            exception.VolumeBackendAPIException(data='abc'))
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume,
                          volume)
        self.assertTrue(mock_delete_volume.called)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'create_volume',
                       return_value=None)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_sc',
                       return_value=12345)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'delete_volume')
    def test_create_volume_failure(self,
                                   mock_delete_volume,
                                   mock_find_sc,
                                   mock_create_volume,
                                   mock_close_connection,
                                   mock_open_connection,
                                   mock_init):
        volume = {'id': self.volume_name, 'size': 1}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume, volume)
        self.assertTrue(mock_delete_volume.called)

    @mock.patch.object(dell_storagecenter_iscsi.DellStorageCenterISCSIDriver,
                       '_delete_replications')
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'delete_volume',
                       return_value=True)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_sc',
                       return_value=12345)
    def test_delete_volume(self,
                           mock_find_sc,
                           mock_delete_volume,
                           mock_delete_replications,
                           mock_close_connection,
                           mock_open_connection,
                           mock_init):
        volume = {'id': self.volume_name, 'size': 1}
        self.driver.delete_volume(volume)
        mock_delete_volume.assert_called_once_with(self.volume_name)
        self.assertTrue(mock_delete_replications.called)

    @mock.patch.object(dell_storagecenter_iscsi.DellStorageCenterISCSIDriver,
                       '_delete_replications')
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'delete_volume',
                       return_value=False)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_sc',
                       return_value=12345)
    def test_delete_volume_failure(self,
                                   mock_find_sc,
                                   mock_delete_volume,
                                   mock_delete_replications,
                                   mock_close_connection,
                                   mock_open_connection,
                                   mock_init):
        volume = {'id': self.volume_name, 'size': 1}
        self.assertRaises(exception.VolumeIsBusy,
                          self.driver.delete_volume,
                          volume)
        self.assertTrue(mock_delete_replications.called)

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
                       return_value=ISCSI_PROPERTIES)
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
        self.assertEqual('iscsi', data['driver_volume_type'])
        # verify find_volume has been called and that is has been called twice
        mock_find_volume.assert_any_call(self.volume_name)
        self.assertEqual(2, mock_find_volume.call_count)
        expected = {'data': self.ISCSI_PROPERTIES,
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
                       return_value=ISCSI_PROPERTIES)
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
        self.assertEqual('iscsi', data['driver_volume_type'])
        # verify find_volume has been called and that is has been called twice
        mock_find_volume.assert_any_call(self.volume_name)
        self.assertEqual(2, mock_find_volume.call_count)
        props = self.ISCSI_PROPERTIES
        expected = {'data': props,
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
                       return_value=None)
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
        mock_find_iscsi_properties.side_effect = Exception('abc')
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
                       return_value=None)
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
                       return_value=None)
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
                       return_value=ISCSI_PROPERTIES)
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
        res = self.driver.terminate_connection(volume, connector)
        mock_unmap_volume.assert_called_once_with(self.VOLUME, self.SCSERVER)
        self.assertIsNone(res, 'None expected')

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

    @mock.patch.object(dell_storagecenter_iscsi.DellStorageCenterISCSIDriver,
                       '_create_replications')
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_replay_profile')
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
                                         mock_find_replay_profile,
                                         mock_create_replications,
                                         mock_close_connection,
                                         mock_open_connection,
                                         mock_init):
        model_update = {'something': 'something'}
        mock_create_replications.return_value = model_update
        volume = {'id': 'fake'}
        snapshot = {'id': 'fake', 'volume_id': 'fake'}
        res = self.driver.create_volume_from_snapshot(volume, snapshot)
        mock_create_view_volume.assert_called_once_with('fake',
                                                        'fake',
                                                        None)
        self.assertTrue(mock_find_replay.called)
        self.assertTrue(mock_find_volume.called)
        self.assertFalse(mock_find_replay_profile.called)
        # This just makes sure that we created
        self.assertTrue(mock_create_replications.called)
        self.assertEqual(model_update, res)

    @mock.patch.object(dell_storagecenter_iscsi.DellStorageCenterISCSIDriver,
                       '_create_replications')
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_replay_profile',
                       return_value='fake')
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'update_cg_volumes')
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
    def test_create_volume_from_snapshot_cg(self,
                                            mock_create_view_volume,
                                            mock_find_replay,
                                            mock_find_volume,
                                            mock_find_sc,
                                            mock_update_cg_volumes,
                                            mock_find_replay_profile,
                                            mock_create_replications,
                                            mock_close_connection,
                                            mock_open_connection,
                                            mock_init):
        model_update = {'something': 'something'}
        mock_create_replications.return_value = model_update
        volume = {'id': 'fake', 'consistencygroup_id': 'guid'}
        snapshot = {'id': 'fake', 'volume_id': 'fake'}
        res = self.driver.create_volume_from_snapshot(volume, snapshot)
        mock_create_view_volume.assert_called_once_with('fake',
                                                        'fake',
                                                        None)
        self.assertTrue(mock_find_replay.called)
        self.assertTrue(mock_find_volume.called)
        self.assertTrue(mock_find_replay_profile.called)
        self.assertTrue(mock_update_cg_volumes.called)
        # This just makes sure that we created
        self.assertTrue(mock_create_replications.called)
        self.assertEqual(model_update, res)

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
                       'find_replay_profile')
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'create_view_volume',
                       return_value=None)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'delete_volume')
    def test_create_volume_from_snapshot_failed(self,
                                                mock_delete_volume,
                                                mock_create_view_volume,
                                                mock_find_replay_profile,
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
        self.assertTrue(mock_find_replay.called)
        self.assertTrue(mock_find_volume.called)
        self.assertFalse(mock_find_replay_profile.called)
        self.assertTrue(mock_delete_volume.called)

    @mock.patch.object(dell_storagecenter_iscsi.DellStorageCenterISCSIDriver,
                       '_create_replications')
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
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'delete_volume')
    def test_create_volume_from_snapshot_failed_replication(
            self,
            mock_delete_volume,
            mock_create_view_volume,
            mock_find_replay,
            mock_find_volume,
            mock_find_sc,
            mock_create_replications,
            mock_close_connection,
            mock_open_connection,
            mock_init):
        mock_create_replications.side_effect = (
            exception.VolumeBackendAPIException(data='abc'))
        volume = {'id': 'fake'}
        snapshot = {'id': 'fake', 'volume_id': 'fake'}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume_from_snapshot,
                          volume, snapshot)
        self.assertTrue(mock_delete_volume.called)

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
        self.assertTrue(mock_find_volume.called)
        self.assertTrue(mock_find_replay.called)
        self.assertFalse(mock_create_view_volume.called)

    @mock.patch.object(dell_storagecenter_iscsi.DellStorageCenterISCSIDriver,
                       '_create_replications',
                       return_value={})
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_sc',
                       return_value=12345)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'create_cloned_volume',
                       return_value=VOLUME)
    def test_create_cloned_volume(self,
                                  mock_create_cloned_volume,
                                  mock_find_volume,
                                  mock_find_sc,
                                  mock_create_replications,
                                  mock_close_connection,
                                  mock_open_connection,
                                  mock_init):
        volume = {'id': self.volume_name + '_clone', 'size': 1}
        src_vref = {'id': self.volume_name, 'size': 1}
        ret = self.driver.create_cloned_volume(volume, src_vref)
        mock_create_cloned_volume.assert_called_once_with(
            self.volume_name + '_clone',
            self.VOLUME,
            None)
        self.assertTrue(mock_find_volume.called)
        self.assertEqual({}, ret)

    @mock.patch.object(dell_storagecenter_iscsi.DellStorageCenterISCSIDriver,
                       '_create_replications',
                       return_value={})
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_sc',
                       return_value=12345)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'create_cloned_volume',
                       return_value=VOLUME)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'expand_volume',
                       return_value=VOLUME)
    def test_create_cloned_volume_expand(self,
                                         mock_expand_volume,
                                         mock_create_cloned_volume,
                                         mock_find_volume,
                                         mock_find_sc,
                                         mock_create_replications,
                                         mock_close_connection,
                                         mock_open_connection,
                                         mock_init):
        volume = {'id': self.volume_name + '_clone', 'size': 2}
        src_vref = {'id': self.volume_name, 'size': 1}
        ret = self.driver.create_cloned_volume(volume, src_vref)
        mock_create_cloned_volume.assert_called_once_with(
            self.volume_name + '_clone',
            self.VOLUME,
            None)
        self.assertTrue(mock_find_volume.called)
        self.assertEqual({}, ret)
        self.assertTrue(mock_expand_volume.called)

    @mock.patch.object(dell_storagecenter_iscsi.DellStorageCenterISCSIDriver,
                       '_create_replications',
                       return_value={})
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_sc',
                       return_value=12345)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'create_cloned_volume',
                       return_value=None)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'delete_volume')
    def test_create_cloned_volume_failed(self,
                                         mock_delete_volume,
                                         mock_create_cloned_volume,
                                         mock_find_volume,
                                         mock_find_sc,
                                         mock_create_replications,
                                         mock_close_connection,
                                         mock_open_connection,
                                         mock_init):
        volume = {'id': self.volume_name + '_clone'}
        src_vref = {'id': self.volume_name}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_cloned_volume,
                          volume, src_vref)
        self.assertTrue(mock_delete_volume.called)

    @mock.patch.object(dell_storagecenter_iscsi.DellStorageCenterISCSIDriver,
                       '_create_replications',
                       return_value={})
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_sc',
                       return_value=12345)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'create_cloned_volume',
                       return_value=VOLUME)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'delete_volume')
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'expand_volume')
    def test_create_cloned_volume_expand_failed(self,
                                                mock_expand_volume,
                                                mock_delete_volume,
                                                mock_create_cloned_volume,
                                                mock_find_volume,
                                                mock_find_sc,
                                                mock_create_replications,
                                                mock_close_connection,
                                                mock_open_connection,
                                                mock_init):
        volume = {'id': self.volume_name + '_clone', 'size': 2}
        src_vref = {'id': self.volume_name, 'size': 1}
        mock_create_replications.side_effect = (
            exception.VolumeBackendAPIException(data='abc'))
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_cloned_volume,
                          volume, src_vref)
        self.assertTrue(mock_delete_volume.called)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'delete_volume')
    @mock.patch.object(dell_storagecenter_iscsi.DellStorageCenterISCSIDriver,
                       '_create_replications')
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_sc',
                       return_value=12345)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'create_cloned_volume',
                       return_value=VOLUME)
    def test_create_cloned_volume_replication_fail(self,
                                                   mock_create_cloned_volume,
                                                   mock_find_volume,
                                                   mock_find_sc,
                                                   mock_create_replications,
                                                   mock_delete_volume,
                                                   mock_close_connection,
                                                   mock_open_connection,
                                                   mock_init):
        mock_create_replications.side_effect = (
            exception.VolumeBackendAPIException(data='abc'))
        volume = {'id': self.volume_name + '_clone', 'size': 1}
        src_vref = {'id': self.volume_name, 'size': 1}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_cloned_volume,
                          volume, src_vref)
        self.assertTrue(mock_delete_volume.called)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_replay_profile',
                       return_value='fake')
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'update_cg_volumes')
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_sc',
                       return_value=12345)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'create_cloned_volume',
                       return_value=VOLUME)
    def test_create_cloned_volume_consistency_group(self,
                                                    mock_create_cloned_volume,
                                                    mock_find_volume,
                                                    mock_find_sc,
                                                    mock_update_cg_volumes,
                                                    mock_find_replay_profile,
                                                    mock_close_connection,
                                                    mock_open_connection,
                                                    mock_init):
        volume = {'id': self.volume_name + '_clone',
                  'consistencygroup_id': 'guid',
                  'size': 1}
        src_vref = {'id': self.volume_name, 'size': 1}
        self.driver.create_cloned_volume(volume, src_vref)
        mock_create_cloned_volume.assert_called_once_with(
            self.volume_name + '_clone',
            self.VOLUME,
            None)
        self.assertTrue(mock_find_volume.called)
        self.assertTrue(mock_find_replay_profile.called)
        self.assertTrue(mock_update_cg_volumes.called)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_sc',
                       return_value=12345)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_volume',
                       return_value=None)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'create_cloned_volume',
                       return_value=VOLUME)
    def test_create_cloned_volume_no_volume(self,
                                            mock_create_cloned_volume,
                                            mock_find_volume,
                                            mock_find_sc,
                                            mock_close_connection,
                                            mock_open_connection,
                                            mock_init):
        volume = {'id': self.volume_name + '_clone'}
        src_vref = {'id': self.volume_name}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_cloned_volume,
                          volume, src_vref)
        self.assertTrue(mock_find_volume.called)
        self.assertFalse(mock_create_cloned_volume.called)

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
            self.VOLUME.get(u'name'))

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
        self.assertEqual('iSCSI', stats['storage_protocol'])
        self.assertTrue(mock_get_storage_usage.called)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_sc',
                       return_value=64702)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'get_storage_usage',
                       return_value={'availableSpace': 100, 'freeSpace': 50})
    def test_update_volume_stats_with_refresh_and_repl(
            self,
            mock_get_storage_usage,
            mock_find_sc,
            mock_close_connection,
            mock_open_connection,
            mock_init):
        backends = self.driver.backends
        repliation_enabled = self.driver.replication_enabled
        self.driver.backends = [{'a': 'a'}, {'b': 'b'}, {'c': 'c'}]
        self.driver.replication_enabled = True
        stats = self.driver.get_volume_stats(True)
        self.assertEqual(3, stats['replication_count'])
        self.assertEqual(['async', 'sync'], stats['replication_type'])
        self.assertTrue(stats['replication_enabled'])
        self.assertTrue(mock_get_storage_usage.called)
        self.driver.backends = backends
        self.driver.replication_enabled = repliation_enabled

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
        self.assertEqual('iSCSI', stats['storage_protocol'])
        self.assertFalse(mock_get_storage_usage.called)

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
        rt = self.driver.update_migrated_volume(None, volume, backend_volume,
                                                'available')
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
        backend_volume = {'id': 112, '_name_id': 113}
        rt = self.driver.update_migrated_volume(None, volume, backend_volume,
                                                'available')
        mock_rename_volume.assert_called_once_with(self.VOLUME,
                                                   volume['id'])
        self.assertEqual({'_name_id': 113}, rt)

    def test_update_migrated_volume_no_volume_id(self,
                                                 mock_close_connection,
                                                 mock_open_connection,
                                                 mock_init):
        volume = {'id': None}
        backend_volume = {'id': 112, '_name_id': 113}
        rt = self.driver.update_migrated_volume(None, volume, backend_volume,
                                                'available')
        self.assertEqual({'_name_id': 113}, rt)

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
        backend_volume = {'id': None, '_name_id': None}
        rt = self.driver.update_migrated_volume(None, volume, backend_volume,
                                                'available')
        mock_find_sc.assert_called_once_with()
        mock_find_volume.assert_called_once_with(None)
        self.assertEqual({'_name_id': None}, rt)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'create_replay_profile',
                       return_value=SCRPLAYPROFILE)
    def test_create_consistencygroup(self,
                                     mock_create_replay_profile,
                                     mock_close_connection,
                                     mock_open_connection,
                                     mock_init):
        context = {}
        group = {'id': 'fc8f2fec-fab2-4e34-9148-c094c913b9a3'}
        self.driver.create_consistencygroup(context, group)
        mock_create_replay_profile.assert_called_once_with(group['id'])

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'create_replay_profile',
                       return_value=None)
    def test_create_consistencygroup_fail(self,
                                          mock_create_replay_profile,
                                          mock_close_connection,
                                          mock_open_connection,
                                          mock_init):
        context = {}
        group = {'id': 'fc8f2fec-fab2-4e34-9148-c094c913b9a3'}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_consistencygroup, context, group)
        mock_create_replay_profile.assert_called_once_with(group['id'])

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'delete_replay_profile')
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_replay_profile',
                       return_value=SCRPLAYPROFILE)
    @mock.patch.object(dell_storagecenter_iscsi.DellStorageCenterISCSIDriver,
                       'delete_volume')
    def test_delete_consistencygroup(self,
                                     mock_delete_volume,
                                     mock_find_replay_profile,
                                     mock_delete_replay_profile,
                                     mock_close_connection,
                                     mock_open_connection,
                                     mock_init):
        mock_volume = mock.MagicMock()
        expected_volumes = [mock_volume]
        context = {}
        group = {'id': 'fc8f2fec-fab2-4e34-9148-c094c913b9a3',
                 'status': fields.ConsistencyGroupStatus.DELETED}
        model_update, volumes = self.driver.delete_consistencygroup(
            context, group, [mock_volume])
        mock_find_replay_profile.assert_called_once_with(group['id'])
        mock_delete_replay_profile.assert_called_once_with(self.SCRPLAYPROFILE)
        mock_delete_volume.assert_called_once_with(mock_volume)
        self.assertEqual(group['status'], model_update['status'])
        self.assertEqual(expected_volumes, volumes)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'delete_replay_profile')
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_replay_profile',
                       return_value=None)
    @mock.patch.object(dell_storagecenter_iscsi.DellStorageCenterISCSIDriver,
                       'delete_volume')
    def test_delete_consistencygroup_not_found(self,
                                               mock_delete_volume,
                                               mock_find_replay_profile,
                                               mock_delete_replay_profile,
                                               mock_close_connection,
                                               mock_open_connection,
                                               mock_init):
        context = {}
        group = {'id': 'fc8f2fec-fab2-4e34-9148-c094c913b9a3',
                 'status': fields.ConsistencyGroupStatus.DELETED}
        model_update, volumes = self.driver.delete_consistencygroup(context,
                                                                    group,
                                                                    [])
        mock_find_replay_profile.assert_called_once_with(group['id'])
        self.assertFalse(mock_delete_replay_profile.called)
        self.assertFalse(mock_delete_volume.called)
        self.assertEqual(group['status'], model_update['status'])
        self.assertEqual([], volumes)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'update_cg_volumes',
                       return_value=True)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_replay_profile',
                       return_value=SCRPLAYPROFILE)
    def test_update_consistencygroup(self,
                                     mock_find_replay_profile,
                                     mock_update_cg_volumes,
                                     mock_close_connection,
                                     mock_open_connection,
                                     mock_init):
        context = {}
        group = {'id': 'fc8f2fec-fab2-4e34-9148-c094c913b9a3'}
        add_volumes = [{'id': '101'}]
        remove_volumes = [{'id': '102'}]
        rt1, rt2, rt3 = self.driver.update_consistencygroup(context,
                                                            group,
                                                            add_volumes,
                                                            remove_volumes)
        mock_update_cg_volumes.assert_called_once_with(self.SCRPLAYPROFILE,
                                                       add_volumes,
                                                       remove_volumes)
        mock_find_replay_profile.assert_called_once_with(group['id'])
        self.assertIsNone(rt1)
        self.assertIsNone(rt2)
        self.assertIsNone(rt3)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_replay_profile',
                       return_value=None)
    def test_update_consistencygroup_not_found(self,
                                               mock_find_replay_profile,
                                               mock_close_connection,
                                               mock_open_connection,
                                               mock_init):
        context = {}
        group = {'id': 'fc8f2fec-fab2-4e34-9148-c094c913b9a3'}
        add_volumes = [{'id': '101'}]
        remove_volumes = [{'id': '102'}]
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.update_consistencygroup,
                          context,
                          group,
                          add_volumes,
                          remove_volumes)
        mock_find_replay_profile.assert_called_once_with(group['id'])

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'update_cg_volumes',
                       return_value=False)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_replay_profile',
                       return_value=SCRPLAYPROFILE)
    def test_update_consistencygroup_error(self,
                                           mock_find_replay_profile,
                                           mock_update_cg_volumes,
                                           mock_close_connection,
                                           mock_open_connection,
                                           mock_init):
        context = {}
        group = {'id': 'fc8f2fec-fab2-4e34-9148-c094c913b9a3'}
        add_volumes = [{'id': '101'}]
        remove_volumes = [{'id': '102'}]
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.update_consistencygroup,
                          context,
                          group,
                          add_volumes,
                          remove_volumes)
        mock_find_replay_profile.assert_called_once_with(group['id'])
        mock_update_cg_volumes.assert_called_once_with(self.SCRPLAYPROFILE,
                                                       add_volumes,
                                                       remove_volumes)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'snap_cg_replay',
                       return_value={'instanceId': '100'})
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_replay_profile',
                       return_value=SCRPLAYPROFILE)
    def test_create_cgsnapshot(self,
                               mock_find_replay_profile,
                               mock_snap_cg_replay,
                               mock_close_connection,
                               mock_open_connection,
                               mock_init):
        mock_snapshot = mock.MagicMock()
        mock_snapshot.id = '1'
        expected_snapshots = [{'id': '1', 'status': 'available'}]

        context = {}
        cggrp = {'consistencygroup_id': 'fc8f2fec-fab2-4e34-9148-c094c913b9a3',
                 'id': '100'}
        model_update, snapshots = self.driver.create_cgsnapshot(
            context, cggrp, [mock_snapshot])
        mock_find_replay_profile.assert_called_once_with(
            cggrp['consistencygroup_id'])
        mock_snap_cg_replay.assert_called_once_with(self.SCRPLAYPROFILE,
                                                    cggrp['id'],
                                                    0)
        self.assertEqual('available', model_update['status'])
        self.assertEqual(expected_snapshots, snapshots)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_replay_profile',
                       return_value=None)
    def test_create_cgsnapshot_profile_not_found(self,
                                                 mock_find_replay_profile,
                                                 mock_close_connection,
                                                 mock_open_connection,
                                                 mock_init):
        context = {}
        cggrp = {'consistencygroup_id': 'fc8f2fec-fab2-4e34-9148-c094c913b9a3',
                 'id': '100'}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_cgsnapshot,
                          context,
                          cggrp,
                          [])
        mock_find_replay_profile.assert_called_once_with(
            cggrp['consistencygroup_id'])

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'snap_cg_replay',
                       return_value=None)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_replay_profile',
                       return_value=SCRPLAYPROFILE)
    def test_create_cgsnapshot_fail(self,
                                    mock_find_replay_profile,
                                    mock_snap_cg_replay,
                                    mock_close_connection,
                                    mock_open_connection,
                                    mock_init):
        context = {}
        cggrp = {'consistencygroup_id': 'fc8f2fec-fab2-4e34-9148-c094c913b9a3',
                 'id': '100'}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_cgsnapshot,
                          context,
                          cggrp,
                          [])
        mock_find_replay_profile.assert_called_once_with(
            cggrp['consistencygroup_id'])
        mock_snap_cg_replay.assert_called_once_with(self.SCRPLAYPROFILE,
                                                    cggrp['id'],
                                                    0)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'delete_cg_replay',
                       return_value=True)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_replay_profile',
                       return_value=SCRPLAYPROFILE)
    def test_delete_cgsnapshot(self,
                               mock_find_replay_profile,
                               mock_delete_cg_replay,
                               mock_close_connection,
                               mock_open_connection,
                               mock_init):
        mock_snapshot = mock.MagicMock()
        expected_snapshots = [mock_snapshot]
        context = {}
        cgsnap = {'consistencygroup_id':
                  'fc8f2fec-fab2-4e34-9148-c094c913b9a3',
                  'id': '100',
                  'status': 'deleted'}
        model_update, snapshots = self.driver.delete_cgsnapshot(
            context, cgsnap, [mock_snapshot])
        mock_find_replay_profile.assert_called_once_with(
            cgsnap['consistencygroup_id'])
        mock_delete_cg_replay.assert_called_once_with(self.SCRPLAYPROFILE,
                                                      cgsnap['id'])
        self.assertEqual({'status': cgsnap['status']}, model_update)
        self.assertEqual(expected_snapshots, snapshots)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'delete_cg_replay')
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_replay_profile',
                       return_value=None)
    def test_delete_cgsnapshot_profile_not_found(self,
                                                 mock_find_replay_profile,
                                                 mock_delete_cg_replay,
                                                 mock_close_connection,
                                                 mock_open_connection,
                                                 mock_init):
        mock_snapshot = mock.MagicMock()
        expected_snapshots = [mock_snapshot]
        context = {}
        cgsnap = {'consistencygroup_id':
                  'fc8f2fec-fab2-4e34-9148-c094c913b9a3',
                  'id': '100',
                  'status': 'deleted'}
        model_update, snapshots = self.driver.delete_cgsnapshot(
            context, cgsnap, [mock_snapshot])
        mock_find_replay_profile.assert_called_once_with(
            cgsnap['consistencygroup_id'])

        self.assertFalse(mock_delete_cg_replay.called)
        self.assertEqual({'status': cgsnap['status']}, model_update)
        self.assertEqual(expected_snapshots, snapshots)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'delete_cg_replay',
                       return_value=False)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_replay_profile',
                       return_value=SCRPLAYPROFILE)
    def test_delete_cgsnapshot_profile_failed_delete(self,
                                                     mock_find_replay_profile,
                                                     mock_delete_cg_replay,
                                                     mock_close_connection,
                                                     mock_open_connection,
                                                     mock_init):
        context = {}
        cgsnap = {'consistencygroup_id':
                  'fc8f2fec-fab2-4e34-9148-c094c913b9a3',
                  'id': '100',
                  'status': 'available'}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.delete_cgsnapshot,
                          context,
                          cgsnap,
                          [])
        mock_find_replay_profile.assert_called_once_with(
            cgsnap['consistencygroup_id'])
        mock_delete_cg_replay.assert_called_once_with(self.SCRPLAYPROFILE,
                                                      cgsnap['id'])

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_volume',
                       return_value={'id': 'guid'})
    @mock.patch.object(dell_storagecenter_iscsi.DellStorageCenterISCSIDriver,
                       '_create_replications',
                       return_value=None)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'manage_existing')
    def test_manage_existing(self,
                             mock_manage_existing,
                             mock_create_replications,
                             mock_find_volume,
                             mock_close_connection,
                             mock_open_connection,
                             mock_init):
        # Very little to do in this one.  The call is sent
        # straight down.
        volume = {'id': 'guid'}
        existing_ref = {'source-name': 'imavolumename'}
        self.driver.manage_existing(volume, existing_ref)
        mock_manage_existing.assert_called_once_with(volume['id'],
                                                     existing_ref)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_volume',
                       return_value={'id': 'guid'})
    @mock.patch.object(dell_storagecenter_iscsi.DellStorageCenterISCSIDriver,
                       '_create_replications',
                       return_value=None)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'manage_existing')
    def test_manage_existing_id(self,
                                mock_manage_existing,
                                mock_create_replications,
                                mock_find_volume,
                                mock_close_connection,
                                mock_open_connection,
                                mock_init):
        # Very little to do in this one.  The call is sent
        # straight down.
        volume = {'id': 'guid'}
        existing_ref = {'source-id': 'imadeviceid'}
        self.driver.manage_existing(volume, existing_ref)
        mock_manage_existing.assert_called_once_with(volume['id'],
                                                     existing_ref)

    def test_manage_existing_bad_ref(self,
                                     mock_close_connection,
                                     mock_open_connection,
                                     mock_init):
        volume = {'id': 'guid'}
        existing_ref = {'banana-name': 'imavolumename'}
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing,
                          volume,
                          existing_ref)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'get_unmanaged_volume_size',
                       return_value=4)
    def test_manage_existing_get_size(self,
                                      mock_get_unmanaged_volume_size,
                                      mock_close_connection,
                                      mock_open_connection,
                                      mock_init):
        # Almost nothing to test here.  Just that we call our function.
        volume = {'id': 'guid'}
        existing_ref = {'source-name': 'imavolumename'}
        res = self.driver.manage_existing_get_size(volume, existing_ref)
        mock_get_unmanaged_volume_size.assert_called_once_with(existing_ref)
        # The above is 4GB and change.
        self.assertEqual(4, res)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'get_unmanaged_volume_size',
                       return_value=4)
    def test_manage_existing_get_size_id(self,
                                         mock_get_unmanaged_volume_size,
                                         mock_close_connection,
                                         mock_open_connection,
                                         mock_init):
        # Almost nothing to test here.  Just that we call our function.
        volume = {'id': 'guid'}
        existing_ref = {'source-id': 'imadeviceid'}
        res = self.driver.manage_existing_get_size(volume, existing_ref)
        mock_get_unmanaged_volume_size.assert_called_once_with(existing_ref)
        # The above is 4GB and change.
        self.assertEqual(4, res)

    def test_manage_existing_get_size_bad_ref(self,
                                              mock_close_connection,
                                              mock_open_connection,
                                              mock_init):
        volume = {'id': 'guid'}
        existing_ref = {'banana-name': 'imavolumename'}
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_get_size,
                          volume,
                          existing_ref)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'update_storage_profile')
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'update_replay_profiles')
    @mock.patch.object(dell_storagecenter_iscsi.DellStorageCenterISCSIDriver,
                       '_create_replications')
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'update_replicate_active_replay')
    def test_retype_not_our_extra_specs(self,
                                        mock_update_replicate_active_replay,
                                        mock_create_replications,
                                        mock_update_replay_profile,
                                        mock_update_storage_profile,
                                        mock_find_volume,
                                        mock_close_connection,
                                        mock_open_connection,
                                        mock_init):
        res = self.driver.retype(
            None, {'id': 'guid'}, None, {'extra_specs': None}, None)
        self.assertTrue(res)
        self.assertFalse(mock_update_replicate_active_replay.called)
        self.assertFalse(mock_create_replications.called)
        self.assertFalse(mock_update_replay_profile.called)
        self.assertFalse(mock_update_storage_profile.called)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'update_replay_profiles')
    def test_retype_replay_profiles(self,
                                    mock_update_replay_profiles,
                                    mock_find_volume,
                                    mock_close_connection,
                                    mock_open_connection,
                                    mock_init):
        mock_update_replay_profiles.side_effect = [True, False]
        # Normal successful run.
        res = self.driver.retype(
            None, {'id': 'guid'}, None,
            {'extra_specs': {'storagetype:replayprofiles': ['A', 'B']}},
            None)
        mock_update_replay_profiles.assert_called_once_with(self.VOLUME, 'B')
        self.assertTrue(res)
        # Run fails.  Make sure this returns False.
        res = self.driver.retype(
            None, {'id': 'guid'}, None,
            {'extra_specs': {'storagetype:replayprofiles': ['B', 'A']}},
            None)
        self.assertFalse(res)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(dell_storagecenter_iscsi.DellStorageCenterISCSIDriver,
                       '_create_replications',
                       return_value={'replication_status': 'enabled',
                                     'replication_driver_data': '54321'})
    @mock.patch.object(dell_storagecenter_iscsi.DellStorageCenterISCSIDriver,
                       '_delete_replications')
    def test_retype_create_replications(self,
                                        mock_delete_replications,
                                        mock_create_replications,
                                        mock_find_volume,
                                        mock_close_connection,
                                        mock_open_connection,
                                        mock_init):

        res = self.driver.retype(
            None, {'id': 'guid'}, None,
            {'extra_specs': {'replication_enabled': [False, True]}},
            None)
        self.assertTrue(mock_create_replications.called)
        self.assertFalse(mock_delete_replications.called)
        self.assertEqual({'replication_status': 'enabled',
                          'replication_driver_data': '54321'}, res)
        res = self.driver.retype(
            None, {'id': 'guid'}, None,
            {'extra_specs': {'replication_enabled': [True, False]}},
            None)
        self.assertTrue(mock_delete_replications.called)
        self.assertEqual({'replication_status': 'disabled',
                          'replication_driver_data': ''}, res)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'update_replicate_active_replay')
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_volume',
                       return_value=VOLUME)
    def test_retype_active_replay(self,
                                  mock_find_volume,
                                  mock_update_replicate_active_replay,
                                  mock_close_connection,
                                  mock_open_connection,
                                  mock_init):
        # Success, Success, Not called and fail.
        mock_update_replicate_active_replay.side_effect = [True, True, False]
        res = self.driver.retype(
            None, {'id': 'guid'}, None,
            {'extra_specs': {'replication:activereplay': ['', '<is> True']}},
            None)
        self.assertTrue(res)
        res = self.driver.retype(
            None, {'id': 'guid'}, None,
            {'extra_specs': {'replication:activereplay': ['<is> True', '']}},
            None)
        self.assertTrue(res)
        res = self.driver.retype(
            None, {'id': 'guid'}, None,
            {'extra_specs': {'replication:activereplay': ['', '']}},
            None)
        self.assertTrue(res)
        res = self.driver.retype(
            None, {'id': 'guid'}, None,
            {'extra_specs': {'replication:activereplay': ['', '<is> True']}},
            None)
        self.assertFalse(res)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_volume',
                       return_value=VOLUME)
    def test_retype_same(self,
                         mock_find_volume,
                         mock_close_connection,
                         mock_open_connection,
                         mock_init):
        res = self.driver.retype(
            None, {'id': 'guid'}, None,
            {'extra_specs': {'storagetype:storageprofile': ['A', 'A']}},
            None)
        self.assertTrue(res)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'unmanage')
    def test_unmanage(self,
                      mock_unmanage,
                      mock_find_volume,
                      mock_close_connection,
                      mock_open_connection,
                      mock_init):
        volume = {'id': 'guid'}
        self.driver.unmanage(volume)
        mock_find_volume.assert_called_once_with(volume['id'])
        mock_unmanage.assert_called_once_with(self.VOLUME)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_volume',
                       return_value=None)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'unmanage')
    def test_unmanage_volume_not_found(self,
                                       mock_unmanage,
                                       mock_find_volume,
                                       mock_close_connection,
                                       mock_open_connection,
                                       mock_init):
        volume = {'id': 'guid'}
        self.driver.unmanage(volume)
        mock_find_volume.assert_called_once_with(volume['id'])
        self.assertFalse(mock_unmanage.called)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'update_storage_profile')
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_sc',
                       return_value=12345)
    def test_retype(self,
                    mock_find_sc,
                    mock_find_volume,
                    mock_update_storage_profile,
                    mock_close_connection,
                    mock_open_connection,
                    mock_init):
        res = self.driver.retype(
            None, {'id': 'volid'}, None,
            {'extra_specs': {'storagetype:storageprofile': ['A', 'B']}},
            None)
        mock_update_storage_profile.assert_called_once_with(
            self.VOLUME, 'B')
        self.assertTrue(res)

    def test__parse_secondary(self,
                              mock_close_connection,
                              mock_open_connection,
                              mock_init):
        backends = self.driver.backends
        self.driver.backends = [{'target_device_id': '12345',
                                 'qosnode': 'cinderqos'},
                                {'target_device_id': '67890',
                                 'qosnode': 'cinderqos'}]
        mock_api = mock.MagicMock()
        # Good run.  Secondary in replication_driver_data and backend.  sc up.
        destssn = self.driver._parse_secondary(mock_api, '67890')
        self.assertEqual(67890, destssn)
        # Bad run.  Secondary not in backend.
        destssn = self.driver._parse_secondary(mock_api, '99999')
        self.assertIsNone(destssn)
        # Good run.
        destssn = self.driver._parse_secondary(mock_api, '12345')
        self.assertEqual(12345, destssn)
        self.driver.backends = backends

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_sc')
    def test__parse_secondary_sc_down(self,
                                      mock_find_sc,
                                      mock_close_connection,
                                      mock_open_connection,
                                      mock_init):
        backends = self.driver.backends
        self.driver.backends = [{'target_device_id': '12345',
                                 'qosnode': 'cinderqos'},
                                {'target_device_id': '67890',
                                 'qosnode': 'cinderqos'}]
        mock_api = mock.MagicMock()
        # Bad run.  Good selection.  SC down.
        mock_api.find_sc = mock.MagicMock(
            side_effect=exception.VolumeBackendAPIException(data='1234'))
        destssn = self.driver._parse_secondary(mock_api, '12345')
        self.assertIsNone(destssn)
        self.driver.backends = backends

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'break_replication')
    @mock.patch.object(dell_storagecenter_iscsi.DellStorageCenterISCSIDriver,
                       '_parse_secondary')
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_volume')
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'remove_mappings')
    def test_failover_host(self,
                           mock_remove_mappings,
                           mock_find_volume,
                           mock_parse_secondary,
                           mock_break_replication,
                           mock_close_connection,
                           mock_open_connection,
                           mock_init):
        self.driver.replication_enabled = False
        self.driver.failed_over = False
        volumes = [{'id': 'guid1', 'replication_driver_data': '12345'},
                   {'id': 'guid2', 'replication_driver_data': '12345'}]
        # No run. Not doing repl.  Should raise.
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.failover_host,
                          {},
                          volumes,
                          '12345')
        # Good run
        self.driver.replication_enabled = True
        mock_parse_secondary.return_value = 12345
        expected_destssn = 12345
        expected_volume_update = [{'volume_id': 'guid1', 'updates':
                                   {'replication_status': 'failed-over'}},
                                  {'volume_id': 'guid2', 'updates':
                                   {'replication_status': 'failed-over'}}]
        destssn, volume_update = self.driver.failover_host(
            {}, volumes, '12345')
        self.assertEqual(expected_destssn, destssn)
        self.assertEqual(expected_volume_update, volume_update)
        # Good run. Not all volumes replicated.
        volumes = [{'id': 'guid1', 'replication_driver_data': '12345'},
                   {'id': 'guid2', 'replication_driver_data': ''}]
        expected_volume_update = [{'volume_id': 'guid1', 'updates':
                                   {'replication_status': 'failed-over'}},
                                  {'volume_id': 'guid2', 'updates':
                                   {'status': 'error'}}]
        destssn, volume_update = self.driver.failover_host(
            {}, volumes, '12345')
        self.assertEqual(expected_destssn, destssn)
        self.assertEqual(expected_volume_update, volume_update)
        # Good run. Not all volumes replicated. No replication_driver_data.
        volumes = [{'id': 'guid1', 'replication_driver_data': '12345'},
                   {'id': 'guid2'}]
        expected_volume_update = [{'volume_id': 'guid1', 'updates':
                                   {'replication_status': 'failed-over'}},
                                  {'volume_id': 'guid2', 'updates':
                                   {'status': 'error'}}]
        destssn, volume_update = self.driver.failover_host(
            {}, volumes, '12345')
        self.assertEqual(expected_destssn, destssn)
        self.assertEqual(expected_volume_update, volume_update)
        # Good run. No volumes replicated. No replication_driver_data.
        volumes = [{'id': 'guid1'},
                   {'id': 'guid2'}]
        expected_volume_update = [{'volume_id': 'guid1', 'updates':
                                   {'status': 'error'}},
                                  {'volume_id': 'guid2', 'updates':
                                   {'status': 'error'}}]
        destssn, volume_update = self.driver.failover_host(
            {}, volumes, '12345')
        self.assertEqual(expected_destssn, destssn)
        self.assertEqual(expected_volume_update, volume_update)
        # Secondary not found.
        mock_parse_secondary.return_value = None
        self.assertRaises(exception.InvalidInput,
                          self.driver.failover_host,
                          {},
                          volumes,
                          '54321')
        # Already failed over.
        self.driver.failed_over = True
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.failover_host,
                          {},
                          volumes,
                          '12345')
        self.driver.replication_enabled = False

    def test__get_unmanaged_replay(self,
                                   mock_close_connection,
                                   mock_open_connection,
                                   mock_init):
        mock_api = mock.MagicMock()
        existing_ref = None
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver._get_unmanaged_replay,
                          mock_api,
                          'guid',
                          existing_ref)
        existing_ref = {'source-id': 'Not a source-name'}
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver._get_unmanaged_replay,
                          mock_api,
                          'guid',
                          existing_ref)
        existing_ref = {'source-name': 'name'}
        mock_api.find_volume = mock.MagicMock(return_value=None)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver._get_unmanaged_replay,
                          mock_api,
                          'guid',
                          existing_ref)
        mock_api.find_volume.return_value = {'instanceId': '1'}
        mock_api.find_replay = mock.MagicMock(return_value=None)
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver._get_unmanaged_replay,
                          mock_api,
                          'guid',
                          existing_ref)
        mock_api.find_replay.return_value = {'instanceId': 2}
        ret = self.driver._get_unmanaged_replay(mock_api, 'guid', existing_ref)
        self.assertEqual({'instanceId': 2}, ret)

    @mock.patch.object(dell_storagecenter_iscsi.DellStorageCenterISCSIDriver,
                       '_get_unmanaged_replay')
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'manage_replay')
    def test_manage_existing_snapshot(self,
                                      mock_manage_replay,
                                      mock_get_unmanaged_replay,
                                      mock_close_connection,
                                      mock_open_connection,
                                      mock_init):
        snapshot = {'volume_id': 'guida',
                    'id': 'guidb'}
        existing_ref = {'source-name': 'name'}
        screplay = {'description': 'name'}
        mock_get_unmanaged_replay.return_value = screplay
        mock_manage_replay.return_value = True
        self.driver.manage_existing_snapshot(snapshot, existing_ref)
        self.assertEqual(1, mock_get_unmanaged_replay.call_count)
        mock_manage_replay.assert_called_once_with(screplay, 'guidb')
        mock_manage_replay.return_value = False
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.manage_existing_snapshot,
                          snapshot,
                          existing_ref)

    @mock.patch.object(dell_storagecenter_iscsi.DellStorageCenterISCSIDriver,
                       '_get_unmanaged_replay')
    def test_manage_existing_snapshot_get_size(self,
                                               mock_get_unmanaged_replay,
                                               mock_close_connection,
                                               mock_open_connection,
                                               mock_init):
        snapshot = {'volume_id': 'a',
                    'id': 'b'}
        existing_ref = {'source-name'}
        # Good size.
        mock_get_unmanaged_replay.return_value = {'size':
                                                  '1.073741824E9 Bytes'}
        ret = self.driver.manage_existing_snapshot_get_size(snapshot,
                                                            existing_ref)
        self.assertEqual(1, ret)
        # Not on 1GB boundries.
        mock_get_unmanaged_replay.return_value = {'size':
                                                  '2.073741824E9 Bytes'}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.manage_existing_snapshot_get_size,
                          snapshot,
                          existing_ref)

    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_volume')
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'find_replay')
    @mock.patch.object(dell_storagecenter_api.StorageCenterApi,
                       'unmanage_replay')
    def test_unmanage_snapshot(self,
                               mock_unmanage_replay,
                               mock_find_replay,
                               mock_find_volume,
                               mock_close_connection,
                               mock_open_connection,
                               mock_init):
        snapshot = {'volume_id': 'guida',
                    'id': 'guidb'}
        screplay = {'description': 'guidb'}
        mock_find_volume.return_value = None
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.unmanage_snapshot,
                          snapshot)
        mock_find_volume.return_value = {'name': 'guida'}
        mock_find_replay.return_value = None
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.unmanage_snapshot,
                          snapshot)
        mock_find_replay.return_value = screplay
        self.driver.unmanage_snapshot(snapshot)
        mock_unmanage_replay.assert_called_once_with(screplay)
