# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2012 Huawei Technologies Co., Ltd.
# Copyright (c) 2012 OpenStack LLC.
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
"""
Tests for HUAWEI volume driver.
"""
import mox
import os
import shutil
import tempfile
from xml.dom.minidom import Document
from xml.etree import ElementTree as ET

from cinder import exception
from cinder.openstack.common import log as logging
from cinder import test
from cinder.volume import configuration as conf
from cinder.volume.drivers.huawei import huawei_iscsi

LOG = logging.getLogger(__name__)

LUNInfo = {'ID': None,
           'Name': None,
           'Size': None,
           'LUN WWN': None,
           'Status': None,
           'Visible Capacity': None,
           'Stripe Unit Size': None,
           'Disk Pool ID': None,
           'Format Progress': None,
           'Cache Prefetch Strategy': None,
           'LUNType': None,
           'Cache Write Strategy': None,
           'Running Cache Write Strategy': None,
           'Consumed Capacity': None,
           'Pool ID': None,
           'SnapShot ID': None,
           'LunCopy ID': None,
           'Whether Private LUN': None,
           'Remote Replication ID': None,
           'Split mirror ID': None,
           'Owner Controller': None,
           'Worker Controller': None,
           'RAID Group ID': None}

LUNInfoCopy = {'ID': None,
               'Name': None,
               'Size': None,
               'LUN WWN': None,
               'Status': None,
               'Visible Capacity': None,
               'Stripe Unit Size': None,
               'Disk Pool ID': None,
               'Format Progress': None,
               'Cache Prefetch Strategy': None,
               'LUNType': None,
               'Cache Write Strategy': None,
               'Running Cache Write Strategy': None,
               'Consumed Capacity': None,
               'Pool ID': None,
               'SnapShot ID': None,
               'LunCopy ID': None,
               'Whether Private LUN': None,
               'Remote Replication ID': None,
               'Split mirror ID': None,
               'Owner Controller': None,
               'Worker Controller': None,
               'RAID Group ID': None}

SnapshotInfo = {'Source LUN ID': None,
                'Source LUN Name': None,
                'ID': None,
                'Name': None,
                'Type': 'Public',
                'Status': None,
                'Time Stamp': '2013-01-15 14:00:00',
                'Rollback Start Time': '--',
                'Rollback End Time': '--',
                'Rollback Speed': '--',
                'Rollback Progress': '--'}

MapInfo = {'Host Group ID': None,
           'Host Group Name': None,
           'File Engine Cluster': None,
           'Host ID': None,
           'Host Name': None,
           'Os Type': None,
           'INI Port ID': None,
           'INI Port Name': None,
           'INI Port Info': None,
           'Port Type': None,
           'Link Status': None,
           'LUN WWN': None,
           'DEV LUN ID': None,
           'Host LUN ID': None}

HostPort = {'ID': None,
            'Name': None,
            'Info': None}

LUNCopy = {'Name': None,
           'ID': None,
           'Type': None,
           'State': None,
           'Status': 'Disable'}

FakeVolume = {'name': 'Volume-lele34fe-223f-dd33-4423-asdfghjklqwe',
              'size': '2',
              'id': '0',
              'wwn': '630303710030303701094b2b00000031',
              'provider_auth': None}

FakeVolumeCopy = {'name': 'Volume-jeje34fe-223f-dd33-4423-asdfghjklqwg',
                  'size': '3',
                  'ID': '1',
                  'wwn': '630303710030303701094b2b0000003'}

FakeLUNCopy = {'ID': '1',
               'Type': 'FULL',
               'State': 'Created',
               'Status': 'Normal'}

FakeSnapshot = {'name': 'keke34fe-223f-dd33-4423-asdfghjklqwf',
                'volume_name': 'Volume-lele34fe-223f-dd33-4423-asdfghjklqwe',
                'id': '3'}

FakePoolInfo = {'ID': '2',
                'Level': 'RAID6',
                'Status': 'Normal',
                'Free Capacity': '10240',
                'Disk List': '0,1;0,2;0,3;0,4;0,5;0,6',
                'Name': 'RAID_001',
                'Type': 'Thick'}

