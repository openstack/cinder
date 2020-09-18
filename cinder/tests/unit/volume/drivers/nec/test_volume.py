#
# Copyright (c) 2016 NEC Corporation.
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

import time
from unittest import mock

import ddt

from cinder import context
from cinder import exception
from cinder.objects import volume_attachment
from cinder.tests.unit import fake_constants as constants
from cinder.tests.unit.fake_volume import fake_volume_obj
from cinder.tests.unit import test
from cinder.volume import configuration as conf
from cinder.volume.drivers.nec import cli
from cinder.volume.drivers.nec import volume_common
from cinder.volume.drivers.nec import volume_helper
from cinder.volume import qos_specs
from cinder.volume import volume_types


xml_out = '''
<REQUEST>
 <CMD_REQUEST cmd_name="/opt/iSMCliGateway/impl/query/iSMquery"
              arg="-cinder -xml -all "
              version="Version 9.4.001">
  <CHAPTER name="Disk Array">
   <OBJECT name="Disk Array">
    <SECTION name="Disk Array Detail Information">
     <UNIT name="Product ID">M310</UNIT>
    </SECTION>
   </OBJECT>
  </CHAPTER>
  <CHAPTER name="Logical Disk">
   <OBJECT name="Logical Disk">
    <SECTION name="LD Detail Information">
     <UNIT name="LDN(h)">0000</UNIT>
     <UNIT name="OS Type">LX</UNIT>
     <UNIT name="LD Name">287RbQoP7VdwR1WsPC2fZT</UNIT>
     <UNIT name="LD Capacity">1073741824</UNIT>
     <UNIT name="Pool No.(h)">0000</UNIT>
     <UNIT name="Purpose">---</UNIT>
     <UNIT name="RPL Attribute">MV</UNIT>
    </SECTION>
   </OBJECT>
   <OBJECT name="Logical Disk">
    <SECTION name="LD Detail Information">
     <UNIT name="LDN(h)">0001</UNIT>
     <UNIT name="OS Type">  </UNIT>
     <UNIT name="LD Name">backup_SDV0001</UNIT>
     <UNIT name="LD Capacity">5368709120</UNIT>
     <UNIT name="Pool No.(h)">0001</UNIT>
     <UNIT name="Purpose">(invalid attribute)</UNIT>
     <UNIT name="RPL Attribute">IV</UNIT>
    </SECTION>
   </OBJECT>
   <OBJECT name="Logical Disk">
    <SECTION name="LD Detail Information">
     <UNIT name="LDN(h)">0003</UNIT>
     <UNIT name="OS Type">LX</UNIT>
     <UNIT name="LD Name">31HxzqBiAFTUxxOlcVn3EA</UNIT>
     <UNIT name="LD Capacity">1073741824</UNIT>
     <UNIT name="Pool No.(h)">0001</UNIT>
     <UNIT name="Purpose">---</UNIT>
     <UNIT name="RPL Attribute">RV</UNIT>
    </SECTION>
   </OBJECT>
   <OBJECT name="Logical Disk">
    <SECTION name="LD Detail Information">
     <UNIT name="LDN(h)">0004</UNIT>
     <UNIT name="OS Type">LX</UNIT>
     <UNIT name="LD Name">287RbQoP7VdwR1WsPC2fZT_back</UNIT>
     <UNIT name="LD Capacity">1073741824</UNIT>
     <UNIT name="Pool No.(h)">0000</UNIT>
     <UNIT name="Purpose">---</UNIT>
     <UNIT name="RPL Attribute">RV</UNIT>
    </SECTION>
   </OBJECT>
   <OBJECT name="Logical Disk">
    <SECTION name="LD Detail Information">
     <UNIT name="LDN(h)">0005</UNIT>
     <UNIT name="OS Type">LX</UNIT>
     <UNIT name="LD Name">20000009910200140005</UNIT>
     <UNIT name="LD Capacity">10737418240</UNIT>
     <UNIT name="Pool No.(h)">0000</UNIT>
     <UNIT name="Purpose">---</UNIT>
     <UNIT name="RPL Attribute">RV</UNIT>
    </SECTION>
   </OBJECT>
   <OBJECT name="Logical Disk">
    <SECTION name="LD Detail Information">
     <UNIT name="LDN(h)">0006</UNIT>
     <UNIT name="OS Type">LX</UNIT>
     <UNIT name="LD Name">287RbQoP7VdwR1WsPC2fZT_l</UNIT>
     <UNIT name="LD Capacity">10737418240</UNIT>
     <UNIT name="Pool No.(h)">0000</UNIT>
     <UNIT name="Purpose">---</UNIT>
     <UNIT name="RPL Attribute">IV</UNIT>
    </SECTION>
   </OBJECT>
   <OBJECT name="Logical Disk">
    <SECTION name="LD Detail Information">
     <UNIT name="LDN(h)">0007</UNIT>
     <UNIT name="OS Type">  </UNIT>
     <UNIT name="LD Name">20000009910200140007</UNIT>
     <UNIT name="LD Capacity">10737418240</UNIT>
     <UNIT name="Pool No.(h)">0000</UNIT>
     <UNIT name="Purpose">---</UNIT>
     <UNIT name="RPL Attribute">IV</UNIT>
    </SECTION>
   </OBJECT>
   <OBJECT name="Logical Disk">
    <SECTION name="LD Detail Information">
     <UNIT name="LDN(h)">0008</UNIT>
     <UNIT name="OS Type">  </UNIT>
     <UNIT name="LD Name">20000009910200140008</UNIT>
     <UNIT name="LD Capacity">10737418240</UNIT>
     <UNIT name="Pool No.(h)">0000</UNIT>
     <UNIT name="Purpose">---</UNIT>
     <UNIT name="RPL Attribute">IV</UNIT>
    </SECTION>
   </OBJECT>
   <OBJECT name="Logical Disk">
    <SECTION name="LD Detail Information">
     <UNIT name="LDN(h)">0009</UNIT>
     <UNIT name="OS Type">  </UNIT>
     <UNIT name="LD Name">20000009910200140009</UNIT>
     <UNIT name="LD Capacity">10737418240</UNIT>
     <UNIT name="Pool No.(h)">0000</UNIT>
     <UNIT name="Purpose">---</UNIT>
     <UNIT name="RPL Attribute">IV</UNIT>
    </SECTION>
   </OBJECT>
   <OBJECT name="Logical Disk">
    <SECTION name="LD Detail Information">
     <UNIT name="LDN(h)">000a</UNIT>
     <UNIT name="OS Type">  </UNIT>
     <UNIT name="LD Name">2000000991020012000A</UNIT>
     <UNIT name="LD Capacity">6442450944</UNIT>
     <UNIT name="Pool No.(h)">0000</UNIT>
     <UNIT name="Purpose">---</UNIT>
     <UNIT name="RPL Attribute">IV</UNIT>
    </SECTION>
   </OBJECT>
   <OBJECT name="Logical Disk">
    <SECTION name="LD Detail Information">
     <UNIT name="LDN(h)">000b</UNIT>
     <UNIT name="OS Type">  </UNIT>
     <UNIT name="LD Name">2000000991020012000B</UNIT>
     <UNIT name="LD Capacity">6442450944</UNIT>
     <UNIT name="Pool No.(h)">0000</UNIT>
     <UNIT name="Purpose">---</UNIT>
     <UNIT name="RPL Attribute">IV</UNIT>
    </SECTION>
   </OBJECT>
   <OBJECT name="Logical Disk">
    <SECTION name="LD Detail Information">
     <UNIT name="LDN(h)">000c</UNIT>
     <UNIT name="OS Type">  </UNIT>
     <UNIT name="LD Name">2000000991020012000C</UNIT>
     <UNIT name="LD Capacity">6442450944</UNIT>
     <UNIT name="Pool No.(h)">0000</UNIT>
     <UNIT name="Purpose">---</UNIT>
     <UNIT name="RPL Attribute">IV</UNIT>
    </SECTION>
   </OBJECT>
   <OBJECT name="Logical Disk">
    <SECTION name="LD Detail Information">
     <UNIT name="LDN(h)">000d</UNIT>
     <UNIT name="OS Type">LX</UNIT>
     <UNIT name="LD Name">yEUHrXa5AHMjOZZLb93eP</UNIT>
     <UNIT name="LD Capacity">6442450944</UNIT>
     <UNIT name="Pool No.(h)">0001</UNIT>
     <UNIT name="Purpose">---</UNIT>
     <UNIT name="RPL Attribute">IV</UNIT>
    </SECTION>
   </OBJECT>
   <OBJECT name="Logical Disk">
    <SECTION name="LD Detail Information">
     <UNIT name="LDN(h)">000e</UNIT>
     <UNIT name="OS Type">LX</UNIT>
     <UNIT name="LD Name">4T7JpyqI3UuPlKeT9D3VQF</UNIT>
     <UNIT name="LD Capacity">6442450944</UNIT>
     <UNIT name="Pool No.(h)">0001</UNIT>
     <UNIT name="Purpose">(invalid attribute)</UNIT>
     <UNIT name="RPL Attribute">SV</UNIT>
    </SECTION>
   </OBJECT>
   <OBJECT name="Logical Disk">
    <SECTION name="LD Detail Information">
     <UNIT name="LDN(h)">000f</UNIT>
     <UNIT name="OS Type">LX</UNIT>
     <UNIT name="LD Name">59V9KIi0ZHWJ5yvjCG5RQ4_d</UNIT>
     <UNIT name="LD Capacity">6442450944</UNIT>
     <UNIT name="Pool No.(h)">0001</UNIT>
     <UNIT name="Purpose">---</UNIT>
     <UNIT name="RPL Attribute">IV</UNIT>
    </SECTION>
   </OBJECT>
   <OBJECT name="Logical Disk">
    <SECTION name="LD Detail Information">
     <UNIT name="LDN(h)">0011</UNIT>
     <UNIT name="OS Type">LX</UNIT>
     <UNIT name="LD Name">6EWPOChJkdSysJmpMAB9YR</UNIT>
     <UNIT name="LD Capacity">6442450944</UNIT>
     <UNIT name="Pool No.(h)">0001</UNIT>
     <UNIT name="Purpose">---</UNIT>
     <UNIT name="RPL Attribute">IV</UNIT>
    </SECTION>
   </OBJECT>
   <OBJECT name="Logical Disk">
    <SECTION name="LD Detail Information">
     <UNIT name="LDN(h)">0fff</UNIT>
     <UNIT name="OS Type">  </UNIT>
     <UNIT name="LD Name">Pool0000_SYV0FFF</UNIT>
     <UNIT name="LD Capacity">8589934592</UNIT>
     <UNIT name="Pool No.(h)">0000</UNIT>
     <UNIT name="Purpose">(invalid attribute)</UNIT>
     <UNIT name="RPL Attribute">---</UNIT>
    </SECTION>
   </OBJECT>
  </CHAPTER>
  <CHAPTER name="Pool">
   <OBJECT name="Pool">
    <SECTION name="Pool Detail Information">
     <UNIT name="Pool No.(h)">0000</UNIT>
     <UNIT name="Pool Capacity">281320357888</UNIT>
     <UNIT name="Used Pool Capacity">84020297728</UNIT>
     <UNIT name="Free Pool Capacity">197300060160</UNIT>
    </SECTION>
   </OBJECT>
   <OBJECT name="Pool">
    <SECTION name="Pool Detail Information">
     <UNIT name="Pool No.(h)">0001</UNIT>
     <UNIT name="Pool Capacity">89657442304</UNIT>
     <UNIT name="Used Pool Capacity">6710886400</UNIT>
     <UNIT name="Free Pool Capacity">82946555904</UNIT>
    </SECTION>
   </OBJECT>
   <OBJECT name="Pool">
    <SECTION name="Pool Detail Information">
     <UNIT name="Pool No.(h)">0002</UNIT>
     <UNIT name="Pool Capacity">1950988894208</UNIT>
     <UNIT name="Used Pool Capacity">18446744073441116160</UNIT>
     <UNIT name="Free Pool Capacity">1951257329664</UNIT>
    </SECTION>
   </OBJECT>
   <OBJECT name="Pool">
    <SECTION name="Pool Detail Information">
     <UNIT name="Pool No.(h)">0003</UNIT>
     <UNIT name="Pool Capacity">1950988894208</UNIT>
     <UNIT name="Used Pool Capacity">18446744073441116160</UNIT>
     <UNIT name="Free Pool Capacity">1951257329664</UNIT>
    </SECTION>
   </OBJECT>
  </CHAPTER>
  <CHAPTER name="Controller">
   <OBJECT name="Host Port">
    <SECTION name="Host Director/Host Port Information">
     <UNIT name="Port No.(h)">00-00</UNIT>
     <UNIT name="WWPN">2100000991020012</UNIT>
    </SECTION>
   </OBJECT>
   <OBJECT name="Host Port">
    <SECTION name="Host Director/Host Port Information">
     <UNIT name="Port No.(h)">00-01</UNIT>
     <UNIT name="WWPN">2200000991020012</UNIT>
    </SECTION>
   </OBJECT>
   <OBJECT name="Host Port">
    <SECTION name="Host Director/Host Port Information">
     <UNIT name="Port No.(h)">00-02</UNIT>
     <UNIT name="IP Address">192.168.1.90</UNIT>
     <UNIT name="Link Status">Link Down</UNIT>
    </SECTION>
   </OBJECT>
   <OBJECT name="Host Port">
    <SECTION name="Host Director/Host Port Information">
     <UNIT name="Port No.(h)">00-03</UNIT>
     <UNIT name="IP Address">192.168.1.91</UNIT>
     <UNIT name="Link Status">Link Down</UNIT>
    </SECTION>
   </OBJECT>
   <OBJECT name="Host Port">
    <SECTION name="Host Director/Host Port Information">
     <UNIT name="Port No.(h)">01-00</UNIT>
     <UNIT name="WWPN">2900000991020012</UNIT>
    </SECTION>
   </OBJECT>
   <OBJECT name="Host Port">
    <SECTION name="Host Director/Host Port Information">
     <UNIT name="Port No.(h)">01-01</UNIT>
     <UNIT name="WWPN">2A00000991020012</UNIT>
    </SECTION>
   </OBJECT>
   <OBJECT name="Host Port">
    <SECTION name="Host Director/Host Port Information">
     <UNIT name="Port No.(h)">01-02</UNIT>
     <UNIT name="IP Address">192.168.2.92</UNIT>
     <UNIT name="Link Status">Link Down</UNIT>
    </SECTION>
   </OBJECT>
   <OBJECT name="Host Port">
    <SECTION name="Host Director/Host Port Information">
     <UNIT name="Port No.(h)">01-03</UNIT>
     <UNIT name="IP Address">192.168.2.93</UNIT>
     <UNIT name="Link Status">Link Up</UNIT>
    </SECTION>
   </OBJECT>
  </CHAPTER>
  <CHAPTER name="Access Control">
   <OBJECT name="LD Set(FC)">
    <SECTION name="LD Set(FC) Information">
     <UNIT name="Platform">LX</UNIT>
     <UNIT name="LD Set Name">OpenStack1</UNIT>
    </SECTION>
    <SECTION name="Path List">
     <UNIT name="Path">1000-0090-FAA0-786B</UNIT>
    </SECTION>
    <SECTION name="Path List">
     <UNIT name="Path">1000-0090-FAA0-786A</UNIT>
    </SECTION>
    <SECTION name="LUN/LD List">
     <UNIT name="LUN(h)">0000</UNIT>
     <UNIT name="LDN(h)">0005</UNIT>
    </SECTION>
    <SECTION name="LUN/LD List">
     <UNIT name="LUN(h)">0001</UNIT>
     <UNIT name="LDN(h)">0006</UNIT>
    </SECTION>
    <SECTION name="LUN/LD List">
     <UNIT name="LUN(h)">0002</UNIT>
     <UNIT name="LDN(h)">0011</UNIT>
    </SECTION>
   </OBJECT>
   <OBJECT name="LD Set(FC)">
    <SECTION name="LD Set(FC) Information">
     <UNIT name="Platform">LX</UNIT>
     <UNIT name="LD Set Name">OpenStack3</UNIT>
    </SECTION>
    <SECTION name="Path List">
     <UNIT name="Path">1000-0090-FAA0-786D</UNIT>
    </SECTION>
    <SECTION name="Path List">
     <UNIT name="Path">1000-0090-FAA0-786C</UNIT>
    </SECTION>
    <SECTION name="LUN/LD List">
     <UNIT name="LUN(h)">0001</UNIT>
     <UNIT name="LDN(h)">0011</UNIT>
    </SECTION>
   </OBJECT>
   <OBJECT name="LD Set(iSCSI)">
    <SECTION name="LD Set(iSCSI) Information">
     <UNIT name="Platform">LX</UNIT>
     <UNIT name="LD Set Name">OpenStack0</UNIT>
     <UNIT name="Target Mode">Multi-Target</UNIT>
    </SECTION>
    <SECTION name="Portal">
     <UNIT name="Portal">192.168.1.90:3260</UNIT>
    </SECTION>
    <SECTION name="Portal">
     <UNIT name="Portal">192.168.1.91:3260</UNIT>
    </SECTION>
    <SECTION name="Portal">
     <UNIT name="Portal">192.168.2.92:3260</UNIT>
    </SECTION>
    <SECTION name="Portal">
     <UNIT name="Portal">192.168.2.93:3260</UNIT>
    </SECTION>
    <SECTION name="Initiator List">
     <UNIT name="Initiator List">iqn.1994-05.com.redhat:d1d8e8f23255</UNIT>
    </SECTION>
    <SECTION name="Target Information For Multi-Target Mode">
     <UNIT name="Target Name">iqn.2001-03.target0000</UNIT>
     <UNIT name="LUN(h)">0000</UNIT>
     <UNIT name="LDN(h)">0000</UNIT>
    </SECTION>
    <SECTION name="Target Information For Multi-Target Mode">
     <UNIT name="Target Name">iqn.2001-03.target0001</UNIT>
     <UNIT name="LUN(h)">0001</UNIT>
     <UNIT name="LDN(h)">0006</UNIT>
    </SECTION>
   </OBJECT>
   <OBJECT name="LD Set(iSCSI)">
    <SECTION name="LD Set(iSCSI) Information">
     <UNIT name="Platform">LX</UNIT>
     <UNIT name="LD Set Name">OpenStack2</UNIT>
     <UNIT name="Target Mode">Normal</UNIT>
     <UNIT name="Target Name">iqn.2001-03.target0002</UNIT>
    </SECTION>
    <SECTION name="Portal">
     <UNIT name="Portal">192.168.1.94:3260</UNIT>
    </SECTION>
    <SECTION name="Portal">
     <UNIT name="Portal">192.168.1.95:3260</UNIT>
    </SECTION>
    <SECTION name="Portal">
     <UNIT name="Portal">192.168.2.96:3260</UNIT>
    </SECTION>
    <SECTION name="Portal">
     <UNIT name="Portal">192.168.2.97:3260</UNIT>
    </SECTION>
    <SECTION name="Initiator List">
     <UNIT name="Initiator List">iqn.1994-05.com.redhat:13a80ea272e</UNIT>
    </SECTION>
   </OBJECT>
  </CHAPTER>
 <RETURN_MSG>Command Completed Successfully!!</RETURN_MSG>
 <RETURN_CODE>0</RETURN_CODE>
 </CMD_REQUEST>
</REQUEST>
'''


