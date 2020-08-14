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


"""Unit tests for brcd fc san lookup service."""
from unittest import mock

from oslo_config import cfg
from oslo_utils import importutils

from cinder.tests.unit import test
from cinder.volume import configuration as conf
import cinder.zonemanager.drivers.brocade.brcd_fc_san_lookup_service \
    as brcd_lookup


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
        self.configuration.brcd_sb_connector = ('cinder.tests.unit.zonemanager'
                                                '.test_brcd_fc_san_lookup_'
                                                'service'
                                                '.FakeBrcdFCZoneClientCLI')
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
        fc_fabric_opts.append(cfg.PortOpt('fc_fabric_port',
                                          default=22, help=''))
        config = conf.Configuration(fc_fabric_opts, 'BRCD_FAB_2')
        self.fabric_configs = {'BRCD_FAB_2': config}

    def get_client(self, protocol='HTTPS'):
        conn = ('cinder.tests.unit.zonemanager.'
                'test_brcd_fc_san_lookup_service.' +
                ('FakeBrcdFCZoneClientCLI' if protocol == "CLI"
                 else 'FakeBrcdHttpFCZoneClient'))
        client = importutils.import_object(
            conn,
            ipaddress="10.24.48.213",
            username="admin",
            password="password",
            key="/home/stack/.ssh/id_rsa",
            port=22,
            vfid="2",
            protocol=protocol
        )
        return client

    @mock.patch.object(brcd_lookup.BrcdFCSanLookupService,
                       '_get_southbound_client')
    def test_get_device_mapping_from_network(self, get_southbound_client_mock):
        initiator_list = [parsed_switch_port_wwns[1]]
        target_list = [parsed_switch_port_wwns[0], '20240002ac000a40']
        get_southbound_client_mock.return_value = self.get_client("HTTPS")
        device_map = self.get_device_mapping_from_network(
            initiator_list, target_list)
        self.assertDictEqual(_device_map_to_verify, device_map)

    @mock.patch.object(brcd_lookup.BrcdFCSanLookupService,
                       '_get_southbound_client', side_effect=ValueError)
    def test_get_device_mapping_from_network_fail(self,
                                                  get_southbound_client_mock):
        initiator_list = [parsed_switch_port_wwns[1]]
        target_list = [parsed_switch_port_wwns[0], '20240002ac000a40']
        self.assertRaises(brcd_lookup.exception.FCSanLookupServiceException,
                          self.get_device_mapping_from_network,
                          initiator_list, target_list)


class FakeClient(object):
    def is_supported_firmware(self):
        return True

    def get_nameserver_info(self):
        ns_info_list_expected = (parsed_switch_port_wwns)
        return ns_info_list_expected

    def close_connection(self):
        pass

    def cleanup(self):
        pass


class FakeBrcdFCZoneClientCLI(FakeClient):
    def __init__(self, ipaddress, username,
                 password, port, key, vfid, protocol):
        self.firmware_supported = True


class FakeBrcdHttpFCZoneClient(FakeClient):

    def __init__(self, ipaddress, username,
                 password, port, key, vfid, protocol):
        self.firmware_supported = True
