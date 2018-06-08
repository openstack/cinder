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

"""Unit tests for classes that are used to invoke DataCore SANsymphony API."""

import mock
from oslo_utils import units
import six
import suds
from suds.sax import parser
from suds import wsdl

from cinder import test
from cinder.volume.drivers.datacore import api
from cinder.volume.drivers.datacore import exception


class FakeWebSocketException(Exception):
    pass


class DataCoreClientTestCase(test.TestCase):
    """Tests for the DataCore SANsymphony client."""

    def setUp(self):
        super(DataCoreClientTestCase, self).setUp()
        self.mock_storage_services = mock.MagicMock()
        self.mock_executive_service = mock.MagicMock()

        self.mock_suds_client = mock.MagicMock()
        self.mock_object(
            api.suds_client, 'Client', return_value=self.mock_suds_client)

        self.mock_channel = mock.MagicMock()
        mock_websocket = self.mock_object(api, 'websocket')
        mock_websocket.WebSocketException = FakeWebSocketException
        mock_websocket.create_connection.return_value = self.mock_channel

        setattr(self.mock_suds_client.service.__getitem__,
                'side_effect',
                self._get_service_side_effect)

        self.client = api.DataCoreClient('hostname', 'username', 'password', 1)
        self.client.API_RETRY_INTERVAL = 0

        # Make sure failure logging does not get emitted during testing
        self.mock_object(api, 'LOG')

    def _get_service_side_effect(self, service_name):
        self.assertIn(service_name,
                      [
                          api.DataCoreClient.STORAGE_SERVICES_BINDING,
                          api.DataCoreClient.EXECUTIVE_SERVICE_BINDING
                      ])

        if service_name is api.DataCoreClient.STORAGE_SERVICES_BINDING:
            return self.mock_storage_services
        else:
            return self.mock_executive_service

    def _assert_storage_services_method_called(self, method_name):
        return self.mock_storage_services.__getitem__.assert_called_with(
            method_name)

    @property
    def mock_storage_service_context(self):
        return self.mock_storage_services.__getitem__()()

    @property
    def mock_executive_service_context(self):
        return self.mock_executive_service.__getitem__()()

    def test_process_request_failed(self):
        def fail_with_socket_error():
            raise FakeWebSocketException()

        def fail_with_web_fault(message):
            fault = mock.Mock()
            fault.faultstring = "General error."
            document = mock.Mock()
            raise suds.WebFault(fault, document)

        self.mock_channel.recv.side_effect = fail_with_socket_error
        self.assertRaises(exception.DataCoreConnectionException,
                          self.client.get_server_groups)
        self.mock_channel.recv.side_effect = None

        (self.mock_storage_service_context.process_reply
         .side_effect) = fail_with_web_fault
        self.assertRaises(exception.DataCoreFaultException,
                          self.client.get_server_groups)

    def test_channel_closing_failed(self):
        def fail_with_socket_error():
            raise FakeWebSocketException()

        def fail_with_web_fault(message):
            fault = mock.Mock()
            fault.faultstring = "General error."
            document = mock.Mock()
            raise suds.WebFault(fault, document)

        self.mock_channel.close.side_effect = fail_with_socket_error
        (self.mock_storage_service_context.process_reply
         .side_effect) = fail_with_web_fault
        self.assertRaises(exception.DataCoreFaultException,
                          self.client.get_server_groups)

    def test_update_api_endpoints(self):
        def fail_with_socket_error():
            try:
                raise FakeWebSocketException()
            finally:
                self.mock_channel.recv.side_effect = None

        self.mock_channel.recv.side_effect = fail_with_socket_error

        mock_executive_endpoints = [{
            'network_address': '127.0.0.1:3794',
            'http_endpoint': 'http://127.0.0.1:3794/',
            'ws_endpoint': 'ws://127.0.0.1:3794/',
        }]
        self.mock_object(self.client,
                         '_executive_service_endpoints',
                         mock_executive_endpoints)

        mock_storage_endpoint = {
            'network_address': '127.0.0.1:3794',
            'http_endpoint': 'http://127.0.0.1:3794/',
            'ws_endpoint': 'ws://127.0.0.1:3794/',
        }
        self.mock_object(self.client,
                         '_storage_services_endpoint',
                         mock_storage_endpoint)

        node = mock.Mock()
        node.HostAddress = '127.0.0.1:3794'
        reply = mock.MagicMock()
        reply.RegionNodeData = [node]
        self.mock_storage_service_context.process_reply.return_value = reply

        result = self.client.get_server_groups()
        self.assertIsNotNone(result)

    def test_update_api_endpoints_failed(self):
        def fail_with_socket_error():
            try:
                raise FakeWebSocketException()
            finally:
                self.mock_channel.recv.side_effect = None

        self.mock_channel.recv.side_effect = fail_with_socket_error

        mock_executive_endpoints = [{
            'network_address': '127.0.0.1:3794',
            'http_endpoint': 'http://127.0.0.1:3794/',
            'ws_endpoint': 'ws://127.0.0.1:3794/',
        }]
        self.mock_object(self.client,
                         '_executive_service_endpoints',
                         mock_executive_endpoints)

        reply = mock.MagicMock()
        reply.RegionNodeData = []
        self.mock_storage_service_context.process_reply.return_value = reply

        self.mock_executive_service_context.process_reply.return_value = None

        result = self.client.get_server_groups()
        self.assertIsNotNone(result)

    def test_get_server_groups(self):
        self.client.get_server_groups()
        self._assert_storage_services_method_called('GetServerGroups')

    def test_get_servers(self):
        self.client.get_servers()
        self._assert_storage_services_method_called('GetServers')

    def test_get_disk_pools(self):
        self.client.get_disk_pools()
        self._assert_storage_services_method_called('GetDiskPools')

    def test_get_logical_disks(self):
        self.client.get_logical_disks()
        self._assert_storage_services_method_called('GetLogicalDisks')

    def test_create_pool_logical_disk(self):
        pool_id = 'pool_id'
        pool_volume_type = 'Striped'
        size = 1 * units.Gi
        min_quota = 1
        max_quota = 1 * units.Gi
        self.client.create_pool_logical_disk(
            pool_id, pool_volume_type, size, min_quota, max_quota)
        self._assert_storage_services_method_called('CreatePoolLogicalDisk')

    def test_delete_logical_disk(self):
        logical_disk_id = 'disk_id'
        self.client.delete_logical_disk(logical_disk_id)
        self._assert_storage_services_method_called('DeleteLogicalDisk')

    def test_get_logical_disk_chunk_allocation_map(self):
        logical_disk_id = 'disk_id'
        self.client.get_logical_disk_chunk_allocation_map(logical_disk_id)
        self._assert_storage_services_method_called(
            'GetLogicalDiskChunkAllocationMap')

    def test_get_next_virtual_disk_alias(self):
        base_alias = 'volume'
        self.client.get_next_virtual_disk_alias(base_alias)
        self._assert_storage_services_method_called('GetNextVirtualDiskAlias')

    def test_get_virtual_disks(self):
        self.client.get_virtual_disks()
        self._assert_storage_services_method_called('GetVirtualDisks')

    def test_build_virtual_disk_data(self):
        disk_alias = 'alias'
        disk_type = 'Mirrored'
        size = 1 * units.Gi
        description = 'description'
        storage_profile_id = 'storage_profile_id'

        vd_data = self.client.build_virtual_disk_data(
            disk_alias, disk_type, size, description, storage_profile_id)

        self.assertEqual(disk_alias, vd_data.Alias)
        self.assertEqual(size, vd_data.Size.Value)
        self.assertEqual(description, vd_data.Description)
        self.assertEqual(storage_profile_id, vd_data.StorageProfileId)
        self.assertTrue(hasattr(vd_data, 'Type'))
        self.assertTrue(hasattr(vd_data, 'SubType'))
        self.assertTrue(hasattr(vd_data, 'DiskStatus'))
        self.assertTrue(hasattr(vd_data, 'RecoveryPriority'))

    def test_create_virtual_disk_ex2(self):
        disk_alias = 'alias'
        disk_type = 'Mirrored'
        size = 1 * units.Gi
        description = 'description'
        storage_profile_id = 'storage_profile_id'
        first_disk_id = 'disk_id'
        second_disk_id = 'disk_id'
        add_redundancy = True
        vd_data = self.client.build_virtual_disk_data(
            disk_alias, disk_type, size, description, storage_profile_id)
        self.client.create_virtual_disk_ex2(
            vd_data, first_disk_id, second_disk_id, add_redundancy)
        self._assert_storage_services_method_called('CreateVirtualDiskEx2')

    def test_set_virtual_disk_size(self):
        disk_id = 'disk_id'
        size = 1 * units.Gi
        self.client.set_virtual_disk_size(disk_id, size)
        self._assert_storage_services_method_called('SetVirtualDiskSize')

    def test_delete_virtual_disk(self):
        virtual_disk_id = 'disk_id'
        delete_logical_disks = True
        self.client.delete_virtual_disk(virtual_disk_id, delete_logical_disks)
        self._assert_storage_services_method_called('DeleteVirtualDisk')

    def test_serve_virtual_disks_to_host(self):
        host_id = 'host_id'
        disks = ['disk_id']
        self.client.serve_virtual_disks_to_host(host_id, disks)
        self._assert_storage_services_method_called('ServeVirtualDisksToHost')

    def test_unserve_virtual_disks_from_host(self):
        host_id = 'host_id'
        disks = ['disk_id']
        self.client.unserve_virtual_disks_from_host(host_id, disks)
        self._assert_storage_services_method_called(
            'UnserveVirtualDisksFromHost')

    def test_unserve_virtual_disks_from_port(self):
        port_id = 'port_id'
        disks = ['disk_id']
        self.client.unserve_virtual_disks_from_port(port_id, disks)
        self._assert_storage_services_method_called(
            'UnserveVirtualDisksFromPort')

    def test_bind_logical_disk(self):
        disk_id = 'disk_id'
        logical_disk_id = 'disk_id'
        role = 'Second'
        create_mirror_mappings = True
        create_client_mappings = False
        add_redundancy = True
        self.client.bind_logical_disk(
            disk_id, logical_disk_id, role, create_mirror_mappings,
            create_client_mappings, add_redundancy)
        self._assert_storage_services_method_called(
            'BindLogicalDisk')

    def test_get_snapshots(self):
        self.client.get_snapshots()
        self._assert_storage_services_method_called('GetSnapshots')

    def test_create_snapshot(self):
        disk_id = 'disk_id'
        name = 'name'
        description = 'description'
        pool_id = 'pool_id'
        snapshot_type = 'Full'
        duplicate_disk_id = False
        storage_profile_id = 'profile_id'
        self.client.create_snapshot(
            disk_id, name, description, pool_id, snapshot_type,
            duplicate_disk_id, storage_profile_id)
        self._assert_storage_services_method_called('CreateSnapshot')

    def test_delete_snapshot(self):
        snapshot_id = "snapshot_id"
        self.client.delete_snapshot(snapshot_id)
        self._assert_storage_services_method_called('DeleteSnapshot')

    def test_get_storage_profiles(self):
        self.client.get_storage_profiles()
        self._assert_storage_services_method_called('GetStorageProfiles')

    def test_designate_map_store(self):
        pool_id = 'pool_id'
        self.client.designate_map_store(pool_id)
        self._assert_storage_services_method_called('DesignateMapStore')

    def test_get_performance_by_type(self):
        types = ['DiskPoolPerformance']
        self.client.get_performance_by_type(types)
        self._assert_storage_services_method_called('GetPerformanceByType')

    def test_get_ports(self):
        self.client.get_ports()
        self._assert_storage_services_method_called('GetPorts')

    def test_build_scsi_port_data(self):
        host_id = 'host_id'
        port_name = 'port_name'
        port_mode = 'Initiator'
        port_type = 'iSCSI'

        port_data = self.client.build_scsi_port_data(
            host_id, port_name, port_mode, port_type)

        self.assertEqual(host_id, port_data.HostId)
        self.assertEqual(port_name, port_data.PortName)
        self.assertTrue(hasattr(port_data, 'PortMode'))
        self.assertTrue(hasattr(port_data, 'PortType'))

    def test_register_port(self):
        port_data = self.client.build_scsi_port_data(
            'host_id', 'port_name', 'initiator', 'iSCSI')
        self.client.register_port(port_data)
        self._assert_storage_services_method_called('RegisterPort')

    def test_assign_port(self):
        client_id = 'client_id'
        port_id = 'port_id'
        self.client.assign_port(client_id, port_id)
        self._assert_storage_services_method_called('AssignPort')

    def test_set_server_port_properties(self):
        port_id = 'port_id'
        port_properties = mock.MagicMock()
        self.client.set_server_port_properties(port_id, port_properties)
        self._assert_storage_services_method_called('SetServerPortProperties')

    def test_build_access_token(self):
        initiator_node_name = 'initiator'
        initiator_username = 'initiator_username'
        initiator_password = 'initiator_password'
        mutual_authentication = True
        target_username = 'target_username'
        target_password = 'target_password'

        access_token = self.client.build_access_token(
            initiator_node_name, initiator_username, initiator_password,
            mutual_authentication, target_username, target_password)

        self.assertEqual(initiator_node_name, access_token.InitiatorNodeName)
        self.assertEqual(initiator_username, access_token.InitiatorUsername)
        self.assertEqual(initiator_password, access_token.InitiatorPassword)
        self.assertEqual(mutual_authentication,
                         access_token.MutualAuthentication)
        self.assertEqual(target_username, access_token.TargetUsername)
        self.assertEqual(target_password, access_token.TargetPassword)

    def test_set_access_token(self):
        port_id = 'port_id'
        access_token = self.client.build_access_token(
            'initiator_name', None, None, False, 'initiator_name', 'password')
        self.client.set_access_token(port_id, access_token)
        self._assert_storage_services_method_called('SetAccessToken')

    def test_get_clients(self):
        self.client.get_clients()
        self._assert_storage_services_method_called('GetClients')

    def test_register_client(self):
        host_name = 'name'
        description = 'description'
        machine_type = 'Other'
        mode = 'PreferredServer'
        preferred_server_ids = None
        self.client.register_client(
            host_name, description, machine_type, mode, preferred_server_ids)
        self._assert_storage_services_method_called('RegisterClient')

    def test_set_client_capabilities(self):
        client_id = 'client_id'
        mpio = True
        alua = True
        self.client.set_client_capabilities(client_id, mpio, alua)
        self._assert_storage_services_method_called('SetClientCapabilities')

    def test_get_target_domains(self):
        self.client.get_target_domains()
        self._assert_storage_services_method_called('GetTargetDomains')

    def test_create_target_domain(self):
        initiator_host_id = 'host_id'
        target_host_id = 'host_id'
        self.client.create_target_domain(initiator_host_id, target_host_id)
        self._assert_storage_services_method_called('CreateTargetDomain')

    def test_delete_target_domain(self):
        domain_id = 'domain_id'
        self.client.delete_target_domain(domain_id)
        self._assert_storage_services_method_called('DeleteTargetDomain')

    def test_get_target_devices(self):
        self.client.get_target_devices()
        self._assert_storage_services_method_called('GetTargetDevices')

    def test_build_scsi_port_nexus_data(self):
        initiator_id = 'initiator_id'
        target_id = 'target_id'

        nexus = self.client.build_scsi_port_nexus_data(initiator_id, target_id)

        self.assertEqual(initiator_id, nexus.InitiatorPortId)
        self.assertEqual(target_id, nexus.TargetPortId)

    def test_create_target_device(self):
        domain_id = 'domain_id'
        nexus = self.client.build_scsi_port_nexus_data('initiator_id',
                                                       'target_id')
        self.client.create_target_device(domain_id, nexus)
        self._assert_storage_services_method_called('CreateTargetDevice')

    def test_delete_target_device(self):
        device_id = 'device_id'
        self.client.delete_target_device(device_id)
        self._assert_storage_services_method_called('DeleteTargetDevice')

    def test_get_next_free_lun(self):
        device_id = 'device_id'
        self.client.get_next_free_lun(device_id)
        self._assert_storage_services_method_called('GetNextFreeLun')

    def test_get_logical_units(self):
        self.client.get_logical_units()
        self._assert_storage_services_method_called('GetLogicalUnits')

    def test_map_logical_disk(self):
        disk_id = 'disk_id'
        lun = 0
        host_id = 'host_id'
        mapping_type = 'Client'
        initiator_id = 'initiator_id'
        target_id = 'target_id'
        nexus = self.client.build_scsi_port_nexus_data(initiator_id, target_id)
        self.client.map_logical_disk(
            disk_id, nexus, lun, host_id, mapping_type)
        self._assert_storage_services_method_called('MapLogicalDisk')

    def test_unmap_logical_disk(self):
        logical_disk_id = 'disk_id'
        nexus = self.client.build_scsi_port_nexus_data('initiator_id',
                                                       'target_id')
        self.client.unmap_logical_disk(logical_disk_id, nexus)
        self._assert_storage_services_method_called('UnmapLogicalDisk')