class DummyVolume(object):

    def __init__(self, volid, volsize=1):
        super(DummyVolume, self).__init__()
        self.id = volid
        self._name_id = None
        self.size = volsize
        self.status = None
        self.volume_type_id = None
        self.attach_status = None
        self.volume_attachment = None
        self.provider_location = None
        self.name = None

    @property
    def name_id(self):
        return self.id if not self._name_id else self._name_id

    @name_id.setter
    def name_id(self, value):
        self._name_id = value


class DummySnapshot(object):

    def __init__(self, snapid):
        super(DummySnapshot, self).__init__()
        self.id = snapid
        self.volume_id = None


@ddt.ddt
class VolumeIDConvertTest(volume_helper.MStorageDSVDriver, test.TestCase):

    def setUp(self):
        super(VolumeIDConvertTest, self).setUp()
        self.mock_object(self, '_create_ismview_dir')
        self._set_config(conf.Configuration(None), 'dummy', 'dummy')
        self.do_setup(None)

    @ddt.data(("AAAAAAAA", "LX:37mA82"), ("BBBBBBBB", "LX:3R9ZwR"))
    @ddt.unpack
    def test_volumeid_should_change_62scale(self, volid, ldname):
        vol = DummyVolume(volid)
        actual = self._convert_id2name(vol)
        self.assertEqual(ldname, actual,
                         "ID:%(volid)s should be change to %(ldname)s" %
                         {'volid': volid, 'ldname': ldname})

    @ddt.data(("AAAAAAAA", "LX:37mA82"), ("BBBBBBBB", "LX:3R9ZwR"))
    @ddt.unpack
    def test_snap_volumeid_should_change_62scale_andpostfix(self,
                                                            snapid,
                                                            ldname):
        snap = DummySnapshot(snapid)
        actual = self._convert_id2snapname(snap)
        self.assertEqual(ldname, actual,
                         "ID:%(snapid)s should be change to %(ldname)s" %
                         {'snapid': snapid, 'ldname': ldname})

    @ddt.data(("AAAAAAAA", "LX:37mA82_m"), ("BBBBBBBB", "LX:3R9ZwR_m"))
    @ddt.unpack
    def test_ddrsnap_volumeid_should_change_62scale_and_m(self,
                                                          volid,
                                                          ldname):
        vol = DummyVolume(volid)
        actual = self._convert_id2migratename(vol)
        self.assertEqual(ldname, actual,
                         "ID:%(volid)s should be change to %(ldname)s" %
                         {'volid': volid, 'ldname': ldname})

    def test_convert_deleteldname(self):
        ldname = self._convert_deleteldname('LX:287RbQoP7VdwR1WsPC2fZT')
        self.assertEqual(ldname, 'LX:287RbQoP7VdwR1WsPC2fZT_d')


