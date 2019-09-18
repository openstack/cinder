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

import eventlet
import mock
import uuid

from cinder import context
from cinder import exception
from cinder.objects import fields
from cinder import test
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume
from cinder.volume.drivers.dell_emc.sc import storagecenter_api
from cinder.volume.drivers.dell_emc.sc import storagecenter_iscsi
from cinder.volume import volume_types

# We patch these here as they are used by every test to keep
# from trying to contact a Dell Storage Center.
MOCKAPI = mock.MagicMock()


@mock.patch.object(storagecenter_api.HttpClient,
                   '__init__',
                   return_value=None)
@mock.patch.object(storagecenter_api.SCApi,
                   'open_connection',
                   return_value=MOCKAPI)
@mock.patch.object(storagecenter_api.SCApi,
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
                u'notes': u'Created by Dell EMC Cinder Driver',
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
                      u'notes': u'Created by Dell EMC Cinder Driver',
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
                        'discard': True,
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
        self.configuration.target_ip_address = '192.168.1.1'
        self.configuration.target_port = 3260
        self.configuration.excluded_domain_ip = None
        self.configuration.excluded_domain_ips = []
        self._context = context.get_admin_context()

        self.driver = storagecenter_iscsi.SCISCSIDriver(
            configuration=self.configuration)

        self.driver.do_setup(None)

        self.driver._stats = {'QoS_support': False,
                              'volume_backend_name': 'dell-1',
                              'free_capacity_gb': 12123,
                              'driver_version': '1.0.1',
                              'total_capacity_gb': 12388,
                              'reserved_percentage': 0,
                              'vendor_name': 'Dell EMC',
                              'storage_protocol': 'iSCSI'}

        # Start with none.  Add in the specific tests later.
        # Mock tests bozo this.
        self.driver.backends = None
        self.driver.replication_enabled = False

        self.mock_sleep = self.mock_object(eventlet, 'sleep')

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
        }

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_sc')
    def test_check_for_setup_error(self,
                                   mock_find_sc,
                                   mock_close_connection,
                                   mock_open_connection,
                                   mock_init):
        # Fail, Fail due to repl partner not found, success.
        mock_find_sc.side_effect = [exception.VolumeBackendAPIException(''),
                                    10000,
                                    12345,
                                    exception.VolumeBackendAPIException(''),
                                    10000,
                                    12345,
                                    67890]

        # Find SC throws
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.check_for_setup_error)
        # Replication enabled but one backend is down.
        self.driver.replication_enabled = True
        self.driver.backends = [{'target_device_id': '12345',
                                 'managed_backend_name': 'host@dell1',
                                 'qosnode': 'cinderqos'},
                                {'target_device_id': '67890',
                                 'managed_backend_name': 'host@dell2',
                                 'qosnode': 'otherqos'}]
        self.assertRaises(exception.InvalidHost,
                          self.driver.check_for_setup_error)
        # Good run. Should run without exceptions.
        self.driver.check_for_setup_error()
        # failed over run
        mock_find_sc.side_effect = None
        mock_find_sc.reset_mock()
        mock_find_sc.return_value = 10000
        self.driver.failed_over = True
        self.driver.check_for_setup_error()
        # find sc should be called exactly once
        mock_find_sc.assert_called_once_with()
        # No repl run
        mock_find_sc.reset_mock()
        mock_find_sc.return_value = 10000
        self.driver.failed_over = False
        self.driver.replication_enabled = False
        self.driver.backends = None
        self.driver.check_for_setup_error()
        mock_find_sc.assert_called_once_with()

    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
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

        vol = {'id': fake.VOLUME_ID, 'replication_driver_data': ''}
        scvol = {'name': fake.VOLUME_ID}
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

    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       '_get_volume_extra_specs')
    def test__create_replications_live_volume(self,
                                              mock_get_volume_extra_specs,
                                              mock_close_connection,
                                              mock_open_connection,
                                              mock_init):
        backends = self.driver.backends
        model_update = {'replication_status': 'enabled',
                        'replication_driver_data': '12345'}

        vol = {'id': fake.VOLUME_ID, 'replication_driver_data': ''}
        scvol = {'name': fake.VOLUME_ID}

        mock_api = mock.MagicMock()
        mock_api.create_live_volume = mock.MagicMock(
            return_value={'instanceId': '1'})
        # Live volume with two backends defined.
        self.driver.backends = [{'target_device_id': '12345',
                                 'managed_backend_name': 'host@dell1',
                                 'qosnode': 'cinderqos',
                                 'remoteqos': 'remoteqos'},
                                {'target_device_id': '67890',
                                 'managed_backend_name': 'host@dell2',
                                 'qosnode': 'otherqos',
                                 'remoteqos': 'remoteqos'}]
        mock_get_volume_extra_specs.return_value = {
            'replication:activereplay': '<is> True',
            'replication_enabled': '<is> True',
            'replication:livevolume': '<is> True'}
        self.assertRaises(exception.ReplicationError,
                          self.driver._create_replications,
                          mock_api,
                          vol,
                          scvol)
        # Live volume
        self.driver.backends = [{'target_device_id': '12345',
                                 'managed_backend_name': 'host@dell1',
                                 'qosnode': 'cinderqos',
                                 'diskfolder': 'ssd',
                                 'remoteqos': 'remoteqos'}]
        res = self.driver._create_replications(mock_api, vol, scvol)
        mock_api.create_live_volume.assert_called_once_with(
            scvol, '12345', True, False, False, 'cinderqos', 'remoteqos')
        self.assertEqual(model_update, res)
        # Active replay False
        mock_get_volume_extra_specs.return_value = {
            'replication_enabled': '<is> True',
            'replication:livevolume': '<is> True'}
        res = self.driver._create_replications(mock_api, vol, scvol)
        mock_api.create_live_volume.assert_called_with(
            scvol, '12345', False, False, False, 'cinderqos', 'remoteqos')
        self.assertEqual(model_update, res)
        # Sync
        mock_get_volume_extra_specs.return_value = {
            'replication_enabled': '<is> True',
            'replication:livevolume': '<is> True',
            'replication_type': '<in> sync'}
        res = self.driver._create_replications(mock_api, vol, scvol)
        mock_api.create_live_volume.assert_called_with(
            scvol, '12345', False, True, False, 'cinderqos', 'remoteqos')
        self.assertEqual(model_update, res)

        self.driver.backends = backends

    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       '_get_volume_extra_specs')
    def test__delete_replications(self,
                                  mock_get_volume_extra_specs,
                                  mock_close_connection,
                                  mock_open_connection,
                                  mock_init):
        backends = self.driver.backends
        vol = {'id': fake.VOLUME_ID}
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
        vol = {'id': fake.VOLUME_ID, 'replication_driver_data': ''}
        self.driver._delete_replications(mock_api, vol)
        self.assertFalse(mock_api.delete_replication.called)
        # Something to call.
        vol = {'id': fake.VOLUME_ID, 'replication_driver_data': '12345,67890'}
        self.driver._delete_replications(mock_api, vol)
        mock_api.delete_replication.assert_any_call(scvol, 12345)
        mock_api.delete_replication.assert_any_call(scvol, 67890)
        self.driver.backends = backends

    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       '_get_volume_extra_specs')
    def test__delete_live_volume(self,
                                 mock_get_volume_extra_specs,
                                 mock_close_connection,
                                 mock_open_connection,
                                 mock_init):
        backends = self.driver.backends
        vol = {'id': fake.VOLUME_ID,
               'provider_id': '101.101'}
        mock_api = mock.MagicMock()
        sclivevol = {'instanceId': '101.102',
                     'secondaryVolume': {'instanceId': '102.101',
                                         'instanceName': fake.VOLUME_ID},
                     'secondaryScSerialNumber': 102,
                     'secondaryRole': 'Secondary'}
        mock_api.get_live_volume = mock.MagicMock(return_value=sclivevol)
        # No replication driver data.
        ret = self.driver._delete_live_volume(mock_api, vol)
        self.assertFalse(mock_api.get_live_volume.called)
        self.assertFalse(ret)
        # Bogus rdd
        vol = {'id': fake.VOLUME_ID,
               'provider_id': '101.101',
               'replication_driver_data': ''}
        ret = self.driver._delete_live_volume(mock_api, vol)
        self.assertFalse(mock_api.get_live_volume.called)
        self.assertFalse(ret)
        # Valid delete.
        mock_api.delete_live_volume = mock.MagicMock(return_value=True)
        vol = {'id': fake.VOLUME_ID,
               'provider_id': '101.101',
               'replication_driver_data': '102'}
        ret = self.driver._delete_live_volume(mock_api, vol)
        mock_api.get_live_volume.assert_called_with('101.101', fake.VOLUME_ID)
        self.assertTrue(ret)
        # Wrong ssn.
        vol = {'id': fake.VOLUME_ID,
               'provider_id': '101.101',
               'replication_driver_data': '103'}
        ret = self.driver._delete_live_volume(mock_api, vol)
        mock_api.get_live_volume.assert_called_with('101.101', fake.VOLUME_ID)
        self.assertFalse(ret)
        # No live volume found.
        mock_api.get_live_volume.return_value = None
        ret = self.driver._delete_live_volume(mock_api, vol)
        mock_api.get_live_volume.assert_called_with('101.101', fake.VOLUME_ID)
        self.assertFalse(ret)

        self.driver.backends = backends

    @mock.patch.object(storagecenter_api.SCApi,
                       'create_volume',
                       return_value=VOLUME)
    def test_create_volume(self,
                           mock_create_volume,
                           mock_close_connection,
                           mock_open_connection,
                           mock_init):
        volume = {'id': fake.VOLUME_ID, 'size': 1}
        self.driver.create_volume(volume)
        mock_create_volume.assert_called_once_with(
            fake.VOLUME_ID, 1, None, None, None, None, None)

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_replay_profile',
                       return_value='fake')
    @mock.patch.object(storagecenter_api.SCApi,
                       'update_cg_volumes')
    @mock.patch.object(storagecenter_api.SCApi,
                       'create_volume',
                       return_value=VOLUME)
    def test_create_volume_with_group(self,
                                      mock_create_volume,
                                      mock_update_cg_volumes,
                                      mock_find_replay_profile,
                                      mock_close_connection,
                                      mock_open_connection,
                                      mock_init):
        volume = {'id': fake.VOLUME_ID, 'size': 1,
                  'group_id': fake.GROUP_ID}
        self.driver.create_volume(volume)
        mock_create_volume.assert_called_once_with(
            fake.VOLUME_ID, 1, None, None, None, None, None)
        self.assertTrue(mock_find_replay_profile.called)
        self.assertTrue(mock_update_cg_volumes.called)

    @mock.patch.object(storagecenter_api.SCApi,
                       'create_volume',
                       return_value=VOLUME)
    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'storagetype:volumeqos': 'volumeqos'})
    def test_create_volume_volumeqos_profile(self,
                                             mock_extra,
                                             mock_create_volume,
                                             mock_close_connection,
                                             mock_open_connection,
                                             mock_init):
        volume = {'id': fake.VOLUME_ID, 'size': 1, 'volume_type_id': 'abc'}
        self.driver.create_volume(volume)
        mock_create_volume.assert_called_once_with(
            fake.VOLUME_ID, 1, None, None, 'volumeqos', None, None)

    @mock.patch.object(storagecenter_api.SCApi,
                       'create_volume',
                       return_value=VOLUME)
    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'storagetype:groupqos': 'groupqos'})
    def test_create_volume_groupqos_profile(self,
                                            mock_extra,
                                            mock_create_volume,
                                            mock_close_connection,
                                            mock_open_connection,
                                            mock_init):
        volume = {'id': fake.VOLUME_ID, 'size': 1, 'volume_type_id': 'abc'}
        self.driver.create_volume(volume)
        mock_create_volume.assert_called_once_with(
            fake.VOLUME_ID, 1, None, None, None, 'groupqos', None)

    @mock.patch.object(storagecenter_api.SCApi,
                       'create_volume',
                       return_value=VOLUME)
    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'storagetype:datareductionprofile': 'drprofile'})
    def test_create_volume_data_reduction_profile(self,
                                                  mock_extra,
                                                  mock_create_volume,
                                                  mock_close_connection,
                                                  mock_open_connection,
                                                  mock_init):
        volume = {'id': fake.VOLUME_ID, 'size': 1, 'volume_type_id': 'abc'}
        self.driver.create_volume(volume)
        mock_create_volume.assert_called_once_with(
            fake.VOLUME_ID, 1, None, None, None, None, 'drprofile')

    @mock.patch.object(storagecenter_api.SCApi,
                       'create_volume',
                       return_value=VOLUME)
    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'storagetype:storageprofile': 'HighPriority'})
    def test_create_volume_storage_profile(self,
                                           mock_extra,
                                           mock_create_volume,
                                           mock_close_connection,
                                           mock_open_connection,
                                           mock_init):
        volume = {'id': fake.VOLUME_ID, 'size': 1, 'volume_type_id': 'abc'}
        self.driver.create_volume(volume)
        mock_create_volume.assert_called_once_with(
            fake.VOLUME_ID, 1, "HighPriority", None, None, None, None)

    @mock.patch.object(storagecenter_api.SCApi,
                       'create_volume',
                       return_value=VOLUME)
    @mock.patch.object(
        volume_types,
        'get_volume_type_extra_specs',
        return_value={'storagetype:replayprofiles': 'Daily'})
    def test_create_volume_replay_profiles(self,
                                           mock_extra,
                                           mock_create_volume,
                                           mock_close_connection,
                                           mock_open_connection,
                                           mock_init):
        volume = {'id': fake.VOLUME_ID, 'size': 1, 'volume_type_id': 'abc'}
        self.driver.create_volume(volume)
        mock_create_volume.assert_called_once_with(
            fake.VOLUME_ID, 1, None, 'Daily', None, None, None)

    @mock.patch.object(storagecenter_api.SCApi,
                       'create_volume',
                       return_value=VOLUME)
    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       '_create_replications',
                       return_value={'replication_status': 'enabled',
                                     'replication_driver_data': 'ssn'})
    def test_create_volume_replication(self,
                                       mock_create_replications,
                                       mock_create_volume,
                                       mock_close_connection,
                                       mock_open_connection,
                                       mock_init):
        volume = {'id': fake.VOLUME_ID, 'size': 1}
        ret = self.driver.create_volume(volume)
        self.assertEqual({'replication_status': 'enabled',
                          'replication_driver_data': 'ssn',
                          'provider_id': self.VOLUME[u'instanceId']}, ret)

    @mock.patch.object(storagecenter_api.SCApi,
                       'create_volume',
                       return_value=VOLUME)
    @mock.patch.object(storagecenter_api.SCApi,
                       'delete_volume')
    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       '_create_replications')
    def test_create_volume_replication_raises(self,
                                              mock_create_replications,
                                              mock_delete_volume,
                                              mock_create_volume,
                                              mock_close_connection,
                                              mock_open_connection,
                                              mock_init):
        volume = {'id': fake.VOLUME_ID, 'size': 1}
        mock_create_replications.side_effect = (
            exception.VolumeBackendAPIException(data='abc'))
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume,
                          volume)
        self.assertTrue(mock_delete_volume.called)

    @mock.patch.object(storagecenter_api.SCApi,
                       'create_volume',
                       return_value=None)
    @mock.patch.object(storagecenter_api.SCApi,
                       'delete_volume')
    def test_create_volume_failure(self,
                                   mock_delete_volume,
                                   mock_create_volume,
                                   mock_close_connection,
                                   mock_open_connection,
                                   mock_init):
        volume = {'id': fake.VOLUME_ID, 'size': 1}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume, volume)
        self.assertTrue(mock_delete_volume.called)

    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       '_delete_replications')
    @mock.patch.object(storagecenter_api.SCApi,
                       'delete_volume',
                       return_value=True)
    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       '_get_replication_specs',
                       return_value={'enabled': True,
                                     'live': False})
    def test_delete_volume(self,
                           mock_get_replication_specs,
                           mock_delete_volume,
                           mock_delete_replications,
                           mock_close_connection,
                           mock_open_connection,
                           mock_init):
        volume = {'id': fake.VOLUME_ID}
        self.driver.delete_volume(volume)
        mock_delete_volume.assert_called_once_with(fake.VOLUME_ID, None)
        self.assertTrue(mock_delete_replications.called)
        self.assertEqual(1, mock_delete_replications.call_count)
        volume = {'id': fake.VOLUME_ID, 'provider_id': '1.1'}
        self.driver.delete_volume(volume)
        mock_delete_volume.assert_called_with(fake.VOLUME_ID, '1.1')
        self.assertTrue(mock_delete_replications.called)
        self.assertEqual(2, mock_delete_replications.call_count)

    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       '_delete_replications')
    @mock.patch.object(storagecenter_api.SCApi,
                       'delete_volume',
                       return_value=True)
    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       '_get_replication_specs',
                       return_value={'enabled': True,
                                     'live': False})
    def test_delete_volume_migrating(self,
                                     mock_get_replication_specs,
                                     mock_delete_volume,
                                     mock_delete_replications,
                                     mock_close_connection,
                                     mock_open_connection,
                                     mock_init):
        volume = {'id': fake.VOLUME_ID, '_name_id': fake.VOLUME2_ID,
                  'provider_id': '12345.100', 'migration_status': 'deleting'}
        self.driver.delete_volume(volume)
        mock_delete_volume.assert_called_once_with(fake.VOLUME2_ID, None)

    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       '_delete_live_volume')
    @mock.patch.object(storagecenter_api.SCApi,
                       'delete_volume',
                       return_value=True)
    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       '_get_replication_specs',
                       return_value={'enabled': True,
                                     'live': True})
    def test_delete_volume_live_volume(self,
                                       mock_get_replication_specs,
                                       mock_delete_volume,
                                       mock_delete_live_volume,
                                       mock_close_connection,
                                       mock_open_connection,
                                       mock_init):
        volume = {'id': fake.VOLUME_ID, 'provider_id': '1.1'}
        self.driver.delete_volume(volume)
        mock_delete_volume.assert_called_with(fake.VOLUME_ID, '1.1')
        self.assertTrue(mock_delete_live_volume.called)

    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       '_delete_replications')
    @mock.patch.object(storagecenter_api.SCApi,
                       'delete_volume',
                       return_value=False)
    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       '_get_replication_specs',
                       return_value={'enabled': True,
                                     'live': False})
    def test_delete_volume_failure(self,
                                   mock_get_replication_specs,
                                   mock_delete_volume,
                                   mock_delete_replications,
                                   mock_close_connection,
                                   mock_open_connection,
                                   mock_init):
        volume = {'id': fake.VOLUME_ID, 'size': 1}
        self.assertRaises(exception.VolumeIsBusy,
                          self.driver.delete_volume,
                          volume)
        self.assertTrue(mock_delete_replications.called)

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
                       return_value=MAPPINGS[0])
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_iscsi_properties',
                       return_value=ISCSI_PROPERTIES)
    def test_initialize_connection(self,
                                   mock_find_iscsi_props,
                                   mock_map_volume,
                                   mock_get_volume,
                                   mock_find_volume,
                                   mock_create_server,
                                   mock_find_server,
                                   mock_close_connection,
                                   mock_open_connection,
                                   mock_init):
        provider_id = self.VOLUME[u'instanceId']
        volume = {'id': fake.VOLUME_ID,
                  'provider_id': provider_id}
        connector = self.connector
        data = self.driver.initialize_connection(volume, connector)
        self.assertEqual('iscsi', data['driver_volume_type'])
        # verify find_volume has been called and that is has been called twice
        mock_find_volume.assert_called_once_with(
            fake.VOLUME_ID, provider_id, False)
        mock_get_volume.assert_called_once_with(provider_id)
        expected = {'data': self.ISCSI_PROPERTIES,
                    'driver_volume_type': 'iscsi'}
        self.assertEqual(expected, data, 'Unexpected return value')

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
                       return_value=MAPPINGS[0])
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_iscsi_properties',
                       return_value=ISCSI_PROPERTIES)
    def test_initialize_connection_multi_path(self,
                                              mock_find_iscsi_props,
                                              mock_map_volume,
                                              mock_get_volume,
                                              mock_find_volume,
                                              mock_create_server,
                                              mock_find_server,
                                              mock_close_connection,
                                              mock_open_connection,
                                              mock_init):
        # Test case where connection is multipath
        provider_id = self.VOLUME[u'instanceId']
        volume = {'id': fake.VOLUME_ID,
                  'provider_id': provider_id}
        connector = self.connector_multipath

        data = self.driver.initialize_connection(volume, connector)
        self.assertEqual('iscsi', data['driver_volume_type'])
        # verify find_volume has been called and that is has been called twice
        mock_find_volume.called_once_with(fake.VOLUME_ID, provider_id)
        mock_get_volume.called_once_with(provider_id)
        props = self.ISCSI_PROPERTIES.copy()
        expected = {'data': props,
                    'driver_volume_type': 'iscsi'}
        self.assertEqual(expected, data, 'Unexpected return value')

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_server',
                       return_value=SCSERVER)
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(storagecenter_api.SCApi,
                       'map_volume',
                       return_value=MAPPINGS)
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_iscsi_properties',
                       return_value=None)
    def test_initialize_connection_no_iqn(self,
                                          mock_find_iscsi_properties,
                                          mock_map_volume,
                                          mock_find_volume,
                                          mock_find_server,
                                          mock_close_connection,
                                          mock_open_connection,
                                          mock_init):
        volume = {'id': fake.VOLUME_ID}
        connector = {}
        mock_find_iscsi_properties.side_effect = Exception('abc')
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
                       return_value=MAPPINGS)
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_iscsi_properties',
                       return_value=None)
    def test_initialize_connection_no_server(self,
                                             mock_find_iscsi_properties,
                                             mock_map_volume,
                                             mock_find_volume,
                                             mock_create_server,
                                             mock_find_server,
                                             mock_close_connection,
                                             mock_open_connection,
                                             mock_init):
        volume = {'id': fake.VOLUME_ID}
        connector = {}
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
                       return_value=MAPPINGS)
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_iscsi_properties',
                       return_value=None)
    def test_initialize_connection_vol_not_found(self,
                                                 mock_find_iscsi_properties,
                                                 mock_map_volume,
                                                 mock_find_volume,
                                                 mock_find_server,
                                                 mock_close_connection,
                                                 mock_open_connection,
                                                 mock_init):
        volume = {'name': fake.VOLUME_ID}
        connector = {}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.initialize_connection,
                          volume,
                          connector)

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
                       'map_volume',
                       return_value=None)
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_iscsi_properties',
                       return_value=ISCSI_PROPERTIES)
    def test_initialize_connection_map_vol_fail(self,
                                                mock_find_iscsi_props,
                                                mock_map_volume,
                                                mock_find_volume,
                                                mock_create_server,
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
                       return_value=MAPPINGS[0])
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_iscsi_properties',
                       return_value=ISCSI_PROPERTIES)
    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       '_is_live_vol')
    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       'initialize_secondary')
    def test_initialize_connection_live_volume(self,
                                               mock_initialize_secondary,
                                               mock_is_live_vol,
                                               mock_find_iscsi_props,
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
        mock_is_live_vol.return_value = True
        lvol_properties = {'access_mode': 'rw',
                           'target_discovered': False,
                           'target_iqn':
                               u'iqn:1',
                           'target_iqns':
                               [
                                   u'iqn:1',
                                   u'iqn:2'],
                           'target_lun': 1,
                           'target_luns': [1, 1],
                           'target_portal': u'192.168.1.21:3260',
                           'target_portals': [u'192.168.1.21:3260',
                                              u'192.168.1.22:3260']}
        mock_initialize_secondary.return_value = lvol_properties
        props = self.ISCSI_PROPERTIES.copy()
        props['target_iqns'] += lvol_properties['target_iqns']
        props['target_luns'] += lvol_properties['target_luns']
        props['target_portals'] += lvol_properties['target_portals']
        ret = self.driver.initialize_connection(volume, connector)
        expected = {'data': props,
                    'driver_volume_type': 'iscsi'}
        self.assertEqual(expected, ret)

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_server',
                       return_value=None)
    @mock.patch.object(storagecenter_api.SCApi,
                       'create_server',
                       return_value=SCSERVER)
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume')
    @mock.patch.object(storagecenter_api.SCApi,
                       'get_volume')
    @mock.patch.object(storagecenter_api.SCApi,
                       'map_volume',
                       return_value=MAPPINGS[0])
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_iscsi_properties')
    @mock.patch.object(storagecenter_api.SCApi,
                       'get_live_volume')
    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       '_is_live_vol')
    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       'initialize_secondary')
    def test_initialize_connection_live_volume_afo(self,
                                                   mock_initialize_secondary,
                                                   mock_is_live_vol,
                                                   mock_get_live_vol,
                                                   mock_find_iscsi_props,
                                                   mock_map_volume,
                                                   mock_get_volume,
                                                   mock_find_volume,
                                                   mock_create_server,
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
                     'primaryVolume': {'instanceId': '101.101',
                                       'instanceName': fake.VOLUME_ID},
                     'primaryScSerialNumber': 101,
                     'secondaryVolume': {'instanceId': '102.101',
                                         'instanceName': fake.VOLUME_ID},
                     'secondaryScSerialNumber': 102,
                     'secondaryRole': 'Activated'}
        mock_is_live_vol.return_value = True
        mock_get_live_vol.return_value = sclivevol
        props = {
            'access_mode': 'rw',
            'target_discovered': False,
            'target_iqn': u'iqn:1',
            'target_iqns': [u'iqn:1',
                            u'iqn:2'],
            'target_lun': 1,
            'target_luns': [1, 1],
            'target_portal': u'192.168.1.21:3260',
            'target_portals': [u'192.168.1.21:3260',
                               u'192.168.1.22:3260']
        }
        mock_find_iscsi_props.return_value = props
        ret = self.driver.initialize_connection(volume, connector)
        expected = {'data': props,
                    'driver_volume_type': 'iscsi'}
        expected['data']['discard'] = True
        self.assertEqual(expected, ret)
        self.assertFalse(mock_initialize_secondary.called)

    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       '_get_replication_specs',
                       return_value={'enabled': True, 'live': True})
    def test_is_live_vol(self,
                         mock_get_replication_specs,
                         mock_close_connection,
                         mock_open_connection,
                         mock_init):
        volume = {'id': fake.VOLUME_ID,
                  'provider_id': '101.1'}
        ret = self.driver._is_live_vol(volume)
        self.assertTrue(ret)

    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       '_get_replication_specs',
                       return_value={'enabled': True, 'live': False})
    def test_is_live_vol_repl_not_live(self,
                                       mock_get_replication_specs,
                                       mock_close_connection,
                                       mock_open_connection,
                                       mock_init):
        volume = {'id': fake.VOLUME_ID}
        ret = self.driver._is_live_vol(volume)
        self.assertFalse(ret)

    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       '_get_replication_specs',
                       return_value={'enabled': False, 'live': False})
    def test_is_live_vol_no_repl(self,
                                 mock_get_replication_specs,
                                 mock_close_connection,
                                 mock_open_connection,
                                 mock_init):
        volume = {'id': fake.VOLUME_ID}
        ret = self.driver._is_live_vol(volume)
        self.assertFalse(ret)

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
        mock_api.find_iscsi_properties = mock.MagicMock(
            return_value=self.ISCSI_PROPERTIES)
        mock_api.get_volume = mock.MagicMock(return_value=self.VOLUME)
        ret = self.driver.initialize_secondary(mock_api, sclivevol, 'iqn')
        self.assertEqual(self.ISCSI_PROPERTIES, ret)

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
        mock_api.find_iscsi_properties = mock.MagicMock(
            return_value=self.ISCSI_PROPERTIES)
        mock_api.get_volume = mock.MagicMock(return_value=self.VOLUME)
        ret = self.driver.initialize_secondary(mock_api, sclivevol, 'iqn')
        self.assertEqual(self.ISCSI_PROPERTIES, ret)

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
        expected = {'target_discovered': False,
                    'target_iqn': None,
                    'target_iqns': [],
                    'target_portal': None,
                    'target_portals': [],
                    'target_lun': None,
                    'target_luns': [],
                    }
        ret = self.driver.initialize_secondary(mock_api, sclivevol, 'iqn')
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
        expected = {'target_discovered': False,
                    'target_iqn': None,
                    'target_iqns': [],
                    'target_portal': None,
                    'target_portals': [],
                    'target_lun': None,
                    'target_luns': [],
                    }
        ret = self.driver.initialize_secondary(mock_api, sclivevol, 'iqn')
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
        expected = {'target_discovered': False,
                    'target_iqn': None,
                    'target_iqns': [],
                    'target_portal': None,
                    'target_portals': [],
                    'target_lun': None,
                    'target_luns': [],
                    }
        ret = self.driver.initialize_secondary(mock_api, sclivevol, 'iqn')
        self.assertEqual(expected, ret)

    def test_terminate_secondary(self,
                                 mock_close_connection,
                                 mock_open_connection,
                                 mock_init):
        sclivevol = {'instanceId': '101.101',
                     'secondaryVolume': {'instanceId': '102.101',
                                         'instanceName': fake.VOLUME_ID},
                     'secondaryScSerialNumber': 102}
        mock_api = mock.MagicMock()
        mock_api.find_server = mock.MagicMock(return_value=self.SCSERVER)
        mock_api.get_volume = mock.MagicMock(return_value=self.VOLUME)
        mock_api.unmap_volume = mock.MagicMock()
        self.driver.terminate_secondary(mock_api, sclivevol, 'iqn')
        mock_api.find_server.assert_called_once_with('iqn', 102)
        mock_api.get_volume.assert_called_once_with('102.101')
        mock_api.unmap_volume.assert_called_once_with(self.VOLUME,
                                                      self.SCSERVER)

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume')
    @mock.patch.object(storagecenter_api.SCApi,
                       'unmap_all')
    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
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
        self.assertTrue(res)
        mock_unmap_all.assert_called_once_with(scvol)

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume')
    @mock.patch.object(storagecenter_api.SCApi,
                       'unmap_all')
    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       '_is_live_vol')
    def test_force_detach_fail(self, mock_is_live_vol, mock_unmap_all,
                               mock_find_volume, mock_close_connection,
                               mock_open_connection, mock_init):
        mock_is_live_vol.return_value = False
        scvol = {'instandId': '12345.1'}
        mock_find_volume.return_value = scvol
        mock_unmap_all.return_value = False
        volume = {'id': fake.VOLUME_ID}
        res = self.driver.force_detach(volume)
        mock_unmap_all.assert_called_once_with(scvol)
        self.assertFalse(res)
        mock_unmap_all.assert_called_once_with(scvol)

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume')
    @mock.patch.object(storagecenter_api.SCApi,
                       'unmap_all')
    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       '_is_live_vol')
    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
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
        self.assertTrue(res)
        self.assertEqual(1, mock_terminate_secondary.call_count)
        mock_unmap_all.assert_called_once_with(scvol)

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume')
    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       '_is_live_vol')
    def test_force_detach_vol_not_found(self,
                                        mock_is_live_vol, mock_find_volume,
                                        mock_close_connection,
                                        mock_open_connection, mock_init):
        mock_is_live_vol.return_value = False
        mock_find_volume.return_value = None
        volume = {'id': fake.VOLUME_ID}
        res = self.driver.force_detach(volume)
        self.assertFalse(res)

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_server',
                       return_value=SCSERVER)
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(storagecenter_api.SCApi,
                       'unmap_volume',
                       return_value=True)
    def test_terminate_connection(self,
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
        self.assertIsNone(res, 'None expected')

    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       'force_detach')
    def test_terminate_connection_no_connector(self, mock_force_detach,
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
    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       '_is_live_vol')
    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       'terminate_secondary')
    @mock.patch.object(storagecenter_api.SCApi,
                       'get_live_volume')
    def test_terminate_connection_live_volume(self,
                                              mock_get_live_vol,
                                              mock_terminate_secondary,
                                              mock_is_live_vol,
                                              mock_unmap_volume,
                                              mock_find_volume,
                                              mock_find_server,
                                              mock_close_connection,
                                              mock_open_connection,
                                              mock_init):
        volume = {'id': fake.VOLUME_ID}
        sclivevol = {'instanceId': '101.101',
                     'secondaryVolume': {'instanceId': '102.101',
                                         'instanceName': fake.VOLUME_ID},
                     'secondaryScSerialNumber': 102,
                     'secondaryRole': 'Secondary'}
        mock_is_live_vol.return_value = True
        mock_get_live_vol.return_value = sclivevol
        connector = self.connector
        res = self.driver.terminate_connection(volume, connector)
        mock_unmap_volume.assert_called_once_with(self.VOLUME, self.SCSERVER)
        self.assertIsNone(res, 'None expected')
        self.assertTrue(mock_terminate_secondary.called)

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(storagecenter_api.SCApi,
                       'unmap_all',
                       return_value=True)
    def test_terminate_connection_no_server(self,
                                            mock_unmap_all,
                                            mock_find_volume,
                                            mock_close_connection,
                                            mock_open_connection,
                                            mock_init):
        volume = {'id': fake.VOLUME_ID, 'provider_id': '101.101'}
        connector = {'initiator': ''}
        res = self.driver.terminate_connection(volume, connector)
        mock_find_volume.assert_called_once_with(fake.VOLUME_ID, '101.101',
                                                 False)
        mock_unmap_all.assert_called_once_with(self.VOLUME)
        self.assertIsNone(res)

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_server',
                       return_value=SCSERVER)
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume',
                       return_value=None)
    @mock.patch.object(storagecenter_api.SCApi,
                       'unmap_volume',
                       return_value=True)
    def test_terminate_connection_no_volume(self,
                                            mock_unmap_volume,
                                            mock_find_volume,
                                            mock_find_server,
                                            mock_close_connection,
                                            mock_open_connection,
                                            mock_init):
        volume = {'id': fake.VOLUME_ID}
        connector = {'initiator': 'fake'}
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
                       return_value=False)
    def test_terminate_connection_failure(self,
                                          mock_unmap_volume,
                                          mock_find_volume,
                                          mock_find_server,
                                          mock_close_connection,
                                          mock_open_connection,
                                          mock_init):
        volume = {'id': fake.VOLUME_ID}
        connector = {'initiator': 'fake'}
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
    def test_terminate_connection_multiattached_host(self,
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
    def test_terminate_connection_multiattached_diffhost(self,
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

    def _simple_volume(self, **kwargs):
        updates = {'display_name': fake.VOLUME_NAME,
                   'id': fake.VOLUME_ID,
                   'provider_id': self.VOLUME[u'instanceId']}
        updates.update(kwargs)

        return fake_volume.fake_volume_obj(self._context, **updates)

    def _simple_snapshot(self, **kwargs):
        updates = {'id': fake.SNAPSHOT_ID,
                   'display_name': fake.SNAPSHOT_NAME,
                   'status': 'available',
                   'provider_location': None,
                   'volume_size': 1}

        updates.update(kwargs)
        snapshot = fake_snapshot.fake_snapshot_obj(self._context, **updates)
        volume = self._simple_volume()
        snapshot.volume = volume

        return snapshot

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(storagecenter_api.SCApi,
                       'create_replay',
                       return_value='fake')
    def test_create_snapshot(self,
                             mock_create_replay,
                             mock_find_volume,
                             mock_close_connection,
                             mock_open_connection,
                             mock_init):
        provider_id = self.VOLUME[u'instanceId']
        snapshot = self._simple_snapshot()
        expected = {'status': 'available',
                    'provider_id': provider_id}
        ret = self.driver.create_snapshot(snapshot)
        self.assertEqual(expected, ret)

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume',
                       return_value=None)
    @mock.patch.object(storagecenter_api.SCApi,
                       'create_replay',
                       return_value=None)
    def test_create_snapshot_no_volume(self,
                                       mock_create_replay,
                                       mock_find_volume,
                                       mock_close_connection,
                                       mock_open_connection,
                                       mock_init):
        snapshot = self._simple_snapshot()
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_snapshot,
                          snapshot)

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(storagecenter_api.SCApi,
                       'create_replay',
                       return_value=None)
    def test_create_snapshot_failure(self,
                                     mock_create_replay,
                                     mock_find_volume,
                                     mock_close_connection,
                                     mock_open_connection,
                                     mock_init):
        snapshot = self._simple_snapshot()
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_snapshot,
                          snapshot)

    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       '_create_replications')
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_replay_profile')
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_replay',
                       return_value='fake')
    @mock.patch.object(storagecenter_api.SCApi,
                       'create_view_volume',
                       return_value=VOLUME)
    def test_create_volume_from_snapshot(self,
                                         mock_create_view_volume,
                                         mock_find_replay,
                                         mock_find_volume,
                                         mock_find_replay_profile,
                                         mock_create_replications,
                                         mock_close_connection,
                                         mock_open_connection,
                                         mock_init):
        model_update = {'something': 'something'}
        mock_create_replications.return_value = model_update
        volume = {'id': fake.VOLUME_ID, 'size': 1}
        snapshot = {'id': fake.SNAPSHOT_ID, 'volume_id': fake.VOLUME_ID,
                    'volume_size': 1}
        res = self.driver.create_volume_from_snapshot(volume, snapshot)
        mock_create_view_volume.assert_called_once_with(
            fake.VOLUME_ID, 'fake', None, None, None, None)
        self.assertTrue(mock_find_replay.called)
        self.assertTrue(mock_find_volume.called)
        self.assertFalse(mock_find_replay_profile.called)
        # This just makes sure that we created
        self.assertTrue(mock_create_replications.called)
        self.assertEqual(model_update, res)

    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       '_create_replications')
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_replay_profile')
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume')
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_replay')
    @mock.patch.object(storagecenter_api.SCApi,
                       'create_view_volume')
    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       '_get_volume_extra_specs')
    def test_create_volume_from_snapshot_with_profiles(
            self, mock_get_volume_extra_specs, mock_create_view_volume,
            mock_find_replay, mock_find_volume, mock_find_replay_profile,
            mock_create_replications, mock_close_connection,
            mock_open_connection, mock_init):
        mock_get_volume_extra_specs.return_value = {
            'storagetype:replayprofiles': 'replayprofiles',
            'storagetype:volumeqos': 'volumeqos',
            'storagetype:groupqos': 'groupqos',
            'storagetype:datareductionprofile': 'drprofile'}

        mock_create_view_volume.return_value = self.VOLUME
        mock_find_replay.return_value = 'fake'
        mock_find_volume.return_value = self.VOLUME
        model_update = {'something': 'something'}
        mock_create_replications.return_value = model_update
        volume = {'id': fake.VOLUME_ID, 'size': 1}
        snapshot = {'id': fake.SNAPSHOT_ID, 'volume_id': fake.VOLUME_ID,
                    'volume_size': 1}
        res = self.driver.create_volume_from_snapshot(volume, snapshot)
        mock_create_view_volume.assert_called_once_with(
            fake.VOLUME_ID, 'fake', 'replayprofiles', 'volumeqos', 'groupqos',
            'drprofile')
        self.assertTrue(mock_find_replay.called)
        self.assertTrue(mock_find_volume.called)
        self.assertFalse(mock_find_replay_profile.called)
        # This just makes sure that we created
        self.assertTrue(mock_create_replications.called)
        self.assertEqual(model_update, res)

    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       '_create_replications')
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_replay_profile')
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_replay',
                       return_value='fake')
    @mock.patch.object(storagecenter_api.SCApi,
                       'create_view_volume',
                       return_value=VOLUME)
    @mock.patch.object(storagecenter_api.SCApi,
                       'expand_volume',
                       return_value=VOLUME)
    def test_create_volume_from_snapshot_expand(self,
                                                mock_expand_volume,
                                                mock_create_view_volume,
                                                mock_find_replay,
                                                mock_find_volume,
                                                mock_find_replay_profile,
                                                mock_create_replications,
                                                mock_close_connection,
                                                mock_open_connection,
                                                mock_init):
        model_update = {'something': 'something'}
        mock_create_replications.return_value = model_update
        volume = {'id': fake.VOLUME_ID, 'size': 2}
        snapshot = {'id': fake.SNAPSHOT_ID, 'volume_id': fake.VOLUME_ID,
                    'volume_size': 1}
        res = self.driver.create_volume_from_snapshot(volume, snapshot)
        mock_create_view_volume.assert_called_once_with(
            fake.VOLUME_ID, 'fake', None, None, None, None)
        self.assertTrue(mock_find_replay.called)
        self.assertTrue(mock_find_volume.called)
        self.assertFalse(mock_find_replay_profile.called)
        # This just makes sure that we created
        self.assertTrue(mock_create_replications.called)
        mock_expand_volume.assert_called_once_with(self.VOLUME, 2)
        self.assertEqual(model_update, res)

    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       '_create_replications')
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_replay_profile',
                       return_value='fake')
    @mock.patch.object(storagecenter_api.SCApi,
                       'update_cg_volumes')
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_replay',
                       return_value='fake')
    @mock.patch.object(storagecenter_api.SCApi,
                       'create_view_volume',
                       return_value=VOLUME)
    def test_create_volume_from_snapshot_cg(self,
                                            mock_create_view_volume,
                                            mock_find_replay,
                                            mock_find_volume,
                                            mock_update_cg_volumes,
                                            mock_find_replay_profile,
                                            mock_create_replications,
                                            mock_close_connection,
                                            mock_open_connection,
                                            mock_init):
        model_update = {'something': 'something'}
        mock_create_replications.return_value = model_update
        volume = {'id': fake.VOLUME_ID,
                  'group_id': fake.GROUP_ID, 'size': 1}
        snapshot = {'id': fake.SNAPSHOT_ID, 'volume_id': fake.VOLUME_ID,
                    'volume_size': 1}
        res = self.driver.create_volume_from_snapshot(volume, snapshot)
        mock_create_view_volume.assert_called_once_with(
            fake.VOLUME_ID, 'fake', None, None, None, None)
        self.assertTrue(mock_find_replay.called)
        self.assertTrue(mock_find_volume.called)
        self.assertTrue(mock_find_replay_profile.called)
        self.assertTrue(mock_update_cg_volumes.called)
        # This just makes sure that we created
        self.assertTrue(mock_create_replications.called)
        self.assertEqual(model_update, res)

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_replay',
                       return_value='fake')
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_replay_profile')
    @mock.patch.object(storagecenter_api.SCApi,
                       'create_view_volume',
                       return_value=None)
    @mock.patch.object(storagecenter_api.SCApi,
                       'delete_volume')
    def test_create_volume_from_snapshot_failed(self,
                                                mock_delete_volume,
                                                mock_create_view_volume,
                                                mock_find_replay_profile,
                                                mock_find_replay,
                                                mock_find_volume,
                                                mock_close_connection,
                                                mock_open_connection,
                                                mock_init):
        volume = {'id': fake.VOLUME_ID}
        snapshot = {'id': fake.SNAPSHOT_ID, 'volume_id': fake.VOLUME_ID}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume_from_snapshot,
                          volume, snapshot)
        self.assertTrue(mock_find_replay.called)
        self.assertTrue(mock_find_volume.called)
        self.assertFalse(mock_find_replay_profile.called)
        self.assertTrue(mock_delete_volume.called)

    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       '_create_replications')
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_replay',
                       return_value='fake')
    @mock.patch.object(storagecenter_api.SCApi,
                       'create_view_volume',
                       return_value=VOLUME)
    @mock.patch.object(storagecenter_api.SCApi,
                       'delete_volume')
    def test_create_volume_from_snapshot_failed_replication(
            self,
            mock_delete_volume,
            mock_create_view_volume,
            mock_find_replay,
            mock_find_volume,
            mock_create_replications,
            mock_close_connection,
            mock_open_connection,
            mock_init):
        mock_create_replications.side_effect = (
            exception.VolumeBackendAPIException(data='abc'))
        volume = {'id': fake.VOLUME_ID, 'size': 1}
        snapshot = {'id': fake.SNAPSHOT_ID, 'volume_id': fake.VOLUME_ID,
                    'volume_size': 1}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume_from_snapshot,
                          volume, snapshot)
        self.assertTrue(mock_delete_volume.called)

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_replay',
                       return_value=None)
    @mock.patch.object(storagecenter_api.SCApi,
                       'create_view_volume',
                       return_value=VOLUME)
    def test_create_volume_from_snapshot_no_replay(self,
                                                   mock_create_view_volume,
                                                   mock_find_replay,
                                                   mock_find_volume,
                                                   mock_close_connection,
                                                   mock_open_connection,
                                                   mock_init):
        volume = {'id': fake.VOLUME_ID}
        snapshot = {'id': fake.SNAPSHOT_ID, 'volume_id': fake.VOLUME2_ID}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume_from_snapshot,
                          volume, snapshot)
        self.assertTrue(mock_find_volume.called)
        self.assertTrue(mock_find_replay.called)
        self.assertFalse(mock_create_view_volume.called)

    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       '_create_replications',
                       return_value={})
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(storagecenter_api.SCApi,
                       'create_cloned_volume',
                       return_value=VOLUME)
    def test_create_cloned_volume(self,
                                  mock_create_cloned_volume,
                                  mock_find_volume,
                                  mock_create_replications,
                                  mock_close_connection,
                                  mock_open_connection,
                                  mock_init):
        provider_id = self.VOLUME[u'instanceId']
        volume = {'id': fake.VOLUME_ID, 'size': 1}
        src_vref = {'id': fake.VOLUME2_ID, 'size': 1}
        ret = self.driver.create_cloned_volume(volume, src_vref)
        mock_create_cloned_volume.assert_called_once_with(
            fake.VOLUME_ID, self.VOLUME, None, None, None, None, None)
        self.assertTrue(mock_find_volume.called)
        self.assertEqual({'provider_id': provider_id}, ret)

    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       '_create_replications')
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume')
    @mock.patch.object(storagecenter_api.SCApi,
                       'create_cloned_volume')
    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       '_get_volume_extra_specs')
    def test_create_cloned_volume_with_profiles(
            self, mock_get_volume_extra_specs, mock_create_cloned_volume,
            mock_find_volume, mock_create_replications, mock_close_connection,
            mock_open_connection, mock_init):
        mock_get_volume_extra_specs.return_value = {
            'storagetype:storageprofile': 'storageprofile',
            'storagetype:replayprofiles': 'replayprofiles',
            'storagetype:volumeqos': 'volumeqos',
            'storagetype:groupqos': 'groupqos',
            'storagetype:datareductionprofile': 'drprofile'}
        mock_find_volume.return_value = self.VOLUME
        mock_create_cloned_volume.return_value = self.VOLUME
        mock_create_replications.return_value = {}
        provider_id = self.VOLUME[u'instanceId']
        volume = {'id': fake.VOLUME_ID, 'size': 1}
        src_vref = {'id': fake.VOLUME2_ID, 'size': 1}
        ret = self.driver.create_cloned_volume(volume, src_vref)
        mock_create_cloned_volume.assert_called_once_with(
            fake.VOLUME_ID, self.VOLUME, 'storageprofile', 'replayprofiles',
            'volumeqos', 'groupqos', 'drprofile')
        self.assertTrue(mock_find_volume.called)
        self.assertEqual({'provider_id': provider_id}, ret)

    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       '_create_replications',
                       return_value={})
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(storagecenter_api.SCApi,
                       'create_cloned_volume',
                       return_value=VOLUME)
    @mock.patch.object(storagecenter_api.SCApi,
                       'expand_volume',
                       return_value=VOLUME)
    def test_create_cloned_volume_expand(self,
                                         mock_expand_volume,
                                         mock_create_cloned_volume,
                                         mock_find_volume,
                                         mock_create_replications,
                                         mock_close_connection,
                                         mock_open_connection,
                                         mock_init):
        provider_id = self.VOLUME[u'instanceId']
        volume = {'id': fake.VOLUME_ID, 'size': 2}
        src_vref = {'id': fake.VOLUME2_ID, 'size': 1}
        ret = self.driver.create_cloned_volume(volume, src_vref)
        mock_create_cloned_volume.assert_called_once_with(
            fake.VOLUME_ID, self.VOLUME, None, None, None, None, None)
        self.assertTrue(mock_find_volume.called)
        self.assertEqual({'provider_id': provider_id}, ret)
        self.assertTrue(mock_expand_volume.called)

    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       '_create_replications',
                       return_value={})
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(storagecenter_api.SCApi,
                       'create_cloned_volume',
                       return_value=None)
    @mock.patch.object(storagecenter_api.SCApi,
                       'delete_volume')
    def test_create_cloned_volume_failed(self,
                                         mock_delete_volume,
                                         mock_create_cloned_volume,
                                         mock_find_volume,
                                         mock_create_replications,
                                         mock_close_connection,
                                         mock_open_connection,
                                         mock_init):
        volume = {'id': fake.VOLUME_ID}
        src_vref = {'id': fake.VOLUME2_ID}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_cloned_volume,
                          volume, src_vref)
        self.assertTrue(mock_delete_volume.called)

    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       '_create_replications',
                       return_value={})
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(storagecenter_api.SCApi,
                       'create_cloned_volume',
                       return_value=VOLUME)
    @mock.patch.object(storagecenter_api.SCApi,
                       'delete_volume')
    @mock.patch.object(storagecenter_api.SCApi,
                       'expand_volume')
    def test_create_cloned_volume_expand_failed(self,
                                                mock_expand_volume,
                                                mock_delete_volume,
                                                mock_create_cloned_volume,
                                                mock_find_volume,
                                                mock_create_replications,
                                                mock_close_connection,
                                                mock_open_connection,
                                                mock_init):
        volume = {'id': fake.VOLUME_ID, 'size': 2}
        src_vref = {'id': fake.VOLUME2_ID, 'size': 1}
        mock_create_replications.side_effect = (
            exception.VolumeBackendAPIException(data='abc'))
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_cloned_volume,
                          volume, src_vref)
        self.assertTrue(mock_delete_volume.called)

    @mock.patch.object(storagecenter_api.SCApi,
                       'delete_volume')
    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       '_create_replications')
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(storagecenter_api.SCApi,
                       'create_cloned_volume',
                       return_value=VOLUME)
    def test_create_cloned_volume_replication_fail(self,
                                                   mock_create_cloned_volume,
                                                   mock_find_volume,
                                                   mock_create_replications,
                                                   mock_delete_volume,
                                                   mock_close_connection,
                                                   mock_open_connection,
                                                   mock_init):
        mock_create_replications.side_effect = (
            exception.VolumeBackendAPIException(data='abc'))
        volume = {'id': fake.VOLUME_ID, 'size': 1}
        src_vref = {'id': fake.VOLUME2_ID, 'size': 1}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_cloned_volume,
                          volume, src_vref)
        self.assertTrue(mock_delete_volume.called)

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_replay_profile',
                       return_value='fake')
    @mock.patch.object(storagecenter_api.SCApi,
                       'update_cg_volumes')
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(storagecenter_api.SCApi,
                       'create_cloned_volume',
                       return_value=VOLUME)
    def test_create_cloned_volume_consistency_group(self,
                                                    mock_create_cloned_volume,
                                                    mock_find_volume,
                                                    mock_update_cg_volumes,
                                                    mock_find_replay_profile,
                                                    mock_close_connection,
                                                    mock_open_connection,
                                                    mock_init):
        volume = {'id': fake.VOLUME_ID,
                  'group_id': fake.CONSISTENCY_GROUP_ID,
                  'size': 1}
        src_vref = {'id': fake.VOLUME2_ID, 'size': 1}
        self.driver.create_cloned_volume(volume, src_vref)
        mock_create_cloned_volume.assert_called_once_with(
            fake.VOLUME_ID, self.VOLUME, None, None, None, None, None)
        self.assertTrue(mock_find_volume.called)
        self.assertTrue(mock_find_replay_profile.called)
        self.assertTrue(mock_update_cg_volumes.called)

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume',
                       return_value=None)
    @mock.patch.object(storagecenter_api.SCApi,
                       'create_cloned_volume',
                       return_value=VOLUME)
    def test_create_cloned_volume_no_volume(self,
                                            mock_create_cloned_volume,
                                            mock_find_volume,
                                            mock_close_connection,
                                            mock_open_connection,
                                            mock_init):
        volume = {'id': fake.VOLUME_ID}
        src_vref = {'id': fake.VOLUME2_ID}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_cloned_volume,
                          volume, src_vref)
        self.assertTrue(mock_find_volume.called)
        self.assertFalse(mock_create_cloned_volume.called)

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(storagecenter_api.SCApi,
                       'delete_replay',
                       return_value=True)
    def test_delete_snapshot(self,
                             mock_delete_replay,
                             mock_find_volume,
                             mock_close_connection,
                             mock_open_connection,
                             mock_init):
        snapshot = {'volume_id': fake.VOLUME_ID,
                    'id': fake.SNAPSHOT_ID}
        self.driver.delete_snapshot(snapshot)
        mock_delete_replay.assert_called_once_with(
            self.VOLUME, fake.SNAPSHOT_ID)

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume',
                       return_value=None)
    @mock.patch.object(storagecenter_api.SCApi,
                       'delete_replay',
                       return_value=True)
    def test_delete_snapshot_no_volume(self,
                                       mock_delete_replay,
                                       mock_find_volume,
                                       mock_close_connection,
                                       mock_open_connection,
                                       mock_init):
        snapshot = {'volume_id': fake.VOLUME_ID,
                    'id': fake.SNAPSHOT_ID}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.delete_snapshot,
                          snapshot)

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume',
                       return_value=VOLUME)
    def test_ensure_export(self,
                           mock_find_volume,
                           mock_close_connection,
                           mock_open_connection,
                           mock_init):
        context = {}
        volume = {'id': fake.VOLUME_ID, 'provider_id': 'fake'}
        self.driver.ensure_export(context, volume)
        mock_find_volume.assert_called_once_with(fake.VOLUME_ID, 'fake', False)

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume',
                       return_value=None)
    def test_ensure_export_failed(self,
                                  mock_find_volume,
                                  mock_close_connection,
                                  mock_open_connection,
                                  mock_init):
        context = {}
        volume = {'id': fake.VOLUME_ID}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.ensure_export,
                          context, volume)
        mock_find_volume.assert_called_once_with(fake.VOLUME_ID, None, False)

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume',
                       return_value=None)
    def test_ensure_export_no_volume(self,
                                     mock_find_volume,
                                     mock_close_connection,
                                     mock_open_connection,
                                     mock_init):
        context = {}
        volume = {'id': fake.VOLUME_ID, 'provider_id': 'fake'}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.ensure_export, context, volume)
        mock_find_volume.assert_called_once_with(fake.VOLUME_ID, 'fake', False)

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(storagecenter_api.SCApi,
                       'expand_volume',
                       return_value=VOLUME)
    def test_extend_volume(self,
                           mock_expand_volume,
                           mock_find_volume,
                           mock_close_connection,
                           mock_open_connection,
                           mock_init):
        volume = {'id': fake.VOLUME_ID, 'size': 1}
        new_size = 2
        self.driver.extend_volume(volume, new_size)
        mock_find_volume.assert_called_once_with(fake.VOLUME_ID, None)
        mock_expand_volume.assert_called_once_with(self.VOLUME, new_size)

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume',
                       return_value=None)
    @mock.patch.object(storagecenter_api.SCApi,
                       'expand_volume',
                       return_value=None)
    def test_extend_volume_no_volume(self,
                                     mock_expand_volume,
                                     mock_find_volume,
                                     mock_close_connection,
                                     mock_open_connection,
                                     mock_init):
        volume = {'id': fake.VOLUME_ID, 'provider_id': 'fake', 'size': 1}
        new_size = 2
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.extend_volume,
                          volume, new_size)
        mock_find_volume.assert_called_once_with(fake.VOLUME_ID, 'fake')

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(storagecenter_api.SCApi,
                       'expand_volume',
                       return_value=None)
    def test_extend_volume_fail(self,
                                mock_expand_volume,
                                mock_find_volume,
                                mock_close_connection,
                                mock_open_connection,
                                mock_init):
        volume = {'id': fake.VOLUME_ID, 'size': 1}
        new_size = 2
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.extend_volume, volume, new_size)
        mock_find_volume.assert_called_once_with(fake.VOLUME_ID, None)
        mock_expand_volume.assert_called_once_with(self.VOLUME, new_size)

    @mock.patch.object(storagecenter_api.SCApi,
                       'get_storage_usage',
                       return_value={'availableSpace': 100, 'freeSpace': 50})
    def test_update_volume_stats_with_refresh(self,
                                              mock_get_storage_usage,
                                              mock_close_connection,
                                              mock_open_connection,
                                              mock_init):
        stats = self.driver.get_volume_stats(True)
        self.assertEqual('iSCSI', stats['storage_protocol'])
        self.assertTrue(mock_get_storage_usage.called)

    @mock.patch.object(storagecenter_api.SCApi,
                       'get_storage_usage',
                       return_value={'availableSpace': 100, 'freeSpace': 50})
    def test_update_volume_stats_with_refresh_and_repl(
            self,
            mock_get_storage_usage,
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

    @mock.patch.object(storagecenter_api.SCApi,
                       'get_storage_usage',
                       return_value={'availableSpace': 100, 'freeSpace': 50})
    def test_get_volume_stats_no_refresh(self,
                                         mock_get_storage_usage,
                                         mock_close_connection,
                                         mock_open_connection,
                                         mock_init):
        stats = self.driver.get_volume_stats(False)
        self.assertEqual('iSCSI', stats['storage_protocol'])
        self.assertFalse(mock_get_storage_usage.called)

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(storagecenter_api.SCApi,
                       'rename_volume',
                       return_value=True)
    def test_update_migrated_volume(self,
                                    mock_rename_volume,
                                    mock_find_volume,
                                    mock_close_connection,
                                    mock_open_connection,
                                    mock_init):
        volume = {'id': fake.VOLUME_ID}
        backend_volume = {'id': fake.VOLUME2_ID}
        model_update = {'_name_id': None,
                        'provider_id': self.VOLUME['instanceId']}
        rt = self.driver.update_migrated_volume(None, volume, backend_volume,
                                                'available')
        mock_rename_volume.assert_called_once_with(self.VOLUME, fake.VOLUME_ID)
        self.assertEqual(model_update, rt)

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(storagecenter_api.SCApi,
                       'rename_volume',
                       return_value=False)
    def test_update_migrated_volume_rename_fail(self,
                                                mock_rename_volume,
                                                mock_find_volume,
                                                mock_close_connection,
                                                mock_open_connection,
                                                mock_init):
        volume = {'id': fake.VOLUME_ID}
        backend_volume = {'id': fake.VOLUME2_ID,
                          '_name_id': fake.VOLUME2_NAME_ID}
        rt = self.driver.update_migrated_volume(None, volume, backend_volume,
                                                'available')
        mock_rename_volume.assert_called_once_with(self.VOLUME, fake.VOLUME_ID)
        self.assertEqual({'_name_id': fake.VOLUME2_NAME_ID}, rt)

    def test_update_migrated_volume_no_volume_id(self,
                                                 mock_close_connection,
                                                 mock_open_connection,
                                                 mock_init):
        volume = {'id': None}
        backend_volume = {'id': fake.VOLUME2_ID,
                          '_name_id': fake.VOLUME2_NAME_ID}
        rt = self.driver.update_migrated_volume(None, volume, backend_volume,
                                                'available')
        self.assertEqual({'_name_id': fake.VOLUME2_NAME_ID}, rt)

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume',
                       return_value=None)
    def test_update_migrated_volume_no_backend_id(self,
                                                  mock_find_volume,
                                                  mock_close_connection,
                                                  mock_open_connection,
                                                  mock_init):
        volume = {'id': fake.VOLUME_ID}
        backend_volume = {'id': None, '_name_id': None}
        rt = self.driver.update_migrated_volume(None, volume, backend_volume,
                                                'available')
        mock_find_volume.assert_called_once_with(None, None)
        self.assertEqual({'_name_id': None}, rt)

    @mock.patch.object(storagecenter_api.SCApi,
                       'create_replay_profile',
                       return_value=SCRPLAYPROFILE)
    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type',
                return_value=True)
    def test_create_group(self,
                          mock_is_cg,
                          mock_create_replay_profile,
                          mock_close_connection,
                          mock_open_connection,
                          mock_init):
        context = {}
        group = {'id': fake.GROUP_ID}
        model_update = self.driver.create_group(context, group)
        mock_create_replay_profile.assert_called_once_with(fake.GROUP_ID)
        self.assertEqual({'status': 'available'}, model_update)

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type',
                return_value=False)
    def test_create_group_not_a_cg(self,
                                   mock_is_cg,
                                   mock_close_connection,
                                   mock_open_connection,
                                   mock_init):
        context = {}
        group = {'id': fake.GROUP_ID}
        self.assertRaises(NotImplementedError, self.driver.create_group,
                          context, group)

    @mock.patch.object(storagecenter_api.SCApi,
                       'create_replay_profile',
                       return_value=None)
    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type',
                return_value=True)
    def test_create_group_fail(self,
                               mock_is_cg,
                               mock_create_replay_profile,
                               mock_close_connection,
                               mock_open_connection,
                               mock_init):
        context = {}
        group = {'id': fake.GROUP_ID}
        model_update = self.driver.create_group(context, group)
        mock_create_replay_profile.assert_called_once_with(fake.GROUP_ID)
        self.assertEqual({'status': 'error'}, model_update)

    @mock.patch.object(storagecenter_api.SCApi,
                       'delete_replay_profile')
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_replay_profile',
                       return_value=SCRPLAYPROFILE)
    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       'delete_volume')
    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type',
                return_value=True)
    def test_delete_group(self,
                          mock_is_cg,
                          mock_delete_volume,
                          mock_find_replay_profile,
                          mock_delete_replay_profile,
                          mock_close_connection,
                          mock_open_connection,
                          mock_init):
        volume = {'id': fake.VOLUME_ID}
        expected_volumes = [{'id': fake.VOLUME_ID,
                             'status': 'deleted'}]
        context = {}
        group = {'id': fake.GROUP_ID,
                 'status': fields.ConsistencyGroupStatus.DELETED}
        model_update, volumes = self.driver.delete_group(
            context, group, [volume])
        mock_find_replay_profile.assert_called_once_with(fake.GROUP_ID)
        mock_delete_replay_profile.assert_called_once_with(self.SCRPLAYPROFILE)
        mock_delete_volume.assert_called_once_with(volume)
        self.assertEqual(group['status'], model_update['status'])
        self.assertEqual(expected_volumes, volumes)

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type',
                return_value=False)
    def test_delete_group_not_a_cg(
            self, mock_is_cg, mock_close_connection,
            mock_open_connection, mock_init):

        volume = {'id': fake.VOLUME_ID}
        context = {}
        group = {'id': fake.GROUP_ID,
                 'status': fields.ConsistencyGroupStatus.DELETED}
        self.assertRaises(NotImplementedError, self.driver.delete_group,
                          context, group, [volume])

    @mock.patch.object(storagecenter_api.SCApi,
                       'delete_replay_profile')
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_replay_profile',
                       return_value=None)
    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       'delete_volume')
    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type',
                return_value=True)
    def test_delete_group_not_found(self,
                                    mock_is_cg,
                                    mock_delete_volume,
                                    mock_find_replay_profile,
                                    mock_delete_replay_profile,
                                    mock_close_connection,
                                    mock_open_connection,
                                    mock_init):
        context = {}
        group = {'id': fake.GROUP_ID,
                 'status': fields.ConsistencyGroupStatus.DELETED}
        model_update, volumes = self.driver.delete_group(context, group, [])
        mock_find_replay_profile.assert_called_once_with(fake.GROUP_ID)
        self.assertFalse(mock_delete_replay_profile.called)
        self.assertFalse(mock_delete_volume.called)
        self.assertEqual(group['status'], model_update['status'])
        self.assertEqual([], volumes)

    @mock.patch.object(storagecenter_api.SCApi,
                       'update_cg_volumes',
                       return_value=True)
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_replay_profile',
                       return_value=SCRPLAYPROFILE)
    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type',
                return_value=True)
    def test_update_group(self,
                          mock_is_cg,
                          mock_find_replay_profile,
                          mock_update_cg_volumes,
                          mock_close_connection,
                          mock_open_connection,
                          mock_init):
        context = {}
        group = {'id': fake.GROUP_ID}
        add_volumes = [{'id': fake.VOLUME_ID}]
        remove_volumes = [{'id': fake.VOLUME2_ID}]
        rt1, rt2, rt3 = self.driver.update_group(context, group, add_volumes,
                                                 remove_volumes)
        mock_update_cg_volumes.assert_called_once_with(self.SCRPLAYPROFILE,
                                                       add_volumes,
                                                       remove_volumes)
        mock_find_replay_profile.assert_called_once_with(fake.GROUP_ID)
        self.assertIsNone(rt1)
        self.assertIsNone(rt2)
        self.assertIsNone(rt3)

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type',
                return_value=False)
    def test_update_group_not_a_cg(self,
                                   mock_is_cg,
                                   mock_close_connection,
                                   mock_open_connection,
                                   mock_init):
        context = {}
        group = {'id': fake.GROUP_ID}
        add_volumes = [{'id': fake.VOLUME_ID}]
        remove_volumes = [{'id': fake.VOLUME2_ID}]
        self.assertRaises(NotImplementedError, self.driver.update_group,
                          context, group, add_volumes, remove_volumes)

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_replay_profile',
                       return_value=None)
    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type',
                return_value=True)
    def test_update_group_not_found(self,
                                    mock_is_cg,
                                    mock_find_replay_profile,
                                    mock_close_connection,
                                    mock_open_connection,
                                    mock_init):
        context = {}
        group = {'id': fake.GROUP_ID}
        add_volumes = [{'id': fake.VOLUME_ID}]
        remove_volumes = [{'id': fake.VOLUME2_ID}]
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.update_group,
                          context,
                          group,
                          add_volumes,
                          remove_volumes)
        mock_find_replay_profile.assert_called_once_with(fake.GROUP_ID)

    @mock.patch.object(storagecenter_api.SCApi,
                       'update_cg_volumes',
                       return_value=False)
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_replay_profile',
                       return_value=SCRPLAYPROFILE)
    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type',
                return_value=True)
    def test_update_group_error(self,
                                mock_is_cg,
                                mock_find_replay_profile,
                                mock_update_cg_volumes,
                                mock_close_connection,
                                mock_open_connection,
                                mock_init):
        context = {}
        group = {'id': fake.GROUP_ID}
        add_volumes = [{'id': fake.VOLUME_ID}]
        remove_volumes = [{'id': fake.VOLUME2_ID}]
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.update_group,
                          context,
                          group,
                          add_volumes,
                          remove_volumes)
        mock_find_replay_profile.assert_called_once_with(fake.GROUP_ID)
        mock_update_cg_volumes.assert_called_once_with(self.SCRPLAYPROFILE,
                                                       add_volumes,
                                                       remove_volumes)

    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       'update_group')
    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       'create_group')
    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       'create_cloned_volume')
    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type',
                return_value=True)
    def test_create_group_from_src(
            self, mock_is_cg, mock_create_cloned_volume, mock_create_group,
            mock_update_group, mock_close_connection, mock_open_connection,
            mock_init):
        context = {}
        group = {'id': fake.GROUP2_ID}
        volumes = [{'id': fake.VOLUME3_ID}, {'id': fake.VOLUME4_ID}]
        source_group = {'id': fake.GROUP_ID}
        source_volumes = [{'id': fake.VOLUME_ID}, {'id': fake.VOLUME2_ID}]
        # create_cloned_volume returns the sc specific provider_id.
        mock_create_cloned_volume.side_effect = [{'provider_id': '12345.1'},
                                                 {'provider_id': '12345.2'}]
        mock_create_group.return_value = {'status': 'available'}
        model_update, volumes_model_update = self.driver.create_group_from_src(
            context, group, volumes, group_snapshot=None, snapshots=None,
            source_group=source_group, source_vols=source_volumes)
        expected = [{'id': fake.VOLUME3_ID, 'provider_id': '12345.1',
                     'status': 'available'},
                    {'id': fake.VOLUME4_ID, 'provider_id': '12345.2',
                     'status': 'available'}]
        self.assertEqual({'status': 'available'}, model_update)
        self.assertEqual(expected, volumes_model_update)

    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       'update_group')
    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       'create_group')
    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       'create_volume_from_snapshot')
    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type',
                return_value=True)
    def test_create_group_from_src_from_snapshot(
            self, mock_is_cg, mock_create_volume_from_snapshot,
            mock_create_group, mock_update_group, mock_close_connection,
            mock_open_connection,
            mock_init):
        context = {}
        group = {'id': fake.GROUP_ID}
        volumes = [{'id': fake.VOLUME_ID}, {'id': fake.VOLUME2_ID}]
        group_snapshot = {'id': fake.GROUP_SNAPSHOT_ID}
        source_snapshots = [{'id': fake.SNAPSHOT_ID},
                            {'id': fake.SNAPSHOT2_ID}]
        # create_volume_from_snapshot returns the sc specific provider_id.
        mock_create_volume_from_snapshot.side_effect = [
            {'provider_id': '12345.1'}, {'provider_id': '12345.2'}]
        mock_create_group.return_value = {'status': 'available'}
        model_update, volumes_model_update = self.driver.create_group_from_src(
            context, group, volumes,
            group_snapshot=group_snapshot, snapshots=source_snapshots,
            source_group=None, source_vols=None)
        expected = [{'id': fake.VOLUME_ID, 'provider_id': '12345.1',
                     'status': 'available'},
                    {'id': fake.VOLUME2_ID, 'provider_id': '12345.2',
                     'status': 'available'}]
        self.assertEqual({'status': 'available'}, model_update)
        self.assertEqual(expected, volumes_model_update)

    def test_create_group_from_src_bad_input(
            self, mock_close_connection, mock_open_connection, mock_init):
        context = {}
        group = {'id': fake.GROUP2_ID}
        volumes = [{'id': fake.VOLUME3_ID}, {'id': fake.VOLUME4_ID}]
        self.assertRaises(exception.InvalidInput,
                          self.driver.create_group_from_src,
                          context, group, volumes, None, None, None, None)

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type',
                return_value=False)
    def test_create_group_from_src_not_a_cg(
            self, mock_is_cg, mock_close_connection,
            mock_open_connection, mock_init):
        context = {}
        group = {'id': fake.GROUP2_ID}
        volumes = [{'id': fake.VOLUME3_ID}, {'id': fake.VOLUME4_ID}]
        source_group = {'id': fake.GROUP_ID}
        source_volumes = [{'id': fake.VOLUME_ID}, {'id': fake.VOLUME2_ID}]
        self.assertRaises(NotImplementedError,
                          self.driver.create_group_from_src,
                          context, group, volumes, None, None,
                          source_group, source_volumes)

    @mock.patch.object(storagecenter_api.SCApi,
                       'snap_cg_replay',
                       return_value={'instanceId': '100'})
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_replay_profile',
                       return_value=SCRPLAYPROFILE)
    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type',
                return_value=True)
    def test_create_group_snapshot(self,
                                   mock_is_cg,
                                   mock_find_replay_profile,
                                   mock_snap_cg_replay,
                                   mock_close_connection,
                                   mock_open_connection,
                                   mock_init):
        mock_snapshot = mock.MagicMock()
        mock_snapshot.id = fake.SNAPSHOT_ID
        expected_snapshots = [{'id': fake.SNAPSHOT_ID, 'status': 'available'}]

        context = {}
        cggrp = {'group_id': fake.GROUP_ID, 'id': fake.GROUP_SNAPSHOT_ID}
        model_update, snapshots = self.driver.create_group_snapshot(
            context, cggrp, [mock_snapshot])
        mock_find_replay_profile.assert_called_once_with(fake.GROUP_ID)
        mock_snap_cg_replay.assert_called_once_with(self.SCRPLAYPROFILE,
                                                    fake.GROUP_SNAPSHOT_ID,
                                                    0)
        self.assertEqual('available', model_update['status'])
        self.assertEqual(expected_snapshots, snapshots)

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_replay_profile',
                       return_value=None)
    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type',
                return_value=True)
    def test_create_group_snapshot_profile_not_found(self,
                                                     mock_is_cg,
                                                     mock_find_replay_profile,
                                                     mock_close_connection,
                                                     mock_open_connection,
                                                     mock_init):
        context = {}
        cggrp = {'group_id': fake.GROUP_ID, 'id': fake.GROUP_SNAPSHOT_ID}
        model_update, snapshot_updates = self.driver.create_group_snapshot(
            context, cggrp, [])
        self.assertEqual({'status': 'error'}, model_update)
        self.assertIsNone(snapshot_updates)

        mock_find_replay_profile.assert_called_once_with(fake.GROUP_ID)

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type',
                return_value=False)
    def test_create_group_snapshot_not_a_cg(
            self, mock_is_cg, mock_close_connection,
            mock_open_connection, mock_init):
        context = {}
        cggrp = {'group_id': fake.GROUP_ID, 'id': fake.GROUP_SNAPSHOT_ID}
        self.assertRaises(NotImplementedError,
                          self.driver.create_group_snapshot,
                          context, cggrp, [])

    @mock.patch.object(storagecenter_api.SCApi,
                       'snap_cg_replay',
                       return_value=None)
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_replay_profile',
                       return_value=SCRPLAYPROFILE)
    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type',
                return_value=True)
    def test_create_group_snapshot_fail(self,
                                        mock_is_cg,
                                        mock_find_replay_profile,
                                        mock_snap_cg_replay,
                                        mock_close_connection,
                                        mock_open_connection,
                                        mock_init):
        context = {}
        cggrp = {'group_id': fake.GROUP_ID, 'id': fake.GROUP_SNAPSHOT_ID}
        model_update, snapshot_updates = self.driver.create_group_snapshot(
            context, cggrp, [])
        mock_find_replay_profile.assert_called_once_with(fake.GROUP_ID)
        mock_snap_cg_replay.assert_called_once_with(self.SCRPLAYPROFILE,
                                                    fake.GROUP_SNAPSHOT_ID, 0)
        self.assertEqual({'status': 'error'}, model_update)
        self.assertIsNone(snapshot_updates)

    @mock.patch.object(storagecenter_api.SCApi,
                       'delete_cg_replay',
                       return_value=True)
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_replay_profile',
                       return_value=SCRPLAYPROFILE)
    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type',
                return_value=True)
    def test_delete_group_snapshot(self,
                                   mock_is_cg,
                                   mock_find_replay_profile,
                                   mock_delete_cg_replay,
                                   mock_close_connection,
                                   mock_open_connection,
                                   mock_init):
        mock_snapshot = {'id': fake.SNAPSHOT_ID, 'status': 'available'}
        context = {}
        cgsnap = {'group_id': fake.GROUP_ID,
                  'id': fake.GROUP_SNAPSHOT_ID, 'status': 'deleted'}
        model_update, snapshots = self.driver.delete_group_snapshot(
            context, cgsnap, [mock_snapshot])
        mock_find_replay_profile.assert_called_once_with(fake.GROUP_ID)
        mock_delete_cg_replay.assert_called_once_with(self.SCRPLAYPROFILE,
                                                      fake.GROUP_SNAPSHOT_ID)
        self.assertEqual({'status': cgsnap['status']}, model_update)
        self.assertEqual([{'id': fake.SNAPSHOT_ID, 'status': 'deleted'}],
                         snapshots)

    @mock.patch.object(storagecenter_api.SCApi,
                       'delete_cg_replay')
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_replay_profile',
                       return_value=None)
    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type',
                return_value=True)
    def test_delete_group_snapshot_profile_not_found(self,
                                                     mock_is_cg,
                                                     mock_find_replay_profile,
                                                     mock_delete_cg_replay,
                                                     mock_close_connection,
                                                     mock_open_connection,
                                                     mock_init):
        snapshot = {'id': fake.SNAPSHOT_ID, 'status': 'available'}
        context = {}
        cgsnap = {'group_id': fake.GROUP_ID,
                  'id': fake.GROUP_SNAPSHOT_ID, 'status': 'available'}
        model_update, snapshots = self.driver.delete_group_snapshot(
            context, cgsnap, [snapshot])
        mock_find_replay_profile.assert_called_once_with(fake.GROUP_ID)
        self.assertFalse(mock_delete_cg_replay.called)
        self.assertEqual({'status': 'error'}, model_update)
        self.assertIsNone(snapshots)

    @mock.patch.object(storagecenter_api.SCApi,
                       'delete_cg_replay',
                       return_value=False)
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_replay_profile',
                       return_value=SCRPLAYPROFILE)
    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type',
                return_value=True)
    def test_delete_group_snapshot_profile_failed_delete(
            self, mock_is_cg, mock_find_replay_profile, mock_delete_cg_replay,
            mock_close_connection, mock_open_connection, mock_init):
        context = {}
        cgsnap = {'group_id': fake.GROUP_ID,
                  'id': fake.GROUP_SNAPSHOT_ID, 'status': 'available'}
        model_update, snapshot_updates = self.driver.delete_group_snapshot(
            context, cgsnap, [])
        self.assertEqual({'status': 'error_deleting'}, model_update)
        mock_find_replay_profile.assert_called_once_with(fake.GROUP_ID)
        mock_delete_cg_replay.assert_called_once_with(self.SCRPLAYPROFILE,
                                                      fake.GROUP_SNAPSHOT_ID)

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type',
                return_value=False)
    def test_delete_group_snapshot_not_a_cg(
            self, mock_is_cg, mock_close_connection,
            mock_open_connection, mock_init):
        context = {}
        cgsnap = {'group_id': fake.GROUP_ID,
                  'id': fake.GROUP_SNAPSHOT_ID, 'status': 'available'}
        self.assertRaises(NotImplementedError,
                          self.driver.delete_group_snapshot,
                          context, cgsnap, [])

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume',
                       return_value={'id': 'guid'})
    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       '_create_replications',
                       return_value=None)
    @mock.patch.object(storagecenter_api.SCApi,
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
        volume = {'id': fake.VOLUME_ID}
        existing_ref = {'source-name': 'imavolumename'}
        self.driver.manage_existing(volume, existing_ref)
        mock_manage_existing.assert_called_once_with(fake.VOLUME_ID,
                                                     existing_ref)

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume',
                       return_value={'id': 'guid'})
    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       '_create_replications',
                       return_value=None)
    @mock.patch.object(storagecenter_api.SCApi,
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
        volume = {'id': fake.VOLUME_ID}
        existing_ref = {'source-id': 'imadeviceid'}
        self.driver.manage_existing(volume, existing_ref)
        mock_manage_existing.assert_called_once_with(fake.VOLUME_ID,
                                                     existing_ref)

    def test_manage_existing_bad_ref(self,
                                     mock_close_connection,
                                     mock_open_connection,
                                     mock_init):
        volume = {'id': fake.VOLUME_ID}
        existing_ref = {'banana-name': 'imavolumename'}
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing,
                          volume, existing_ref)

    @mock.patch.object(storagecenter_api.SCApi,
                       'get_unmanaged_volume_size',
                       return_value=4)
    def test_manage_existing_get_size(self,
                                      mock_get_unmanaged_volume_size,
                                      mock_close_connection,
                                      mock_open_connection,
                                      mock_init):
        # Almost nothing to test here.  Just that we call our function.
        volume = {'id': fake.VOLUME_ID}
        existing_ref = {'source-name': 'imavolumename'}
        res = self.driver.manage_existing_get_size(volume, existing_ref)
        mock_get_unmanaged_volume_size.assert_called_once_with(existing_ref)
        # The above is 4GB and change.
        self.assertEqual(4, res)

    @mock.patch.object(storagecenter_api.SCApi,
                       'get_unmanaged_volume_size',
                       return_value=4)
    def test_manage_existing_get_size_id(self,
                                         mock_get_unmanaged_volume_size,
                                         mock_close_connection,
                                         mock_open_connection,
                                         mock_init):
        # Almost nothing to test here.  Just that we call our function.
        volume = {'id': fake.VOLUME_ID}
        existing_ref = {'source-id': 'imadeviceid'}
        res = self.driver.manage_existing_get_size(volume, existing_ref)
        mock_get_unmanaged_volume_size.assert_called_once_with(existing_ref)
        # The above is 4GB and change.
        self.assertEqual(4, res)

    def test_manage_existing_get_size_bad_ref(self,
                                              mock_close_connection,
                                              mock_open_connection,
                                              mock_init):
        volume = {'id': fake.VOLUME_ID}
        existing_ref = {'banana-name': 'imavolumename'}
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_get_size,
                          volume, existing_ref)

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(storagecenter_api.SCApi,
                       'update_storage_profile')
    @mock.patch.object(storagecenter_api.SCApi,
                       'update_replay_profiles')
    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       '_create_replications')
    @mock.patch.object(storagecenter_api.SCApi,
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
            None, {'id': fake.VOLUME_ID}, None, {'extra_specs': None}, None)
        self.assertTrue(res)
        self.assertFalse(mock_update_replicate_active_replay.called)
        self.assertFalse(mock_create_replications.called)
        self.assertFalse(mock_update_replay_profile.called)
        self.assertFalse(mock_update_storage_profile.called)

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(storagecenter_api.SCApi,
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
            None, {'id': fake.VOLUME_ID}, None,
            {'extra_specs': {'storagetype:replayprofiles': ['A', 'B']}},
            None)
        mock_update_replay_profiles.assert_called_once_with(self.VOLUME, 'B')
        self.assertTrue(res)
        # Run fails.  Make sure this returns False.
        res = self.driver.retype(
            None, {'id': fake.VOLUME_ID}, None,
            {'extra_specs': {'storagetype:replayprofiles': ['B', 'A']}},
            None)
        self.assertFalse(res)

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       '_create_replications',
                       return_value={'replication_status': 'enabled',
                                     'replication_driver_data': '54321'})
    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       '_delete_replications')
    def test_retype_create_replications(self,
                                        mock_delete_replications,
                                        mock_create_replications,
                                        mock_find_volume,
                                        mock_close_connection,
                                        mock_open_connection,
                                        mock_init):

        res = self.driver.retype(
            None, {'id': fake.VOLUME_ID},
            {'extra_specs': {'replication_enabled': [None, '<is> True']}},
            {'extra_specs': {'replication_enabled': [None, '<is> True']}},
            None)
        self.assertTrue(mock_create_replications.called)
        self.assertFalse(mock_delete_replications.called)
        self.assertEqual((True, {'replication_status': 'enabled',
                                 'replication_driver_data': '54321'}), res)
        res = self.driver.retype(
            None, {'id': fake.VOLUME_ID}, None,
            {'extra_specs': {'replication_enabled': ['<is> True', None]}},
            None)
        self.assertTrue(mock_delete_replications.called)
        self.assertEqual((True, {'replication_status': 'disabled',
                                 'replication_driver_data': ''}), res)

    @mock.patch.object(storagecenter_api.SCApi,
                       'update_replicate_active_replay')
    @mock.patch.object(storagecenter_api.SCApi,
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
            None, {'id': fake.VOLUME_ID}, None,
            {'extra_specs': {'replication:activereplay': ['', '<is> True']}},
            None)
        self.assertTrue(res)
        res = self.driver.retype(
            None, {'id': fake.VOLUME_ID}, None,
            {'extra_specs': {'replication:activereplay': ['<is> True', '']}},
            None)
        self.assertTrue(res)
        res = self.driver.retype(
            None, {'id': fake.VOLUME_ID}, None,
            {'extra_specs': {'replication:activereplay': ['', '']}},
            None)
        self.assertTrue(res)
        res = self.driver.retype(
            None, {'id': fake.VOLUME_ID}, None,
            {'extra_specs': {'replication:activereplay': ['', '<is> True']}},
            None)
        self.assertFalse(res)

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume',
                       return_value=VOLUME)
    def test_retype_same(self,
                         mock_find_volume,
                         mock_close_connection,
                         mock_open_connection,
                         mock_init):
        res = self.driver.retype(
            None, {'id': fake.VOLUME_ID}, None,
            {'extra_specs': {'storagetype:storageprofile': ['A', 'A']}},
            None)
        self.assertTrue(res)

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume',
                       return_value=VOLUME)
    @mock.patch.object(storagecenter_api.SCApi,
                       'unmanage')
    def test_unmanage(self,
                      mock_unmanage,
                      mock_find_volume,
                      mock_close_connection,
                      mock_open_connection,
                      mock_init):
        volume = {'id': fake.VOLUME_ID, 'provider_id': '11111.1'}
        self.driver.unmanage(volume)
        mock_find_volume.assert_called_once_with(fake.VOLUME_ID, '11111.1')
        mock_unmanage.assert_called_once_with(self.VOLUME)

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume',
                       return_value=None)
    @mock.patch.object(storagecenter_api.SCApi,
                       'unmanage')
    def test_unmanage_volume_not_found(self,
                                       mock_unmanage,
                                       mock_find_volume,
                                       mock_close_connection,
                                       mock_open_connection,
                                       mock_init):
        volume = {'id': fake.VOLUME_ID, 'provider_id': '11111.1'}
        self.driver.unmanage(volume)
        mock_find_volume.assert_called_once_with(fake.VOLUME_ID, '11111.1')
        self.assertFalse(mock_unmanage.called)

    @mock.patch.object(storagecenter_api.SCApi,
                       'update_storage_profile')
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume',
                       return_value=VOLUME)
    def test_retype(self,
                    mock_find_volume,
                    mock_update_storage_profile,
                    mock_close_connection,
                    mock_open_connection,
                    mock_init):
        res = self.driver.retype(
            None, {'id': fake.VOLUME_ID}, None,
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

    @mock.patch.object(storagecenter_api.SCApi,
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

    def test__failover_live_volume(self,
                                   mock_close_connection,
                                   mock_open_connection,
                                   mock_init):
        mock_api = mock.MagicMock()
        sclivevol = {'instanceId': '101.100',
                     'primaryVolume': {'instanceId': '101.101',
                                       'instanceName': fake.VOLUME2_ID},
                     'secondaryVolume': {'instanceId': '102.101',
                                         'instanceName': fake.VOLUME_ID},
                     'secondaryScSerialNumber': 102,
                     'secondaryRole': 'Secondary'}
        postfail = {'instanceId': '101.100',
                    'primaryVolume': {'instanceId': '102.101',
                                      'instanceName': fake.VOLUME_ID},
                    'secondaryVolume': {'instanceId': '101.101',
                                        'instanceName': fake.VOLUME2_ID},
                    'secondaryScSerialNumber': 102,
                    'secondaryRole': 'Secondary'}
        mock_api.get_live_volume = mock.MagicMock()
        mock_api.get_live_volume.side_effect = [sclivevol, postfail,
                                                sclivevol, sclivevol]
        # Good run.
        mock_api.is_swapped = mock.MagicMock(return_value=False)
        mock_api.swap_roles_live_volume = mock.MagicMock(return_value=True)
        model_update = {'provider_id': '102.101',
                        'replication_status': 'failed-over'}
        ret = self.driver._failover_live_volume(mock_api, fake.VOLUME_ID,
                                                '101.101')
        self.assertEqual(model_update, ret)
        # Swap fail
        mock_api.swap_roles_live_volume.return_value = False
        model_update = {'status': 'error'}
        ret = self.driver._failover_live_volume(mock_api, fake.VOLUME_ID,
                                                '101.101')
        self.assertEqual(model_update, ret)
        # Can't find live volume.
        mock_api.get_live_volume.return_value = None
        ret = self.driver._failover_live_volume(mock_api, fake.VOLUME_ID,
                                                '101.101')
        self.assertEqual(model_update, ret)

    def test__failover_replication(self,
                                   mock_close_connection,
                                   mock_open_connection,
                                   mock_init):
        rvol = {'instanceId': '102.101'}
        mock_api = mock.MagicMock()
        mock_api.break_replication = mock.MagicMock(return_value=rvol)
        # Good run.
        model_update = {'replication_status': 'failed-over',
                        'provider_id': '102.101'}
        ret = self.driver._failover_replication(mock_api, fake.VOLUME_ID,
                                                '101.100', 102)
        self.assertEqual(model_update, ret)
        # break fail
        mock_api.break_replication.return_value = None
        model_update = {'status': 'error'}
        ret = self.driver._failover_replication(mock_api, fake.VOLUME_ID,
                                                '101.100', 102)
        self.assertEqual(model_update, ret)

    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       '_failover_replication')
    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       '_parse_secondary')
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume')
    @mock.patch.object(storagecenter_api.SCApi,
                       'remove_mappings')
    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       'failback_volumes')
    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       '_get_replication_specs')
    def test_failover_host(self,
                           mock_get_replication_specs,
                           mock_failback_volumes,
                           mock_remove_mappings,
                           mock_find_volume,
                           mock_parse_secondary,
                           mock_failover_replication,
                           mock_close_connection,
                           mock_open_connection,
                           mock_init):
        mock_get_replication_specs.return_value = {'enabled': False,
                                                   'live': False}
        self.driver.replication_enabled = False
        self.driver.failed_over = False
        volumes = [{'id': fake.VOLUME_ID,
                    'replication_driver_data': '12345',
                    'provider_id': '1.1'},
                   {'id': fake.VOLUME2_ID,
                    'replication_driver_data': '12345',
                    'provider_id': '1.2'}]
        # No run. Not doing repl.  Should raise.
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.failover_host,
                          {},
                          volumes,
                          '12345')
        # Good run
        self.driver.replication_enabled = True
        mock_get_replication_specs.return_value = {'enabled': True,
                                                   'live': False}
        mock_parse_secondary.return_value = 12345
        expected_destssn = 12345
        mock_failover_replication.side_effect = [
            {'provider_id': '2.1', 'replication_status': 'failed-over'},  # 1
            {'provider_id': '2.2', 'replication_status': 'failed-over'},
            {'provider_id': '2.1', 'replication_status': 'failed-over'},  # 2
            {'provider_id': '2.1', 'replication_status': 'failed-over'}]  # 3
        expected_volume_update = [{'volume_id': fake.VOLUME_ID, 'updates':
                                   {'replication_status': 'failed-over',
                                    'provider_id': '2.1'}},
                                  {'volume_id': fake.VOLUME2_ID, 'updates':
                                   {'replication_status': 'failed-over',
                                    'provider_id': '2.2'}}]
        destssn, volume_update, __ = self.driver.failover_host(
            {}, volumes, '12345', [])
        self.assertEqual(expected_destssn, destssn)
        self.assertEqual(expected_volume_update, volume_update)
        # Good run. Not all volumes replicated.
        volumes = [{'id': fake.VOLUME_ID, 'replication_driver_data': '12345'},
                   {'id': fake.VOLUME2_ID, 'replication_driver_data': ''}]
        expected_volume_update = [{'volume_id': fake.VOLUME_ID, 'updates':
                                   {'replication_status': 'failed-over',
                                    'provider_id': '2.1'}},
                                  {'volume_id': fake.VOLUME2_ID, 'updates':
                                   {'status': 'error'}}]
        self.driver.failed_over = False
        self.driver.active_backend_id = None
        destssn, volume_update, __ = self.driver.failover_host(
            {}, volumes, '12345', [])
        self.assertEqual(expected_destssn, destssn)
        self.assertEqual(expected_volume_update, volume_update)
        # Good run. Not all volumes replicated. No replication_driver_data.
        volumes = [{'id': fake.VOLUME_ID, 'replication_driver_data': '12345'},
                   {'id': fake.VOLUME2_ID}]
        expected_volume_update = [{'volume_id': fake.VOLUME_ID, 'updates':
                                   {'replication_status': 'failed-over',
                                    'provider_id': '2.1'}},
                                  {'volume_id': fake.VOLUME2_ID, 'updates':
                                   {'status': 'error'}}]
        self.driver.failed_over = False
        self.driver.active_backend_id = None
        destssn, volume_update, __ = self.driver.failover_host(
            {}, volumes, '12345', [])
        self.assertEqual(expected_destssn, destssn)
        self.assertEqual(expected_volume_update, volume_update)
        # Good run. No volumes replicated. No replication_driver_data.
        volumes = [{'id': fake.VOLUME_ID},
                   {'id': fake.VOLUME2_ID}]
        expected_volume_update = [{'volume_id': fake.VOLUME_ID, 'updates':
                                   {'status': 'error'}},
                                  {'volume_id': fake.VOLUME2_ID, 'updates':
                                   {'status': 'error'}}]
        self.driver.failed_over = False
        self.driver.active_backend_id = None
        destssn, volume_update, __ = self.driver.failover_host(
            {}, volumes, '12345', [])
        self.assertEqual(expected_destssn, destssn)
        self.assertEqual(expected_volume_update, volume_update)
        # Secondary not found.
        mock_parse_secondary.return_value = None
        self.driver.failed_over = False
        self.driver.active_backend_id = None
        self.assertRaises(exception.InvalidReplicationTarget,
                          self.driver.failover_host,
                          {},
                          volumes,
                          '54321',
                          [])
        # Already failed over.
        self.driver.failed_over = True
        self.driver.failover_host({}, volumes, 'default')
        mock_failback_volumes.assert_called_once_with(volumes)
        # Already failed over.
        self.assertRaises(exception.InvalidReplicationTarget,
                          self.driver.failover_host, {}, volumes, '67890', [])
        self.driver.replication_enabled = False

    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       '_failover_live_volume')
    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       '_parse_secondary')
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume')
    @mock.patch.object(storagecenter_api.SCApi,
                       'remove_mappings')
    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       'failback_volumes')
    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       '_get_replication_specs')
    def test_failover_host_live_volume(self,
                                       mock_get_replication_specs,
                                       mock_failback_volumes,
                                       mock_remove_mappings,
                                       mock_find_volume,
                                       mock_parse_secondary,
                                       mock_failover_live_volume,
                                       mock_close_connection,
                                       mock_open_connection,
                                       mock_init):
        mock_get_replication_specs.return_value = {'enabled': False,
                                                   'live': False}
        self.driver.replication_enabled = False
        self.driver.failed_over = False
        volumes = [{'id': fake.VOLUME_ID,
                    'replication_driver_data': '12345',
                    'provider_id': '1.1'},
                   {'id': fake.VOLUME2_ID,
                    'replication_driver_data': '12345',
                    'provider_id': '1.2'}]
        # No run. Not doing repl.  Should raise.
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.failover_host,
                          {},
                          volumes,
                          '12345')
        # Good run
        self.driver.replication_enabled = True
        mock_get_replication_specs.return_value = {'enabled': True,
                                                   'live': True}
        mock_parse_secondary.return_value = 12345
        expected_destssn = 12345
        mock_failover_live_volume.side_effect = [
            {'provider_id': '2.1', 'replication_status': 'failed-over'},  # 1
            {'provider_id': '2.2', 'replication_status': 'failed-over'},
            {'provider_id': '2.1', 'replication_status': 'failed-over'},  # 2
            {'provider_id': '2.1', 'replication_status': 'failed-over'}]  # 3
        expected_volume_update = [{'volume_id': fake.VOLUME_ID, 'updates':
                                   {'replication_status': 'failed-over',
                                    'provider_id': '2.1'}},
                                  {'volume_id': fake.VOLUME2_ID, 'updates':
                                   {'replication_status': 'failed-over',
                                    'provider_id': '2.2'}}]
        destssn, volume_update, __ = self.driver.failover_host(
            {}, volumes, '12345', [])
        self.assertEqual(expected_destssn, destssn)
        self.assertEqual(expected_volume_update, volume_update)
        # Good run. Not all volumes replicated.
        volumes = [{'id': fake.VOLUME_ID, 'replication_driver_data': '12345'},
                   {'id': fake.VOLUME2_ID, 'replication_driver_data': ''}]
        expected_volume_update = [{'volume_id': fake.VOLUME_ID, 'updates':
                                   {'replication_status': 'failed-over',
                                    'provider_id': '2.1'}},
                                  {'volume_id': fake.VOLUME2_ID, 'updates':
                                   {'status': 'error'}}]
        self.driver.failed_over = False
        self.driver.active_backend_id = None
        destssn, volume_update, __ = self.driver.failover_host(
            {}, volumes, '12345', [])
        self.assertEqual(expected_destssn, destssn)
        self.assertEqual(expected_volume_update, volume_update)
        # Good run. Not all volumes replicated. No replication_driver_data.
        volumes = [{'id': fake.VOLUME_ID, 'replication_driver_data': '12345'},
                   {'id': fake.VOLUME2_ID}]
        expected_volume_update = [{'volume_id': fake.VOLUME_ID, 'updates':
                                   {'replication_status': 'failed-over',
                                    'provider_id': '2.1'}},
                                  {'volume_id': fake.VOLUME2_ID, 'updates':
                                   {'status': 'error'}}]
        self.driver.failed_over = False
        self.driver.active_backend_id = None
        destssn, volume_update, __ = self.driver.failover_host(
            {}, volumes, '12345', [])
        self.assertEqual(expected_destssn, destssn)
        self.assertEqual(expected_volume_update, volume_update)
        # Good run. No volumes replicated. No replication_driver_data.
        volumes = [{'id': fake.VOLUME_ID},
                   {'id': fake.VOLUME2_ID}]
        expected_volume_update = [{'volume_id': fake.VOLUME_ID, 'updates':
                                   {'status': 'error'}},
                                  {'volume_id': fake.VOLUME2_ID, 'updates':
                                   {'status': 'error'}}]
        self.driver.failed_over = False
        self.driver.active_backend_id = None
        destssn, volume_update, __ = self.driver.failover_host(
            {}, volumes, '12345', [])
        self.assertEqual(expected_destssn, destssn)
        self.assertEqual(expected_volume_update, volume_update)
        # Secondary not found.
        mock_parse_secondary.return_value = None
        self.driver.failed_over = False
        self.driver.active_backend_id = None
        self.assertRaises(exception.InvalidReplicationTarget,
                          self.driver.failover_host,
                          {},
                          volumes,
                          '54321',
                          [])
        # Already failed over.
        self.driver.failed_over = True
        self.driver.failover_host({}, volumes, 'default')
        mock_failback_volumes.assert_called_once_with(volumes)
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
                          fake.VOLUME_ID,
                          '11111.1',
                          existing_ref)
        existing_ref = {'source-id': 'Not a source-name'}
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver._get_unmanaged_replay,
                          mock_api,
                          fake.VOLUME_ID,
                          '11111.1',
                          existing_ref)
        existing_ref = {'source-name': 'name'}
        mock_api.find_volume = mock.MagicMock(return_value=None)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver._get_unmanaged_replay,
                          mock_api,
                          fake.VOLUME_ID,
                          '11111.1',
                          existing_ref)
        mock_api.find_volume.return_value = {'instanceId': '11111.1'}
        mock_api.find_replay = mock.MagicMock(return_value=None)
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver._get_unmanaged_replay,
                          mock_api,
                          fake.VOLUME_ID,
                          '11111.1',
                          existing_ref)
        mock_api.find_replay.return_value = {'instanceId': '11111.101'}
        ret = self.driver._get_unmanaged_replay(mock_api, fake.VOLUME_ID,
                                                '11111.1', existing_ref)
        self.assertEqual({'instanceId': '11111.101'}, ret)

    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       '_get_unmanaged_replay')
    @mock.patch.object(storagecenter_api.SCApi,
                       'manage_replay')
    def test_manage_existing_snapshot(self,
                                      mock_manage_replay,
                                      mock_get_unmanaged_replay,
                                      mock_close_connection,
                                      mock_open_connection,
                                      mock_init):
        snapshot = {'volume_id': fake.VOLUME_ID,
                    'id': fake.SNAPSHOT_ID}
        existing_ref = {'source-name': 'name'}
        screplay = {'description': 'name', 'createVolume': {'instanceId': '1'}}
        expected = {'provider_id': '1'}
        mock_get_unmanaged_replay.return_value = screplay
        mock_manage_replay.return_value = True
        ret = self.driver.manage_existing_snapshot(snapshot, existing_ref)
        self.assertEqual(expected, ret)
        self.assertEqual(1, mock_get_unmanaged_replay.call_count)
        mock_manage_replay.assert_called_once_with(screplay, fake.SNAPSHOT_ID)
        mock_manage_replay.return_value = False
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.manage_existing_snapshot,
                          snapshot,
                          existing_ref)

    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       '_get_unmanaged_replay')
    def test_manage_existing_snapshot_get_size(self,
                                               mock_get_unmanaged_replay,
                                               mock_close_connection,
                                               mock_open_connection,
                                               mock_init):
        snapshot = {'volume_id': fake.VOLUME_ID,
                    'id': fake.SNAPSHOT_ID}
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

    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume')
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_replay')
    @mock.patch.object(storagecenter_api.SCApi,
                       'unmanage_replay')
    def test_unmanage_snapshot(self,
                               mock_unmanage_replay,
                               mock_find_replay,
                               mock_find_volume,
                               mock_close_connection,
                               mock_open_connection,
                               mock_init):
        snapshot = {'volume_id': fake.VOLUME_ID,
                    'id': fake.SNAPSHOT_ID}
        mock_find_volume.return_value = None
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.unmanage_snapshot,
                          snapshot)
        mock_find_volume.return_value = {'name': fake.VOLUME_ID}
        mock_find_replay.return_value = None
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.unmanage_snapshot,
                          snapshot)
        screplay = {'description': fake.SNAPSHOT_ID}
        mock_find_replay.return_value = screplay
        self.driver.unmanage_snapshot(snapshot)
        mock_unmanage_replay.assert_called_once_with(screplay)

    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       '_get_qos',
                       return_value='cinderqos')
    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       '_parse_extraspecs',
                       return_value={'replay_profile_string': 'pro'})
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume')
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_repl_volume')
    @mock.patch.object(storagecenter_api.SCApi,
                       'delete_replication')
    @mock.patch.object(storagecenter_api.SCApi,
                       'replicate_to_common')
    @mock.patch.object(storagecenter_api.SCApi,
                       'remove_mappings')
    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       '_wait_for_replication')
    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       '_reattach_remaining_replications')
    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       '_fixup_types')
    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       '_volume_updates',
                       return_value=[])
    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       '_update_backend')
    def test_failback_volumes(self,
                              mock_update_backend,
                              mock_volume_updates,
                              mock_fixup_types,
                              mock_reattach_remaining_replications,
                              mock_wait_for_replication,
                              mock_remove_mappings,
                              mock_replicate_to_common,
                              mock_delete_replication,
                              mock_find_repl_volume,
                              mock_find_volume,
                              mock_parse_extraspecs,
                              mock_get_qos,
                              mock_close_connection,
                              mock_open_connection,
                              mock_init):
        self.driver.replication_enabled = True
        self.driver.failed_over = True
        self.driver.active_backend_id = 12345
        self.driver.primaryssn = 11111
        backends = self.driver.backends
        self.driver.backends = [{'target_device_id': '12345',
                                 'qosnode': 'cinderqos'},
                                {'target_device_id': '67890',
                                 'qosnode': 'cinderqos'}]
        volumes = [{'id': fake.VOLUME_ID,
                    'replication_driver_data': '12345',
                    'provider_id': '12345.1'},
                   {'id': fake.VOLUME2_ID,
                    'replication_driver_data': '12345',
                    'provider_id': '12345.2'}]
        mock_find_volume.side_effect = [{'instanceId': '12345.1'},
                                        {'instanceId': '12345.2'}]
        mock_find_repl_volume.side_effect = [{'instanceId': '11111.1'},
                                             {'instanceId': '11111.2'}]
        mock_replicate_to_common.side_effect = [{'instanceId': '12345.100',
                                                 'destinationVolume':
                                                     {'instanceId': '11111.3'}
                                                 },
                                                {'instanceId': '12345.200',
                                                 'destinationVolume':
                                                     {'instanceId': '11111.4'}
                                                 }]
        # we don't care about the return.  We just want to make sure that
        # _wait_for_replication is called with the proper replitems.
        self.driver.failback_volumes(volumes)
        expected = [{'volume': volumes[0],
                     'specs': {'replay_profile_string': 'pro'},
                     'qosnode': 'cinderqos',
                     'screpl': '12345.100',
                     'cvol': '12345.1',
                     'ovol': '11111.1',
                     'nvol': '11111.3',
                     'rdd': '12345',
                     'status': 'inprogress'},
                    {'volume': volumes[1],
                     'specs': {'replay_profile_string': 'pro'},
                     'qosnode': 'cinderqos',
                     'screpl': '12345.200',
                     'cvol': '12345.2',
                     'ovol': '11111.2',
                     'nvol': '11111.4',
                     'rdd': '12345',
                     'status': 'inprogress'}
                    ]
        # We are stubbing everything out so we just want to be sure this hits
        # _volume_updates as expected.  (Ordinarily this would be modified by
        # the time it hit this but since it isn't we use this to our advantage
        # and check that our replitems was set correctly coming out of the
        # main loop.)
        mock_volume_updates.assert_called_once_with(expected)

        self.driver.replication_enabled = False
        self.driver.failed_over = False
        self.driver.backends = backends

    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       '_get_qos',
                       return_value='cinderqos')
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume')
    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       '_update_backend')
    @mock.patch.object(storagecenter_api.SCApi,
                       'get_live_volume')
    @mock.patch.object(storagecenter_api.SCApi,
                       'swap_roles_live_volume')
    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       '_get_replication_specs')
    def test_failback_volumes_live_vol(self,
                                       mock_get_replication_specs,
                                       mock_swap_roles_live_volume,
                                       mock_get_live_volume,
                                       mock_update_backend,
                                       mock_find_volume,
                                       mock_get_qos,
                                       mock_close_connection,
                                       mock_open_connection,
                                       mock_init):
        self.driver.replication_enabled = True
        self.driver.failed_over = True
        self.driver.active_backend_id = 12345
        self.driver.primaryssn = 11111
        backends = self.driver.backends
        self.driver.backends = [{'target_device_id': '12345',
                                 'qosnode': 'cinderqos',
                                 'remoteqos': 'remoteqos'}]
        volumes = [{'id': fake.VOLUME_ID,
                    'replication_driver_data': '12345',
                    'provider_id': '12345.1'},
                   {'id': fake.VOLUME2_ID,
                    'replication_driver_data': '12345',
                    'provider_id': '12345.2'}]
        mock_get_live_volume.side_effect = [
            {'instanceId': '11111.101',
             'secondaryVolume': {'instanceId': '11111.1001',
                                 'instanceName': fake.VOLUME_ID},
             'secondaryScSerialNumber': 11111},
            {'instanceId': '11111.102',
             'secondaryVolume': {'instanceId': '11111.1002',
                                 'instanceName': fake.VOLUME2_ID},
             'secondaryScSerialNumber': 11111}
        ]
        mock_get_replication_specs.return_value = {'enabled': True,
                                                   'live': True}
        mock_swap_roles_live_volume.side_effect = [True, True]
        mock_find_volume.side_effect = [{'instanceId': '12345.1'},
                                        {'instanceId': '12345.2'}]

        # we don't care about the return.  We just want to make sure that
        # _wait_for_replication is called with the proper replitems.
        ret = self.driver.failback_volumes(volumes)
        expected = [{'updates': {'provider_id': '11111.1001',
                                 'replication_status': 'enabled',
                                 'status': 'available'},
                     'volume_id': fake.VOLUME_ID},
                    {'updates': {'provider_id': '11111.1002',
                                 'replication_status': 'enabled',
                                 'status': 'available'},
                     'volume_id': fake.VOLUME2_ID}]

        self.assertEqual(expected, ret)

        self.driver.replication_enabled = False
        self.driver.failed_over = False
        self.driver.backends = backends

    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       '_get_qos',
                       return_value='cinderqos')
    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       '_parse_extraspecs',
                       return_value={'replay_profile_string': 'pro'})
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_volume')
    @mock.patch.object(storagecenter_api.SCApi,
                       'find_repl_volume')
    @mock.patch.object(storagecenter_api.SCApi,
                       'delete_replication')
    @mock.patch.object(storagecenter_api.SCApi,
                       'replicate_to_common')
    @mock.patch.object(storagecenter_api.SCApi,
                       'remove_mappings')
    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       '_wait_for_replication')
    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       '_reattach_remaining_replications')
    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       '_fixup_types')
    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       '_volume_updates',
                       return_value=[])
    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       '_update_backend')
    def test_failback_volumes_with_some_not_replicated(
            self,
            mock_update_backend,
            mock_volume_updates,
            mock_fixup_types,
            mock_reattach_remaining_replications,
            mock_wait_for_replication,
            mock_remove_mappings,
            mock_replicate_to_common,
            mock_delete_replication,
            mock_find_repl_volume,
            mock_find_volume,
            mock_parse_extraspecs,
            mock_get_qos,
            mock_close_connection,
            mock_open_connection,
            mock_init):
        self.driver.replication_enabled = True
        self.driver.failed_over = True
        self.driver.active_backend_id = 12345
        self.driver.primaryssn = 11111
        backends = self.driver.backends
        self.driver.backends = [{'target_device_id': '12345',
                                 'qosnode': 'cinderqos'},
                                {'target_device_id': '67890',
                                 'qosnode': 'cinderqos'}]
        volumes = [{'id': fake.VOLUME_ID,
                    'replication_driver_data': '12345',
                    'provider_id': '12345.1'},
                   {'id': fake.VOLUME2_ID,
                    'replication_driver_data': '12345',
                    'provider_id': '12345.2'},
                   {'id': fake.VOLUME3_ID, 'provider_id': '11111.10'}]
        mock_find_volume.side_effect = [{'instanceId': '12345.1'},
                                        {'instanceId': '12345.2'}]
        mock_find_repl_volume.side_effect = [{'instanceId': '11111.1'},
                                             {'instanceId': '11111.2'}]
        mock_replicate_to_common.side_effect = [{'instanceId': '12345.100',
                                                 'destinationVolume':
                                                     {'instanceId': '11111.3'}
                                                 },
                                                {'instanceId': '12345.200',
                                                 'destinationVolume':
                                                     {'instanceId': '11111.4'}
                                                 }]
        expected = [{'volume': volumes[0],
                     'specs': {'replay_profile_string': 'pro'},
                     'qosnode': 'cinderqos',
                     'screpl': '12345.100',
                     'cvol': '12345.1',
                     'ovol': '11111.1',
                     'nvol': '11111.3',
                     'rdd': '12345',
                     'status': 'inprogress'},
                    {'volume': volumes[1],
                     'specs': {'replay_profile_string': 'pro'},
                     'qosnode': 'cinderqos',
                     'screpl': '12345.200',
                     'cvol': '12345.2',
                     'ovol': '11111.2',
                     'nvol': '11111.4',
                     'rdd': '12345',
                     'status': 'inprogress'}
                    ]
        ret = self.driver.failback_volumes(volumes)
        mock_volume_updates.assert_called_once_with(expected)

        # make sure ret is right. In this case just the unreplicated volume
        # as our volume updates elsewhere return nothing.
        expected_updates = [{'volume_id': fake.VOLUME3_ID,
                             'updates': {'status': 'available'}}]
        self.assertEqual(expected_updates, ret)
        self.driver.replication_enabled = False
        self.driver.failed_over = False
        self.driver.backends = backends

    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       '_get_qos',
                       return_value='cinderqos')
    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       '_update_backend')
    def test_failback_volumes_with_none_replicated(
            self,
            mock_update_backend,
            mock_get_qos,
            mock_close_connection,
            mock_open_connection,
            mock_init):
        self.driver.replication_enabled = True
        self.driver.failed_over = True
        self.driver.active_backend_id = 12345
        self.driver.primaryssn = 11111
        backends = self.driver.backends
        self.driver.backends = [{'target_device_id': '12345',
                                 'qosnode': 'cinderqos'},
                                {'target_device_id': '67890',
                                 'qosnode': 'cinderqos'}]
        volumes = [{'id': fake.VOLUME_ID,
                    'provider_id': '11111.1'},
                   {'id': fake.VOLUME2_ID, 'provider_id': '11111.2'},
                   {'id': fake.VOLUME3_ID, 'provider_id': '11111.10'}]

        ret = self.driver.failback_volumes(volumes)

        # make sure ret is right. In this case just the unreplicated volume
        # as our volume updates elsewhere return nothing.
        expected_updates = [{'volume_id': fake.VOLUME_ID,
                             'updates': {'status': 'available'}},
                            {'volume_id': fake.VOLUME2_ID,
                             'updates': {'status': 'available'}},
                            {'volume_id': fake.VOLUME3_ID,
                             'updates': {'status': 'available'}}]
        self.assertEqual(expected_updates, ret)
        self.driver.replication_enabled = False
        self.driver.failed_over = False
        self.driver.backends = backends

    def test_volume_updates(self,
                            mock_close_connection,
                            mock_open_connection,
                            mock_init):
        items = [{'volume': {'id': fake.VOLUME_ID},
                  'specs': {'replay_profile_string': 'pro'},
                  'qosnode': 'cinderqos',
                  'screpl': '12345.100',
                  'cvol': '12345.1',
                  'ovol': '11111.1',
                  'nvol': '11111.3',
                  'rdd': '12345,67890',
                  'status': 'available'},
                 {'volume': {'id': fake.VOLUME2_ID},
                  'specs': {'replay_profile_string': 'pro'},
                  'qosnode': 'cinderqos',
                  'screpl': '12345.200',
                  'cvol': '12345.2',
                  'ovol': '11111.2',
                  'nvol': '11111.4',
                  'rdd': '12345,67890',
                  'status': 'available'}
                 ]
        ret = self.driver._volume_updates(items)
        expected = [{'volume_id': fake.VOLUME_ID,
                     'updates': {'status': 'available',
                                 'replication_status': 'enabled',
                                 'provider_id': '11111.3',
                                 'replication_driver_data': '12345,67890'}},
                    {'volume_id': fake.VOLUME2_ID,
                     'updates': {'status': 'available',
                                 'replication_status': 'enabled',
                                 'provider_id': '11111.4',
                                 'replication_driver_data': '12345,67890'}}
                    ]
        self.assertEqual(expected, ret)
        items.append({'volume': {'id': fake.VOLUME3_ID},
                      'specs': {'replay_profile_string': 'pro'},
                      'qosnode': 'cinderqos',
                      'screpl': '12345.300',
                      'cvol': '12345.5',
                      'ovol': '11111.5',
                      'nvol': '11111.6',
                      'rdd': '12345',
                      'status': 'error'})

        ret = self.driver._volume_updates(items)
        expected.append({'volume_id': fake.VOLUME3_ID,
                         'updates': {'status': 'error',
                                     'replication_status': 'error',
                                     'provider_id': '11111.6',
                                     'replication_driver_data': '12345'}})
        self.assertEqual(expected, ret)

    @mock.patch.object(storagecenter_api.SCApi,
                       'get_volume',
                       return_value=VOLUME)
    def test_fixup_types(self,
                         mock_get_volume,
                         mock_close_connection,
                         mock_open_connection,
                         mock_init):
        items = [{'volume': {'id': fake.VOLUME_ID},
                  'specs': {'replay_profile_string': 'pro'},
                  'qosnode': 'cinderqos',
                  'screpl': '12345.100',
                  'cvol': '12345.1',
                  'ovol': '11111.1',
                  'nvol': '11111.3',
                  'rdd': '12345,67890',
                  'status': 'reattached'},
                 {'volume': {'id': fake.VOLUME2_ID},
                  'specs': {'replay_profile_string': 'pro'},
                  'qosnode': 'cinderqos',
                  'screpl': '12345.200',
                  'cvol': '12345.2',
                  'ovol': '11111.2',
                  'nvol': '11111.4',
                  'rdd': '12345,67890',
                  'status': 'reattached'}
                 ]
        mock_api = mock.Mock()
        mock_api.update_replay_profiles.return_value = True
        self.driver._fixup_types(mock_api, items)
        expected = [{'volume': {'id': fake.VOLUME_ID},
                     'specs': {'replay_profile_string': 'pro'},
                     'qosnode': 'cinderqos',
                     'screpl': '12345.100',
                     'cvol': '12345.1',
                     'ovol': '11111.1',
                     'nvol': '11111.3',
                     'rdd': '12345,67890',
                     'status': 'available'},
                    {'volume': {'id': fake.VOLUME2_ID},
                     'specs': {'replay_profile_string': 'pro'},
                     'qosnode': 'cinderqos',
                     'screpl': '12345.200',
                     'cvol': '12345.2',
                     'ovol': '11111.2',
                     'nvol': '11111.4',
                     'rdd': '12345,67890',
                     'status': 'available'}]
        self.assertEqual(expected, items)

    @mock.patch.object(storagecenter_api.SCApi,
                       'get_volume',
                       return_value=VOLUME)
    def test_fixup_types_with_error(self,
                                    mock_get_volume,
                                    mock_close_connection,
                                    mock_open_connection,
                                    mock_init):
        items = [{'volume': {'id': fake.VOLUME_ID},
                  'specs': {'replay_profile_string': 'pro'},
                  'qosnode': 'cinderqos',
                  'screpl': '12345.100',
                  'cvol': '12345.1',
                  'ovol': '11111.1',
                  'nvol': '11111.3',
                  'rdd': '12345,67890',
                  'status': 'reattached'},
                 {'volume': {'id': fake.VOLUME2_ID},
                  'specs': {'replay_profile_string': 'pro'},
                  'qosnode': 'cinderqos',
                  'screpl': '12345.200',
                  'cvol': '12345.2',
                  'ovol': '11111.2',
                  'nvol': '11111.4',
                  'rdd': '12345,67890',
                  'status': 'reattached'}
                 ]
        # One good one fail.
        mock_api = mock.Mock()
        mock_api.update_replay_profiles.side_effect = [True, False]
        self.driver._fixup_types(mock_api, items)
        expected = [{'volume': {'id': fake.VOLUME_ID},
                     'specs': {'replay_profile_string': 'pro'},
                     'qosnode': 'cinderqos',
                     'screpl': '12345.100',
                     'cvol': '12345.1',
                     'ovol': '11111.1',
                     'nvol': '11111.3',
                     'rdd': '12345,67890',
                     'status': 'available'},
                    {'volume': {'id': fake.VOLUME2_ID},
                     'specs': {'replay_profile_string': 'pro'},
                     'qosnode': 'cinderqos',
                     'screpl': '12345.200',
                     'cvol': '12345.2',
                     'ovol': '11111.2',
                     'nvol': '11111.4',
                     'rdd': '12345,67890',
                     'status': 'error'}]
        self.assertEqual(expected, items)

    @mock.patch.object(storagecenter_api.SCApi,
                       'get_volume',
                       return_value=VOLUME)
    def test_fixup_types_with_previous_error(self,
                                             mock_get_volume,
                                             mock_close_connection,
                                             mock_open_connection,
                                             mock_init):
        items = [{'volume': {'id': fake.VOLUME_ID},
                  'specs': {'replay_profile_string': 'pro'},
                  'qosnode': 'cinderqos',
                  'screpl': '12345.100',
                  'cvol': '12345.1',
                  'ovol': '11111.1',
                  'nvol': '11111.3',
                  'rdd': '12345,67890',
                  'status': 'reattached'},
                 {'volume': {'id': fake.VOLUME2_ID},
                  'specs': {'replay_profile_string': 'pro'},
                  'qosnode': 'cinderqos',
                  'screpl': '12345.200',
                  'cvol': '12345.2',
                  'ovol': '11111.2',
                  'nvol': '11111.4',
                  'rdd': '12345,67890',
                  'status': 'error'}
                 ]
        mock_api = mock.Mock()
        mock_api.update_replay_profiles.return_value = True
        self.driver._fixup_types(mock_api, items)
        expected = [{'volume': {'id': fake.VOLUME_ID},
                     'specs': {'replay_profile_string': 'pro'},
                     'qosnode': 'cinderqos',
                     'screpl': '12345.100',
                     'cvol': '12345.1',
                     'ovol': '11111.1',
                     'nvol': '11111.3',
                     'rdd': '12345,67890',
                     'status': 'available'},
                    {'volume': {'id': fake.VOLUME2_ID},
                     'specs': {'replay_profile_string': 'pro'},
                     'qosnode': 'cinderqos',
                     'screpl': '12345.200',
                     'cvol': '12345.2',
                     'ovol': '11111.2',
                     'nvol': '11111.4',
                     'rdd': '12345,67890',
                     'status': 'error'}]
        self.assertEqual(expected, items)

    def test_reattach_remaining_replications(self,
                                             mock_close_connection,
                                             mock_open_connection,
                                             mock_init):
        self.driver.replication_enabled = True
        self.driver.failed_over = True
        self.driver.active_backend_id = 12345
        self.driver.primaryssn = 11111
        backends = self.driver.backends
        self.driver.backends = [{'target_device_id': '12345',
                                 'qosnode': 'cinderqos'},
                                {'target_device_id': '67890',
                                 'qosnode': 'cinderqos'}]
        items = [{'volume': {'id': fake.VOLUME_ID},
                  'specs': {'replicationtype': 'Synchronous',
                            'activereplay': False},
                  'qosnode': 'cinderqos',
                  'screpl': '12345.100',
                  'cvol': '12345.1',
                  'ovol': '11111.1',
                  'nvol': '11111.3',
                  'rdd': '12345',
                  'status': 'synced'},
                 {'volume': {'id': fake.VOLUME2_ID},
                  'specs': {'replicationtype': 'Asynchronous',
                            'activereplay': True},
                  'qosnode': 'cinderqos',
                  'screpl': '12345.200',
                  'cvol': '12345.2',
                  'ovol': '11111.2',
                  'nvol': '11111.4',
                  'rdd': '12345',
                  'status': 'synced'}
                 ]
        mock_api = mock.Mock()
        mock_api.ssn = self.driver.active_backend_id
        mock_api.get_volume.return_value = self.VOLUME
        mock_api.find_repl_volume.return_value = self.VOLUME
        mock_api.start_replication.side_effect = [{'instanceId': '11111.1001'},
                                                  {'instanceId': '11111.1002'},
                                                  None,
                                                  {'instanceId': '11111.1001'}]
        self.driver._reattach_remaining_replications(mock_api, items)

        expected = [{'volume': {'id': fake.VOLUME_ID},
                     'specs': {'replicationtype': 'Synchronous',
                               'activereplay': False},
                     'qosnode': 'cinderqos',
                     'screpl': '12345.100',
                     'cvol': '12345.1',
                     'ovol': '11111.1',
                     'nvol': '11111.3',
                     'rdd': '12345,67890',
                     'status': 'reattached'},
                    {'volume': {'id': fake.VOLUME2_ID},
                     'specs': {'replicationtype': 'Asynchronous',
                               'activereplay': True},
                     'qosnode': 'cinderqos',
                     'screpl': '12345.200',
                     'cvol': '12345.2',
                     'ovol': '11111.2',
                     'nvol': '11111.4',
                     'rdd': '12345,67890',
                     'status': 'reattached'}]
        self.assertEqual(expected, items)
        mock_api.start_replication.assert_any_call(self.VOLUME, self.VOLUME,
                                                   'Synchronous', 'cinderqos',
                                                   False)

        mock_api.start_replication.assert_any_call(self.VOLUME, self.VOLUME,
                                                   'Asynchronous', 'cinderqos',
                                                   True)
        items = [{'volume': {'id': fake.VOLUME_ID},
                  'specs': {'replicationtype': 'Synchronous',
                            'activereplay': False},
                  'qosnode': 'cinderqos',
                  'screpl': '12345.100',
                  'cvol': '12345.1',
                  'ovol': '11111.1',
                  'nvol': '11111.3',
                  'rdd': '12345',
                  'status': 'synced'},
                 {'volume': {'id': fake.VOLUME2_ID},
                  'specs': {'replicationtype': 'Asynchronous',
                            'activereplay': True},
                  'qosnode': 'cinderqos',
                  'screpl': '12345.200',
                  'cvol': '12345.2',
                  'ovol': '11111.2',
                  'nvol': '11111.4',
                  'rdd': '12345',
                  'status': 'synced'}
                 ]
        self.driver._reattach_remaining_replications(mock_api, items)

        expected = [{'volume': {'id': fake.VOLUME_ID},
                     'specs': {'replicationtype': 'Synchronous',
                               'activereplay': False},
                     'qosnode': 'cinderqos',
                     'screpl': '12345.100',
                     'cvol': '12345.1',
                     'ovol': '11111.1',
                     'nvol': '11111.3',
                     'rdd': '12345',
                     'status': 'error'},
                    {'volume': {'id': fake.VOLUME2_ID},
                     'specs': {'replicationtype': 'Asynchronous',
                               'activereplay': True},
                     'qosnode': 'cinderqos',
                     'screpl': '12345.200',
                     'cvol': '12345.2',
                     'ovol': '11111.2',
                     'nvol': '11111.4',
                     'rdd': '12345,67890',
                     'status': 'reattached'}]
        self.assertEqual(expected, items)
        mock_api.start_replication.assert_any_call(self.VOLUME, self.VOLUME,
                                                   'Synchronous', 'cinderqos',
                                                   False)

        mock_api.start_replication.assert_any_call(self.VOLUME, self.VOLUME,
                                                   'Asynchronous', 'cinderqos',
                                                   True)

        self.driver.backends = backends

    def _setup_items(self):
        self.driver.replication_enabled = True
        self.driver.failed_over = True
        self.driver.active_backend_id = 12345
        self.driver.primaryssn = 11111
        backends = self.driver.backends
        self.driver.backends = [{'target_device_id': '12345',
                                 'qosnode': 'cinderqos'},
                                {'target_device_id': '67890',
                                 'qosnode': 'cinderqos'}]
        volumes = [{'id': fake.VOLUME_ID,
                    'replication_driver_data': '12345',
                    'provider_id': '12345.1'},
                   {'id': fake.VOLUME2_ID,
                    'replication_driver_data': '12345',
                    'provider_id': '12345.2'}]

        items = [{'volume': volumes[0],
                  'specs': {'replay_profile_string': 'pro',
                            'replicationtype': 'Asynchronous',
                            'activereplay': True},
                  'qosnode': 'cinderqos',
                  'screpl': '12345.100',
                  'cvol': '12345.1',
                  'ovol': '11111.1',
                  'nvol': '11111.3',
                  'rdd': '12345',
                  'status': 'inprogress'},
                 {'volume': volumes[1],
                  'specs': {'replay_profile_string': 'pro',
                            'replicationtype': 'Asynchronous',
                            'activereplay': True},
                  'qosnode': 'cinderqos',
                  'screpl': '12345.200',
                  'cvol': '12345.2',
                  'ovol': '11111.2',
                  'nvol': '11111.4',
                  'rdd': '12345',
                  'status': 'inprogress'}
                 ]
        return items, backends

    def test_wait_for_replication(self,
                                  mock_close_connection,
                                  mock_open_connection,
                                  mock_init):
        items, backends = self._setup_items()
        expected = []
        for item in items:
            expected.append(dict(item))
        expected[0]['status'] = 'synced'
        expected[1]['status'] = 'synced'
        mock_api = mock.Mock()
        mock_api.flip_replication.return_value = True
        mock_api.get_volume.return_value = self.VOLUME
        mock_api.replication_progress.return_value = (True, 0)
        mock_api.rename_volume.return_value = True
        self.driver._wait_for_replication(mock_api, items)
        self.assertEqual(expected, items)
        self.backends = backends

    def test_wait_for_replication_flip_flops(self,
                                             mock_close_connection,
                                             mock_open_connection,
                                             mock_init):
        items, backends = self._setup_items()
        expected = []
        for item in items:
            expected.append(dict(item))
        expected[0]['status'] = 'synced'
        expected[1]['status'] = 'error'
        mock_api = mock.Mock()
        mock_api.flip_replication.side_effect = [True, False]
        mock_api.get_volume.return_value = self.VOLUME
        mock_api.replication_progress.return_value = (True, 0)
        mock_api.rename_volume.return_value = True
        self.driver._wait_for_replication(mock_api, items)
        self.assertEqual(expected, items)
        self.backends = backends

    def test_wait_for_replication_flip_no_vol(self,
                                              mock_close_connection,
                                              mock_open_connection,
                                              mock_init):
        items, backends = self._setup_items()
        expected = []
        for item in items:
            expected.append(dict(item))
        expected[0]['status'] = 'synced'
        expected[1]['status'] = 'error'
        mock_api = mock.Mock()
        mock_api.flip_replication.return_value = True
        mock_api.get_volume.side_effect = [self.VOLUME, self.VOLUME,
                                           self.VOLUME,
                                           self.VOLUME, None]
        mock_api.replication_progress.return_value = (True, 0)
        mock_api.rename_volume.return_value = True
        self.driver._wait_for_replication(mock_api, items)
        self.assertEqual(expected, items)
        self.backends = backends

    def test_wait_for_replication_cant_find_orig(self,
                                                 mock_close_connection,
                                                 mock_open_connection,
                                                 mock_init):
        items, backends = self._setup_items()
        expected = []
        for item in items:
            expected.append(dict(item))
        expected[0]['status'] = 'synced'
        expected[1]['status'] = 'synced'
        mock_api = mock.Mock()
        mock_api.flip_replication.return_value = True
        mock_api.get_volume.side_effect = [self.VOLUME, self.VOLUME,
                                           None,
                                           self.VOLUME, self.VOLUME,
                                           None]
        mock_api.replication_progress.return_value = (True, 0)
        mock_api.rename_volume.return_value = True
        self.driver._wait_for_replication(mock_api, items)
        self.assertEqual(expected, items)
        self.backends = backends

    def test_wait_for_replication_rename_fail(self,
                                              mock_close_connection,
                                              mock_open_connection,
                                              mock_init):
        items, backends = self._setup_items()
        expected = []
        for item in items:
            expected.append(dict(item))
        expected[0]['status'] = 'synced'
        expected[1]['status'] = 'synced'
        mock_api = mock.Mock()
        mock_api.flip_replication.return_value = True
        mock_api.get_volume.return_value = self.VOLUME
        mock_api.replication_progress.return_value = (True, 0)
        mock_api.rename_volume.return_value = True
        self.driver._wait_for_replication(mock_api, items)
        self.assertEqual(expected, items)
        self.backends = backends

    def test_wait_for_replication_timeout(self,
                                          mock_close_connection,
                                          mock_open_connection,
                                          mock_init):
        items, backends = self._setup_items()
        expected = []
        for item in items:
            expected.append(dict(item))
        expected[0]['status'] = 'error'
        expected[1]['status'] = 'error'
        self.assertNotEqual(items, expected)
        mock_api = mock.Mock()
        mock_api.get_volume.side_effect = [self.VOLUME, self.VOLUME,
                                           self.VOLUME,
                                           self.VOLUME, None]
        mock_api.replication_progress.return_value = (False, 500)
        self.driver.failback_timeout = 1
        self.driver._wait_for_replication(mock_api, items)
        self.assertEqual(expected, items)
        calls = [mock.call(1)] * 5
        self.mock_sleep.assert_has_calls(calls)
        self.backends = backends

    @mock.patch.object(storagecenter_iscsi.SCISCSIDriver,
                       '_get_volume_extra_specs')
    def test_parse_extraspecs(self,
                              mock_get_volume_extra_specs,
                              mock_close_connection,
                              mock_open_connection,
                              mock_init):
        volume = {'id': fake.VOLUME_ID}
        mock_get_volume_extra_specs.return_value = {}
        ret = self.driver._parse_extraspecs(volume)
        expected = {'replicationtype': 'Asynchronous',
                    'activereplay': False,
                    'storage_profile': None,
                    'replay_profile_string': None}
        self.assertEqual(expected, ret)

    def test_get_qos(self,
                     mock_close_connection,
                     mock_open_connection,
                     mock_init):
        backends = self.driver.backends
        self.driver.backends = [{'target_device_id': '12345',
                                 'qosnode': 'cinderqos1'},
                                {'target_device_id': '67890',
                                 'qosnode': 'cinderqos2'}]
        ret = self.driver._get_qos(12345)
        self.assertEqual('cinderqos1', ret)
        ret = self.driver._get_qos(67890)
        self.assertEqual('cinderqos2', ret)
        ret = self.driver._get_qos(11111)
        self.assertIsNone(ret)
        self.driver.backends[0] = {'target_device_id': '12345'}
        ret = self.driver._get_qos(12345)
        self.assertEqual('cinderqos', ret)
        self.driver.backends = backends

    def test_thaw_backend(self,
                          mock_close_connection,
                          mock_open_connection,
                          mock_init):
        self.driver.failed_over = False
        ret = self.driver.thaw_backend(self._context)
        self.assertTrue(ret)

    def test_thaw_backend_failed_over(self,
                                      mock_close_connection,
                                      mock_open_connection,
                                      mock_init):
        self.driver.failed_over = True
        self.assertRaises(exception.Invalid,
                          self.driver.thaw_backend,
                          self._context)
