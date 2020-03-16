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

import ddt
import mock

from cinder import exception
from cinder import test
from cinder.tests.unit import fake_constants as constants
from cinder.volume import configuration as conf
from cinder.volume.drivers.nec import cli
from cinder.volume.drivers.nec import volume_common
from cinder.volume.drivers.nec import volume_helper


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
        self.size = volsize
        self.status = None
        self.migration_status = None
        self.volume_id = None
        self.volume_type_id = None
        self.attach_status = None
        self.provider_location = None


@ddt.ddt
class VolumeIDConvertTest(volume_helper.MStorageDSVDriver, test.TestCase):

    def setUp(self):
        super(VolumeIDConvertTest, self).setUp()
        self.mock_object(self, '_create_ismview_dir')
        self._set_config(conf.Configuration(None), 'dummy', 'dummy')
        self.do_setup(None)
        self.vol = DummyVolume(constants.VOLUME_ID)

    @ddt.data(("AAAAAAAA", "LX:37mA82"), ("BBBBBBBB", "LX:3R9ZwR"))
    @ddt.unpack
    def test_volumeid_should_change_62scale(self, volid, ldname):
        self.vol.id = volid
        actual = self._convert_id2name(self.vol)
        self.assertEqual(ldname, actual,
                         "ID:%(volid)s should be change to %(ldname)s" %
                         {'volid': volid, 'ldname': ldname})

    @ddt.data(("AAAAAAAA", "LX:37mA82"), ("BBBBBBBB", "LX:3R9ZwR"))
    @ddt.unpack
    def test_snap_volumeid_should_change_62scale_andpostfix(self,
                                                            volid,
                                                            ldname):
        self.vol.id = volid
        actual = self._convert_id2snapname(self.vol)
        self.assertEqual(ldname, actual,
                         "ID:%(volid)s should be change to %(ldname)s" %
                         {'volid': volid, 'ldname': ldname})

    @ddt.data(("AAAAAAAA", "LX:37mA82_m"), ("BBBBBBBB", "LX:3R9ZwR_m"))
    @ddt.unpack
    def test_ddrsnap_volumeid_should_change_62scale_and_m(self,
                                                          volid,
                                                          ldname):
        self.vol.id = volid
        actual = self._convert_id2migratename(self.vol)
        self.assertEqual(ldname, actual,
                         "ID:%(volid)s should be change to %(ldname)s" %
                         {'volid': volid, 'ldname': ldname})


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
        self.vol = DummyVolume(constants.VOLUME_ID, 10)

    def test_getxml(self):
        self.assertIsNotNone(self.xml, "iSMview xml should not be None")

    def test_selectldn_for_normalvolume(self):
        ldn = self._select_ldnumber(self.used_ldns, self.max_ld_count)
        self.assertEqual(2, ldn, "selected ldn should be XXX")

    def test_selectpool_for_normalvolume(self):
        pool = self._select_leastused_poolnumber(self.vol,
                                                 self.pools,
                                                 self.xml)
        self.assertEqual(1, pool, "selected pool should be 1")
        # config:pool_pools=[1]
        self.vol.size = 999999999999
        with self.assertRaisesRegex(exception.VolumeBackendAPIException,
                                    'No available pools found.'):
            pool = self._select_leastused_poolnumber(self.vol,
                                                     self.pools,
                                                     self.xml)

    def test_return_poolnumber(self):
        self.assertEqual(1, self._return_poolnumber(self.test_pools))

    def test_selectpool_for_migratevolume(self):
        self.vol.id = "46045673-41e7-44a7-9333-02f07feab04b"
        dummyhost = {}
        dummyhost['capabilities'] = self._update_volume_status()
        pool = self._select_migrate_poolnumber(self.vol,
                                               self.pools,
                                               self.xml,
                                               dummyhost)
        self.assertEqual(1, pool, "selected pool should be 1")
        self.vol.id = "1febb976-86d0-42ed-9bc0-4aa3e158f27d"
        pool = self._select_migrate_poolnumber(self.vol,
                                               self.pools,
                                               self.xml,
                                               dummyhost)
        self.assertEqual(-1, pool, "selected pool is the same pool(return -1)")
        self.vol.size = 999999999999
        with self.assertRaisesRegex(exception.VolumeBackendAPIException,
                                    'No available pools found.'):
            pool = self._select_migrate_poolnumber(self.vol,
                                                   self.pools,
                                                   self.xml,
                                                   dummyhost)

    def test_selectpool_for_snapvolume(self):
        savePool1 = self.pools[1]['free']
        self.pools[1]['free'] = 0
        pool = self._select_dsv_poolnumber(self.vol, self.pools)
        self.assertEqual(2, pool, "selected pool should be 2")
        # config:pool_backup_pools=[2]
        self.pools[1]['free'] = savePool1

        if len(self.pools[0]['ld_list']) is 1024:
            savePool2 = self.pools[2]['free']
            savePool3 = self.pools[3]['free']
            self.pools[2]['free'] = 0
            self.pools[3]['free'] = 0
            with self.assertRaisesRegex(exception.VolumeBackendAPIException,
                                        'No available pools found.'):
                pool = self._select_dsv_poolnumber(self.vol, self.pools)
            self.pools[2]['free'] = savePool2
            self.pools[3]['free'] = savePool3

        self.vol.size = 999999999999
        pool = self._select_dsv_poolnumber(self.vol, self.pools)
        self.assertEqual(2, pool, "selected pool should be 2")
        # config:pool_backup_pools=[2]

    def test_selectpool_for_ddrvolume(self):
        pool = self._select_ddr_poolnumber(self.vol,
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
            pool = self._select_ddr_poolnumber(self.vol,
                                               self.pools,
                                               self.xml,
                                               10)
        self.pools[2]['free'] = savePool2
        self.pools[3]['free'] = savePool3

        self.vol.size = 999999999999
        with self.assertRaisesRegex(exception.VolumeBackendAPIException,
                                    'No available pools found.'):
            pool = self._select_ddr_poolnumber(self.vol,
                                               self.pools,
                                               self.xml,
                                               999999999999)

    def test_selectpool_for_volddrvolume(self):
        pool = self._select_volddr_poolnumber(self.vol,
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
            pool = self._select_volddr_poolnumber(self.vol,
                                                  self.pools,
                                                  self.xml,
                                                  10)
        self.pools[0]['free'] = savePool0
        self.pools[1]['free'] = savePool1

        self.vol.size = 999999999999
        with self.assertRaisesRegex(exception.VolumeBackendAPIException,
                                    'No available pools found.'):
            pool = self._select_volddr_poolnumber(self.vol,
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
        self.vol = DummyVolume("46045673-41e7-44a7-9333-02f07feab04b", 1)

    def test_validate_migrate_volume(self):
        self.vol.status = 'available'
        self._validate_migrate_volume(self.vol, self.xml)

        self.vol.status = 'creating'
        with self.assertRaisesRegex(exception.VolumeBackendAPIException,
                                    'Specified Logical Disk'
                                    ' LX:287RbQoP7VdwR1WsPC2fZT'
                                    ' is not available.'):
            self._validate_migrate_volume(self.vol, self.xml)

        self.vol.id = "AAAAAAAA"
        self.vol.status = 'available'
        with self.assertRaisesRegex(exception.NotFound,
                                    'Logical Disk `LX:37mA82`'
                                    ' could not be found.'):
            self._validate_migrate_volume(self.vol, self.xml)

    def test_extend_volume(self):
        self.vol.status = 'available'
        self.extend_volume(self.vol, 10)

        self.vol.id = "00046058-d38e-7f60-67b7-59ed65e54225"  # RV
        with self.assertRaisesRegex(exception.VolumeBackendAPIException,
                                    'RPL Attribute Error. '
                                    'RPL Attribute = RV.'):
            self.extend_volume(self.vol, 10)


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
        self.vol = DummyVolume(constants.VOLUME_ID, 1)

    def test_bindld_CreateVolume(self):
        self.vol.migration_status = "success"
        self.create_volume(self.vol)
        self._bind_ld.assert_called_once_with(
            self.vol, self.vol.size, None,
            self._convert_id2name,
            self._select_leastused_poolnumber)

    def test_bindld_CreateCloneVolume(self):
        self.vol.migration_status = "success"
        self.src = DummyVolume("46045673-41e7-44a7-9333-02f07feab04b", 1)
        self.mock_object(self._cli, 'query_BV_SV_status',
                         return_value='snap/active')
        self.mock_object(self._cli, 'query_MV_RV_name',
                         return_value='separated')
        self.mock_object(self._cli, 'backup_restore')
        self.create_cloned_volume(self.vol, self.src)
        self._bind_ld.assert_called_once_with(
            self.vol, self.vol.size, None,
            self._convert_id2name,
            self._select_leastused_poolnumber)
        self.mock_object(self._cli, 'get_pair_lds',
                         return_value={'lds1', 'lds2', 'lds3'})
        with self.assertRaisesRegex(exception.VolumeBackendAPIException,
                                    'Cannot create clone volume. '
                                    'number of pairs reached 3. '
                                    'ldname=LX:287RbQoP7VdwR1WsPC2fZT'):
            self.create_cloned_volume(self.vol, self.src)

    def test_bindld_CreateCloneWaitingInterval(self):
        self.assertEqual(10, cli.get_sleep_time_for_clone(0))
        self.assertEqual(12, cli.get_sleep_time_for_clone(2))
        self.assertEqual(60, cli.get_sleep_time_for_clone(19))

    def test_delete_volume(self):
        self.vol.id = "46045673-41e7-44a7-9333-02f07feab04b"
        detached = self._detach_from_all(self.vol)
        self.assertTrue(detached)
        self.vol.id = constants.VOLUME_ID
        detached = self._detach_from_all(self.vol)
        self.assertFalse(detached)
        self.vol.id = constants.VOLUME2_ID
        with mock.patch.object(self, '_detach_from_all') as detach_mock:
            self.delete_volume(self.vol)
            detach_mock.assert_called_once_with(self.vol)


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
        self.vol = DummyVolume(constants.VOLUME_ID)
        self.snap = DummyVolume(constants.SNAPSHOT_ID)

    def test_bindld_CreateSnapshot(self):
        self.snap.volume_id = constants.VOLUME_ID
        self.create_snapshot(self.snap)
        self._create_snapshot.assert_called_once_with(
            self.snap, self._properties['diskarray_name'])

    def test_bindld_CreateFromSnapshot(self):
        self.vol.migration_status = "success"
        self.snap.id = "63410c76-2f12-4473-873d-74a63dfcd3e2"
        self.snap.volume_id = "1febb976-86d0-42ed-9bc0-4aa3e158f27d"
        self.mock_object(self._cli, 'query_BV_SV_status',
                         return_value='snap/active')
        self.mock_object(self._cli, 'backup_restore')
        self.create_volume_from_snapshot(self.vol, self.snap)
        self._bind_ld.assert_called_once_with(
            self.vol, 1, None,
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
        self.vol = DummyVolume("46045673-41e7-44a7-9333-02f07feab04b", 10)

    def test_iscsi_portal(self):
        connector = {'initiator': "iqn.1994-05.com.redhat:d1d8e8f23255"}
        self.iscsi_do_export(None, self.vol, connector,
                             self._properties['diskarray_name'])

    def test_fc_do_export(self):
        connector = {'wwpns': ["10000090FAA0786A", "10000090FAA0786B"]}
        self.fc_do_export(None, self.vol, connector)

    def test_iscsi_initialize_connection(self):
        loc = "127.0.0.1:3260:1 iqn.2010-10.org.openstack:volume-00000001 88"
        self.vol.provider_location = loc
        connector = {'initiator': "iqn.1994-05.com.redhat:d1d8e8f23255",
                     'multipath': False}
        info = self._iscsi_initialize_connection(self.vol, connector)
        self.assertEqual('iscsi', info['driver_volume_type'])
        self.assertEqual('iqn.2010-10.org.openstack:volume-00000001',
                         info['data']['target_iqn'])
        self.assertEqual('127.0.0.1:3260', info['data']['target_portal'])
        self.assertEqual(88, info['data']['target_lun'])

    def test_iscsi_multipath_initialize_connection(self):
        self.vol.id = "46045673-41e7-44a7-9333-02f07feab04b"
        loc = ("1.1.1.1:3260;2.2.2.2:3260,1 "
               "iqn.2010-10.org.openstack:volume-00000001 88")
        self.vol.provider_location = loc
        connector = {'initiator': "iqn.1994-05.com.redhat:d1d8e8f23255",
                     'multipath': True}
        info = self._iscsi_initialize_connection(self.vol, connector)
        self.assertEqual('iscsi', info['driver_volume_type'])
        self.assertEqual('iqn.2010-10.org.openstack:volume-00000001',
                         info['data']['target_iqn'])
        self.assertEqual('1.1.1.1:3260', info['data']['target_portal'])
        self.assertEqual(88, info['data']['target_lun'])
        self.assertEqual('iqn.2010-10.org.openstack:volume-00000001',
                         info['data']['target_iqns'][0])
        self.assertEqual('iqn.2010-10.org.openstack:volume-00000001',
                         info['data']['target_iqns'][1])
        self.assertEqual('1.1.1.1:3260', info['data']['target_portals'][0])
        self.assertEqual('2.2.2.2:3260', info['data']['target_portals'][1])
        self.assertEqual(88, info['data']['target_luns'][0])
        self.assertEqual(88, info['data']['target_luns'][1])

    def test_iscsi_terminate_connection(self):
        connector = {'initiator': "iqn.1994-05.com.redhat:d1d8e8f23255",
                     'multipath': True}
        ret = self._iscsi_terminate_connection(self.vol, connector)
        self.assertIsNone(ret)

    def test_iscsi_terminate_connection_negative(self):
        connector = {'initiator': "iqn.1994-05.com.redhat:d1d8e8f23255",
                     'multipath': True}
        with self.assertRaisesRegex(exception.VolumeBackendAPIException,
                                    r'Failed to unregister Logical Disk from'
                                    r' Logical Disk Set \(iSM31064\)'):
            self.mock_object(self._cli, 'delldsetld',
                             return_value=(False, 'iSM31064'))
            self._iscsi_terminate_connection(self.vol, connector)

    def test_fc_initialize_connection(self):
        connector = {'wwpns': ["10000090FAA0786A", "10000090FAA0786B"]}
        info = self._fc_initialize_connection(self.vol, connector)
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
            self._fc_terminate_connection(self.vol, connector)

    def test_fc_terminate_connection(self):
        connector = {'wwpns': ["10000090FAA0786A", "10000090FAA0786B"]}
        info = self._fc_terminate_connection(self.vol, connector)
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
        info = self._fc_terminate_connection(self.vol, None)
        self.assertEqual('fibre_channel', info['driver_volume_type'])
        self.assertEqual({}, info['data'])

    def test_iscsi_portal_with_controller_node_name(self):
        self.vol.status = 'downloading'
        connector = {'initiator': "iqn.1994-05.com.redhat:d1d8e8f23255"}
        self._properties['ldset_controller_node_name'] = 'LX:OpenStack1'
        self._properties['portal_number'] = 2
        location = self.iscsi_do_export(None, self.vol, connector,
                                        self._properties['diskarray_name'])
        self.assertEqual('192.168.1.90:3260;192.168.1.91:3260;'
                         '192.168.2.92:3260;192.168.2.93:3260'
                         ',1 iqn.2001-03.target0000 0',
                         location['provider_location'])

    def test_fc_do_export_with_controller_node_name(self):
        self.vol.status = 'downloading'
        connector = {'wwpns': ["10000090FAA0786A", "10000090FAA0786B"]}
        self._properties['ldset_controller_node_name'] = 'LX:OpenStack0'
        location = self.fc_do_export(None, self.vol, connector)
        self.assertIsNone(location)


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
        self.vol = DummyVolume(constants.SNAPSHOT_ID)
        self.vol.volume_id = constants.VOLUME_ID

    def test_delete_snapshot(self):
        self.mock_object(self._cli, 'query_BV_SV_status',
                         return_value='snap/active')
        ret = self.delete_snapshot(self.vol)
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
        self.do_setup(None)
        self.vol = DummyVolume('46045673-41e7-44a7-9333-02f07feab04b')
        self.xml = xml_out
        (self.pools,
         self.lds,
         self.ldsets,
         self.used_ldns,
         self.hostports,
         self.max_ld_count) = self.configs(self.xml)

    def test_validate_ld_exist(self):
        ldname = self._validate_ld_exist(
            self.lds, self.vol.id, self._properties['ld_name_format'])
        self.assertEqual('LX:287RbQoP7VdwR1WsPC2fZT', ldname)
        self.vol.id = "00000000-0000-0000-0000-6b6d96553b4b"
        with self.assertRaisesRegex(exception.NotFound,
                                    'Logical Disk `LX:XXXXXXXX`'
                                    ' could not be found.'):
            self._validate_ld_exist(
                self.lds, self.vol.id, self._properties['ld_name_format'])

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
        self._properties['portal_number'] = 2
        portal = self._enumerate_iscsi_portals(self.hostports, ldset)
        self.assertEqual('192.168.1.90:3260', portal[0])
        self.assertEqual('192.168.1.91:3260', portal[1])
        self.assertEqual('192.168.2.92:3260', portal[2])
        self.assertEqual('192.168.2.93:3260', portal[3])

    def test_initialize_connection_snapshot(self):
        connector = {'initiator': "iqn.1994-05.com.redhat:d1d8e8f23255"}
        loc = "127.0.0.1:3260:1 iqn.2010-10.org.openstack:volume-00000001 88"
        self.vol.provider_location = loc
        ret = self.iscsi_initialize_connection_snapshot(self.vol, connector)
        self.assertIsNotNone(ret)
        self.assertEqual('iscsi', ret['driver_volume_type'])

        connector = {'wwpns': ["10000090FAA0786A", "10000090FAA0786B"]}
        ret = self.fc_initialize_connection_snapshot(self.vol, connector)
        self.assertIsNotNone(ret)
        self.assertEqual('fibre_channel', ret['driver_volume_type'])

    def test_terminate_connection_snapshot(self):
        connector = {'initiator': "iqn.1994-05.com.redhat:d1d8e8f23255"}
        self.iscsi_terminate_connection_snapshot(self.vol, connector)

        connector = {'wwpns': ["10000090FAA0786A", "10000090FAA0786B"]}
        ret = self.fc_terminate_connection_snapshot(self.vol, connector)
        self.assertEqual('fibre_channel', ret['driver_volume_type'])

    def test_remove_export_snapshot(self):
        self.remove_export_snapshot(None, self.vol)

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
        self.do_setup(None)
        self.newvol = DummyVolume(constants.VOLUME_ID)
        self.sourcevol = DummyVolume(constants.VOLUME2_ID)

    def test_update_migrate_volume(self):
        update_data = self.update_migrated_volume(None, self.sourcevol,
                                                  self.newvol, 'available')
        self.assertIsNone(update_data['_name_id'])
        self.assertIsNone(update_data['provider_location'])


class ManageUnmanage_test(volume_helper.MStorageDSVDriver, test.TestCase):

    def setUp(self):
        super(ManageUnmanage_test, self).setUp()
        self.mock_object(self, '_create_ismview_dir')
        self._set_config(conf.Configuration(None), 'dummy', 'dummy')
        self.mock_object(self._cli, 'view_all', return_value=xml_out)
        self.do_setup(None)
        self._properties['pool_pools'] = {0}
        self._properties['pool_backup_pools'] = {1}
        self.newvol = DummyVolume(constants.VOLUME_ID)

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
        self.manage_existing(self.newvol, volumes[4]['reference'])
        self._cli.changeldname.assert_called_once_with(
            None, 'LX:vD03hJCiHvGpvP4iSevKk', '  :20000009910200140009')
        with self.assertRaisesRegex(exception.ManageExistingInvalidReference,
                                    'Specified resource is already in-use.'):
            self.manage_existing(self.newvol, volumes[3]['reference'])
        volume = {'source-name': 'LX:yEUHrXa5AHMjOZZLb93eP'}
        with self.assertRaisesRegex(exception.ManageExistingVolumeTypeMismatch,
                                    'Volume type is unmatched.'):
            self.manage_existing(self.newvol, volume)

    def test_manage_existing_get_size(self):
        current_volumes = []
        volumes = self.get_manageable_volumes(current_volumes, None,
                                              100, 0, ['reference'], ['dec'])
        size_in_gb = self.manage_existing_get_size(self.newvol,
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
        self.newsnap = DummyVolume('46045673-41e7-44a7-9333-02f07feab04b')
        self.newsnap.volume_id = "1febb976-86d0-42ed-9bc0-4aa3e158f27d"

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
        self.manage_existing_snapshot(self.newsnap, snaps[0]['reference'])
        self._cli.changeldname.assert_called_once_with(
            None,
            'LX:287RbQoP7VdwR1WsPC2fZT',
            'LX:4T7JpyqI3UuPlKeT9D3VQF')

        self.newsnap.volume_id = "AAAAAAAA"
        with self.assertRaisesRegex(exception.ManageExistingInvalidReference,
                                    'Snapshot source is unmatch.'):
            self.manage_existing_snapshot(self.newsnap, snaps[0]['reference'])

        self._cli.get_bvname.return_value = "2000000991020012000C"
        self.newsnap.volume_id = "00046058-d38e-7f60-67b7-59ed6422520c"
        snap = {'source-name': '  :2000000991020012000B'}
        with self.assertRaisesRegex(exception.ManageExistingVolumeTypeMismatch,
                                    'Volume type is unmatched.'):
            self.manage_existing_snapshot(self.newsnap, snap)

    def test_manage_existing_snapshot_get_size(self):
        self.mock_object(self._cli, 'get_bvname',
                         return_value='yEUHrXa5AHMjOZZLb93eP')
        current_snapshots = []
        snaps = self.get_manageable_snapshots(current_snapshots, None,
                                              100, 0, ['reference'], ['asc'])
        size_in_gb = self.manage_existing_snapshot_get_size(
            self.newsnap,
            snaps[0]['reference'])
        self.assertEqual(6, size_in_gb)
