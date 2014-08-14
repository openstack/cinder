
# Copyright (c) 2013 Huawei Technologies Co., Ltd.
# Copyright (c) 2012 OpenStack Foundation
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
Unit Tests for Huawei T and Dorado volume drivers.
"""

import os
import shutil
import socket
import tempfile
import time
from xml.dom.minidom import Document
from xml.etree import ElementTree as ET

import mox

from cinder import context
from cinder import exception
from cinder import ssh_utils
from cinder import test
from cinder.volume import configuration as conf
from cinder.volume.drivers.huawei import huawei_utils
from cinder.volume.drivers.huawei import HuaweiVolumeDriver
from cinder.volume.drivers.huawei import ssh_common
from cinder.volume import volume_types


LUN_INFO = {'ID': None,
            'Name': None,
            'Size': None,
            'LUN WWN': None,
            'Status': None,
            'Visible Capacity': None,
            'Disk Pool ID': None,
            'Cache Prefetch Strategy': None,
            'Lun Type': None,
            'Consumed Capacity': None,
            'Pool ID': None,
            'SnapShot ID': None,
            'LunCopy ID': None,
            'Owner Controller': None,
            'Worker Controller': None,
            'RAID Group ID': None}

CLONED_LUN_INFO = {'ID': None,
                   'Name': None,
                   'Size': None,
                   'LUN WWN': None,
                   'Status': None,
                   'Visible Capacity': None,
                   'Disk Pool ID': None,
                   'Cache Prefetch Strategy': None,
                   'Lun Type': None,
                   'Consumed Capacity': None,
                   'Pool ID': None,
                   'SnapShot ID': None,
                   'LunCopy ID': None,
                   'Owner Controller': None,
                   'Worker Controller': None,
                   'RAID Group ID': None}

SNAPSHOT_INFO = {'Source LUN ID': None,
                 'Source LUN Name': None,
                 'ID': None,
                 'Name': None,
                 'Type': 'Public',
                 'Status': None}

MAP_INFO = {'Host Group ID': None,
            'Host Group Name': None,
            'Host ID': None,
            'Host Name': None,
            'Os Type': None,
            'INI Port ID': None,
            'INI Port Name': None,
            'INI Port Info': None,
            'INI Port WWN': None,
            'INI Port Type': None,
            'Link Status': None,
            'LUN WWN': None,
            'DEV LUN ID': None,
            'Host LUN ID': None,
            'CHAP status': False}

HOST_PORT_INFO = {'ID': None,
                  'Name': None,
                  'Info': None,
                  'WWN': None,
                  'Type': None}

LUNCOPY_INFO = {'Name': None,
                'ID': None,
                'Type': None,
                'State': None,
                'Status': None}

LUNCOPY_SETTING = {'ID': '1',
                   'Type': 'FULL',
                   'State': 'Created',
                   'Status': 'Normal'}

POOL_SETTING = {'ID': '2',
                'Level': 'RAID6',
                'Status': 'Normal',
                'Free Capacity': '10240',
                'Disk List': '0,1;0,2;0,3;0,4;0,5;0,6',
                'Name': 'RAID_001',
                'Type': 'Thick'}

INITIATOR_SETTING = {'TargetIQN': 'iqn.2006-08.com.huawei:oceanspace:2103037:',
                     'TargetIQN-form': 'iqn.2006-08.com.huawei:oceanspace:'
                     '2103037::1020001:192.168.100.2',
                     'Initiator Name': 'iqn.1993-08.debian:01:ec2bff7ac3a3',
                     'Initiator TargetIP': '192.168.100.2',
                     'WWN': ['2011666666666565']}

FAKE_VOLUME = {'name': 'Volume-lele34fe-223f-dd33-4423-asdfghjklqwe',
               'id': 'lele34fe-223f-dd33-4423-asdfghjklqwe',
               'size': '2',
               'provider_auth': None,
               'volume_type_id': None,
               'provider_location': None}

FAKE_CLONED_VOLUME = {'name': 'Volume-jeje34fe-223f-dd33-4423-asdfghjklqwg',
                      'id': 'jeje34fe-223f-dd33-4423-asdfghjklqwg',
                      'size': '3',
                      'provider_auth': None,
                      'volume_type_id': None,
                      'provider_location': None}

FAKE_SNAPSHOT = {'name': 'keke34fe-223f-dd33-4423-asdfghjklqwf',
                 'id': '223f-dd33-4423-asdfghjklqwf',
                 'volume_name': 'Volume-lele34fe-223f-dd33-4423-asdfghjklqwe',
                 'provider_location': None}

FAKE_CONNECTOR = {'initiator': 'iqn.1993-08.debian:01:ec2bff7ac3a3',
                  'wwpns': ['1000000164s45126'],
                  'wwnns': ['2000666666666565'],
                  'host': 'fakehost',
                  'ip': '10.10.0.1'}

RESPOOL_A_SIM = {'Size': '10240', 'Valid Size': '5120'}
RESPOOL_B_SIM = {'Size': '10240', 'Valid Size': '10240'}
VOLUME_SNAP_ID = {'vol': '0', 'vol_copy': '1', 'snap': '2'}

cmd_error_list = []  # CLI cmds in this list will run failed
Curr_test = ['']  # show current testing driver


class FakeChannel():
    def __init__(self):
        if Curr_test[0] == 'T':
            self.simu = HuaweiTCLIResSimulator()
        elif Curr_test[0] == 'Dorado5100':
            self.simu = HuaweiDorado5100CLIResSimulator()
        else:
            self.simu = HuaweiDorado2100G2CLIResSimulator()

    def resize_pty(self, width=80, height=24):
        pass

    def settimeout(self, time):
        pass

    def send(self, s):
        self.command = s

    def recv(self, nbytes):
        command = self.command.split()
        cmd = command[0]
        params = command[1:]
        if cmd in cmd_error_list:
            reset_error_flg(cmd)
            out = self.command[:-1] + 'ERROR' + '\nadmin:/>'
            return out.replace('\n', '\r\n')
        func_name = 'cli_' + cmd
        cli_func = getattr(self.simu, func_name)
        out = cli_func(params)
        out = self.command[:-1] + out + '\nadmin:/>'
        return out.replace('\n', '\r\n')

    def close(self):
        pass


class FakeSSHClient():
    def invoke_shell(self):
        return FakeChannel()

    def get_transport(self):

        class transport():
            def __init__(self):
                self.sock = sock()

        class sock():
            def settimeout(self, time):
                pass

        return transport()

    def close(self):
        pass


class FakeSSHPool():
    def __init__(self, ip, port, conn_timeout, login, password=None,
                 *args, **kwargs):
        self.ip = ip
        self.port = port
        self.login = login
        self.password = password

    def create(self):
        return FakeSSHClient()

    def get(self):
        return FakeSSHClient()

    def put(self, ssh):
        pass

    def remove(self, ssh):
        pass


def Fake_sleep(time):
    pass


def Fake_change_file_mode(obj, filepath):
    pass


def create_fake_conf_file(filename):
    doc = Document()

    config = doc.createElement('config')
    doc.appendChild(config)

    storage = doc.createElement('Storage')
    config.appendChild(storage)
    product = doc.createElement('Product')
    product_text = doc.createTextNode('T')
    product.appendChild(product_text)
    storage.appendChild(product)
    config.appendChild(storage)
    protocol = doc.createElement('Protocol')
    protocol_text = doc.createTextNode('iSCSI')
    protocol.appendChild(protocol_text)
    storage.appendChild(protocol)
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
    luntype = doc.createElement('LUNType')
    luntype_text = doc.createTextNode('Thick')
    luntype.appendChild(luntype_text)
    lun.appendChild(luntype)

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

    os_type = doc.createElement('Host')
    os_type.setAttribute('OSType', 'Linux')
    os_type.setAttribute('HostIP', '10.10.0.1')
    config.appendChild(os_type)

    tmp_file = open(filename, 'w')
    tmp_file.write(doc.toprettyxml(indent=''))
    tmp_file.close()


def modify_conf(conf, item, val, attrib=None):
    tree = ET.parse(conf)
    root = tree.getroot()
    conf_item = root.find('%s' % item)
    if not attrib:
        conf_item.text = '%s' % val
    else:
        conf_item.attrib['%s' % attrib] = '%s' % val
    tree.write(conf, 'UTF-8')


def set_error_flg(cmd):
    cmd_error_list.append(cmd)


def reset_error_flg(cmd):
    cmd_error_list.remove(cmd)


class HuaweiTCLIResSimulator():
    def _paras_name(self, params):
        index = params.index('-n')
        return params[index + 1]

    def cli_showsys(self, params):
        pass

    def cli_createlun(self, params):
        lun_type = ('THIN' if '-pool' in params else 'THICK')
        if LUN_INFO['ID'] is None:
            LUN_INFO['Name'] = self._paras_name(params)
            LUN_INFO['ID'] = VOLUME_SNAP_ID['vol']
            LUN_INFO['Size'] = FAKE_VOLUME['size']
            LUN_INFO['Lun Type'] = lun_type
            LUN_INFO['Owner Controller'] = 'A'
            LUN_INFO['Worker Controller'] = 'A'
            LUN_INFO['RAID Group ID'] = POOL_SETTING['ID']
            FAKE_VOLUME['provider_location'] = LUN_INFO['ID']
        else:
            CLONED_LUN_INFO['Name'] = self._paras_name(params)
            CLONED_LUN_INFO['ID'] = VOLUME_SNAP_ID['vol_copy']
            CLONED_LUN_INFO['Size'] = FAKE_CLONED_VOLUME['size']
            CLONED_LUN_INFO['Lun Type'] = lun_type
            CLONED_LUN_INFO['Owner Controller'] = 'A'
            CLONED_LUN_INFO['Worker Controller'] = 'A'
            CLONED_LUN_INFO['RAID Group ID'] = POOL_SETTING['ID']
            FAKE_CLONED_VOLUME['provider_location'] = CLONED_LUN_INFO['ID']
        out = 'command operates successfully'
        return out

    def cli_showlun(self, params):
        if '-lun' not in params:
            if LUN_INFO['ID'] is None:
                out = 'command operates successfully, but no information.'
            elif CLONED_LUN_INFO['ID'] is None:
                msg = """/>showlun
