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

"""Unit tests for the iSCSI Driver for DataCore SANsymphony storage array."""

import mock

from cinder import exception as cinder_exception
from cinder import test
from cinder.tests.unit.volume.drivers.datacore import test_datacore_driver
from cinder.tests.unit.volume.drivers.datacore import test_datacore_passwd
from cinder.volume.drivers.datacore import exception as datacore_exception
from cinder.volume.drivers.datacore import iscsi


ISCSI_PORT_STATE_INFO_READY = mock.Mock(
    PortalsState=mock.Mock(
        PortalStateInfo=[mock.Mock(State='Ready')]
    )
)

ISCSI_PORT_CONFIG_INFO = mock.Mock(
    PortalsConfig=mock.Mock(
        iScsiPortalConfigInfo=[mock.Mock(
            Address=mock.Mock(Address='127.0.0.1'), TcpPort='3260')]
    )
)

PORTS = [
    mock.Mock(Id='initiator_port_id1',
              PortType='iSCSI',
              PortMode='Initiator',
              PortName='iqn.1993-08.org.debian:1:1',
              HostId='client_id1'),
    mock.Mock(Id='initiator_port_id2',
              PortType='iSCSI',
              PortMode='Initiator',
              PortName='iqn.1993-08.org.debian:1:2'),
    mock.Mock(__class__=mock.Mock(__name__='ServeriScsiPortData'),
              Id='target_port_id1',
              PortType='iSCSI',
              PortMode='Target',
              PortName='iqn.2000-08.com.datacore:server-1-1',
              HostId='server_id1',
              PresenceStatus='Present',
              ServerPortProperties=mock.Mock(Role="Frontend",
                                             Authentication='None'),
              IScsiPortStateInfo=ISCSI_PORT_STATE_INFO_READY,
              PortConfigInfo=ISCSI_PORT_CONFIG_INFO),
    mock.Mock(Id='target_port_id2',
              PortType='iSCSI',
              PortMode='Target',
              PortName='iqn.2000-08.com.datacore:server-1-2',
              HostId='server_id1',
              PresenceStatus='Present',
              ServerPortProperties=mock.Mock(Role="Frontend",
                                             Authentication='None'),
              IScsiPortStateInfo=ISCSI_PORT_STATE_INFO_READY,
              PortConfigInfo=ISCSI_PORT_CONFIG_INFO),
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


class ISCSIVolumeDriverTestCase(
        test_datacore_driver.DataCoreVolumeDriverTestCase, test.TestCase):
    """Tests for the iSCSI Driver for DataCore SANsymphony storage array."""

    def setUp(self):
        super(ISCSIVolumeDriverTestCase, self).setUp()
        self.mock_client.get_ports.return_value = PORTS
        (self.mock_client.build_scsi_port_nexus_data
         .side_effect) = self._build_nexus_data
        self.mock_client.map_logical_disk.side_effect = self._map_logical_disk

    @staticmethod
    def _build_nexus_data(initiator_port_id, target_port_id):
        return mock.Mock(InitiatorPortId=initiator_port_id,
                         TargetPortId=target_port_id)

    @staticmethod
    def _map_logical_disk(logical_disk_id, nexus, *args):
        target_device_id = next((
            device.Id for device in TARGET_DEVICES
            if device.TargetPortId == nexus.TargetPortId
            and device.InitiatorPortId == nexus.InitiatorPortId), None)
        return next(unit for unit in LOGICAL_UNITS
                    if unit.VirtualTargetDeviceId == target_device_id)

    @staticmethod
    def init_driver(config):
        driver = iscsi.ISCSIVolumeDriver(configuration=config)
        driver.do_setup(None)
        return driver

    @staticmethod
    def create_configuration():
        config = super(ISCSIVolumeDriverTestCase,
                       ISCSIVolumeDriverTestCase).create_configuration()
        config.append_config_values(iscsi.datacore_iscsi_opts)
        return config

    def test_do_setup_failed(self):
        super(ISCSIVolumeDriverTestCase, self).test_do_setup_failed()

        config = self.setup_default_configuration()
        config.datacore_iscsi_chap_enabled = True
        config.datacore_iscsi_chap_storage = None
        self.assertRaises(cinder_exception.InvalidInput,
                          self.init_driver,
                          config)

    def test_validate_connector(self):
        driver = self.init_driver(self.setup_default_configuration())
        connector = {
            'host': 'host_name',
            'initiator': 'iqn.1993-08.org.debian:1:1',
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

        connector = {'initiator': 'iqn.1993-08.org.debian:1:1'}
        self.assertRaises(cinder_exception.InvalidConnectorException,
                          driver.validate_connector,
                          connector)

    def test_initialize_connection(self):
        self.mock_client.get_logical_units.return_value = []
        self.mock_client.get_target_domains.return_value = []
        self.mock_client.get_target_devices.return_value = TARGET_DEVICES

        virtual_disk = test_datacore_driver.VIRTUAL_DISKS[0]
        client = test_datacore_driver.CLIENTS[0]
        driver = self.init_driver(self.setup_default_configuration())
        volume = test_datacore_driver.VOLUME.copy()
        volume['provider_location'] = virtual_disk.Id
        initiator_iqn = PORTS[0].PortName
        connector = {
            'host': client.HostName,
            'initiator': initiator_iqn
        }
        result = driver.initialize_connection(volume, connector)
        self.assertEqual('iscsi', result['driver_volume_type'])

        target_iqn = [port.PortName for port
                      in PORTS
                      if port.PortMode == 'Target']
        self.assertIn(result['data']['target_iqn'], target_iqn)

        target_iqn = result['data']['target_iqn']
        target_port = next((
            port for port
            in PORTS
            if port.PortName == target_iqn), None)
        target_device_id = next((
            device.Id for device
            in TARGET_DEVICES
            if device.TargetPortId == target_port.Id), None)
        target_lun = next((
            unit.Lun.Quad for unit
            in LOGICAL_UNITS
            if unit.VirtualTargetDeviceId == target_device_id), None)
        self.assertEqual(target_lun, result['data']['target_lun'])

        self.assertEqual('127.0.0.1:3260', result['data']['target_portal'])
        self.assertFalse(result['data']['target_discovered'])
        self.assertEqual(volume['id'], result['data']['volume_id'])
        self.assertEqual('rw', result['data']['access_mode'])

    def test_initialize_connection_unknown_client(self):
        client = test_datacore_driver.CLIENTS[0]
        self.mock_client.register_client.return_value = client
        (self.mock_client.get_clients
         .return_value) = test_datacore_driver.CLIENTS[1:]
        self.mock_client.get_logical_units.return_value = []
        self.mock_client.get_target_domains.return_value = []
        self.mock_client.get_target_devices.return_value = TARGET_DEVICES

        virtual_disk = test_datacore_driver.VIRTUAL_DISKS[0]
        client = test_datacore_driver.CLIENTS[0]
        driver = self.init_driver(self.setup_default_configuration())
        volume = test_datacore_driver.VOLUME.copy()
        volume['provider_location'] = virtual_disk.Id
        initiator_iqn = PORTS[0].PortName
        connector = {
            'host': client.HostName,
            'initiator': initiator_iqn
        }
        result = driver.initialize_connection(volume, connector)
        self.assertEqual('iscsi', result['driver_volume_type'])

        target_iqn = [port.PortName for port
                      in PORTS
                      if port.PortMode == 'Target']
        self.assertIn(result['data']['target_iqn'], target_iqn)

        target_iqn = result['data']['target_iqn']
        target_port = next((
            port for port
            in PORTS
            if port.PortName == target_iqn), None)
        target_device_id = next((
            device.Id for device
            in TARGET_DEVICES
            if device.TargetPortId == target_port.Id), None)
        target_lun = next((
            unit.Lun.Quad for unit
            in LOGICAL_UNITS
            if unit.VirtualTargetDeviceId == target_device_id), None)
        self.assertEqual(target_lun, result['data']['target_lun'])

        self.assertEqual('127.0.0.1:3260', result['data']['target_portal'])
        self.assertFalse(result['data']['target_discovered'])
        self.assertEqual(volume['id'], result['data']['volume_id'])
        self.assertEqual('rw', result['data']['access_mode'])

    def test_initialize_connection_unknown_initiator(self):
        self.mock_client.register_port.return_value = PORTS[0]
        self.mock_client.get_ports.return_value = PORTS[1:]
        self.mock_client.get_logical_units.return_value = []
        self.mock_client.get_target_domains.return_value = []
        self.mock_client.get_target_devices.return_value = TARGET_DEVICES

        virtual_disk = test_datacore_driver.VIRTUAL_DISKS[0]
        client = test_datacore_driver.CLIENTS[0]
        driver = self.init_driver(self.setup_default_configuration())
        volume = test_datacore_driver.VOLUME.copy()
        volume['provider_location'] = virtual_disk.Id
        initiator_iqn = PORTS[0].PortName
        connector = {
            'host': client.HostName,
            'initiator': initiator_iqn
        }
        result = driver.initialize_connection(volume, connector)
        self.assertEqual('iscsi', result['driver_volume_type'])

        target_iqn = [port.PortName for port
                      in PORTS
                      if port.PortMode == 'Target']
        self.assertIn(result['data']['target_iqn'], target_iqn)

        target_iqn = result['data']['target_iqn']
        target_port = next((
            port for port
            in PORTS
            if port.PortName == target_iqn), None)
        target_device_id = next((
            device.Id for device
            in TARGET_DEVICES
            if device.TargetPortId == target_port.Id), None)
        target_lun = next((
            unit.Lun.Quad for unit
            in LOGICAL_UNITS
            if unit.VirtualTargetDeviceId == target_device_id), None)
        self.assertEqual(target_lun, result['data']['target_lun'])

        self.assertEqual('127.0.0.1:3260', result['data']['target_portal'])
        self.assertFalse(result['data']['target_discovered'])
        self.assertEqual(volume['id'], result['data']['volume_id'])
        self.assertEqual('rw', result['data']['access_mode'])

    def test_initialize_connection_failed_not_found(self):
        client = test_datacore_driver.CLIENTS[0]
        driver = self.init_driver(self.setup_default_configuration())
        volume = test_datacore_driver.VOLUME.copy()
        volume['provider_location'] = 'wrong_virtual_disk_id'
        initiator_iqn = PORTS[0].PortName
        connector = {
            'host': client.HostName,
            'initiator': initiator_iqn
        }
        self.assertRaises(cinder_exception.VolumeDriverException,
                          driver.initialize_connection,
                          volume,
                          connector)

    def test_initialize_connection_failed_target_not_found(self):
        virtual_disk = test_datacore_driver.VIRTUAL_DISKS[0]
        client = test_datacore_driver.CLIENTS[0]
        config = self.setup_default_configuration()
        config.datacore_iscsi_unallowed_targets = [
            port.PortName for port in PORTS if port.PortMode == 'Target'
        ]
        driver = self.init_driver(config)
        volume = test_datacore_driver.VOLUME.copy()
        volume['provider_location'] = virtual_disk.Id
        initiator_iqn = PORTS[0].PortName
        connector = {
            'host': client.HostName,
            'initiator': initiator_iqn
        }
        self.assertRaises(cinder_exception.VolumeDriverException,
                          driver.initialize_connection,
                          volume,
                          connector)

    def test_initialize_connection_failed_on_map(self):
        def fail_with_datacore_fault(*args):
            raise datacore_exception.DataCoreFaultException(
                reason="General error.")

        (self.mock_client.map_logical_disk
         .side_effect) = fail_with_datacore_fault
        self.mock_client.get_logical_units.return_value = []
        self.mock_client.get_target_domains.return_value = []
        self.mock_client.get_target_devices.return_value = TARGET_DEVICES

        virtual_disk = test_datacore_driver.VIRTUAL_DISKS[0]
        client = test_datacore_driver.CLIENTS[0]
        driver = self.init_driver(self.setup_default_configuration())
        volume = test_datacore_driver.VOLUME.copy()
        volume['provider_location'] = virtual_disk.Id
        initiator_iqn = PORTS[0].PortName
        connector = {
            'host': client.HostName,
            'initiator': initiator_iqn
        }
        self.assertRaises(datacore_exception.DataCoreFaultException,
                          driver.initialize_connection,
                          volume,
                          connector)

    def test_initialize_connection_chap(self):
        mock_file_storage = self.mock_object(iscsi.passwd, 'FileStorage')
        mock_file_storage.return_value = test_datacore_passwd.FakeFileStorage()
        target_port = mock.Mock(
            Id='target_port_id1',
            PortType='iSCSI',
            PortMode='Target',
            PortName='iqn.2000-08.com.datacore:server-1-1',
            HostId='server_id1',
            PresenceStatus='Present',
            ServerPortProperties=mock.Mock(Role="Frontend",
                                           Authentication='None'),
            IScsiPortStateInfo=ISCSI_PORT_STATE_INFO_READY,
            PortConfigInfo=ISCSI_PORT_CONFIG_INFO,
            iSCSINodes=mock.Mock(Node=[]))
        ports = PORTS[:2]
        ports.append(target_port)
        self.mock_client.get_ports.return_value = ports
        self.mock_client.get_logical_units.return_value = []
        self.mock_client.get_target_domains.return_value = []
        self.mock_client.get_target_devices.return_value = TARGET_DEVICES

        virtual_disk = test_datacore_driver.VIRTUAL_DISKS[0]
        client = test_datacore_driver.CLIENTS[0]
        config = self.setup_default_configuration()
        config.datacore_iscsi_chap_enabled = True
        config.datacore_iscsi_chap_storage = 'fake_file_path'
        driver = self.init_driver(config)
        volume = test_datacore_driver.VOLUME.copy()
        volume['provider_location'] = virtual_disk.Id
        initiator_iqn = PORTS[0].PortName
        connector = {
            'host': client.HostName,
            'initiator': initiator_iqn
        }
        result = driver.initialize_connection(volume, connector)
        self.assertEqual('iscsi', result['driver_volume_type'])

        target_iqn = [port.PortName for port
                      in PORTS
                      if port.PortMode == 'Target']
        self.assertIn(result['data']['target_iqn'], target_iqn)

        target_iqn = result['data']['target_iqn']
        target_port = next((
            port for port
            in PORTS
            if port.PortName == target_iqn), None)
        target_device_id = next((
            device.Id for device
            in TARGET_DEVICES
            if device.TargetPortId == target_port.Id), None)
        target_lun = next((
            unit.Lun.Quad for unit
            in LOGICAL_UNITS
            if unit.VirtualTargetDeviceId == target_device_id), None)
        self.assertEqual(target_lun, result['data']['target_lun'])

        self.assertEqual('127.0.0.1:3260', result['data']['target_portal'])
        self.assertFalse(result['data']['target_discovered'])
        self.assertEqual(volume['id'], result['data']['volume_id'])
        self.assertEqual('rw', result['data']['access_mode'])
        self.assertEqual('CHAP', result['data']['auth_method'])
        self.assertEqual(initiator_iqn, result['data']['auth_username'])
        self.assertIsNotNone(result['data']['auth_password'])

    def test_initialize_connection_chap_failed_check(self):
        target_port = mock.Mock(
            __class__=mock.Mock(__name__='ServeriScsiPortData'),
            Id='target_port_id2',
            PortType='iSCSI',
            PortMode='Target',
            PortName='iqn.2000-08.com.datacore:server-1-2',
            HostId='server_id1',
            PresenceStatus='Present',
            ServerPortProperties=mock.Mock(Role="Frontend",
                                           Authentication='CHAP'),
            IScsiPortStateInfo=ISCSI_PORT_STATE_INFO_READY,
            PortConfigInfo=ISCSI_PORT_CONFIG_INFO)
        ports = PORTS[:2]
        ports.append(target_port)
        self.mock_client.get_ports.return_value = ports
        self.mock_client.get_target_devices.return_value = TARGET_DEVICES
        self.mock_client.get_logical_units.return_value = LOGICAL_UNITS
        self.mock_client.get_target_domains.return_value = []

        virtual_disk = test_datacore_driver.VIRTUAL_DISKS[0]
        client = test_datacore_driver.CLIENTS[0]
        driver = self.init_driver(self.setup_default_configuration())
        volume = test_datacore_driver.VOLUME.copy()
        volume['provider_location'] = virtual_disk.Id
        initiator_iqn = PORTS[0].PortName
        connector = {
            'host': client.HostName,
            'initiator': initiator_iqn
        }
        self.assertRaises(cinder_exception.VolumeDriverException,
                          driver.initialize_connection,
                          volume,
                          connector)

    def test_initialize_connection_chap_failed_on_set_port_properties(self):
        def fail_with_datacore_fault(*args):
            raise datacore_exception.DataCoreFaultException(
                reason="General error.")

        mock_file_storage = self.mock_object(iscsi.passwd, 'FileStorage')
        mock_file_storage.return_value = test_datacore_passwd.FakeFileStorage()
        target_port = mock.Mock(
            __class__=mock.Mock(__name__='ServeriScsiPortData'),
            Id='target_port_id1',
            PortType='iSCSI',
            PortMode='Target',
            PortName='iqn.2000-08.com.datacore:server-1-1',
            HostId='server_id1',
            PresenceStatus='Present',
            ServerPortProperties=mock.Mock(Role="Frontend",
                                           Authentication='None'),
            IScsiPortStateInfo=ISCSI_PORT_STATE_INFO_READY,
            PortConfigInfo=ISCSI_PORT_CONFIG_INFO,
            iSCSINodes=mock.Mock(Node=[]))
        ports = PORTS[:2]
        ports.append(target_port)
        self.mock_client.get_ports.return_value = ports
        (self.mock_client.set_server_port_properties
         .side_effect) = fail_with_datacore_fault
        self.mock_client.get_logical_units.return_value = []
        self.mock_client.get_target_domains.return_value = []
        self.mock_client.get_target_devices.return_value = TARGET_DEVICES

        virtual_disk = test_datacore_driver.VIRTUAL_DISKS[0]
        client = test_datacore_driver.CLIENTS[0]
        config = self.setup_default_configuration()
        config.datacore_iscsi_chap_enabled = True
        config.datacore_iscsi_chap_storage = 'fake_file_path'
        driver = self.init_driver(config)
        volume = test_datacore_driver.VOLUME.copy()
        volume['provider_location'] = virtual_disk.Id
        initiator_iqn = PORTS[0].PortName
        connector = {
            'host': client.HostName,
            'initiator': initiator_iqn
        }
        self.assertRaises(datacore_exception.DataCoreFaultException,
                          driver.initialize_connection,
                          volume,
                          connector)
