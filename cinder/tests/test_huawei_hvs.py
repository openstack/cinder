
# Copyright (c) 2013 Huawei Technologies Co., Ltd.
# Copyright (c) 2013 OpenStack Foundation
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
Unit Tests for Huawei HVS volume drivers.
"""

import json
import mox
import os
import shutil
import tempfile
import time

from xml.dom.minidom import Document

from cinder import exception
from cinder import test
from cinder import utils
from cinder.volume import configuration as conf
from cinder.volume.drivers.huawei import huawei_hvs
from cinder.volume.drivers.huawei import rest_common


test_volume = {'name': 'volume-21ec7341-9256-497b-97d9-ef48edcf0635',
               'size': 2,
               'volume_name': 'vol1',
               'id': '21ec7341-9256-497b-97d9-ef48edcf0635',
               'volume_id': '21ec7341-9256-497b-97d9-ef48edcf0635',
               'provider_auth': None,
               'project_id': 'project',
               'display_name': 'vol1',
               'display_description': 'test volume',
               'volume_type_id': None}

test_snap = {'name': 'volume-21ec7341-9256-497b-97d9-ef48edcf0635',
             'size': 1,
             'volume_name': 'vol1',
             'id': '21ec7341-9256-497b-97d9-ef48edcf0635',
             'volume_id': '21ec7341-9256-497b-97d9-ef48edcf0635',
             'provider_auth': None,
             'project_id': 'project',
             'display_name': 'vol1',
             'display_description': 'test volume',
             'volume_type_id': None}

FakeConnector = {'initiator': 'iqn.1993-08.debian:01:ec2bff7ac3a3',
                 'wwpns': ['10000090fa0d6754'],
                 'wwnns': ['10000090fa0d6755'],
                 'host': 'fakehost',
                 'ip': '10.10.0.1'}

volume_size = 3


def Fake_sleep(time):
    pass


class FakeHVSCommon(rest_common.HVSCommon):

    def __init__(self, configuration):
        rest_common.HVSCommon.__init__(self, configuration)
        self.test_normal = True
        self.other_flag = True
        self.deviceid = None
        self.lun_id = None
        self.snapshot_id = None
        self.luncopy_id = None
        self.termin_flag = False

    def _parse_volume_type(self, volume):
        self._get_lun_conf_params()
        poolinfo = self._find_pool_info()
        volume_size = self._get_volume_size(poolinfo, volume)

        params = {'LUNType': 0,
                  'WriteType': '1',
                  'PrefetchType': '3',
                  'qos_level': 'Qos-high',
                  'StripUnitSize': '64',
                  'PrefetchValue': '0',
                  'PrefetchTimes': '0',
                  'qos': 'OpenStack_Qos_High',
                  'MirrorSwitch': '1',
                  'tier': 'Tier_high'}

        params['volume_size'] = volume_size
        params['pool_id'] = poolinfo['ID']
        return params

    def _change_file_mode(self, filepath):
        utils.execute('chmod', '777', filepath)

    def call(self, url=False, data=None, method=None):

        url = url.replace('http://100.115.10.69:8082/deviceManager/rest', '')
        url = url.replace('/210235G7J20000000000/', '')
        data = None

        if self.test_normal:
            if url == "/xx/sessions":
                    data = """{"error":{"code":0},
                                "data":{"username":"admin",
                                        "deviceid":"210235G7J20000000000"
                                       }}"""
            if url == "sessions":
                    data = """{"error":{"code":0},
                                "data":{"ID":11}}"""

            if url == "storagepool":
                data = """{"error":{"code":0},
                            "data":[{"ID":"0",
                                    "NAME":"OpenStack_Pool",
                                    "USERFREECAPACITY":"985661440",
                                    "USERTOTALCAPACITY":"985661440"
                                   }]}"""

            if url == "lun":
                if method is None:
                    data = """{"error":{"code":0},
                                "data":{"ID":"1",
                                       "NAME":"5mFHcBv4RkCcD+JyrWc0SA"}}"""
                    self.lun_id = "0"

                if method == 'GET':
                    data = """{"error":{"code":0},
                               "data":[{"ID":"1",
                                        "NAME":"IexzQZJWSXuX2e9I7c8GNQ"}]}"""

            if url == "lungroup":
                if method is None:
                    data = """{"error":{"code":0},
                               "data":{"NAME":"5mFHcBv4RkCcD+JyrWc0SA",
                                       "DESCRIPTION":"5mFHcBv4RkCcD",
                                       "ID":"11",
                                       "TYPE":256}}"""

                if method == "GET":
                    data = """{"error":{"code":0},
                               "data":[{"NAME":"IexzQZJWSXuX2e9I7c8GNQ",
                                        "DESCRIPTION":"5mFHcBv4RkCcD",
                                        "ID":"11",
                                        "TYPE":256}]}"""

                if method == "DELETE":
                    data = """{"error":{"code":0},
                               "data":[{"NAME":"IexzQZJWSXuX2e9I7c8GNQ",
                                       "DESCRIPTION":"5mFHcBv4RkCcD+JyrWc0SA",
                                       "ID":"11",
                                       "TYPE":256}]}"""

            if url == "lungroup/associate":
                data = """{"error":{"code":0},
                           "data":{"NAME":"5mFHcBv4RkCcD+JyrWc0SA",
                                   "DESCRIPTION":"5mFHcBv4RkCcD+JyrWc0SA",
                                   "ID":"11",
                                   "TYPE":256}}"""

            if url == "snapshot":
                if method is None:
                    data = """{"error":{"code":0},
                               "data":{"ID":11}}"""
                    self.snapshot_id = "3"

                if method == "GET":
                    data = """{"error":{"code":0},
                               "data":[{"ID":11,"NAME":"SDFAJSDFLKJ"},
                                       {"ID":12,"NAME":"SDFAJSDFLKJ"}]}"""

            if url == "snapshot/activate":
                data = """{"error":{"code":0}}"""

            if url == ("lungroup/associate?ID=11"
                       "&ASSOCIATEOBJTYPE=11&ASSOCIATEOBJID=1"):
                data = """{"error":{"code":0}}"""

            if url == "LUNGroup/11":
                data = """{"error":{"code":0}}"""

            if url == 'lun/1':
                data = """{"error":{"code":0}}"""
                self.lun_id = None

            if url == 'snapshot':
                if method == "GET":
                    data = """{"error":{"code":0},
                               "data":[{"PARENTTYPE":11,
                                        "NAME":"IexzQZJWSXuX2e9I7c8GNQ",
                                        "WWN":"60022a11000a2a3907ce96cb00000b",
                                        "ID":"11",
                                        "CONSUMEDCAPACITY":"0"}]}"""

            if url == "snapshot/stop":
                data = """{"error":{"code":0}}"""

            if url == "snapshot/11":
                data = """{"error":{"code":0}}"""
                self.snapshot_id = None

            if url == "luncopy":
                data = """{"error":{"code":0},
                           "data":{"COPYSTOPTIME":"-1",
                                   "HEALTHSTATUS":"1",
                                   "NAME":"w1PSNvu6RumcZMmSh4/l+Q==",
                                   "RUNNINGSTATUS":"36",
                                   "DESCRIPTION":"w1PSNvu6RumcZMmSh4/l+Q==",
                                   "ID":"0","LUNCOPYTYPE":"1",
                                   "COPYPROGRESS":"0","COPYSPEED":"2",
                                   "TYPE":219,"COPYSTARTTIME":"-1"}}"""
                self.luncopy_id = "7"

            if url == "LUNCOPY/start":
                data = """{"error":{"code":0}}"""

            if url == "LUNCOPY?range=[0-100000]":
                data = """{"error":{"code":0},
                           "data":[{"COPYSTOPTIME":"1372209335",
                                    "HEALTHSTATUS":"1",
                                    "NAME":"w1PSNvu6RumcZMmSh4/l+Q==",
                                    "RUNNINGSTATUS":"40",
                                    "DESCRIPTION":"w1PSNvu6RumcZMmSh4/l+Q==",
                                    "ID":"0","LUNCOPYTYPE":"1",
                                    "COPYPROGRESS":"100",
                                    "COPYSPEED":"2",
                                    "TYPE":219,
                                    "COPYSTARTTIME":"1372209329"}]}"""

            if url == "LUNCOPY/0":
                data = '{"error":{"code":0}}'

            if url == "eth_port":
                data = """{"error":{"code":0},
                           "data":[{"PARENTTYPE":209,
                                    "MACADDRESS":"00:22:a1:0a:79:57",
                                    "ETHNEGOTIATE":"-1","ERRORPACKETS":"0",
                                    "IPV4ADDR":"100.115.10.68",
                                    "IPV6GATEWAY":"","IPV6MASK":"0",
                                    "OVERFLOWEDPACKETS":"0","ISCSINAME":"P0",
                                    "HEALTHSTATUS":"1","ETHDUPLEX":"2",
                                    "ID":"16909568","LOSTPACKETS":"0",
                                    "TYPE":213,"NAME":"P0","INIORTGT":"4",
                                    "RUNNINGSTATUS":"10","IPV4GATEWAY":"",
                                    "BONDNAME":"","STARTTIME":"1371684218",
                                    "SPEED":"1000","ISCSITCPPORT":"0",
                                    "IPV4MASK":"255.255.0.0","IPV6ADDR":"",
                                    "LOGICTYPE":"0","LOCATION":"ENG0.B5.P0",
                                    "MTU":"1500","PARENTID":"1.5"}]}"""

            if url == "iscsidevicename":
                data = """{"error":{"code":0},
"data":[{"CMO_ISCSI_DEVICE_NAME":
"iqn.2006-08.com.huawei:oceanstor:21000022a10a2a39:iscsinametest"}]}"""

            if url == "hostgroup":
                if method is None:
                    data = """{"error":{"code":0},
                               "data":{"NAME":"ubuntuc",
                                       "DESCRIPTION":"",
                                       "ID":"0",
                                       "TYPE":14}}"""

                if method == "GET":
                    data = """{"error":{"code":0},
                               "data":[{"NAME":"ubuntuc",
                                        "DESCRIPTION":"",
                                        "ID":"0",
                                        "TYPE":14}]}"""

            if url == "host":
                if method is None:
                    data = """{"error":{"code":0},
                               "data":{"PARENTTYPE":245,
                                       "NAME":"Default Host",
                                       "DESCRIPTION":"",
                                       "RUNNINGSTATUS":"1",
                                       "IP":"","PARENTNAME":"0",
                                       "OPERATIONSYSTEM":"1","LOCATION":"",
                                       "HEALTHSTATUS":"1","MODEL":"",
                                       "ID":"0","PARENTID":"0",
                                       "NETWORKNAME":"","TYPE":21}} """

                if method == "GET":
                    data = """{"error":{"code":0},
                               "data":[{"PARENTTYPE":245,
                                        "NAME":"ubuntuc",
                                        "DESCRIPTION":"",
                                        "RUNNINGSTATUS":"1",
                                        "IP":"","PARENTNAME":"",
                                        "OPERATIONSYSTEM":"0",
                                        "LOCATION":"",
                                        "HEALTHSTATUS":"1",
                                        "MODEL":"",
                                        "ID":"1","PARENTID":"",
                                        "NETWORKNAME":"","TYPE":21},
                                        {"PARENTTYPE":245,
                                        "NAME":"ubuntu",
                                        "DESCRIPTION":"",
                                        "RUNNINGSTATUS":"1",
                                        "IP":"","PARENTNAME":"",
                                        "OPERATIONSYSTEM":"0",
                                        "LOCATION":"",
                                        "HEALTHSTATUS":"1",
                                        "MODEL":"","ID":"2",
                                        "PARENTID":"",
                                        "NETWORKNAME":"","TYPE":21}]} """

            if url == "host/associate":
                if method is None:
                    data = """{"error":{"code":0}}"""
                if method == "GET":
                    data = """{"error":{"code":0}}"""

            if url == "iscsi_initiator/iqn.1993-08.debian:01:ec2bff7ac3a3":
                data = """{"error":{"code":0},
                           "data":{"ID":"iqn.1993-08.win:01:ec2bff7ac3a3",
                                   "NAME":"iqn.1993-08.win:01:ec2bff7ac3a3",
                                   "ISFREE":"True"}}"""

            if url == "iscsi_initiator/":
                data = """{"error":{"code":0}}"""

            if url == "iscsi_initiator":
                data = """{"error":{"code":0}}"""

            if url == "mappingview":
                self.termin_flag = True
                if method is None:
                    data = """{"error":{"code":0},
                               "data":{"WORKMODE":"255",
                                       "HEALTHSTATUS":"1",
                                       "NAME":"mOWtSXnaQKi3hpB3tdFRIQ",
                                       "RUNNINGSTATUS":"27","DESCRIPTION":"",
                                       "ENABLEINBANDCOMMAND":"true",
                                       "ID":"1","INBANDLUNWWN":"",
                                       "TYPE":245}}"""

                if method == "GET":
                    if self.other_flag:
                        data = """{"error":{"code":0},
                                   "data":[{"WORKMODE":"255",
                                            "HEALTHSTATUS":"1",
                                            "NAME":"mOWtSXnaQKi3hpB3tdFRIQ",
                                            "RUNNINGSTATUS":"27",
                                            "DESCRIPTION":"",
                                            "ENABLEINBANDCOMMAND":
                                            "true","ID":"1",
                                            "INBANDLUNWWN":"",
                                            "TYPE":245},
                                            {"WORKMODE":"255",
                                            "HEALTHSTATUS":"1",
                                            "NAME":"YheUoRwbSX2BxN767nvLSw",
                                            "RUNNINGSTATUS":"27",
                                            "DESCRIPTION":"",
                                            "ENABLEINBANDCOMMAND":"true",
                                            "ID":"2",
                                            "INBANDLUNWWN":"",
                                            "TYPE":245}]}"""
                    else:
                        data = """{"error":{"code":0},
                                   "data":[{"WORKMODE":"255",
                                            "HEALTHSTATUS":"1",
                                            "NAME":"IexzQZJWSXuX2e9I7c8GNQ",
                                            "RUNNINGSTATUS":"27",
                                            "DESCRIPTION":"",
                                            "ENABLEINBANDCOMMAND":"true",
                                            "ID":"1",
                                            "INBANDLUNWWN":"",
                                            "TYPE":245},
                                           {"WORKMODE":"255",
                                            "HEALTHSTATUS":"1",
                                            "NAME":"YheUoRwbSX2BxN767nvLSw",
                                            "RUNNINGSTATUS":"27",
                                            "DESCRIPTION":"",
                                            "ENABLEINBANDCOMMAND":"true",
                                            "ID":"2",
                                            "INBANDLUNWWN":"",
                                            "TYPE":245}]}"""

            if url == "MAPPINGVIEW/CREATE_ASSOCIATE":
                data = """{"error":{"code":0}}"""

            if url == ("lun/associate?TYPE=11&"
                       "ASSOCIATEOBJTYPE=21&ASSOCIATEOBJID=0"):
                data = """{"error":{"code":0}}"""

            if url == "fc_initiator?ISFREE=true&range=[0-1000]":
                data = """{"error":{"code":0},
                           "data":[{"HEALTHSTATUS":"1",
                                    "NAME":"",
                                    "MULTIPATHTYPE":"1",
                                    "ISFREE":"true",
                                    "RUNNINGSTATUS":"27",
                                    "ID":"10000090fa0d6754",
                                    "OPERATIONSYSTEM":"255",
                                    "TYPE":223},
                                   {"HEALTHSTATUS":"1",
                                    "NAME":"",
                                    "MULTIPATHTYPE":"1",
                                    "ISFREE":"true",
                                    "RUNNINGSTATUS":"27",
                                    "ID":"10000090fa0d6755",
                                    "OPERATIONSYSTEM":"255",
                                    "TYPE":223}]}"""

            if url == "host_link?INITIATOR_TYPE=223&INITIATOR_PORT_WWN="\
                      "10000090fa0d6754":

                data = """{"error":{"code":0},
                           "data":[{"PARENTTYPE":21,
                                    "TARGET_ID":"0000000000000000",
                                    "INITIATOR_NODE_WWN":"20000090fa0d6754",
                                    "INITIATOR_TYPE":"223",
                                    "RUNNINGSTATUS":"27",
                                    "PARENTNAME":"ubuntuc",
                                    "INITIATOR_ID":"10000090fa0d6754",
                                    "TARGET_PORT_WWN":"24000022a10a2a39",
                                    "HEALTHSTATUS":"1",
                                    "INITIATOR_PORT_WWN":"10000090fa0d6754",
                                    "ID":"010000090fa0d675-0000000000110400",
                                    "TARGET_NODE_WWN":"21000022a10a2a39",
                                    "PARENTID":"1","CTRL_ID":"0",
                                    "TYPE":255,"TARGET_TYPE":"212"}]}"""

            if url == ("mappingview/associate?TYPE=245&"
                       "ASSOCIATEOBJTYPE=14&ASSOCIATEOBJID=0"):

                data = """{"error":{"code":0},
                            "data":[{"ID":11,"NAME":"test"}]}"""

            if url == ("mappingview/associate?TYPE=245&"
                       "ASSOCIATEOBJTYPE=256&ASSOCIATEOBJID=11"):

                data = """{"error":{"code":0},
                            "data":[{"ID":11,"NAME":"test"}]}"""

            if url == "fc_initiator/10000090fa0d6754":
                data = """{"error":{"code":0}}"""

            if url == "mappingview/REMOVE_ASSOCIATE":
                data = """{"error":{"code":0}}"""
                self.termin_flag = True

            if url == "mappingview/1":
                data = """{"error":{"code":0}}"""

            if url == "ioclass":
                data = """{"error":{"code":0},
                           "data":[{"NAME":"OpenStack_Qos_High",
                                    "ID":"0",
                                    "LUNLIST":"[]",
                                    "TYPE":230}]}"""

            if url == "ioclass/0":
                data = """{"error":{"code":0}}"""

            if url == "lun/expand":
                data = """{"error":{"code":0}}"""
                self.lun_id = '0'

        else:
            data = """{"error":{"code":31755596}}"""

        res_json = json.loads(data)
        return res_json


class FakeHVSiSCSIStorage(huawei_hvs.HuaweiHVSISCSIDriver):

    def __init__(self, configuration):
        super(FakeHVSiSCSIStorage, self).__init__(configuration)
        self.configuration = configuration

    def do_setup(self, context):
        self.common = FakeHVSCommon(configuration=self.configuration)


class FakeHVSFCStorage(huawei_hvs.HuaweiHVSFCDriver):

    def __init__(self, configuration):
        super(FakeHVSFCStorage, self).__init__(configuration)
        self.configuration = configuration

    def do_setup(self, context):
        self.common = FakeHVSCommon(configuration=self.configuration)


class HVSRESTiSCSIDriverTestCase(test.TestCase):
    def setUp(self):
        super(HVSRESTiSCSIDriverTestCase, self).setUp()
        self.tmp_dir = tempfile.mkdtemp()
        self.fake_conf_file = self.tmp_dir + '/cinder_huawei_conf.xml'
        self.create_fake_conf_file()
        self.configuration = mox.MockObject(conf.Configuration)
        self.configuration.cinder_huawei_conf_file = self.fake_conf_file
        self.configuration.append_config_values(mox.IgnoreArg())

        self.stubs.Set(time, 'sleep', Fake_sleep)

        self.driver = FakeHVSiSCSIStorage(configuration=self.configuration)
        self.driver.do_setup({})
        self.driver.common.test_normal = True

    def tearDown(self):
        if os.path.exists(self.fake_conf_file):
            os.remove(self.fake_conf_file)
        shutil.rmtree(self.tmp_dir)
        super(HVSRESTiSCSIDriverTestCase, self).tearDown()

    def test_log_in_success(self):
        deviceid = self.driver.common.login()
        self.assertIsNotNone(deviceid)

    def test_log_out_success(self):
        self.driver.common.login()
        self.driver.common.login_out()

    def test_create_volume_success(self):
        self.driver.common.login()
        self.driver.create_volume(test_volume)
        self.assertEqual(self.driver.common.lun_id, "0")

    def test_extend_volume_success(self):
        self.driver.common.login()
        self.driver.extend_volume(test_volume, volume_size)
        self.assertEqual(self.driver.common.lun_id, "0")

    def test_create_snapshot_success(self):
        self.driver.common.login()
        self.driver.create_snapshot(test_volume)
        self.assertEqual(self.driver.common.snapshot_id, "3")

    def test_delete_volume_success(self):
        self.driver.common.login()
        self.driver.delete_volume(test_volume)
        self.assertIsNone(self.driver.common.lun_id)

    def test_delete_snapshot_success(self):
        self.driver.common.login()
        self.driver.delete_snapshot(test_snap)
        self.assertIsNone(self.driver.common.snapshot_id)

    def test_colone_volume_success(self):
        self.driver.common.login()
        self.driver.create_cloned_volume(test_volume, test_volume)
        self.assertEqual(self.driver.common.luncopy_id, "7")

    def test_create_volume_from_snapshot_success(self):
        self.driver.common.login()
        self.driver.create_volume_from_snapshot(test_volume, test_volume)
        self.assertEqual(self.driver.common.luncopy_id, "7")

    def test_initialize_connection_success(self):
        self.driver.common.login()
        conn = self.driver.initialize_connection(test_volume, FakeConnector)
        self.assertEqual(conn['data']['target_lun'], 1)

    def test_terminate_connection_success(self):
        self.driver.common.login()
        self.driver.terminate_connection(test_volume, FakeConnector)
        self.assertEqual(self.driver.common.termin_flag, True)

    def test_initialize_connection_no_view_success(self):
        self.driver.common.login()
        self.driver.common.other_flag = False
        conn = self.driver.initialize_connection(test_volume, FakeConnector)
        self.assertEqual(conn['data']['target_lun'], 1)

    def test_terminate_connectio_no_view_success(self):
        self.driver.common.login()
        self.driver.common.other_flag = False
        self.driver.terminate_connection(test_volume, FakeConnector)
        self.assertEqual(self.driver.common.termin_flag, True)

    def test_get_volume_stats(self):
        self.driver.common.login()
        status = self.driver.get_volume_stats()
        self.assertIsNotNone(status['free_capacity_gb'])

    def test_create_snapshot_fail(self):
        self.driver.common.login()
        self.driver.common.test_normal = False
        self.assertRaises(exception.CinderException,
                          self.driver.create_snapshot, test_volume)

    def test_create_volume_fail(self):
        self.driver.common.login()
        self.driver.common.test_normal = False
        self.assertRaises(exception.CinderException,
                          self.driver.create_volume, test_volume)

    def test_delete_volume_fail(self):
        self.driver.common.login()
        self.driver.common.test_normal = False
        self.assertRaises(exception.CinderException,
                          self.driver.delete_volume, test_volume)

    def test_delete_snapshot_fail(self):
        self.driver.common.login()
        self.driver.common.test_normal = False
        self.assertRaises(exception.CinderException,
                          self.driver.delete_snapshot, test_volume)

    def test_initialize_connection_fail(self):
        self.driver.common.login()
        self.driver.common.test_normal = False
        self.assertRaises(exception.CinderException,
                          self.driver.initialize_connection,
                          test_volume, FakeConnector)

    def create_fake_conf_file(self):
        doc = Document()

        config = doc.createElement('config')
        doc.appendChild(config)

        storage = doc.createElement('Storage')
        config.appendChild(storage)

        product = doc.createElement('Product')
        product_text = doc.createTextNode('HVS')
        product.appendChild(product_text)
        storage.appendChild(product)

        protocol = doc.createElement('Protocol')
        protocol_text = doc.createTextNode('iSCSI')
        protocol.appendChild(protocol_text)
        storage.appendChild(protocol)

        username = doc.createElement('UserName')
        username_text = doc.createTextNode('admin')
        username.appendChild(username_text)
        storage.appendChild(username)
        userpassword = doc.createElement('UserPassword')
        userpassword_text = doc.createTextNode('Admin@storage')
        userpassword.appendChild(userpassword_text)
        storage.appendChild(userpassword)
        url = doc.createElement('HVSURL')
        url_text = doc.createTextNode('http://100.115.10.69:8082/'
                                      'deviceManager/rest/')
        url.appendChild(url_text)
        storage.appendChild(url)
        lun = doc.createElement('LUN')
        config.appendChild(lun)
        storagepool = doc.createElement('StoragePool')
        pool_text = doc.createTextNode('OpenStack_Pool')
        storagepool.appendChild(pool_text)
        lun.appendChild(storagepool)

        luntype = doc.createElement('LUNType')
        luntype_text = doc.createTextNode('Thick')
        luntype.appendChild(luntype_text)
        lun.appendChild(luntype)

        writetype = doc.createElement('WriteType')
        writetype_text = doc.createTextNode('1')
        writetype.appendChild(writetype_text)
        lun.appendChild(writetype)

        prefetchType = doc.createElement('Prefetch')
        prefetchType.setAttribute('Type', '2')
        prefetchType.setAttribute('Value', '20')
        lun.appendChild(prefetchType)

        iscsi = doc.createElement('iSCSI')
        config.appendChild(iscsi)
        defaulttargetip = doc.createElement('DefaultTargetIP')
        defaulttargetip_text = doc.createTextNode('100.115.10.68')
        defaulttargetip.appendChild(defaulttargetip_text)
        iscsi.appendChild(defaulttargetip)

        initiator = doc.createElement('Initiator')
        initiator.setAttribute('Name', 'iqn.1993-08.debian:01:ec2bff7ac3a3')
        initiator.setAttribute('TargetIP', '100.115.10.68')
        iscsi.appendChild(initiator)

        newefile = open(self.fake_conf_file, 'w')
        newefile.write(doc.toprettyxml(indent=''))
        newefile.close()


class HVSRESTFCDriverTestCase(test.TestCase):
    def setUp(self):
        super(HVSRESTFCDriverTestCase, self).setUp()
        self.tmp_dir = tempfile.mkdtemp()
        self.fake_conf_file = self.tmp_dir + '/cinder_huawei_conf.xml'
        self.create_fake_conf_file()
        self.configuration = mox.MockObject(conf.Configuration)
        self.configuration.cinder_huawei_conf_file = self.fake_conf_file
        self.configuration.append_config_values(mox.IgnoreArg())

        self.stubs.Set(time, 'sleep', Fake_sleep)

        self.driver = FakeHVSFCStorage(configuration=self.configuration)
        self.driver.do_setup({})
        self.driver.common.test_normal = True

    def tearDown(self):
        if os.path.exists(self.fake_conf_file):
            os.remove(self.fake_conf_file)
        shutil.rmtree(self.tmp_dir)
        super(HVSRESTFCDriverTestCase, self).tearDown()

    def test_log_in_Success(self):
        deviceid = self.driver.common.login()
        self.assertIsNotNone(deviceid)

    def test_create_volume_success(self):
        self.driver.common.login()
        self.driver.create_volume(test_volume)
        self.assertEqual(self.driver.common.lun_id, "0")

    def test_extend_volume_success(self):
        self.driver.common.login()
        self.driver.extend_volume(test_volume, volume_size)
        self.assertEqual(self.driver.common.lun_id, "0")

    def test_create_snapshot_success(self):
        self.driver.common.login()
        self.driver.create_snapshot(test_volume)
        self.assertEqual(self.driver.common.snapshot_id, "3")

    def test_delete_volume_success(self):
        self.driver.common.login()
        self.driver.delete_volume(test_volume)
        self.assertIsNone(self.driver.common.lun_id)

    def test_delete_snapshot_success(self):
        self.driver.common.login()
        self.driver.delete_snapshot(test_snap)
        self.assertIsNone(self.driver.common.snapshot_id)

    def test_colone_volume_success(self):
        self.driver.common.login()
        self.driver.create_cloned_volume(test_volume, test_volume)
        self.assertEqual(self.driver.common.luncopy_id, "7")

    def test_create_volume_from_snapshot_success(self):
        self.driver.common.login()
        self.driver.create_volume_from_snapshot(test_volume, test_volume)
        self.assertEqual(self.driver.common.luncopy_id, "7")

    def test_initialize_connection_success(self):
        self.driver.common.login()
        conn = self.driver.initialize_connection(test_volume, FakeConnector)
        self.assertEqual(conn['data']['target_lun'], 1)

    def test_terminate_connection_success(self):
        self.driver.common.login()
        self.driver.terminate_connection(test_volume, FakeConnector)
        self.assertEqual(self.driver.common.termin_flag, True)

    def test_initialize_connection_no_view_success(self):
        self.driver.common.login()
        self.driver.common.other_flag = False
        conn = self.driver.initialize_connection(test_volume, FakeConnector)
        self.assertEqual(conn['data']['target_lun'], 1)

    def test_terminate_connection_no_viewn_success(self):
        self.driver.common.login()
        self.driver.common.other_flag = False
        self.driver.terminate_connection(test_volume, FakeConnector)
        self.assertEqual(self.driver.common.termin_flag, True)

    def test_get_volume_stats(self):
        self.driver.common.login()
        status = self.driver.get_volume_stats()
        self.assertIsNotNone(status['free_capacity_gb'])

    def test_create_snapshot_fail(self):
        self.driver.common.login()
        self.driver.common.test_normal = False
        self.assertRaises(exception.CinderException,
                          self.driver.create_snapshot, test_volume)

    def test_create_volume_fail(self):
        self.driver.common.login()
        self.driver.common.test_normal = False
        self.assertRaises(exception.CinderException,
                          self.driver.create_volume, test_volume)

    def test_delete_volume_fail(self):
        self.driver.common.login()
        self.driver.common.test_normal = False
        self.assertRaises(exception.CinderException,
                          self.driver.delete_volume, test_volume)

    def test_delete_snapshot_fail(self):
        self.driver.common.login()
        self.driver.common.test_normal = False
        self.assertRaises(exception.CinderException,
                          self.driver.delete_snapshot, test_volume)

    def create_fake_conf_file(self):
        doc = Document()

        config = doc.createElement('config')
        doc.appendChild(config)

        storage = doc.createElement('Storage')
        config.appendChild(storage)

        product = doc.createElement('Product')
        product_text = doc.createTextNode('HVS')
        product.appendChild(product_text)
        storage.appendChild(product)

        protocol = doc.createElement('Protocol')
        protocol_text = doc.createTextNode('FC')
        protocol.appendChild(protocol_text)
        storage.appendChild(protocol)

        username = doc.createElement('UserName')
        username_text = doc.createTextNode('admin')
        username.appendChild(username_text)
        storage.appendChild(username)

        userpassword = doc.createElement('UserPassword')
        userpassword_text = doc.createTextNode('Admin@storage')
        userpassword.appendChild(userpassword_text)
        storage.appendChild(userpassword)
        url = doc.createElement('HVSURL')
        url_text = doc.createTextNode('http://100.115.10.69:8082/'
                                      'deviceManager/rest/')
        url.appendChild(url_text)
        storage.appendChild(url)

        lun = doc.createElement('LUN')
        config.appendChild(lun)
        storagepool = doc.createElement('StoragePool')
        pool_text = doc.createTextNode('OpenStack_Pool')
        storagepool.appendChild(pool_text)
        lun.appendChild(storagepool)

        luntype = doc.createElement('LUNType')
        luntype_text = doc.createTextNode('Thick')
        luntype.appendChild(luntype_text)
        lun.appendChild(luntype)

        writetype = doc.createElement('WriteType')
        writetype_text = doc.createTextNode('1')
        writetype.appendChild(writetype_text)
        lun.appendChild(writetype)

        prefetchType = doc.createElement('Prefetch')
        prefetchType.setAttribute('Type', '2')
        prefetchType.setAttribute('Value', '20')
        lun.appendChild(prefetchType)

        newfile = open(self.fake_conf_file, 'w')
        newfile.write(doc.toprettyxml(indent=''))
        newfile.close()