===========================================================================
                           LUN Information
---------------------------------------------------------------------------
  ID  RAID Group ID  Disk Pool ID  Status  Controller  Visible Capacity(MB) \
  LUN Name   Stripe Unit Size(KB)   Lun Type
---------------------------------------------------------------------------
  %s    %s    --    Normal    %s    %s    %s    64    THICK
===========================================================================
"""
                out = msg % (LUN_INFO['ID'], LUN_INFO['RAID Group ID'],
                             LUN_INFO['Owner Controller'],
                             str(int(LUN_INFO['Size']) * 1024),
                             LUN_INFO['Name'])
            else:
                msg = """/>showlun
============================================================================
                               LUN Information
----------------------------------------------------------------------------
  ID  RAID Group ID  Disk Pool ID  Status  Controller  Visible Capacity(MB)\
  LUN Name   Stripe Unit Size(KB)   Lun Type
----------------------------------------------------------------------------
  %s    %s    --    Normal    %s    %s    %s    64    THICK
  %s    %s    --    Normal    %s    %s    %s    64    THICK
============================================================================
"""
                out = msg % (
                    LUN_INFO['ID'], LUN_INFO['RAID Group ID'],
                    LUN_INFO['Owner Controller'],
                    str(int(LUN_INFO['Size']) * 1024), LUN_INFO['Name'],
                    CLONED_LUN_INFO['ID'], CLONED_LUN_INFO['RAID Group ID'],
                    CLONED_LUN_INFO['Owner Controller'],
                    str(int(CLONED_LUN_INFO['Size']) * 1024),
                    CLONED_LUN_INFO['Name'])

        elif params[params.index('-lun') + 1] in VOLUME_SNAP_ID.values():
            msg = """/>showlun
================================================
                 LUN Information
------------------------------------------------
  ID                     |  %s
  Name                   |  %s
  LUN WWN                |  --
  Visible Capacity       |  %s
  RAID GROUP ID          |  %s
  Owning Controller      |  %s
  Workong Controller     |  %s
  Lun Type               |  %s
  SnapShot ID            |  %s
  LunCopy ID             |  %s
================================================
"""
            out = msg % (
                (LUN_INFO['ID'], LUN_INFO['Name'],
                 LUN_INFO['Visible Capacity'],
                 LUN_INFO['RAID Group ID'], LUN_INFO['Owner Controller'],
                 LUN_INFO['Worker Controller'], LUN_INFO['Lun Type'],
                 LUN_INFO['SnapShot ID'], LUN_INFO['LunCopy ID'])
                if (params[params.index('-lun') + 1] ==
                    VOLUME_SNAP_ID['vol']) else
                (CLONED_LUN_INFO['ID'], CLONED_LUN_INFO['Name'],
                 CLONED_LUN_INFO['Visible Capacity'],
                 CLONED_LUN_INFO['RAID Group ID'],
                 CLONED_LUN_INFO['Owner Controller'],
                 CLONED_LUN_INFO['Worker Controller'],
                 CLONED_LUN_INFO['Lun Type'],
                 CLONED_LUN_INFO['SnapShot ID'],
                 CLONED_LUN_INFO['LunCopy ID']))
        else:
            out = 'ERROR: The object does not exist.'
        return out

    def cli_dellun(self, params):
        if params[params.index('-lun') + 1] == VOLUME_SNAP_ID['vol']:
            LUN_INFO['Name'] = None
            LUN_INFO['ID'] = None
            LUN_INFO['Size'] = None
            LUN_INFO['Lun Type'] = None
            LUN_INFO['LUN WWN'] = None
            LUN_INFO['Owner Controller'] = None
            LUN_INFO['Worker Controller'] = None
            LUN_INFO['RAID Group ID'] = None
            FAKE_VOLUME['provider_location'] = None
        else:
            CLONED_LUN_INFO['Name'] = None
            CLONED_LUN_INFO['ID'] = None
            CLONED_LUN_INFO['Size'] = None
            CLONED_LUN_INFO['Lun Type'] = None
            CLONED_LUN_INFO['LUN WWN'] = None
            CLONED_LUN_INFO['Owner Controller'] = None
            CLONED_LUN_INFO['Worker Controller'] = None
            CLONED_LUN_INFO['RAID Group ID'] = None
            CLONED_LUN_INFO['provider_location'] = None
            FAKE_CLONED_VOLUME['provider_location'] = None
        out = 'command operates successfully'
        return out

    def cli_showrg(self, params):
        msg = """/>showrg
=====================================================================
                      RAID Group Information
---------------------------------------------------------------------
  ID    Level    Status    Free Capacity(MB)    Disk List    Name
---------------------------------------------------------------------
  0     RAID6    Normal    1024                 0,0;0,2;     RAID003
  %s    %s       %s        %s                   %s           %s
=====================================================================
-"""
        out = msg % (POOL_SETTING['ID'], POOL_SETTING['Level'],
                     POOL_SETTING['Status'], POOL_SETTING['Free Capacity'],
                     POOL_SETTING['Disk List'], POOL_SETTING['Name'])
        return out

    def cli_showpool(self, params):
        out = """/>showpool
=====================================================================
                      Pool Information
---------------------------------------------------------------------
  Level    Status    Available Capacity(MB)    Disk List
---------------------------------------------------------------------
  RAID6    Normal    %s                        0,0;0,2;0,4;0,5;
=====================================================================
-""" % POOL_SETTING['Free Capacity']
        return out

    def cli_createluncopy(self, params):
        src_id = params[params.index('-slun') + 1]
        tgt_id = params[params.index('-tlun') + 1]
        LUNCOPY_INFO['Name'] = 'OpenStack_%s_%s' % (src_id, tgt_id)
        LUNCOPY_INFO['ID'] = LUNCOPY_SETTING['ID']
        LUNCOPY_INFO['Type'] = LUNCOPY_SETTING['Type']
        LUNCOPY_INFO['State'] = LUNCOPY_SETTING['State']
        LUNCOPY_INFO['Status'] = LUNCOPY_SETTING['Status']
        out = 'command operates successfully'
        return out

    def cli_chgluncopystatus(self, params):
        LUNCOPY_INFO['State'] = 'Start'
        out = 'command operates successfully'
        return out

    def cli_showluncopy(self, params):
        if LUNCOPY_INFO['State'] == 'Start':
            LUNCOPY_INFO['State'] = 'Copying'
        elif LUNCOPY_INFO['State'] == 'Copying':
            LUNCOPY_INFO['State'] = 'Complete'
        msg = """/>showluncopy
============================================================================
                            LUN Copy Information
----------------------------------------------------------------------------
  LUN Copy Name    LUN Copy ID    Type    LUN Copy State    LUN Copy Status
----------------------------------------------------------------------------
  %s               %s             %s      %s                %s
============================================================================
"""
        out = msg % (LUNCOPY_INFO['Name'], LUNCOPY_INFO['ID'],
                     LUNCOPY_INFO['Type'], LUNCOPY_INFO['State'],
                     LUNCOPY_INFO['Status'])
        return out

    def cli_delluncopy(self, params):
        LUNCOPY_INFO['Name'] = None
        LUNCOPY_INFO['ID'] = None
        LUNCOPY_INFO['Type'] = None
        LUNCOPY_INFO['State'] = None
        LUNCOPY_INFO['Status'] = None
        out = 'command operates successfully'
        return out

    def cli_createsnapshot(self, params):
        SNAPSHOT_INFO['Source LUN ID'] = LUN_INFO['ID']
        SNAPSHOT_INFO['Source LUN Name'] = LUN_INFO['Name']
        SNAPSHOT_INFO['ID'] = VOLUME_SNAP_ID['snap']
        SNAPSHOT_INFO['Name'] = self._paras_name(params)
        SNAPSHOT_INFO['Status'] = 'Disable'
        out = 'command operates successfully'
        return out

    def cli_showsnapshot(self, params):
        if SNAPSHOT_INFO['ID'] is None:
            out = 'command operates successfully, but no information.'
        else:
            out = """/>showsnapshot
