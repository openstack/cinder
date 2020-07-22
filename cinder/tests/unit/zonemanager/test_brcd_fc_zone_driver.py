#    (c) Copyright 2014 Brocade Communications Systems Inc.
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


"""Unit tests for Brocade fc zone driver."""
from unittest import mock

from oslo_utils import importutils
import paramiko
import requests

from cinder import exception
from cinder.tests.unit import test
from cinder.volume import configuration as conf
from cinder.zonemanager.drivers.brocade import brcd_fabric_opts as fabric_opts
from cinder.zonemanager.drivers.brocade import brcd_fc_zone_driver as driver
from cinder.zonemanager import fc_zone_manager as zmanager

_zone_name = 'openstack_fab1_10008c7cff523b0120240002ac000a50'
_zone_name_initiator_mode = 'openstack_fab1_10008c7cff523b01'
WWNS = ['10:00:8c:7c:ff:52:3b:01', '20:24:00:02:ac:00:0a:50']

_active_cfg_before_add = {}
_activate = True
_target_ns_map = {'100000051e55a100': ['20240002ac000a50']}
_initiator_ns_map = {'100000051e55a100': ['10008c7cff523b01']}
_zone_map_to_add = {_zone_name: WWNS}

_initiator_target_map = {'10008c7cff523b01': ['20240002ac000a50']}
_device_map_to_verify = {
    '100000051e55a100': {
        'initiator_port_wwn_list': [
            '10008c7cff523b01'], 'target_port_wwn_list': ['20240002ac000a50']}}
_fabric_wwn = '100000051e55a100'