FakeConfInfo = {'HostGroup': 'HostGroup_OpenStack',
                'HostnamePrefix': 'Host_',
                'DefaultTargetIP': '192.168.100.1',
                'TargetIQN': 'iqn.2006-08.com.huawei:oceanspace:2103037:',
                'TargetIQN-T': 'iqn.2006-08.com.huawei:oceanspace:2103037::'
                '20001:192.168.100.2',
                'TargetIQN-Dorado5100': 'iqn.2006-08.com.huawei:oceanspace:'
                '2103037::192.168.100.2',
                'TargetIQN-Dorado2100G2': 'iqn.2006-08.com.huawei:oceanspace:'
                '2103037::192.168.100.2-20001',
                'Initiator Name': 'iqn.1993-08.debian:01:ec2bff7ac3a3',
                'Initiator TargetIP': '192.168.100.2'}

FakeConnector = {'initiator': "iqn.1993-08.debian:01:ec2bff7ac3a3"}


class HuaweiVolumeTestCase(test.TestCase):

    def __init__(self, *args, **kwargs):
        super(HuaweiVolumeTestCase, self).__init__(*args, **kwargs)

    def setUp(self):
        super(HuaweiVolumeTestCase, self).setUp()
        self.tmp_dir = tempfile.mkdtemp()
        self.fake_conf_file = self.tmp_dir + '/cinder_huawei_conf.xml'
        self._create_fake_conf_file()
        configuration = mox.MockObject(conf.Configuration)
        configuration.cinder_huawei_conf_file = self.fake_conf_file
        configuration.append_config_values(mox.IgnoreArg())
        self.driver = FakeHuaweiStorage(configuration=configuration)

        self.driver.do_setup({})
        self.driver._test_flg = 'check_for_fail'
        self._test_check_for_setup_errors()

    def tearDown(self):
        shutil.rmtree(self.tmp_dir)
        super(HuaweiVolumeTestCase, self).tearDown()

    def test_create_export_failed(self):
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_export,
                          {}, FakeVolume)

    def test_delete_volume_failed(self):
        self._test_delete_volume()

    def test_create_snapshot_failed(self):
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_snapshot,
                          FakeSnapshot)

    def test_delete_snapshot_failed(self):
        self._test_delete_snapshot()

    def test_create_luncopy_failed(self):
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume_from_snapshot,
                          FakeVolumeCopy, FakeSnapshot)

    def test_initialize_failed(self):
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.initialize_connection,
                          FakeVolume, FakeConnector)

    def test_terminate_connection_failed(self):
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.terminate_connection,
                          FakeVolume, FakeConnector)

    def test_normal(self):
        # test for T Series
        self.driver._test_flg = 'check_for_T'
        self._test_check_for_setup_errors()
        self._test_create_volume()
        self._test_create_export()
        self._test_create_snapshot()
        self._test_create_volume_from_snapshot()
        self._test_initialize_connection_for_T()
        self._test_terminate_connection()
        self._test_delete_snapshot()
        self._test_delete_volume()
        self._test_get_get_volume_stats()

        # test for Dorado2100 G2
        self.driver._test_flg = 'check_for_Dorado2100G2'
        self._test_check_for_setup_errors()
        self._test_create_volume()
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_snapshot,
                          FakeSnapshot)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume_from_snapshot,
                          FakeVolumeCopy, FakeSnapshot)
        self._test_initialize_connection_for_Dorado2100G2()
        self._test_terminate_connection()
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.delete_snapshot,
                          FakeSnapshot)
        self._test_delete_volume()

        # test for Dorado5100
        self.driver._test_flg = 'check_for_Dorado5100'
        self._test_check_for_setup_errors()
        self._test_create_volume()
        self._test_create_snapshot()
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume_from_snapshot,
                          FakeVolumeCopy, FakeSnapshot)
        self._test_initialize_connection_for_Dorado5100()
        self._test_terminate_connection()
        self._test_delete_snapshot()
        self._test_delete_volume()

    def cleanup(self):
        if os.path.exists(self.fake_conf_file):
            os.remove(self.fake_conf_file)
        shutil.rmtree(self.tmp_dir)

    def _create_fake_conf_file(self):
        doc = Document()

        config = doc.createElement('config')
        doc.appendChild(config)

        storage = doc.createElement('Storage')
        config.appendChild(storage)
        controllerip0 = doc.createElement('ControllerIP0')
        controllerip0_text = doc.createTextNode('10.10.10.1')
        controllerip0.appendChild(controllerip0_text)
        storage.appendChild(controllerip0)
        controllerip1 = doc.createElement('ControllerIP1')
        controllerip1_text = doc.createTextNode('10.10.10.2')
        controllerip1.appendChild(controllerip1_text)
        storage.appendChild(controllerip1)
        username = doc.createElement('UserName')
        username_text = doc.createTextNode('admin')
        username.appendChild(username_text)
        storage.appendChild(username)
        userpassword = doc.createElement('UserPassword')
        userpassword_text = doc.createTextNode('123456')
        userpassword.appendChild(userpassword_text)
        storage.appendChild(userpassword)

        lun = doc.createElement('LUN')
        config.appendChild(lun)
        storagepool = doc.createElement('StoragePool')
        storagepool.setAttribute('Name', 'RAID_001')
        lun.appendChild(storagepool)
        storagepool = doc.createElement('StoragePool')
        storagepool.setAttribute('Name', 'RAID_002')
        lun.appendChild(storagepool)

        iscsi = doc.createElement('iSCSI')
        config.appendChild(iscsi)
        defaulttargetip = doc.createElement('DefaultTargetIP')
        defaulttargetip_text = doc.createTextNode('192.168.100.1')
        defaulttargetip.appendChild(defaulttargetip_text)
        iscsi.appendChild(defaulttargetip)
        initiator = doc.createElement('Initiator')
        initiator.setAttribute('Name', 'iqn.1993-08.debian:01:ec2bff7ac3a3')
        initiator.setAttribute('TargetIP', '192.168.100.2')
        iscsi.appendChild(initiator)

        file = open(self.fake_conf_file, 'w')
        file.write(doc.toprettyxml(indent=''))
        file.close()

    def _test_check_for_setup_errors(self):
        self.driver.check_for_setup_error()

    def _test_create_volume(self):
        self.driver.create_volume(FakeVolume)
        self.assertNotEqual(LUNInfo["ID"], None)
        self.assertEqual(LUNInfo["RAID Group ID"], FakePoolInfo['ID'])

    def _test_delete_volume(self):
        self.driver.delete_volume(FakeVolume)
        self.assertEqual(LUNInfo["ID"], None)

    def _test_create_snapshot(self):
        self.driver.create_snapshot(FakeSnapshot)
        self.assertNotEqual(SnapshotInfo["ID"], None)
        self.assertNotEqual(LUNInfo["ID"], None)
        self.assertEqual(SnapshotInfo["Status"], 'Active')
        self.assertEqual(SnapshotInfo["Source LUN ID"], LUNInfo["ID"])

    def _test_delete_snapshot(self):
        self.driver.delete_snapshot(FakeSnapshot)
        self.assertEqual(SnapshotInfo["ID"], None)

    def _test_create_volume_from_snapshot(self):
        self.driver.create_volume_from_snapshot(FakeVolumeCopy, FakeSnapshot)
        self.assertNotEqual(LUNInfoCopy["ID"], None)

    def _test_create_export(self):
        retval = self.driver.create_export({}, FakeVolume)
        self.assertNotEqual(retval, FakeVolume["id"])

    def _test_initialize_connection_for_T(self):
        connection_data = self.driver.initialize_connection(FakeVolume,
                                                            FakeConnector)
        iscsi_properties = connection_data['data']

        self.assertEquals(iscsi_properties['target_iqn'],
                          FakeConfInfo['TargetIQN-T'])
        self.assertEquals(iscsi_properties['target_portal'],
                          FakeConfInfo['Initiator TargetIP'] + ':3260')
        self.assertEqual(MapInfo["DEV LUN ID"], FakeVolume['id'])
        self.assertEqual(MapInfo["INI Port Info"],
                         FakeConnector['initiator'])

    def _test_initialize_connection_for_Dorado2100G2(self):
        connection_data = self.driver.initialize_connection(FakeVolume,
                                                            FakeConnector)
        iscsi_properties = connection_data['data']

        self.assertEquals(iscsi_properties['target_iqn'],
                          FakeConfInfo['TargetIQN-Dorado2100G2'])
        self.assertEquals(iscsi_properties['target_portal'],
                          FakeConfInfo['Initiator TargetIP'] + ':3260')
        self.assertEqual(MapInfo["DEV LUN ID"], FakeVolume['id'])
        self.assertEqual(MapInfo["INI Port Info"],
                         FakeConnector['initiator'])

    def _test_initialize_connection_for_Dorado5100(self):
        connection_data = self.driver.initialize_connection(FakeVolume,
                                                            FakeConnector)
        iscsi_properties = connection_data['data']

        self.assertEquals(iscsi_properties['target_iqn'],
                          FakeConfInfo['TargetIQN-Dorado5100'])
        self.assertEquals(iscsi_properties['target_portal'],
                          FakeConfInfo['Initiator TargetIP'] + ':3260')
        self.assertEqual(MapInfo["DEV LUN ID"], FakeVolume['id'])
        self.assertEqual(MapInfo["INI Port Info"],
                         FakeConnector['initiator'])

    def _test_terminate_connection(self):
        self.driver.terminate_connection(FakeVolume, FakeConnector)
        self.assertEqual(MapInfo["DEV LUN ID"], None)
        self.assertEqual(MapInfo["Host LUN ID"], None)
        self.assertEqual(MapInfo["INI Port Info"], None)

    def _test_get_get_volume_stats(self):
        stats = self.driver.get_volume_stats(True)

        fakecapacity = float(FakePoolInfo['Free Capacity']) / 1024
        self.assertEqual(stats['free_capacity_gb'], fakecapacity)