==========================================================================
                             Snapshot Information
--------------------------------------------------------------------------
  Name         ID         Type         Status        Time Stamp
--------------------------------------------------------------------------
  %s           %s         Public       %s            2013-01-15 14:21:13
==========================================================================
""" % (SNAPSHOT_INFO['Name'], SNAPSHOT_INFO['ID'], SNAPSHOT_INFO['Status'])
        return out

    def cli_actvsnapshot(self, params):
        SNAPSHOT_INFO['Status'] = 'Active'
        FAKE_SNAPSHOT['provider_location'] = SNAPSHOT_INFO['ID']
        out = 'command operates successfully'
        return out

    def cli_disablesnapshot(self, params):
        SNAPSHOT_INFO['Status'] = 'Disable'
        out = 'command operates successfully'
        return out

    def cli_delsnapshot(self, params):
        SNAPSHOT_INFO['Source LUN ID'] = None
        SNAPSHOT_INFO['Source LUN Name'] = None
        SNAPSHOT_INFO['ID'] = None
        SNAPSHOT_INFO['Name'] = None
        SNAPSHOT_INFO['Status'] = None
        FAKE_SNAPSHOT['provider_location'] = None
        out = 'command operates successfully'
        return out

    def cli_showrespool(self, params):
        msg = """/>showrespool
===========================================================================
                         Resource Pool Information
---------------------------------------------------------------------------
  Pool ID    Size(MB)    Usage(MB)    Valid Size(MB)    Alarm Threshold
---------------------------------------------------------------------------
  A          %s          0.0          %s                80
  B          %s          0.0         %s                80
===========================================================================
-"""
        out = msg % (RESPOOL_A_SIM['Size'], RESPOOL_A_SIM['Valid Size'],
                     RESPOOL_B_SIM['Size'], RESPOOL_B_SIM['Valid Size'])
        return out

    def cli_showiscsitgtname(self, params):
        iqn = INITIATOR_SETTING['TargetIQN']
        out = """/>showiscsitgtname
===================================================================
                    ISCSI Name
-------------------------------------------------------------------
  Iscsi Name     | %s
===================================================================
""" % iqn
        return out

    def cli_showiscsiip(self, params):
        out = """/>showiscsiip
============================================================================
                          iSCSI IP Information
----------------------------------------------------------------------------
  Controller ID   Interface Module ID   Port ID   IP Address   Mask
----------------------------------------------------------------------------
  B               0                     P1        %s           255.255.255.0
============================================================================
-""" % INITIATOR_SETTING['Initiator TargetIP']
        return out

    def cli_showhostgroup(self, params):
        if MAP_INFO['Host Group ID'] is None:
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
  %s               %s                  NO
============================================================
""" % (MAP_INFO['Host Group ID'], MAP_INFO['Host Group Name'])
        return out

    def cli_createhostgroup(self, params):
        MAP_INFO['Host Group ID'] = '1'
        MAP_INFO['Host Group Name'] = 'HostGroup_OpenStack'
        out = 'command operates successfully'
        return out

    def cli_showhost(self, params):
        if MAP_INFO['Host ID'] is None:
            out = 'command operates successfully, but no information.'
        else:
            out = """/>showhost
=======================================================
                   Host Information
-------------------------------------------------------
  Host ID    Host Name      Host Group ID    Os Type
-------------------------------------------------------
  %s         %s             %s               Linux
=======================================================
""" % (MAP_INFO['Host ID'], MAP_INFO['Host Name'], MAP_INFO['Host Group ID'])
        return out

    def cli_addhost(self, params):
        MAP_INFO['Host ID'] = '1'
        MAP_INFO['Host Name'] = 'Host_' + FAKE_CONNECTOR['host']
        MAP_INFO['Os Type'] = 'Linux'
        out = 'command operates successfully'
        return out

    def cli_delhost(self, params):
        MAP_INFO['Host ID'] = None
        MAP_INFO['Host Name'] = None
        MAP_INFO['Os Type'] = None
        out = 'command operates successfully'
        return out

    def cli_showiscsiini(self, params):
        if HOST_PORT_INFO['ID'] is None:
            out = 'Error: The parameter is wrong.'
        else:
            out = """/>showiscsiini
========================================================
                 Initiator Information
--------------------------------------------------------
  Initiator Name                     Chap Status
--------------------------------------------------------
  %s                                 Disable
========================================================
""" % HOST_PORT_INFO['Info']
        return out

    def cli_addiscsiini(self, params):
        HOST_PORT_INFO['ID'] = '1'
        HOST_PORT_INFO['Name'] = 'iSCSIInitiator001'
        HOST_PORT_INFO['Info'] = INITIATOR_SETTING['Initiator Name']
        HOST_PORT_INFO['Type'] = 'ISCSITGT'
        out = 'command operates successfully'
        return out

    def cli_deliscsiini(self, params):
        HOST_PORT_INFO['ID'] = None
        HOST_PORT_INFO['Name'] = None
        HOST_PORT_INFO['Info'] = None
        HOST_PORT_INFO['Type'] = None
        out = 'command operates successfully'
        return out

    def cli_showhostport(self, params):
        if MAP_INFO['INI Port ID'] is None:
            out = 'command operates successfully, but no information.'
        else:
            msg = """/>showhostport
============================================================================
                        Host Port Information
----------------------------------------------------------------------------
Port ID  Port Name  Port Information  Port Type  Host ID  Link Status \
Multipath Type
----------------------------------------------------------------------------
 %s      %s       %s       %s       %s       Unconnected       Default
============================================================================
"""
            out = msg % (MAP_INFO['INI Port ID'], MAP_INFO['INI Port Name'],
                         MAP_INFO['INI Port Info'], MAP_INFO['INI Port Type'],
                         MAP_INFO['Host ID'])
        return out

    def cli_addhostport(self, params):
        MAP_INFO['INI Port ID'] = HOST_PORT_INFO['ID']
        MAP_INFO['INI Port Name'] = HOST_PORT_INFO['Name']
        MAP_INFO['INI Port Info'] = HOST_PORT_INFO['Info']
        MAP_INFO['INI Port Type'] = HOST_PORT_INFO['Type']
        out = 'command operates successfully'
        return out

    def cli_delhostport(self, params):
        MAP_INFO['INI Port ID'] = None
        MAP_INFO['INI Port Name'] = None
        MAP_INFO['INI Port Info'] = None
        MAP_INFO['INI Port Type'] = None
        HOST_PORT_INFO['ID'] = None
        HOST_PORT_INFO['Name'] = None
        HOST_PORT_INFO['Info'] = None
        HOST_PORT_INFO['Type'] = None
        out = 'command operates successfully'
        return out

    def cli_showhostmap(self, params):
        if MAP_INFO['DEV LUN ID'] is None:
            out = 'command operates successfully, but no information.'
        else:
            msg = """/>showhostmap
===========================================================================
                           Map Information
---------------------------------------------------------------------------
  Map ID   Working Controller   Dev LUN ID   LUN WWN   Host LUN ID  Mapped to\
  RAID ID   Dev LUN Cap(MB)   Map Type   Whether Command LUN   Pool ID
----------------------------------------------------------------------------
  2147483649   %s   %s   %s   %s   Host: %s   %s   %s   HOST   No   --
============================================================================
"""
            out = msg % (LUN_INFO['Worker Controller'], LUN_INFO['ID'],
                         LUN_INFO['LUN WWN'], MAP_INFO['Host LUN ID'],
                         MAP_INFO['Host ID'], LUN_INFO['RAID Group ID'],
                         str(int(LUN_INFO['Size']) * 1024))
        return out

    def cli_addhostmap(self, params):
        MAP_INFO['DEV LUN ID'] = LUN_INFO['ID']
        MAP_INFO['LUN WWN'] = LUN_INFO['LUN WWN']
        MAP_INFO['Host LUN ID'] = '2'
        MAP_INFO['Link Status'] = 'Linked'
        out = 'command operates successfully'
        return out

    def cli_delhostmap(self, params):
        if MAP_INFO['Link Status'] == 'Linked':
            MAP_INFO['Link Status'] = 'Deleting'
            out = 'there are IOs accessing the system, please try later'
        else:
            MAP_INFO['Link Status'] = None
            MAP_INFO['DEV LUN ID'] = None
            MAP_INFO['LUN WWN'] = None
            MAP_INFO['Host LUN ID'] = None
            out = 'command operates successfully'
        return out

    def cli_showfreeport(self, params):
        out = """/>showfreeport
=======================================================================
                      Host Free Port Information
-----------------------------------------------------------------------
  WWN Or MAC          Type    Location              Connection Status
-----------------------------------------------------------------------
  1000000164s45126    FC      Primary Controller    Connected
=======================================================================
"""
        HOST_PORT_INFO['ID'] = '2'
        HOST_PORT_INFO['Name'] = 'FCInitiator001'
        HOST_PORT_INFO['Info'] = '1000000164s45126'
        HOST_PORT_INFO['Type'] = 'FC'
        return out

    def cli_showhostpath(self, params):
        host = params[params.index('-host') + 1]
        out = """/>showhostpath -host 1
=======================================
        Multi Path Information
---------------------------------------
  Host ID           | %s
  Controller ID     | B
  Port Type         | FC
  Initiator WWN     | 1000000164s45126
  Target WWN        | %s
  Host Port ID      | 0
  Link Status       | Normal
=======================================
""" % (host, INITIATOR_SETTING['WWN'][0])
        return out

    def cli_showfcmode(self, params):
        out = """/>showfcport
=========================================================================
                      FC Port Topology Mode
-------------------------------------------------------------------------
  Controller ID   Interface Module ID   Port ID   WWN    Current Mode
-------------------------------------------------------------------------
  B               1                     P0        %s     --
=========================================================================
-""" % INITIATOR_SETTING['WWN'][0]
        return out

    def cli_chglun(self, params):
        if params[params.index('-lun') + 1] == VOLUME_SNAP_ID['vol']:
            LUN_INFO['Owner Controller'] = 'B'
        else:
            CLONED_LUN_INFO['Owner Controller'] = 'B'
        out = 'command operates successfully'
        return out

    def cli_addluntoextlun(self, params):
        LUN_INFO['Size'] = int(LUN_INFO['Size']) + int(CLONED_LUN_INFO['Size'])
        out = 'command operates successfully'
        return out

    def cli_rmlunfromextlun(self, patams):
        LUN_INFO['Size'] = int(LUN_INFO['Size']) - int(CLONED_LUN_INFO['Size'])
        out = 'command operates successfully'
        return out