class NominatePoolLDTest(volume_helper.MStorageDSVDriver, test.TestCase):

    def setUp(self):
        super(NominatePoolLDTest, self).setUp()
        self.mock_object(self, '_create_ismview_dir')
        self._set_config(conf.Configuration(None), 'dummy', 'dummy')
        self.mock_object(self._cli, '_execute',
                         return_value=('success', 0, 0))
        self.mock_object(self._cli, 'view_all', return_value=xml_out)
        self.do_setup(None)
        self.xml = xml_out
        self._properties['cli_fip'] = '10.0.0.1'
        self._properties['pool_pools'] = {0, 1}
        self._properties['pool_backup_pools'] = {2, 3}
        (self.pools,
         self.lds,
         self.ldsets,
         self.used_ldns,
         self.hostports,
         self.max_ld_count) = self.configs(self.xml)

        pool_data = {'pool_num': 1,
                     'total': 1,
                     'free': 1,
                     'ld_list': []}
        volume = {'id': 'X'}
        self.test_pools = []
        for var in range(0, 1025):
            pool_data['ld_list'].append(volume)
        self.test_pools = [pool_data]

    def test_getxml(self):
        self.assertIsNotNone(self.xml, "iSMview xml should not be None")

    def test_selectldn_for_normalvolume(self):
        ldn = self._select_ldnumber(self.used_ldns, self.max_ld_count)
        self.assertEqual(2, ldn, "selected ldn should be XXX")

    def test_selectpool_for_normalvolume(self):
        vol = DummyVolume(constants.VOLUME_ID, 10)
        pool = self._select_leastused_poolnumber(vol,
                                                 self.pools,
                                                 self.xml)
        self.assertEqual(1, pool, "selected pool should be 1")
        # config:pool_pools=[1]
        vol.size = 999999999999
        with self.assertRaisesRegex(exception.VolumeBackendAPIException,
                                    'No available pools found.'):
            pool = self._select_leastused_poolnumber(vol,
                                                     self.pools,
                                                     self.xml)

    def test_return_poolnumber(self):
        self.assertEqual(1, self._return_poolnumber(self.test_pools))

    def test_selectpool_for_migratevolume(self):
        vol = DummyVolume("46045673-41e7-44a7-9333-02f07feab04b")
        self.VERSION = '9.99.9'
        dummyhost = {}
        dummyhost['capabilities'] = self._update_volume_status()
        pool = self._select_migrate_poolnumber(vol,
                                               self.pools,
                                               self.xml,
                                               dummyhost)
        self.assertEqual(1, pool, "selected pool should be 1")
        vol.id = "1febb976-86d0-42ed-9bc0-4aa3e158f27d"
        pool = self._select_migrate_poolnumber(vol,
                                               self.pools,
                                               self.xml,
                                               dummyhost)
        self.assertEqual(-1, pool, "selected pool is the same pool(return -1)")
        vol.size = 999999999999
        with self.assertRaisesRegex(exception.VolumeBackendAPIException,
                                    'No available pools found.'):
            pool = self._select_migrate_poolnumber(vol,
                                                   self.pools,
                                                   self.xml,
                                                   dummyhost)

    def test_selectpool_for_snapvolume(self):
        savePool1 = self.pools[1]['free']
        self.pools[1]['free'] = 0
        vol = DummyVolume(constants.VOLUME_ID, 10)
        pool = self._select_dsv_poolnumber(vol, self.pools)
        self.assertEqual(2, pool, "selected pool should be 2")
        # config:pool_backup_pools=[2]
        self.pools[1]['free'] = savePool1

        if len(self.pools[0]['ld_list']) == 1024:
            savePool2 = self.pools[2]['free']
            savePool3 = self.pools[3]['free']
            self.pools[2]['free'] = 0
            self.pools[3]['free'] = 0
            with self.assertRaisesRegex(exception.VolumeBackendAPIException,
                                        'No available pools found.'):
                pool = self._select_dsv_poolnumber(vol, self.pools)
            self.pools[2]['free'] = savePool2
            self.pools[3]['free'] = savePool3

        vol.size = 999999999999
        pool = self._select_dsv_poolnumber(vol, self.pools)
        self.assertEqual(2, pool, "selected pool should be 2")
        # config:pool_backup_pools=[2]

    def test_selectpool_for_ddrvolume(self):
        vol = DummyVolume(constants.VOLUME_ID, 10)
        pool = self._select_ddr_poolnumber(vol,
                                           self.pools,
                                           self.xml,
                                           10)
        self.assertEqual(2, pool, "selected pool should be 2")
        # config:pool_backup_pools=[2]

        savePool2 = self.pools[2]['free']
        savePool3 = self.pools[3]['free']
        self.pools[2]['free'] = 0
        self.pools[3]['free'] = 0
        with self.assertRaisesRegex(exception.VolumeBackendAPIException,
                                    'No available pools found.'):
            pool = self._select_ddr_poolnumber(vol,
                                               self.pools,
                                               self.xml,
                                               10)
        self.pools[2]['free'] = savePool2
        self.pools[3]['free'] = savePool3

        vol.size = 999999999999
        with self.assertRaisesRegex(exception.VolumeBackendAPIException,
                                    'No available pools found.'):
            pool = self._select_ddr_poolnumber(vol,
                                               self.pools,
                                               self.xml,
                                               999999999999)

    def test_selectpool_for_volddrvolume(self):
        vol = DummyVolume(constants.VOLUME_ID, 10)
        pool = self._select_volddr_poolnumber(vol,
                                              self.pools,
                                              self.xml,
                                              10)
        self.assertEqual(1, pool, "selected pool should be 1")
        # config:pool_backup_pools=[2]

        savePool0 = self.pools[0]['free']
        savePool1 = self.pools[1]['free']
        self.pools[0]['free'] = 0
        self.pools[1]['free'] = 0
        with self.assertRaisesRegex(exception.VolumeBackendAPIException,
                                    'No available pools found.'):
            pool = self._select_volddr_poolnumber(vol,
                                                  self.pools,
                                                  self.xml,
                                                  10)
        self.pools[0]['free'] = savePool0
        self.pools[1]['free'] = savePool1

        vol.size = 999999999999
        with self.assertRaisesRegex(exception.VolumeBackendAPIException,
                                    'No available pools found.'):
            pool = self._select_volddr_poolnumber(vol,
                                                  self.pools,
                                                  self.xml,
                                                  999999999999)


class GetInformationTest(volume_helper.MStorageDSVDriver, test.TestCase):

    def setUp(self):
        super(GetInformationTest, self).setUp()
        self._set_config(conf.Configuration(None), 'dummy', 'dummy')
        self.do_setup(None)

    def test_get_ldset(self):
        self.xml = xml_out
        (self.pools,
         self.lds,
         self.ldsets,
         self.used_ldns,
         self.hostports,
         self.max_ld_count) = self.configs(self.xml)
        self._properties['ldset_name'] = ''
        ldset = self.get_ldset(self.ldsets)
        self.assertIsNone(ldset)
        self._properties['ldset_name'] = 'LX:OpenStack1'
        ldset = self.get_ldset(self.ldsets)
        self.assertEqual('LX:OpenStack1', ldset['ldsetname'])
        self._properties['ldset_name'] = 'LX:OpenStackX'
        with self.assertRaisesRegex(exception.NotFound,
                                    'Logical Disk Set'
                                    ' `LX:OpenStackX`'
                                    ' could not be found.'):
            self.get_ldset(self.ldsets)


class VolumeCreateTest(volume_helper.MStorageDSVDriver, test.TestCase):

    def setUp(self):
        super(VolumeCreateTest, self).setUp()
        self.mock_object(self, '_create_ismview_dir')
        self._set_config(conf.Configuration(None), 'dummy', 'dummy')
        self.mock_object(self._cli, '_execute',
                         return_value=('success', 0, 0))
        self.mock_object(self._cli, 'view_all', return_value=xml_out)
        self.do_setup(None)
        self.xml = xml_out

    def test_validate_migrate_volume(self):
        vol = DummyVolume("46045673-41e7-44a7-9333-02f07feab04b", 1)
        vol.status = 'available'
        self._validate_migrate_volume(vol, self.xml)

        vol.id = "AAAAAAAA"
        vol.status = 'available'
        with self.assertRaisesRegex(exception.NotFound,
                                    'Logical Disk `LX:37mA82`'
                                    ' could not be found.'):
            self._validate_migrate_volume(vol, self.xml)

    def test_extend_volume(self):
        vol = DummyVolume("46045673-41e7-44a7-9333-02f07feab04b", 1)
        vol.status = 'available'
        self.extend_volume(vol, 10)

        vol.id = "00046058-d38e-7f60-67b7-59ed65e54225"  # RV
        with self.assertRaisesRegex(exception.VolumeBackendAPIException,
                                    'RPL Attribute Error. '
                                    'RPL Attribute = RV.'):
            self.extend_volume(vol, 10)


