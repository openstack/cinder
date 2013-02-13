#!/usr/bin/env python
# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
#    (c) Copyright 2013 Hewlett-Packard Development Company, L.P.
#    All Rights Reserved.
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
"""
Unit tests for OpenStack Cinder volume drivers
"""
import shutil
import tempfile

from hp3parclient import exceptions as hpexceptions

from cinder import exception
import cinder.flags
from cinder.openstack.common import log as logging
from cinder import test
from cinder.volume.drivers.san.hp import hp_3par_fc as hpfcdriver
from cinder.volume.drivers.san.hp import hp_3par_iscsi as hpdriver

FLAGS = cinder.flags.FLAGS

LOG = logging.getLogger(__name__)

HP3PAR_DOMAIN = 'OpenStack',
HP3PAR_CPG = 'OpenStackCPG',
HP3PAR_CPG_SNAP = 'OpenStackCPGSnap'


class FakeHP3ParClient(object):

    api_url = None
    debug = False

    volumes = []
    hosts = []
    vluns = []
    cpgs = [
        {'SAGrowth': {'LDLayout': {'diskPatterns': [{'diskType': 2}]},
                      'incrementMiB': 8192},
         'SAUsage': {'rawTotalMiB': 24576,
                     'rawUsedMiB': 768,
                     'totalMiB': 8192,
                     'usedMiB': 256},
         'SDGrowth': {'LDLayout': {'RAIDType': 4,
                      'diskPatterns': [{'diskType': 2}]},
                      'incrementMiB': 32768},
         'SDUsage': {'rawTotalMiB': 49152,
                     'rawUsedMiB': 1023,
                     'totalMiB': 36864,
                     'usedMiB': 768},
         'UsrUsage': {'rawTotalMiB': 57344,
                      'rawUsedMiB': 43349,
                      'totalMiB': 43008,
                      'usedMiB': 32512},
         'additionalStates': [],
         'degradedStates': [],
         'domain': HP3PAR_DOMAIN,
         'failedStates': [],
         'id': 5,
         'name': HP3PAR_CPG,
         'numFPVVs': 2,
         'numTPVVs': 0,
         'state': 1,
         'uuid': '29c214aa-62b9-41c8-b198-543f6cf24edf'}]

    def __init__(self, api_url):
        self.api_url = api_url

    def debug_rest(self, flag):
        self.debug = flag

    def login(self, username, password, optional=None):
        return None

    def logout(self):
        return None

    def getVolumes(self):
        return self.volumes

    def getVolume(self, name):
        if self.volumes:
            for volume in self.volumes:
                if volume['name'] == name:
                    return volume

        msg = {'code': 'NON_EXISTENT_HOST',
               'desc': "VOLUME '%s' was not found" % name}
        raise hpexceptions.HTTPNotFound(msg)

    def createVolume(self, name, cpgName, sizeMiB, optional=None):
        new_vol = {'additionalStates': [],
                   'adminSpace': {'freeMiB': 0,
                                  'rawReservedMiB': 384,
                                  'reservedMiB': 128,
                                  'usedMiB': 128},
                   'baseId': 115,
                   'comment': optional['comment'],
                   'copyType': 1,
                   'creationTime8601': '2012-10-22T16:37:57-07:00',
                   'creationTimeSec': 1350949077,
                   'degradedStates': [],
                   'domain': HP3PAR_DOMAIN,
                   'failedStates': [],
                   'id': 115,
                   'name': name,
                   'policies': {'caching': True,
                                'oneHost': False,
                                'staleSS': True,
                                'system': False,
                                'zeroDetect': False},
                   'provisioningType': 1,
                   'readOnly': False,
                   'sizeMiB': sizeMiB,
                   'snapCPG': optional['snapCPG'],
                   'snapshotSpace': {'freeMiB': 0,
                                     'rawReservedMiB': 683,
                                     'reservedMiB': 512,
                                     'usedMiB': 512},
                   'ssSpcAllocLimitPct': 0,
                   'ssSpcAllocWarningPct': 0,
                   'state': 1,
                   'userCPG': cpgName,
                   'userSpace': {'freeMiB': 0,
                                 'rawReservedMiB': 41984,
                                 'reservedMiB': 31488,
                                 'usedMiB': 31488},
                   'usrSpcAllocLimitPct': 0,
                   'usrSpcAllocWarningPct': 0,
                   'uuid': '1e7daee4-49f4-4d07-9ab8-2b6a4319e243',
                   'wwn': '50002AC00073383D'}
        self.volumes.append(new_vol)
        return None

    def deleteVolume(self, name):
        volume = self.getVolume(name)
        self.volumes.remove(volume)

    def createSnapshot(self, name, copyOfName, optional=None):
        new_snap = {'additionalStates': [],
                    'adminSpace': {'freeMiB': 0,
                                   'rawReservedMiB': 0,
                                   'reservedMiB': 0,
                                   'usedMiB': 0},
                    'baseId': 342,
                    'comment': optional['comment'],
                    'copyOf': copyOfName,
                    'copyType': 3,
                    'creationTime8601': '2012-11-09T15:13:28-08:00',
                    'creationTimeSec': 1352502808,
                    'degradedStates': [],
                    'domain': HP3PAR_DOMAIN,
                    'expirationTime8601': '2012-11-09T17:13:28-08:00',
                    'expirationTimeSec': 1352510008,
                    'failedStates': [],
                    'id': 343,
                    'name': name,
                    'parentId': 342,
                    'policies': {'caching': True,
                                 'oneHost': False,
                                 'staleSS': True,
                                 'system': False,
                                 'zeroDetect': False},
                    'provisioningType': 3,
                    'readOnly': True,
                    'retentionTime8601': '2012-11-09T16:13:27-08:00',
                    'retentionTimeSec': 1352506407,
                    'sizeMiB': 256,
                    'snapCPG': HP3PAR_CPG_SNAP,
                    'snapshotSpace': {'freeMiB': 0,
                                      'rawReservedMiB': 0,
                                      'reservedMiB': 0,
                                      'usedMiB': 0},
                    'ssSpcAllocLimitPct': 0,
                    'ssSpcAllocWarningPct': 0,
                    'state': 1,
                    'userCPG': HP3PAR_CPG,
                    'userSpace': {'freeMiB': 0,
                                  'rawReservedMiB': 0,
                                  'reservedMiB': 0,
                                  'usedMiB': 0},
                    'usrSpcAllocLimitPct': 0,
                    'usrSpcAllocWarningPct': 0,
                    'uuid': 'd7a40b8f-2511-46a8-9e75-06383c826d19',
                    'wwn': '50002AC00157383D'}
        self.volumes.append(new_snap)
        return None

    def deleteSnapshot(self, name):
        volume = self.getVolume(name)
        self.volumes.remove(volume)

    def getCPGs(self):
        return self.cpgs

    def getCPG(self, name):
        if self.cpgs:
            for cpg in self.cpgs:
                if cpg['name'] == name:
                    return cpg

        msg = {'code': 'NON_EXISTENT_HOST',
               'desc': "CPG '%s' was not found" % name}
        raise hpexceptions.HTTPNotFound(msg)

    def createVLUN(self, volumeName, lun, hostname=None,
                   portPos=None, noVcn=None,
                   overrideLowerPriority=None):

        vlun = {'active': False,
                'failedPathInterval': 0,
                'failedPathPol': 1,
                'hostname': hostname,
                'lun': lun,
                'multipathing': 1,
                'portPos': portPos,
                'type': 4,
                'volumeName': volumeName,
                'volumeWWN': '50002AC00077383D'}
        self.vluns.append(vlun)
        return None

    def deleteVLUN(self, name, lunID, hostname=None, port=None):
        vlun = self.getVLUN(name)
        self.vluns.remove(vlun)

    def getVLUNs(self):
        return self.vluns

    def getVLUN(self, volumeName):
        for vlun in self.vluns:
            if vlun['volumeName'] == volumeName:
                return vlun

        msg = {'code': 'NON_EXISTENT_HOST',
               'desc': "VLUN '%s' was not found" % volumeName}
        raise hpexceptions.HTTPNotFound(msg)