class HuaweiDorado5100CLIResSimulator(HuaweiTCLIResSimulator):
    def cli_showsys(self, params):
        out = """/>showsys
=============================================================
                                System Information
-------------------------------------------------------------
  System Name           | SN_Dorado5100
  Device Type           | Oceanstor Dorado5100
  Current System Mode   | Double Controllers Normal
  Mirroring Link Status | Link Up
  Location              |
  Time                  | 2013-01-01 01:01:01
  Product Version       | V100R001C00
=============================================================
"""
        return out

    def cli_showlun(self, params):
        if '-lun' not in params:
            if LUN_INFO['ID'] is None:
                out = 'command operates successfully, but no information.'
            elif CLONED_LUN_INFO['ID'] is None:
                msg = """/>showlun
===========================================================================
                           LUN Information
---------------------------------------------------------------------------
  ID   RAIDgroup ID  Status   Controller  Visible Capacity(MB)   LUN Name..\
  Strip Unit Size(KB)   Lun Type
---------------------------------------------------------------------------
  %s      %s       Normal       %s      %s       %s       64       THICK
===========================================================================
"""
                out = msg % (LUN_INFO['ID'], LUN_INFO['RAID Group ID'],
                             LUN_INFO['Owner Controller'],
                             str(int(LUN_INFO['Size']) * 1024),
                             LUN_INFO['Name'])
            else:
                msg = """/>showlun
===========================================================================
                           LUN Information
---------------------------------------------------------------------------
  ID   RAIDgroup ID   Status   Controller   Visible Capacity(MB)   LUN Name \
  Strip Unit Size(KB)   Lun Type
---------------------------------------------------------------------------
  %s      %s       Normal      %s      %s       %s        64       THICK
  %s      %s       Norma       %s      %s       %s        64       THICK
===========================================================================
"""
                out = msg % (LUN_INFO['ID'], LUN_INFO['RAID Group ID'],
                             LUN_INFO['Owner Controller'],
                             str(int(LUN_INFO['Size']) * 1024),
                             LUN_INFO['Name'], CLONED_LUN_INFO['ID'],
                             CLONED_LUN_INFO['RAID Group ID'],
                             CLONED_LUN_INFO['Owner Controller'],
                             str(int(CLONED_LUN_INFO['Size']) * 1024),
                             CLONED_LUN_INFO['Name'])
        elif params[params.index('-lun') + 1] in VOLUME_SNAP_ID.values():
            msg = """/>showlun
================================================
                 LUN Information
------------------------------------------------
  ID                     |  %s
  Name                   |  %s
  LUN WWN                |  --
  Visible Capacity       |  %s
  RAID GROUP ID          |  %s
  Owning Controller      |  %s
  Workong Controller     |  %s
  Lun Type               |  %s
  SnapShot ID            |  %s
  LunCopy ID             |  %s
================================================
"""
            out = msg % (
                (LUN_INFO['ID'], LUN_INFO['Name'],
                 LUN_INFO['Visible Capacity'],
                 LUN_INFO['RAID Group ID'], LUN_INFO['Owner Controller'],
                 LUN_INFO['Worker Controller'], LUN_INFO['Lun Type'],
                 LUN_INFO['SnapShot ID'], LUN_INFO['LunCopy ID'])
                if (params[params.index('-lun') + 1] ==
                    VOLUME_SNAP_ID['vol']) else
                (CLONED_LUN_INFO['ID'], CLONED_LUN_INFO['Name'],
                 CLONED_LUN_INFO['Visible Capacity'],
                 CLONED_LUN_INFO['RAID Group ID'],
                 CLONED_LUN_INFO['Owner Controller'],
                 CLONED_LUN_INFO['Worker Controller'],
                 CLONED_LUN_INFO['Lun Type'], CLONED_LUN_INFO['SnapShot ID'],
                 CLONED_LUN_INFO['LunCopy ID']))
        else:
            out = 'ERROR: The object does not exist.'
        return out


class HuaweiDorado2100G2CLIResSimulator(HuaweiTCLIResSimulator):
    def cli_showsys(self, params):
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
        return out

    def cli_createlun(self, params):
        lun_type = ('THIN' if params[params.index('-type') + 1] == '2' else
                    'THICK')
        if LUN_INFO['ID'] is None:
            LUN_INFO['Name'] = self._paras_name(params)
            LUN_INFO['ID'] = VOLUME_SNAP_ID['vol']
            LUN_INFO['Size'] = FAKE_VOLUME['size']
            LUN_INFO['Lun Type'] = lun_type
            LUN_INFO['Owner Controller'] = 'A'
            LUN_INFO['Worker Controller'] = 'A'
            LUN_INFO['RAID Group ID'] = POOL_SETTING['ID']
            FAKE_VOLUME['provider_location'] = LUN_INFO['ID']
        else:
            CLONED_LUN_INFO['Name'] = self._paras_name(params)
            CLONED_LUN_INFO['ID'] = VOLUME_SNAP_ID['vol_copy']
            CLONED_LUN_INFO['Size'] = FAKE_CLONED_VOLUME['size']
            CLONED_LUN_INFO['Lun Type'] = lun_type
            CLONED_LUN_INFO['Owner Controller'] = 'A'
            CLONED_LUN_INFO['Worker Controller'] = 'A'
            CLONED_LUN_INFO['RAID Group ID'] = POOL_SETTING['ID']
            CLONED_LUN_INFO['provider_location'] = CLONED_LUN_INFO['ID']
            FAKE_CLONED_VOLUME['provider_location'] = CLONED_LUN_INFO['ID']
        out = 'command operates successfully'
        return out

    def cli_showlun(self, params):
        if '-lun' not in params:
            if LUN_INFO['ID'] is None:
                out = 'command operates successfully, but no information.'
            elif CLONED_LUN_INFO['ID'] is None:
                msg = """/>showlun
===========================================================================
                           LUN Information
---------------------------------------------------------------------------
  ID   Status   Controller  Visible Capacity(MB)   LUN Name  Lun Type
---------------------------------------------------------------------------
  %s   Normal   %s          %s                     %s        THICK
===========================================================================
"""
                out = msg % (LUN_INFO['ID'], LUN_INFO['Owner Controller'],
                             str(int(LUN_INFO['Size']) * 1024),
                             LUN_INFO['Name'])
            else:
                msg = """/>showlun
===========================================================================
                           LUN Information
---------------------------------------------------------------------------
  ID   Status   Controller  Visible Capacity(MB)   LUN Name  Lun Type
---------------------------------------------------------------------------
  %s   Normal   %s          %s                     %s         THICK
  %s   Normal   %s          %s                     %s         THICK
===========================================================================
"""
                out = msg % (LUN_INFO['ID'], LUN_INFO['Owner Controller'],
                             str(int(LUN_INFO['Size']) * 1024),
                             LUN_INFO['Name'],
                             CLONED_LUN_INFO['ID'],
                             CLONED_LUN_INFO['Owner Controller'],
                             str(int(CLONED_LUN_INFO['Size']) * 1024),
                             CLONED_LUN_INFO['Name'])

        elif params[params.index('-lun') + 1] in VOLUME_SNAP_ID.values():
            msg = """/>showlun
================================================
                 LUN Information
------------------------------------------------
  ID                     |  %s
  Name                   |  %s
  LUN WWN                |  --
  Visible Capacity       |  %s
  RAID GROUP ID          |  %s
  Owning Controller      |  %s
  Workong Controller     |  %s
  Lun Type               |  %s
  SnapShot ID            |  %s
  LunCopy ID             |  %s
================================================
"""
            out = msg % (
                (LUN_INFO['ID'], LUN_INFO['Name'],
                 LUN_INFO['Visible Capacity'],
                 LUN_INFO['RAID Group ID'], LUN_INFO['Owner Controller'],
                 LUN_INFO['Worker Controller'], LUN_INFO['Lun Type'],
                 LUN_INFO['SnapShot ID'], LUN_INFO['LunCopy ID'])
                if params[params.index('-lun')] == VOLUME_SNAP_ID['vol'] else
                (CLONED_LUN_INFO['ID'], CLONED_LUN_INFO['Name'],
                 CLONED_LUN_INFO['Visible Capacity'],
                 CLONED_LUN_INFO['RAID Group ID'],
                 CLONED_LUN_INFO['Owner Controller'],
                 CLONED_LUN_INFO['Worker Controller'],
                 CLONED_LUN_INFO['Lun Type'], CLONED_LUN_INFO['SnapShot ID'],
                 CLONED_LUN_INFO['LunCopy ID']))

        else:
            out = 'ERROR: The object does not exist.'

        return out