class BindLDTest(volume_helper.MStorageDSVDriver, test.TestCase):

    def setUp(self):
        super(BindLDTest, self).setUp()
        self.mock_object(self, '_create_ismview_dir')
        self._set_config(conf.Configuration(None), 'dummy', 'dummy')
        self.mock_object(self._cli, '_execute',
                         return_value=('success', 0, 0))
        self.mock_object(self._cli, 'view_all', return_value=xml_out)
        self.do_setup(None)
        self.mock_object(self, '_bind_ld', return_value=(0, 0, 0))

    def test_bindld_CreateVolume(self):
        vol = DummyVolume(constants.VOLUME_ID, 1)
        vol.migration_status = "success"
        self.create_volume(vol)
        self._bind_ld.assert_called_once_with(
            vol, vol.size, None,
            self._convert_id2name,
            self._select_leastused_poolnumber)

    def test_bindld_CreateCloneVolume(self):
        vol = DummyVolume(constants.VOLUME_ID, 1)
        vol.migration_status = "success"
        src = DummyVolume("46045673-41e7-44a7-9333-02f07feab04b", 1)
        self.mock_object(self._cli, 'query_BV_SV_status',
                         return_value='snap/active')
        self.mock_object(self._cli, 'query_MV_RV_name',
                         return_value='separated')
        self.mock_object(self._cli, 'backup_restore')
        self.create_cloned_volume(vol, src)
        self._bind_ld.assert_called_once_with(
            vol, vol.size, None,
            self._convert_id2name,
            self._select_leastused_poolnumber)
        self.mock_object(self._cli, 'get_pair_lds',
                         return_value={'lds1', 'lds2', 'lds3'})
        with self.assertRaisesRegex(exception.VolumeBackendAPIException,
                                    'Cannot create clone volume. '
                                    'number of pairs reached 3. '
                                    'ldname=LX:287RbQoP7VdwR1WsPC2fZT'):
            self.create_cloned_volume(vol, src)

    def test_bindld_CreateCloneWaitingInterval(self):
        self.assertEqual(10, cli.get_sleep_time_for_clone(0))
        self.assertEqual(12, cli.get_sleep_time_for_clone(2))
        self.assertEqual(60, cli.get_sleep_time_for_clone(19))

    def test_delete_volume(self):
        ldname = "LX:287RbQoP7VdwR1WsPC2fZT"
        detached = self._detach_from_all(ldname, xml_out)
        self.assertTrue(detached)
        ldname = 'LX:31HxzqBiAFTUxxOlcVn3EA'
        detached = self._detach_from_all(ldname, xml_out)
        self.assertFalse(detached)
        vol = DummyVolume("1febb976-86d0-42ed-9bc0-4aa3e158f27d")
        with mock.patch.object(self._cli, 'unbind') as unbind_mock:
            self.delete_volume(vol)
            unbind_mock.assert_called_once_with('LX:yEUHrXa5AHMjOZZLb93eP')

        pools, lds, ldsets, used_ldns, hostports, max_ld_count = (
            self.configs(xml_out))
        vol = DummyVolume('1febb976-86d0-42ed-9bc0-4aa3e158f27d')
        vol._name_id = None
        with mock.patch.object(self._cli, 'unbind') as unbind_mock:
            self.delete_volume(vol)
            unbind_mock.assert_called_once_with('LX:yEUHrXa5AHMjOZZLb93eP')

        vol = DummyVolume('46045673-41e7-44a7-9333-02f07feab04b')
        vol._name_id = '1febb976-86d0-42ed-9bc0-4aa3e158f27d'
        with mock.patch.object(self._cli, 'unbind') as unbind_mock:
            self.delete_volume(vol)
            unbind_mock.assert_called_once_with('LX:yEUHrXa5AHMjOZZLb93eP')

        vol = DummyVolume(constants.VOLUME_ID)
        vol._name_id = 'a951f0eb-27ae-41a7-a5e5-604e721a16d4'
        with mock.patch.object(self._cli, 'unbind') as unbind_mock:
            self.delete_volume(vol)
            unbind_mock.assert_called_once_with('LX:59V9KIi0ZHWJ5yvjCG5RQ4_d')


class BindLDTest_Snap(volume_helper.MStorageDSVDriver, test.TestCase):

    def setUp(self):
        super(BindLDTest_Snap, self).setUp()
        self.mock_object(self, '_create_ismview_dir')
        self._set_config(conf.Configuration(None), 'dummy', 'dummy')
        self.mock_object(self._cli, '_execute',
                         return_value=('success', 0, 0))
        self.mock_object(self._cli, 'view_all', return_value=xml_out)
        self.do_setup(None)
        self.mock_object(self, '_bind_ld', return_value=(0, 0, 0))
        self.mock_object(self, '_create_snapshot')

    def test_bindld_CreateSnapshot(self):
        snap = DummySnapshot(constants.SNAPSHOT_ID)
        snap.volume_id = constants.VOLUME_ID
        self.create_snapshot(snap)
        self._create_snapshot.assert_called_once_with(
            snap, self._properties['diskarray_name'])

    def test_bindld_CreateFromSnapshot(self):
        vol = DummyVolume(constants.VOLUME_ID)
        vol.migration_status = "success"
        snap = DummySnapshot("63410c76-2f12-4473-873d-74a63dfcd3e2")
        snap.volume_id = "1febb976-86d0-42ed-9bc0-4aa3e158f27d"
        self.mock_object(self._cli, 'query_BV_SV_status',
                         return_value='snap/active')
        self.mock_object(self._cli, 'backup_restore')
        self.create_volume_from_snapshot(vol, snap)
        self._bind_ld.assert_called_once_with(
            vol, 1, None,
            self._convert_id2name,
            self._select_volddr_poolnumber, 1)


