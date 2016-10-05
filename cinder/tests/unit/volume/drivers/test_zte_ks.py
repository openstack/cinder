# Copyright 2016 ZTE Corporation. All rights reserved
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.
#

"""
Self test for ZTE Storage Driver platform.
"""
from oslo_config import cfg

from cinder import exception
from cinder import test
from cinder.volume import configuration as conf
from cinder.volume.drivers.zte import zte_ks
from cinder.volume.drivers.zte import zte_pub


session_id = 'kfomqdnoetjcjlva'
volume_paras = {'name': 'volume-21ec7341-9256-497b-97d9-ef48edcf0635',
                'size': 2,
                'volume_name': 'vol1',
                'id': '21ec7341-9256-497b-97d9-ef48edcf0635',
                'volume_id': '21ec7341-9256-497b-97d9-ef48edcf0635',
                'provider_auth': None,
                'project_id': 'project',
                'display_name': 'vol1',
                'source_volid': None,
                'volume_metadata': [],
                'display_description': 'test volume',
                'volume_type_id': None}

volume_clone = {'name': 'volume-ee317512-f6a6-4284-a94e-5f4ac8783169',
                'size': 4,
                'volume_name': 'vol1',
                'id': 'ee317512-f6a6-4284-a94e-5f4ac8783169',
                'volume_id': 'ee317512-f6a6-4284-a94e-5f4ac8783169',
                'provider_auth': None,
                'project_id': 'project',
                'display_name': 'clone_vol1',
                'source_volid': None,
                'volume_metadata': [],
                'display_description': 'test clone volume',
                'volume_type_id': None}
snapvolume_paras = {'name': 'volume-21ec7341-9256-497b-97d9-ef48edcf0635',
                    'size': 2,
                    'volume_size': 2,
                    'volume_name': 'vol1',
                    'id': '21ec7341-9256-497b-97d9-ef48edcf0635',
                    'volume_id': '21ec7341-9256-497b-97d9-ef48edcf0635',
                    'provider_auth': None,
                    'project_id': 'project',
                    'display_name': 'vol1',
                    'source_volid': None,
                    'volume_metadata': [],
                    'display_description': 'test volume',
                    'volume_type_id': None}
connector = {'ip': '10.0.0.0',
             'initiator': 'iqn.1993-08.org.debian:01:222'}
fcconnector = {'ip': '10.0.0.0',
               'wwpns': [1, 2, 3, 4, 5, 6, 7, 8]}
fake_opt = [
    cfg.StrOpt('fake_opt', default='fake', help='fake opts')
]
VolFlowLimitAttr_paras = {'sqwWriteFlowLimit': 0,
                          'cVolName': 'OpenCos_5072124445952515861',
                          'sqwTotalFlowLimit': 500,
                          'sqwWriteIoCount': 0,
                          'sqwTotalIoCount': 0,
                          'sqwReadFlowLimit': 0,
                          'sqwReadIoCount': 0}

volume_name = 'OpenCos_8359669312515962256'
return_success = {'returncode': zte_pub.ZTE_SUCCESS, 'data': {}}
return_error = {'returncode': zte_pub.ZTE_ERR_LUNDEV_NOT_EXIST, 'data': {}}
return_port_error = (
    {'returncode': zte_pub.ZTE_ERR_PORT_EXIST_INOTHER, 'data': {}})
return_host_error = (
    {'returncode': zte_pub.ZTE_ERR_HOST_EXIST_INOTHER, 'data': {}})

MAP_TO_RESPONSE = {}
signin_info = {'sessionID': session_id}
MAP_TO_RESPONSE['plat.session.signin'] = {'returncode': zte_pub.ZTE_SUCCESS,
                                          'data': signin_info}
MAP_TO_RESPONSE['plat.session.heartbeat'] = return_success
pool_info = {'sdwState': 1, 'qwTotalCapacity': 1024560,
             'qwFreeCapacity': 102456}
MAP_TO_RESPONSE['GetPoolInfo'] = {'returncode': zte_pub.ZTE_SUCCESS,
                                  'data': pool_info}