class HuaweiTISCSIDriverTestCase(test.TestCase):
    def __init__(self, *args, **kwargs):
        super(HuaweiTISCSIDriverTestCase, self).__init__(*args, **kwargs)

    def setUp(self):
        super(HuaweiTISCSIDriverTestCase, self).setUp()

        self.tmp_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp_dir)

        self.fake_conf_file = self.tmp_dir + '/cinder_huawei_conf.xml'
        self.addCleanup(os.remove, self.fake_conf_file)

        create_fake_conf_file(self.fake_conf_file)
        self.configuration = mox.MockObject(conf.Configuration)
        self.configuration.cinder_huawei_conf_file = self.fake_conf_file
        self.configuration.append_config_values(mox.IgnoreArg())

        self.stubs.Set(time, 'sleep', Fake_sleep)
        self.stubs.Set(ssh_utils, 'SSHPool', FakeSSHPool)
        self.stubs.Set(ssh_common.TseriesCommon, '_change_file_mode',
                       Fake_change_file_mode)
        self._init_driver()

    def _init_driver(self):
        Curr_test[0] = 'T'
        self.driver = HuaweiVolumeDriver(configuration=self.configuration)
        self.driver.do_setup(None)

    def test_conf_invalid(self):
        # Test config file not found
        tmp_fonf_file = '/xxx/cinder_huawei_conf.xml'
        tmp_configuration = mox.MockObject(conf.Configuration)
        tmp_configuration.cinder_huawei_conf_file = tmp_fonf_file
        tmp_configuration.append_config_values(mox.IgnoreArg())
        self.assertRaises(IOError,
                          HuaweiVolumeDriver,
                          configuration=tmp_configuration)
        # Test Product and Protocol invalid
        tmp_dict = {'Storage/Product': 'T', 'Storage/Protocol': 'iSCSI'}
        for k, v in tmp_dict.items():
            modify_conf(self.fake_conf_file, k, 'xx')
            self.assertRaises(exception.InvalidInput,
                              HuaweiVolumeDriver,
                              configuration=self.configuration)
            modify_conf(self.fake_conf_file, k, v)
        # Test ctr ip, UserName and password unspecified
        tmp_dict = {'Storage/ControllerIP0': '10.10.10.1',
                    'Storage/ControllerIP1': '10.10.10.2',
                    'Storage/UserName': 'admin',
                    'Storage/UserPassword': '123456'}
        for k, v in tmp_dict.items():
            modify_conf(self.fake_conf_file, k, '')
            tmp_driver = HuaweiVolumeDriver(configuration=self.configuration)
            self.assertRaises(exception.InvalidInput,
                              tmp_driver.do_setup, None)
            modify_conf(self.fake_conf_file, k, v)
        # Test StoragePool unspecified
        modify_conf(self.fake_conf_file, 'LUN/StoragePool', '', attrib='Name')
        tmp_driver = HuaweiVolumeDriver(configuration=self.configuration)
        self.assertRaises(exception.InvalidInput,
                          tmp_driver.do_setup, None)
        modify_conf(self.fake_conf_file, 'LUN/StoragePool', 'RAID_001',
                    attrib='Name')
        # Test LUN type invalid
        modify_conf(self.fake_conf_file, 'LUN/LUNType', 'thick')
        tmp_driver = HuaweiVolumeDriver(configuration=self.configuration)
        tmp_driver.do_setup(None)
        self.assertRaises(exception.InvalidInput,
                          tmp_driver.create_volume, FAKE_VOLUME)
        modify_conf(self.fake_conf_file, 'LUN/LUNType', 'Thick')
        # Test OSType invalid
        modify_conf(self.fake_conf_file, 'Host', 'invalid_type',
                    attrib='OSType')
        tmp_driver = HuaweiVolumeDriver(configuration=self.configuration)
        self.assertRaises(exception.InvalidInput,
                          tmp_driver.do_setup, None)
        modify_conf(self.fake_conf_file, 'Host', 'Linux', attrib='OSType')
        # Test TargetIP not found
        modify_conf(self.fake_conf_file, 'iSCSI/DefaultTargetIP', '')
        modify_conf(self.fake_conf_file, 'iSCSI/Initiator', '', attrib='Name')
        tmp_driver = HuaweiVolumeDriver(configuration=self.configuration)
        tmp_driver.do_setup(None)
        tmp_driver.create_volume(FAKE_VOLUME)
        self.assertRaises(exception.InvalidInput,
                          tmp_driver.initialize_connection,
                          FAKE_VOLUME, FAKE_CONNECTOR)
        tmp_driver.delete_volume(FAKE_VOLUME)
        modify_conf(self.fake_conf_file, 'iSCSI/DefaultTargetIP',
                    '192.168.100.1')
        modify_conf(self.fake_conf_file, 'iSCSI/Initiator',
                    'iqn.1993-08.debian:01:ec2bff7ac3a3', attrib='Name')

    def test_volume_type(self):
        ctxt = context.get_admin_context()
        extra_specs = {'drivers:LUNType': 'Thin'}
        type_ref = volume_types.create(ctxt, 'THIN', extra_specs)
        FAKE_VOLUME['volume_type_id'] = type_ref['id']
        self.driver.create_volume(FAKE_VOLUME)
        self.assertEqual(LUN_INFO["ID"], VOLUME_SNAP_ID['vol'])
        self.assertEqual(LUN_INFO['Lun Type'], 'THIN')
        self.driver.delete_volume(FAKE_VOLUME)
        FAKE_VOLUME['volume_type_id'] = None

        # Test volume type invalid
        extra_specs = {'drivers:InvalidLUNType': 'Thin'}
        type_ref = volume_types.create(ctxt, 'Invalid_THIN', extra_specs)
        FAKE_VOLUME['volume_type_id'] = type_ref['id']
        self.driver.create_volume(FAKE_VOLUME)
        self.assertEqual(LUN_INFO["ID"], VOLUME_SNAP_ID['vol'])
        self.assertNotEqual(LUN_INFO['Lun Type'], 'THIN')
        self.driver.delete_volume(FAKE_VOLUME)
        FAKE_VOLUME['volume_type_id'] = None

    def test_create_delete_volume(self):
        # Test create lun cli exception
        set_error_flg('createlun')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume, FAKE_VOLUME)

        ret = self.driver.create_volume(FAKE_VOLUME)
        self.assertEqual(LUN_INFO['ID'], VOLUME_SNAP_ID['vol'])
        self.assertEqual(ret['provider_location'], LUN_INFO['ID'])

        # Test delete lun cli exception
        set_error_flg('dellun')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.delete_volume, FAKE_VOLUME)

        self.driver.delete_volume(FAKE_VOLUME)
        self.assertIsNone(LUN_INFO['ID'])
        self.assertIsNone(FAKE_VOLUME['provider_location'])

    def test_create_delete_cloned_volume(self):
        # Test no source volume
        self.assertRaises(exception.VolumeNotFound,
                          self.driver.create_cloned_volume,
                          FAKE_CLONED_VOLUME, FAKE_VOLUME)

        self.driver.create_volume(FAKE_VOLUME)
        # Test create luncopy failed
        self.assertEqual(LUN_INFO['ID'], VOLUME_SNAP_ID['vol'])
        set_error_flg('createluncopy')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_cloned_volume,
                          FAKE_CLONED_VOLUME, FAKE_VOLUME)
        self.assertEqual(CLONED_LUN_INFO['ID'], VOLUME_SNAP_ID['vol_copy'])
        self.driver.delete_volume(FAKE_CLONED_VOLUME)
        self.assertIsNone(CLONED_LUN_INFO['ID'])
        # Test start luncopy failed
        self.assertEqual(LUN_INFO['ID'], VOLUME_SNAP_ID['vol'])
        set_error_flg('chgluncopystatus')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_cloned_volume,
                          FAKE_CLONED_VOLUME, FAKE_VOLUME)
        self.assertIsNone(CLONED_LUN_INFO['ID'])
        self.assertEqual(LUN_INFO['ID'], VOLUME_SNAP_ID['vol'])
        # Test luncopy status abnormal
        LUNCOPY_SETTING['Status'] = 'Disable'
        self.assertEqual(LUN_INFO['ID'], '0')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_cloned_volume,
                          FAKE_CLONED_VOLUME, FAKE_VOLUME)
        self.assertIsNone(CLONED_LUN_INFO['ID'])
        self.assertEqual(LUN_INFO['ID'], VOLUME_SNAP_ID['vol'])
        LUNCOPY_SETTING['Status'] = 'Normal'
        # Test delete luncopy failed
        set_error_flg('delluncopy')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_cloned_volume,
                          FAKE_CLONED_VOLUME, FAKE_VOLUME)
        self.assertEqual(CLONED_LUN_INFO['ID'], VOLUME_SNAP_ID['vol_copy'])
        self.driver.delete_volume(FAKE_CLONED_VOLUME)
        self.assertIsNone(CLONED_LUN_INFO['ID'])
        # need to clean up LUNCopy
        LUNCOPY_INFO['Name'] = None
        LUNCOPY_INFO['ID'] = None
        LUNCOPY_INFO['Type'] = None
        LUNCOPY_INFO['State'] = None
        LUNCOPY_INFO['Status'] = None

        # Test normal create and delete cloned volume
        self.assertEqual(LUN_INFO['ID'], VOLUME_SNAP_ID['vol'])
        ret = self.driver.create_cloned_volume(FAKE_CLONED_VOLUME, FAKE_VOLUME)
        self.assertEqual(CLONED_LUN_INFO['ID'], VOLUME_SNAP_ID['vol_copy'])
        self.assertEqual(ret['provider_location'], CLONED_LUN_INFO['ID'])
        self.driver.delete_volume(FAKE_CLONED_VOLUME)
        self.assertIsNone(CLONED_LUN_INFO['ID'])
        self.assertIsNone(FAKE_CLONED_VOLUME['provider_location'])
        self.driver.delete_volume(FAKE_VOLUME)
        self.assertIsNone(LUN_INFO['ID'])

    def test_extend_volume(self):
        VOLUME_SIZE = 5
        # Test no extended volume
        self.assertRaises(exception.VolumeNotFound,
                          self.driver.extend_volume, FAKE_VOLUME, VOLUME_SIZE)

        self.driver.create_volume(FAKE_VOLUME)
        self.assertEqual(LUN_INFO['Size'], '2')
        # Test extend volume cli exception
        set_error_flg('addluntoextlun')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.extend_volume, FAKE_VOLUME, VOLUME_SIZE)
        self.assertEqual(CLONED_LUN_INFO['Name'], None)

        self.driver.extend_volume(FAKE_VOLUME, VOLUME_SIZE)
        self.assertEqual(LUN_INFO['Size'], VOLUME_SIZE)
        self.driver.delete_volume(FAKE_VOLUME)
        self.assertEqual(LUN_INFO['Name'], None)

    def test_create_delete_snapshot(self):
        # Test no resource pool
        RESPOOL_A_SIM['Valid Size'] = '0'
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_snapshot, FAKE_SNAPSHOT)
        RESPOOL_A_SIM['Valid Size'] = '5120'
        # Test no source volume
        self.assertRaises(exception.VolumeNotFound,
                          self.driver.create_snapshot, FAKE_SNAPSHOT)
        # Test create snapshot cli exception
        self.driver.create_volume(FAKE_VOLUME)
        set_error_flg('createsnapshot')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_snapshot,
                          FAKE_SNAPSHOT)
        self.assertEqual(LUN_INFO['ID'], VOLUME_SNAP_ID['vol'])
        # Test active snapshot failed
        set_error_flg('actvsnapshot')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_snapshot,
                          FAKE_SNAPSHOT)
        self.assertIsNone(SNAPSHOT_INFO['ID'])
        self.assertIsNone(SNAPSHOT_INFO['Status'])
        # Test disable snapshot failed
        set_error_flg('disablesnapshot')
        self.driver.create_snapshot(FAKE_SNAPSHOT)
        self.assertEqual(SNAPSHOT_INFO['ID'], VOLUME_SNAP_ID['snap'])
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.delete_snapshot,
                          FAKE_SNAPSHOT)
        self.assertEqual(SNAPSHOT_INFO['Status'], 'Active')
        # Test delsnapshot failed
        set_error_flg('delsnapshot')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.delete_snapshot,
                          FAKE_SNAPSHOT)
        self.assertEqual(SNAPSHOT_INFO['Status'], 'Disable')

        self.driver.delete_snapshot(FAKE_SNAPSHOT)

        # Test normal create and delete snapshot
        self.driver.create_volume(FAKE_VOLUME)
        ret = self.driver.create_snapshot(FAKE_SNAPSHOT)
        self.assertEqual(SNAPSHOT_INFO['ID'], VOLUME_SNAP_ID['snap'])
        self.assertEqual(SNAPSHOT_INFO['Status'], 'Active')
        self.assertEqual(ret['provider_location'], SNAPSHOT_INFO['ID'])
        self.driver.delete_snapshot(FAKE_SNAPSHOT)
        self.assertIsNone(SNAPSHOT_INFO['ID'])
        self.assertIsNone(SNAPSHOT_INFO['Status'])

    def test_create_delete_snapshot_volume(self):
        # Test no source snapshot
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume_from_snapshot,
                          FAKE_CLONED_VOLUME, FAKE_SNAPSHOT)
        # Test normal create and delete snapshot volume
        self.driver.create_volume(FAKE_VOLUME)
        self.driver.create_snapshot(FAKE_SNAPSHOT)
        self.assertEqual(LUN_INFO['ID'], VOLUME_SNAP_ID['vol'])
        self.assertEqual(SNAPSHOT_INFO['ID'], VOLUME_SNAP_ID['snap'])
        ret = self.driver.create_volume_from_snapshot(FAKE_CLONED_VOLUME,
                                                      FAKE_SNAPSHOT)
        self.assertEqual(CLONED_LUN_INFO['ID'], VOLUME_SNAP_ID['vol_copy'])
        self.assertEqual(ret['provider_location'], CLONED_LUN_INFO['ID'])
        self.driver.delete_snapshot(FAKE_SNAPSHOT)
        self.driver.delete_volume(FAKE_VOLUME)
        self.driver.delete_volume(FAKE_CLONED_VOLUME)
        self.assertIsNone(LUN_INFO['ID'])
        self.assertIsNone(CLONED_LUN_INFO['ID'])
        self.assertIsNone(SNAPSHOT_INFO['ID'])

    def test_initialize_connection(self):
        # Test can not get iscsi iqn
        set_error_flg('showiscsitgtname')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.initialize_connection,
                          FAKE_VOLUME, FAKE_CONNECTOR)
        # Test failed to get iSCSI port info
        set_error_flg('showiscsiip')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.initialize_connection,
                          FAKE_VOLUME, FAKE_CONNECTOR)
        # Test create hostgroup failed
        set_error_flg('createhostgroup')
        MAP_INFO['Host Group ID'] = None
        MAP_INFO['Host Group Name'] = None
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.initialize_connection,
                          FAKE_VOLUME, FAKE_CONNECTOR)
        # Test create host failed
        set_error_flg('addhost')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.initialize_connection,
                          FAKE_VOLUME, FAKE_CONNECTOR)
        # Test add iSCSI initiator failed
        set_error_flg('addiscsiini')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.initialize_connection,
                          FAKE_VOLUME, FAKE_CONNECTOR)
        # Test add hostport failed
        set_error_flg('addhostport')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.initialize_connection,
                          FAKE_VOLUME, FAKE_CONNECTOR)
        # Test no volume
        FAKE_VOLUME['provider_location'] = '100'
        self.assertRaises(exception.VolumeNotFound,
                          self.driver.initialize_connection,
                          FAKE_VOLUME, FAKE_CONNECTOR)
        FAKE_VOLUME['provider_location'] = None
        # Test map volume failed
        self.driver.create_volume(FAKE_VOLUME)
        set_error_flg('addhostmap')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.initialize_connection,
                          FAKE_VOLUME, FAKE_CONNECTOR)
        # Test normal initialize connection
        self.assertEqual(FAKE_VOLUME['provider_location'],
                         VOLUME_SNAP_ID['vol'])
        self.assertEqual(LUN_INFO['Owner Controller'], 'A')
        ret = self.driver.initialize_connection(FAKE_VOLUME, FAKE_CONNECTOR)
        iscsi_propers = ret['data']
        self.assertEqual(iscsi_propers['target_iqn'],
                         INITIATOR_SETTING['TargetIQN-form'])
        self.assertEqual(iscsi_propers['target_portal'],
                         INITIATOR_SETTING['Initiator TargetIP'] + ':3260')
        self.assertEqual(MAP_INFO["DEV LUN ID"], LUN_INFO['ID'])
        self.assertEqual(MAP_INFO["INI Port Info"],
                         FAKE_CONNECTOR['initiator'])
        self.assertEqual(LUN_INFO['Owner Controller'], 'B')
        self.driver.terminate_connection(FAKE_VOLUME, FAKE_CONNECTOR)
        self.driver.delete_volume(FAKE_VOLUME)
        self.assertIsNone(LUN_INFO['ID'])

    def test_terminate_connection(self):
        # Test no host was found
        self.assertRaises(exception.HostNotFound,
                          self.driver.terminate_connection,
                          FAKE_VOLUME, FAKE_CONNECTOR)
        # Test no volume was found
        self.driver .create_volume(FAKE_VOLUME)
        self.driver.initialize_connection(FAKE_VOLUME, FAKE_CONNECTOR)
        FAKE_VOLUME['provider_location'] = None
        self.assertRaises(exception.VolumeNotFound,
                          self.driver.terminate_connection,
                          FAKE_VOLUME, FAKE_CONNECTOR)
        FAKE_VOLUME['provider_location'] = LUN_INFO['ID']
        # Test delete map failed
        set_error_flg('delhostmap')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.terminate_connection,
                          FAKE_VOLUME, FAKE_CONNECTOR)
        # Delete hostport failed
        set_error_flg('delhostport')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.terminate_connection,
                          FAKE_VOLUME, FAKE_CONNECTOR)
        # Test delete initiator failed
        set_error_flg('deliscsiini')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.terminate_connection,
                          FAKE_VOLUME, FAKE_CONNECTOR)
        # Test delete host failed
        set_error_flg('delhost')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.terminate_connection,
                          FAKE_VOLUME, FAKE_CONNECTOR)
        # Test normal terminate connection
        self.assertEqual(LUN_INFO['ID'], VOLUME_SNAP_ID['vol'])
        self.driver.initialize_connection(FAKE_VOLUME, FAKE_CONNECTOR)
        self.driver.terminate_connection(FAKE_VOLUME, FAKE_CONNECTOR)
        self.assertIsNone(MAP_INFO["DEV LUN ID"])
        self.driver.delete_volume(FAKE_VOLUME)
        self.assertIsNone(LUN_INFO['ID'])

    def test_get_volume_stats(self):
        stats = self.driver.get_volume_stats(True)
        free_capacity = float(POOL_SETTING['Free Capacity']) / 1024
        self.assertEqual(stats['free_capacity_gb'], free_capacity)
        self.assertEqual(stats['storage_protocol'], 'iSCSI')


