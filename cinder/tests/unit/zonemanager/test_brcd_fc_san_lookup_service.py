#    (c) Copyright 2014 Brocade Communications Systems Inc.
#    All Rights Reserved.
#
#    Copyright 2014 OpenStack Foundation
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


"""Unit tests for brcd fc san lookup service."""

import mock
from oslo_concurrency import processutils as putils
from oslo_config import cfg

from cinder import exception
from cinder import ssh_utils
from cinder import test
from cinder.volume import configuration as conf
import cinder.zonemanager.drivers.brocade.brcd_fc_san_lookup_service \
    as brcd_lookup
from cinder.zonemanager.drivers.brocade import fc_zone_constants


parsed_switch_port_wwns = ['20:1a:00:05:1e:e8:e3:29',
                           '10:00:00:90:fa:34:40:f6']
switch_data = ("""
 Type Pid    COS     PortName                NodeName                 TTL(sec)
 N    011a00;    2,3;    %(port_1)s;    20:1a:00:05:1e:e8:e3:29;    na
    FC4s: FCP
    PortSymb: [26] "222222 - 1:1:1 - LPe12442"
    NodeSymb: [32] "SomeSym 7211"
    Fabric Port Name: 20:1a:00:05:1e:e8:e3:29
    Permanent Port Name: 22:22:00:22:ac:00:bc:b0
    Port Index: 0
    Share Area: No
    Device Shared in Other AD: No
    Redirect: No
    Partial: No
    LSAN: No
 N    010100;    2,3;    %(port_2)s;    20:00:00:00:af:00:00:af;     na
    FC4s: FCP
    PortSymb: [26] "333333 - 1:1:1 - LPe12442"
    NodeSymb: [32] "SomeSym 2222"
    Fabric Port Name: 10:00:00:90:fa:34:40:f6
    Permanent Port Name: 22:22:00:22:ac:00:bc:b0
    Port Index: 0
    Share Area: No
    Device Shared in Other AD: No
    Redirect: No
    Partial: No
    LSAN: No""" % {'port_1': parsed_switch_port_wwns[0],
                   'port_2': parsed_switch_port_wwns[1]})

_device_map_to_verify = {
    'BRCD_FAB_2': {
        'initiator_port_wwn_list': [parsed_switch_port_wwns[1].replace(':',
                                                                       '')],
        'target_port_wwn_list': [parsed_switch_port_wwns[0].replace(':', '')]}}


class TestBrcdFCSanLookupService(brcd_lookup.BrcdFCSanLookupService,
                                 test.TestCase):

    def setUp(self):
        super(TestBrcdFCSanLookupService, self).setUp()
        self.configuration = conf.Configuration(None)
        self.configuration.set_default('fc_fabric_names', 'BRCD_FAB_2',
                                       'fc-zone-manager')
        self.configuration.fc_fabric_names = 'BRCD_FAB_2'
        self.create_configuration()

    # override some of the functions
    def __init__(self, *args, **kwargs):
        test.TestCase.__init__(self, *args, **kwargs)

    def create_configuration(self):
        fc_fabric_opts = []
        fc_fabric_opts.append(cfg.StrOpt('fc_fabric_address',
                                         default='10.24.49.100', help=''))
        fc_fabric_opts.append(cfg.StrOpt('fc_fabric_user',
                                         default='admin', help=''))
        fc_fabric_opts.append(cfg.StrOpt('fc_fabric_password',
                                         default='password', help='',
                                         secret=True))
        fc_fabric_opts.append(cfg.IntOpt('fc_fabric_port',
                                         default=22, help=''))
        fc_fabric_opts.append(cfg.StrOpt('principal_switch_wwn',
                                         default='100000051e55a100', help=''))
        config = conf.Configuration(fc_fabric_opts, 'BRCD_FAB_2')
        self.fabric_configs = {'BRCD_FAB_2': config}

    @mock.patch.object(brcd_lookup.BrcdFCSanLookupService,
                       'get_nameserver_info')
    @mock.patch('cinder.zonemanager.drivers.brocade.brcd_fc_san_lookup_service'
                '.ssh_utils.SSHPool')
    def test_get_device_mapping_from_network(self, mock_ssh_pool,
                                             get_nameserver_info_mock):
        initiator_list = [parsed_switch_port_wwns[1]]
        target_list = [parsed_switch_port_wwns[0], '20240002ac000a40']
        get_nameserver_info_mock.return_value = parsed_switch_port_wwns
        device_map = self.get_device_mapping_from_network(
            initiator_list, target_list)
        self.assertDictMatch(device_map, _device_map_to_verify)

    @mock.patch.object(brcd_lookup.BrcdFCSanLookupService, '_get_switch_data')
    def test_get_nameserver_info(self, get_switch_data_mock):
        ns_info_list = []

        get_switch_data_mock.return_value = (switch_data)
        # get_switch_data will be called twice with the results appended
        ns_info_list_expected = (parsed_switch_port_wwns +
                                 parsed_switch_port_wwns)

        ns_info_list = self.get_nameserver_info(None)
        self.assertEqual(ns_info_list_expected, ns_info_list)

    @mock.patch.object(putils, 'ssh_execute', return_value=(switch_data, ''))
    @mock.patch.object(ssh_utils.SSHPool, 'item')
    def test__get_switch_data(self, ssh_pool_mock, ssh_execute_mock):
        actual_switch_data = self._get_switch_data(ssh_pool_mock,
                                                   fc_zone_constants.NS_SHOW)
        self.assertEqual(actual_switch_data, switch_data)
        ssh_execute_mock.side_effect = putils.ProcessExecutionError()
        self.assertRaises(exception.FCSanLookupServiceException,
                          self._get_switch_data, ssh_pool_mock,
                          fc_zone_constants.NS_SHOW)

    def test__parse_ns_output(self):
        invalid_switch_data = ' N 011a00;20:1a:00:05:1e:e8:e3:29'
        return_wwn_list = []
        return_wwn_list = self._parse_ns_output(switch_data)
        self.assertEqual(parsed_switch_port_wwns, return_wwn_list)
        self.assertRaises(exception.InvalidParameterValue,
                          self._parse_ns_output, invalid_switch_data)

    def test_get_formatted_wwn(self):
        wwn_list = ['10008c7cff523b01']
        return_wwn_list = []
        expected_wwn_list = ['10:00:8c:7c:ff:52:3b:01']
        return_wwn_list.append(self.get_formatted_wwn(wwn_list[0]))
        self.assertEqual(expected_wwn_list, return_wwn_list)