class HP3PARBaseDriver():

    VOLUME_ID = "d03338a9-9115-48a3-8dfc-35cdfcdc15a7"
    CLONE_ID = "d03338a9-9115-48a3-8dfc-000000000000"
    VOLUME_NAME = "volume-d03338a9-9115-48a3-8dfc-35cdfcdc15a7"
    SNAPSHOT_ID = "2f823bdc-e36e-4dc8-bd15-de1c7a28ff31"
    SNAPSHOT_NAME = "snapshot-2f823bdc-e36e-4dc8-bd15-de1c7a28ff31"
    VOLUME_3PAR_NAME = "osv-0DM4qZEVSKON-DXN-NwVpw"
    SNAPSHOT_3PAR_NAME = "oss-L4I73ONuTci9Fd4ceij-MQ"
    FAKE_HOST = "fakehost"
    USER_ID = '2689d9a913974c008b1d859013f23607'
    PROJECT_ID = 'fac88235b9d64685a3530f73e490348f'
    VOLUME_ID_SNAP = '761fc5e5-5191-4ec7-aeba-33e36de44156'
    FAKE_DESC = 'test description name'
    FAKE_FC_PORTS = ['0987654321234', '123456789000987']
    FAKE_ISCSI_PORTS = ['10.10.10.10', '10.10.10.11']

    volume = {'name': VOLUME_NAME,
              'id': VOLUME_ID,
              'display_name': 'Foo Volume',
              'size': 2,
              'host': FAKE_HOST,
              'volume_type': None,
              'volume_type_id': None}

    snapshot = {'name': SNAPSHOT_NAME,
                'id': SNAPSHOT_ID,
                'user_id': USER_ID,
                'project_id': PROJECT_ID,
                'volume_id': VOLUME_ID_SNAP,
                'volume_name': VOLUME_NAME,
                'status': 'creating',
                'progress': '0%',
                'volume_size': 2,
                'display_name': 'fakesnap',
                'display_description': FAKE_DESC}

    connector = {'ip': '10.0.0.2',
                 'initiator': 'iqn.1993-08.org.debian:01:222',
                 'wwpns': ["123456789012345", "123456789054321"],
                 'wwnns': ["223456789012345", "223456789054321"],
                 'host': 'fakehost'}

    def fake_create_client(self):
        return FakeHP3ParClient(FLAGS.hp3par_api_url)

    def fake_get_3par_host(self, hostname):
        if hostname not in self._hosts:
            msg = {'code': 'NON_EXISTENT_HOST',
                   'desc': "HOST '%s' was not found" % hostname}
            raise hpexceptions.HTTPNotFound(msg)
        else:
            return self._hosts[hostname]

    def fake_delete_3par_host(self, hostname):
        if hostname not in self._hosts:
            msg = {'code': 'NON_EXISTENT_HOST',
                   'desc': "HOST '%s' was not found" % hostname}
            raise hpexceptions.HTTPNotFound(msg)
        else:
            self._hosts[hostname] = None

    def fake_create_3par_vlun(self, volume, hostname):
        self.driver.client.createVLUN(volume, 19, hostname)

    def fake_get_ports(self):
        return {'FC': self.FAKE_FC_PORTS, 'iSCSI': self.FAKE_ISCSI_PORTS}

    def fake_copy_volume(self, src_name, dest_name):
        pass

    def fake_get_volume_state(self, vol_name):
        return "normal"

    def test_delete_volume(self):
        self.flags(lock_path=self.tempdir)
        self.driver.delete_volume(self.volume)
        self.assertRaises(hpexceptions.HTTPNotFound,
                          self.driver.client.getVolume,
                          self.VOLUME_ID)

    def test_create_snapshot(self):
        self.flags(lock_path=self.tempdir)
        self.driver.create_snapshot(self.snapshot)

        # check to see if the snapshot was created
        snap_vol = self.driver.client.getVolume(self.SNAPSHOT_3PAR_NAME)
        self.assertEqual(snap_vol['name'], self.SNAPSHOT_3PAR_NAME)

    def test_delete_snapshot(self):
        self.flags(lock_path=self.tempdir)
        self.driver.delete_snapshot(self.snapshot)

        # the snapshot should be deleted now
        self.assertRaises(hpexceptions.HTTPNotFound,
                          self.driver.client.getVolume,
                          self.SNAPSHOT_3PAR_NAME)

    def test_create_volume_from_snapshot(self):
        self.flags(lock_path=self.tempdir)
        self.driver.create_volume_from_snapshot(self.volume, self.snapshot)

        snap_vol = self.driver.client.getVolume(self.SNAPSHOT_3PAR_NAME)
        self.assertEqual(snap_vol['name'], self.SNAPSHOT_3PAR_NAME)

        volume = self.volume.copy()
        volume['size'] = 1
        self.assertRaises(exception.InvalidInput,
                          self.driver.create_volume_from_snapshot,
                          volume, self.snapshot)

    def test_terminate_connection(self):
        self.flags(lock_path=self.tempdir)
        self.driver.terminate_connection(self.volume, self.connector, True)
        # vlun should be gone.
        self.assertRaises(hpexceptions.HTTPNotFound,
                          self.driver.client.getVLUN,
                          self.VOLUME_3PAR_NAME)