class HuaweiTFCDriverTestCase(test.TestCase):
    def __init__(self, *args, **kwargs):
        super(HuaweiTFCDriverTestCase, self).__init__(*args, **kwargs)

    def setUp(self):
        super(HuaweiTFCDriverTestCase, self).setUp()

        self.tmp_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp_dir)

        self.fake_conf_file = self.tmp_dir + '/cinder_huawei_conf.xml'
        self.addCleanup(os.remove, self.fake_conf_file)

        create_fake_conf_file(self.fake_conf_file)
        modify_conf(self.fake_conf_file, 'Storage/Protocol', 'FC')
        self.configuration = mox.MockObject(conf.Configuration)
        self.configuration.cinder_huawei_conf_file = self.fake_conf_file
        self.configuration.append_config_values(mox.IgnoreArg())

        self.stubs.Set(time, 'sleep', Fake_sleep)
        self.stubs.Set(ssh_utils, 'SSHPool', FakeSSHPool)
        self.stubs.Set(ssh_common.TseriesCommon, '_change_file_mode',
                       Fake_change_file_mode)
        self._init_driver()

    def _init_driver(self):
        Curr_test[0] = 'T'
        self.driver = HuaweiVolumeDriver(configuration=self.configuration)
        self.driver.do_setup(None)

    def test_validate_connector_failed(self):
        invalid_connector = {'host': 'testhost'}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.validate_connector,
                          invalid_connector)

    def test_create_delete_volume(self):
        self.driver.create_volume(FAKE_VOLUME)
        self.assertEqual(LUN_INFO['ID'], VOLUME_SNAP_ID['vol'])
        self.driver.delete_volume(FAKE_VOLUME)
        self.assertIsNone(LUN_INFO['ID'])

    def test_create_delete_snapshot(self):
        self.driver.create_volume(FAKE_VOLUME)
        self.driver.create_snapshot(FAKE_SNAPSHOT)
        self.assertEqual(SNAPSHOT_INFO['ID'], VOLUME_SNAP_ID['snap'])
        self.driver.delete_snapshot(FAKE_SNAPSHOT)
        self.assertIsNone(SNAPSHOT_INFO['ID'])
        self.driver.delete_volume(FAKE_VOLUME)
        self.assertIsNone(LUN_INFO['ID'])

    def test_create_cloned_volume(self):
        self.driver.create_volume(FAKE_VOLUME)
        ret = self.driver.create_cloned_volume(FAKE_CLONED_VOLUME, FAKE_VOLUME)
        self.assertEqual(CLONED_LUN_INFO['ID'], VOLUME_SNAP_ID['vol_copy'])
        self.assertEqual(ret['provider_location'], CLONED_LUN_INFO['ID'])
        self.driver.delete_volume(FAKE_CLONED_VOLUME)
        self.driver.delete_volume(FAKE_VOLUME)
        self.assertIsNone(CLONED_LUN_INFO['ID'])
        self.assertIsNone(LUN_INFO['ID'])

    def test_create_snapshot_volume(self):
        self.driver.create_volume(FAKE_VOLUME)
        self.driver.create_snapshot(FAKE_SNAPSHOT)
        ret = self.driver.create_volume_from_snapshot(FAKE_CLONED_VOLUME,
                                                      FAKE_SNAPSHOT)
        self.assertEqual(CLONED_LUN_INFO['ID'], VOLUME_SNAP_ID['vol_copy'])
        self.assertEqual(ret['provider_location'], CLONED_LUN_INFO['ID'])
        self.driver.delete_volume(FAKE_CLONED_VOLUME)
        self.driver.delete_volume(FAKE_VOLUME)
        self.assertIsNone(CLONED_LUN_INFO['ID'])
        self.assertIsNone(LUN_INFO['ID'])

    def test_initialize_terminitat_connection(self):
        self.driver.create_volume(FAKE_VOLUME)
        ret = self.driver.initialize_connection(FAKE_VOLUME, FAKE_CONNECTOR)
        fc_properties = ret['data']
        self.assertEqual(fc_properties['target_wwn'],
                         INITIATOR_SETTING['WWN'])
        self.assertEqual(MAP_INFO["DEV LUN ID"], LUN_INFO['ID'])

        self.driver.terminate_connection(FAKE_VOLUME, FAKE_CONNECTOR)
        self.assertIsNone(MAP_INFO["DEV LUN ID"])
        self.assertIsNone(MAP_INFO["Host LUN ID"])
        self.driver.delete_volume(FAKE_VOLUME)
        self.assertIsNone(LUN_INFO['ID'])

    def _test_get_volume_stats(self):
        stats = self.driver.get_volume_stats(True)
        fakecapacity = float(POOL_SETTING['Free Capacity']) / 1024
        self.assertEqual(stats['free_capacity_gb'], fakecapacity)
        self.assertEqual(stats['storage_protocol'], 'FC')