class BrcdFcZoneDriverBaseTest(object):

    def _set_conf_overrides(self, group, **kwargs):
        for name, value in kwargs.items():
            self.override_config(name, value, group)

    def setup_config(self, is_normal, mode):
        self.override_config('zoning_mode', 'fabric')

        fabric_group_name = 'BRCD_FAB_1'
        self._set_conf_overrides(
            'fc-zone-manager',
            zone_driver=('cinder.tests.unit.zonemanager.'
                         'test_brcd_fc_zone_driver.FakeBrcdFCZoneDriver'),
            brcd_sb_connector=('cinder.tests.unit.zonemanager.'
                               'test_brcd_fc_zone_driver.'
                               'FakeBrcdFCZoneClientCLI'),
            zoning_policy='initiator-target',
            fc_san_lookup_service=('cinder.tests.unit.zonemanager.'
                                   'test_brcd_fc_zone_driver.'
                                   'FakeBrcdFCSanLookupService'),
            fc_fabric_names=fabric_group_name,
        )

        # Ensure that we have the fabric_name group
        conf.Configuration(fabric_opts.brcd_zone_opts, fabric_group_name)
        self._set_conf_overrides(
            fabric_group_name,
            fc_fabric_address='10.24.48.213',
            fc_fabric_password='password',
            fc_fabric_user='admin' if is_normal else 'invaliduser',
            zoning_policy='initiator' if mode == 2 else 'initiator-target',
            zone_activate=True,
            zone_name_prefix='openstack_fab1_',
            fc_southbound_protocol='SSH',
        )

        configuration = conf.Configuration(zmanager.zone_manager_opts,
                                           'fc-zone-manager')
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

    def get_client(self, protocol='HTTPS'):
        conn = ('cinder.tests.unit.zonemanager.test_brcd_fc_zone_driver.' +
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

    @mock.patch.object(driver.BrcdFCZoneDriver, '_get_southbound_client')
    def test_add_connection(self, get_southbound_client_mock):
        """Normal flow for i-t mode."""
        GlobalVars._is_normal_test = True
        GlobalVars._zone_state = []
        GlobalVars._active_cfg = _active_cfg_before_add
        get_southbound_client_mock.return_value = self.get_client("HTTPS")
        self.driver.add_connection('BRCD_FAB_1', _initiator_target_map)
        self.assertIn(_zone_name, GlobalVars._zone_state)

    def _active_cfg_before_delete(self, mode):
        zone_name = _zone_name if mode == 1 else _zone_name_initiator_mode
        return {'zones': {zone_name: WWNS, 't_zone': ['1,0']},
                'active_zone_config': 'cfg1'}

    @mock.patch.object(driver.BrcdFCZoneDriver, '_get_southbound_client')
    def test_delete_connection(self, get_southbound_client_mock):
        GlobalVars._is_normal_test = True
        GlobalVars._zone_state.append(_zone_name)
        get_southbound_client_mock.return_value = self.get_client("CLI")
        GlobalVars._active_cfg = self._active_cfg_before_delete(mode=1)
        self.driver.delete_connection(
            'BRCD_FAB_1', _initiator_target_map)
        self.assertNotIn(_zone_name, GlobalVars._zone_state)

    @mock.patch.object(driver.BrcdFCZoneDriver, '_get_southbound_client')
    def test_add_connection_for_initiator_mode(self, get_southbound_client_mk):
        """Normal flow for i mode."""
        GlobalVars._is_normal_test = True
        get_southbound_client_mk.return_value = self.get_client("CLI")
        GlobalVars._active_cfg = _active_cfg_before_add
        self.setup_driver(self.setup_config(True, 2))
        self.driver.add_connection('BRCD_FAB_1', _initiator_target_map)
        self.assertIn(_zone_name_initiator_mode, GlobalVars._zone_state)

    @mock.patch.object(driver.BrcdFCZoneDriver, '_get_southbound_client')
    def test_delete_connection_for_initiator_mode(self,
                                                  get_southbound_client_mk):
        GlobalVars._is_normal_test = True
        GlobalVars._zone_state.append(_zone_name_initiator_mode)
        get_southbound_client_mk.return_value = self.get_client("HTTPS")
        GlobalVars._active_cfg = self._active_cfg_before_delete(mode=2)
        self.setup_driver(self.setup_config(True, 2))
        self.driver.delete_connection(
            'BRCD_FAB_1', _initiator_target_map)
        self.assertNotIn(_zone_name_initiator_mode, GlobalVars._zone_state)

    @mock.patch('cinder.zonemanager.drivers.brocade.brcd_fc_zone_client_cli.'
                'BrcdFCZoneClientCLI.__init__', side_effect=Exception)
    def test_add_connection_for_invalid_fabric(self, create_client_mock):
        """Test abnormal flows."""
        GlobalVars._active_cfg = _active_cfg_before_add
        self.setup_driver(self.setup_config(False, 1))
        self.assertRaises(exception.FCZoneDriverException,
                          self.driver.add_connection,
                          'BRCD_FAB_1',
                          _initiator_target_map)

    @mock.patch('cinder.zonemanager.drivers.brocade.brcd_fc_zone_client_cli.'
                'BrcdFCZoneClientCLI.__init__', side_effect=Exception)
    def test_delete_connection_for_invalid_fabric(self, create_client_mock):
        GlobalVars._active_cfg = self._active_cfg_before_delete(mode=1)
        GlobalVars._is_normal_test = False
        self.setup_driver(self.setup_config(False, 1))
        self.assertRaises(exception.FCZoneDriverException,
                          self.driver.delete_connection,
                          'BRCD_FAB_1',
                          _initiator_target_map)

    @mock.patch.object(driver.BrcdFCZoneDriver, '_get_southbound_client')
    def test_get_san_context(self, client_mock):
        GlobalVars._is_normal_test = True
        self.setup_driver(self.setup_config(True, 1))
        get_ns_mock = client_mock.return_value.get_nameserver_info
        wwn = '20:24:00:02:ac:00:0a:50'
        get_ns_mock.return_value = [wwn]
        expected = {'BRCD_FAB_1': ['20240002ac000a50']}

        res = self.driver.get_san_context([WWNS[0], wwn.upper()])

        client_mock.assert_called_once_with('BRCD_FAB_1')
        client_mock.return_value.cleanup.assert_called_once_with()
        get_ns_mock.assert_called_once_with()
        self.assertEqual(expected, res)


class FakeClient(object):
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


class FakeBrcdFCZoneClientCLI(FakeClient):
    def __init__(self, ipaddress, username,
                 password, port, key, vfid, protocol):
        self.firmware_supported = True
        if not GlobalVars._is_normal_test:
            raise paramiko.SSHException("Unable to connect to fabric.")


class FakeBrcdHttpFCZoneClient(FakeClient):

    def __init__(self, ipaddress, username,
                 password, port, key, vfid, protocol):
        self.firmware_supported = True
        if not GlobalVars._is_normal_test:
            raise requests.exception.HTTPError("Unable to connect to fabric")


class FakeBrcdFCSanLookupService(object):

    def get_device_mapping_from_network(self,
                                        initiator_wwn_list,
                                        target_wwn_list):
        device_map = {}
        initiators = []
        targets = []
        for i in initiator_wwn_list:
            if i in _initiator_ns_map[_fabric_wwn]:
                initiators.append(i)
        for t in target_wwn_list:
            if t in _target_ns_map[_fabric_wwn]:
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