class ExportTest(volume_helper.MStorageDSVDriver, test.TestCase):

    def setUp(self):
        super(ExportTest, self).setUp()
        self.mock_object(self, '_create_ismview_dir')
        self._set_config(conf.Configuration(None), 'dummy', 'dummy')
        self.mock_object(self._cli, '_execute',
                         return_value=('success', 0, 0))
        self.mock_object(self._cli, 'view_all', return_value=xml_out)
        self.do_setup(None)

    def test_iscsi_initialize_connection(self):
        vol = DummyVolume("46045673-41e7-44a7-9333-02f07feab04b")
        connector = {'initiator': "iqn.1994-05.com.redhat:d1d8e8f23255",
                     'multipath': False}
        info = self.iscsi_initialize_connection(vol, connector)
        self.assertEqual('iscsi', info['driver_volume_type'])
        self.assertEqual('iqn.2001-03.target0000', info['data']['target_iqn'])
        self.assertIn(info['data']['target_portal'],
                      ['192.168.1.90:3260', '192.168.1.91:3260',
                       '192.168.2.92:3260', '192.168.2.93:3260'])
        self.assertEqual(0, info['data']['target_lun'])

        vol.id = "87d8d42f-7550-4f43-9a2b-fe722bf86941"
        with self.assertRaisesRegex(exception.NotFound,
                                    'Logical Disk `LX:48L3QCi4npuqxPX0Lyeu8H`'
                                    ' could not be found.'):
            self.iscsi_initialize_connection(vol, connector)

    def test_iscsi_multipath_initialize_connection(self):
        vol = DummyVolume("46045673-41e7-44a7-9333-02f07feab04b")
        connector = {'initiator': "iqn.1994-05.com.redhat:d1d8e8f23255",
                     'multipath': True}
        info = self.iscsi_initialize_connection(vol, connector)
        self.assertEqual('iscsi', info['driver_volume_type'])
        self.assertEqual('iqn.2001-03.target0000',
                         info['data']['target_iqn'])
        self.assertIn(info['data']['target_portal'],
                      ['192.168.1.90:3260', '192.168.1.91:3260',
                       '192.168.2.92:3260', '192.168.2.93:3260'])
        self.assertEqual(0, info['data']['target_lun'])
        self.assertEqual('iqn.2001-03.target0000',
                         info['data']['target_iqns'][0])
        self.assertEqual('iqn.2001-03.target0000',
                         info['data']['target_iqns'][1])
        self.assertEqual('iqn.2001-03.target0000',
                         info['data']['target_iqns'][2])
        self.assertEqual('iqn.2001-03.target0000',
                         info['data']['target_iqns'][3])
        self.assertEqual(info['data']['target_portals'][0],
                         '192.168.1.90:3260')
        self.assertEqual(info['data']['target_portals'][1],
                         '192.168.1.91:3260')
        self.assertEqual(info['data']['target_portals'][2],
                         '192.168.2.92:3260')
        self.assertEqual(info['data']['target_portals'][3],
                         '192.168.2.93:3260')
        self.assertEqual(0, info['data']['target_luns'][0])
        self.assertEqual(0, info['data']['target_luns'][1])
        self.assertEqual(0, info['data']['target_luns'][2])
        self.assertEqual(0, info['data']['target_luns'][3])

    def test_iscsi_terminate_connection(self):
        ctx = context.RequestContext('admin', 'fake', True)
        vol = fake_volume_obj(ctx, id='46045673-41e7-44a7-9333-02f07feab04b')
        connector = {'initiator': "iqn.1994-05.com.redhat:d1d8e8f23255",
                     'multipath': True, 'host': 'DummyHost'}
        attachment = {
            'id': constants.ATTACHMENT_ID,
            'volume_id': vol.id,
            'connector': connector
        }
        attach_object = volume_attachment.VolumeAttachment(**attachment)
        attachment = volume_attachment.VolumeAttachmentList(
            objects=[attach_object])
        vol.volume_attachment = attachment
        with mock.patch.object(self._cli, 'delldsetld',
                               return_value=(True, '')
                               ) as delldsetld_mock:
            ret = self._iscsi_terminate_connection(vol, connector)
            delldsetld_mock.assert_called_once_with(
                'LX:OpenStack0', 'LX:287RbQoP7VdwR1WsPC2fZT')
            self.assertIsNone(ret)

        attachment1 = {
            'id': constants.ATTACHMENT_ID,
            'volume_id': vol.id,
            'connector': connector
        }
        attachment2 = {
            'id': constants.ATTACHMENT2_ID,
            'volume_id': vol.id,
            'connector': connector
        }
        attach_object1 = volume_attachment.VolumeAttachment(**attachment1)
        attach_object2 = volume_attachment.VolumeAttachment(**attachment2)
        attachments = volume_attachment.VolumeAttachmentList(
            objects=[attach_object1, attach_object2])
        vol.volume_attachment = attachments
        with mock.patch.object(self._cli, 'delldsetld',
                               return_value=(True, '')
                               ) as delldsetld_mock:
            ret = self._iscsi_terminate_connection(vol, connector)
            delldsetld_mock.assert_not_called()
            self.assertIsNone(ret)

    def test_iscsi_terminate_connection_negative(self):
        ctx = context.RequestContext('admin', 'fake', True)
        vol = fake_volume_obj(ctx, id='46045673-41e7-44a7-9333-02f07feab04b')
        connector = {'initiator': "iqn.1994-05.com.redhat:d1d8e8f23255",
                     'multipath': True, 'host': 'DummyHost'}
        attachment = {
            'id': constants.ATTACHMENT_ID,
            'volume_id': vol.id,
            'connector': connector
        }
        attach_object = volume_attachment.VolumeAttachment(**attachment)
        attachment = volume_attachment.VolumeAttachmentList(
            objects=[attach_object])
        vol.volume_attachment = attachment
        with self.assertRaisesRegex(exception.VolumeBackendAPIException,
                                    r'Failed to unregister Logical Disk from'
                                    r' Logical Disk Set \(iSM31064\)'):
            self.mock_object(self._cli, 'delldsetld',
                             return_value=(False, 'iSM31064'))
            self._iscsi_terminate_connection(vol, connector)

    def test_fc_initialize_connection(self):
        ctx = context.RequestContext('admin', 'fake', True)
        vol = fake_volume_obj(ctx, id='46045673-41e7-44a7-9333-02f07feab04b')
        connector = {'wwpns': ["10000090FAA0786A", "10000090FAA0786B"],
                     'host': 'DummyHost'}
        attachment = {
            'id': constants.ATTACHMENT_ID,
            'volume_id': vol.id,
            'connector': connector
        }
        attach_object = volume_attachment.VolumeAttachment(**attachment)
        attachment = volume_attachment.VolumeAttachmentList(
            objects=[attach_object])
        vol.volume_attachment = attachment
        info = self._fc_initialize_connection(vol, connector)
        self.assertEqual('fibre_channel', info['driver_volume_type'])
        self.assertEqual('2100000991020012', info['data']['target_wwn'][0])
        self.assertEqual('2200000991020012', info['data']['target_wwn'][1])
        self.assertEqual('2900000991020012', info['data']['target_wwn'][2])
        self.assertEqual('2A00000991020012', info['data']['target_wwn'][3])
        self.assertEqual(
            '2100000991020012',
            info['data']['initiator_target_map']['10000090FAA0786A'][0])
        self.assertEqual(
            '2100000991020012',
            info['data']['initiator_target_map']['10000090FAA0786B'][0])
        self.assertEqual(
            '2200000991020012',
            info['data']['initiator_target_map']['10000090FAA0786A'][1])
        self.assertEqual(
            '2200000991020012',
            info['data']['initiator_target_map']['10000090FAA0786B'][1])
        self.assertEqual(
            '2900000991020012',
            info['data']['initiator_target_map']['10000090FAA0786A'][2])
        self.assertEqual(
            '2900000991020012',
            info['data']['initiator_target_map']['10000090FAA0786B'][2])
        self.assertEqual(
            '2A00000991020012',
            info['data']['initiator_target_map']['10000090FAA0786A'][3])
        self.assertEqual(
            '2A00000991020012',
            info['data']['initiator_target_map']['10000090FAA0786B'][3])
        with self.assertRaisesRegex(exception.VolumeBackendAPIException,
                                    r'Failed to unregister Logical Disk from'
                                    r' Logical Disk Set \(iSM31064\)'):
            self.mock_object(self._cli, 'delldsetld',
                             return_value=(False, 'iSM31064'))
            self._fc_terminate_connection(vol, connector)
        ctx = context.RequestContext('admin', 'fake', True)
        vol = fake_volume_obj(ctx, id='46045673-41e7-44a7-9333-02f07feab04b')
        attachment = {
            'id': constants.ATTACHMENT_ID,
            'volume_id': vol.id,
            'connector': connector
        }
        attach_object = volume_attachment.VolumeAttachment(**attachment)
        attachment = volume_attachment.VolumeAttachmentList(
            objects=[attach_object])
        vol.volume_attachment = attachment
        with mock.patch.object(self._cli, 'delldsetld',
                               return_value=(True, '')
                               ) as delldsetld_mock:
            self._fc_terminate_connection(vol, connector)
            delldsetld_mock.assert_called_once_with(
                'LX:OpenStack1', 'LX:287RbQoP7VdwR1WsPC2fZT')

        attachment1 = {
            'id': constants.ATTACHMENT_ID,
            'volume_id': vol.id,
            'connector': connector
        }
        attachment2 = {
            'id': constants.ATTACHMENT2_ID,
            'volume_id': vol.id,
            'connector': connector
        }
        attach_object1 = volume_attachment.VolumeAttachment(**attachment1)
        attach_object2 = volume_attachment.VolumeAttachment(**attachment2)
        attachments = volume_attachment.VolumeAttachmentList(
            objects=[attach_object1, attach_object2])
        vol.volume_attachment = attachments
        with mock.patch.object(self._cli, 'delldsetld',
                               return_value=(True, '')
                               ) as delldsetld_mock:
            self._fc_terminate_connection(vol, connector)
            delldsetld_mock.assert_not_called()

        vol = fake_volume_obj(ctx, id='ccd662e5-2efe-4899-b12f-114b5cad81c3')
        connector = {'wwpns': ["10000090FAA0786A", "10000090FAA0786B"],
                     'host': 'HostA'}
        atchmnt = {
            'id': constants.ATTACHMENT_ID,
            'volume_id': vol.id,
            'connector': connector
        }
        attach_object = volume_attachment.VolumeAttachment(**atchmnt)
        attachment = volume_attachment.VolumeAttachmentList(
            objects=[attach_object])
        vol.volume_attachment = attachment

        info = self._fc_initialize_connection(vol, connector)
        self.assertEqual(2, info['data']['target_lun'])

        connector = {'wwpns': ["10000090FAA0786C", "10000090FAA0786D"],
                     'host': 'HostB'}
        atchmnt = {
            'id': constants.ATTACHMENT_ID,
            'volume_id': vol.id,
            'connector': connector
        }
        attach_object = volume_attachment.VolumeAttachment(**atchmnt)
        attachment = volume_attachment.VolumeAttachmentList(
            objects=[attach_object])
        vol.volume_attachment = attachment

        info = self._fc_initialize_connection(vol, connector)
        self.assertEqual(1, info['data']['target_lun'])

    def test_fc_terminate_connection(self):
        ctx = context.RequestContext('admin', 'fake', True)
        vol = fake_volume_obj(ctx, id='46045673-41e7-44a7-9333-02f07feab04b')
        connector = {'wwpns': ["10000090FAA0786A", "10000090FAA0786B"],
                     'host': 'DummyHost'}
        attachment = {
            'id': constants.ATTACHMENT_ID,
            'volume_id': vol.id,
            'connector': connector
        }
        attach_object = volume_attachment.VolumeAttachment(**attachment)
        attachment = volume_attachment.VolumeAttachmentList(
            objects=[attach_object])
        vol.volume_attachment = attachment
        info = self._fc_terminate_connection(vol, connector)
        self.assertEqual('fibre_channel', info['driver_volume_type'])
        self.assertEqual('2100000991020012', info['data']['target_wwn'][0])
        self.assertEqual('2200000991020012', info['data']['target_wwn'][1])
        self.assertEqual('2900000991020012', info['data']['target_wwn'][2])
        self.assertEqual('2A00000991020012', info['data']['target_wwn'][3])
        self.assertEqual(
            '2100000991020012',
            info['data']['initiator_target_map']['10000090FAA0786A'][0])
        self.assertEqual(
            '2100000991020012',
            info['data']['initiator_target_map']['10000090FAA0786B'][0])
        self.assertEqual(
            '2200000991020012',
            info['data']['initiator_target_map']['10000090FAA0786A'][1])
        self.assertEqual(
            '2200000991020012',
            info['data']['initiator_target_map']['10000090FAA0786B'][1])
        self.assertEqual(
            '2900000991020012',
            info['data']['initiator_target_map']['10000090FAA0786A'][2])
        self.assertEqual(
            '2900000991020012',
            info['data']['initiator_target_map']['10000090FAA0786B'][2])
        self.assertEqual(
            '2A00000991020012',
            info['data']['initiator_target_map']['10000090FAA0786A'][3])
        self.assertEqual(
            '2A00000991020012',
            info['data']['initiator_target_map']['10000090FAA0786B'][3])
        info = self._fc_terminate_connection(vol, None)
        self.assertEqual('fibre_channel', info['driver_volume_type'])
        self.assertEqual({}, info['data'])

    def test_is_multi_attachment(self):
        ctx = context.RequestContext('admin', 'fake', True)
        vol = fake_volume_obj(ctx, id=constants.VOLUME_ID)
        connector = {'wwpns': ["10000090FAA0786A", "10000090FAA0786B"],
                     'host': 'DummyHost'}
        attachment1 = {
            'id': constants.ATTACHMENT_ID,
            'volume_id': vol.id,
            'connector': connector
        }
        attachment2 = {
            'id': constants.ATTACHMENT2_ID,
            'volume_id': vol.id,
            'connector': connector
        }
        attach_object1 = volume_attachment.VolumeAttachment(**attachment1)
        attach_object2 = volume_attachment.VolumeAttachment(**attachment2)
        attachments = volume_attachment.VolumeAttachmentList(
            objects=[attach_object1, attach_object2])
        vol.volume_attachment = attachments
        ret = self._is_multi_attachment(vol, connector)
        self.assertTrue(ret)

        attachments = volume_attachment.VolumeAttachmentList(
            objects=[attach_object1])
        vol.volume_attachment = attachments
        ret = self._is_multi_attachment(vol, connector)
        self.assertFalse(ret)

        vol.volume_attachment = None
        ret = self._is_multi_attachment(vol, connector)
        self.assertFalse(ret)


class DeleteDSVVolume_test(volume_helper.MStorageDSVDriver,
                           test.TestCase):

    def setUp(self):
        super(DeleteDSVVolume_test, self).setUp()
        self.mock_object(self, '_create_ismview_dir')
        self._set_config(conf.Configuration(None), 'dummy', 'dummy')
        self.mock_object(self._cli, '_execute',
                         return_value=('success', 0, 0))
        self.mock_object(self._cli, 'view_all', return_value=xml_out)
        self.do_setup(None)

    def test_delete_snapshot(self):
        self.mock_object(self._cli, 'query_BV_SV_status',
                         return_value='snap/active')
        snap = DummySnapshot(constants.SNAPSHOT_ID)
        snap.volume_id = constants.VOLUME_ID
        ret = self.delete_snapshot(snap)
        self.assertIsNone(ret)