MAP_TO_RESPONSE['CreateVolOnPool'] = return_success
MAP_TO_RESPONSE['DelCvol'] = return_success
MAP_TO_RESPONSE['GetCvolNamesOnVol'] = {
    'returncode': zte_pub.ZTE_SUCCESS,
    'data': {'sdwCvolNum': 2, 'scCvolNames': [{'scCvolName': 'clone1'},
                                              {'scCvolName': 'clone2'}]}}
MAP_TO_RESPONSE['CreateSvol'] = return_success
MAP_TO_RESPONSE['DelSvol'] = return_success
MAP_TO_RESPONSE['ExpandVolOnPool'] = return_success
MAP_TO_RESPONSE['CreateCvol'] = return_success
cVolName_from_vol_name = "OpenCos_9fbc232bf71ee2fa8bd"
grp_info = {'sdwHostNum': 1,
            'tHostInfo': [{'ucHostName': 'host1'}],
            'sdwLunNum': 5,
            'cMapGrpName': 'group_cjf',
            'tLunInfo': [{'sdwLunState': 0, 'sdwBlockSize': 0,
                          'sdwAccessAttr': 0, 'sdwLunId': 0,
                          'cVolName': 'vol1'},
                         {'sdwLunState': 0, 'sdwBlockSize': 0,
                          'sdwAccessAttr': 0, 'sdwLunId': 1,
                          'cVolName': volume_name},
                         {'sdwLunState': 0, 'sdwBlockSize': 0,
                          'sdwAccessAttr': 0, 'sdwLunId': 2,
                          'cVolName': 'vol3'},
                         {'sdwLunState': 0, 'sdwBlockSize': 0,
                          'sdwAccessAttr': 0, 'sdwLunId': 3,
                          'cVolName': cVolName_from_vol_name},
                         {'sdwLunState': 0, 'sdwBlockSize': 0,
                          'sdwAccessAttr': 0, 'sdwLunId': 5,
                          'cVolName': 'vol4'}]}
MAP_TO_RESPONSE['GetMapGrpInfo'] = (
    {'returncode': zte_pub.ZTE_SUCCESS, 'data': grp_info})
MAP_TO_RESPONSE['DelMapGrp'] = return_success
simple_grp_info = {'sdwMapGrpNum': 0,
                   'tMapGrpSimpleInfo': [{'sdwHostNum': 0,
                                          'sdwLunNum': 0,
                                          'cMapGrpName': session_id},
                                         {'sdwHostNum': 1,
                                          'sdwLunNum': 1,
                                          'cMapGrpName': ''}]}
MAP_TO_RESPONSE['GetGrpSimpleInfoList'] = {'returncode': zte_pub.ZTE_SUCCESS,
                                           'data': simple_grp_info}
luninfo = {'sdwLunId': 3}
MAP_TO_RESPONSE['AddVolToGrp'] = {'returncode': zte_pub.ZTE_SUCCESS,
                                  'data': luninfo}
sys_info = {'cVendor': 'ZTE', 'cVersionName': 'V1.0',
            'storage_protocol': 'iSCSI'}
MAP_TO_RESPONSE['GetSysInfo'] = {'returncode': zte_pub.ZTE_SUCCESS,
                                 'data': sys_info}
cfg_info = {'sdwDeviceNum': 4,
            'tSystemNetCfg': [
                {'udwCtrlId': 0, 'udwRoleType': 0,
                 'udwPortType': 1, 'udwDeviceId': 123,
                 'cIpAddr': '198.51.100.20'},
                {'udwCtrlId': 0, 'udwRoleType': 0,
                 'udwPortType': 1, 'udwDeviceId': 123,
                 'cIpAddr': '198.51.100.21'},
                {'udwCtrlId': 0, 'udwRoleType': 0,
                 'udwPortType': 1, 'udwDeviceId': 123,
                 'cIpAddr': '198.51.100.22'},
                {'udwCtrlId': 0, 'udwRoleType': 0,
                 'udwPortType': 1, 'udwDeviceId': 123,
                 'cIpAddr': '198.51.100.23'}]}
