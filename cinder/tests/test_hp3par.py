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
"""Unit tests for OpenStack Cinder volume drivers."""

import ast
import mock
import mox
import shutil
import tempfile

from hp3parclient import exceptions as hpexceptions

from cinder import context
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

    PORT_MODE_TARGET = 2
    PORT_MODE_INITIATOR = 3
    PORT_MODE_PEER = 4

    PORT_TYPE_HOST = 1
    PORT_TYPE_DISK = 2
    PORT_TYPE_FREE = 3
    PORT_TYPE_RCIP = 6
    PORT_TYPE_ISCSI = 7

    PORT_PROTO_FC = 1
    PORT_PROTO_ISCSI = 2
    PORT_PROTO_IP = 4

    PORT_STATE_READY = 4
    PORT_STATE_SYNC = 5
    PORT_STATE_OFFLINE = 10

    HOST_EDIT_ADD = 1
    HOST_EDIT_REMOVE = 2

    api_url = None
    debug = False

    connection_count = 0

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
        self.connection_count += 1
        return None

    def logout(self):
        if self.connection_count < 1:
            raise hpexceptions.CommandError('No connection to log out.')
        self.connection_count -= 1
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

    def getHost(self, hostname):
        return None

    def modifyHost(self, hostname, options):
        return None

    def getPorts(self):
        return None


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
    FAKE_FC_PORTS = [{'portPos': {'node': 7, 'slot': 1, 'cardPort': 1},
                      'portWWN': '0987654321234',
                      'protocol': 1,
                      'mode': 2,
                      'linkState': 4},
                     {'portPos': {'node': 6, 'slot': 1, 'cardPort': 1},
                      'portWWN': '123456789000987',
                      'protocol': 1,
                      'mode': 2,
                      'linkState': 4}]
    QOS = {'qos:maxIOPS': '1000', 'qos:maxBWS': '50'}
    VVS_NAME = "myvvs"
    FAKE_ISCSI_PORT = {'portPos': {'node': 8, 'slot': 1, 'cardPort': 1},
                       'protocol': 2,
                       'mode': 2,
                       'IPAddr': '1.1.1.2',
                       'iSCSIName': ('iqn.2000-05.com.3pardata:'
                                     '21810002ac00383d'),
                       'linkState': 4}
    volume = {'name': VOLUME_NAME,
              'id': VOLUME_ID,
              'display_name': 'Foo Volume',
              'size': 2,
              'host': FAKE_HOST,
              'volume_type': None,
              'volume_type_id': None}

    volume_qos = {'name': VOLUME_NAME,
                  'id': VOLUME_ID,
                  'display_name': 'Foo Volume',
                  'size': 2,
                  'host': FAKE_HOST,
                  'volume_type': None,
                  'volume_type_id': 'gold'}

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

    volume_type = {'name': 'gold',
                   'deleted': False,
                   'updated_at': None,
                   'extra_specs': {'qos:maxBWS': '50',
                                   'qos:maxIOPS': '1000'},
                   'deleted_at': None,
                   'id': 'gold'}

    def setup_configuration(self):
        configuration = mox.MockObject(conf.Configuration)
        configuration.hp3par_debug = False
        configuration.hp3par_username = 'testUser'
        configuration.hp3par_password = 'testPassword'
        configuration.hp3par_api_url = 'https://1.1.1.1/api/v1'
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
        self.stubs.Set(hpdriver.hpcommon.HP3PARCommon, "_set_connections",
                       self.fake_set_connections)
        self.stubs.Set(hpdriver.hpcommon.HP3PARCommon, "_get_3par_host",
                       self.fake_get_3par_host)
        self.stubs.Set(hpdriver.hpcommon.HP3PARCommon, "_delete_3par_host",
                       self.fake_delete_3par_host)
        self.stubs.Set(hpdriver.hpcommon.HP3PARCommon, "_create_3par_vlun",
                       self.fake_create_3par_vlun)
        self.stubs.Set(hpdriver.hpcommon.HP3PARCommon, "get_ports",
                       self.fake_get_ports)
        self.stubs.Set(hpdriver.hpcommon.HP3PARCommon, "get_cpg",
                       self.fake_get_cpg)
        self.stubs.Set(hpdriver.hpcommon.HP3PARCommon,
                       "get_volume_settings_from_type",
                       self.fake_get_volume_settings_from_type)
        self.stubs.Set(hpfcdriver.hpcommon.HP3PARCommon, "get_domain",
                       self.fake_get_domain)

    def clear_mox(self):
        self.mox.ResetAll()
        self.stubs.UnsetAll()

    def fake_create_client(self):
        return FakeHP3ParClient(self.driver.configuration.hp3par_api_url)

    def fake_get_cpg(self, volume, allowSnap=False):
        return HP3PAR_CPG

    def fake_set_connections(self):
        return

    def fake_get_domain(self, cpg):
        return HP3PAR_DOMAIN

    def fake_extend_volume(self, volume, new_size):
        vol = self.driver.common.client.getVolume(volume['name'])
        old_size = vol['sizeMiB']
        option = {'comment': vol['comment'], 'snapCPG': vol['snapCPG']}
        self.driver.common.client.deleteVolume(volume['name'])
        self.driver.common.client.createVolume(vol['name'],
                                               vol['userCPG'],
                                               new_size, option)

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
        ports = self.FAKE_FC_PORTS
        ports.append(self.FAKE_ISCSI_PORT)
        return {'members': ports}

    def fake_get_volume_type(self, type_id):
        return self.volume_type

    def fake_get_qos_by_volume_type(self, volume_type):
        return self.QOS

    def fake_add_volume_to_volume_set(self, volume, volume_name,
                                      cpg, vvs_name, qos):
        return volume

    def fake_copy_volume(self, src_name, dest_name, cpg=None,
                         snap_cpg=None, tpvv=True):
        pass

    def fake_get_volume_stats(self, vol_name):
        return "normal"

    def fake_get_volume_settings_from_type(self, volume):
        return {'cpg': HP3PAR_CPG,
                'snap_cpg': HP3PAR_CPG_SNAP,
                'vvs_name': self.VVS_NAME,
                'qos': self.QOS,
                'tpvv': True,
                'volume_type': self.volume_type}

    def fake_get_volume_settings_from_type_noqos(self, volume):
        return {'cpg': HP3PAR_CPG,
                'snap_cpg': HP3PAR_CPG_SNAP,
                'vvs_name': None,
                'qos': None,
                'tpvv': True,
                'volume_type': None}

    def test_create_volume(self):
        self.flags(lock_path=self.tempdir)
        self.stubs.Set(hpdriver.hpcommon.HP3PARCommon,
                       "get_volume_settings_from_type",
                       self.fake_get_volume_settings_from_type_noqos)
        self.driver.create_volume(self.volume)
        volume = self.driver.common.client.getVolume(self.VOLUME_3PAR_NAME)
        self.assertEqual(volume['name'], self.VOLUME_3PAR_NAME)

    def test_create_volume_qos(self):
        self.flags(lock_path=self.tempdir)
        self.stubs.Set(hpdriver.hpcommon.HP3PARCommon,
                       "get_volume_settings_from_type",
                       self.fake_get_volume_settings_from_type)
        self.stubs.Set(hpdriver.hpcommon.HP3PARCommon,
                       "_add_volume_to_volume_set",
                       self.fake_add_volume_to_volume_set)
        self.driver.create_volume(self.volume_qos)
        volume = self.driver.common.client.getVolume(self.VOLUME_3PAR_NAME)

        self.assertEqual(volume['name'], self.VOLUME_3PAR_NAME)
        self.assertNotIn(self.QOS, dict(ast.literal_eval(volume['comment'])))

    def test_delete_volume(self):
        self.flags(lock_path=self.tempdir)
        self.stubs.Set(hpdriver.hpcommon.HP3PARCommon,
                       "get_volume_settings_from_type",
                       self.fake_get_volume_settings_from_type)
        self.driver.delete_volume(self.volume)
        self.assertRaises(hpexceptions.HTTPNotFound,
                          self.driver.common.client.getVolume,
                          self.VOLUME_ID)

    def test_create_cloned_volume(self):
        self.flags(lock_path=self.tempdir)
        self.stubs.Set(hpdriver.hpcommon.HP3PARCommon,
                       "get_volume_settings_from_type",
                       self.fake_get_volume_settings_from_type)
        self.stubs.Set(hpdriver.hpcommon.HP3PARCommon, "_copy_volume",
                       self.fake_copy_volume)
        volume = {'name': HP3PARBaseDriver.VOLUME_NAME,
                  'id': HP3PARBaseDriver.CLONE_ID,
                  'display_name': 'Foo Volume',
                  'size': 2,
                  'host': HP3PARBaseDriver.FAKE_HOST,
                  'source_volid': HP3PARBaseDriver.VOLUME_ID}
        src_vref = {}
        model_update = self.driver.create_cloned_volume(volume, src_vref)
        self.assertIsNotNone(model_update)

    @mock.patch.object(hpdriver.hpcommon.HP3PARCommon, '_run_ssh')
    def test_attach_volume(self, mock_run_ssh):
        mock_run_ssh.side_effect = [[CLI_CR, ''], Exception('Custom ex')]
        self.driver.attach_volume(context.get_admin_context(),
                                  self.volume,
                                  'abcdef',
                                  'newhost',
                                  '/dev/vdb')
        self.assertTrue(mock_run_ssh.called)
        self.assertRaises(exception.CinderException,
                          self.driver.attach_volume,
                          context.get_admin_context(),
                          self.volume,
                          'abcdef',
                          'newhost',
                          '/dev/vdb')

    @mock.patch.object(hpdriver.hpcommon.HP3PARCommon, '_run_ssh')
    def test_detach_volume(self, mock_run_ssh):
        mock_run_ssh.side_effect = [[CLI_CR, ''], Exception('Custom ex')]
        self.driver.detach_volume(context.get_admin_context(), self.volume)
        self.assertTrue(mock_run_ssh.called)
        self.assertRaises(exception.CinderException,
                          self.driver.detach_volume,
                          context.get_admin_context(),
                          self.volume)

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

    def test_delete_snapshot_in_use(self):
        self.flags(lock_path=self.tempdir)

        self.driver.create_snapshot(self.snapshot)
        self.driver.create_volume_from_snapshot(self.volume, self.snapshot)

        ex = hpexceptions.HTTPConflict("In use")
        self.driver.common.client.deleteVolume = mock.Mock(side_effect=ex)

        # Deleting the snapshot that a volume is dependent on should fail
        self.assertRaises(exception.SnapshotIsBusy,
                          self.driver.delete_snapshot,
                          self.snapshot)

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

    def test_create_volume_from_snapshot_qos(self):
        self.flags(lock_path=self.tempdir)
        self.stubs.Set(hpdriver.hpcommon.HP3PARCommon, "_get_volume_type",
                       self.fake_get_volume_type)
        self.stubs.Set(hpdriver.hpcommon.HP3PARCommon,
                       "_get_qos_by_volume_type",
                       self.fake_get_qos_by_volume_type)
        self.stubs.Set(hpdriver.hpcommon.HP3PARCommon,
                       "_add_volume_to_volume_set",
                       self.fake_add_volume_to_volume_set)
        self.driver.create_volume_from_snapshot(self.volume_qos, self.snapshot)
        snap_vol = self.driver.common.client.getVolume(self.VOLUME_3PAR_NAME)
        self.assertEqual(snap_vol['name'], self.VOLUME_3PAR_NAME)
        self.assertNotIn(self.QOS, dict(ast.literal_eval(snap_vol['comment'])))

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

    @mock.patch.object(hpdriver.hpcommon.HP3PARCommon, '_run_ssh')
    def test_update_volume_key_value_pair(self, mock_run_ssh):
        mock_run_ssh.return_value = [CLI_CR, '']
        self.assertEqual(
            self.driver.common.update_volume_key_value_pair(self.volume,
                                                            'a',
                                                            'b'),
            None)
        update_cmd = ['setvv', '-setkv', 'a=b', self.VOLUME_3PAR_NAME]
        mock_run_ssh.assert_called_once_with(update_cmd, False)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.common.update_volume_key_value_pair,
                          self.volume,
                          None,
                          'b')

    @mock.patch.object(hpdriver.hpcommon.HP3PARCommon, '_run_ssh')
    def test_clear_volume_key_value_pair(self, mock_run_ssh):
        mock_run_ssh.side_effect = [[CLI_CR, ''], Exception('Custom ex')]
        self.assertEqual(
            self.driver.common.clear_volume_key_value_pair(self.volume, 'a'),
            None)
        clear_cmd = ['setvv', '-clrkey', 'a', self.VOLUME_3PAR_NAME]
        mock_run_ssh.assert_called_once_with(clear_cmd, False)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.common.clear_volume_key_value_pair,
                          self.volume,
                          None)

    def test_extend_volume(self):
        self.flags(lock_path=self.tempdir)
        self.stubs.UnsetAll()
        self.stubs.Set(hpdriver.hpcommon.HP3PARCommon, "extend_volume",
                       self.fake_extend_volume)
        option = {'comment': '', 'snapCPG': HP3PAR_CPG_SNAP}
        self.driver.common.client.createVolume(self.volume['name'],
                                               HP3PAR_CPG,
                                               self.volume['size'],
                                               option)
        old_size = self.volume['size']
        volume = self.driver.common.client.getVolume(self.volume['name'])
        self.driver.extend_volume(volume, str(old_size + 1))
        vol = self.driver.common.client.getVolume(self.volume['name'])
        self.assertEqual(vol['sizeMiB'], str(old_size + 1))


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
        self.assertEqual(0, self.driver.common.client.connection_count,
                         'Leaked hp3parclient connection.')
        super(TestHP3PARFCDriver, self).tearDown()

    def setup_driver(self, configuration):
        self.driver = hpfcdriver.HP3PARFCDriver(configuration=configuration)

        self.stubs.Set(hpdriver.hpcommon.HP3PARCommon, "_create_client",
                       self.fake_create_client)
        self.stubs.Set(hpdriver.hpcommon.HP3PARCommon, "_set_connections",
                       self.fake_set_connections)
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

    def test_initialize_connection(self):
        self.flags(lock_path=self.tempdir)
        result = self.driver.initialize_connection(self.volume, self.connector)
        self.assertEqual(result['driver_volume_type'], 'fibre_channel')

        # we should have a host and a vlun now.
        host = self.fake_get_3par_host(self.FAKE_HOST)
        self.assertEqual(self.FAKE_HOST, host['name'])
        self.assertEqual(HP3PAR_DOMAIN, host['domain'])
        vlun = self.driver.common.client.getVLUN(self.VOLUME_3PAR_NAME)

        self.assertEqual(self.VOLUME_3PAR_NAME, vlun['volumeName'])
        self.assertEqual(self.FAKE_HOST, vlun['hostname'])

    def test_get_volume_stats(self):
        self.flags(lock_path=self.tempdir)

        def fake_safe_get(*args):
            return "HP3PARFCDriver"

        self.stubs.Set(self.driver.configuration, 'safe_get', fake_safe_get)
        stats = self.driver.get_volume_stats(True)
        self.assertEqual(stats['storage_protocol'], 'FC')
        self.assertEqual(stats['total_capacity_gb'], 'infinite')
        self.assertEqual(stats['free_capacity_gb'], 'infinite')

        #modify the CPG to have a limit
        old_cpg = self.driver.common.client.getCPG(HP3PAR_CPG)
        options = {'SDGrowth': {'limitMiB': 8192}}
        self.driver.common.client.deleteCPG(HP3PAR_CPG)
        self.driver.common.client.createCPG(HP3PAR_CPG, options)

        const = 0.0009765625
        stats = self.driver.get_volume_stats(True)
        self.assertEqual(stats['storage_protocol'], 'FC')
        total_capacity_gb = 8192 * const
        self.assertEqual(stats['total_capacity_gb'], total_capacity_gb)
        free_capacity_gb = int((8192 - old_cpg['UsrUsage']['usedMiB']) * const)
        self.assertEqual(stats['free_capacity_gb'], free_capacity_gb)
        self.driver.common.client.deleteCPG(HP3PAR_CPG)
        self.driver.common.client.createCPG(HP3PAR_CPG, {})

    def test_create_host(self):
        self.flags(lock_path=self.tempdir)

        #record
        self.clear_mox()
        self.stubs.Set(hpfcdriver.hpcommon.HP3PARCommon, "get_cpg",
                       self.fake_get_cpg)
        self.stubs.Set(hpfcdriver.hpcommon.HP3PARCommon, "get_domain",
                       self.fake_get_domain)
        _run_ssh = self.mox.CreateMock(hpdriver.hpcommon.HP3PARCommon._run_ssh)
        self.stubs.Set(hpdriver.hpcommon.HP3PARCommon, "_run_ssh", _run_ssh)

        getHost = self.mox.CreateMock(FakeHP3ParClient.getHost)
        self.stubs.Set(FakeHP3ParClient, "getHost", getHost)

        ex = hpexceptions.HTTPNotFound('Host not found.')
        getHost('fakehost').AndRaise(ex)

        create_host_cmd = (['createhost', '-persona', '1', '-domain',
                            ('OpenStack',), 'fakehost', '123456789012345',
                            '123456789054321'])
        _run_ssh(create_host_cmd, False).AndReturn([CLI_CR, ''])

        getHost('fakehost').AndReturn({'name': self.FAKE_HOST,
                                       'FCPaths': [{'wwn': '123456789012345'},
                                                   {'wwn': '123456789054321'}]}
                                      )
        self.mox.ReplayAll()

        host = self.driver._create_host(self.volume, self.connector)
        self.assertEqual(host['name'], self.FAKE_HOST)

    def test_create_invalid_host(self):
        self.flags(lock_path=self.tempdir)

        #record
        self.clear_mox()
        self.stubs.Set(hpdriver.hpcommon.HP3PARCommon, "get_cpg",
                       self.fake_get_cpg)
        self.stubs.Set(hpdriver.hpcommon.HP3PARCommon, "get_domain",
                       self.fake_get_domain)
        _run_ssh = self.mox.CreateMock(hpdriver.hpcommon.HP3PARCommon._run_ssh)
        self.stubs.Set(hpdriver.hpcommon.HP3PARCommon, "_run_ssh", _run_ssh)

        getHost = self.mox.CreateMock(FakeHP3ParClient.getHost)
        self.stubs.Set(FakeHP3ParClient, "getHost", getHost)

        not_found_ex = hpexceptions.HTTPNotFound('Host not found.')
        getHost('fakehost').AndRaise(not_found_ex)

        create_host_cmd = (['createhost', '-persona', '1', '-domain',
                            ('OpenStack',), 'fakehost', '123456789012345',
                            '123456789054321'])
        create_host_ret = pack(CLI_CR +
                               'already used by host fakehost.foo (19)')
        _run_ssh(create_host_cmd, False).AndReturn([create_host_ret, ''])

        host_ret = {
            'name': 'fakehost.foo',
            'FCPaths': [{'wwn': '123456789012345'},
                        {'wwn': '123456789054321'}]}
        getHost('fakehost.foo').AndReturn(host_ret)

        self.mox.ReplayAll()

        host = self.driver._create_host(self.volume, self.connector)

        self.assertEqual(host['name'], 'fakehost.foo')

    def test_create_modify_host(self):
        self.flags(lock_path=self.tempdir)

        #record
        self.clear_mox()
        self.stubs.Set(hpdriver.hpcommon.HP3PARCommon, "get_cpg",
                       self.fake_get_cpg)
        self.stubs.Set(hpdriver.hpcommon.HP3PARCommon, "get_domain",
                       self.fake_get_domain)

        getHost = self.mox.CreateMock(FakeHP3ParClient.getHost)
        self.stubs.Set(FakeHP3ParClient, "getHost", getHost)

        modifyHost = self.mox.CreateMock(FakeHP3ParClient.modifyHost)
        self.stubs.Set(FakeHP3ParClient, "modifyHost", modifyHost)

        getHost('fakehost').AndReturn(({'name': self.FAKE_HOST,
                                        'FCPaths': []}))

        modifyHost('fakehost', {'FCWWNs':
                                ['123456789012345', '123456789054321'],
                                'pathOperation': 1})

        getHost('fakehost').AndReturn({'name': self.FAKE_HOST,
                                       'FCPaths': [{'wwn': '123456789012345'},
                                                   {'wwn': '123456789054321'}]}
                                      )

        self.mox.ReplayAll()

        host = self.driver._create_host(self.volume, self.connector)
        self.assertEqual(host['name'], self.FAKE_HOST)
        self.assertEqual(len(host['FCPaths']), 2)

    def test_modify_host_with_new_wwn(self):
        self.flags(lock_path=self.tempdir)
        self.clear_mox()

        hpdriver.hpcommon.HP3PARCommon.get_cpg = mock.Mock(
            return_value=self.fake_get_cpg)
        hpdriver.hpcommon.HP3PARCommon.get_domain = mock.Mock(
            return_value=self.fake_get_domain)

        # set up the getHost mock
        self.driver.common.client.getHost = mock.Mock()
        # define the return values for the 2 calls
        getHost_ret1 = {
            'name': self.FAKE_HOST,
            'FCPaths': [{'wwn': '123456789054321'}]}
        getHost_ret2 = {
            'name': self.FAKE_HOST,
            'FCPaths': [{'wwn': '123456789012345'},
                        {'wwn': '123456789054321'}]}
        self.driver.common.client.getHost.side_effect = [
            getHost_ret1, getHost_ret2]

        # setup the modifyHost mock
        self.driver.common.client.modifyHost = mock.Mock()

        host = self.driver._create_host(self.volume, self.connector)

        # mock assertions
        self.driver.common.client.getHost.assert_has_calls([
            mock.call('fakehost'),
            mock.call('fakehost')])
        self.driver.common.client.modifyHost.assert_called_once_with(
            'fakehost', {'FCWWNs': ['123456789012345'], 'pathOperation': 1})

        self.assertEqual(host['name'], self.FAKE_HOST)
        self.assertEqual(len(host['FCPaths']), 2)

    def test_modify_host_with_unknown_wwn_and_new_wwn(self):
        self.flags(lock_path=self.tempdir)
        self.clear_mox()

        hpdriver.hpcommon.HP3PARCommon.get_cpg = mock.Mock(
            return_value=self.fake_get_cpg)
        hpdriver.hpcommon.HP3PARCommon.get_domain = mock.Mock(
            return_value=self.fake_get_domain)

        # set up the getHost mock
        self.driver.common.client.getHost = mock.Mock()
        # define the return values for the 2 calls
        getHost_ret1 = {
            'name': self.FAKE_HOST,
            'FCPaths': [{'wwn': '123456789054321'},
                        {'wwn': 'xxxxxxxxxxxxxxx'}]}
        getHost_ret2 = {
            'name': self.FAKE_HOST,
            'FCPaths': [{'wwn': '123456789012345'},
                        {'wwn': '123456789054321'},
                        {'wwn': 'xxxxxxxxxxxxxxx'}]}
        self.driver.common.client.getHost.side_effect = [
            getHost_ret1, getHost_ret2]

        # setup the modifyHost mock
        self.driver.common.client.modifyHost = mock.Mock()

        host = self.driver._create_host(self.volume, self.connector)

        # mock assertions
        self.driver.common.client.getHost.assert_has_calls([
            mock.call('fakehost'),
            mock.call('fakehost')])
        self.driver.common.client.modifyHost.assert_called_once_with(
            'fakehost', {'FCWWNs': ['123456789012345'], 'pathOperation': 1})

        self.assertEqual(host['name'], self.FAKE_HOST)
        self.assertEqual(len(host['FCPaths']), 3)


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
        self.assertEqual(0, self.driver.common.client.connection_count,
                         'Leaked hp3parclient connection.')
        self._hosts = {}
        super(TestHP3PARISCSIDriver, self).tearDown()

    def setup_driver(self, configuration, set_up_fakes=True):
        self.driver = hpdriver.HP3PARISCSIDriver(configuration=configuration)

        self.stubs.Set(hpdriver.hpcommon.HP3PARCommon, "_create_client",
                       self.fake_create_client)

        if set_up_fakes:
            self.stubs.Set(hpdriver.hpcommon.HP3PARCommon, "get_ports",
                           self.fake_get_ports)

        self.stubs.Set(hpdriver.hpcommon.HP3PARCommon, "_set_connections",
                       self.fake_set_connections)
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
        self.assertEqual(self.FAKE_HOST, host['name'])
        self.assertEqual(HP3PAR_DOMAIN, host['domain'])
        vlun = self.driver.common.client.getVLUN(self.VOLUME_3PAR_NAME)

        self.assertEqual(self.VOLUME_3PAR_NAME, vlun['volumeName'])
        self.assertEqual(self.FAKE_HOST, vlun['hostname'])

    def test_get_volume_stats(self):
        self.flags(lock_path=self.tempdir)

        def fake_safe_get(*args):
            return "HP3PARFCDriver"

        self.stubs.Set(self.driver.configuration, 'safe_get', fake_safe_get)
        stats = self.driver.get_volume_stats(True)
        self.assertEqual(stats['storage_protocol'], 'iSCSI')
        self.assertEqual(stats['total_capacity_gb'], 'infinite')
        self.assertEqual(stats['free_capacity_gb'], 'infinite')

        #modify the CPG to have a limit
        old_cpg = self.driver.common.client.getCPG(HP3PAR_CPG)
        options = {'SDGrowth': {'limitMiB': 8192}}
        self.driver.common.client.deleteCPG(HP3PAR_CPG)
        self.driver.common.client.createCPG(HP3PAR_CPG, options)

        const = 0.0009765625
        stats = self.driver.get_volume_stats(True)
        self.assertEqual(stats['storage_protocol'], 'iSCSI')
        total_capacity_gb = 8192 * const
        self.assertEqual(stats['total_capacity_gb'], total_capacity_gb)
        free_capacity_gb = int((8192 - old_cpg['UsrUsage']['usedMiB']) * const)
        self.assertEqual(stats['free_capacity_gb'], free_capacity_gb)
        self.driver.common.client.deleteCPG(HP3PAR_CPG)
        self.driver.common.client.createCPG(HP3PAR_CPG, {})

    def test_create_host(self):
        self.flags(lock_path=self.tempdir)

        #record
        self.clear_mox()
        self.stubs.Set(hpdriver.hpcommon.HP3PARCommon, "get_cpg",
                       self.fake_get_cpg)
        self.stubs.Set(hpdriver.hpcommon.HP3PARCommon, "get_domain",
                       self.fake_get_domain)
        _run_ssh = self.mox.CreateMock(hpdriver.hpcommon.HP3PARCommon._run_ssh)
        self.stubs.Set(hpdriver.hpcommon.HP3PARCommon, "_run_ssh", _run_ssh)

        getHost = self.mox.CreateMock(FakeHP3ParClient.getHost)
        self.stubs.Set(FakeHP3ParClient, "getHost", getHost)

        not_found_ex = hpexceptions.HTTPNotFound('Host not found.')
        getHost('fakehost').AndRaise(not_found_ex)

        create_host_cmd = (['createhost', '-iscsi', '-persona', '1', '-domain',
                            ('OpenStack',), 'fakehost',
                            'iqn.1993-08.org.debian:01:222'])
        _run_ssh(create_host_cmd, False).AndReturn([CLI_CR, ''])

        getHost('fakehost').AndReturn({'name': self.FAKE_HOST})
        self.mox.ReplayAll()

        host = self.driver._create_host(self.volume, self.connector)
        self.assertEqual(host['name'], self.FAKE_HOST)

    def test_create_invalid_host(self):
        self.flags(lock_path=self.tempdir)

        #record
        self.clear_mox()
        self.stubs.Set(hpdriver.hpcommon.HP3PARCommon, "get_cpg",
                       self.fake_get_cpg)
        self.stubs.Set(hpdriver.hpcommon.HP3PARCommon, "get_domain",
                       self.fake_get_domain)
        _run_ssh = self.mox.CreateMock(hpdriver.hpcommon.HP3PARCommon._run_ssh)
        self.stubs.Set(hpdriver.hpcommon.HP3PARCommon, "_run_ssh", _run_ssh)

        getHost = self.mox.CreateMock(FakeHP3ParClient.getHost)
        self.stubs.Set(FakeHP3ParClient, "getHost", getHost)

        not_found_ex = hpexceptions.HTTPNotFound('Host not found.')
        getHost('fakehost').AndRaise(not_found_ex)

        create_host_cmd = (['createhost', '-iscsi', '-persona', '1', '-domain',
                           ('OpenStack',), 'fakehost',
                            'iqn.1993-08.org.debian:01:222'])
        in_use_ret = pack('\r\nalready used by host fakehost.foo ')
        _run_ssh(create_host_cmd, False).AndReturn([in_use_ret, ''])

        getHost('fakehost.foo').AndReturn({'name': 'fakehost.foo'})
        self.mox.ReplayAll()

        host = self.driver._create_host(self.volume, self.connector)

        self.assertEqual(host['name'], 'fakehost.foo')

    def test_create_modify_host(self):
        self.flags(lock_path=self.tempdir)

        #record
        self.clear_mox()
        self.stubs.Set(hpdriver.hpcommon.HP3PARCommon, "get_cpg",
                       self.fake_get_cpg)
        self.stubs.Set(hpdriver.hpcommon.HP3PARCommon, "get_domain",
                       self.fake_get_domain)

        getHost = self.mox.CreateMock(FakeHP3ParClient.getHost)
        self.stubs.Set(FakeHP3ParClient, "getHost", getHost)

        modifyHost = self.mox.CreateMock(FakeHP3ParClient.modifyHost)
        self.stubs.Set(FakeHP3ParClient, "modifyHost", modifyHost)

        getHost('fakehost').AndReturn(({'name': self.FAKE_HOST,
                                        'iSCSIPaths': []}))

        modifyHost('fakehost', {'iSCSINames':
                                ['iqn.1993-08.org.debian:01:222'],
                                'pathOperation': 1})

        ret_value = {'name': self.FAKE_HOST,
                     'iSCSIPaths': [{'name': 'iqn.1993-08.org.debian:01:222'}]
                     }
        getHost('fakehost').AndReturn(ret_value)
        self.mox.ReplayAll()

        host = self.driver._create_host(self.volume, self.connector)
        self.assertEqual(host['name'], self.FAKE_HOST)
        self.assertEqual(len(host['iSCSIPaths']), 1)

    def test_get_ports(self):
        self.flags(lock_path=self.tempdir)

        #record
        self.clear_mox()
        getPorts = self.mox.CreateMock(FakeHP3ParClient.getPorts)
        self.stubs.Set(FakeHP3ParClient, "getPorts", getPorts)

        getPorts().AndReturn(PORTS1_RET)
        self.mox.ReplayAll()

        ports = self.driver.common.get_ports()['members']
        self.assertEqual(len(ports), 3)

    def test_get_iscsi_ip_active(self):
        self.flags(lock_path=self.tempdir)

        #record set up
        self.clear_mox()

        getPorts = self.mox.CreateMock(FakeHP3ParClient.getPorts)
        self.stubs.Set(FakeHP3ParClient, "getPorts", getPorts)

        getVLUNs = self.mox.CreateMock(FakeHP3ParClient.getVLUNs)
        self.stubs.Set(FakeHP3ParClient, "getVLUNs", getVLUNs)

        getPorts().AndReturn(PORTS_RET)
        getVLUNs().AndReturn(VLUNS2_RET)
        self.mox.ReplayAll()

        config = self.setup_configuration()
        config.hp3par_iscsi_ips = ['10.10.220.253', '10.10.220.252']
        self.setup_driver(config, set_up_fakes=False)
        self.mox.ReplayAll()

        ip = self.driver._get_iscsi_ip('fakehost')
        self.assertEqual(ip, '10.10.220.252')

    def test_get_iscsi_ip(self):
        self.flags(lock_path=self.tempdir)

        #record driver set up
        self.clear_mox()
        getPorts = self.mox.CreateMock(FakeHP3ParClient.getPorts)
        self.stubs.Set(FakeHP3ParClient, "getPorts", getPorts)

        getVLUNs = self.mox.CreateMock(FakeHP3ParClient.getVLUNs)
        self.stubs.Set(FakeHP3ParClient, "getVLUNs", getVLUNs)

        getPorts().AndReturn(PORTS_RET)
        getVLUNs().AndReturn(VLUNS1_RET)
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
        getPorts = self.mox.CreateMock(FakeHP3ParClient.getPorts)
        self.stubs.Set(FakeHP3ParClient, "getPorts", getPorts)

        getPorts().AndReturn(PORTS_RET)

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
        getVLUNs = self.mox.CreateMock(FakeHP3ParClient.getVLUNs)
        self.stubs.Set(FakeHP3ParClient, "getVLUNs", getVLUNs)

        getVLUNs().AndReturn(VLUNS3_RET)
        getVLUNs().AndReturn(VLUNS4_RET)
        getVLUNs().AndReturn(VLUNS4_RET)

        self.mox.ReplayAll()
        # in use count
        vluns = self.driver.common.client.getVLUNs()
        nsp = self.driver._get_least_used_nsp(vluns['members'],
                                              ['0:2:1', '1:8:1'])
        self.assertEqual(nsp, '1:8:1')

        # in use count
        vluns = self.driver.common.client.getVLUNs()
        nsp = self.driver._get_least_used_nsp(vluns['members'],
                                              ['0:2:1', '1:2:1'])
        self.assertEqual(nsp, '1:2:1')

        # in use count
        vluns = self.driver.common.client.getVLUNs()
        nsp = self.driver._get_least_used_nsp(vluns['members'],
                                              ['1:1:1', '1:2:1'])
        self.assertEqual(nsp, '1:1:1')


