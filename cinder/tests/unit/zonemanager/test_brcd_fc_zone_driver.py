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


"""Unit tests for Brocade fc zone driver."""

import mock
from oslo_config import cfg
from oslo_utils import importutils
import paramiko

from cinder import exception
from cinder import test
from cinder.volume import configuration as conf
from cinder.zonemanager.drivers.brocade import brcd_fc_zone_driver as driver

_active_cfg_before_add = {}
_active_cfg_before_delete = {
    'zones': {
        'openstack10008c7cff523b0120240002ac000a50': (
            ['10:00:8c:7c:ff:52:3b:01',
             '20:24:00:02:ac:00:0a:50']), 't_zone': ['1,0']},
        'active_zone_config': 'cfg1'}
_activate = True
_zone_name = 'openstack10008c7cff523b0120240002ac000a50'
_target_ns_map = {'100000051e55a100': ['20240002ac000a50']}
_initiator_ns_map = {'100000051e55a100': ['10008c7cff523b01']}
_zone_map_to_add = {'openstack10008c7cff523b0120240002ac000a50': (
    ['10:00:8c:7c:ff:52:3b:01', '20:24:00:02:ac:00:0a:50'])}

_initiator_target_map = {'10008c7cff523b01': ['20240002ac000a50']}
_device_map_to_verify = {
    '100000051e55a100': {
        'initiator_port_wwn_list': [
            '10008c7cff523b01'], 'target_port_wwn_list': ['20240002ac000a50']}}
_fabric_wwn = '100000051e55a100'


class BrcdFcZoneDriverBaseTest(object):

    def setup_config(self, is_normal, mode):
        fc_test_opts = [
            cfg.StrOpt('fc_fabric_address_BRCD_FAB_1', default='10.24.48.213',
                       help='FC Fabric names'),
        ]
        configuration = conf.Configuration(fc_test_opts)
        # fill up config
        configuration.zoning_mode = 'fabric'
        configuration.zone_driver = ('cinder.tests.unit.zonemanager.'
                                     'test_brcd_fc_zone_driver.'
                                     'FakeBrcdFCZoneDriver')
        configuration.brcd_sb_connector = ('cinder.tests.unit.zonemanager.'
                                           'test_brcd_fc_zone_driver'
                                           '.FakeBrcdFCZoneClientCLI')
        configuration.zoning_policy = 'initiator-target'
        configuration.zone_activate = True
        configuration.zone_name_prefix = 'openstack'
        configuration.fc_san_lookup_service = ('cinder.tests.unit.zonemanager.'
                                               'test_brcd_fc_zone_driver.'
                                               'FakeBrcdFCSanLookupService')

        configuration.fc_fabric_names = 'BRCD_FAB_1'
        configuration.fc_fabric_address_BRCD_FAB_1 = '10.24.48.213'
        if (is_normal):
            configuration.fc_fabric_user_BRCD_FAB_1 = 'admin'
        else:
            configuration.fc_fabric_user_BRCD_FAB_1 = 'invaliduser'
        configuration.fc_fabric_password_BRCD_FAB_1 = 'password'

        if (mode == 1):
            configuration.zoning_policy_BRCD_FAB_1 = 'initiator-target'
        elif (mode == 2):
            configuration.zoning_policy_BRCD_FAB_1 = 'initiator'
        else:
            configuration.zoning_policy_BRCD_FAB_1 = 'initiator-target'
        configuration.zone_activate_BRCD_FAB_1 = True
        configuration.zone_name_prefix_BRCD_FAB_1 = 'openstack_fab1'
        configuration.principal_switch_wwn_BRCD_FAB_1 = '100000051e55a100'
        return configuration


