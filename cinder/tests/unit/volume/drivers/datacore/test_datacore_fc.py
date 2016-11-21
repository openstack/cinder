# Copyright (c) 2017 DataCore Software Corp. All Rights Reserved.
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

"""Unit tests for the Fibre Channel Driver for DataCore SANsymphony
storage array.
"""

import mock

from cinder import exception as cinder_exception
from cinder import test
from cinder.tests.unit.volume.drivers.datacore import test_datacore_driver
from cinder.volume.drivers.datacore import fc


PORTS = [
    mock.Mock(Id='initiator_port_id1',
              PortType='FibreChannel',
              PortMode='Initiator',
              PortName='AA-AA-AA-AA-AA-AA-AA-AA',
              HostId='client_id1'),
    mock.Mock(Id='initiator_port_id2',
              PortType='FibreChannel',
              PortMode='Initiator',
              PortName='BB-BB-BB-BB-BB-BB-BB-BB'),
    mock.Mock(Id='target_port_id1',
              PortMode='Target',
              PortName='CC-CC-CC-CC-CC-CC-CC-CC',
              HostId='server_id1'),
    mock.Mock(Id='target_port_id2',
              PortMode='Target',
              PortName='DD-DD-DD-DD-DD-DD-DD-DD',
              HostId='server_id1'),
]

LOGICAL_UNITS = [
    mock.Mock(VirtualTargetDeviceId='target_device_id1',
              Lun=mock.Mock(Quad=4)),
    mock.Mock(VirtualTargetDeviceId='target_device_id2',
              Lun=mock.Mock(Quad=3)),
    mock.Mock(VirtualTargetDeviceId='target_device_id3',
              Lun=mock.Mock(Quad=2)),
    mock.Mock(VirtualTargetDeviceId='target_device_id4',
              Lun=mock.Mock(Quad=1)),
]

TARGET_DEVICES = [
    mock.Mock(Id='target_device_id1',
              TargetPortId='target_port_id1',
              InitiatorPortId='initiator_port_id1'),
    mock.Mock(Id='target_device_id2',
              TargetPortId='target_port_id2',
              InitiatorPortId='initiator_port_id1'),
    mock.Mock(Id='target_device_id3',
              TargetPortId='target_port_id2',
              InitiatorPortId='initiator_port_id1'),
    mock.Mock(Id='target_device_id4',
              TargetPortId='target_port_id2',
              InitiatorPortId='initiator_port_id2'),
]