class NonDisruptiveBackup_test(volume_helper.MStorageDSVDriver,
                               test.TestCase):

    def setUp(self):
        super(NonDisruptiveBackup_test, self).setUp()
        self.mock_object(self, '_create_ismview_dir')
        self._set_config(conf.Configuration(None), 'dummy', 'dummy')
        self.mock_object(self._cli, '_execute',
                         return_value=('success', 0, 0))
        self.mock_object(self._cli, 'view_all', return_value=xml_out)
        self.mock_object(self._cli, 'query_BV_SV_status',
                         return_value='snap/active')
        self.do_setup(None)
        self.xml = xml_out
        (self.pools,
         self.lds,
         self.ldsets,
         self.used_ldns,
         self.hostports,
         self.max_ld_count) = self.configs(self.xml)

    def test_validate_ld_exist(self):
        vol = DummyVolume("46045673-41e7-44a7-9333-02f07feab04b")
        ldname = self._validate_ld_exist(
            self.lds, vol.id, self._properties['ld_name_format'])
        self.assertEqual('LX:287RbQoP7VdwR1WsPC2fZT', ldname)
        vol.id = "00000000-0000-0000-0000-6b6d96553b4b"
        with self.assertRaisesRegex(exception.NotFound,
                                    'Logical Disk `LX:XXXXXXXX`'
                                    ' could not be found.'):
            self._validate_ld_exist(
                self.lds, vol.id, self._properties['ld_name_format'])

    def test_validate_iscsildset_exist(self):
        connector = {'initiator': "iqn.1994-05.com.redhat:d1d8e8f23255"}
        ldset = self._validate_iscsildset_exist(self.ldsets, connector)
        self.assertEqual('LX:OpenStack0', ldset['ldsetname'])
        connector = {'initiator': "iqn.1994-05.com.redhat:d1d8e8f232XX"}
        mock_data = {'ldsetname': 'LX:redhatd1d8e8f23',
                     'protocol': 'iSCSI',
                     'mode': 'Multi-Target',
                     'portal_list': ['1.1.1.1:3260', '2.2.2.2:3260'],
                     'lds': {},
                     'initiator_list':
                         ['iqn.1994-05.com.redhat:d1d8e8f232XX']}
        mock_ldset = {}
        mock_ldset['LX:redhatd1d8e8f23'] = mock_data
        self.mock_object(
            self, 'configs',
            return_value=(None, None, mock_ldset, None, None, None))
        ldset = self._validate_iscsildset_exist(self.ldsets, connector)
        self.assertEqual('LX:redhatd1d8e8f23', ldset['ldsetname'])
        self.assertEqual('iqn.1994-05.com.redhat:d1d8e8f232XX',
                         ldset['initiator_list'][0])

    def test_validate_fcldset_exist(self):
        connector = {'wwpns': ["10000090FAA0786A", "10000090FAA0786B"]}
        ldset = self._validate_fcldset_exist(self.ldsets, connector)
        self.assertEqual('LX:OpenStack1', ldset['ldsetname'])
        connector = {'wwpns': ["10000090FAA0786X", "10000090FAA0786Y"]}
        mock_data = {'ldsetname': 'LX:10000090FAA0786X',
                     'lds': {},
                     'protocol': 'FC',
                     'wwpn': ["1000-0090-FAA0-786X", "1000-0090-FAA0-786Y"],
                     'port': []}
        mock_ldset = {}
        mock_ldset['LX:10000090FAA0786X'] = mock_data
        self.mock_object(
            self, 'configs',
            return_value=(None, None, mock_ldset, None, None, None))
        ldset = self._validate_fcldset_exist(self.ldsets, connector)
        self.assertEqual('LX:10000090FAA0786X', ldset['ldsetname'])
        self.assertEqual('1000-0090-FAA0-786X', ldset['wwpn'][0])
        self.assertEqual('1000-0090-FAA0-786Y', ldset['wwpn'][1])

    def test_enumerate_iscsi_portals(self):
        connector = {'initiator': "iqn.1994-05.com.redhat:d1d8e8f23255"}
        ldset = self._validate_iscsildset_exist(self.ldsets, connector)
        self.assertEqual('LX:OpenStack0', ldset['ldsetname'])
        portal = self._enumerate_iscsi_portals(self.hostports, ldset)
        self.assertEqual('192.168.1.90:3260', portal[0])
        self.assertEqual('192.168.1.91:3260', portal[1])
        self.assertEqual('192.168.2.92:3260', portal[2])
        self.assertEqual('192.168.2.93:3260', portal[3])

    def test_initialize_connection_snapshot(self):
        snap = DummySnapshot('46045673-41e7-44a7-9333-02f07feab04b')
        snap.volume_id = "92dbc7f4-dbc3-4a87-aef4-d5a2ada3a9af"
        connector = {'initiator': "iqn.1994-05.com.redhat:d1d8e8f23255",
                     'multipath': True}
        ret = self.iscsi_initialize_connection_snapshot(snap, connector)
        self.assertIsNotNone(ret)
        self.assertEqual('iscsi', ret['driver_volume_type'])

        connector = {'wwpns': ["10000090FAA0786A", "10000090FAA0786B"]}
        ret = self.fc_initialize_connection_snapshot(snap, connector)
        self.assertIsNotNone(ret)
        self.assertEqual('fibre_channel', ret['driver_volume_type'])

        ldset_lds0 = {'ldsetname': 'LX:OpenStack1', 'lds': {},
                      'protocol': 'FC',
                      'wwpn': ['1000-0090-FAA0-786A', '1000-0090-FAA0-786B'],
                      'port': []}
        ldset_lds1 = {'ldsetname': 'LX:OpenStack1',
                      'lds': {16: {'ldn': 16, 'lun': 0}},
                      'protocol': 'FC',
                      'wwpn': ['1000-0090-FAA0-786A', '1000-0090-FAA0-786B'],
                      'port': []}
        ldset_lds2 = {'ldsetname': 'LX:OpenStack1',
                      'lds': {6: {'ldn': 6, 'lun': 1}},
                      'protocol': 'FC',
                      'wwpn': ['1000-0090-FAA0-786A', '1000-0090-FAA0-786B'],
                      'port': []}
        return_ldset = [ldset_lds0, ldset_lds1, ldset_lds2]
        self.mock_object(self, '_validate_fcldset_exist',
                         side_effect=return_ldset)
        mocker = self.mock_object(self._cli, 'addldsetld',
                                  mock.Mock(wraps=self._cli.addldsetld))
        connector = {'wwpns': ["10000090FAA0786A", "10000090FAA0786B"]}
        ret = self.fc_initialize_connection_snapshot(snap, connector)
        self.assertIsNotNone(ret)
        self.assertEqual('fibre_channel', ret['driver_volume_type'])
        mocker.assert_any_call('LX:OpenStack1', 'LX:__ControlVolume_10h', 0)
        mocker.assert_any_call('LX:OpenStack1',
                               'LX:287RbQoP7VdwR1WsPC2fZT_l', 1)

    def test_terminate_connection_snapshot(self):
        ctx = context.RequestContext('admin', 'fake', True)
        snap = fake_volume_obj(ctx, id="46045673-41e7-44a7-9333-02f07feab04b")
        connector = {'initiator': 'iqn.1994-05.com.redhat:d1d8e8f23255',
                     'host': 'DummyHost'}
        attachment = {
            'id': constants.ATTACHMENT_ID,
            'volume_id': snap.id,
            'connector': connector
        }
        attach_object = volume_attachment.VolumeAttachment(**attachment)
        attachment = volume_attachment.VolumeAttachmentList(
            objects=[attach_object])
        snap.volume_attachment = attachment
        self.iscsi_terminate_connection_snapshot(snap, connector)

        connector = {'wwpns': ["10000090FAA0786A", "10000090FAA0786B"],
                     'host': 'DummyHost'}
        attachment = {
            'id': constants.ATTACHMENT_ID,
            'volume_id': snap.id,
            'connector': connector
        }
        attach_object = volume_attachment.VolumeAttachment(**attachment)
        attachment = volume_attachment.VolumeAttachmentList(
            objects=[attach_object])
        snap.volume_attachment = attachment
        mocker = self.mock_object(self, '_is_multi_attachment',
                                  mock.Mock(wraps=self._is_multi_attachment))
        ret = self.fc_terminate_connection_snapshot(snap, connector,
                                                    is_snapshot=True)
        self.assertEqual('fibre_channel', ret['driver_volume_type'])
        mocker.assert_not_called()

    def test_remove_export_snapshot(self):
        snap = DummySnapshot('46045673-41e7-44a7-9333-02f07feab04b')
        self.remove_export_snapshot(None, snap)

    def test_backup_use_temp_snapshot(self):
        ret = self.backup_use_temp_snapshot()
        self.assertTrue(ret)


class VolumeStats_test(volume_helper.MStorageDSVDriver, test.TestCase):

    def setUp(self):
        super(VolumeStats_test, self).setUp()
        self._set_config(conf.Configuration(None), 'dummy', 'dummy')
        self.do_setup(None)
        self._properties['cli_fip'] = '10.0.0.1'
        self._properties['pool_pools'] = {0, 1}
        self._properties['pool_backup_pools'] = {2, 3}
        self.VERSION = '9.99.9'

    def test_update_volume_status(self):
        self.mock_object(volume_common.MStorageVolumeCommon, 'parse_xml',
                         side_effect=Exception)
        stats = self._update_volume_status()
        self.assertEqual('dummy', stats.get('volume_backend_name'))
        self.assertEqual('NEC', stats.get('vendor_name'))
        self.assertEqual(self.VERSION, stats.get('driver_version'))
        self.assertEqual('10.0.0.1', stats.get('location_info').split(':')[0])
        self.assertEqual('0,1', stats.get('location_info').split(':')[1])


class GetFreeLun_test(volume_helper.MStorageDSVDriver, test.TestCase):

    def setUp(self):
        super(GetFreeLun_test, self).setUp()
        self.do_setup(None)

    def test_get_free_lun_iscsi_multi(self):
        ldset = {'protocol': 'iSCSI',
                 'mode': 'Multi-Target',
                 'lds': {}}
        target_lun = self._get_free_lun(ldset)
        self.assertIsNone(target_lun)

    def test_get_free_lun_iscsi_lun0(self):
        ldset = {'protocol': 'iSCSI',
                 'mode': 'Normal',
                 'lds': {}}
        target_lun = self._get_free_lun(ldset)
        self.assertEqual(0, target_lun)

    def test_get_free_lun_iscsi_lun2(self):
        ld0 = {'lun': 0}
        ld1 = {'lun': 1}
        ld3 = {'lun': 3}
        ldsetlds = {}
        ldsetlds[0] = ld0
        ldsetlds[1] = ld1
        ldsetlds[3] = ld3
        ldset = {'protocol': 'iSCSI',
                 'mode': 'Normal',
                 'lds': ldsetlds}
        target_lun = self._get_free_lun(ldset)
        self.assertEqual(2, target_lun)

    def test_get_free_lun_fc_lun1(self):
        ld0 = {'lun': 0}
        ldsetlds = {}
        ldsetlds[0] = ld0
        ldset = {'lds': ldsetlds,
                 'protocol': 'FC'}
        target_lun = self._get_free_lun(ldset)
        self.assertEqual(1, target_lun)


