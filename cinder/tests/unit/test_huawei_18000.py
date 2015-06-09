# Copyright (c) 2013 - 2014 Huawei Technologies Co., Ltd.
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
""" Tests for huawei 18000 storage."""
import json
import os
import shutil
import tempfile
import time
from xml.dom import minidom

import mock
from oslo_log import log as logging

from cinder import exception
from cinder import test
from cinder.volume import configuration as conf
from cinder.volume.drivers.huawei import huawei_18000
from cinder.volume.drivers.huawei import rest_common

LOG = logging.getLogger(__name__)

test_volume = {'name': 'volume-21ec7341-9256-497b-97d9-ef48edcf0635',
               'size': 2,
               'volume_name': 'vol1',
               'id': '21ec7341-9256-497b-97d9-ef48edcf0635',
               'volume_id': '21ec7341-9256-497b-97d9-ef48edcf0635',
               'provider_auth': None,
               'project_id': 'project',
               'display_name': 'vol1',
               'display_description': 'test volume',
               'volume_type_id': None,
               'provider_location': '11'}

test_snap = {'name': 'volume-21ec7341-9256-497b-97d9-ef48edcf0635',
             'size': 1,
             'volume_name': 'vol1',
             'id': '21ec7341-9256-497b-97d9-ef48edcf0635',
             'volume_id': '21ec7341-9256-497b-97d9-ef48edcf0635',
             'provider_auth': None,
             'project_id': 'project',
             'display_name': 'vol1',
             'display_description': 'test volume',
             'volume_type_id': None,
             'provider_location': '11'}

FakeConnector = {'initiator': 'iqn.1993-08.debian:01:ec2bff7ac3a3',
                 'wwpns': ['10000090fa0d6754'],
                 'wwnns': ['10000090fa0d6755'],
                 'host': 'ubuntuc'}


def find_data(method):
    if method is None:
        data = """{"error":{"code":0},
                   "data":{"ID":"1",
                           "NAME":"5mFHcBv4RkCcD+JyrWc0SA"}}"""
    if method == 'GET':
        data = """{"error":{"code":0},
                   "data":[{"ID":"1",
                   "NAME":"IexzQZJWSXuX2e9I7c8GNQ"}]}"""
    return data


def find_data_lun(method):
    if method == 'GET':
        data = """{"error":{"code":0},
                   "data":{"ID":"1",
                   "NAME":"IexzQZJWSXuX2e9I7c8GNQ",
                   "HEALTHSTATUS":"1",
                   "RUNNINGSTATUS":"27"}}"""
    return data


def find_data_lungroup(method):
    if method is None:
        data = '{"error":{"code":0},\
                 "data":{"NAME":"5mFHcBv4RkCcD+JyrWc0SA",\
                         "DESCRIPTION":"5mFHcBv4RkCcD+JyrWc0SA",\
                         "ID":"11",\
                         "TYPE":256}}'

    if method == "GET":
        data = """{"error":{"code":0},
                   "data":[{
                    "NAME":"OpenStack_LunGroup_1",
                    "DESCRIPTION":"5mFHcBv4RkCcD+JyrWc0SA",
                    "ID":"11",
                    "TYPE":256}]}"""

    if method == "DELETE":
        data = """{"error":{"code":0},
                   "data":[{
                   "NAME":"IexzQZJWSXuX2e9I7c8GNQ",
                   "DESCRIPTION":"5mFHcBv4RkCcD+JyrWc0SA",
                   "ID":"11",
                   "TYPE":256}]}"""
    return data


def find_data_hostgroup(method):
    if method is None:
        data = """{"error":{"code":0},"data":{
                    "NAME":"ubuntuc",
                    "DESCRIPTION":"",
                    "ID":"0",
                    "TYPE":14}}"""

    if method == "GET":
        data = """{"error":{"code":0},"data":[{
                        "NAME":"ubuntuc",
                        "DESCRIPTION":"",
                        "ID":"0","TYPE":14}]}"""
    return data


def Fake_sleep(time):
    pass