FAKE_WSDL_DOCUMENT = """<?xml version="1.0" encoding="utf-8"?>
<wsdl:definitions name="ExecutiveServices"
                  targetNamespace="http://tempuri.org/"
                  xmlns:wsdl="http://schemas.xmlsoap.org/wsdl/"
                  xmlns:soap="http://schemas.xmlsoap.org/wsdl/soap/"
                  xmlns:tns="http://tempuri.org/"
                  xmlns:wsa10="http://www.w3.org/2005/08/addressing"
                  xmlns:wsaw="http://www.w3.org/2006/05/addressing/wsdl">
    <wsdl:types>
        <xs:schema elementFormDefault="qualified"
                   targetNamespace="http://tempuri.org/"
                   xmlns:xs="http://www.w3.org/2001/XMLSchema">
            <xs:import
namespace="http://schemas.microsoft.com/2003/10/Serialization/Arrays"/>
            <xs:import
namespace="http://schemas.datacontract.org/2004/07/DataCore.Executive"/>
            <xs:element name="StartExecutive">
                <xs:complexType>
                    <xs:sequence/>
                </xs:complexType>
            </xs:element>
            <xs:element name="StartExecutiveResponse">
                <xs:complexType>
                    <xs:sequence/>
                </xs:complexType>
            </xs:element>
            <xs:element name="StopExecutive">
                <xs:complexType>
                    <xs:sequence/>
                </xs:complexType>
            </xs:element>
            <xs:element name="StopExecutiveResponse">
                <xs:complexType>
                    <xs:sequence/>
                </xs:complexType>
            </xs:element>
            <xs:element name="ExecutiveStarted">
                <xs:complexType>
                    <xs:sequence/>
                </xs:complexType>
            </xs:element>
            <xs:element name="ExecutiveStopped">
                <xs:complexType>
                    <xs:sequence/>
                </xs:complexType>
            </xs:element>
        </xs:schema>
    </wsdl:types>
    <wsdl:message name="IExecutiveServiceEx_StartExecutive_InputMessage">
        <wsdl:part name="parameters" element="tns:StartExecutive"/>
    </wsdl:message>
    <wsdl:message name="IExecutiveServiceEx_StartExecutive_OutputMessage">
        <wsdl:part name="parameters" element="tns:StartExecutiveResponse"/>
    </wsdl:message>
    <wsdl:message
name="IExecutiveServiceEx_StartExecutive_ExecutiveError_FaultMessage">
        <wsdl:part name="detail" element="ExecutiveError"/>
    </wsdl:message>
    <wsdl:message name="IExecutiveServiceEx_StopExecutive_InputMessage">
        <wsdl:part name="parameters" element="tns:StopExecutive"/>
    </wsdl:message>
    <wsdl:message name="IExecutiveServiceEx_StopExecutive_OutputMessage">
        <wsdl:part name="parameters" element="tns:StopExecutiveResponse"/>
    </wsdl:message>
    <wsdl:message
name="IExecutiveServiceEx_StopExecutive_ExecutiveError_FaultMessage">
        <wsdl:part name="detail" element="ExecutiveError"/>
    </wsdl:message>
    <wsdl:message
            name="IExecutiveServiceEx_ExecutiveStarted_OutputCallbackMessage">
        <wsdl:part name="parameters" element="tns:ExecutiveStarted"/>
    </wsdl:message>
    <wsdl:message
name="IExecutiveServiceEx_ExecutiveStopped_OutputCallbackMessage">
        <wsdl:part name="parameters" element="tns:ExecutiveStopped"/>
    </wsdl:message>
    <wsdl:portType name="IExecutiveServiceEx">
        <wsdl:operation name="StartExecutive">
            <wsdl:input
wsaw:Action="http://tempuri.org/IExecutiveService/StartExecutive"
message="tns:IExecutiveServiceEx_StartExecutive_InputMessage"/>
            <wsdl:output
wsaw:Action="http://tempuri.org/IExecutiveService/StartExecutiveResponse"
message="tns:IExecutiveServiceEx_StartExecutive_OutputMessage"/>
            <wsdl:fault wsaw:Action="ExecutiveError" name="ExecutiveError"
message="tns:IExecutiveServiceEx_StartExecutive_ExecutiveError_FaultMessage"/>
        </wsdl:operation>
        <wsdl:operation name="StopExecutive">
            <wsdl:input
wsaw:Action="http://tempuri.org/IExecutiveService/StopExecutive"
message="tns:IExecutiveServiceEx_StopExecutive_InputMessage"/>
            <wsdl:output
wsaw:Action="http://tempuri.org/IExecutiveService/StopExecutiveResponse"
message="tns:IExecutiveServiceEx_StopExecutive_OutputMessage"/>
            <wsdl:fault wsaw:Action="ExecutiveError" name="ExecutiveError"
message="tns:IExecutiveServiceEx_StopExecutive_ExecutiveError_FaultMessage"/>
        </wsdl:operation>
        <wsdl:operation name="ExecutiveStarted">
            <wsdl:output
wsaw:Action="http://tempuri.org/IExecutiveService/ExecutiveStarted"
message="tns:IExecutiveServiceEx_ExecutiveStarted_OutputCallbackMessage"/>
            <wsdl:fault wsaw:Action="ExecutiveError" name="ExecutiveError"
                        message="tns:"/>
        </wsdl:operation>
        <wsdl:operation name="ExecutiveStopped">
            <wsdl:output
wsaw:Action="http://tempuri.org/IExecutiveService/ExecutiveStopped"
message="tns:IExecutiveServiceEx_ExecutiveStopped_OutputCallbackMessage"/>
            <wsdl:fault wsaw:Action="ExecutiveError" name="ExecutiveError"
                        message="tns:"/>
        </wsdl:operation>
    </wsdl:portType>
    <wsdl:binding name="CustomBinding_IExecutiveServiceEx"
                  type="tns:IExecutiveServiceEx">
        <soap:binding transport="http://schemas.microsoft.com/soap/websocket"/>
        <wsdl:operation name="StartExecutive">
            <soap:operation
soapAction="http://tempuri.org/IExecutiveService/StartExecutive"
                    style="document"/>
            <wsdl:input>
                <soap:body use="literal"/>
            </wsdl:input>
            <wsdl:output>
                <soap:body use="literal"/>
            </wsdl:output>
            <wsdl:fault name="ExecutiveError">
                <soap:fault use="literal" name="ExecutiveError" namespace=""/>
            </wsdl:fault>
        </wsdl:operation>
        <wsdl:operation name="StopExecutive">
            <soap:operation
soapAction="http://tempuri.org/IExecutiveService/StopExecutive"
                    style="document"/>
            <wsdl:input>
                <soap:body use="literal"/>
            </wsdl:input>
            <wsdl:output>
                <soap:body use="literal"/>
            </wsdl:output>
            <wsdl:fault name="ExecutiveError">
                <soap:fault use="literal" name="ExecutiveError" namespace=""/>
            </wsdl:fault>
        </wsdl:operation>
        <wsdl:operation name="ExecutiveStarted">
            <soap:operation
soapAction="http://tempuri.org/IExecutiveService/ExecutiveStarted"
                    style="document"/>
            <wsdl:output>
                <soap:body use="literal"/>
            </wsdl:output>
            <wsdl:fault name="ExecutiveError">
                <soap:fault use="literal" name="ExecutiveError" namespace=""/>
            </wsdl:fault>
        </wsdl:operation>
        <wsdl:operation name="ExecutiveStopped">
            <soap:operation
soapAction="http://tempuri.org/IExecutiveService/ExecutiveStopped"
                    style="document"/>
            <wsdl:output>
                <soap:body use="literal"/>
            </wsdl:output>
            <wsdl:fault name="ExecutiveError">
                <soap:fault use="literal" name="ExecutiveError" namespace=""/>
            </wsdl:fault>
        </wsdl:operation>
    </wsdl:binding>
    <wsdl:service name="ExecutiveServices">
        <wsdl:port name="CustomBinding_IExecutiveServiceEx"
                   binding="tns:CustomBinding_IExecutiveServiceEx">
            <soap:address
                    location="ws://mns-vsp-001:3794/IExecutiveServiceEx"/>
            <wsa10:EndpointReference>
                <wsa10:Address>ws://mns-vsp-001:3794/IExecutiveServiceEx
                </wsa10:Address>
            </wsa10:EndpointReference>
        </wsdl:port>
    </wsdl:service>
</wsdl:definitions>"""


