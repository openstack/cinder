# Copyright (c) 2012 - 2014 EMC Corporation, Inc.
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


import os

import mock

from cinder import exception
from cinder import test
from cinder.volume import configuration as conf
from cinder.volume.drivers.emc.emc_cli_iscsi import EMCCLIISCSIDriver
from cinder.volume.drivers.emc.emc_vnx_cli import EMCVnxCli
from cinder.volume import volume_types


class EMCVNXCLIDriverTestData():

    test_volume = {
        'name': 'vol1',
        'size': 1,
        'volume_name': 'vol1',
        'id': '1',
        'provider_auth': None,
        'project_id': 'project',
        'display_name': 'vol1',
        'display_description': 'test volume',
        'volume_type_id': None}
    test_volfromsnap = {
        'name': 'volfromsnap',
        'size': 1,
        'volume_name': 'volfromsnap',
        'id': '10',
        'provider_auth': None,
        'project_id': 'project',
        'display_name': 'volfromsnap',
        'display_description': 'test volume',
        'volume_type_id': None}
    test_volfromsnap_e = {
        'name': 'volfromsnap_e',
        'size': 1,
        'volume_name': 'volfromsnap_e',
        'id': '20',
        'provider_auth': None,
        'project_id': 'project',
        'display_name': 'volfromsnap_e',
        'display_description': 'test volume',
        'volume_type_id': None}
    test_failed_volume = {
        'name': 'failed_vol1',
        'size': 1,
        'volume_name': 'failed_vol1',
        'id': '4',
        'provider_auth': None,
        'project_id': 'project',
        'display_name': 'failed_vol',
        'display_description': 'test failed volume',
        'volume_type_id': None}
    test_snapshot = {
        'name': 'snapshot1',
        'size': 1,
        'id': '4444',
        'volume_name': 'vol-vol1',
        'volume_size': 1,
        'project_id': 'project'}
    test_failed_snapshot = {
        'name': 'failed_snapshot',
        'size': 1,
        'id': '5555',
        'volume_name': 'vol-vol1',
        'volume_size': 1,
        'project_id': 'project'}
    test_clone = {
        'name': 'clone1',
        'size': 1,
        'id': '20',
        'volume_name': 'clone1',
        'provider_auth': None,
        'project_id': 'project',
        'display_name': 'clone1',
        'display_description': 'volume created from snapshot',
        'volume_type_id': None}
    test_clone_e = {
        'name': 'clone1_e',
        'size': 1,
        'id': '28',
        'volume_name': 'clone1_e',
        'provider_auth': None,
        'project_id': 'project',
        'display_name': 'clone1_e',
        'display_description': 'volume created from snapshot',
        'volume_type_id': None}
    test_clone_src = {
        'name': 'clone1src',
        'size': 1,
        'id': '22',
        'volume_name': 'clone1src',
        'provider_auth': None,
        'project_id': 'project',
        'display_name': 'clone1src',
        'display_description': 'volume created from snapshot',
        'volume_type_id': None}
    connector = {
        'ip': '10.0.0.2',
        'initiator': 'iqn.1993-08.org.debian:01:222',
        'wwpns': ["123456789012345", "123456789054321"],
        'wwnns': ["223456789012345", "223456789054321"],
        'host': 'fakehost'}


