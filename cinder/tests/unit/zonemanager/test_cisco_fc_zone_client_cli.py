#    (c) Copyright 2014 Cisco Systems Inc.
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


"""Unit tests for Cisco fc zone client cli."""

import time

import mock
from oslo_concurrency import processutils
from six.moves import range

from cinder import exception
from cinder import test
from cinder.zonemanager.drivers.cisco \
    import cisco_fc_zone_client_cli as cli
import cinder.zonemanager.drivers.cisco.fc_zone_constants as ZoneConstant

nsshow = '20:1a:00:05:1e:e8:e3:29'
switch_data = ['VSAN 303\n',
               '----------------------------------------------------------\n',
               'FCID     TYPE  PWWN           (VENDOR)    FC4-TYPE:FEATURE\n',
               '----------------------------------------------------------\n',
               '0x030001 N     20:1a:00:05:1e:e8:e3:29 (Cisco)        ipfc\n',
               '0x030101 NL    10:00:00:00:77:99:60:2c (Interphase)\n',
               '0x030200    NL    10:00:00:49:c9:28:c7:01\n']

cfgactv = ['zoneset name OpenStack_Cfg vsan 303\n',
           'zone name openstack50060b0000c26604201900051ee8e329 vsan 303\n',
           'pwwn 50:06:0b:00:00:c2:66:04\n',
           'pwwn 20:19:00:05:1e:e8:e3:29\n']

active_zoneset = {
    'zones': {
        'openstack50060b0000c26604201900051ee8e329':
        ['50:06:0b:00:00:c2:66:04', '20:19:00:05:1e:e8:e3:29']},
    'active_zone_config': 'OpenStack_Cfg'}

zoning_status_data_basic = [
    'VSAN: 303 default-zone: deny distribute: active only Interop: default\n',
    '    mode: basic merge-control: allow\n',
    '    session: none\n',
    '    hard-zoning: enabled broadcast: unsupported\n',
    '    smart-zoning: disabled\n',
    '    rscn-format: fabric-address\n',
    'Default zone:\n',
    '    qos: none broadcast: unsupported ronly: unsupported\n',
    'Full Zoning Database :\n',
    '    DB size: 220 bytes\n',
    '    Zonesets:2  Zones:2 Aliases: 0\n',
    'Active Zoning Database :\n',
    '    DB size: 80 bytes\n',
    '    Name: test-zs-test  Zonesets:1  Zones:1\n',
    'Status:\n']

zoning_status_basic = {'mode': 'basic', 'session': 'none'}

zoning_status_data_enhanced_nosess = [
    'VSAN: 303 default-zone: deny distribute: active only Interop: default\n',
    '    mode: enhanced merge-control: allow\n',
    '    session: none\n',
    '    hard-zoning: enabled broadcast: unsupported\n',
    '    smart-zoning: disabled\n',
    '    rscn-format: fabric-address\n',
    'Default zone:\n',
    '    qos: none broadcast: unsupported ronly: unsupported\n',
    'Full Zoning Database :\n',
    '    DB size: 220 bytes\n',
    '    Zonesets:2  Zones:2 Aliases: 0\n',
    'Active Zoning Database :\n',
    '    DB size: 80 bytes\n',
    '    Name: test-zs-test  Zonesets:1  Zones:1\n',
    'Status:\n']

zoning_status_enhanced_nosess = {'mode': 'enhanced', 'session': 'none'}

zoning_status_data_enhanced_sess = [
    'VSAN: 303 default-zone: deny distribute: active only Interop: default\n',
    '    mode: enhanced merge-control: allow\n',
    '    session: otherthannone\n',
    '    hard-zoning: enabled broadcast: unsupported\n',
    '    smart-zoning: disabled\n',
    '    rscn-format: fabric-address\n',
    'Default zone:\n',
    '    qos: none broadcast: unsupported ronly: unsupported\n',
    'Full Zoning Database :\n',
    '    DB size: 220 bytes\n',
    '    Zonesets:2  Zones:2 Aliases: 0\n',
    'Active Zoning Database :\n',
    '    DB size: 80 bytes\n',
    '    Name: test-zs-test  Zonesets:1  Zones:1\n',
    'Status:\n']

zoning_status_enhanced_sess = {'mode': 'enhanced', 'session': 'otherthannone'}

active_zoneset_multiple_zones = {
    'zones': {
        'openstack50060b0000c26604201900051ee8e329':
        ['50:06:0b:00:00:c2:66:04', '20:19:00:05:1e:e8:e3:29'],
        'openstack10000012345678902001009876543210':
        ['50:06:0b:00:00:c2:66:02', '20:19:00:05:1e:e8:e3:27']},
    'active_zone_config': 'OpenStack_Cfg'}

new_zone = {'openstack10000012345678902001009876543210':
            ['10:00:00:12:34:56:78:90', '20:01:00:98:76:54:32:10']}

