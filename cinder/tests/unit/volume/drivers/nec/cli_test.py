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


class MStorageISMCLI(object):
    def __init__(self, properties):
        super(MStorageISMCLI, self).__init__()

        self._properties = properties

    def view_all(self, conf_ismview_path=None, delete_ismview=True,
                 cmd_lock=True):
        out = '''<REQUEST>
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
     <UNIT name="LD Name">31HxzqBiAFTUxxOlcVn3EA_back</UNIT>
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
     <UNIT name="OS Type">  </UNIT>
     <UNIT name="LD Name">20000009910200140006</UNIT>
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
     <UNIT name="Purpose">RPL</UNIT>
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
   </OBJECT>
   <OBJECT name="LD Set(FC)">
    <SECTION name="LD Set(FC) Information">
     <UNIT name="Platform">WN</UNIT>
     <UNIT name="LD Set Name">TNES120250</UNIT>
    </SECTION>
    <SECTION name="Path List">
     <UNIT name="Path">1000-0090-FA76-9605</UNIT>
    </SECTION>
    <SECTION name="Path List">
     <UNIT name="Path">1000-0090-FA76-9604</UNIT>
    </SECTION>
   </OBJECT>
   <OBJECT name="LD Set(FC)">
    <SECTION name="LD Set(FC) Information">
     <UNIT name="Platform">WN</UNIT>
     <UNIT name="LD Set Name">TNES140098</UNIT>
    </SECTION>
    <SECTION name="Path List">
     <UNIT name="Path">1000-0090-FA53-302C</UNIT>
    </SECTION>
    <SECTION name="Path List">
     <UNIT name="Path">1000-0090-FA53-302D</UNIT>
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
        return out

    def ldbind(self, name, pool, ldn, size):
        return True, 0

    def unbind(self, name):
        pass

    def expand(self, ldn, capacity):
        pass

    def addldsetld(self, ldset, ldname, lun=None):
        pass

    def delldsetld(self, ldset, ldname):
        if ldname == "LX:287RbQoP7VdwR1WsPC2fZT":
            return False, 'iSM31064'
        else:
            return True, None

    def changeldname(self, ldn, new_name, old_name=None):
        pass

    def setpair(self, mvname, rvname):
        pass

    def unpair(self, mvname, rvname, flag):
        pass

    def replicate(self, mvname, rvname, flag):
        pass

    def separate(self, mvname, rvname, flag):
        pass

    def query_MV_RV_status(self, ldname, rpltype):
        return 'separated'

    def query_MV_RV_name(self, ldname, rpltype):
        pass

    def query_MV_RV_diff(self, ldname, rpltype):
        pass

    def backup_restore(self, volume_properties, unpairWait, canPairing=True):
        pass

    def check_ld_existed_rplstatus(self, lds, ldname, snapshot, flag):
        return {'ld_capacity': 10}

    def get_pair_lds(self, ldname, lds):
        return {'0004': {'ld_capacity': 1, 'pool_num': 0,
                         'ldname': 'LX:287RbQoP7VdwR1WsPC2fZT_back',
                         'ldn': 4, 'RPL Attribute': 'RV', 'Purpose': '---'}}

    def snapshot_create(self, bvname, svname, poolnumber):
        pass

    def snapshot_delete(self, bvname, svname):
        pass

    def query_BV_SV_status(self, bvname, svname):
        return 'snap/active'

    def set_io_limit(self, ldname, specs, force_delete=True):
        pass