class EMCVNXCLIDriverISCSITestCase(test.TestCase):

    def _fake_cli_executor(self, *cmd, **kwargv):
        # mock cli
        if cmd == ("storagepool", "-list",
                   "-name", "unit_test_pool", "-state"):
            return None, 0
        elif cmd == ('storagepool', '-list',
                     '-name', 'unit_test_pool', '-userCap', '-availableCap'):
            pool_details = "test\ntest\ntest\ntotal capacity:10000\n" + \
                "test\nfree capacity:1000\ntest\ntest"
            return pool_details, 0
        elif cmd == ('lun', '-create', '-type', 'NonThin',
                     '-capacity', 1, '-sq', 'gb',
                     '-poolName', 'unit_test_pool', '-name', 'vol1'):
            return None, 0
        elif cmd == ('lun', '-create', '-type', 'NonThin',
                     '-capacity', 1, '-sq', 'gb',
                     '-poolName', 'unit_test_pool', '-name', 'failed_vol1'):
            return None, 1023
        elif cmd == ('lun', '-create', '-type', 'Thin',
                     '-capacity', 1, '-sq', 'gb',
                     '-poolName', 'unit_test_pool', '-name', 'vol1'):
            return None, 0
        elif cmd == ('lun', '-list', '-name', 'vol1'):
            return "   10\nReady", 0
        elif cmd == ('lun', '-destroy', '-name', 'vol1',
                     '-forceDetach', '-o'):
            return "Lun deleted successfully", 0
        elif cmd == ('lun', '-destroy', '-name', 'failed_vol1',
                     '-forceDetach', '-o'):
            return "Lun deleted successfully", 1023
        elif cmd == ('lun', '-list', '-name', 'vol-vol1'):
            return "   16\n", 0
        elif cmd == ('snap', '-create', '-res', '16', '-name',
                     'snapshot1', '-allowReadWrite', 'yes'):
            return "Create Snap successfully", 0
        elif cmd == ('snap', '-create', '-res', '16', '-name',
                     'failed_snapshot', '-allowReadWrite', 'yes'):
            return "Create Snap failed", 1023
        elif cmd == ('snap', '-destroy', '-id', 'snapshot1', '-o'):
            return "Delete Snap successfully", 0
        elif cmd == ('lun', '-create', '-type', 'NonThin',
                     '-capacity', 1, '-sq', 'gb',
                     '-poolName', 'unit_test_pool', '-name',
                     'volfromsnapdest'):
            return "create temp volume successfully", 0
        elif cmd == ('lun', '-create', '-type', 'NonThin',
                     '-capacity', 1, '-sq', 'gb',
                     '-poolName', 'unit_test_pool', '-name',
                     'volfromsnap_edest'):
            return "create temp volume successfully", 0
        elif cmd == ('lun', '-create', '-type', 'Snap',
                     '-primaryLunName', 'vol-vol1', '-name', 'volfromsnap'):
            return "create mount point successfully", 0
        elif cmd == ('lun', '-create', '-type', 'Snap',
                     '-primaryLunName', 'vol-vol1', '-name', 'volfromsnap_e'):
            return "create mount point successfully", 0
        elif cmd == ('lun', '-attach', '-name', 'volfromsnap',
                     '-snapName', 'snapshot1'):
            return None, 0
        elif cmd == ('lun', '-attach', '-name', 'volfromsnap_e',
                     '-snapName', 'snapshot1'):
            return None, 0
        elif cmd == ('lun', '-list', '-name', 'volfromsnap'):
            return "   10\n", 0
        elif cmd == ('lun', '-list', '-name', 'volfromsnapdest'):
            return "   101\n", 0
        elif cmd == ('lun', '-list', '-name', 'volfromsnap_e'):
            return "   20\n", 0
        elif cmd == ('lun', '-list', '-name', 'volfromsnap_edest'):
            return "   201\n", 0
        elif cmd == ('migrate', '-start', '-source', '10', '-dest', '101',
                     '-rate', 'ASAP', '-o'):
            return None, 0
        elif cmd == ('migrate', '-start', '-source', '20', '-dest', '201',
                     '-rate', 'ASAP', '-o'):
            return None, 0
        elif cmd == ('lun', '-list', '-name', 'volfromsnap',
                     '-attachedSnapshot'):
            return "\n test \n :N/A", 0
        elif cmd == ('lun', '-list', '-name', 'volfromsnap_e',
                     '-attachedSnapshot'):
            return "\n test \n :N", 0
        elif cmd == ('snap', '-create', '-res', '22', '-name',
                     'clone1src-temp-snapshot', '-allowReadWrite', 'yes'):
            return "Create Snap successfully", 0
        elif cmd == ('lun', '-list', '-name', 'clone1src'):
            return "   22\n", 0
        elif cmd == ('lun', '-create', '-type', 'NonThin',
                     '-capacity', 1, '-sq', 'gb',
                     '-poolName', 'unit_test_pool', '-name', 'clone1dest'):
            return "create temp volume successfully", 0
        elif cmd == ('lun', '-create', '-type', 'Snap',
                     '-primaryLunName', 'clone1src', '-name', 'clone1'):
            return "create mount point successfully", 0
        elif cmd == ('lun', '-attach', '-name', 'clone1',
                     '-snapName', 'clone1src-temp-snapshot'):
            return 'create temp snap successfully', 0
        elif cmd == ('lun', '-list', '-name', 'clone1'):
            return "   30\n", 0
        elif cmd == ('lun', '-list', '-name', 'clone1dest'):
            return "   301\n", 0
        elif cmd == ('migrate', '-start', '-source', '30', '-dest', '301',
                     '-rate', 'ASAP', '-o'):
            return None, 0
        elif cmd == ('lun', '-list', '-name', 'clone1',
                     '-attachedSnapshot'):
            return "\n test \n :N/A", 0
        elif cmd == ('snap', '-destroy', '-id',
                     'clone1src-temp-snapshot', '-o'):
            return None, 0
        elif cmd == ('lun', '-create', '-type', 'NonThin',
                     '-capacity', 1, '-sq', 'gb',
                     '-poolName', 'unit_test_pool', '-name', 'clone1_edest'):
            return "create temp volume successfully", 0
        elif cmd == ('lun', '-create', '-type', 'Snap',
                     '-primaryLunName', 'clone1src', '-name', 'clone1_e'):
            return "create mount point successfully", 0
        elif cmd == ('lun', '-attach', '-name', 'clone1_e', '-snapName',
                     'clone1src-temp-snapshot'):
            return None, 0
        elif cmd == ('lun', '-list', '-name', 'clone1_e'):
            return "   40\n", 0
        elif cmd == ('lun', '-list', '-name', 'clone1_edest'):
            return "   401\n", 0
        elif cmd == ('migrate', '-start', '-source', '40', '-dest', '401',
                     '-rate', 'ASAP', '-o'):
            return None, 0
        elif cmd == ('lun', '-list', '-name', 'clone1_e',
                     '-attachedSnapshot'):
            return "\n test \n :N", 0
        elif cmd == ('lun', '-expand', '-name', 'vol1',
                     '-capacity', 2, '-sq', 'gb', '-o',
                     '-ignoreThresholds'):
            return "Expand volume successfully", 0
        elif cmd == ('lun', '-expand', '-name', 'failed_vol1',
                     '-capacity', 2, '-sq', 'gb', '-o',
                     '-ignoreThresholds'):
            return "Expand volume failed because it has snap", 97
        elif cmd == ('lun', '-expand', '-name', 'failed_vol1',
                     '-capacity', 3, '-sq', 'gb', '-o',
                     '-ignoreThresholds'):
            return "Expand volume failed", 1023
        elif cmd == ('storagegroup', '-list', '-gname',
                     'fakehost'):
            return '\nStorage Group Name:    fakehost' + \
                   '\nStorage Group UID:     78:47:C4:F2:CA:' + \
                   '\n\nHLU/ALU Pairs:\n\n  HLU Number     ' + \
                   'ALU Number\n  ----------     ----------\n' + \
                   '    10               64\nShareable:             YES\n', 0
        elif cmd == ('lun', '-list', '-l', '10', '-owner'):
            return '\n\nCurrent Owner:  SP A', 0
        elif cmd == ('storagegroup', '-addhlu', '-o', '-gname',
                     'fakehost', '-hlu', 1, '-alu', '10'):
            return None, 0
        elif cmd == ('connection', '-getport', '-sp', 'A'):
            return 'SP:  A\nPort ID:  5\nPort WWN:  iqn.1992-04.' + \
                   'com.emc:cx.fnm00124000215.a5\niSCSI Alias:  0215.a5\n', 0
        else:
            self.assertTrue(False)

    def setUp(self):
        # backup
        back_os_path_exists = os.path.exists
        self.addCleanup(self._restore, back_os_path_exists)
        super(EMCVNXCLIDriverISCSITestCase, self).setUp()
        self.configuration = conf.Configuration(None)
        self.configuration.append_config_values = mock.Mock(return_value=0)
        self.configuration.naviseccli_path = '/opt/Navisphere/bin/naviseccli'
        self.configuration.san_ip = '10.0.0.1'
        self.configuration.storage_vnx_pool_name = 'unit_test_pool'
        self.configuration.san_login = 'sysadmin'
        self.configuration.san_password = 'sysadmin'
        self.configuration.default_timeout = 0
        self.testData = EMCVNXCLIDriverTestData()
        self.navisecclicmd = '/opt/Navisphere/bin/naviseccli ' + \
            '-address 10.0.0.1 -user sysadmin -password sysadmin -scope 0 '
        os.path.exists = mock.Mock(return_value=1)
        EMCVnxCli._cli_execute = mock.Mock(side_effect=self._fake_cli_executor)
        self.driver = EMCCLIISCSIDriver(configuration=self.configuration)
        self.driver.cli.wait_interval = 0

    def _restore(self, back_os_path_exists):
        # recover
        os.path.exists = back_os_path_exists

    def test_create_destroy_volume_withoutExtraSpec(self):
        # case
        self.driver.create_volume(self.testData.test_volume)
        self.driver.delete_volume(self.testData.test_volume)
        expected = [mock.call('storagepool', '-list', '-name',
                              'unit_test_pool', '-state'),
                    mock.call('lun', '-create', '-type', 'NonThin',
                              '-capacity', 1, '-sq', 'gb', '-poolName',
                              'unit_test_pool', '-name', 'vol1'),
                    mock.call('lun', '-list', '-name', 'vol1'),
                    mock.call('lun', '-destroy', '-name', 'vol1',
                              '-forceDetach', '-o')]
        EMCVnxCli._cli_execute.assert_has_calls(expected)

    def test_create_destroy_volume_withExtraSpec(self):
        # mock
        extra_specs = {'storage:provisioning': 'Thin'}
        volume_types.get = mock.Mock(return_value=extra_specs)
        # case
        self.driver.create_volume(self.testData.test_volume)
        self.driver.delete_volume(self.testData.test_volume)
        expected = [mock.call('storagepool', '-list', '-name',
                              'unit_test_pool', '-state'),
                    mock.call('lun', '-create', '-type', 'NonThin',
                              '-capacity', 1, '-sq', 'gb', '-poolName',
                              'unit_test_pool', '-name', 'vol1'),
                    mock.call('lun', '-list', '-name', 'vol1'),
                    mock.call('lun', '-destroy', '-name', 'vol1',
                              '-forceDetach', '-o')]
        EMCVnxCli._cli_execute.assert_has_calls(expected)

    def test_get_volume_stats(self):
        # mock
        self.configuration.safe_get = mock.Mock(return_value=0)
        # case
        rc = self.driver.get_volume_stats(True)
        stats = {'volume_backend_name': 'EMCCLIISCSIDriver',
                 'free_capacity_gb': 1000.0,
                 'driver_version': '02.00.00', 'total_capacity_gb': 10000.0,
                 'reserved_percentage': 0, 'vendor_name': 'EMC',
                 'storage_protocol': 'iSCSI'}
        self.assertEqual(rc, stats)
        expected = [mock.call('storagepool', '-list', '-name',
                              'unit_test_pool', '-state'),
                    mock.call('storagepool', '-list', '-name',
                              'unit_test_pool', '-userCap', '-availableCap')]
        EMCVnxCli._cli_execute.assert_has_calls(expected)

    def test_create_destroy_volume_snapshot(self):
        # case
        self.driver.create_snapshot(self.testData.test_snapshot)
        self.driver.delete_snapshot(self.testData.test_snapshot)
        expected = [mock.call('storagepool', '-list', '-name',
                              'unit_test_pool', '-state'),
                    mock.call('lun', '-list', '-name', 'vol-vol1'),
                    mock.call('snap', '-create', '-res', '16', '-name',
                              'snapshot1', '-allowReadWrite', 'yes'),
                    mock.call('snap', '-destroy', '-id', 'snapshot1', '-o')]
        EMCVnxCli._cli_execute.assert_has_calls(expected)

    @mock.patch.object(
        EMCCLIISCSIDriver,
        '_do_iscsi_discovery',
        return_value=['10.0.0.3:3260,1 '
                      'iqn.1992-04.com.emc:cx.apm00123907237.a8',
                      '10.0.0.4:3260,2 '
                      'iqn.1992-04.com.emc:cx.apm00123907237.b8'])
    def test_initialize_connection(self, _mock_iscsi_discovery):
        # case
        rc = self.driver.initialize_connection(
            self.testData.test_volume,
            self.testData.connector)
        connect_info = {'driver_volume_type': 'iscsi', 'data':
                        {'target_lun': -1, 'volume_id': '1',
                         'target_iqn': 'iqn.1992-04.com.emc:' +
                         'cx.apm00123907237.b8',
                         'target_discovered': True,
                         'target_portal': '10.0.0.4:3260'}}
        self.assertEqual(rc, connect_info)
        expected = [mock.call('storagepool', '-list', '-name',
                              'unit_test_pool', '-state'),
                    mock.call('storagegroup', '-list', '-gname', 'fakehost'),
                    mock.call('lun', '-list', '-name', 'vol1'),
                    mock.call('lun', '-list', '-name', 'vol1'),
                    mock.call('storagegroup', '-list', '-gname', 'fakehost'),
                    mock.call('lun', '-list', '-l', '10', '-owner'),
                    mock.call('storagegroup', '-addhlu', '-o', '-gname',
                              'fakehost', '-hlu', 1, '-alu', '10'),
                    mock.call('lun', '-list', '-name', 'vol1'),
                    mock.call('storagegroup', '-list', '-gname', 'fakehost'),
                    mock.call('lun', '-list', '-l', '10', '-owner'),
                    mock.call('connection', '-getport', '-sp', 'A')]
        EMCVnxCli._cli_execute.assert_has_calls(expected)

    def test_terminate_connection(self):
        # case
        self.driver.terminate_connection(self.testData.test_volume,
                                         self.testData.connector)
        expected = [mock.call('storagepool', '-list', '-name',
                              'unit_test_pool', '-state'),
                    mock.call('storagegroup', '-list', '-gname', 'fakehost'),
                    mock.call('lun', '-list', '-name', 'vol1'),
                    mock.call('storagegroup', '-list', '-gname', 'fakehost'),
                    mock.call('lun', '-list', '-l', '10', '-owner')]
        EMCVnxCli._cli_execute.assert_has_calls(expected)

    def test_create_volume_failed(self):
        # case
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume,
                          self.testData.test_failed_volume)
        expected = [mock.call('storagepool', '-list', '-name',
                              'unit_test_pool', '-state'),
                    mock.call('lun', '-create', '-type', 'NonThin',
                              '-capacity', 1, '-sq', 'gb', '-poolName',
                              'unit_test_pool', '-name', 'failed_vol1')]
        EMCVnxCli._cli_execute.assert_has_calls(expected)

    def test_create_volume_snapshot_failed(self):
        # case
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_snapshot,
                          self.testData.test_failed_snapshot)
        expected = [mock.call('storagepool', '-list', '-name',
                              'unit_test_pool', '-state'),
                    mock.call('lun', '-list', '-name', 'vol-vol1'),
                    mock.call('snap', '-create', '-res', '16', '-name',
                              'failed_snapshot', '-allowReadWrite', 'yes')]
        EMCVnxCli._cli_execute.assert_has_calls(expected)

    def test_create_volume_from_snapshot(self):
        # case
        self.driver.create_volume_from_snapshot(self.testData.test_volfromsnap,
                                                self.testData.test_snapshot)
        expected = [mock.call('storagepool', '-list', '-name',
                              'unit_test_pool', '-state'),
                    mock.call('lun', '-create', '-type', 'NonThin',
                              '-capacity', 1, '-sq', 'gb', '-poolName',
                              'unit_test_pool', '-name', 'volfromsnapdest'),
                    mock.call('lun', '-create', '-type', 'Snap',
                              '-primaryLunName', 'vol-vol1', '-name',
                              'volfromsnap'),
                    mock.call('lun', '-attach', '-name', 'volfromsnap',
                              '-snapName', 'snapshot1'),
                    mock.call('lun', '-list', '-name', 'volfromsnap'),
                    mock.call('lun', '-list', '-name', 'volfromsnapdest'),
                    mock.call('migrate', '-start', '-source', '10', '-dest',
                              '101', '-rate', 'ASAP', '-o'),
                    mock.call('lun', '-list', '-name', 'volfromsnap',
                              '-attachedSnapshot')]
        EMCVnxCli._cli_execute.assert_has_calls(expected)

    def test_create_volume_from_snapshot_sync_failed(self):
        # case
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume_from_snapshot,
                          self.testData.test_volfromsnap_e,
                          self.testData.test_snapshot)
        expected = [mock.call('storagepool', '-list', '-name',
                              'unit_test_pool', '-state'),
                    mock.call('lun', '-create', '-type', 'NonThin',
                              '-capacity', 1, '-sq', 'gb', '-poolName',
                              'unit_test_pool', '-name', 'volfromsnap_edest'),
                    mock.call('lun', '-create', '-type', 'Snap',
                              '-primaryLunName', 'vol-vol1', '-name',
                              'volfromsnap_e'),
                    mock.call('lun', '-attach', '-name', 'volfromsnap_e',
                              '-snapName', 'snapshot1'),
                    mock.call('lun', '-list', '-name', 'volfromsnap_e'),
                    mock.call('lun', '-list', '-name', 'volfromsnap_edest'),
                    mock.call('migrate', '-start', '-source', '20', '-dest',
                              '201', '-rate', 'ASAP', '-o'),
                    mock.call('lun', '-list', '-name', 'volfromsnap_e',
                              '-attachedSnapshot')]
        EMCVnxCli._cli_execute.assert_has_calls(expected)

    def test_create_cloned_volume(self):
        # case
        self.driver.create_cloned_volume(self.testData.test_clone,
                                         self.testData.test_clone_src)
        expected = [mock.call('storagepool', '-list', '-name',
                              'unit_test_pool', '-state'),
                    mock.call('lun', '-list', '-name', 'clone1src'),
                    mock.call('snap', '-create', '-res', '22', '-name',
                              'clone1src-temp-snapshot', '-allowReadWrite',
                              'yes'),
                    mock.call('lun', '-create', '-type', 'NonThin',
                              '-capacity', 1, '-sq', 'gb', '-poolName',
                              'unit_test_pool', '-name', 'clone1dest'),
                    mock.call('lun', '-create', '-type', 'Snap',
                              '-primaryLunName', 'clone1src', '-name',
                              'clone1'),
                    mock.call('lun', '-attach', '-name', 'clone1',
                              '-snapName', 'clone1src-temp-snapshot'),
                    mock.call('lun', '-list', '-name', 'clone1'),
                    mock.call('lun', '-list', '-name', 'clone1dest'),
                    mock.call('migrate', '-start', '-source', '30', '-dest',
                              '301', '-rate', 'ASAP', '-o'),
                    mock.call('lun', '-list', '-name', 'clone1',
                              '-attachedSnapshot'),
                    mock.call('snap', '-destroy', '-id',
                              'clone1src-temp-snapshot', '-o')]
        EMCVnxCli._cli_execute.assert_has_calls(expected)

    def test_create_volume_clone_sync_failed(self):
        # case
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_cloned_volume,
                          self.testData.test_clone_e,
                          self.testData.test_clone_src)
        expected = [mock.call('storagepool', '-list', '-name',
                              'unit_test_pool', '-state'),
                    mock.call('lun', '-list', '-name', 'clone1src'),
                    mock.call('snap', '-create', '-res', '22', '-name',
                              'clone1src-temp-snapshot', '-allowReadWrite',
                              'yes'),
                    mock.call('lun', '-create', '-type', 'NonThin',
                              '-capacity', 1, '-sq', 'gb', '-poolName',
                              'unit_test_pool', '-name', 'clone1_edest'),
                    mock.call('lun', '-create', '-type', 'Snap',
                              '-primaryLunName', 'clone1src', '-name',
                              'clone1_e'),
                    mock.call('lun', '-attach', '-name', 'clone1_e',
                              '-snapName', 'clone1src-temp-snapshot'),
                    mock.call('lun', '-list', '-name', 'clone1_e'),
                    mock.call('lun', '-list', '-name', 'clone1_edest'),
                    mock.call('migrate', '-start', '-source', '40', '-dest',
                              '401', '-rate', 'ASAP', '-o'),
                    mock.call('lun', '-list', '-name', 'clone1_e',
                              '-attachedSnapshot')]
        EMCVnxCli._cli_execute.assert_has_calls(expected)

    def test_delete_volume_failed(self):
        # case
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.delete_volume,
                          self.testData.test_failed_volume)
        expected = [mock.call('storagepool', '-list', '-name',
                              'unit_test_pool', '-state'),
                    mock.call('lun', '-destroy', '-name', 'failed_vol1',
                              '-forceDetach', '-o')]
        EMCVnxCli._cli_execute.assert_has_calls(expected)

    def test_extend_volume(self):
        # case
        self.driver.extend_volume(self.testData.test_volume, 2)
        expected = [mock.call('storagepool', '-list', '-name',
                              'unit_test_pool', '-state'),
                    mock.call('lun', '-expand', '-name', 'vol1', '-capacity',
                              2, '-sq', 'gb', '-o', '-ignoreThresholds')]
        EMCVnxCli._cli_execute.assert_has_calls(expected)

    def test_extend_volume_has_snapshot(self):
        # case
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.extend_volume,
                          self.testData.test_failed_volume,
                          2)
        expected = [mock.call('storagepool', '-list', '-name',
                              'unit_test_pool', '-state'),
                    mock.call('lun', '-expand', '-name', 'failed_vol1',
                              '-capacity', 2, '-sq', 'gb', '-o',
                              '-ignoreThresholds')]
        EMCVnxCli._cli_execute.assert_has_calls(expected)

    def test_extend_volume_failed(self):
        # case
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.extend_volume,
                          self.testData.test_failed_volume,
                          3)
        expected = [mock.call('storagepool', '-list', '-name',
                              'unit_test_pool', '-state'),
                    mock.call('lun', '-expand', '-name', 'failed_vol1',
                              '-capacity', 3, '-sq', 'gb', '-o',
                              '-ignoreThresholds')]
        EMCVnxCli._cli_execute.assert_has_calls(expected)

    def test_create_remove_export(self):
        # case
        self.driver.create_export(None, self.testData.test_volume)
        self.driver.remove_export(None, self.testData.test_volume)
        expected = [mock.call('storagepool', '-list', '-name',
                              'unit_test_pool', '-state'),
                    mock.call('lun', '-list', '-name', 'vol1')]
        EMCVnxCli._cli_execute.assert_has_calls(expected)