class HuaweiDorado5100FCDriverTestCase(HuaweiTFCDriverTestCase):
    def __init__(self, *args, **kwargs):
        super(HuaweiDorado5100FCDriverTestCase, self).__init__(*args, **kwargs)

    def setUp(self):
        super(HuaweiDorado5100FCDriverTestCase, self).setUp()

    def _init_driver(self):
        Curr_test[0] = 'Dorado5100'
        modify_conf(self.fake_conf_file, 'Storage/Product', 'Dorado')
        self.driver = HuaweiVolumeDriver(configuration=self.configuration)
        self.driver.do_setup(None)

    def test_create_cloned_volume(self):
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_cloned_volume,
                          FAKE_CLONED_VOLUME, FAKE_VOLUME)

    def test_create_snapshot_volume(self):
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume_from_snapshot,
                          FAKE_CLONED_VOLUME, FAKE_SNAPSHOT)


class HuaweiDorado2100G2FCDriverTestCase(HuaweiTFCDriverTestCase):
    def __init__(self, *args, **kwargs):
        super(HuaweiDorado2100G2FCDriverTestCase, self).__init__(*args,
                                                                 **kwargs)

    def setUp(self):
        super(HuaweiDorado2100G2FCDriverTestCase, self).setUp()

    def _init_driver(self):
        Curr_test[0] = 'Dorado2100G2'
        modify_conf(self.fake_conf_file, 'Storage/Product', 'Dorado')
        self.driver = HuaweiVolumeDriver(configuration=self.configuration)
        self.driver.do_setup(None)

    def test_create_cloned_volume(self):
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_cloned_volume,
                          FAKE_CLONED_VOLUME, FAKE_VOLUME)

    def test_create_delete_snapshot(self):
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_snapshot, FAKE_SNAPSHOT)

    def test_create_snapshot_volume(self):
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume_from_snapshot,
                          FAKE_CLONED_VOLUME, FAKE_SNAPSHOT)

    def test_extend_volume(self):
        NEWSIZE = 5
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.extend_volume,
                          FAKE_VOLUME, NEWSIZE)


