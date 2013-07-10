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
import mox
import shutil
import tempfile

from hp3parclient import exceptions as hpexceptions

from cinder import exception
from cinder.openstack.common import log as logging
from cinder import test
from cinder.volume import configuration as conf
from cinder.volume.drivers.san.hp import hp_3par_fc as hpfcdriver
from cinder.volume.drivers.san.hp import hp_3par_iscsi as hpdriver

LOG = logging.getLogger(__name__)

HP3PAR_DOMAIN = 'OpenStack',
HP3PAR_CPG = 'OpenStackCPG',
HP3PAR_CPG_SNAP = 'OpenStackCPGSnap'
CLI_CR = '\r\n'


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
        self.volumes = []
        self.hosts = []
        self.vluns = []

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

    def createCPG(self, name, optional=None):
        cpg = {'SAGrowth': {'LDLayout': {'diskPatterns': [{'diskType': 2}]},
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
               'id': 1,
               'name': name,
               'numFPVVs': 2,
               'numTPVVs': 0,
               'state': 1,
               'uuid': '29c214aa-62b9-41c8-b198-000000000000'}

        new_cpg = cpg.copy()
        new_cpg.update(optional)
        self.cpgs.append(new_cpg)

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

    def deleteCPG(self, name):
        cpg = self.getCPG(name)
        self.cpgs.remove(cpg)

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
    FAKE_ISCSI_PORTS = {'1.1.1.2': {'nsp': '8:1:1',
                                    'iqn': ('iqn.2000-05.com.3pardata:'
                                            '21810002ac00383d'),
                                    'ip_port': '3262'}}

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

    def setup_configuration(self):
        configuration = mox.MockObject(conf.Configuration)
        configuration.hp3par_debug = False
        configuration.hp3par_username = 'testUser'
        configuration.hp3par_password = 'testPassword'
        configuration.hp3par_api_url = 'https://1.1.1.1/api/v1'
        configuration.hp3par_domain = HP3PAR_DOMAIN
        configuration.hp3par_cpg = HP3PAR_CPG
        configuration.hp3par_cpg_snap = HP3PAR_CPG_SNAP
        configuration.iscsi_ip_address = '1.1.1.2'
        configuration.iscsi_port = '1234'
        configuration.san_ip = '2.2.2.2'
        configuration.san_login = 'test'
        configuration.san_password = 'test'
        configuration.hp3par_snapshot_expiration = ""
        configuration.hp3par_snapshot_retention = ""
        configuration.hp3par_iscsi_ips = []
        return configuration

    def setup_fakes(self):
        self.stubs.Set(hpdriver.hpcommon.HP3PARCommon, "_create_client",
                       self.fake_create_client)
        self.stubs.Set(hpdriver.hpcommon.HP3PARCommon, "_get_3par_host",
                       self.fake_get_3par_host)
        self.stubs.Set(hpdriver.hpcommon.HP3PARCommon, "_delete_3par_host",
                       self.fake_delete_3par_host)
        self.stubs.Set(hpdriver.hpcommon.HP3PARCommon, "_create_3par_vlun",
                       self.fake_create_3par_vlun)
        self.stubs.Set(hpdriver.hpcommon.HP3PARCommon, "get_ports",
                       self.fake_get_ports)
        self.stubs.Set(hpfcdriver.hpcommon.HP3PARCommon, "get_domain",
                       self.fake_get_domain)

    def clear_mox(self):
        self.mox.ResetAll()
        self.stubs.UnsetAll()

    def fake_create_client(self):
        return FakeHP3ParClient(self.driver.configuration.hp3par_api_url)

    def fake_get_domain(self, cpg):
        return HP3PAR_DOMAIN

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
            del self._hosts[hostname]

    def fake_create_3par_vlun(self, volume, hostname):
        self.driver.common.client.createVLUN(volume, 19, hostname)

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
                          self.driver.common.client.getVolume,
                          self.VOLUME_ID)

    def test_create_snapshot(self):
        self.flags(lock_path=self.tempdir)
        self.driver.create_snapshot(self.snapshot)

        # check to see if the snapshot was created
        snap_vol = self.driver.common.client.getVolume(self.SNAPSHOT_3PAR_NAME)
        self.assertEqual(snap_vol['name'], self.SNAPSHOT_3PAR_NAME)

    def test_delete_snapshot(self):
        self.flags(lock_path=self.tempdir)

        self.driver.create_snapshot(self.snapshot)
        #make sure it exists first
        vol = self.driver.common.client.getVolume(self.SNAPSHOT_3PAR_NAME)
        self.assertEqual(vol['name'], self.SNAPSHOT_3PAR_NAME)
        self.driver.delete_snapshot(self.snapshot)

        # the snapshot should be deleted now
        self.assertRaises(hpexceptions.HTTPNotFound,
                          self.driver.common.client.getVolume,
                          self.SNAPSHOT_3PAR_NAME)

    def test_create_volume_from_snapshot(self):
        self.flags(lock_path=self.tempdir)
        self.driver.create_volume_from_snapshot(self.volume, self.snapshot)

        snap_vol = self.driver.common.client.getVolume(self.VOLUME_3PAR_NAME)
        self.assertEqual(snap_vol['name'], self.VOLUME_3PAR_NAME)

        volume = self.volume.copy()
        volume['size'] = 1
        self.assertRaises(exception.InvalidInput,
                          self.driver.create_volume_from_snapshot,
                          volume, self.snapshot)

    def test_terminate_connection(self):
        self.flags(lock_path=self.tempdir)
        #setup the connections
        self.driver.initialize_connection(self.volume, self.connector)
        vlun = self.driver.common.client.getVLUN(self.VOLUME_3PAR_NAME)
        self.assertEqual(vlun['volumeName'], self.VOLUME_3PAR_NAME)
        self.driver.terminate_connection(self.volume, self.connector,
                                         force=True)
        # vlun should be gone.
        self.assertRaises(hpexceptions.HTTPNotFound,
                          self.driver.common.client.getVLUN,
                          self.VOLUME_3PAR_NAME)


