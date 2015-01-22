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


"""Unit tests for Cisco FC zone driver."""

from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_utils import importutils

from cinder import exception
from cinder import test
from cinder.volume import configuration as conf

_active_cfg_before_add = {}
_active_cfg_before_delete = {
    'zones': {
        'openstack10008c7cff523b0120240002ac000a50': (
            ['10:00:8c:7c:ff:52:3b:01',
             '20:24:00:02:ac:00:0a:50'])},
        'active_zone_config': 'cfg1'}
_activate = True
_zone_name = 'openstack10008c7cff523b0120240002ac000a50'
_target_ns_map = {'100000051e55a100': ['20240002ac000a50']}
_zoning_status = {'mode': 'basis', 'session': 'none'}
_initiator_ns_map = {'100000051e55a100': ['10008c7cff523b01']}
_zone_map_to_add = {'openstack10008c7cff523b0120240002ac000a50': (
    ['10:00:8c:7c:ff:52:3b:01', '20:24:00:02:ac:00:0a:50'])}

_initiator_target_map = {'10008c7cff523b01': ['20240002ac000a50']}
_device_map_to_verify = {
    '304': {
        'initiator_port_wwn_list': [
            '10008c7cff523b01'], 'target_port_wwn_list': ['20240002ac000a50']}}
_fabric_wwn = '304'


class CiscoFcZoneDriverBaseTest(object):

    def setup_config(self, is_normal, mode):
        fc_test_opts = [
            cfg.StrOpt('fc_fabric_address_CISCO_FAB_1', default='10.24.48.213',
                       help='FC Fabric names'),
        ]
        configuration = conf.Configuration(fc_test_opts)
        # fill up config
        configuration.zoning_mode = 'fabric'
        configuration.zone_driver = ('cinder.tests.zonemanager.'
                                     'test_cisco_fc_zone_driver.'
                                     'FakeCiscoFCZoneDriver')
        configuration.cisco_sb_connector = ('cinder.tests.zonemanager.'
                                            'test_cisco_fc_zone_driver'
                                            '.FakeCiscoFCZoneClientCLI')
        configuration.zoning_policy = 'initiator-target'
        configuration.zone_activate = True
        configuration.zone_name_prefix = 'openstack'
        configuration.fc_san_lookup_service = ('cinder.tests.zonemanager.'
                                               'test_cisco_fc_zone_driver.'
                                               'FakeCiscoFCSanLookupService')

        configuration.fc_fabric_names = 'CISCO_FAB_1'
        configuration.fc_fabric_address_CISCO_FAB_1 = '172.21.60.220'
        if (is_normal):
            configuration.fc_fabric_user_CISCO_FAB_1 = 'admin'
        else:
            configuration.fc_fabric_user_CISCO_FAB_1 = 'invaliduser'
        configuration.fc_fabric_password_CISCO_FAB_1 = 'admin1234'

        if (mode == 1):
            configuration.zoning_policy_CISCO_FAB_1 = 'initiator-target'
        elif (mode == 2):
            configuration.zoning_policy_CISCO_FAB_1 = 'initiator'
        else:
            configuration.zoning_policy_CISCO_FAB_1 = 'initiator-target'
        configuration.zone_activate_CISCO_FAB_1 = True
        configuration.zone_name_prefix_CISCO_FAB_1 = 'openstack'
        configuration.zoning_vsan_CISCO_FAB_1 = '304'
        return configuration


class TestCiscoFcZoneDriver(CiscoFcZoneDriverBaseTest, test.TestCase):

    def setUp(self):
        super(TestCiscoFcZoneDriver, self).setUp()
        # setup config for normal flow
        self.setup_driver(self.setup_config(True, 1))
        GlobalVars._zone_state = []

    def setup_driver(self, config):
        self.driver = importutils.import_object(
            'cinder.zonemanager.drivers.cisco.cisco_fc_zone_driver'
            '.CiscoFCZoneDriver', configuration=config)

    def fake_get_active_zone_set(self, fabric_ip, fabric_user, fabric_pwd,
                                 zoning_vsan):
        return GlobalVars._active_cfg

    def fake_get_san_context(self, target_wwn_list):
        fabric_map = {}
        return fabric_map

    def test_delete_connection(self):
        GlobalVars._is_normal_test = True
        GlobalVars._active_cfg = _active_cfg_before_delete
        self.driver.delete_connection(
            'CISCO_FAB_1', _initiator_target_map)
        self.assertFalse(_zone_name in GlobalVars._zone_state)

    def test_delete_connection_for_initiator_mode(self):
        GlobalVars._is_normal_test = True
        GlobalVars._active_cfg = _active_cfg_before_delete
        self.setup_driver(self.setup_config(True, 2))
        self.driver.delete_connection(
            'CISCO_FAB_1', _initiator_target_map)
        self.assertFalse(_zone_name in GlobalVars._zone_state)

    def test_add_connection_for_invalid_fabric(self):
        """Test abnormal flows."""
        GlobalVars._is_normal_test = True
        GlobalVars._active_cfg = _active_cfg_before_add
        GlobalVars._is_normal_test = False
        self.setup_driver(self.setup_config(False, 1))
        self.assertRaises(exception.FCZoneDriverException,
                          self.driver.add_connection,
                          'CISCO_FAB_1',
                          _initiator_target_map)

    def test_delete_connection_for_invalid_fabric(self):
        GlobalVars._active_cfg = _active_cfg_before_delete
        GlobalVars._is_normal_test = False
        self.setup_driver(self.setup_config(False, 1))
        self.assertRaises(exception.FCZoneDriverException,
                          self.driver.delete_connection,
                          'CISCO_FAB_1',
                          _initiator_target_map)


class FakeCiscoFCZoneClientCLI(object):
    def __init__(self, ipaddress, username, password, port, vsan):
        if not GlobalVars._is_normal_test:
            raise processutils.ProcessExecutionError(
                "Unable to connect to fabric")

    def get_active_zone_set(self):
        return GlobalVars._active_cfg

    def add_zones(self, zones, isActivate):
        GlobalVars._zone_state.extend(zones.keys())

    def delete_zones(self, zone_names, isActivate):
        zone_list = zone_names.split(';')
        GlobalVars._zone_state = [
            x for x in GlobalVars._zone_state if x not in zone_list]

    def get_nameserver_info(self):
        return _target_ns_map

    def get_zoning_status(self):
        return _zoning_status

    def close_connection(self):
        pass

    def cleanup(self):
        pass


class FakeCiscoFCSanLookupService(object):
    def get_device_mapping_from_network(self,
                                        initiator_wwn_list,
                                        target_wwn_list):
        device_map = {}
        initiators = []
        targets = []
        for i in initiator_wwn_list:
            if (i in _initiator_ns_map[_fabric_wwn]):
                initiators.append(i)
        for t in target_wwn_list:
            if (t in _target_ns_map[_fabric_wwn]):
                targets.append(t)
        device_map[_fabric_wwn] = {
            'initiator_port_wwn_list': initiators,
            'target_port_wwn_list': targets}
        return device_map


class GlobalVars(object):
    global _active_cfg
    _active_cfg = {}
    global _zone_state
    _zone_state = list()
    global _is_normal_test
    _is_normal_test = True
    global _zoning_status
    _zoning_status = {}