class TestBrcdFcZoneDriver(BrcdFcZoneDriverBaseTest, test.TestCase):

    def setUp(self):
        super(TestBrcdFcZoneDriver, self).setUp()
        # setup config for normal flow
        self.setup_driver(self.setup_config(True, 1))
        GlobalVars._zone_state = []

    def setup_driver(self, config):
        self.driver = importutils.import_object(
            'cinder.zonemanager.drivers.brocade.brcd_fc_zone_driver'
            '.BrcdFCZoneDriver', configuration=config)

    def fake__get_active_zone_set(self, brcd_sb_connector, fabric_ip):
        return GlobalVars._active_cfg

    def fake_get_san_context(self, target_wwn_list):
        fabric_map = {}
        return fabric_map

    @mock.patch.object(driver.BrcdFCZoneDriver, '_get_active_zone_set')
    def test_add_connection(self, get_active_zs_mock):
        """Normal flow for i-t mode."""
        GlobalVars._is_normal_test = True
        GlobalVars._zone_state = []
        get_active_zs_mock.return_value = _active_cfg_before_add
        self.driver.add_connection('BRCD_FAB_1', _initiator_target_map)
        self.assertTrue(_zone_name in GlobalVars._zone_state)

    @mock.patch.object(driver.BrcdFCZoneDriver, '_get_active_zone_set')
    def test_delete_connection(self, get_active_zs_mock):
        GlobalVars._is_normal_test = True
        get_active_zs_mock.return_value = _active_cfg_before_delete
        self.driver.delete_connection(
            'BRCD_FAB_1', _initiator_target_map)
        self.assertFalse(_zone_name in GlobalVars._zone_state)

    @mock.patch.object(driver.BrcdFCZoneDriver, '_get_active_zone_set')
    def test_add_connection_for_initiator_mode(self, get_active_zs_mock):
        """Normal flow for i mode."""
        GlobalVars._is_normal_test = True
        get_active_zs_mock.return_value = _active_cfg_before_add
        self.setup_driver(self.setup_config(True, 2))
        self.driver.add_connection('BRCD_FAB_1', _initiator_target_map)
        self.assertTrue(_zone_name in GlobalVars._zone_state)

    @mock.patch.object(driver.BrcdFCZoneDriver, '_get_active_zone_set')
    def test_delete_connection_for_initiator_mode(self, get_active_zs_mock):
        GlobalVars._is_normal_test = True
        get_active_zs_mock.return_value = _active_cfg_before_delete
        self.setup_driver(self.setup_config(True, 2))
        self.driver.delete_connection(
            'BRCD_FAB_1', _initiator_target_map)
        self.assertFalse(_zone_name in GlobalVars._zone_state)

    def test_add_connection_for_invalid_fabric(self):
        """Test abnormal flows."""
        GlobalVars._is_normal_test = True
        GlobalVars._active_cfg = _active_cfg_before_add
        GlobalVars._is_normal_test = False
        self.setup_driver(self.setup_config(False, 1))
        self.assertRaises(exception.FCZoneDriverException,
                          self.driver.add_connection,
                          'BRCD_FAB_1',
                          _initiator_target_map)

    def test_delete_connection_for_invalid_fabric(self):
        GlobalVars._active_cfg = _active_cfg_before_delete
        GlobalVars._is_normal_test = False
        self.setup_driver(self.setup_config(False, 1))
        self.assertRaises(exception.FCZoneDriverException,
                          self.driver.delete_connection,
                          'BRCD_FAB_1',
                          _initiator_target_map)


class FakeBrcdFCZoneClientCLI(object):
    def __init__(self, ipaddress, username, password, port):
        self.firmware_supported = True
        if not GlobalVars._is_normal_test:
            raise paramiko.SSHException("Unable to connect to fabric")

    def get_active_zone_set(self):
        return GlobalVars._active_cfg

    def add_zones(self, zones, isActivate, active_zone_set):
        GlobalVars._zone_state.extend(zones.keys())

    def delete_zones(self, zone_names, isActivate, active_zone_set):
        zone_list = zone_names.split(';')
        GlobalVars._zone_state = [
            x for x in GlobalVars._zone_state if x not in zone_list]

    def is_supported_firmware(self):
        return True

    def get_nameserver_info(self):
        return _target_ns_map

    def close_connection(self):
        pass

    def cleanup(self):
        pass


class FakeBrcdFCSanLookupService(object):
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
