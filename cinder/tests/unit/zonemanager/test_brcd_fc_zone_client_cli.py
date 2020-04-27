#    (c) Copyright 2016 Brocade Communications Systems Inc.
#    All Rights Reserved.
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
#


"""Unit tests for brcd fc zone client cli."""
from unittest import mock

from oslo_concurrency import processutils

from cinder import exception
from cinder.tests.unit import test
from cinder.zonemanager.drivers.brocade import (brcd_fc_zone_client_cli
                                                as client_cli)
from cinder.zonemanager.drivers.brocade import exception as b_exception
import cinder.zonemanager.drivers.brocade.fc_zone_constants as zone_constant


nsshow = '20:1a:00:05:1e:e8:e3:29'
switch_data = [' N 011a00;2,3;20:1a:00:05:1e:e8:e3:29;\
                 20:1a:00:05:1e:e8:e3:29;na',
               '    Fabric Port Name: 20:1a:00:05:1e:e8:e3:29']
cfgactvshow = ['Effective configuration:\n',
               ' cfg:\tOpenStack_Cfg\t\n',
               ' zone:\topenstack50060b0000c26604201900051ee8e329\t\n',
               '\t\t50:06:0b:00:00:c2:66:04\n',
               '\t\t20:19:00:05:1e:e8:e3:29\n']
active_zoneset = {
    'zones': {
        'openstack50060b0000c26604201900051ee8e329':
        ['50:06:0b:00:00:c2:66:04', '20:19:00:05:1e:e8:e3:29']},
    'active_zone_config': 'OpenStack_Cfg'}
active_zoneset_multiple_zones = {
    'zones': {
        'openstack50060b0000c26604201900051ee8e329':
        ['50:06:0b:00:00:c2:66:04', '20:19:00:05:1e:e8:e3:29'],
        'openstack50060b0000c26602201900051ee8e327':
        ['50:06:0b:00:00:c2:66:02', '20:19:00:05:1e:e8:e3:27']},
    'active_zone_config': 'OpenStack_Cfg'}
new_zone_memb_same = {
    'openstack50060b0000c26604201900051ee8e329':
    ['50:06:0b:00:00:c2:66:04', '20:19:00:05:1e:e8:e3:29']}
new_zone_memb_not_same = {
    'openstack50060b0000c26604201900051ee8e330':
    ['50:06:0b:00:00:c2:66:04', '20:19:00:05:1e:e8:e3:30']}
new_zone = {'openstack10000012345678902001009876543210':
            ['10:00:00:12:34:56:78:90', '20:01:00:98:76:54:32:10']}
new_zones = {'openstack10000012345678902001009876543210':
             ['10:00:00:12:34:56:78:90', '20:01:00:98:76:54:32:10'],
             'openstack10000011111111112001001111111111':
             ['10:00:00:11:11:11:11:11', '20:01:00:11:11:11:11:11']}
zone_names_to_delete = 'openstack50060b0000c26604201900051ee8e329'
supported_firmware = ['Kernel: 2.6', 'Fabric OS:  v7.0.1']
unsupported_firmware = ['Fabric OS:  v6.2.1']