class TestHP3PARFCDriver(HP3PARBaseDriver, test.TestCase):

    _hosts = {}

    def setUp(self):
        self.tempdir = tempfile.mkdtemp()
        super(TestHP3PARFCDriver, self).setUp()
        self.setup_driver(self.setup_configuration())
        self.setup_fakes()

    def setup_fakes(self):
        super(TestHP3PARFCDriver, self).setup_fakes()
        self.stubs.Set(hpfcdriver.HP3PARFCDriver,
                       "_create_3par_fibrechan_host",
                       self.fake_create_3par_fibrechan_host)

    def tearDown(self):
        shutil.rmtree(self.tempdir)
        super(TestHP3PARFCDriver, self).tearDown()

    def setup_driver(self, configuration):
        self.driver = hpfcdriver.HP3PARFCDriver(configuration=configuration)

        self.stubs.Set(hpdriver.hpcommon.HP3PARCommon, "_create_client",
                       self.fake_create_client)
        self.driver.do_setup(None)

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
        return hostname

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
        vlun = self.driver.common.client.getVLUN(self.VOLUME_3PAR_NAME)

        self.assertEquals(self.VOLUME_3PAR_NAME, vlun['volumeName'])
        self.assertEquals(self.FAKE_HOST, vlun['hostname'])

    def test_create_cloned_volume(self):
        self.flags(lock_path=self.tempdir)
        self.stubs.Set(hpdriver.hpcommon.HP3PARCommon, "_get_volume_state",
                       self.fake_get_volume_state)
        self.stubs.Set(hpdriver.hpcommon.HP3PARCommon, "_copy_volume",
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

        def fake_safe_get(*args):
            return "HP3PARFCDriver"

        self.stubs.Set(self.driver.configuration, 'safe_get', fake_safe_get)
        stats = self.driver.get_volume_stats(True)
        self.assertEquals(stats['storage_protocol'], 'FC')
        self.assertEquals(stats['total_capacity_gb'], 'infinite')
        self.assertEquals(stats['free_capacity_gb'], 'infinite')

        #modify the CPG to have a limit
        old_cpg = self.driver.common.client.getCPG(HP3PAR_CPG)
        options = {'SDGrowth': {'limitMiB': 8192}}
        self.driver.common.client.deleteCPG(HP3PAR_CPG)
        self.driver.common.client.createCPG(HP3PAR_CPG, options)

        const = 0.0009765625
        stats = self.driver.get_volume_stats(True)
        self.assertEquals(stats['storage_protocol'], 'FC')
        total_capacity_gb = 8192 * const
        self.assertEquals(stats['total_capacity_gb'], total_capacity_gb)
        free_capacity_gb = int((8192 - old_cpg['UsrUsage']['usedMiB']) * const)
        self.assertEquals(stats['free_capacity_gb'], free_capacity_gb)
        self.driver.common.client.deleteCPG(HP3PAR_CPG)
        self.driver.common.client.createCPG(HP3PAR_CPG, {})

    def test_create_host(self):
        self.flags(lock_path=self.tempdir)

        #record
        self.clear_mox()
        self.stubs.Set(hpfcdriver.hpcommon.HP3PARCommon, "get_domain",
                       self.fake_get_domain)
        _run_ssh = self.mox.CreateMock(hpdriver.hpcommon.HP3PARCommon._run_ssh)
        self.stubs.Set(hpdriver.hpcommon.HP3PARCommon, "_run_ssh", _run_ssh)

        show_host_cmd = 'showhost -verbose fakehost'
        _run_ssh(show_host_cmd, False).AndReturn([pack('no hosts listed'), ''])

        create_host_cmd = ('createhost -persona 1 -domain (\'OpenStack\',) '
                           'fakehost 123456789012345 123456789054321')
        _run_ssh(create_host_cmd, False).AndReturn([CLI_CR, ''])

        _run_ssh(show_host_cmd, False).AndReturn([pack(FC_HOST_RET), ''])
        self.mox.ReplayAll()

        host = self.driver._create_host(self.volume, self.connector)
        self.assertEqual(host['name'], self.FAKE_HOST)

    def test_create_invalid_host(self):
        self.flags(lock_path=self.tempdir)

        #record
        self.clear_mox()
        self.stubs.Set(hpdriver.hpcommon.HP3PARCommon, "get_domain",
                       self.fake_get_domain)
        _run_ssh = self.mox.CreateMock(hpdriver.hpcommon.HP3PARCommon._run_ssh)
        self.stubs.Set(hpdriver.hpcommon.HP3PARCommon, "_run_ssh", _run_ssh)

        show_host_cmd = 'showhost -verbose fakehost'
        _run_ssh(show_host_cmd, False).AndReturn([pack('no hosts listed'), ''])

        create_host_cmd = ('createhost -persona 1 -domain (\'OpenStack\',) '
                           'fakehost 123456789012345 123456789054321')
        create_host_ret = pack(CLI_CR +
                               'already used by host fakehost.foo (19)')
        _run_ssh(create_host_cmd, False).AndReturn([create_host_ret, ''])

        show_3par_cmd = 'showhost -verbose fakehost.foo'
        _run_ssh(show_3par_cmd, False).AndReturn([pack(FC_SHOWHOST_RET), ''])
        self.mox.ReplayAll()

        host = self.driver._create_host(self.volume, self.connector)

        self.assertEquals(host['name'], 'fakehost.foo')

    def test_create_modify_host(self):
        self.flags(lock_path=self.tempdir)

        #record
        self.clear_mox()
        self.stubs.Set(hpdriver.hpcommon.HP3PARCommon, "get_domain",
                       self.fake_get_domain)
        _run_ssh = self.mox.CreateMock(hpdriver.hpcommon.HP3PARCommon._run_ssh)
        self.stubs.Set(hpdriver.hpcommon.HP3PARCommon, "_run_ssh", _run_ssh)

        show_host_cmd = 'showhost -verbose fakehost'
        _run_ssh(show_host_cmd, False).AndReturn([pack(NO_FC_HOST_RET), ''])

        create_host_cmd = ('createhost -add fakehost '
                           '123456789012345 123456789054321')
        _run_ssh(create_host_cmd, False).AndReturn([CLI_CR, ''])

        show_host_cmd = 'showhost -verbose fakehost'
        _run_ssh(show_host_cmd, False).AndReturn([pack(FC_HOST_RET), ''])
        self.mox.ReplayAll()

        host = self.driver._create_host(self.volume, self.connector)
        self.assertEqual(host['name'], self.FAKE_HOST)


class TestHP3PARISCSIDriver(HP3PARBaseDriver, test.TestCase):

    TARGET_IQN = "iqn.2000-05.com.3pardata:21810002ac00383d"

    _hosts = {}

    def setUp(self):
        self.tempdir = tempfile.mkdtemp()
        super(TestHP3PARISCSIDriver, self).setUp()
        self.setup_driver(self.setup_configuration())
        self.setup_fakes()

    def setup_fakes(self):
        super(TestHP3PARISCSIDriver, self).setup_fakes()

        self.stubs.Set(hpdriver.HP3PARISCSIDriver, "_create_3par_iscsi_host",
                       self.fake_create_3par_iscsi_host)

        #target_iqn = 'iqn.2000-05.com.3pardata:21810002ac00383d'
        self.properties = {'data':
                          {'target_discovered': True,
                           'target_iqn': self.TARGET_IQN,
                           'target_lun': 186,
                           'target_portal': '1.1.1.2:1234'},
                           'driver_volume_type': 'iscsi'}

    def tearDown(self):
        shutil.rmtree(self.tempdir)
        self._hosts = {}
        super(TestHP3PARISCSIDriver, self).tearDown()

    def setup_driver(self, configuration, set_up_fakes=True):
        self.driver = hpdriver.HP3PARISCSIDriver(configuration=configuration)

        self.stubs.Set(hpdriver.hpcommon.HP3PARCommon, "_create_client",
                       self.fake_create_client)

        if set_up_fakes:
            self.stubs.Set(hpdriver.hpcommon.HP3PARCommon, "get_ports",
                           self.fake_get_ports)

        self.driver.do_setup(None)

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
        return hostname

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
        vlun = self.driver.common.client.getVLUN(self.VOLUME_3PAR_NAME)

        self.assertEquals(self.VOLUME_3PAR_NAME, vlun['volumeName'])
        self.assertEquals(self.FAKE_HOST, vlun['hostname'])

    def test_create_cloned_volume(self):
        self.flags(lock_path=self.tempdir)
        self.stubs.Set(hpdriver.hpcommon.HP3PARCommon, "_get_volume_state",
                       self.fake_get_volume_state)
        self.stubs.Set(hpdriver.hpcommon.HP3PARCommon, "_copy_volume",
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

        def fake_safe_get(*args):
            return "HP3PARFCDriver"

        self.stubs.Set(self.driver.configuration, 'safe_get', fake_safe_get)
        stats = self.driver.get_volume_stats(True)
        self.assertEquals(stats['storage_protocol'], 'iSCSI')
        self.assertEquals(stats['total_capacity_gb'], 'infinite')
        self.assertEquals(stats['free_capacity_gb'], 'infinite')

        #modify the CPG to have a limit
        old_cpg = self.driver.common.client.getCPG(HP3PAR_CPG)
        options = {'SDGrowth': {'limitMiB': 8192}}
        self.driver.common.client.deleteCPG(HP3PAR_CPG)
        self.driver.common.client.createCPG(HP3PAR_CPG, options)

        const = 0.0009765625
        stats = self.driver.get_volume_stats(True)
        self.assertEquals(stats['storage_protocol'], 'iSCSI')
        total_capacity_gb = 8192 * const
        self.assertEquals(stats['total_capacity_gb'], total_capacity_gb)
        free_capacity_gb = int((8192 - old_cpg['UsrUsage']['usedMiB']) * const)
        self.assertEquals(stats['free_capacity_gb'], free_capacity_gb)
        self.driver.common.client.deleteCPG(HP3PAR_CPG)
        self.driver.common.client.createCPG(HP3PAR_CPG, {})

    def test_create_host(self):
        self.flags(lock_path=self.tempdir)

        #record
        self.clear_mox()
        self.stubs.Set(hpdriver.hpcommon.HP3PARCommon, "get_domain",
                       self.fake_get_domain)
        _run_ssh = self.mox.CreateMock(hpdriver.hpcommon.HP3PARCommon._run_ssh)
        self.stubs.Set(hpdriver.hpcommon.HP3PARCommon, "_run_ssh", _run_ssh)

        show_host_cmd = 'showhost -verbose fakehost'
        _run_ssh(show_host_cmd, False).AndReturn([pack('no hosts listed'), ''])

        create_host_cmd = ('createhost -iscsi -persona 1 -domain '
                           '(\'OpenStack\',) '
                           'fakehost iqn.1993-08.org.debian:01:222')
        _run_ssh(create_host_cmd, False).AndReturn([CLI_CR, ''])

        _run_ssh(show_host_cmd, False).AndReturn([pack(ISCSI_HOST_RET), ''])
        self.mox.ReplayAll()

        host = self.driver._create_host(self.volume, self.connector)
        self.assertEqual(host['name'], self.FAKE_HOST)

    def test_create_invalid_host(self):
        self.flags(lock_path=self.tempdir)

        #record
        self.clear_mox()
        self.stubs.Set(hpdriver.hpcommon.HP3PARCommon, "get_domain",
                       self.fake_get_domain)
        _run_ssh = self.mox.CreateMock(hpdriver.hpcommon.HP3PARCommon._run_ssh)
        self.stubs.Set(hpdriver.hpcommon.HP3PARCommon, "_run_ssh", _run_ssh)

        show_host_cmd = 'showhost -verbose fakehost'
        _run_ssh(show_host_cmd, False).AndReturn([pack('no hosts listed'), ''])

        create_host_cmd = ('createhost -iscsi -persona 1 -domain '
                           '(\'OpenStack\',) '
                           'fakehost iqn.1993-08.org.debian:01:222')
        in_use_ret = pack('\r\nalready used by host fakehost.foo ')
        _run_ssh(create_host_cmd, False).AndReturn([in_use_ret, ''])

        show_3par_cmd = 'showhost -verbose fakehost.foo'
        _run_ssh(show_3par_cmd, False).AndReturn([pack(ISCSI_3PAR_RET), ''])
        self.mox.ReplayAll()

        host = self.driver._create_host(self.volume, self.connector)

        self.assertEquals(host['name'], 'fakehost.foo')

    def test_create_modify_host(self):
        self.flags(lock_path=self.tempdir)

        #record
        self.clear_mox()
        self.stubs.Set(hpdriver.hpcommon.HP3PARCommon, "get_domain",
                       self.fake_get_domain)
        _run_ssh = self.mox.CreateMock(hpdriver.hpcommon.HP3PARCommon._run_ssh)
        self.stubs.Set(hpdriver.hpcommon.HP3PARCommon, "_run_ssh", _run_ssh)

        show_host_cmd = 'showhost -verbose fakehost'
        _run_ssh(show_host_cmd, False).AndReturn([pack(ISCSI_NO_HOST_RET), ''])

        create_host_cmd = ('createhost -iscsi -add fakehost '
                           'iqn.1993-08.org.debian:01:222')
        _run_ssh(create_host_cmd, False).AndReturn([CLI_CR, ''])
        _run_ssh(show_host_cmd, False).AndReturn([pack(ISCSI_HOST_RET), ''])
        self.mox.ReplayAll()

        host = self.driver._create_host(self.volume, self.connector)
        self.assertEqual(host['name'], self.FAKE_HOST)

    def test_get_volume_state(self):
        self.flags(lock_path=self.tempdir)

        #record
        self.clear_mox()
        _run_ssh = self.mox.CreateMock(hpdriver.hpcommon.HP3PARCommon._run_ssh)
        self.stubs.Set(hpdriver.hpcommon.HP3PARCommon, "_run_ssh", _run_ssh)

        show_vv_cmd = ('showvv -state '
                       'volume-d03338a9-9115-48a3-8dfc-35cdfcdc15a7')
        _run_ssh(show_vv_cmd, False).AndReturn([pack(VOLUME_STATE_RET), ''])
        self.mox.ReplayAll()

        status = self.driver.common._get_volume_state(self.VOLUME_NAME)
        self.assertEqual(status, 'normal')

    def test_get_ports(self):
        self.flags(lock_path=self.tempdir)

        #record
        self.clear_mox()
        _run_ssh = self.mox.CreateMock(hpdriver.hpcommon.HP3PARCommon._run_ssh)
        self.stubs.Set(hpdriver.hpcommon.HP3PARCommon, "_run_ssh", _run_ssh)

        show_port_cmd = 'showport'
        _run_ssh(show_port_cmd, False).AndReturn([pack(PORT_RET), ''])

        show_port_i_cmd = 'showport -iscsi'
        _run_ssh(show_port_i_cmd, False).AndReturn([pack(READY_ISCSI_PORT_RET),
                                                    ''])

        show_port_i_cmd = 'showport -iscsiname'
        _run_ssh(show_port_i_cmd, False).AndReturn([pack(SHOW_PORT_ISCSI),
                                                    ''])
        self.mox.ReplayAll()

        ports = self.driver.common.get_ports()
        self.assertEqual(ports['FC'][0], '20210002AC00383D')
        self.assertEqual(ports['iSCSI']['10.10.120.252']['nsp'], '0:8:2')

    def test_get_iscsi_ip_active(self):
        self.flags(lock_path=self.tempdir)

        #record set up
        self.clear_mox()
        _run_ssh = self.mox.CreateMock(hpdriver.hpcommon.HP3PARCommon._run_ssh)
        self.stubs.Set(hpdriver.hpcommon.HP3PARCommon, "_run_ssh", _run_ssh)

        show_port_cmd = 'showport'
        _run_ssh(show_port_cmd, False).AndReturn([pack(PORT_RET), ''])

        show_port_i_cmd = 'showport -iscsi'
        _run_ssh(show_port_i_cmd, False).AndReturn([pack(READY_ISCSI_PORT_RET),
                                                    ''])

        show_port_i_cmd = 'showport -iscsiname'
        _run_ssh(show_port_i_cmd, False).AndReturn([pack(SHOW_PORT_ISCSI), ''])

        self.mox.ReplayAll()

        config = self.setup_configuration()
        config.hp3par_iscsi_ips = ['10.10.220.253', '10.10.220.252']
        self.setup_driver(config, set_up_fakes=False)

        #record
        self.clear_mox()
        _run_ssh = self.mox.CreateMock(hpdriver.hpcommon.HP3PARCommon._run_ssh)
        self.stubs.Set(hpdriver.hpcommon.HP3PARCommon, "_run_ssh", _run_ssh)

        show_vlun_cmd = 'showvlun -a -host fakehost'
        _run_ssh(show_vlun_cmd, False).AndReturn([pack(SHOW_VLUN), ''])

        self.mox.ReplayAll()

        ip = self.driver._get_iscsi_ip('fakehost')
        self.assertEqual(ip, '10.10.220.253')

    def test_get_iscsi_ip(self):
        self.flags(lock_path=self.tempdir)

        #record driver set up
        self.clear_mox()
        _run_ssh = self.mox.CreateMock(hpdriver.hpcommon.HP3PARCommon._run_ssh)
        self.stubs.Set(hpdriver.hpcommon.HP3PARCommon, "_run_ssh", _run_ssh)

        show_port_cmd = 'showport'
        _run_ssh(show_port_cmd, False).AndReturn([pack(PORT_RET), ''])

        show_port_i_cmd = 'showport -iscsi'
        _run_ssh(show_port_i_cmd, False).AndReturn([pack(READY_ISCSI_PORT_RET),
                                                    ''])

        show_port_i_cmd = 'showport -iscsiname'
        _run_ssh(show_port_i_cmd, False).AndReturn([pack(SHOW_PORT_ISCSI), ''])

        #record
        show_vlun_cmd = 'showvlun -a -host fakehost'
        show_vlun_ret = 'no vluns listed\r\n'
        _run_ssh(show_vlun_cmd, False).AndReturn([pack(show_vlun_ret), ''])
        show_vlun_cmd = 'showvlun -a -showcols Port'
        _run_ssh(show_vlun_cmd, False).AndReturn([pack(SHOW_VLUN_NONE), ''])

        self.mox.ReplayAll()

        config = self.setup_configuration()
        config.iscsi_ip_address = '10.10.10.10'
        config.hp3par_iscsi_ips = ['10.10.220.253', '10.10.220.252']
        self.setup_driver(config, set_up_fakes=False)

        ip = self.driver._get_iscsi_ip('fakehost')
        self.assertEqual(ip, '10.10.220.252')

    def test_invalid_iscsi_ip(self):
        self.flags(lock_path=self.tempdir)

        #record driver set up
        self.clear_mox()
        _run_ssh = self.mox.CreateMock(hpdriver.hpcommon.HP3PARCommon._run_ssh)
        self.stubs.Set(hpdriver.hpcommon.HP3PARCommon, "_run_ssh", _run_ssh)

        show_port_cmd = 'showport'
        _run_ssh(show_port_cmd, False).AndReturn([pack(PORT_RET), ''])

        show_port_i_cmd = 'showport -iscsi'
        _run_ssh(show_port_i_cmd, False).AndReturn([pack(READY_ISCSI_PORT_RET),
                                                    ''])

        show_port_i_cmd = 'showport -iscsiname'
        _run_ssh(show_port_i_cmd, False).AndReturn([pack(SHOW_PORT_ISCSI), ''])

        config = self.setup_configuration()
        config.hp3par_iscsi_ips = ['10.10.220.250', '10.10.220.251']
        config.iscsi_ip_address = '10.10.10.10'
        self.mox.ReplayAll()

        # no valid ip addr should be configured.
        self.assertRaises(exception.InvalidInput,
                          self.setup_driver,
                          config,
                          set_up_fakes=False)

    def test_get_least_used_nsp(self):
        self.flags(lock_path=self.tempdir)

        #record
        self.clear_mox()
        _run_ssh = self.mox.CreateMock(hpdriver.hpcommon.HP3PARCommon._run_ssh)
        self.stubs.Set(hpdriver.hpcommon.HP3PARCommon, "_run_ssh", _run_ssh)

        show_vlun_cmd = 'showvlun -a -showcols Port'
        _run_ssh(show_vlun_cmd, False).AndReturn([pack(SHOW_VLUN_NONE), ''])
        _run_ssh(show_vlun_cmd, False).AndReturn([pack(SHOW_VLUN_NONE), ''])
        _run_ssh(show_vlun_cmd, False).AndReturn([pack(SHOW_VLUN_NONE), ''])

        self.mox.ReplayAll()
        # in use count                           11       12
        nsp = self.driver._get_least_used_nsp(['0:2:1', '1:8:1'])
        self.assertEqual(nsp, '0:2:1')

        # in use count                            11       10
        nsp = self.driver._get_least_used_nsp(['0:2:1', '1:2:1'])
        self.assertEqual(nsp, '1:2:1')

        # in use count                            0       10
        nsp = self.driver._get_least_used_nsp(['1:1:1', '1:2:1'])
        self.assertEqual(nsp, '1:1:1')


def pack(arg):
    header = '\r\n\r\n\r\n\r\n\r\n'
    footer = '\r\n\r\n\r\n'
    return header + arg + footer

FC_HOST_RET = (
    'Id,Name,Persona,-WWN/iSCSI_Name-,Port,IP_addr\r\n'
    '75,fakehost,Generic,50014380242B8B4C,0:2:1,n/a\r\n'
    '75,fakehost,Generic,50014380242B8B4E,---,n/a\r\n'
    '75,fakehost,Generic,1000843497F90711,0:2:1,n/a \r\n'
    '75,fakehost,Generic,1000843497F90715,1:2:1,n/a\r\n'
    '\r\n'
    'Id,Name,-Initiator_CHAP_Name-,-Target_CHAP_Name-\r\n'
    '75,fakehost,--,--\r\n'
    '\r\n'
    '---------- Host fakehost ----------\r\n'
    'Name       : fakehost\r\n'
    'Domain     : FAKE_TEST\r\n'
    'Id         : 75\r\n'
    'Location   : --\r\n'
    'IP Address : --\r\n'
    'OS         : --\r\n'
    'Model      : --\r\n'
    'Contact    : --\r\n'
    'Comment    : --  \r\n\r\n\r\n')

FC_SHOWHOST_RET = (
    'Id,Name,Persona,-WWN/iSCSI_Name-,Port,IP_addr\r\n'
    '75,fakehost.foo,Generic,50014380242B8B4C,0:2:1,n/a\r\n'
    '75,fakehost.foo,Generic,50014380242B8B4E,---,n/a\r\n'
    '75,fakehost.foo,Generic,1000843497F90711,0:2:1,n/a \r\n'
    '75,fakehost.foo,Generic,1000843497F90715,1:2:1,n/a\r\n'
    '\r\n'
    'Id,Name,-Initiator_CHAP_Name-,-Target_CHAP_Name-\r\n'
    '75,fakehost.foo,--,--\r\n'
    '\r\n'
    '---------- Host fakehost.foo ----------\r\n'
    'Name       : fakehost.foo\r\n'
    'Domain     : FAKE_TEST\r\n'
    'Id         : 75\r\n'
    'Location   : --\r\n'
    'IP Address : --\r\n'
    'OS         : --\r\n'
    'Model      : --\r\n'
    'Contact    : --\r\n'
    'Comment    : --  \r\n\r\n\r\n')

NO_FC_HOST_RET = (
    'Id,Name,Persona,-WWN/iSCSI_Name-,Port,IP_addr\r\n'
    '\r\n'
    'Id,Name,-Initiator_CHAP_Name-,-Target_CHAP_Name-\r\n'
    '75,fakehost,--,--\r\n'
    '\r\n'
    '---------- Host fakehost ----------\r\n'
    'Name       : fakehost\r\n'
    'Domain     : FAKE_TEST\r\n'
    'Id         : 75\r\n'
    'Location   : --\r\n'
    'IP Address : --\r\n'
    'OS         : --\r\n'
    'Model      : --\r\n'
    'Contact    : --\r\n'
    'Comment    : --  \r\n\r\n\r\n')

ISCSI_HOST_RET = (
    'Id,Name,Persona,-WWN/iSCSI_Name-,Port,IP_addr\r\n'
    '75,fakehost,Generic,iqn.1993-08.org.debian:01:222,---,10.10.222.12\r\n'
    '\r\n'
    'Id,Name,-Initiator_CHAP_Name-,-Target_CHAP_Name-\r\n'
    '75,fakehost,--,--\r\n'
    '\r\n'
    '---------- Host fakehost ----------\r\n'
    'Name       : fakehost\r\n'
    'Domain     : FAKE_TEST\r\n'
    'Id         : 75\r\n'
    'Location   : --\r\n'
    'IP Address : --\r\n'
    'OS         : --\r\n'
    'Model      : --\r\n'
    'Contact    : --\r\n'
    'Comment    : --  \r\n\r\n\r\n')

ISCSI_NO_HOST_RET = (
    'Id,Name,Persona,-WWN/iSCSI_Name-,Port,IP_addr\r\n'
    '\r\n'
    'Id,Name,-Initiator_CHAP_Name-,-Target_CHAP_Name-\r\n'
    '75,fakehost,--,--\r\n'
    '\r\n'
    '---------- Host fakehost ----------\r\n'
    'Name       : fakehost\r\n'
    'Domain     : FAKE_TEST\r\n'
    'Id         : 75\r\n'
    'Location   : --\r\n'
    'IP Address : --\r\n'
    'OS         : --\r\n'
    'Model      : --\r\n'
    'Contact    : --\r\n'
    'Comment    : --  \r\n\r\n\r\n')

ISCSI_PORT_IDS_RET = (
    'N:S:P,-Node_WWN/IPAddr-,-----------Port_WWN/iSCSI_Name-----------\r\n'
    '0:2:1,28210002AC00383D,20210002AC00383D\r\n'
    '0:2:2,2FF70002AC00383D,20220002AC00383D\r\n'
    '0:2:3,2FF70002AC00383D,20230002AC00383D\r\n'
    '0:2:4,2FF70002AC00383D,20240002AC00383D\r\n'
    '0:5:1,2FF70002AC00383D,20510002AC00383D\r\n'
    '0:5:2,2FF70002AC00383D,20520002AC00383D\r\n'
    '0:5:3,2FF70002AC00383D,20530002AC00383D\r\n'
    '0:5:4,2FF70202AC00383D,20540202AC00383D\r\n'
    '0:6:4,2FF70002AC00383D,20640002AC00383D\r\n'
    '0:8:1,10.10.120.253,iqn.2000-05.com.3pardata:21810002ac00383d\r\n'
    '0:8:2,0.0.0.0,iqn.2000-05.com.3pardata:20820002ac00383d\r\n'
    '1:2:1,29210002AC00383D,21210002AC00383D\r\n'
    '1:2:2,2FF70002AC00383D,21220002AC00383D\r\n'
    '-----------------------------------------------------------------\r\n')

VOLUME_STATE_RET = (
    'Id,Name,Prov,Type,State,-Detailed_State-\r\n'
    '410,volume-d03338a9-9115-48a3-8dfc-35cdfcdc15a7,snp,vcopy,normal,'
    'normal\r\n'
    '-----------------------------------------------------------------\r\n')

PORT_RET = (
    'N:S:P,Mode,State,----Node_WWN----,-Port_WWN/HW_Addr-,Type,Protocol,'
    'Label,Partner,FailoverState\r\n'
    '0:2:1,target,ready,28210002AC00383D,20210002AC00383D,host,FC,'
    '-,1:2:1,none\r\n'
    '0:2:2,initiator,loss_sync,2FF70002AC00383D,20220002AC00383D,free,FC,'
    '-,-,-\r\n'
    '0:2:3,initiator,loss_sync,2FF70002AC00383D,20230002AC00383D,free,FC,'
    '-,-,-\r\n'
    '0:2:4,initiator,loss_sync,2FF70002AC00383D,20240002AC00383D,free,FC,'
    '-,-,-\r\n'
    '0:5:1,initiator,loss_sync,2FF70002AC00383D,20510002AC00383D,free,FC,'
    '-,-,-\r\n'
    '0:5:2,initiator,loss_sync,2FF70002AC00383D,20520002AC00383D,free,FC,'
    '-,-,-\r\n'
    '0:5:3,initiator,loss_sync,2FF70002AC00383D,20530002AC00383D,free,FC,'
    '-,-,-\r\n'
    '0:5:4,initiator,ready,2FF70202AC00383D,20540202AC00383D,host,FC,'
    '-,1:5:4,active\r\n'
    '0:6:1,initiator,ready,2FF70002AC00383D,20610002AC00383D,disk,FC,'
    '-,-,-\r\n'
    '0:6:2,initiator,ready,2FF70002AC00383D,20620002AC00383D,disk,FC,'
    '-,-,-\r\n')

ISCSI_PORT_RET = (
    'N:S:P,State,IPAddr,Netmask,Gateway,TPGT,MTU,Rate,DHCP,iSNS_Addr,'
    'iSNS_Port\r\n'
    '0:8:1,ready,10.10.120.253,255.255.224.0,0.0.0.0,81,1500,10Gbps,'
    '0,0.0.0.0,3205\r\n'
    '0:8:2,loss_sync,0.0.0.0,0.0.0.0,0.0.0.0,82,1500,n/a,0,0.0.0.0,3205\r\n'
    '1:8:1,ready,10.10.220.253,255.255.224.0,0.0.0.0,181,1500,10Gbps,'
    '0,0.0.0.0,3205\r\n'
    '1:8:2,loss_sync,0.0.0.0,0.0.0.0,0.0.0.0,182,1500,n/a,0,0.0.0.0,3205\r\n')

ISCSI_3PAR_RET = (
    'Id,Name,Persona,-WWN/iSCSI_Name-,Port,IP_addr\r\n'
    '75,fakehost.foo,Generic,iqn.1993-08.org.debian:01:222,---,'
    '10.10.222.12\r\n'
    '\r\n'
    'Id,Name,-Initiator_CHAP_Name-,-Target_CHAP_Name-\r\n'
    '75,fakehost.foo,--,--\r\n'
    '\r\n'
    '---------- Host fakehost.foo ----------\r\n'
    'Name       : fakehost.foo\r\n'
    'Domain     : FAKE_TEST\r\n'
    'Id         : 75\r\n'
    'Location   : --\r\n'
    'IP Address : --\r\n'
    'OS         : --\r\n'
    'Model      : --\r\n'
    'Contact    : --\r\n'
    'Comment    : --  \r\n\r\n\r\n')

SHOW_PORT_ISCSI = (
    'N:S:P,IPAddr,---------------iSCSI_Name----------------\r\n'
    '0:8:1,1.1.1.2,iqn.2000-05.com.3pardata:21810002ac00383d\r\n'
    '0:8:2,10.10.120.252,iqn.2000-05.com.3pardata:20820002ac00383d\r\n'
    '1:8:1,10.10.220.253,iqn.2000-05.com.3pardata:21810002ac00383d\r\n'
    '1:8:2,10.10.220.252,iqn.2000-05.com.3pardata:21820002ac00383d\r\n'
    '-------------------------------------------------------------\r\n')

SHOW_VLUN = (
    'Lun,VVName,HostName,---------Host_WWN/iSCSI_Name----------,Port,Type,'
    'Status,ID\r\n'
    '0,a,fakehost,iqn.1993-08.org.debian:01:3a779e4abc22,1:8:1,matched set,'
    'active,0\r\n'
    '------------------------------------------------------------------------'
    '--------------\r\n')

SHOW_VLUN_NONE = (
    'Port\r\n0:2:1\r\n0:2:1\r\n1:8:1\r\n1:8:1\r\n1:8:1\r\n1:2:1\r\n'
    '1:2:1\r\n1:2:1\r\n1:2:1\r\n1:2:1\r\n1:2:1\r\n1:8:1\r\n1:8:1\r\n1:8:1\r\n'
    '1:8:1\r\n1:8:1\r\n1:8:1\r\n0:2:1\r\n0:2:1\r\n0:2:1\r\n0:2:1\r\n0:2:1\r\n'
    '0:2:1\r\n0:2:1\r\n1:8:1\r\n1:8:1\r\n0:2:1\r\n0:2:1\r\n1:2:1\r\n1:2:1\r\n'
    '1:2:1\r\n1:2:1\r\n1:8:1\r\n-----')

READY_ISCSI_PORT_RET = (
    'N:S:P,State,IPAddr,Netmask,Gateway,TPGT,MTU,Rate,DHCP,iSNS_Addr,'
    'iSNS_Port\r\n'
    '0:8:1,ready,10.10.120.253,255.255.224.0,0.0.0.0,81,1500,10Gbps,'
    '0,0.0.0.0,3205\r\n'
    '0:8:2,ready,10.10.120.252,255.255.224.0,0.0.0.0,82,1500,10Gbps,0,'
    '0.0.0.0,3205\r\n'
    '1:8:1,ready,10.10.220.253,255.255.224.0,0.0.0.0,181,1500,10Gbps,'
    '0,0.0.0.0,3205\r\n'
    '1:8:2,ready,10.10.220.252,255.255.224.0,0.0.0.0,182,1500,10Gbps,0,'
    '0.0.0.0,3205\r\n'
    '-------------------------------------------------------------------'
    '----------------------\r\n')