MAP_TO_RESPONSE['GetSystemNetCfg'] = {'returncode': zte_pub.ZTE_SUCCESS,
                                      'data': cfg_info}
iscsi_target = {
    'tIscsiTargetInfo': [
        {'udwCtrlId': 0,
         'cTgtName': 'iqn.2099-01.cn.com.zte:usp.spr11-00:00:22:15'},
        {'udwCtrlId': 0,
         'cTgtName': 'iqn.2099-01.cn.com.zte:usp.spr11-00:00:22:25'}],
    'udwCtrlCount': 2}
MAP_TO_RESPONSE['GetIscsiTargetName'] = {'returncode': zte_pub.ZTE_SUCCESS,
                                         'data': iscsi_target}
MAP_TO_RESPONSE['CreateMapGrp'] = return_success
grp_info_forsearch = {'cVolName': 'vol1',
                      'sdwMapGrpNum': 1,
                      'cMapGrpNames': ['grp1'],
                      'sdwLunLocalId': [1]}
MAP_TO_RESPONSE['GetGrpNamesOfVol'] = (
    {'returncode': zte_pub.ZTE_SUCCESS, 'data': grp_info_forsearch})
MAP_TO_RESPONSE['CreateHost'] = return_success
MAP_TO_RESPONSE['AddPortToHost'] = return_success
MAP_TO_RESPONSE['AddHostToGrp'] = return_success
MAP_TO_RESPONSE['DelVolFromGrp'] = return_success
MAP_TO_RESPONSE['DelHostFromGrp'] = return_success
host_info = {'sdwPortNum': 2,
             'tPort': [{'cPortName': 'port1'},
                       {'cPortName': 'port2'}]}
MAP_TO_RESPONSE['GetHost'] = {'returncode': zte_pub.ZTE_SUCCESS,
                              'data': host_info}
MAP_TO_RESPONSE['DelPortFromHost'] = return_success
MAP_TO_RESPONSE['DelHost'] = return_success


class FakeZteISCSIDriver(zte_ks.ZteISCSIDriver):
    def __init__(self, configuration):
        self.configuration = configuration
        super(FakeZteISCSIDriver, self).__init__(
            configuration=self.configuration)
        self.result = zte_pub.ZTE_SUCCESS
        self.test_flag = True
        self.portexist_flag = False
        self.portexistother_flag = False
        self.hostexist_flag = False
        self.hostexistother_flag = False

    def _call(self, sessionid='', method='', params=None):
        return_data = return_success

        if method in MAP_TO_RESPONSE.keys():
            return_data = MAP_TO_RESPONSE[method]

        if not self.test_flag:
            return_data = return_error
        if self.portexistother_flag:
            return_data = return_port_error
        if self.hostexistother_flag:
            return_data = return_host_error
        return return_data

    def _check_conf_file(self):
        pass

    def _get_iscsi_info(self):
        iscsi_info = {'DefaultTargetIPs': ["198.51.100.20"]}

        return iscsi_info