class FakeHuaweiStorage(huawei_iscsi.HuaweiISCSIDriver):
    """Fake Huawei Storage, Rewrite some methods of HuaweiISCSIDriver."""

    def __init__(self, *args, **kwargs):
        super(FakeHuaweiStorage, self).__init__(*args, **kwargs)
        self._test_flg = None

    def _execute_cli(self, cmdIn):
        cmd = cmdIn.split(' ')[0].lower()
        if cmd == 'showsys':
            if ((self._test_flg == 'check_for_fail') or
                    (self._test_flg == 'check_for_T')):
                out = """/>showsys
==========================================================================
                                System Information
--------------------------------------------------------------------------
  System Name           | SN_S5500T-xu-0123456789
  Device Type           | Oceanstor S5500T
  Current System Mode   | Double Controllers Normal
  Mirroring Link Status | Link Up
  Location              |
  Time                  | 2013-01-01 01:01:01
  Product Version       | V100R005C00
===========================================================================
"""
            elif self._test_flg == 'check_for_Dorado2100G2':
                out = """/>showsys
==========================================================================
                                System Information
--------------------------------------------------------------------------
  System Name           | SN_Dorado2100_G2
  Device Type           | Oceanstor Dorado2100 G2
  Current System Mode   | Double Controllers Normal
  Mirroring Link Status | Link Up
  Location              |
  Time                  | 2013-01-01 01:01:01
  Product Version       | V100R001C00
===========================================================================
"""
            elif self._test_flg == 'check_for_Dorado5100':
                out = """/>showsys
==========================================================================
                                System Information
--------------------------------------------------------------------------
  System Name           | SN_Dorado5100
  Device Type           | Oceanstor Dorado5100
  Current System Mode   | Double Controllers Normal
  Mirroring Link Status | Link Up
  Location              |
  Time                  | 2013-01-01 01:01:01
  Product Version       | V100R001C00
===========================================================================
"""
        elif cmd == 'addhostmap':
            MapInfo['DEV LUN ID'] = LUNInfo['ID']
            MapInfo['LUN WWN'] = LUNInfo['LUN WWN']
            MapInfo['Host LUN ID'] = '0'
            out = 'command operates successfully'

        elif cmd == 'showhostmap':
            if MapInfo['DEV LUN ID'] is None:
                out = 'command operates successfully, but no information.'
            else:
                out = """/>showhostmap
==========================================================================
                           Map Information
--------------------------------------------------------------------------
  Map ID  Working Controller   Dev LUN ID  LUN WWN  Host LUN ID  Mapped to  \
  RAID ID  Dev LUN Cap(MB)  Map Type  Whether Command LUN  Pool ID
---------------------------------------------------------------------------
  2147483649  %s  %s  %s  %s  Host: %s   %s  %s  HOST  No --
===========================================================================
""" % (LUNInfo['Worker Controller'], LUNInfo['ID'], LUNInfo['LUN WWN'],
       MapInfo['Host ID'], MapInfo['Host ID'], LUNInfo['RAID Group ID'],
       str(int(LUNInfo['Size']) * 1024))

        elif cmd == 'delhostmap':
            MapInfo['DEV LUN ID'] = None
            MapInfo['LUN WWN'] = None
            MapInfo['Host LUN ID'] = None
            out = 'command operates successfully'

        elif cmd == 'createsnapshot':
            SnapshotInfo['Source LUN ID'] = LUNInfo['ID']
            SnapshotInfo['Source LUN Name'] = LUNInfo['Name']
            SnapshotInfo['ID'] = FakeSnapshot['id']
            SnapshotInfo['Name'] = self._name_translate(FakeSnapshot['name'])
            SnapshotInfo['Status'] = 'Disable'
            out = 'command operates successfully'

        elif cmd == 'actvsnapshot':
            SnapshotInfo['Status'] = 'Active'
            out = 'command operates successfully'

        elif cmd == 'disablesnapshot':
            SnapshotInfo['Status'] = 'Disable'
            out = 'command operates successfully'

        elif cmd == 'delsnapshot':
            SnapshotInfo['Source LUN ID'] = None
            SnapshotInfo['Source LUN Name'] = None
            SnapshotInfo['ID'] = None
            SnapshotInfo['Name'] = None
            SnapshotInfo['Status'] = None
            out = 'command operates successfully'

        elif cmd == 'showsnapshot':
            if SnapshotInfo['ID'] is None:
                out = 'command operates successfully, but no information.'
            else:
                out = """/>showsnapshot
==========================================================================
                             Snapshot Information
--------------------------------------------------------------------------
  Name                       ID     Type      Status     Time Stamp
--------------------------------------------------------------------------
  %s     %s     Public    %s     2013-01-15 14:21:13
==========================================================================
""" % (SnapshotInfo['Name'], SnapshotInfo['ID'], SnapshotInfo['Status'])

        elif cmd == 'showlunsnapshot':
            if SnapshotInfo['ID'] is None:
                out = """Current LUN is not a source LUN"""
            else:
                out = """/>showlunsnapshot -lun 2
==========================================================================
                               Snapshot of LUN
--------------------------------------------------------------------------
  Name                       ID     Type      Status     Time Stamp
--------------------------------------------------------------------------
  %s       %s    Public    %s     2013-01-15 14:17:19
==========================================================================
""" % (SnapshotInfo['Name'], SnapshotInfo['ID'], SnapshotInfo['Status'])

        elif cmd == 'createlun':
            if LUNInfo['ID'] is None:
                LUNInfo['Name'] = self._name_translate(FakeVolume['name'])
                LUNInfo['ID'] = FakeVolume['id']
                LUNInfo['Size'] = FakeVolume['size']
                LUNInfo['LUN WWN'] = FakeVolume['wwn']
                LUNInfo['Owner Controller'] = 'A'
                LUNInfo['Worker Controller'] = 'A'
                LUNInfo['RAID Group ID'] = FakePoolInfo['ID']
            else:
                LUNInfoCopy['Name'] = \
                    self._name_translate(FakeVolumeCopy['name'])
                LUNInfoCopy['ID'] = FakeVolumeCopy['ID']
                LUNInfoCopy['Size'] = FakeVolumeCopy['size']
                LUNInfoCopy['LUN WWN'] = FakeVolumeCopy['wwn']
                LUNInfoCopy['Owner Controller'] = 'A'
                LUNInfoCopy['Worker Controller'] = 'A'
                LUNInfoCopy['RAID Group ID'] = FakePoolInfo['ID']
            out = 'command operates successfully'

        elif cmd == 'dellun':
            LUNInfo['Name'] = None
            LUNInfo['ID'] = None
            LUNInfo['Size'] = None
            LUNInfo['LUN WWN'] = None
            LUNInfo['Owner Controller'] = None
            LUNInfo['Worker Controller'] = None
            LUNInfo['RAID Group ID'] = None
            out = 'command operates successfully'

        elif cmd == 'showlun':
            if LUNInfo['ID'] is None:
                out = 'command operates successfully, but no information.'
            elif LUNInfoCopy['ID'] is None:
                if ((self._test_flg == 'check_for_fail') or
                        (self._test_flg == 'check_for_T')):
                    out = """/>showlun
===========================================================================
                           LUN Information
---------------------------------------------------------------------------
  ID  RAID Group ID  Disk Pool ID  Status  Controller  Visible Capacity(MB) \
    LUN Name                            Stripe Unit Size(KB)    Lun Type
---------------------------------------------------------------------------
  %s  %s  --  Normal  %s  %s  %s  64  THICK
===========================================================================
""" % (LUNInfo['ID'], LUNInfo['RAID Group ID'], LUNInfo['Owner Controller'],
       str(int(LUNInfo['Size']) * 1024), LUNInfo['Name'])
                elif self._test_flg == 'check_for_Dorado2100G2':
                    out = """/>showlun
===========================================================================
                           LUN Information
---------------------------------------------------------------------------
  ID   Status   Controller  Visible Capacity(MB)   LUN Name  Lun Type
---------------------------------------------------------------------------
  %s   Normal   %s          %s                     %s         THICK
===========================================================================
""" % (LUNInfo['ID'], LUNInfo['Owner Controller'],
       str(int(LUNInfo['Size']) * 1024), LUNInfo['Name'])
                elif self._test_flg == 'check_for_Dorado5100':
                    out = """/>showlun
===========================================================================
                           LUN Information
---------------------------------------------------------------------------
  ID   RAIDgroup ID  Status   Controller  Visible Capacity(MB)   LUN Name
  Strip Unit Size(KB)  Lun Type
---------------------------------------------------------------------------
  %s      %s       Normal      %s       %s       %s        64        THICK
===========================================================================
""" % (LUNInfo['ID'], LUNInfo['RAID Group ID'],
       LUNInfo['Owner Controller'], str(int(LUNInfo['Size']) * 1024),
       LUNInfo['Name'])
            else:
                if ((self._test_flg == 'check_for_fail') or
                        (self._test_flg == 'check_for_T')):
                    out = """/>showlun
============================================================================
                               LUN Information
----------------------------------------------------------------------------
  ID  RAID Group ID  Disk Pool ID  Status  Controller  Visible Capacity(MB)\
   LUN Name  Stripe Unit Size(KB)    Lun Type
----------------------------------------------------------------------------
  %s  %s  --  Normal  %s  %s  %s  64   THICK
  %s  %s  --  Normal  %s  %s  %s  64   THICK
============================================================================
""" % (LUNInfo['ID'], LUNInfo['RAID Group ID'], LUNInfo['Owner Controller'],
       str(int(LUNInfo['Size']) * 1024), LUNInfo['Name'], LUNInfoCopy['ID'],
       LUNInfoCopy['RAID Group ID'], LUNInfoCopy['Owner Controller'],
       str(int(LUNInfoCopy['Size']) * 1024), LUNInfoCopy['Name'])
                elif self._test_flg == 'check_for_Dorado2100G2':
                    out = """/>showlun
===========================================================================
                           LUN Information
---------------------------------------------------------------------------
  ID   Status   Controller  Visible Capacity(MB)   LUN Name  Lun Type
---------------------------------------------------------------------------
  %s   Normal   %s          %s                     %s         THICK
  %s   Normal   %s          %s                     %s         THICK
===========================================================================
""" % (LUNInfo['ID'], LUNInfo['Owner Controller'],
       str(int(LUNInfo['Size']) * 1024), LUNInfo['Name'],
       LUNInfoCopy['ID'], LUNInfoCopy['Owner Controller'],
       str(int(LUNInfoCopy['Size']) * 1024), LUNInfoCopy['Name'])
                elif self._test_flg == 'check_for_Dorado5100':
                    out = """/>showlun
===========================================================================
                           LUN Information
---------------------------------------------------------------------------
  ID   RAIDgroup ID  Status  Controller  Visible Capacity(MB)   LUN Name  \
  Strip Unit Size(KB)  Lun Type
---------------------------------------------------------------------------
  %s      %s       Normal      %s      %s       %s        64        THICK
  %s      %s       Norma       %s      %s       %s        64        THICK
===========================================================================
""" % (LUNInfo['ID'], LUNInfo['RAID Group ID'], LUNInfo['Owner Controller'],
       str(int(LUNInfo['Size']) * 1024), LUNInfo['Name'],
       LUNInfoCopy['ID'], LUNInfoCopy['RAID Group ID'],
       LUNInfoCopy['Owner Controller'], str(int(LUNInfoCopy['Size']) * 1024),
       LUNInfoCopy['Name'])

        elif cmd == 'createhostgroup':
            MapInfo['Host Group ID'] = '1'
            MapInfo['Host Group Name'] = FakeConfInfo['HostGroup']
            out = 'command operates successfully'

        elif cmd == 'showhostgroup':
            if MapInfo['Host Group ID'] is None:
                out = """/>showhostgroup
============================================================
                   Host Group Information
------------------------------------------------------------
  Host Group ID    Name                File Engine Cluster
------------------------------------------------------------
  0                Default Group       NO
============================================================
"""
            else:
                out = """/>showhostgroup
============================================================
                   Host Group Information
------------------------------------------------------------
  Host Group ID    Name                File Engine Cluster
------------------------------------------------------------
  0                Default Group       NO
  %s                %s       NO
============================================================
""" % (MapInfo['Host Group ID'], MapInfo['Host Group Name'])

        elif cmd == 'addhost':
            MapInfo['Host ID'] = '1'
            MapInfo['Host Name'] = FakeConfInfo['HostnamePrefix'] + \
                str(hash(FakeConnector['initiator']))
            MapInfo['Os Type'] = 'Linux'
            out = 'command operates successfully'

        elif cmd == 'delhost':
            MapInfo['Host ID'] = None
            MapInfo['Host Name'] = None
            MapInfo['Os Type'] = None
            out = 'command operates successfully'

        elif cmd == 'showhost':
            if MapInfo['Host ID'] is None:
                out = 'command operates successfully, but no information.'
            else:
                out = """/>showhost
=======================================================
                   Host Information
-------------------------------------------------------
  Host ID    Host Name      Host Group ID    Os Type
-------------------------------------------------------
  %s          %s      %s                Linux
=======================================================
""" % (MapInfo['Host ID'], MapInfo['Host Name'], MapInfo['Host Group ID'])

        elif cmd == 'createluncopy':
            LUNCopy['Name'] = LUNInfoCopy['Name']
            LUNCopy['ID'] = FakeLUNCopy['ID']
            LUNCopy['Type'] = FakeLUNCopy['Type']
            LUNCopy['State'] = FakeLUNCopy['State']
            LUNCopy['Status'] = FakeLUNCopy['Status']
            out = 'command operates successfully'

        elif cmd == 'delluncopy':
            LUNCopy['Name'] = None
            LUNCopy['ID'] = None
            LUNCopy['Type'] = None
            LUNCopy['State'] = None
            LUNCopy['Status'] = None
            out = 'command operates successfully'

        elif cmd == 'chgluncopystatus':
            LUNCopy['State'] = 'Complete'
            out = 'command operates successfully'

        elif cmd == 'showluncopy':
            if LUNCopy['ID'] is None:
                out = 'command operates successfully, but no information.'
            else:
                out = """/>showluncopy
============================================================================
                            LUN Copy Information
----------------------------------------------------------------------------
  LUN Copy Name    LUN Copy ID    Type    LUN Copy State    LUN Copy Status
----------------------------------------------------------------------------
  %s       %s              %s    %s          %s
============================================================================
""" % (LUNCopy['Name'], LUNCopy['ID'], LUNCopy['Type'],
       LUNCopy['State'], LUNCopy['Status'])

        elif cmd == 'showiscsitgtname':
            if ((self._test_flg == 'check_for_fail') or
                    (self._test_flg == 'check_for_T')):
                out = """/>showiscsitgtname
============================================================================
                                 ISCSI Name
----------------------------------------------------------------------------
  Iscsi Name | %s
============================================================================
""" % FakeConfInfo['TargetIQN']
            elif (self._test_flg == 'check_for_Dorado2100G2' or
                  self._test_flg == 'check_for_Dorado5100'):
                out = """/>showiscsitgtname
============================================================================
                                 ISCSI Name
----------------------------------------------------------------------------
  Iscsi Name | %s
============================================================================
""" % FakeConfInfo['TargetIQN']

        elif cmd == 'showiscsiip':
            out = """/>showiscsiip
============================================================================
                          iSCSI IP Information
----------------------------------------------------------------------------
  Controller ID    Interface Module ID    Port ID    IP Address        Mask
----------------------------------------------------------------------------
  A                0                      P1         %s    255.255.255.0
============================================================================
""" % FakeConfInfo['Initiator TargetIP']

        elif cmd == 'addhostport':
            MapInfo['INI Port ID'] = HostPort['ID']
            MapInfo['INI Port Name'] = HostPort['Name']
            MapInfo['INI Port Info'] = HostPort['Info']
            out = 'command operates successfully'

        elif cmd == 'delhostport':
            MapInfo['INI Port ID'] = None
            MapInfo['INI Port Name'] = None
            MapInfo['INI Port Info'] = None
            out = 'command operates successfully'

        elif cmd == 'showhostport':
            if MapInfo['INI Port ID'] is None:
                out = 'command operates successfully, but no information.'
            else:
                out = """/>showhostport -host 3
==============================================================================
                        Host Port Information
------------------------------------------------------------------------------
Port ID  Port Name  Port Information  Port Type  Host ID  \
Link Status  Multipath Type
------------------------------------------------------------------------------
 %s          %s    %s    ISCSITGT           %s         Unconnected   Default
==============================================================================
""" % (MapInfo['INI Port ID'], MapInfo['INI Port Name'],
       MapInfo['INI Port Info'], MapInfo['Host ID'])

        elif cmd == 'addiscsiini':
            HostPort['ID'] = '1'
            HostPort['Name'] = 'iSCSIInitiator001'
            HostPort['Info'] = FakeConfInfo['Initiator Name']
            out = 'command operates successfully'

        elif cmd == 'deliscsiini':
            HostPort['ID'] = None
            HostPort['Name'] = None
            HostPort['Info'] = None
            out = 'command operates successfully'

        elif cmd == 'showiscsiini':
            if HostPort['ID'] is None:
                out = 'Error: The parameter is wrong.'
            else:
                out = """/>showiscsiini -ini iqn.1993-08.org\
.debian:01:503629a9d3f
========================================================
                 Initiator Information
--------------------------------------------------------
  Initiator Name                           Chap Status
--------------------------------------------------------
  %s    Disable
========================================================
""" % (HostPort['Info'])

        elif cmd == 'showrg':
            out = """/>showrg
=====================================================================
                      RAID Group Information
---------------------------------------------------------------------
  ID    Level    Status    Free Capacity(MB)    Disk List        Name
---------------------------------------------------------------------
  0     RAID6    Normal  1024  0,0;0,2;0,4;0,5;0,6;0,7;    RAID003
  %s     %s    %s    %s                %s    %s
=====================================================================
""" % (FakePoolInfo['ID'], FakePoolInfo['Level'],
       FakePoolInfo['Status'], FakePoolInfo['Free Capacity'],
       FakePoolInfo['Disk List'], FakePoolInfo['Name'])

        elif cmd == 'showrespool':
            out = """/>showrespool
============================================================================
                         Resource Pool Information
----------------------------------------------------------------------------
  Pool ID    Size(MB)    Usage(MB)    Valid Size(MB)    Alarm Threshold(%)
----------------------------------------------------------------------------
  A          5130.0      0.0          5130.0            80
  B          3082.0      0.0          3082.0            80
============================================================================
"""

        elif cmd == 'chglun':
            out = 'command operates successfully'

        out = out.replace('\n', '\r\n')
        return out

    def _get_lun_controller(self, lunid):
        pass