class Migrate_test(volume_helper.MStorageDSVDriver, test.TestCase):

    def setUp(self):
        super(Migrate_test, self).setUp()
        self.mock_object(self, '_create_ismview_dir')
        self._set_config(conf.Configuration(None), 'dummy', 'dummy')
        self.mock_object(self._cli, '_execute',
                         return_value=('success', 0, 0))
        self.mock_object(self._cli, 'view_all', return_value=xml_out)
        self.mock_object(self, '_bind_ld', return_value=(0, 0, 0))
        self.mock_object(self._cli, 'backup_restore')
        self.mock_object(volume_types, 'get_volume_type',
                         return_value={})
        self.mock_object(qos_specs, 'get_qos_specs',
                         return_value={})
        self.do_setup(None)
        self._properties['cli_fip'] = '10.0.0.1'
        self._properties['pool_pools'] = {0, 1}
        self._properties['pool_backup_pools'] = {2, 3}
        self.newvol = DummyVolume(constants.VOLUME_ID)
        self.sourcevol = DummyVolume(constants.VOLUME2_ID)
        self.host = {}
        self.VERSION = '9.99.9'
        self.host['capabilities'] = self._update_volume_status()
        self.xml = xml_out

    def test_update_migrate_volume(self):
        newvol = DummyVolume(constants.VOLUME_ID)
        sourcevol = DummyVolume(constants.VOLUME2_ID)
        update_data = self.update_migrated_volume(None, sourcevol,
                                                  newvol, 'available')
        self.assertIsNone(update_data['_name_id'])
        self.assertIsNone(update_data['provider_location'])

    def test_migrate_volume(self):
        vol = DummyVolume(constants.VOLUME2_ID)
        vol.status = 'available'
        moved, __ = self.migrate_volume(None, vol,
                                        self.host)
        self.assertTrue(moved)

        vol = DummyVolume(constants.VOLUME2_ID)
        vol.status = 'in-use'
        moved, __ = self.migrate_volume(None, vol,
                                        self.host)
        self.assertFalse(moved)

        vol.id = "87d8d42f-7550-4f43-9a2b-fe722bf86941"
        with self.assertRaisesRegex(exception.NotFound,
                                    'Logical Disk `LX:48L3QCi4npuqxPX0Lyeu8H`'
                                    ' could not be found.'):
            self._validate_migrate_volume(vol, xml_out)

        vol.id = '46045673-41e7-44a7-9333-02f07feab04b'
        vol.status = 'creating'
        moved, __ = self.migrate_volume(None, vol,
                                        self.host)
        self.assertFalse(moved)

        vol.id = "92dbc7f4-dbc3-4a87-aef4-d5a2ada3a9af"
        vol.status = 'available'
        with self.assertRaisesRegex(exception.VolumeBackendAPIException,
                                    r'Specified Logical Disk '
                                    r'LX:4T7JpyqI3UuPlKeT9D3VQF has an '
                                    r'invalid attribute '
                                    r'\(\(invalid attribute\)\).'):
            self._validate_migrate_volume(vol, xml_out)

    def test_retype_volume(self):
        vol = DummyVolume(constants.VOLUME2_ID)
        diff = {'encryption': {},
                'qos_specs': {},
                'extra_specs': {u'volume_backend_name': (u'Storage1',
                                                         u'Storage2')}}
        new_type = {'id': constants.VOLUME_TYPE_ID}
        retyped = self.retype(None, vol, new_type, diff, self.host)
        self.assertTrue(retyped)

        volume_type = {'name': u'Bronze',
                       'qos_specs_id': u'57223246-1d49-4565-860f-bbbee6cee122',
                       'deleted': False,
                       'created_at': '2019-01-08 08:48:20',
                       'updated_at': '2019-01-08 08:48:29',
                       'extra_specs': {}, 'is_public': True,
                       'deleted_at': None,
                       'id': u'33cd6136-0465-4ee0-82fa-b5f3a9138249',
                       'description': None}
        specs = {'specs': {u'lowerlimit': u'500', u'upperlimit': u'2000'}}
        volume_types.get_volume_type.return_value = volume_type
        qos_specs.get_qos_specs.return_value = specs
        diff = {'encryption': {},
                'qos_specs': {'consumer': (u'back-end', u'back-end'),
                              u'lowerlimit': (u'1000', u'500'),
                              u'upperlimit': (u'3000', u'2000')},
                'extra_specs': {u'volume_backend_name': (u'Storage', None)}}
        retyped = self.retype(None, vol, new_type, diff, self.host)
        self.assertTrue(retyped)
        diff = {'encryption': {},
                'qos_specs': {'consumer': (u'back-end', None),
                              u'lowerlimit': (u'1000', u'500'),
                              u'upperlimit': (u'3000', u'2000')},
                'extra_specs': {}}
        retyped = self.retype(None, vol, new_type, diff, self.host)
        self.assertTrue(retyped)

        vol.attach_status = 'attached'
        diff = {'encryption': {},
                'qos_specs': {},
                'extra_specs': {u'volume_backend_name': (u'Storage1',
                                                         u'Storage2')}}
        retyped = self.retype(None, vol, new_type, diff, self.host)
        self.assertFalse(retyped)

    def test_validate_retype_volume(self):
        vol = DummyVolume("87d8d42f-7550-4f43-9a2b-fe722bf86941")
        with self.assertRaisesRegex(exception.NotFound,
                                    'Logical Disk `LX:48L3QCi4npuqxPX0Lyeu8H`'
                                    ' could not be found.'):
            self._validate_retype_volume(vol, xml_out)

        vol = DummyVolume("92dbc7f4-dbc3-4a87-aef4-d5a2ada3a9af")
        with self.assertRaisesRegex(exception.VolumeBackendAPIException,
                                    r'Specified Logical Disk '
                                    r'LX:4T7JpyqI3UuPlKeT9D3VQF has an '
                                    r'invalid attribute '
                                    r'\(\(invalid attribute\)\).'):
            self._validate_retype_volume(vol, xml_out)

    def test_spec_is_changed(self):
        extra_specs = {u'volume_backend_name': (u'Storage', None)}
        equal = self._spec_is_changed(extra_specs, 'volume_backend_name')
        self.assertTrue(equal)

        extra_specs = {u'volume_backend_name': (u'Storage', u'Storage')}
        equal = self._spec_is_changed(extra_specs, 'volume_backend_name')
        self.assertFalse(equal)

    def test_check_same_backend(self):
        diff = {'encryption': {},
                'qos_specs': {'consumer': (u'back-end', u'back-end'),
                              u'upperlimit': (u'3000', u'2000'),
                              u'lowerlimit': (u'1000', u'500')},
                'extra_specs': {u'volume_backend_name': (u'Storage', None)}}
        qos = self._check_same_backend(diff)
        self.assertFalse(qos)

        diff['extra_specs'] = {u'volume_backend_name':
                               (u'Storage', u'Storage')}
        qos = self._check_same_backend(diff)
        self.assertTrue(qos)

        diff['extra_specs'] = {u'volume_backend_name': (u'Storage', None),
                               u'dummy_specs': None}
        qos = self._check_same_backend(diff)
        self.assertFalse(qos)


class ManageUnmanage_test(volume_helper.MStorageDSVDriver, test.TestCase):

    def setUp(self):
        super(ManageUnmanage_test, self).setUp()
        self.mock_object(self, '_create_ismview_dir')
        self._set_config(conf.Configuration(None), 'dummy', 'dummy')
        self.mock_object(self._cli, 'view_all', return_value=xml_out)
        self.do_setup(None)
        self._properties['pool_pools'] = {0}
        self._properties['pool_backup_pools'] = {1}

    def test_is_manageable_volume(self):
        ld_ok_iv = {'pool_num': 0, 'RPL Attribute': 'IV', 'Purpose': '---'}
        ld_ok_bv = {'pool_num': 0, 'RPL Attribute': 'BV', 'Purpose': 'INV'}
        ld_ng_pool = {'pool_num': 1, 'RPL Attribute': 'IV', 'Purpose': '---'}
        ld_ng_rpl1 = {'pool_num': 0, 'RPL Attribute': 'MV', 'Purpose': 'INV'}
        ld_ng_rpl2 = {'pool_num': 0, 'RPL Attribute': 'RV', 'Purpose': 'INV'}
        ld_ng_rpl3 = {'pool_num': 0, 'RPL Attribute': 'SV', 'Purpose': 'INV'}
        ld_ng_purp = {'pool_num': 0, 'RPL Attribute': 'IV', 'Purpose': 'INV'}
        self.assertTrue(self._is_manageable_volume(ld_ok_iv))
        self.assertTrue(self._is_manageable_volume(ld_ok_bv))
        self.assertFalse(self._is_manageable_volume(ld_ng_pool))
        self.assertFalse(self._is_manageable_volume(ld_ng_rpl1))
        self.assertFalse(self._is_manageable_volume(ld_ng_rpl2))
        self.assertFalse(self._is_manageable_volume(ld_ng_rpl3))
        self.assertFalse(self._is_manageable_volume(ld_ng_purp))

    def test_get_manageable_volumes(self):
        current_volumes = []
        volumes = self.get_manageable_volumes(current_volumes, None,
                                              100, 0, ['reference'], ['dec'])
        self.assertEqual('LX:287RbQoP7VdwR1WsPC2fZT',
                         volumes[2]['reference']['source-name'])
        current_volumes = []
        volumes = self.get_manageable_volumes(current_volumes, None,
                                              100, 0, ['reference'], ['asc'])
        self.assertEqual('  :2000000991020012000A',
                         volumes[0]['reference']['source-name'])
        self.assertEqual(10, len(volumes))

        volume = {'id': '46045673-41e7-44a7-9333-02f07feab04b'}
        current_volumes = []
        current_volumes.append(volume)
        volumes = self.get_manageable_volumes(current_volumes, None,
                                              100, 0, ['reference'], ['dec'])
        self.assertFalse(volumes[2]['safe_to_manage'])
        self.assertFalse(volumes[3]['safe_to_manage'])
        self.assertTrue(volumes[4]['safe_to_manage'])

    def test_manage_existing(self):
        self.mock_object(self._cli, 'changeldname')
        current_volumes = []
        volumes = self.get_manageable_volumes(current_volumes, None,
                                              100, 0, ['reference'], ['dec'])
        newvol = DummyVolume(constants.VOLUME_ID)
        self.manage_existing(newvol, volumes[4]['reference'])
        self._cli.changeldname.assert_called_once_with(
            None, 'LX:vD03hJCiHvGpvP4iSevKk', '  :20000009910200140009')
        with self.assertRaisesRegex(exception.ManageExistingInvalidReference,
                                    'Specified resource is already in-use.'):
            self.manage_existing(newvol, volumes[3]['reference'])
        volume = {'source-name': 'LX:yEUHrXa5AHMjOZZLb93eP'}
        with self.assertRaisesRegex(exception.ManageExistingVolumeTypeMismatch,
                                    'Volume type is unmatched.'):
            self.manage_existing(newvol, volume)

    def test_manage_existing_get_size(self):
        current_volumes = []
        volumes = self.get_manageable_volumes(current_volumes, None,
                                              100, 0, ['reference'], ['dec'])
        newvol = DummyVolume(constants.VOLUME_ID)
        size_in_gb = self.manage_existing_get_size(newvol,
                                                   volumes[3]['reference'])
        self.assertEqual(10, size_in_gb)