def pack(arg):
    header = '\r\n\r\n\r\n\r\n\r\n'
    footer = '\r\n\r\n\r\n'
    return header + arg + footer

PORTS_RET = ({'members':
              [{'portPos': {'node': 1, 'slot': 8, 'cardPort': 2},
                'protocol': 2,
                'IPAddr': '10.10.220.252',
                'linkState': 4,
                'device': [],
                'iSCSIName': 'iqn.2000-05.com.3pardata:21820002ac00383d',
                'mode': 2,
                'HWAddr': '2C27D75375D2',
                'type': 8},
               {'portPos': {'node': 1, 'slot': 8, 'cardPort': 1},
                'protocol': 2,
                'IPAddr': '10.10.220.253',
                'linkState': 4,
                'device': [],
                'iSCSIName': 'iqn.2000-05.com.3pardata:21810002ac00383d',
                'mode': 2,
                'HWAddr': '2C27D75375D6',
                'type': 8}]})

PORTS1_RET = ({'members':
               [{'portPos': {'node': 0, 'slot': 8, 'cardPort': 2},
                 'protocol': 2,
                 'IPAddr': '10.10.120.252',
                 'linkState': 4,
                 'device': [],
                 'iSCSIName': 'iqn.2000-05.com.3pardata:21820002ac00383d',
                 'mode': 2,
                 'HWAddr': '2C27D75375D2',
                 'type': 8},
                {'portPos': {'node': 1, 'slot': 8, 'cardPort': 1},
                 'protocol': 2,
                 'IPAddr': '10.10.220.253',
                 'linkState': 4,
                 'device': [],
                 'iSCSIName': 'iqn.2000-05.com.3pardata:21810002ac00383d',
                 'mode': 2,
                 'HWAddr': '2C27D75375D6',
                 'type': 8},
                {'portWWN': '20210002AC00383D',
                 'protocol': 1,
                 'linkState': 4,
                 'mode': 2,
                 'device': ['cage2'],
                 'nodeWWN': '20210002AC00383D',
                 'type': 2,
                 'portPos': {'node': 0, 'slot': 6, 'cardPort': 3}}]})