class ZteBaseDriverTestCase(object):
    def test_create_volume_success(self):
        self.driver.test_flag = True
        self.driver.create_volume(volume_paras)
        self.assertEqual(zte_pub.ZTE_SUCCESS, self.driver.result)

    def test_create_volume_fail(self):
        self.driver.test_flag = False
        self.assertRaises(exception.CinderException,
                          self.driver.create_volume, volume_paras)

    def test_delete_volume_success(self):
        self.driver.test_flag = True
        self.driver.delete_volume(volume_paras)
        self.assertEqual(zte_pub.ZTE_SUCCESS, self.driver.result)

    def test_delete_volume_fail(self):
        self.driver.test_flag = False
        self.assertRaises(exception.CinderException,
                          self.driver.delete_volume, volume_paras)

    def test_delete_cloned_volume_success(self):
        self.driver.test_flag = True
        vol = {'name': 'volume-21ec7341-9256-497b-97d9-ef48edcf0635',
               'source_volid': '68a52c1e-ecbe-4f6c-954c-9f551347ff3f'}
        self.driver.delete_volume(vol)
        self.assertEqual(zte_pub.ZTE_SUCCESS, self.driver.result)

    def test_delete_cloned_volume_fail(self):
        self.driver.test_flag = False
        vol = {'name': 'volume-21ec7341-9256-497b-97d9-ef48edcf0635',
               'source_volid': '68a52c1e-ecbe-4f6c-954c-9f551347ff3f'}
        self.assertRaises(exception.CinderException,
                          self.driver.delete_volume, vol)

    def test_create_snapshot_success(self):
        self.driver.test_flag = True
        snap_vol = {'name': 'snapshot-2b9b982a-8b56-46e3-9d4f-6392e8a72e6e',
                    'volume_name':
                        'volume-21ec7341-9256-497b-97d9-ef48edcf0635',
                    'volume_size': 2}
        self.driver.create_snapshot(snap_vol)
        self.assertEqual(zte_pub.ZTE_SUCCESS, self.driver.result)

    def test_create_snapshot_fail(self):
        self.driver.test_flag = False
        snap_vol = {'name': 'snapshot-2b9b982a-8b56-46e3-9d4f-6392e8a72e6e',
                    'volume_name':
                        'volume-21ec7341-9256-497b-97d9-ef48edcf0635',
                    'volume_size': 2}
        self.assertRaises(exception.CinderException,
                          self.driver.create_snapshot, snap_vol)

    def test_delete_snapshot_success(self):
        self.driver.test_flag = True
        snap_vol = {'name': 'snapshot-2b9b982a-8b56-46e3-9d4f-6392e8a72e6e'}
        self.driver.delete_snapshot(snap_vol)
        self.assertEqual(zte_pub.ZTE_SUCCESS, self.driver.result)

    def test_delete_snapshot_fail(self):
        self.driver.test_flag = False
        snap_vol = {'name': 'snapshot-2b9b982a-8b56-46e3-9d4f-6392e8a72e6e'}
        self.assertRaises(exception.CinderException,
                          self.driver.delete_snapshot, snap_vol)

    def test_extend_volume_success(self):
        self.driver.test_flag = True
        self.driver.extend_volume(volume_paras, 4)
        self.assertEqual(zte_pub.ZTE_SUCCESS, self.driver.result)

    def test_extend_volume_fail(self):
        self.driver.test_flag = False
        self.assertRaises(exception.CinderException,
                          self.driver.extend_volume, volume_paras, 4)

    def test_create_cloned_volume_success(self):
        self.driver.test_flag = True
        self.driver.create_cloned_volume(volume_clone, volume_paras)
        self.assertEqual(zte_pub.ZTE_SUCCESS, self.driver.result)

    def test_create_cloned_volume_fail(self):
        self.driver.test_flag = False
        self.assertRaises(exception.CinderException,
                          self.driver.create_cloned_volume,
                          volume_clone, volume_paras)

    def test_create_volume_from_snapshot_success(self):
        self.driver.test_flag = True
        self.driver.create_volume_from_snapshot(volume_clone, snapvolume_paras)
        self.assertEqual(zte_pub.ZTE_SUCCESS, self.driver.result)

    def test_create_volume_from_snapshot_fail(self):
        self.driver.test_flag = False
        self.assertRaises(exception.CinderException,
                          self.driver.create_cloned_volume,
                          volume_clone, volume_paras)