class ManageUnmanage_Snap_test(volume_helper.MStorageDSVDriver, test.TestCase):

    def setUp(self):
        super(ManageUnmanage_Snap_test, self).setUp()
        self.mock_object(self, '_create_ismview_dir')
        self._set_config(conf.Configuration(None), 'dummy', 'dummy')
        self.mock_object(self._cli, 'view_all', return_value=xml_out)
        self.do_setup(None)
        self._properties['pool_pools'] = {0}
        self._properties['pool_backup_pools'] = {1}

    def test_is_manageable_snapshot(self):
        ld_ok_sv1 = {'pool_num': 1, 'RPL Attribute': 'SV', 'Purpose': 'INV'}
        ld_ok_sv2 = {'pool_num': 1, 'RPL Attribute': 'SV', 'Purpose': '---'}
        ld_ng_pool = {'pool_num': 0, 'RPL Attribute': 'SV', 'Purpose': 'INV'}
        ld_ng_rpl1 = {'pool_num': 1, 'RPL Attribute': 'MV', 'Purpose': 'INV'}
        ld_ng_rpl2 = {'pool_num': 1, 'RPL Attribute': 'RV', 'Purpose': 'INV'}
        ld_ng_rpl3 = {'pool_num': 1, 'RPL Attribute': 'IV', 'Purpose': '---'}
        ld_ng_rpl4 = {'pool_num': 1, 'RPL Attribute': 'BV', 'Purpose': 'INV'}
        self.assertTrue(self._is_manageable_snapshot(ld_ok_sv1))
        self.assertTrue(self._is_manageable_snapshot(ld_ok_sv2))
        self.assertFalse(self._is_manageable_snapshot(ld_ng_pool))
        self.assertFalse(self._is_manageable_snapshot(ld_ng_rpl1))
        self.assertFalse(self._is_manageable_snapshot(ld_ng_rpl2))
        self.assertFalse(self._is_manageable_snapshot(ld_ng_rpl3))
        self.assertFalse(self._is_manageable_snapshot(ld_ng_rpl4))

    def test_get_manageable_snapshots(self):
        self.mock_object(self._cli, 'get_bvname',
                         return_value='yEUHrXa5AHMjOZZLb93eP')
        current_snapshots = []
        volumes = self.get_manageable_snapshots(current_snapshots, None,
                                                100, 0, ['reference'], ['asc'])
        self.assertEqual('LX:4T7JpyqI3UuPlKeT9D3VQF',
                         volumes[0]['reference']['source-name'])

    def test_manage_existing_snapshot(self):
        self.mock_object(self._cli, 'changeldname')
        self.mock_object(self._cli, 'get_bvname',
                         return_value='yEUHrXa5AHMjOZZLb93eP')
        current_snapshots = []
        snaps = self.get_manageable_snapshots(current_snapshots, None,
                                              100, 0, ['reference'], ['asc'])
        newsnap = DummySnapshot('46045673-41e7-44a7-9333-02f07feab04b')
        newsnap.volume_id = "1febb976-86d0-42ed-9bc0-4aa3e158f27d"
        self.manage_existing_snapshot(newsnap, snaps[0]['reference'])
        self._cli.changeldname.assert_called_once_with(
            None,
            'LX:287RbQoP7VdwR1WsPC2fZT',
            'LX:4T7JpyqI3UuPlKeT9D3VQF')

        newsnap.volume_id = "AAAAAAAA"
        with self.assertRaisesRegex(exception.ManageExistingInvalidReference,
                                    'Snapshot source is unmatch.'):
            self.manage_existing_snapshot(newsnap, snaps[0]['reference'])

        self._cli.get_bvname.return_value = "2000000991020012000C"
        newsnap.volume_id = "00046058-d38e-7f60-67b7-59ed6422520c"
        snap = {'source-name': '  :2000000991020012000B'}
        with self.assertRaisesRegex(exception.ManageExistingVolumeTypeMismatch,
                                    'Volume type is unmatched.'):
            self.manage_existing_snapshot(newsnap, snap)

    def test_manage_existing_snapshot_get_size(self):
        self.mock_object(self._cli, 'get_bvname',
                         return_value='yEUHrXa5AHMjOZZLb93eP')
        current_snapshots = []
        snaps = self.get_manageable_snapshots(current_snapshots, None,
                                              100, 0, ['reference'], ['asc'])
        newsnap = DummySnapshot('46045673-41e7-44a7-9333-02f07feab04b')
        newsnap.volume_id = "1febb976-86d0-42ed-9bc0-4aa3e158f27d"
        size_in_gb = self.manage_existing_snapshot_get_size(
            newsnap,
            snaps[0]['reference'])
        self.assertEqual(6, size_in_gb)


class RevertToSnapshotTestCase(volume_helper.MStorageDSVDriver, test.TestCase):

    def setUp(self):
        super(RevertToSnapshotTestCase, self).setUp()
        self._set_config(conf.Configuration(None), 'dummy', 'dummy')
        self.do_setup(None)
        self.mock_object(self._cli, 'view_all', return_value=xml_out)

    def test_revert_to_snapshot(self):
        vol = DummyVolume("1febb976-86d0-42ed-9bc0-4aa3e158f27d")
        snap = DummySnapshot("63410c76-2f12-4473-873d-74a63dfcd3e2")
        self.mock_object(time, 'sleep')
        self.mock_object(self._cli, '_execute',
                         return_value=('success', 0, 0))
        self.mock_object(self._cli, 'query_BV_SV_status',
                         return_value='snap/active')
        self.revert_to_snapshot(None, vol, snap)
        self._cli._execute.assert_called_once_with(
            'iSMsc_restore -bv yEUHrXa5AHMjOZZLb93eP -bvflg ld '
            '-sv 31HxzqBiAFTUxxOlcVn3EA -svflg ld -derivsv keep -nowait')

        vol.id = constants.VOLUME_ID
        with self.assertRaisesRegex(exception.NotFound,
                                    'Logical Disk `LX:vD03hJCiHvGpvP4iSevKk` '
                                    'has unbound already.'):
            self.revert_to_snapshot(None, vol, snap)
        vol.id = '1febb976-86d0-42ed-9bc0-4aa3e158f27d'
        snap.id = constants.SNAPSHOT_ID
        with self.assertRaisesRegex(exception.NotFound,
                                    'Logical Disk `LX:18FkaTGqa43xSFL8aX4A2N` '
                                    'has unbound already.'):
            self.revert_to_snapshot(None, vol, snap)
        snap.id = '63410c76-2f12-4473-873d-74a63dfcd3e2'
        self.mock_object(self._cli, 'query_BV_SV_status',
                         return_value='rst/exec')
        with self.assertRaisesRegex(exception.VolumeBackendAPIException,
                                    'The snapshot does not exist or is '
                                    'not in snap/active status. '
                                    'bvname=LX:yEUHrXa5AHMjOZZLb93eP, '
                                    'svname=LX:31HxzqBiAFTUxxOlcVn3EA, '
                                    'status=rst/exec'):
            self.revert_to_snapshot(None, vol, snap)

        return_status = ['snap/active', 'rst/exec', 'snap/active']
        self.mock_object(self._cli, 'query_BV_SV_status',
                         side_effect=return_status)
        self.revert_to_snapshot(None, vol, snap)

        return_status = ['snap/active', 'rst/exec', 'snap/fault']
        self.mock_object(self._cli, 'query_BV_SV_status',
                         side_effect=return_status)
        with self.assertRaisesRegex(exception.VolumeBackendAPIException,
                                    'Failed to restore from snapshot. '
                                    'bvname=LX:yEUHrXa5AHMjOZZLb93eP, '
                                    'svname=LX:31HxzqBiAFTUxxOlcVn3EA, '
                                    'status=snap/fault'):
            self.revert_to_snapshot(None, vol, snap)


class SetQosSpec_test(volume_helper.MStorageDSVDriver,
                      test.TestCase):

    def setUp(self):
        super(SetQosSpec_test, self).setUp()
        self._set_config(conf.Configuration(None), 'dummy', 'dummy')
        self.mock_object(self._cli, '_execute',
                         return_value=('success', 0, 0))
        self.do_setup(None)

    def test_set_qos_spec(self):
        volume_type = {'name': u'Bronze',
                       'qos_specs_id': u'57223246-1d49-4565-860f-bbbee6cee122',
                       'deleted': False,
                       'created_at': '2019-01-08 08:48:20',
                       'updated_at': '2019-01-08 08:48:29',
                       'extra_specs': {}, 'is_public': True,
                       'deleted_at': None,
                       'id': u'33cd6136-0465-4ee0-82fa-b5f3a9138249',
                       'description': None}
        voltype_qos_specs = {'specs': {u'lowerlimit': u'500',
                                       u'upperlimit': u'2000',
                                       'upperreport': None}}
        self.mock_object(volume_types, 'get_volume_type',
                         return_value=volume_type)
        self.mock_object(qos_specs, 'get_qos_specs',
                         return_value=voltype_qos_specs)
        ldname = 'LX:287RbQoP7VdwR1WsPC2fZT'
        volume_type_id = '33cd6136-0465-4ee0-82fa-b5f3a9138249'
        ret = self._set_qos_spec(ldname, volume_type_id)
        self.assertIsNone(ret)

    def test_get_qos_parameters(self):
        specs = {}
        qos_params = self.get_qos_parameters(specs, True)
        self.assertEqual(0, qos_params['upperlimit'])
        self.assertEqual(0, qos_params['lowerlimit'])
        self.assertEqual('off', qos_params['upperreport'])

        specs = {}
        qos_params = self.get_qos_parameters(specs, False)
        self.assertIsNone(qos_params['upperlimit'])
        self.assertIsNone(qos_params['lowerlimit'])
        self.assertIsNone(qos_params['upperreport'])

        specs = {u'upperlimit': u'1000',
                 u'lowerlimit': u'500',
                 u'upperreport': u'off'}
        qos_params = self.get_qos_parameters(specs, False)
        self.assertEqual(1000, qos_params['upperlimit'])
        self.assertEqual(500, qos_params['lowerlimit'])
        self.assertEqual('off', qos_params['upperreport'])

        specs = {u'upperreport': u'on'}
        qos_params = self.get_qos_parameters(specs, False)
        self.assertIsNone(qos_params['upperlimit'])
        self.assertIsNone(qos_params['lowerlimit'])
        self.assertEqual('on', qos_params['upperreport'])

        specs = {u'upperreport': u'aaa'}
        qos_params = self.get_qos_parameters(specs, False)
        self.assertIsNone(qos_params['upperlimit'])
        self.assertIsNone(qos_params['lowerlimit'])
        self.assertIsNone(qos_params['upperreport'])

        specs = {u'upperlimit': u'1000001',
                 u'lowerlimit': u'500'}
        with self.assertRaisesRegex(exception.InvalidConfigurationValue,
                                    'Value "1000001" is not valid for '
                                    'configuration option "upperlimit"'):
            self.get_qos_parameters(specs, False)

        specs = {u'upperlimit': u'aaa',
                 u'lowerlimit': u'500'}
        with self.assertRaisesRegex(exception.InvalidConfigurationValue,
                                    'Value "aaa" is not valid for '
                                    'configuration option "upperlimit"'):
            self.get_qos_parameters(specs, False)

        specs = {u'upperlimit': u'1000',
                 u'lowerlimit': u'aaa'}
        with self.assertRaisesRegex(exception.InvalidConfigurationValue,
                                    'Value "aaa" is not valid for '
                                    'configuration option "lowerlimit"'):
            self.get_qos_parameters(specs, False)

        specs = {u'upperlimit': u'1000',
                 u'lowerlimit': u'1'}
        with self.assertRaisesRegex(exception.InvalidConfigurationValue,
                                    'Value "1" is not valid for '
                                    'configuration option "lowerlimit"'):
            self.get_qos_parameters(specs, False)
