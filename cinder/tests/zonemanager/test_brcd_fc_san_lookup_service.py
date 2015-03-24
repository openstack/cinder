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
from oslo_config import cfg
from oslo_log import log as logging
import paramiko

from cinder import exception
from cinder import test
from cinder.volume import configuration as conf
import cinder.zonemanager.drivers.brocade.brcd_fc_san_lookup_service \
    as brcd_lookup
from cinder.zonemanager.drivers.brocade import fc_zone_constants

LOG = logging.getLogger(__name__)

nsshow = '20:1a:00:05:1e:e8:e3:29'
switch_data = [' N 011a00;2,3;20:1a:00:05:1e:e8:e3:29;\
                 20:1a:00:05:1e:e8:e3:29;na']
nsshow_data = ['10:00:8c:7c:ff:52:3b:01', '20:24:00:02:ac:00:0a:50']
_device_map_to_verify = {
    'BRCD_FAB_2': {
        'initiator_port_wwn_list': ['10008c7cff523b01'],
        'target_port_wwn_list': ['20240002ac000a50']}}


class TestBrcdFCSanLookupService(brcd_lookup.BrcdFCSanLookupService,
                                 test.TestCase):

    def setUp(self):
        super(TestBrcdFCSanLookupService, self).setUp()
        self.client = paramiko.SSHClient()
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

    @mock.patch.object(paramiko.hostkeys.HostKeys, 'load')
    def test_create_ssh_client(self, load_mock):
        mock_args = {}
        mock_args['known_hosts_file'] = 'dummy_host_key_file'
        mock_args['missing_key_policy'] = paramiko.RejectPolicy()
        ssh_client = self.create_ssh_client(**mock_args)
        self.assertEqual(ssh_client._host_keys_filename, 'dummy_host_key_file')
        self.assertTrue(isinstance(ssh_client._policy, paramiko.RejectPolicy))
        mock_args = {}
        ssh_client = self.create_ssh_client(**mock_args)
        self.assertIsNone(ssh_client._host_keys_filename)
        self.assertTrue(isinstance(ssh_client._policy, paramiko.WarningPolicy))

    @mock.patch.object(brcd_lookup.BrcdFCSanLookupService,
                       'get_nameserver_info')
    def test_get_device_mapping_from_network(self, get_nameserver_info_mock):
        initiator_list = ['10008c7cff523b01']
        target_list = ['20240002ac000a50', '20240002ac000a40']
        with mock.patch.object(self.client, 'connect'):
            get_nameserver_info_mock.return_value = (nsshow_data)
            device_map = self.get_device_mapping_from_network(
                initiator_list, target_list)
            self.assertDictMatch(device_map, _device_map_to_verify)

    @mock.patch.object(brcd_lookup.BrcdFCSanLookupService, '_get_switch_data')
    def test_get_nameserver_info(self, get_switch_data_mock):
        ns_info_list = []
        ns_info_list_expected = ['20:1a:00:05:1e:e8:e3:29',
                                 '20:1a:00:05:1e:e8:e3:29']
        get_switch_data_mock.return_value = (switch_data)
        ns_info_list = self.get_nameserver_info()
        self.assertEqual(ns_info_list, ns_info_list_expected)

    def test__get_switch_data(self):
        cmd = fc_zone_constants.NS_SHOW

        with mock.patch.object(self.client, 'exec_command') \
                as exec_command_mock:
            exec_command_mock.return_value = (Stream(),
                                              Stream(nsshow),
                                              Stream())
            switch_data = self._get_switch_data(cmd)
            self.assertEqual(switch_data, nsshow)
            exec_command_mock.assert_called_once_with(cmd)

    def test__parse_ns_output(self):
        invalid_switch_data = [' N 011a00;20:1a:00:05:1e:e8:e3:29']
        return_wwn_list = []
        expected_wwn_list = ['20:1a:00:05:1e:e8:e3:29']
        return_wwn_list = self._parse_ns_output(switch_data)
        self.assertEqual(return_wwn_list, expected_wwn_list)
        self.assertRaises(exception.InvalidParameterValue,
                          self._parse_ns_output, invalid_switch_data)

    def test_get_formatted_wwn(self):
        wwn_list = ['10008c7cff523b01']
        return_wwn_list = []
        expected_wwn_list = ['10:00:8c:7c:ff:52:3b:01']
        return_wwn_list.append(self.get_formatted_wwn(wwn_list[0]))
        self.assertEqual(return_wwn_list, expected_wwn_list)


class Channel(object):
    def recv_exit_status(self):
        return 0


class Stream(object):
    def __init__(self, buffer=''):
        self.buffer = buffer
        self.channel = Channel()

    def readlines(self):
        return self.buffer

    def close(self):
        pass

    def flush(self):
        self.buffer = ''