class TestHP3PARFCDriver(HP3PARBaseDriver, test.TestCase):

    _hosts = {}

    def setUp(self):
        self.tempdir = tempfile.mkdtemp()
        super(TestHP3PARFCDriver, self).setUp()
        self.flags(
            hp3par_username='testUser',
            hp3par_password='testPassword',
            hp3par_api_url='https://1.1.1.1/api/v1',
            hp3par_domain=HP3PAR_DOMAIN,
            hp3par_cpg=HP3PAR_CPG,
            hp3par_cpg_snap=HP3PAR_CPG_SNAP,
            iscsi_ip_address='1.1.1.2',
            iscsi_port='1234',
            san_ip='2.2.2.2',
            san_login='test',
            san_password='test'
        )
        self.stubs.Set(hpfcdriver.HP3PARFCDriver, "_create_client",
                       self.fake_create_client)
        self.stubs.Set(hpfcdriver.HP3PARFCDriver,
                       "_create_3par_fibrechan_host",
                       self.fake_create_3par_fibrechan_host)

        self.stubs.Set(hpfcdriver.HP3PARCommon, "_get_3par_host",
                       self.fake_get_3par_host)
        self.stubs.Set(hpfcdriver.HP3PARCommon, "_delete_3par_host",
                       self.fake_delete_3par_host)
        self.stubs.Set(hpdriver.HP3PARCommon, "_create_3par_vlun",
                       self.fake_create_3par_vlun)
        self.stubs.Set(hpdriver.HP3PARCommon, "get_ports",
                       self.fake_get_ports)

        self.driver = hpfcdriver.HP3PARFCDriver()
        self.driver.do_setup(None)

    def tearDown(self):
        shutil.rmtree(self.tempdir)
        super(TestHP3PARFCDriver, self).tearDown()

    def fake_create_3par_fibrechan_host(self, hostname, wwn,
                                        domain, persona_id):
        host = {'FCPaths': [{'driverVersion': None,
                             'firmwareVersion': None,
                             'hostSpeed': 0,
                             'model': None,
                             'portPos': {'cardPort': 1, 'node': 1,
                                         'slot': 2},
                             'vendor': None,
                             'wwn': wwn[0]},
                            {'driverVersion': None,
                             'firmwareVersion': None,
                             'hostSpeed': 0,
                             'model': None,
                             'portPos': {'cardPort': 1, 'node': 0,
                                         'slot': 2},
                             'vendor': None,
                             'wwn': wwn[1]}],
                'descriptors': None,
                'domain': domain,
                'iSCSIPaths': [],
                'id': 11,
                'name': hostname}
        self._hosts[hostname] = host

        self.properties = {'data':
                          {'target_discovered': True,
                           'target_lun': 186,
                           'target_portal': '1.1.1.2:1234'},
                           'driver_volume_type': 'fibre_channel'}

    def test_create_volume(self):
        self.flags(lock_path=self.tempdir)
        model_update = self.driver.create_volume(self.volume)
        metadata = model_update['metadata']
        self.assertFalse(metadata['3ParName'] is None)
        self.assertEqual(metadata['CPG'], HP3PAR_CPG)
        self.assertEqual(metadata['snapCPG'], HP3PAR_CPG_SNAP)

    def test_initialize_connection(self):
        self.flags(lock_path=self.tempdir)
        result = self.driver.initialize_connection(self.volume, self.connector)
        self.assertEqual(result['driver_volume_type'], 'fibre_channel')

        # we should have a host and a vlun now.
        host = self.fake_get_3par_host(self.FAKE_HOST)
        self.assertEquals(self.FAKE_HOST, host['name'])
        self.assertEquals(HP3PAR_DOMAIN, host['domain'])
        vlun = self.driver.client.getVLUN(self.VOLUME_3PAR_NAME)

        self.assertEquals(self.VOLUME_3PAR_NAME, vlun['volumeName'])
        self.assertEquals(self.FAKE_HOST, vlun['hostname'])

    def test_create_cloned_volume(self):
        self.flags(lock_path=self.tempdir)
        self.stubs.Set(hpdriver.HP3PARCommon, "_get_volume_state",
                       self.fake_get_volume_state)
        self.stubs.Set(hpdriver.HP3PARCommon, "_copy_volume",
                       self.fake_copy_volume)
        self.state_tries = 0
        volume = {'name': HP3PARBaseDriver.VOLUME_NAME,
                  'id': HP3PARBaseDriver.CLONE_ID,
                  'display_name': 'Foo Volume',
                  'size': 2,
                  'host': HP3PARBaseDriver.FAKE_HOST,
                  'source_volid': HP3PARBaseDriver.VOLUME_ID}
        src_vref = {}
        model_update = self.driver.create_cloned_volume(volume, src_vref)
        self.assertTrue(model_update is not None)
        metadata = model_update['metadata']
        self.assertFalse(metadata['3ParName'] is None)
        self.assertEqual(metadata['CPG'], HP3PAR_CPG)
        self.assertEqual(metadata['snapCPG'], HP3PAR_CPG_SNAP)

    def test_get_volume_stats(self):
        self.flags(lock_path=self.tempdir)
        stats = self.driver.get_volume_stats(True)
        self.assertEquals(stats['storage_protocol'], 'FC')
        self.assertEquals(stats['volume_backend_name'], 'HP3PARFCDriver')