class FibreChannelVolumeDriverTestCase(
        test_datacore_driver.DataCoreVolumeDriverTestCase, test.TestCase):
    """Tests for the FC Driver for DataCore SANsymphony storage array."""

    def setUp(self):
        super(FibreChannelVolumeDriverTestCase, self).setUp()
        self.mock_client.get_ports.return_value = PORTS
        self.mock_client.get_target_devices.return_value = TARGET_DEVICES

    @staticmethod
    def init_driver(config):
        driver = fc.FibreChannelVolumeDriver(configuration=config)
        driver.do_setup(None)
        return driver

    def test_validate_connector(self):
        driver = self.init_driver(self.setup_default_configuration())
        connector = {
            'host': 'host_name',
            'wwpns': ['AA-AA-AA-AA-AA-AA-AA-AA'],
        }
        driver.validate_connector(connector)

    def test_validate_connector_failed(self):
        driver = self.init_driver(self.setup_default_configuration())
        connector = {}
        self.assertRaises(cinder_exception.InvalidConnectorException,
                          driver.validate_connector,
                          connector)

        connector = {'host': 'host_name'}
        self.assertRaises(cinder_exception.InvalidConnectorException,
                          driver.validate_connector,
                          connector)

        connector = {'wwpns': ['AA-AA-AA-AA-AA-AA-AA-AA']}
        self.assertRaises(cinder_exception.InvalidConnectorException,
                          driver.validate_connector,
                          connector)

    def test_initialize_connection(self):
        (self.mock_client.serve_virtual_disks_to_host
         .return_value) = LOGICAL_UNITS

        virtual_disk = test_datacore_driver.VIRTUAL_DISKS[0]
        client = test_datacore_driver.CLIENTS[0]
        driver = self.init_driver(self.setup_default_configuration())
        volume = test_datacore_driver.VOLUME.copy()
        volume['provider_location'] = virtual_disk.Id
        initiator_wwpns = [port.PortName.replace('-', '').lower() for port
                           in PORTS
                           if port.PortMode == 'Initiator']
        connector = {
            'host': client.HostName,
            'wwpns': initiator_wwpns,
        }
        result = driver.initialize_connection(volume, connector)
        self.assertEqual('fibre_channel', result['driver_volume_type'])

        target_wwns = [port.PortName.replace('-', '').lower() for port
                       in PORTS
                       if port.PortMode == 'Target']
        self.assertIn(result['data']['target_wwn'], target_wwns)

        target_wwn = result['data']['target_wwn']
        target_port_id = next((
            port.Id for port
            in PORTS
            if port.PortName.replace('-', '').lower() == target_wwn), None)
        target_device_id = next((
            device.Id for device
            in TARGET_DEVICES
            if device.TargetPortId == target_port_id), None)
        target_lun = next((
            unit.Lun.Quad for unit
            in LOGICAL_UNITS
            if unit.VirtualTargetDeviceId == target_device_id), None)
        self.assertEqual(target_lun, result['data']['target_lun'])

        self.assertFalse(result['data']['target_discovered'])
        self.assertEqual(volume['id'], result['data']['volume_id'])
        self.assertEqual('rw', result['data']['access_mode'])

    def test_initialize_connection_unknown_client(self):
        client = test_datacore_driver.CLIENTS[0]
        self.mock_client.register_client.return_value = client
        (self.mock_client.get_clients
         .return_value) = test_datacore_driver.CLIENTS[1:]
        (self.mock_client.serve_virtual_disks_to_host
         .return_value) = LOGICAL_UNITS

        virtual_disk = test_datacore_driver.VIRTUAL_DISKS[0]
        driver = self.init_driver(self.setup_default_configuration())
        volume = test_datacore_driver.VOLUME.copy()
        volume['provider_location'] = virtual_disk.Id
        initiator_wwpns = [port.PortName.replace('-', '').lower() for port
                           in PORTS
                           if port.PortMode == 'Initiator']
        connector = {
            'host': client.HostName,
            'wwpns': initiator_wwpns,
        }
        result = driver.initialize_connection(volume, connector)
        self.assertEqual('fibre_channel', result['driver_volume_type'])

        target_wwns = [port.PortName.replace('-', '').lower() for port
                       in PORTS
                       if port.PortMode == 'Target']
        self.assertIn(result['data']['target_wwn'], target_wwns)

        target_wwn = result['data']['target_wwn']
        target_port_id = next((
            port.Id for port
            in PORTS
            if port.PortName.replace('-', '').lower() == target_wwn), None)
        target_device_id = next((
            device.Id for device
            in TARGET_DEVICES
            if device.TargetPortId == target_port_id), None)
        target_lun = next((
            unit.Lun.Quad for unit
            in LOGICAL_UNITS
            if unit.VirtualTargetDeviceId == target_device_id), None)
        self.assertEqual(target_lun, result['data']['target_lun'])

        self.assertFalse(result['data']['target_discovered'])
        self.assertEqual(volume['id'], result['data']['volume_id'])
        self.assertEqual('rw', result['data']['access_mode'])

    def test_initialize_connection_failed_not_found(self):
        client = test_datacore_driver.CLIENTS[0]
        driver = self.init_driver(self.setup_default_configuration())
        volume = test_datacore_driver.VOLUME.copy()
        volume['provider_location'] = 'wrong_virtual_disk_id'
        initiator_wwpns = [port.PortName.replace('-', '').lower() for port
                           in PORTS
                           if port.PortMode == 'Initiator']
        connector = {
            'host': client.HostName,
            'wwpns': initiator_wwpns,
        }
        self.assertRaises(cinder_exception.VolumeDriverException,
                          driver.initialize_connection,
                          volume,
                          connector)

    def test_initialize_connection_failed_initiator_not_found(self):
        (self.mock_client.serve_virtual_disks_to_host
         .return_value) = LOGICAL_UNITS

        virtual_disk = test_datacore_driver.VIRTUAL_DISKS[0]
        client = test_datacore_driver.CLIENTS[0]
        driver = self.init_driver(self.setup_default_configuration())
        volume = test_datacore_driver.VOLUME.copy()
        volume['provider_location'] = virtual_disk.Id
        connector = {
            'host': client.HostName,
            'wwpns': ['0000000000000000'],
        }
        self.assertRaises(cinder_exception.VolumeDriverException,
                          driver.initialize_connection,
                          volume,
                          connector)

    def test_initialize_connection_failed_on_serve(self):
        self.mock_client.serve_virtual_disks_to_host.return_value = []

        virtual_disk = test_datacore_driver.VIRTUAL_DISKS[0]
        client = test_datacore_driver.CLIENTS[0]
        driver = self.init_driver(self.setup_default_configuration())
        volume = test_datacore_driver.VOLUME.copy()
        volume['provider_location'] = virtual_disk.Id
        initiator_wwpns = [port.PortName.replace('-', '').lower() for port
                           in PORTS
                           if port.PortMode == 'Initiator']
        connector = {
            'host': client.HostName,
            'wwpns': initiator_wwpns,
        }
        self.assertRaises(cinder_exception.VolumeDriverException,
                          driver.initialize_connection,
                          volume,
                          connector)