class FaultDefinitionsFilterTestCase(test.TestCase):
    """Tests for the plugin to process the DataCore API WSDL document."""

    @staticmethod
    def _binding_operation_has_fault(document, operation_name):
        for binding in document.getChildren('binding', wsdl.wsdlns):
            for operation in binding.getChildren('operation', wsdl.wsdlns):
                if operation.get('name') == operation_name:
                    fault = operation.getChildren('fault', wsdl.wsdlns)
                    if fault:
                        return True
        return False

    @staticmethod
    def _port_type_operation_has_fault(document, operation_name):
        for port_type in document.getChildren('portType', wsdl.wsdlns):
            for operation in port_type.getChildren('operation', wsdl.wsdlns):
                if operation.get('name') == operation_name:
                    fault = operation.getChildren('fault', wsdl.wsdlns)
                    if fault:
                        return True
        return False

    def _operation_has_fault(self, document, operation_name):
        _binding_has_fault = self._binding_operation_has_fault(
            document, operation_name)
        _port_type_has_fault = self._port_type_operation_has_fault(
            document, operation_name)
        self.assertEqual(_binding_has_fault, _port_type_has_fault)
        return _binding_has_fault

    def test_parsed(self):
        context = mock.Mock()
        sax = parser.Parser()
        wsdl_document = FAKE_WSDL_DOCUMENT
        if isinstance(wsdl_document, six.text_type):
            wsdl_document = wsdl_document.encode('utf-8')
        context.document = sax.parse(string=wsdl_document).root()
        self.assertTrue(self._operation_has_fault(context.document,
                                                  'StartExecutive'))
        self.assertTrue(self._operation_has_fault(context.document,
                                                  'StopExecutive'))
        self.assertTrue(self._operation_has_fault(context.document,
                                                  'ExecutiveStarted'))
        self.assertTrue(self._operation_has_fault(context.document,
                                                  'ExecutiveStopped'))
        plugin = api.FaultDefinitionsFilter()
        plugin.parsed(context)
        self.assertTrue(self._operation_has_fault(context.document,
                                                  'StartExecutive'))
        self.assertTrue(self._operation_has_fault(context.document,
                                                  'StopExecutive'))
        self.assertFalse(self._operation_has_fault(context.document,
                                                   'ExecutiveStarted'))
        self.assertFalse(self._operation_has_fault(context.document,
                                                   'ExecutiveStopped'))