class ZteISCSIDriverTestCase(ZteBaseDriverTestCase, test.TestCase):
    """Test ZTE iSCSI volume driver."""

    def __init__(self, *args, **kwargs):
        super(ZteISCSIDriverTestCase, self).__init__(*args, **kwargs)

    def setUp(self):
        super(ZteISCSIDriverTestCase, self).setUp()
        configuration = conf.Configuration(None)
        self.configuration = configuration

        self.configuration.zteControllerIP0 = '192.0.2.2'
        self.configuration.zteLocalIP = '192.0.2.8'
        self.configuration.zteUserName = 'root'
        self.configuration.zteUserPassword = 'root'
        self.configuration.zteChunkSize = 64
        self.configuration.zteAheadReadSize = 8
        self.configuration.zteCachePolicy = 65535
        self.configuration.zteSSDCacheSwitch = 0
        self.configuration.zteStoragePool = 'pool1,pool2,pool3'
        self.configuration.ztePoolVolAllocPolicy = 0
        self.configuration.ztePoolVolMovePolicy = 0
        self.configuration.ztePoolVolIsThin = 0
        self.configuration.ztePoolVolInitAllocedCapacity = 0
        self.configuration.ztePoolVolAlarmThreshold = 0
        self.configuration.ztePoolVolAlarmStopAllocFlag = 0

        self.driver = FakeZteISCSIDriver(configuration=self.configuration)
        self.driver.do_setup({})

    def test_get_volume_stats(self):
        stats = self.driver.get_volume_stats(True)
        self.assertEqual("ZTE", stats["vendor_name"])
        self.assertEqual("iSCSI", stats["storage_protocol"])
        self.assertEqual("V1.0", stats["driver_version"])
        self.assertLess(0, stats["total_capacity_gb"])

    def test_initialize_connection_success(self):
        self.driver.test_flag = True
        data = self.driver.initialize_connection(volume_paras, connector)
        properties = data['data']
        self.assertEqual("iscsi", data["driver_volume_type"])
        self.assertEqual('iqn.2099-01.cn.com.zte:usp.spr11-00:00:22:15',
                         properties["target_iqn"])
        self.assertEqual(3, properties["target_lun"])
        self.assertEqual('198.51.100.20:3260', properties["target_portal"])

    def test_initialize_connection_portexist(self):
        self.driver.portexist_flag = True
        data = self.driver.initialize_connection(volume_paras, connector)
        properties = data['data']
        self.assertEqual("iscsi", data["driver_volume_type"])
        self.assertEqual('iqn.2099-01.cn.com.zte:usp.spr11-00:00:22:15',
                         properties["target_iqn"])
        self.assertEqual(3, properties["target_lun"])
        self.assertEqual('198.51.100.20:3260', properties["target_portal"])

    def test_initialize_connection_hostexist(self):
        self.driver.hostexist_flag = True
        data = self.driver.initialize_connection(volume_paras, connector)

        properties = data['data']
        self.assertEqual("iscsi", data["driver_volume_type"])
        self.assertEqual('iqn.2099-01.cn.com.zte:usp.spr11-00:00:22:15',
                         properties["target_iqn"])
        self.assertEqual(3, properties["target_lun"])
        self.assertEqual('198.51.100.20:3260', properties["target_portal"])

    def test_initialize_connection_portexistother(self):
        self.driver.portexistother_flag = True
        self.assertRaises(exception.CinderException,
                          self.driver.initialize_connection,
                          volume_paras, connector)

    def test_initialize_connection_hostexistother(self):
        self.driver.hostexistother_flag = True
        self.assertRaises(exception.CinderException,
                          self.driver.initialize_connection,
                          volume_paras, connector)

    def test_initialize_connection_fail(self):
        self.driver.test_flag = False
        self.assertRaises(exception.CinderException,
                          self.driver.initialize_connection,
                          volume_paras, connector)

    def test_terminate_connection_success(self):
        self.driver.test_flag = True
        vol = {'name': 'volume-ee317512-f6a6-4284-a94e-5f4ac8783169'}
        self.driver.terminate_connection(vol, connector)
        self.assertEqual(zte_pub.ZTE_SUCCESS, self.driver.result)

    def test_terminate_connection_fail(self):
        self.driver.test_flag = False
        vol = {'name': 'volume-ee317512-f6a6-4284-a94e-5f4ac8783169'}
        self.assertRaises(exception.CinderException,
                          self.driver.terminate_connection, vol, connector)