new_zones = {'openstack10000012345678902001009876543210':
             ['10:00:00:12:34:56:78:90', '20:01:00:98:76:54:32:10'],
             'openstack10000011111111112001001111111111':
             ['10:00:00:11:11:11:11:11', '20:01:00:11:11:11:11:11']}

zone_names_to_delete = 'openstack50060b0000c26604201900051ee8e329'


class TestCiscoFCZoneClientCLI(cli.CiscoFCZoneClientCLI, test.TestCase):

    def setUp(self):
        super(TestCiscoFCZoneClientCLI, self).setUp()
        self.fabric_vsan = '303'

    # override some of the functions
    def __init__(self, *args, **kwargs):
        test.TestCase.__init__(self, *args, **kwargs)

    @mock.patch.object(cli.CiscoFCZoneClientCLI, '_get_switch_info')
    def test_get_active_zone_set(self, get_switch_info_mock):
        cmd_list = [ZoneConstant.GET_ACTIVE_ZONE_CFG, self.fabric_vsan,
                    ' | no-more']
        get_switch_info_mock.return_value = cfgactv
        active_zoneset_returned = self.get_active_zone_set()
        get_switch_info_mock.assert_called_once_with(cmd_list)
        self.assertDictEqual(active_zoneset, active_zoneset_returned)

    @mock.patch.object(cli.CiscoFCZoneClientCLI, '_run_ssh')
    def test_get_active_zone_set_ssh_error(self, run_ssh_mock):
        run_ssh_mock.side_effect = processutils.ProcessExecutionError
        self.assertRaises(exception.CiscoZoningCliException,
                          self.get_active_zone_set)

    @mock.patch.object(cli.CiscoFCZoneClientCLI, '_get_switch_info')
    def test_get_zoning_status_basic(self, get_zoning_status_mock):
        cmd_list = [ZoneConstant.GET_ZONE_STATUS, self.fabric_vsan]
        get_zoning_status_mock.return_value = zoning_status_data_basic
        zoning_status_returned = self.get_zoning_status()
        get_zoning_status_mock.assert_called_once_with(cmd_list)
        self.assertDictEqual(zoning_status_basic, zoning_status_returned)

    @mock.patch.object(cli.CiscoFCZoneClientCLI, '_get_switch_info')
    def test_get_zoning_status_enhanced_nosess(self, get_zoning_status_mock):
        cmd_list = [ZoneConstant.GET_ZONE_STATUS, self.fabric_vsan]
        get_zoning_status_mock.return_value =\
            zoning_status_data_enhanced_nosess
        zoning_status_returned = self.get_zoning_status()
        get_zoning_status_mock.assert_called_once_with(cmd_list)
        self.assertDictEqual(zoning_status_enhanced_nosess,
                             zoning_status_returned)

    @mock.patch.object(cli.CiscoFCZoneClientCLI, '_get_switch_info')
    def test_get_zoning_status_enhanced_sess(self, get_zoning_status_mock):
        cmd_list = [ZoneConstant.GET_ZONE_STATUS, self.fabric_vsan]
        get_zoning_status_mock.return_value = zoning_status_data_enhanced_sess
        zoning_status_returned = self.get_zoning_status()
        get_zoning_status_mock.assert_called_once_with(cmd_list)
        self.assertDictEqual(zoning_status_enhanced_sess,
                             zoning_status_returned)

    @mock.patch.object(cli.CiscoFCZoneClientCLI, '_get_switch_info')
    def test_get_nameserver_info(self, get_switch_info_mock):
        ns_info_list = []
        ns_info_list_expected = ['20:1a:00:05:1e:e8:e3:29']
        get_switch_info_mock.return_value = (switch_data)
        ns_info_list = self.get_nameserver_info()
        self.assertEqual(ns_info_list_expected, ns_info_list)

    @mock.patch.object(cli.CiscoFCZoneClientCLI, '_run_ssh')
    def test_get_nameserver_info_ssh_error(self, run_ssh_mock):
        run_ssh_mock.side_effect = processutils.ProcessExecutionError
        self.assertRaises(exception.CiscoZoningCliException,
                          self.get_nameserver_info)

    @mock.patch.object(cli.CiscoFCZoneClientCLI, '_run_ssh')
    def test__cfg_save(self, run_ssh_mock):
        cmd_list = ['copy', 'running-config', 'startup-config']
        self._cfg_save()
        run_ssh_mock.assert_called_once_with(cmd_list, True)

    @mock.patch.object(cli.CiscoFCZoneClientCLI, '_run_ssh')
    @mock.patch.object(time, 'sleep')
    def test__cfg_save_with_retry(self, mock_sleep, run_ssh_mock):
        cmd_list = ['copy', 'running-config', 'startup-config']
        run_ssh_mock.side_effect = [
            processutils.ProcessExecutionError,
            ('', None)
        ]

        self._cfg_save()

        self.assertEqual(2, run_ssh_mock.call_count)
        run_ssh_mock.assert_has_calls([
            mock.call(cmd_list, True),
            mock.call(cmd_list, True)
        ])

    @mock.patch.object(cli.CiscoFCZoneClientCLI, '_run_ssh')
    @mock.patch.object(time, 'sleep')
    def test__cfg_save_with_error(self, mock_sleep, run_ssh_mock):
        cmd_list = ['copy', 'running-config', 'startup-config']
        run_ssh_mock.side_effect = processutils.ProcessExecutionError

        self.assertRaises(processutils.ProcessExecutionError, self._cfg_save)

        expected_num_calls = 5
        expected_calls = []
        for i in range(expected_num_calls):
            expected_calls.append(mock.call(cmd_list, True))

        self.assertEqual(expected_num_calls, run_ssh_mock.call_count)
        run_ssh_mock.assert_has_calls(expected_calls)

    @mock.patch.object(cli.CiscoFCZoneClientCLI, '_run_ssh')
    def test__get_switch_info(self, run_ssh_mock):
        cmd_list = [ZoneConstant.FCNS_SHOW, self.fabric_vsan]
        nsshow_list = [nsshow]
        run_ssh_mock.return_value = (Stream(nsshow), Stream())
        switch_data = self._get_switch_info(cmd_list)
        self.assertEqual(nsshow_list, switch_data)
        run_ssh_mock.assert_called_once_with(cmd_list, True)

    @mock.patch.object(cli.CiscoFCZoneClientCLI, '_ssh_execute')
    @mock.patch.object(cli.CiscoFCZoneClientCLI, '_cfg_save')
    def test__update_zones_add(self, cfg_save_mock, ssh_execute_mock):
        self.update_zones(new_zone, False, self.fabric_vsan,
                          ZoneConstant.ZONE_ADD, active_zoneset_multiple_zones,
                          zoning_status_basic)
        ssh_cmd = [['conf'],
                   ['zoneset', 'name', 'OpenStack_Cfg', 'vsan',
                    self.fabric_vsan],
                   ['zone', 'name',
                    'openstack10000012345678902001009876543210'],
                   ['member', 'pwwn', '10:00:00:12:34:56:78:90'],
                   ['member', 'pwwn', '20:01:00:98:76:54:32:10'],
                   ['end']]

        self.assertEqual(1, cfg_save_mock.call_count)
        ssh_execute_mock.assert_called_once_with(ssh_cmd, True, 1)

    @mock.patch.object(cli.CiscoFCZoneClientCLI, '_ssh_execute')
    @mock.patch.object(cli.CiscoFCZoneClientCLI, '_cfg_save')
    def test__update_zones_remove(self, cfg_save_mock, ssh_execute_mock):
        self.update_zones(new_zone, False, self.fabric_vsan,
                          ZoneConstant.ZONE_REMOVE,
                          active_zoneset_multiple_zones,
                          zoning_status_basic)
        ssh_cmd = [['conf'],
                   ['zoneset', 'name', 'OpenStack_Cfg', 'vsan',
                    self.fabric_vsan],
                   ['zone', 'name',
                    'openstack10000012345678902001009876543210'],
                   ['no', 'member', 'pwwn', '10:00:00:12:34:56:78:90'],
                   ['no', 'member', 'pwwn', '20:01:00:98:76:54:32:10'],
                   ['end']]

        self.assertEqual(1, cfg_save_mock.call_count)
        ssh_execute_mock.assert_called_once_with(ssh_cmd, True, 1)

    def test__parse_ns_output(self):
        return_wwn_list = []
        expected_wwn_list = ['20:1a:00:05:1e:e8:e3:29']
        return_wwn_list = self._parse_ns_output(switch_data)
        self.assertEqual(expected_wwn_list, return_wwn_list)


class TestCiscoFCZoneClientCLISSH(test.TestCase):

    def setUp(self):
        super(TestCiscoFCZoneClientCLISSH, self).setUp()
        self.client = cli.CiscoFCZoneClientCLI(None, None, None, None, None)
        self.client.sshpool = mock.MagicMock()
        self.mock_ssh = self.client.sshpool.item().__enter__()

    @mock.patch('oslo_concurrency.processutils.ssh_execute')
    def test__run_ssh(self, mock_execute):
        mock_execute.return_value = 'ssh output'
        ret = self.client._run_ssh(['cat', 'foo'])
        self.assertEqual('ssh output', ret)
        mock_execute.assert_called_once_with(self.mock_ssh,
                                             'cat foo',
                                             check_exit_code=True)

    @mock.patch('oslo_concurrency.processutils.ssh_execute')
    def test__run_ssh_with_error(self, mock_execute):
        mock_execute.side_effect = processutils.ProcessExecutionError()
        self.assertRaises(processutils.ProcessExecutionError,
                          self.client._run_ssh,
                          ['cat', 'foo'])


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