def find_data_mappingview(method, other_flag):
    if method is None:
        data = """{"error":{"code":0},"data":
            {"WORKMODE":"255","HEALTHSTATUS":"1",
            "NAME":"mOWtSXnaQKi3hpB3tdFRIQ",
            "RUNNINGSTATUS":"27","DESCRIPTION":"",
            "ENABLEINBANDCOMMAND":"true",
            "ID":"1","INBANDLUNWWN":"",
            "TYPE":245}}
            """

    if method == "GET":
        if other_flag:
            data = """{"error":{"code":0},"data":[
                {"WORKMODE":"255","HEALTHSTATUS":"1",
                "NAME":"mOWtSXnaQKi3hpB3tdFRIQ",
                "RUNNINGSTATUS":"27","DESCRIPTION":"",
                "ENABLEINBANDCOMMAND":"true","ID":"1",
                "INBANDLUNWWN":"","TYPE":245},
                {"WORKMODE":"255","HEALTHSTATUS":"1",
                "NAME":"YheUoRwbSX2BxN767nvLSw",
                "RUNNINGSTATUS":"27","DESCRIPTION":"",
                "ENABLEINBANDCOMMAND":"true",
                "ID":"2","INBANDLUNWWN":"",
                "TYPE":245}]}
                """
        else:
            data = """{"error":{"code":0},"data":[
                {"WORKMODE":"255","HEALTHSTATUS":"1",
                "NAME":"IexzQZJWSXuX2e9I7c8GNQ",
                "RUNNINGSTATUS":"27","DESCRIPTION":"",
                "ENABLEINBANDCOMMAND":"true","ID":"1",
                "INBANDLUNWWN":"","TYPE":245},
                {"WORKMODE":"255","HEALTHSTATUS":"1",
                "NAME":"YheUoRwbSX2BxN767nvLSw",
                "RUNNINGSTATUS":"27","DESCRIPTION":"",
                "ENABLEINBANDCOMMAND":"true","ID":"2",
                "INBANDLUNWWN":"","TYPE":245}]}
                """
    return data


def find_data_snapshot(method):
    if method is None:
        data = '{"error":{"code":0},"data":{"ID":11,"NAME":"YheUoRwbSX2BxN7"}}'
    if method == "GET":
        data = """{"error":{"code":0},"data":[
                    {"ID":11,"NAME":"SDFAJSDFLKJ"},
                    {"ID":12,"NAME":"SDFAJSDFLKJ2"}]}"""
    return data


def find_data_host(method):
    if method is None:
        data = """{"error":{"code":0},
               "data":
                {"PARENTTYPE":245,
                "NAME":"Default Host",
                "DESCRIPTION":"",
                "RUNNINGSTATUS":"1",
                "IP":"",
                "PARENTNAME":"0",
                "OPERATIONSYSTEM":"1",
                "LOCATION":"",
                "HEALTHSTATUS":"1",
                "MODEL":"",
                "ID":"0",
                "PARENTID":"0",
                "NETWORKNAME":"",
                "TYPE":21}} """

    if method == "GET":
        data = """{"error":{"code":0},
               "data":[
                {"PARENTTYPE":245,"NAME":"ubuntuc",
                "DESCRIPTION":"","RUNNINGSTATUS":"1",
                "IP":"","PARENTNAME":"",
                "OPERATIONSYSTEM":"0","LOCATION":"",
                "HEALTHSTATUS":"1","MODEL":"",
                "ID":"1","PARENTID":"",
                "NETWORKNAME":"","TYPE":21},
                {"PARENTTYPE":245,"NAME":"ubuntu",
                "DESCRIPTION":"","RUNNINGSTATUS":"1",
                "IP":"","PARENTNAME":"","OPERATIONSYSTEM":"0",
                "LOCATION":"","HEALTHSTATUS":"1",
                "MODEL":"","ID":"2","PARENTID":"",
                "NETWORKNAME":"","TYPE":21}]} """
    return data


def find_data_host_associate(method):
    if (method is None) or (method == "GET"):
        data = '{"error":{"code":0}}'
    return data


def data_session(url):
    if url == "/xx/sessions":
        data = """{"error":{"code":0},
                       "data":{"username":"admin",
                               "iBaseToken":"2001031430",
                               "deviceid":"210235G7J20000000000"}}"""
    if url == "sessions":
        data = '{"error":{"code":0},"data":{"ID":11}}'
    return data