class HuaweiDorado5100ISCSIDriverTestCase(HuaweiTISCSIDriverTestCase):
    def __init__(self, *args, **kwargs):
        super(HuaweiDorado5100ISCSIDriverTestCase, self).__init__(*args,
                                                                  **kwargs)

    def setUp(self):
        super(HuaweiDorado5100ISCSIDriverTestCase, self).setUp()

    def _init_driver(self):
        Curr_test[0] = 'Dorado5100'
        modify_conf(self.fake_conf_file, 'Storage/Product', 'Dorado')
        self.driver = HuaweiVolumeDriver(configuration=self.configuration)
        self.driver.do_setup(None)

    def test_create_delete_cloned_volume(self):
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_cloned_volume,
                          FAKE_CLONED_VOLUME, FAKE_VOLUME)

    def test_create_delete_snapshot_volume(self):
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume_from_snapshot,
                          FAKE_CLONED_VOLUME, FAKE_SNAPSHOT)

    def test_volume_type(self):
        pass


class HuaweiDorado2100G2ISCSIDriverTestCase(HuaweiTISCSIDriverTestCase):
    def __init__(self, *args, **kwargs):
        super(HuaweiDorado2100G2ISCSIDriverTestCase, self).__init__(*args,
                                                                    **kwargs)

    def setUp(self):
        super(HuaweiDorado2100G2ISCSIDriverTestCase, self).setUp()

    def _init_driver(self):
        Curr_test[0] = 'Dorado2100G2'
        modify_conf(self.fake_conf_file, 'Storage/Product', 'Dorado')
        self.driver = HuaweiVolumeDriver(configuration=self.configuration)
        self.driver.do_setup(None)

    def test_conf_invalid(self):
        pass

    def test_create_delete_cloned_volume(self):
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_cloned_volume,
                          FAKE_CLONED_VOLUME, FAKE_VOLUME)

    def test_create_delete_snapshot(self):
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_snapshot, FAKE_SNAPSHOT)

    def test_create_delete_snapshot_volume(self):
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume_from_snapshot,
                          FAKE_CLONED_VOLUME, FAKE_SNAPSHOT)

    def test_initialize_connection(self):
        self.driver.create_volume(FAKE_VOLUME)
        ret = self.driver.initialize_connection(FAKE_VOLUME, FAKE_CONNECTOR)
        iscsi_propers = ret['data']
        self.assertEqual(iscsi_propers['target_iqn'],
                         INITIATOR_SETTING['TargetIQN-form'])
        self.assertEqual(iscsi_propers['target_portal'],
                         INITIATOR_SETTING['Initiator TargetIP'] + ':3260')
        self.assertEqual(MAP_INFO["DEV LUN ID"], LUN_INFO['ID'])
        self.assertEqual(MAP_INFO["INI Port Info"],
                         FAKE_CONNECTOR['initiator'])
        self.driver.terminate_connection(FAKE_VOLUME, FAKE_CONNECTOR)
        self.driver.delete_volume(FAKE_VOLUME)
        self.assertIsNone(LUN_INFO['ID'])

    def test_extend_volume(self):
        NEWSIZE = 5
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.extend_volume,
                          FAKE_VOLUME, NEWSIZE)


class SSHMethodTestCase(test.TestCase):
    def __init__(self, *args, **kwargs):
        super(SSHMethodTestCase, self).__init__(*args, **kwargs)

    def setUp(self):
        super(SSHMethodTestCase, self).setUp()
        self.tmp_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp_dir)

        self.fake_conf_file = self.tmp_dir + '/cinder_huawei_conf.xml'
        self.addCleanup(os.remove, self.fake_conf_file)

        create_fake_conf_file(self.fake_conf_file)
        self.configuration = mox.MockObject(conf.Configuration)
        self.configuration.cinder_huawei_conf_file = self.fake_conf_file
        self.configuration.append_config_values(mox.IgnoreArg())

        self.stubs.Set(time, 'sleep', Fake_sleep)
        self.stubs.Set(ssh_utils, 'SSHPool', FakeSSHPool)
        self.stubs.Set(ssh_common.TseriesCommon, '_change_file_mode',
                       Fake_change_file_mode)
        Curr_test[0] = 'T'
        self.driver = HuaweiVolumeDriver(configuration=self.configuration)
        self.driver.do_setup(None)

    def test_reach_max_connection_limit(self):
        self.stubs.Set(FakeChannel, 'recv', self._fake_recv1)
        self.assertRaises(exception.CinderException,
                          self.driver.create_volume, FAKE_VOLUME)

    def test_socket_timeout(self):
        self.stubs.Set(FakeChannel, 'recv', self._fake_recv2)
        self.assertRaises(socket.timeout,
                          self.driver.create_volume, FAKE_VOLUME)

    def _fake_recv1(self, nbytes):
        return "No response message"

    def _fake_recv2(self, nBytes):
        raise socket.timeout()


class HuaweiUtilsTestCase(test.TestCase):
    def __init__(self, *args, **kwargs):
        super(HuaweiUtilsTestCase, self).__init__(*args, **kwargs)

    def setUp(self):
        super(HuaweiUtilsTestCase, self).setUp()

        self.tmp_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp_dir)
        self.fake_conf_file = self.tmp_dir + '/cinder_huawei_conf.xml'
        self.addCleanup(os.remove, self.fake_conf_file)
        create_fake_conf_file(self.fake_conf_file)

    def test_parse_xml_file_ioerror(self):
        tmp_fonf_file = '/xxx/cinder_huawei_conf.xml'
        self.assertRaises(IOError, huawei_utils.parse_xml_file, tmp_fonf_file)

    def test_is_xml_item_exist(self):
        root = huawei_utils.parse_xml_file(self.fake_conf_file)
        res = huawei_utils.is_xml_item_exist(root, 'Storage/UserName')
        self.assertTrue(res)
        res = huawei_utils.is_xml_item_exist(root, 'xxx')
        self.assertFalse(res)
        res = huawei_utils.is_xml_item_exist(root, 'LUN/StoragePool', 'Name')
        self.assertTrue(res)
        res = huawei_utils.is_xml_item_exist(root, 'LUN/StoragePool', 'xxx')
        self.assertFalse(res)

    def test_is_xml_item_valid(self):
        root = huawei_utils.parse_xml_file(self.fake_conf_file)
        res = huawei_utils.is_xml_item_valid(root, 'LUN/LUNType',
                                             ['Thin', 'Thick'])
        self.assertTrue(res)
        res = huawei_utils.is_xml_item_valid(root, 'LUN/LUNType', ['test'])
        self.assertFalse(res)
        res = huawei_utils.is_xml_item_valid(root, 'Host',
                                             ['Linux', 'Windows'], 'OSType')
        self.assertTrue(res)
        res = huawei_utils.is_xml_item_valid(root, 'Host', ['test'], 'OSType')
        self.assertFalse(res)

    def test_get_conf_host_os_type(self):
        # Default os is Linux
        res = huawei_utils.get_conf_host_os_type('10.10.10.1',
                                                 self.fake_conf_file)
        self.assertEqual(res, '0')
        modify_conf(self.fake_conf_file, 'Host', 'Windows', 'OSType')
        res = huawei_utils.get_conf_host_os_type(FAKE_CONNECTOR['ip'],
                                                 self.fake_conf_file)
        self.assertEqual(res, '1')
