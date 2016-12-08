# Copyright (c) 2013 - 2016 Huawei Technologies Co., Ltd.
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
Unit Tests for Huawei FusionStorage drivers.
"""

import mock

from cinder import test
from cinder import utils
from cinder.volume.drivers.fusionstorage import fspythonapi


class FSPythonApiTestCase(test.TestCase):

    def setUp(self):
        super(FSPythonApiTestCase, self).setUp()
        self.api = fspythonapi.FSPythonApi()

    @mock.patch.object(fspythonapi.FSPythonApi, 'get_ip_port')
    @mock.patch.object(fspythonapi.FSPythonApi, 'get_manage_ip')
    @mock.patch.object(utils, 'execute')
    def test_start_execute_cmd(self, mock_execute,
                               mock_get_manage_ip, mock_get_ip_port):
        result1 = ['result=0\ndesc=success\n', '']
        result2 = ['result=50150007\ndesc=volume does not exist\n', '']
        result3 = ['result=50150008\ndesc=volume is being deleted\n', '']
        result4 = ['result=50\ndesc=exception\n', '']
        cmd = 'abcdef'

        mock_get_ip_port.return_value = ['127.0.0.1', '128.0.0.1']
        mock_get_manage_ip.return_value = '127.0.0.1'

        mock_execute.return_value = result1
        retval = self.api.start_execute_cmd(cmd, 0)
        self.assertEqual('result=0', retval)

        mock_execute.return_value = result2
        retval = self.api.start_execute_cmd(cmd, 0)
        self.assertEqual('result=0', retval)

        mock_execute.return_value = result3
        retval = self.api.start_execute_cmd(cmd, 0)
        self.assertEqual('result=0', retval)

        mock_execute.return_value = result4
        retval = self.api.start_execute_cmd(cmd, 0)
        self.assertEqual('result=50', retval)

        mock_execute.return_value = result1
        retval = self.api.start_execute_cmd(cmd, 1)
        self.assertEqual(['result=0', 'desc=success', ''], retval)

        mock_execute.return_value = result2
        retval = self.api.start_execute_cmd(cmd, 1)
        self.assertEqual('result=0', retval)

        mock_execute.return_value = result3
        retval = self.api.start_execute_cmd(cmd, 1)
        self.assertEqual('result=0', retval)

        mock_execute.return_value = result4
        retval = self.api.start_execute_cmd(cmd, 1)
        self.assertEqual(['result=50', 'desc=exception', ''], retval)

    @mock.patch.object(fspythonapi.FSPythonApi, 'start_execute_cmd')
    def test_create_volume(self, mock_start_execute):
        mock_start_execute.side_effect = ['result=0\n',
                                          'result=50150007\n', None]

        retval = self.api.create_volume('volume_name', 'pool_id-123', 1024, 0)
        self.assertEqual(0, retval)

        retval = self.api.create_volume('volume_name', 'pool_id-123', 1024, 0)
        self.assertEqual('50150007\n', retval)

        retval = self.api.create_volume('volume_name', 'pool_id-123', 1024, 0)
        self.assertEqual(1, retval)

    @mock.patch.object(fspythonapi.FSPythonApi, 'start_execute_cmd')
    def test_extend_volume(self, mock_start_execute):
        mock_start_execute.side_effect = ['result=0\n',
                                          'result=50150007\n', None]

        retval = self.api.extend_volume('volume_name', 1024)
        self.assertEqual(0, retval)

        retval = self.api.extend_volume('volume_name', 1024)
        self.assertEqual('50150007\n', retval)

        retval = self.api.extend_volume('volume_name', 1024)
        self.assertEqual(1, retval)

    @mock.patch.object(fspythonapi.FSPythonApi, 'start_execute_cmd')
    def test_create_volume_from_snap(self, mock_start_execute):
        mock_start_execute.side_effect = ['result=0\n',
                                          'result=50150007\n', None]

        retval = self.api.create_volume_from_snap('volume_name', 1024,
                                                  'snap_name')
        self.assertEqual(0, retval)

        retval = self.api.create_volume_from_snap('volume_name', 1024,
                                                  'snap_name')
        self.assertEqual('50150007\n', retval)

        retval = self.api.create_volume_from_snap('volume_name', 1024,
                                                  'snap_name')
        self.assertEqual(1, retval)

    @mock.patch.object(fspythonapi.FSPythonApi, 'start_execute_cmd')
    def test_create_fullvol_from_snap(self, mock_start_execute):
        mock_start_execute.side_effect = ['result=0\n',
                                          'result=50150007\n', None]

        retval = self.api.create_fullvol_from_snap('volume_name', 'snap_name')
        self.assertEqual(0, retval)

        retval = self.api.create_fullvol_from_snap('volume_name', 'snap_name')
        self.assertEqual('50150007\n', retval)

        retval = self.api.create_fullvol_from_snap('volume_name', 'snap_name')
        self.assertEqual(1, retval)

    @mock.patch.object(fspythonapi.FSPythonApi, 'create_snapshot')
    @mock.patch.object(fspythonapi.FSPythonApi, 'create_volume')
    @mock.patch.object(fspythonapi.FSPythonApi, 'delete_snapshot')
    @mock.patch.object(fspythonapi.FSPythonApi, 'delete_volume')
    @mock.patch.object(fspythonapi.FSPythonApi, 'create_fullvol_from_snap')
    def test_create_volume_from_volume(self, mock_create_fullvol,
                                       mock_delete_volume, mock_delete_snap,
                                       mock_create_volume, mock_create_snap):
        mock_create_snap.return_value = 0
        mock_create_volume.return_value = 0
        mock_create_fullvol.return_value = 0

        retval = self.api.create_volume_from_volume('vol_name', 1024,
                                                    'src_vol_name')
        self.assertEqual(0, retval)

        mock_create_snap.return_value = 1
        retval = self.api.create_volume_from_volume('vol_name', 1024,
                                                    'src_vol_name')
        self.assertEqual(1, retval)

        mock_create_snap.return_value = 0
        mock_create_volume.return_value = 1
        retval = self.api.create_volume_from_volume('vol_name', 1024,
                                                    'src_vol_name')
        self.assertEqual(1, retval)

        mock_create_volume.return_value = 0
        self.api.create_fullvol_from_snap.return_value = 1
        retval = self.api.create_volume_from_volume('vol_name', 1024,
                                                    'src_vol_name')
        self.assertEqual(1, retval)

    @mock.patch.object(fspythonapi.FSPythonApi, 'create_snapshot')
    @mock.patch.object(fspythonapi.FSPythonApi, 'create_volume_from_snap')
    def test_create_clone_volume_from_volume(self, mock_volume, mock_snap):
        mock_snap.side_effect = [0, 1]
        mock_volume.side_effect = [0, 1]
        retval = self.api.create_clone_volume_from_volume('vol_name', 1024,
                                                          'src_vol_name')
        self.assertEqual(0, retval)
        retval = self.api.create_clone_volume_from_volume('vol_name', 1024,
                                                          'src_vol_name')
        self.assertEqual(1, retval)

    def test_volume_info_analyze_success(self):
        vol_info = ('vol_name=vol1,father_name=vol1_father,'
                    'status=available,vol_size=1024,real_size=1024,'
                    'pool_id=pool1,create_time=01/01/2015')
        vol_info_res = {'result': 0, 'vol_name': 'vol1',
                        'father_name': 'vol1_father',
                        'status': 'available', 'vol_size': '1024',
                        'real_size': '1024', 'pool_id': 'pool1',
                        'create_time': '01/01/2015'}

        retval = self.api.volume_info_analyze(vol_info)
        self.assertEqual(vol_info_res, retval)

    def test_volume_info_analyze_fail(self):
        vol_info = ''
        vol_info_res = {'result': 1, 'vol_name': '', 'father_name': '',
                        'status': '', 'vol_size': '', 'real_size': '',
                        'pool_id': '', 'create_time': ''}
        retval = self.api.volume_info_analyze(vol_info)
        self.assertEqual(vol_info_res, retval)

    @mock.patch.object(fspythonapi.FSPythonApi, 'start_execute_cmd')
    @mock.patch.object(fspythonapi.FSPythonApi, 'volume_info_analyze')
    @mock.patch.object(fspythonapi.FSPythonApi, 'delete_snapshot')
    def test_query_volume(self, mock_delete, mock_analyze, mock_execute):
        exec_result = ['result=0\n',
                       'vol_name=vol1,father_name=vol1_father,status=0,' +
                       'vol_size=1024,real_size=1024,pool_id=pool1,' +
                       'create_time=01/01/2015']
        query_result = {'result': 0, 'vol_name': 'vol1',
                        'father_name': 'vol1_father', 'status': '0',
                        'vol_size': '1024', 'real_size': '1024',
                        'pool_id': 'pool1', 'create_time': '01/01/2015'}
        mock_delete.return_value = 0
        mock_execute.return_value = exec_result
        mock_analyze.return_value = query_result
        retval = self.api.query_volume('vol1')
        self.assertEqual(query_result, retval)

        exec_result = ['result=0\n',
                       'vol_name=vol1,father_name=vol1_father,status=1,' +
                       'vol_size=1024,real_size=1024,pool_id=pool1,' +
                       'create_time=01/01/2015']
        query_result = {'result': 0, 'vol_name': 'vol1',
                        'father_name': 'vol1_father', 'status': '1',
                        'vol_size': '1024', 'real_size': '1024',
                        'pool_id': 'pool1', 'create_time': '01/01/2015'}
        mock_delete.return_value = 0
        mock_execute.return_value = exec_result
        mock_analyze.return_value = query_result
        retval = self.api.query_volume('vol1')
        self.assertEqual(query_result, retval)

        vol_info_failure = 'result=32500000\n'
        failure_res = {'result': 1, 'vol_name': '', 'father_name': '',
                       'status': '', 'vol_size': '', 'real_size': '',
                       'pool_id': '', 'create_time': ''}
        mock_execute.return_value = vol_info_failure
        retval = self.api.query_volume('vol1')
        self.assertEqual(failure_res, retval)

        vol_info_failure = None
        failure_res = {'result': 1, 'vol_name': '', 'father_name': '',
                       'status': '', 'vol_size': '', 'real_size': '',
                       'pool_id': '', 'create_time': ''}

        mock_execute.return_value = vol_info_failure
        retval = self.api.query_volume('vol1')
        self.assertEqual(failure_res, retval)

    @mock.patch.object(fspythonapi.FSPythonApi, 'start_execute_cmd')
    def test_delete_volume(self, mock_execute):
        mock_execute.side_effect = ['result=0\n',
                                    'result=50150007\n', None]

        retval = self.api.delete_volume('volume_name')
        self.assertEqual(0, retval)

        retval = self.api.delete_volume('volume_name')
        self.assertEqual('50150007\n', retval)

        retval = self.api.delete_volume('volume_name')
        self.assertEqual(1, retval)

    @mock.patch.object(fspythonapi.FSPythonApi, 'start_execute_cmd')
    def test_create_snapshot(self, mock_execute):
        mock_execute.side_effect = ['result=0\n',
                                    'result=50150007\n', None]

        retval = self.api.create_snapshot('snap_name', 'vol_name', 0)
        self.assertEqual(0, retval)

        retval = self.api.create_snapshot('snap_name', 'vol_name', 0)
        self.assertEqual('50150007\n', retval)

        retval = self.api.create_snapshot('snap_name', 'vol_name', 0)
        self.assertEqual(1, retval)

    def test_snap_info_analyze_success(self):
        snap_info = ('snap_name=snap1,father_name=snap1_father,status=0,'
                     'snap_size=1024,real_size=1024,pool_id=pool1,'
                     'delete_priority=1,create_time=01/01/2015')
        snap_info_res = {'result': 0, 'snap_name': 'snap1',
                         'father_name': 'snap1_father', 'status': '0',
                         'snap_size': '1024', 'real_size': '1024',
                         'pool_id': 'pool1', 'delete_priority': '1',
                         'create_time': '01/01/2015'}

        retval = self.api.snap_info_analyze(snap_info)
        self.assertEqual(snap_info_res, retval)

    def test_snap_info_analyze_fail(self):
        snap_info = ''
        snap_info_res = {'result': 1, 'snap_name': '', 'father_name': '',
                         'status': '', 'snap_size': '', 'real_size': '',
                         'pool_id': '', 'delete_priority': '',
                         'create_time': ''}
        retval = self.api.snap_info_analyze(snap_info)
        self.assertEqual(snap_info_res, retval)

    @mock.patch.object(fspythonapi.FSPythonApi, 'start_execute_cmd')
    def test_query_snap(self, mock_execute):
        exec_result = ['result=0\n',
                       'snap_name=snap1,father_name=snap1_father,status=0,' +
                       'snap_size=1024,real_size=1024,pool_id=pool1,' +
                       'delete_priority=1,create_time=01/01/2015']
        query_result = {'result': 0, 'snap_name': 'snap1',
                        'father_name': 'snap1_father', 'status': '0',
                        'snap_size': '1024', 'real_size': '1024',
                        'pool_id': 'pool1', 'delete_priority': '1',
                        'create_time': '01/01/2015'}
        mock_execute.return_value = exec_result
        retval = self.api.query_snap('snap1')
        self.assertEqual(query_result, retval)

        exec_result = ['result=50150007\n']
        qurey_result = {'result': '50150007\n', 'snap_name': '',
                        'father_name': '', 'status': '', 'snap_size': '',
                        'real_size': '', 'pool_id': '',
                        'delete_priority': '', 'create_time': ''}
        mock_execute.return_value = exec_result
        retval = self.api.query_snap('snap1')
        self.assertEqual(qurey_result, retval)

        exec_result = ''
        query_result = {'result': 1, 'snap_name': '', 'father_name': '',
                        'status': '', 'snap_size': '', 'real_size': '',
                        'pool_id': '', 'delete_priority': '',
                        'create_time': ''}
        mock_execute.return_value = exec_result
        retval = self.api.query_snap('snap1')
        self.assertEqual(query_result, retval)

    @mock.patch.object(fspythonapi.FSPythonApi, 'start_execute_cmd')
    def test_delete_snapshot(self, mock_execute):
        mock_execute.side_effect = ['result=0\n',
                                    'result=50150007\n', None]

        retval = self.api.delete_snapshot('snap_name')
        self.assertEqual(0, retval)

        retval = self.api.delete_snapshot('snap_name')
        self.assertEqual('50150007\n', retval)

        retval = self.api.delete_snapshot('snap_name')
        self.assertEqual(1, retval)

    def test_pool_info_analyze(self):
        pool_info = 'pool_id=pool100,total_capacity=1024,' + \
                    'used_capacity=500,alloc_capacity=500'
        analyze_res = {'result': 0, 'pool_id': 'pool100',
                       'total_capacity': '1024', 'used_capacity': '500',
                       'alloc_capacity': '500'}

        retval = self.api.pool_info_analyze(pool_info)
        self.assertEqual(analyze_res, retval)

        pool_info = ''
        analyze_res = {'result': 1, 'pool_id': '', 'total_capacity': '',
                       'used_capacity': '', 'alloc_capacity': ''}
        retval = self.api.pool_info_analyze(pool_info)
        self.assertEqual(analyze_res, retval)

    @mock.patch.object(fspythonapi.FSPythonApi, 'start_execute_cmd')
    def test_query_pool_info(self, mock_execute):
        exec_result = ['result=0\n',
                       'pool_id=0,total_capacity=1024,' +
                       'used_capacity=500,alloc_capacity=500\n']
        query_result = {'result': 0, 'pool_id': '0',
                        'total_capacity': '1024', 'used_capacity': '500',
                        'alloc_capacity': '500'}
        mock_execute.return_value = exec_result
        retval = self.api.query_pool_info('0')
        self.assertEqual(query_result, retval)

        exec_result = ['result=51050008\n']
        query_result = {'result': '51050008\n', 'pool_id': '',
                        'total_capacity': '', 'used_capacity': '',
                        'alloc_capacity': ''}
        mock_execute.return_value = exec_result
        retval = self.api.query_pool_info('0')
        self.assertEqual(query_result, retval)

        exec_result = ''
        query_result = {'result': 1, 'pool_id': '', 'total_capacity': '',
                        'used_capacity': '', 'alloc_capacity': ''}
        mock_execute.return_value = exec_result
        retval = self.api.query_pool_info('0')
        self.assertEqual(query_result, retval)

    @mock.patch.object(fspythonapi.FSPythonApi, 'start_execute_cmd')
    def test_query_pool_type(self, mock_execute):
        exec_result = ['result=0\n',
                       'pool_id=0,total_capacity=1024,' +
                       'used_capacity=500,alloc_capacity=500\n']
        query_result = (0, [{'result': 0,
                             'pool_id': '0', 'total_capacity': '1024',
                             'used_capacity': '500', 'alloc_capacity': '500'}])

        mock_execute.return_value = exec_result
        retval = self.api.query_pool_type('sata2copy')
        self.assertEqual(query_result, retval)

        exec_result = ['result=0\n',
                       'pool_id=0,total_capacity=1024,' +
                       'used_capacity=500,alloc_capacity=500\n',
                       'pool_id=1,total_capacity=2048,' +
                       'used_capacity=500,alloc_capacity=500\n']
        query_result = (0, [{'result': 0, 'pool_id': '0',
                             'total_capacity': '1024', 'used_capacity': '500',
                             'alloc_capacity': '500'},
                            {'result': 0, 'pool_id': '1',
                             'total_capacity': '2048', 'used_capacity': '500',
                             'alloc_capacity': '500'}])
        mock_execute.return_value = exec_result
        retval = self.api.query_pool_type('sata2copy')
        self.assertEqual(query_result, retval)

        exec_result = ['result=51010015\n']
        query_result = (51010015, [])
        mock_execute.return_value = exec_result
        retval = self.api.query_pool_type('sata2copy')
        self.assertEqual(query_result, retval)

        exec_result = ''
        query_result = (0, [])
        mock_execute.return_value = exec_result
        retval = self.api.query_pool_type('sata2copy')
        self.assertEqual(query_result, retval)

    @mock.patch.object(fspythonapi.FSPythonApi, 'start_execute_cmd')
    def test_query_dsware_version(self, mock_execute):
        mock_execute.side_effect = ['result=0\n', 'result=50500001\n',
                                    'result=50150007\n', None]

        retval = self.api.query_dsware_version()
        self.assertEqual(0, retval)

        retval = self.api.query_dsware_version()
        self.assertEqual(1, retval)

        retval = self.api.query_dsware_version()
        self.assertEqual('50150007\n', retval)

        retval = self.api.query_dsware_version()
        self.assertEqual(2, retval)