def data_lun(url, method):
    if url == "lun":
        data = find_data(method)
    if url == "lun/1":
        data = find_data_lun(method)
    if url == "lun?range=[0-65535]":
        data = find_data(method)
    if url == "lungroup?range=[0-8191]":
        data = find_data_lungroup(method)
    if url == "lungroup":
        data = find_data_lungroup(method)
    if url == "lungroup/associate":
        data = """{"error":{"code":0},
                   "data":{"NAME":"5mFHcBv4RkCcD+JyrWc0SA",
                           "DESCRIPTION":"5mFHcBv4RkCcD+JyrWc0SA",
                           "ID":"11",
                           "TYPE":256}}"""
    return data


def data_host(url, method):
    if url == "hostgroup":
        data = find_data_hostgroup(method)
    if url == "hostgroup?range=[0-8191]":
        data = find_data_hostgroup(method)
    if url == "host":
        data = find_data_host(method)
    if url == "host?range=[0-65534]":
        data = find_data_host(method)
    if url == "host/associate":
        data = find_data_host_associate(method)
    if url == "host/associate?TYPE=21&ASSOCIATEOBJTYPE=14&ASSOCIATEOBJID=0":
        data = find_data_host_associate(method)
    return data


def find_data_storagepool_snapshot(url, method):
    if url == "storagepool":
        data = """{"error":{"code":0},
                  "data":[{"USERFREECAPACITY":"985661440",
                           "ID":"0",
                           "NAME":"OpenStack_Pool",
                           "USERTOTALCAPACITY":"985661440"
                           }]}"""
    if url == "snapshot":
        data = find_data_snapshot(method)
    if url == "snapshot/activate":
        data = """{"error":{"code":0},"data":[
                        {"ID":11,"NAME":"SDFAJSDFLKJ"},
                        {"ID":12,"NAME":"SDFAJSDFLKJ"}]}"""

    return data


