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


"""Unit tests for Cisco fc san lookup service."""
from unittest import mock

from oslo_config import cfg

from cinder import exception
from cinder.tests.unit import test
from cinder.volume import configuration as conf
import cinder.zonemanager.drivers.cisco.cisco_fc_san_lookup_service \
    as cisco_lookup
import cinder.zonemanager.drivers.cisco.fc_zone_constants as ZoneConstant
from cinder.zonemanager import utils as zm_utils

nsshow = '20:1a:00:05:1e:e8:e3:29'
switch_data = ['VSAN 304\n',
               '------------------------------------------------------\n',
               'FCID        TYPE  PWWN                    (VENDOR)    \n',
               '------------------------------------------------------\n',
               '0x030001    N     20:1a:00:05:1e:e8:e3:29 (Cisco) ipfc\n',
               '0x030101    NL    10:00:00:00:77:99:60:2c (Interphase)\n',
               '0x030200    N     10:00:00:49:c9:28:c7:01\n']

nsshow_data = ['10:00:8c:7c:ff:52:3b:01', '20:24:00:02:ac:00:0a:50']

_device_map_to_verify = {
    'CISCO_FAB_2': {
        'initiator_port_wwn_list': ['10008c7cff523b01'],
        'target_port_wwn_list': ['20240002ac000a50']}}


class TestCiscoFCSanLookupService(cisco_lookup.CiscoFCSanLookupService,
                                  test.TestCase):

    def setUp(self):
        super(TestCiscoFCSanLookupService, self).setUp()
        self.configuration = conf.Configuration(None)
        self.configuration.set_default('fc_fabric_names', 'CISCO_FAB_2',
                                       'fc-zone-manager')
        self.configuration.fc_fabric_names = 'CISCO_FAB_2'
        self.create_configuration()
        self.fabric_vsan = '304'

    # override some of the functions
    def __init__(self, *args, **kwargs):
        test.TestCase.__init__(self, *args, **kwargs)

    def create_configuration(self):
        fc_fabric_opts = []
        fc_fabric_opts.append(cfg.StrOpt('cisco_fc_fabric_address',
                                         default='172.24.173.142', help=''))
        fc_fabric_opts.append(cfg.StrOpt('cisco_fc_fabric_user',
                                         default='admin', help=''))
        fc_fabric_opts.append(cfg.StrOpt('cisco_fc_fabric_password',
                                         default='admin1234', help='',
                                         secret=True))
        fc_fabric_opts.append(cfg.PortOpt('cisco_fc_fabric_port',
                                          default=22, help=''))
        fc_fabric_opts.append(cfg.StrOpt('cisco_zoning_vsan',
                                         default='304', help=''))
        config = conf.Configuration(fc_fabric_opts, 'CISCO_FAB_2')
        self.fabric_configs = {'CISCO_FAB_2': config}

    @mock.patch.object(cisco_lookup.CiscoFCSanLookupService,
                       'get_nameserver_info')
    def test_get_device_mapping_from_network(self, get_nameserver_info_mock):
        initiator_list = ['10008c7cff523b01']
        target_list = ['20240002ac000a50', '20240002ac000a40']
        get_nameserver_info_mock.return_value = (nsshow_data)
        device_map = self.get_device_mapping_from_network(
            initiator_list, target_list)
        self.assertDictEqual(_device_map_to_verify, device_map)

    @mock.patch.object(cisco_lookup.CiscoFCSanLookupService,
                       '_get_switch_info')
    def test_get_nameserver_info(self, get_switch_data_mock):
        ns_info_list = []
        ns_info_list_expected = ['20:1a:00:05:1e:e8:e3:29',
                                 '10:00:00:49:c9:28:c7:01']
        get_switch_data_mock.return_value = (switch_data)
        ns_info_list = self.get_nameserver_info('304')
        self.assertEqual(ns_info_list_expected, ns_info_list)

    def test_parse_ns_output(self):
        invalid_switch_data = [' N 011a00;20:1a:00:05:1e:e8:e3:29']
        return_wwn_list = []
        expected_wwn_list = ['20:1a:00:05:1e:e8:e3:29',
                             '10:00:00:49:c9:28:c7:01']
        return_wwn_list = self._parse_ns_output(switch_data)
        self.assertEqual(expected_wwn_list, return_wwn_list)
        self.assertRaises(exception.InvalidParameterValue,
                          self._parse_ns_output, invalid_switch_data)

    def test_get_formatted_wwn(self):
        wwn_list = ['10008c7cff523b01']
        return_wwn_list = []
        expected_wwn_list = ['10:00:8c:7c:ff:52:3b:01']
        return_wwn_list.append(zm_utils.get_formatted_wwn(wwn_list[0]))
        self.assertEqual(expected_wwn_list, return_wwn_list)

    @mock.patch.object(cisco_lookup.CiscoFCSanLookupService,
                       '_run_ssh')
    def test__get_switch_info(self, run_ssh_mock):
        cmd_list = [ZoneConstant.FCNS_SHOW, self.fabric_vsan,
                    ' | no-more']
        nsshow_list = [nsshow]
        run_ssh_mock.return_value = (Stream(nsshow), Stream())
        switch_data = self._get_switch_info(cmd_list)
        self.assertEqual(nsshow_list, switch_data)
        run_ssh_mock.assert_called_once_with(cmd_list, True, 1)


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