class TestHP3PARISCSIDriver(HP3PARBaseDriver, test.TestCase):

    TARGET_IQN = "iqn.2000-05.com.3pardata:21810002ac00383d"

    _hosts = {}

    def setUp(self):
        self.tempdir = tempfile.mkdtemp()
        super(TestHP3PARISCSIDriver, self).setUp()
        self.flags(
            hp3par_username='testUser',
            hp3par_password='testPassword',
            hp3par_api_url='https://1.1.1.1/api/v1',
            hp3par_domain=HP3PAR_DOMAIN,
            hp3par_cpg=HP3PAR_CPG,
            hp3par_cpg_snap=HP3PAR_CPG_SNAP,
            iscsi_ip_address='1.1.1.2',
            iscsi_port='1234',
            san_ip='2.2.2.2',
            san_login='test',
            san_password='test'
        )
        self.stubs.Set(hpdriver.HP3PARISCSIDriver, "_create_client",
                       self.fake_create_client)
        self.stubs.Set(hpdriver.HP3PARISCSIDriver,
                       "_iscsi_discover_target_iqn",
                       self.fake_iscsi_discover_target_iqn)
        self.stubs.Set(hpdriver.HP3PARISCSIDriver, "_create_3par_iscsi_host",
                       self.fake_create_3par_iscsi_host)
        self.stubs.Set(hpdriver.HP3PARISCSIDriver,
                       "_iscsi_discover_target_iqn",
                       self.fake_iscsi_discover_target_iqn)

        self.stubs.Set(hpdriver.HP3PARCommon, "_get_3par_host",
                       self.fake_get_3par_host)
        self.stubs.Set(hpdriver.HP3PARCommon, "_delete_3par_host",
                       self.fake_delete_3par_host)
        self.stubs.Set(hpdriver.HP3PARCommon, "_create_3par_vlun",
                       self.fake_create_3par_vlun)

        self.driver = hpdriver.HP3PARISCSIDriver()
        self.driver.do_setup(None)

        target_iqn = 'iqn.2000-05.com.3pardata:21810002ac00383d'
        self.properties = {'data':
                          {'target_discovered': True,
                           'target_iqn': target_iqn,
                           'target_lun': 186,
                           'target_portal': '1.1.1.2:1234'},
                           'driver_volume_type': 'iscsi'}

    def tearDown(self):
        shutil.rmtree(self.tempdir)
        super(TestHP3PARISCSIDriver, self).tearDown()

    def fake_iscsi_discover_target_iqn(self, ip_address):
        return self.TARGET_IQN

    def fake_create_3par_iscsi_host(self, hostname, iscsi_iqn,
                                    domain, persona_id):
        host = {'FCPaths': [],
                'descriptors': None,
                'domain': domain,
                'iSCSIPaths': [{'driverVersion': None,
                                'firmwareVersion': None,
                                'hostSpeed': 0,
                                'ipAddr': '10.10.221.59',
                                'model': None,
                                'name': iscsi_iqn,
                                'portPos': {'cardPort': 1, 'node': 1,
                                            'slot': 8},
                                'vendor': None}],
                'id': 11,
                'name': hostname}
        self._hosts[hostname] = host

    def fake_iscsi_discover_target_iqn(self, remote_ip):
        return 'iqn.2000-05.com.3pardata:21810002ac00383d'

    def test_create_volume(self):
        self.flags(lock_path=self.tempdir)
        model_update = self.driver.create_volume(self.volume)
        metadata = model_update['metadata']
        self.assertFalse(metadata['3ParName'] is None)
        self.assertEqual(metadata['CPG'], HP3PAR_CPG)
        self.assertEqual(metadata['snapCPG'], HP3PAR_CPG_SNAP)
        expected_location = "%s:%s" % (FLAGS.iscsi_ip_address,
                                       FLAGS.iscsi_port)
        self.assertEqual(model_update['provider_location'], expected_location)

    def test_initialize_connection(self):
        self.flags(lock_path=self.tempdir)
        result = self.driver.initialize_connection(self.volume, self.connector)
        self.assertEqual(result['driver_volume_type'], 'iscsi')
        self.assertEqual(result['data']['target_iqn'],
                         self.properties['data']['target_iqn'])
        self.assertEqual(result['data']['target_portal'],
                         self.properties['data']['target_portal'])
        self.assertEqual(result['data']['target_discovered'],
                         self.properties['data']['target_discovered'])

        # we should have a host and a vlun now.
        host = self.fake_get_3par_host(self.FAKE_HOST)
        self.assertEquals(self.FAKE_HOST, host['name'])
        self.assertEquals(HP3PAR_DOMAIN, host['domain'])
        vlun = self.driver.client.getVLUN(self.VOLUME_3PAR_NAME)

        self.assertEquals(self.VOLUME_3PAR_NAME, vlun['volumeName'])
        self.assertEquals(self.FAKE_HOST, vlun['hostname'])

    def test_create_cloned_volume(self):
        self.flags(lock_path=self.tempdir)
        self.stubs.Set(hpdriver.HP3PARCommon, "_get_volume_state",
                       self.fake_get_volume_state)
        self.stubs.Set(hpdriver.HP3PARCommon, "_copy_volume",
                       self.fake_copy_volume)
        self.state_tries = 0
        volume = {'name': HP3PARBaseDriver.VOLUME_NAME,
                  'id': HP3PARBaseDriver.CLONE_ID,
                  'display_name': 'Foo Volume',
                  'size': 2,
                  'host': HP3PARBaseDriver.FAKE_HOST,
                  'source_volid': HP3PARBaseDriver.VOLUME_ID}
        src_vref = {}
        model_update = self.driver.create_cloned_volume(volume, src_vref)
        self.assertTrue(model_update is not None)
        metadata = model_update['metadata']
        self.assertFalse(metadata['3ParName'] is None)
        self.assertEqual(metadata['CPG'], HP3PAR_CPG)
        self.assertEqual(metadata['snapCPG'], HP3PAR_CPG_SNAP)

    def test_get_volume_stats(self):
        self.flags(lock_path=self.tempdir)
        stats = self.driver.get_volume_stats(True)
        self.assertEquals(stats['storage_protocol'], 'iSCSI')
        self.assertEquals(stats['volume_backend_name'], 'HP3PARISCSIDriver')