def find_data_luncpy_range_eth_port(url):
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

    if url == "eth_port":
        data = """{"error":{"code":0},
                    "data":[{"PARENTTYPE":209,
                    "MACADDRESS":"00:22:a1:0a:79:57",
                    "ETHNEGOTIATE":"-1","ERRORPACKETS":"0",
                    "IPV4ADDR":"192.168.100.2",
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
    return data


class Fake18000Common(rest_common.RestCommon):

    def __init__(self, configuration):
        rest_common.RestCommon.__init__(self, configuration)
        self.test_normal = True
        self.other_flag = True
        self.associate_flag = True
        self.connect_flag = False
        self.delete_flag = False
        self.terminateFlag = False
        self.deviceid = None

    def _change_file_mode(self, filepath):
        pass

    def _parse_volume_type(self, volume):

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

    def _get_snapshotid_by_name(self, snapshot_name):
        return "11"

    def _get_qosid_by_lunid(self, lunid):
        return ""

    def _check_snapshot_exist(self, snapshot_id):
        return True

    def fc_initiator_data(self):
        data = """{"error":{"code":0},"data":[
              {"HEALTHSTATUS":"1","NAME":"",
              "MULTIPATHTYPE":"1","ISFREE":"true",
              "RUNNINGSTATUS":"27","ID":"10000090fa0d6754",
              "OPERATIONSYSTEM":"255","TYPE":223},
              {"HEALTHSTATUS":"1","NAME":"",
              "MULTIPATHTYPE":"1","ISFREE":"true",
              "RUNNINGSTATUS":"27","ID":"10000090fa0d6755",
              "OPERATIONSYSTEM":"255","TYPE":223}]}"""
        return data

    def host_link(self):
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
        self.connect_flag = True
        return data

    def call(self, url=False, data=None, method=None):

        url = url.replace('http://100.115.10.69:8082/deviceManager/rest', '')
        url = url.replace('/210235G7J20000000000/', '')
        data = None

        if self.test_normal:
            if url == "/xx/sessions" or url == "sessions":
                data = data_session(url)

            if url == "lun/count?TYPE=11&ASSOCIATEOBJTYPE=256&"\
                      "ASSOCIATEOBJID=11":
                data = """{"data":{"COUNT":"7"},
                           "error":{"code":0,"description":"0"}}"""

            if url == "lungroup/associate?TYPE=256&ASSOCIATEOBJTYPE=11&"\
                      "ASSOCIATEOBJID=11":
                data = """{"error":{"code":0},
                           "data":[{"ID":11}]}"""

            if url == "storagepool" or url == "snapshot" or url == "snaps"\
                      "hot/activate":
                data = find_data_storagepool_snapshot(url, method)

            if url == "lungroup" or url == "lungroup/associate"\
                      or url == "lun" or url == "lun/1":
                data = data_lun(url, method)

            if url == "lun?range=[0-65535]" or url == "lungroup?r"\
                                                      "ange=[0-8191]":
                data = data_lun(url, method)

            if url == "lungroup/associate?ID=11"\
                      "&ASSOCIATEOBJTYPE=11&ASSOCIATEOBJID=11"\
                      or url == "lungroup/associate?ID=12"\
                      "&ASSOCIATEOBJTYPE=11&ASSOCIATEOBJID=12":
                data = '{"error":{"code":0}}'
                self.terminateFlag = True

            if url == "fc_initiator/10000090fa0d6754" or url == "lun/11"\
                      or url == "LUNCOPY/0"\
                      or url == "mappingview/REMOVE_ASSOCIATE":
                data = '{"error":{"code":0}}'
                self.delete_flag = True

            if url == "LUNCOPY/start" or url == "mappingview/1"\
                      or url == "hostgroup/associate":
                data = '{"error":{"code":0}}'

            if url == "MAPPINGVIEW/CREATE_ASSOCIATE" or url == "snapshot/11"\
                      or url == "snapshot/stop" or url == "LUNGroup/11":
                data = '{"error":{"code":0}}'
                self.delete_flag = True

            if url == "luncopy" or url == "eth_port" or url == "LUNC"\
                      "OPY?range=[0-100000]":
                data = find_data_luncpy_range_eth_port(url)

            if url == "iscsidevicename":
                data = """{"error":{"code":0},
                        "data":[{"CMO_ISCSI_DEVICE_NAME":
"iqn.2006-08.com.huawei:oceanstor:21000022a10a2a39:iscsinametest"}]}"""

            if url == "hostgroup" or url == "host" or url == "host/associate":
                data = data_host(url, method)

            if url == "host/associate?TYPE=21&ASSOCIATEOBJTYPE=14&AS"\
                      "SOCIATEOBJID=0":
                data = data_host(url, method)

            if url == "hostgroup?range=[0-8191]" or url == "host?ra"\
                      "nge=[0-65534]":
                data = data_host(url, method)

            if url == "iscsi_initiator/iqn.1993-08.debian:01:ec2bff7ac3a3":
                data = """{"error":{"code":0},"data":{
                            "ID":"iqn.1993-08.debian:01:ec2bff7ac3a3",
                            "NAME":"iqn.1993-08.debian:01:ec2bff7ac3a3",
                            "ISFREE":"True"}}"""

            if url == "iscsi_initiator" or url == "iscsi_initiator/"\
               or url == "iscsi_initiator?range=[0-65535]":
                data = '{"error":{"code":0}}'

            if url == "mappingview" or url == "mappingview?range=[0-65535]":
                data = find_data_mappingview(method, self.other_flag)

            if (url == ("lun/associate?ID=1&TYPE=11&"
                        "ASSOCIATEOBJTYPE=21&ASSOCIATEOBJID=0")
               or url == ("lun/associate?TYPE=11&ASSOCIATEOBJTYPE=256"
                          "&ASSOCIATEOBJID=11")
               or (url == ("lun/associate?TYPE=11&ASSOCIATEOBJTYPE=256"
                           "&ASSOCIATEOBJID=12")
               and not self.associate_flag)):
                data = '{"error":{"code":0},"data":[{"ID":"11"}]}'
            if ((url == ("lun/associate?TYPE=11&ASSOCIATEOBJTYPE=256"
                         "&ASSOCIATEOBJID=12"))
               and self.associate_flag):
                data = '{"error":{"code":0},"data":[{"ID":"12"}]}'

            if url == "fc_initiator?ISFREE=true&range=[0-1000]":
                data = self.fc_initiator_data()

            if url == "host_link?INITIATOR_TYPE=223&INITIATOR_PORT_WWN="\
                      "10000090fa0d6754":
                data = self.host_link()

            if url == "mappingview/associate?TYPE=245&"\
                      "ASSOCIATEOBJTYPE=14&ASSOCIATEOBJID=0"\
                      or url == "mappingview/associate?TYPE=245&"\
                      "ASSOCIATEOBJTYPE=256&ASSOCIATEOBJID=11":
                data = '{"error":{"code":0},"data":[{"ID":11,"NAME":"test"}]}'

            if url == "lun/associate?TYPE=11&"\
                      "ASSOCIATEOBJTYPE=21&ASSOCIATEOBJID=1":
                data = '{"error":{"code":0}}'
                self.connect_flag = True

            if url == "iscsi_tgt_port":
                data = '{"data":[{"ETHPORTID":"139267",\
                "ID":"iqn.oceanstor:21004846fb8ca15f::22003:111.111.101.244",\
                "TPGT":"8196","TYPE":249}],\
                "error":{"code":0,"description":"0"}}'

        else:
            data = '{"error":{"code":31755596}}'
            if (url == "lun/11") and (method == "GET"):
                data = """{"error":{"code":0},"data":{"ID":"11",
                       "IOCLASSID":"11",
                       "NAME":"5mFHcBv4RkCcD+JyrWc0SA"}}"""
        res_json = json.loads(data)

        return res_json


class Fake18000Storage(huawei_18000.Huawei18000ISCSIDriver):
    """Fake Huawei Storage, Rewrite some methods of HuaweiISCSIDriver."""

    def __init__(self, configuration):
        super(Fake18000Storage, self).__init__(configuration)
        self.configuration = configuration

    def do_setup(self):
        self.common = Fake18000Common(configuration=self.configuration)


class Fake18000FCStorage(huawei_18000.Huawei18000FCDriver):
    """Fake Huawei Storage, Rewrite some methods of HuaweiISCSIDriver."""
    def __init__(self, configuration):
        super(Fake18000FCStorage, self).__init__(configuration)
        self.configuration = configuration

    def do_setup(self):
        self.common = Fake18000Common(configuration=self.configuration)


class Huawei18000ISCSIDriverTestCase(test.TestCase):

    def setUp(self):
        super(Huawei18000ISCSIDriverTestCase, self).setUp()
        self.tmp_dir = tempfile.mkdtemp()
        self.fake_conf_file = self.tmp_dir + '/cinder_huawei_conf.xml'
        self.addCleanup(shutil.rmtree, self.tmp_dir)
        self.create_fake_conf_file()
        self.addCleanup(os.remove, self.fake_conf_file)
        self.configuration = mock.Mock(spec=conf.Configuration)
        self.configuration.cinder_huawei_conf_file = self.fake_conf_file
        self.stubs.Set(time, 'sleep', Fake_sleep)
        driver = Fake18000Storage(configuration=self.configuration)
        self.driver = driver
        self.driver.do_setup()
        self.driver.common.test_normal = True

    def testloginSuccess(self):
        deviceid = self.driver.common.login()
        self.assertEqual(deviceid, '210235G7J20000000000')

    def testcreatevolumesuccess(self):
        self.driver.common.login()
        lun_info = self.driver.create_volume(test_volume)
        self.assertEqual(lun_info['provider_location'], '1')
        self.assertEqual(lun_info['lun_info']['NAME'],
                         '5mFHcBv4RkCcD+JyrWc0SA')

    def testcreatesnapshotsuccess(self):
        self.driver.common.login()
        lun_info = self.driver.create_snapshot(test_volume)
        self.assertEqual(lun_info['provider_location'], 11)
        self.assertEqual(lun_info['lun_info']['NAME'], 'YheUoRwbSX2BxN7')

    def testdeletevolumesuccess(self):
        self.driver.common.login()
        self.driver.common.delete_flag = False
        self.driver.delete_volume(test_volume)
        self.assertTrue(self.driver.common.delete_flag)

    def testdeletesnapshotsuccess(self):
        self.driver.common.login()
        self.driver.common.delete_flag = False
        self.driver.delete_snapshot(test_snap)
        self.assertTrue(self.driver.common.delete_flag)

    def testcolonevolumesuccess(self):
        self.driver.common.login()
        lun_info = self.driver.create_cloned_volume(test_volume,
                                                    test_volume)
        self.assertEqual(lun_info['provider_location'], '1')
        self.assertEqual(lun_info['lun_info']['NAME'],
                         '5mFHcBv4RkCcD+JyrWc0SA')

    def testcreateolumefromsnapsuccess(self):
        self.driver.common.login()
        lun_info = self.driver.create_volume_from_snapshot(test_volume,
                                                           test_volume)
        self.assertEqual(lun_info['provider_location'], '1')
        self.assertEqual(lun_info['lun_info']['NAME'],
                         '5mFHcBv4RkCcD+JyrWc0SA')

    def testinitializeconnectionsuccess(self):
        self.driver.common.login()
        iscsi_properties = self.driver.initialize_connection(test_volume,
                                                             FakeConnector)
        self.assertEqual(iscsi_properties['data']['target_lun'], 1)

    def testterminateconnectionsuccess(self):
        self.driver.common.login()
        self.driver.common.terminateFlag = False
        self.driver.terminate_connection(test_volume, FakeConnector)
        self.assertTrue(self.driver.common.terminateFlag)

    def testinitializeconnectionnoviewsuccess(self):
        self.driver.common.login()
        self.driver.common.other_flag = False
        self.driver.common.connect_flag = False
        self.driver.initialize_connection(test_volume, FakeConnector)
        self.assertTrue(self.driver.common.connect_flag)

    def testterminateconnectionoviewnsuccess(self):
        self.driver.common.login()
        self.driver.common.terminateFlag = False
        self.driver.terminate_connection(test_volume, FakeConnector)
        self.assertTrue(self.driver.common.terminateFlag)

    def testgetvolumestatus(self):
        self.driver.common.login()
        data = self.driver.get_volume_stats()
        self.assertEqual(data['driver_version'], '1.1.0')

    def testloginfail(self):
        self.driver.common.test_normal = False
        self.assertRaises(exception.CinderException, self.driver.common.login)

    def testcreatesnapshotfail(self):
        self.driver.common.login()
        self.driver.common.test_normal = False
        self.assertRaises(exception.CinderException,
                          self.driver.create_snapshot, test_volume)

    def testcreatevolumefail(self):
        self.driver.common.login()
        self.driver.common.test_normal = False
        self.assertRaises(exception.CinderException,
                          self.driver.create_volume, test_volume)

    def testdeletevolumefail(self):
        self.driver.common.login()
        self.driver.common.test_normal = False
        self.assertRaises(exception.CinderException,
                          self.driver.delete_volume, test_volume)

    def testdeletesnapshotfail(self):
        self.driver.common.login()
        self.driver.common.test_normal = False
        self.assertRaises(exception.CinderException,
                          self.driver.delete_snapshot, test_volume)

    def testinitializeconnectionfail(self):
        self.driver.common.login()
        self.driver.common.test_normal = False
        self.assertRaises(exception.CinderException,
                          self.driver.initialize_connection,
                          test_volume, FakeConnector)

    def testgetdefaulttimeout(self):
        result = self.driver.common._get_default_timeout()
        self.assertEqual('43200', result)

    def testgetwaitinterval(self):
        result = self.driver.common._get_wait_interval('LUNReadyWaitInterval')
        self.assertEqual('2', result)

    def test_lun_is_associated_to_lungroup(self):
        self.driver.common.login()
        self.driver.common._associate_lun_to_lungroup('11', '11')
        result = self.driver.common._is_lun_associated_to_lungroup('11', '11')
        self.assertTrue(result)

    def test_lun_is_not_associated_to_lun_group(self):
        self.driver.common.login()
        self.driver.common._associate_lun_to_lungroup('12', '12')
        self.driver.common.associate_flag = True
        result = self.driver.common._is_lun_associated_to_lungroup('12', '12')
        self.assertTrue(result)
        self.driver.common._remove_lun_from_lungroup('12', '12')
        self.driver.common.associate_flag = False
        result = self.driver.common._is_lun_associated_to_lungroup('12', '12')
        self.assertFalse(result)

    def create_fake_conf_file(self):
        """Create a fake Config file

          Huawei storage customize a XML configuration file, the configuration
          file is used to set the Huawei storage custom parameters, therefore,
          in the UT test we need to simulate such a configuration file
        """
        doc = minidom.Document()

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
        userpassword_text = doc.createTextNode('Admin@storage')
        userpassword.appendChild(userpassword_text)
        storage.appendChild(userpassword)
        url = doc.createElement('RestURL')
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

        timeout = doc.createElement('Timeout')
        timeout_text = doc.createTextNode('43200')
        timeout.appendChild(timeout_text)
        lun.appendChild(timeout)

        lun_ready_wait_interval = doc.createElement('LUNReadyWaitInterval')
        lun_ready_wait_interval_text = doc.createTextNode('2')
        lun_ready_wait_interval.appendChild(lun_ready_wait_interval_text)
        lun.appendChild(lun_ready_wait_interval)

        prefetch = doc.createElement('Prefetch')
        prefetch.setAttribute('Type', '0')
        prefetch.setAttribute('Value', '0')
        lun.appendChild(prefetch)

        iscsi = doc.createElement('iSCSI')
        config.appendChild(iscsi)
        defaulttargetip = doc.createElement('DefaultTargetIP')
        defaulttargetip_text = doc.createTextNode('100.115.10.68')
        defaulttargetip.appendChild(defaulttargetip_text)
        iscsi.appendChild(defaulttargetip)
        initiator = doc.createElement('Initiator')
        initiator.setAttribute('Name', 'iqn.1993-08.debian:01:ec2bff7ac3a3')
        initiator.setAttribute('TargetIP', '192.168.100.2')
        iscsi.appendChild(initiator)

        fakefile = open(self.fake_conf_file, 'w')
        fakefile.write(doc.toprettyxml(indent=''))
        fakefile.close()


class Huawei18000FCDriverTestCase(test.TestCase):

    def setUp(self):
        super(Huawei18000FCDriverTestCase, self).setUp()
        self.tmp_dir = tempfile.mkdtemp()
        self.fake_conf_file = self.tmp_dir + '/cinder_huawei_conf.xml'
        self.addCleanup(shutil.rmtree, self.tmp_dir)
        self.create_fake_conf_file()
        self.addCleanup(os.remove, self.fake_conf_file)
        self.configuration = mock.Mock(spec=conf.Configuration)
        self.configuration.cinder_huawei_conf_file = self.fake_conf_file
        self.stubs.Set(time, 'sleep', Fake_sleep)
        driver = Fake18000FCStorage(configuration=self.configuration)
        self.driver = driver
        self.driver.do_setup()
        self.driver.common.test_normal = True

    def testloginSuccess(self):
        deviceid = self.driver.common.login()
        self.assertEqual(deviceid, '210235G7J20000000000')

    def testcreatevolumesuccess(self):
        self.driver.common.login()
        lun_info = self.driver.create_volume(test_volume)
        self.assertEqual(lun_info['provider_location'], '1')
        self.assertEqual(lun_info['lun_info']['NAME'],
                         '5mFHcBv4RkCcD+JyrWc0SA')

    def testcreatesnapshotsuccess(self):
        self.driver.common.login()
        lun_info = self.driver.create_snapshot(test_volume)
        self.assertEqual(lun_info['provider_location'], 11)
        self.assertEqual(lun_info['lun_info']['NAME'], 'YheUoRwbSX2BxN7')

    def testdeletevolumesuccess(self):
        self.driver.common.login()
        self.driver.common.delete_flag = False
        self.driver.delete_volume(test_volume)
        self.assertTrue(self.driver.common.delete_flag)

    def testdeletesnapshotsuccess(self):
        self.driver.common.login()
        self.driver.common.delete_flag = False
        self.driver.delete_snapshot(test_snap)
        self.assertTrue(self.driver.common.delete_flag)

    def testcolonevolumesuccess(self):
        self.driver.common.login()
        lun_info = self.driver.create_cloned_volume(test_volume,
                                                    test_volume)
        self.assertEqual(lun_info['provider_location'], '1')
        self.assertEqual(lun_info['lun_info']['NAME'],
                         '5mFHcBv4RkCcD+JyrWc0SA')

    def testcreateolumefromsnapsuccess(self):
        self.driver.common.login()
        volumeid = self.driver.create_volume_from_snapshot(test_volume,
                                                           test_volume)
        self.assertEqual(volumeid['provider_location'], '1')

    def testinitializeconnectionsuccess(self):
        self.driver.common.login()
        properties = self.driver.initialize_connection(test_volume,
                                                       FakeConnector)
        self.assertEqual(properties['data']['target_lun'], 1)

    def testterminateconnectionsuccess(self):
        self.driver.common.login()
        self.driver.common.terminateFlag = False
        self.driver.terminate_connection(test_volume, FakeConnector)
        self.assertTrue(self.driver.common.terminateFlag)

    def testinitializeconnectionnoviewsuccess(self):
        self.driver.common.login()
        self.driver.common.other_flag = False
        self.driver.common.connect_flag = False
        self.driver.initialize_connection(test_volume, FakeConnector)
        self.assertTrue(self.driver.common.connect_flag)

    def testterminateconnectionoviewnsuccess(self):
        self.driver.common.login()
        self.driver.common.terminateFlag = False
        self.driver.terminate_connection(test_volume, FakeConnector)
        self.assertTrue(self.driver.common.terminateFlag)

    def testgetvolumestatus(self):
        self.driver.common.login()
        data = self.driver.get_volume_stats()
        self.assertEqual(data['driver_version'], '1.1.0')

    def testloginfail(self):
        self.driver.common.test_normal = False
        self.assertRaises(exception.CinderException,
                          self.driver.common.login)

    def testcreatesnapshotfail(self):
        self.driver.common.login()
        self.driver.common.test_normal = False
        self.assertRaises(exception.CinderException,
                          self.driver.create_snapshot, test_volume)

    def testcreatevolumefail(self):
        self.driver.common.login()
        self.driver.common.test_normal = False
        self.assertRaises(exception.CinderException,
                          self.driver.create_volume, test_volume)

    def testdeletevolumefail(self):
        self.driver.common.login()
        self.driver.common.test_normal = False
        self.assertRaises(exception.CinderException,
                          self.driver.delete_volume, test_volume)

    def testdeletesnapshotfail(self):
        self.driver.common.login()
        self.driver.common.test_normal = False
        self.assertRaises(exception.CinderException,
                          self.driver.delete_snapshot, test_volume)

    def testinitializeconnectionfail(self):
        self.driver.common.login()
        self.driver.common.test_normal = False
        self.assertRaises(exception.CinderException,
                          self.driver.initialize_connection,
                          test_volume, FakeConnector)

    def testgetdefaulttimeout(self):
        result = self.driver.common._get_default_timeout()
        self.assertEqual('43200', result)

    def testgetwaitinterval(self):
        result = self.driver.common._get_wait_interval('LUNReadyWaitInterval')
        self.assertEqual('2', result)

    def test_lun_is_associated_to_lungroup(self):
        self.driver.common.login()
        self.driver.common._associate_lun_to_lungroup('11', '11')
        result = self.driver.common._is_lun_associated_to_lungroup('11', '11')
        self.assertTrue(result)

    def test_lun_is_not_associated_to_lun_group(self):
        self.driver.common.login()
        self.driver.common._associate_lun_to_lungroup('12', '12')
        self.driver.common.associate_flag = True
        result = self.driver.common._is_lun_associated_to_lungroup('12', '12')
        self.assertTrue(result)
        self.driver.common._remove_lun_from_lungroup('12', '12')
        self.driver.common.associate_flag = False
        result = self.driver.common._is_lun_associated_to_lungroup('12', '12')
        self.assertFalse(result)

    def create_fake_conf_file(self):
        """Create a fake Config file

          Huawei storage customize a XML configuration file, the configuration
          file is used to set the Huawei storage custom parameters, therefore,
          in the UT test we need to simulate such a configuration file
        """
        doc = minidom.Document()

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
        userpassword_text = doc.createTextNode('Admin@storage')
        userpassword.appendChild(userpassword_text)
        storage.appendChild(userpassword)
        url = doc.createElement('RestURL')
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

        timeout = doc.createElement('Timeout')
        timeout_text = doc.createTextNode('43200')
        timeout.appendChild(timeout_text)
        lun.appendChild(timeout)

        lun_ready_wait_interval = doc.createElement('LUNReadyWaitInterval')
        lun_ready_wait_interval_text = doc.createTextNode('2')
        lun_ready_wait_interval.appendChild(lun_ready_wait_interval_text)
        lun.appendChild(lun_ready_wait_interval)

        prefetch = doc.createElement('Prefetch')
        prefetch.setAttribute('Type', '0')
        prefetch.setAttribute('Value', '0')
        lun.appendChild(prefetch)

        iscsi = doc.createElement('iSCSI')
        config.appendChild(iscsi)
        defaulttargetip = doc.createElement('DefaultTargetIP')
        defaulttargetip_text = doc.createTextNode('100.115.10.68')
        defaulttargetip.appendChild(defaulttargetip_text)
        iscsi.appendChild(defaulttargetip)
        initiator = doc.createElement('Initiator')
        initiator.setAttribute('Name', 'iqn.1993-08.debian:01:ec2bff7ac3a3')
        initiator.setAttribute('TargetIP', '192.168.100.2')
        iscsi.appendChild(initiator)

        fakefile = open(self.fake_conf_file, 'w')
        fakefile.write(doc.toprettyxml(indent=''))
        fakefile.close()