class TestBrcdFCZoneClientCLI(client_cli.BrcdFCZoneClientCLI, test.TestCase):

    # override some of the functions
    def __init__(self, *args, **kwargs):
        test.TestCase.__init__(self, *args, **kwargs)

    @mock.patch.object(client_cli.BrcdFCZoneClientCLI, '_get_switch_info')
    def test_get_active_zone_set(self, get_switch_info_mock):
        cmd_list = [zone_constant.GET_ACTIVE_ZONE_CFG]
        get_switch_info_mock.return_value = cfgactvshow
        active_zoneset_returned = self.get_active_zone_set()
        get_switch_info_mock.assert_called_once_with(cmd_list)
        self.assertDictEqual(active_zoneset, active_zoneset_returned)

    @mock.patch.object(client_cli.BrcdFCZoneClientCLI, '_run_ssh')
    def test_get_active_zone_set_ssh_error(self, run_ssh_mock):
        run_ssh_mock.side_effect = processutils.ProcessExecutionError
        self.assertRaises(b_exception.BrocadeZoningCliException,
                          self.get_active_zone_set)

    @mock.patch.object(client_cli.BrcdFCZoneClientCLI, 'get_active_zone_set')
    @mock.patch.object(client_cli.BrcdFCZoneClientCLI, 'apply_zone_change')
    @mock.patch.object(client_cli.BrcdFCZoneClientCLI, '_cfg_save')
    def test_add_zones_new_zone_no_activate(self, cfg_save_mock,
                                            apply_zone_change_mock,
                                            get_active_zs_mock):
        get_active_zs_mock.return_value = active_zoneset
        self.add_zones(new_zones, False, None)
        self.assertEqual(1, get_active_zs_mock.call_count)
        self.assertEqual(3, apply_zone_change_mock.call_count)
        cfg_save_mock.assert_called_once_with()

    @mock.patch.object(client_cli.BrcdFCZoneClientCLI, 'get_active_zone_set')
    @mock.patch.object(client_cli.BrcdFCZoneClientCLI, 'apply_zone_change')
    @mock.patch.object(client_cli.BrcdFCZoneClientCLI, 'activate_zoneset')
    def test_add_zones_new_zone_activate(self, activate_zoneset_mock,
                                         apply_zone_change_mock,
                                         get_active_zs_mock):
        get_active_zs_mock.return_value = active_zoneset
        self.add_zones(new_zone, True, active_zoneset)
        self.assertEqual(2, apply_zone_change_mock.call_count)
        activate_zoneset_mock.assert_called_once_with(
            active_zoneset['active_zone_config'])

    @mock.patch.object(client_cli.BrcdFCZoneClientCLI, 'get_active_zone_set')
    @mock.patch.object(client_cli.BrcdFCZoneClientCLI, 'activate_zoneset')
    @mock.patch.object(client_cli.BrcdFCZoneClientCLI, 'apply_zone_change')
    def test_update_zone_exists_memb_same(self, apply_zone_change_mock,
                                          activate_zoneset_mock,
                                          get_active_zs_mock):
        get_active_zs_mock.return_value = active_zoneset
        self.update_zones(new_zone_memb_same, True, zone_constant.ZONE_ADD,
                          active_zoneset)
        self.assertEqual(1, apply_zone_change_mock.call_count)

    @mock.patch.object(client_cli.BrcdFCZoneClientCLI, 'get_active_zone_set')
    @mock.patch.object(client_cli.BrcdFCZoneClientCLI, 'activate_zoneset')
    @mock.patch.object(client_cli.BrcdFCZoneClientCLI, 'apply_zone_change')
    def test_update_zone_exists_memb_not_same(self, apply_zone_change_mock,
                                              activate_zoneset_mock,
                                              get_active_zs_mock):
        get_active_zs_mock.return_value = active_zoneset
        self.update_zones(new_zone_memb_not_same, True,
                          zone_constant.ZONE_ADD, active_zoneset)
        self.assertEqual(1, apply_zone_change_mock.call_count)

    @mock.patch.object(client_cli.BrcdFCZoneClientCLI, 'get_active_zone_set')
    @mock.patch.object(client_cli.BrcdFCZoneClientCLI, 'activate_zoneset')
    @mock.patch.object(client_cli.BrcdFCZoneClientCLI, 'apply_zone_change')
    def test_add_zone_all_exists_memb_not_same(self, apply_zone_change_mock,
                                               activate_zoneset_mock,
                                               get_active_zs_mock):

        self.add_zones(new_zone_memb_not_same, True, active_zoneset)
        call_args = apply_zone_change_mock.call_args[0][0]
        self.assertEqual(0, get_active_zs_mock.call_count)
        self.assertEqual(2, apply_zone_change_mock.call_count)
        self.assertIn(zone_constant.CFG_ADD.strip(), call_args)

    @mock.patch.object(client_cli.BrcdFCZoneClientCLI, '_ssh_execute')
    def test_activate_zoneset(self, ssh_execute_mock):
        ssh_execute_mock.return_value = True
        return_value = self.activate_zoneset('zoneset1')
        self.assertTrue(return_value)

    @mock.patch.object(client_cli.BrcdFCZoneClientCLI, '_ssh_execute')
    def test_deactivate_zoneset(self, ssh_execute_mock):
        ssh_execute_mock.return_value = True
        return_value = self.deactivate_zoneset()
        self.assertTrue(return_value)

    @mock.patch.object(client_cli.BrcdFCZoneClientCLI, 'apply_zone_change')
    @mock.patch.object(client_cli.BrcdFCZoneClientCLI, '_cfg_save')
    def test_delete_zones_activate_false(self, cfg_save_mock,
                                         apply_zone_change_mock):
        with mock.patch.object(self, '_zone_delete') as zone_delete_mock:
            self.delete_zones(zone_names_to_delete, False,
                              active_zoneset_multiple_zones)
            self.assertEqual(1, apply_zone_change_mock.call_count)
            zone_delete_mock.assert_called_once_with(zone_names_to_delete)
            cfg_save_mock.assert_called_once_with()

    @mock.patch.object(client_cli.BrcdFCZoneClientCLI, 'apply_zone_change')
    @mock.patch.object(client_cli.BrcdFCZoneClientCLI, 'activate_zoneset')
    def test_delete_zones_activate_true(self, activate_zs_mock,
                                        apply_zone_change_mock):
        with mock.patch.object(self, '_zone_delete') \
                as zone_delete_mock:
            self.delete_zones(zone_names_to_delete, True,
                              active_zoneset_multiple_zones)
            self.assertEqual(1, apply_zone_change_mock.call_count)
            zone_delete_mock.assert_called_once_with(zone_names_to_delete)
            activate_zs_mock.assert_called_once_with(
                active_zoneset['active_zone_config'])

    @mock.patch.object(client_cli.BrcdFCZoneClientCLI, '_get_switch_info')
    def test_get_nameserver_info(self, get_switch_info_mock):
        ns_info_list_expected = ['20:1a:00:05:1e:e8:e3:29']
        get_switch_info_mock.return_value = (switch_data)
        ns_info_list = self.get_nameserver_info()
        self.assertEqual(ns_info_list_expected, ns_info_list)

    @mock.patch.object(client_cli.BrcdFCZoneClientCLI, '_run_ssh')
    def test_get_nameserver_info_ssh_error(self, run_ssh_mock):
        run_ssh_mock.side_effect = processutils.ProcessExecutionError
        self.assertRaises(b_exception.BrocadeZoningCliException,
                          self.get_nameserver_info)

    @mock.patch.object(client_cli.BrcdFCZoneClientCLI, '_ssh_execute')
    def test__cfg_save(self, ssh_execute_mock):
        cmd_list = [zone_constant.CFG_SAVE]
        self._cfg_save()
        ssh_execute_mock.assert_called_once_with(cmd_list, True, 1)

    @mock.patch.object(client_cli.BrcdFCZoneClientCLI, 'apply_zone_change')
    def test__zone_delete(self, apply_zone_change_mock):
        zone_name = 'testzone'
        cmd_list = ['zonedelete', '"testzone"']
        self._zone_delete(zone_name)
        apply_zone_change_mock.assert_called_once_with(cmd_list)

    @mock.patch.object(client_cli.BrcdFCZoneClientCLI, 'apply_zone_change')
    def test__cfg_trans_abort(self, apply_zone_change_mock):
        cmd_list = [zone_constant.CFG_ZONE_TRANS_ABORT]
        with mock.patch.object(self, '_is_trans_abortable') \
                as is_trans_abortable_mock:
            is_trans_abortable_mock.return_value = True
            self._cfg_trans_abort()
            is_trans_abortable_mock.assert_called_once_with()
            apply_zone_change_mock.assert_called_once_with(cmd_list)

    @mock.patch.object(client_cli.BrcdFCZoneClientCLI, '_run_ssh')
    def test__is_trans_abortable_true(self, run_ssh_mock):
        cmd_list = [zone_constant.CFG_SHOW_TRANS]
        run_ssh_mock.return_value = (Stream(zone_constant.TRANS_ABORTABLE),
                                     None)
        data = self._is_trans_abortable()
        self.assertTrue(data)
        run_ssh_mock.assert_called_once_with(cmd_list, True, 1)

    @mock.patch.object(client_cli.BrcdFCZoneClientCLI, '_run_ssh')
    def test__is_trans_abortable_ssh_error(self, run_ssh_mock):
        run_ssh_mock.return_value = (Stream(), Stream())
        self.assertRaises(b_exception.BrocadeZoningCliException,
                          self._is_trans_abortable)

    @mock.patch.object(client_cli.BrcdFCZoneClientCLI, '_run_ssh')
    def test__is_trans_abortable_false(self, run_ssh_mock):
        cmd_list = [zone_constant.CFG_SHOW_TRANS]
        cfgtransshow = 'There is no outstanding zoning transaction'
        run_ssh_mock.return_value = (Stream(cfgtransshow), None)
        data = self._is_trans_abortable()
        self.assertFalse(data)
        run_ssh_mock.assert_called_once_with(cmd_list, True, 1)

    @mock.patch.object(client_cli.BrcdFCZoneClientCLI, '_run_ssh')
    def test_apply_zone_change(self, run_ssh_mock):
        cmd_list = [zone_constant.CFG_SAVE]
        run_ssh_mock.return_value = (None, None)
        self.apply_zone_change(cmd_list)
        run_ssh_mock.assert_called_once_with(cmd_list, True, 1)

    @mock.patch.object(client_cli.BrcdFCZoneClientCLI, '_run_ssh')
    def test__get_switch_info(self, run_ssh_mock):
        cmd_list = [zone_constant.NS_SHOW]
        nsshow_list = [nsshow]
        run_ssh_mock.return_value = (Stream(nsshow), Stream())
        switch_data = self._get_switch_info(cmd_list)
        self.assertEqual(nsshow_list, switch_data)
        run_ssh_mock.assert_called_once_with(cmd_list, True, 1)

    def test__parse_ns_output(self):
        invalid_switch_data = [' N 011a00;20:1a:00:05:1e:e8:e3:29']
        expected_wwn_list = ['20:1a:00:05:1e:e8:e3:29']
        return_wwn_list = self._parse_ns_output(switch_data)
        self.assertEqual(expected_wwn_list, return_wwn_list)
        self.assertRaises(exception.InvalidParameterValue,
                          self._parse_ns_output, invalid_switch_data)

    @mock.patch.object(client_cli.BrcdFCZoneClientCLI, '_execute_shell_cmd')
    def test_is_supported_firmware(self, exec_shell_cmd_mock):
        exec_shell_cmd_mock.return_value = (supported_firmware, None)
        self.assertTrue(self.is_supported_firmware())

    @mock.patch.object(client_cli.BrcdFCZoneClientCLI, '_execute_shell_cmd')
    def test_is_supported_firmware_invalid(self, exec_shell_cmd_mock):
        exec_shell_cmd_mock.return_value = (unsupported_firmware, None)
        self.assertFalse(self.is_supported_firmware())

    @mock.patch.object(client_cli.BrcdFCZoneClientCLI, '_execute_shell_cmd')
    def test_is_supported_firmware_no_ssh_response(self, exec_shell_cmd_mock):
        exec_shell_cmd_mock.return_value = (None, Stream())
        self.assertFalse(self.is_supported_firmware())

    @mock.patch.object(client_cli.BrcdFCZoneClientCLI, '_execute_shell_cmd')
    def test_is_supported_firmware_ssh_error(self, exec_shell_cmd_mock):
        exec_shell_cmd_mock.side_effect = processutils.ProcessExecutionError
        self.assertRaises(b_exception.BrocadeZoningCliException,
                          self.is_supported_firmware)


class Channel(object):
    def recv_exit_status(self):
        return 0


class Stream(object):
    def __init__(self, buffer=''):
        self.buffer = buffer
        self.channel = Channel()

    def readlines(self):
        return self.buffer

    def splitlines(self):
        return self.buffer.splitlines()

    def close(self):
        pass

    def flush(self):
        self.buffer = ''