VLUNS1_RET = ({'members':
               [{'portPos': {'node': 1, 'slot': 8, 'cardPort': 2},
                 'hostname': 'foo', 'active': True},
                {'portPos': {'node': 1, 'slot': 8, 'cardPort': 1},
                 'hostname': 'bar', 'active': True},
                {'portPos': {'node': 1, 'slot': 8, 'cardPort': 1},
                 'hostname': 'bar', 'active': True},
                {'portPos': {'node': 1, 'slot': 8, 'cardPort': 1},
                 'hostname': 'bar', 'active': True}]})

VLUNS2_RET = ({'members':
               [{'portPos': {'node': 1, 'slot': 8, 'cardPort': 2},
                 'hostname': 'bar', 'active': True},
                {'portPos': {'node': 1, 'slot': 8, 'cardPort': 1},
                 'hostname': 'bar', 'active': True},
                {'portPos': {'node': 1, 'slot': 8, 'cardPort': 2},
                 'hostname': 'bar', 'active': True},
                {'portPos': {'node': 1, 'slot': 8, 'cardPort': 2},
                 'hostname': 'fakehost', 'active': True}]})

VLUNS3_RET = ({'members':
               [{'portPos': {'node': 1, 'slot': 8, 'cardPort': 2},
                 'active': True},
                {'portPos': {'node': 1, 'slot': 8, 'cardPort': 1},
                 'active': True},
                {'portPos': {'node': 1, 'slot': 8, 'cardPort': 2},
                 'active': True},
                {'portPos': {'node': 0, 'slot': 2, 'cardPort': 2},
                 'active': True},
                {'portPos': {'node': 0, 'slot': 2, 'cardPort': 1},
                 'active': True},
                {'portPos': {'node': 0, 'slot': 2, 'cardPort': 1},
                 'active': True},
                {'portPos': {'node': 0, 'slot': 2, 'cardPort': 1},
                 'active': True},
                {'portPos': {'node': 0, 'slot': 2, 'cardPort': 1},
                 'active': True}]})

VLUNS4_RET = ({'members':
               [{'portPos': {'node': 1, 'slot': 2, 'cardPort': 1},
                 'active': True},
                {'portPos': {'node': 1, 'slot': 2, 'cardPort': 1},
                 'active': True},
                {'portPos': {'node': 1, 'slot': 2, 'cardPort': 1},
                 'active': True},
                {'portPos': {'node': 1, 'slot': 2, 'cardPort': 1},
                 'active': True},
                {'portPos': {'node': 0, 'slot': 2, 'cardPort': 1},
                 'active': True},
                {'portPos': {'node': 0, 'slot': 2, 'cardPort': 1},
                 'active': True},
                {'portPos': {'node': 0, 'slot': 2, 'cardPort': 1},
                 'active': True},
                {'portPos': {'node': 0, 'slot': 2, 'cardPort': 1},
                 'active': True},
                {'portPos': {'node': 0, 'slot': 2, 'cardPort': 1},
                 'active': True}]})
