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

"""Classes to invoke DataCore SANsymphony API."""

import copy
import sys
import uuid

from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import importutils
import retrying
import six
import socket
import suds
from suds import client as suds_client
from suds import plugin
from suds.sax import attribute
from suds.sax import element
from suds import wsdl
from suds import wsse
from suds import xsd

from cinder.i18n import _
from cinder import utils as cinder_utils
from cinder.volume.drivers.datacore import exception as datacore_exceptions
from cinder.volume.drivers.datacore import utils as datacore_utils

websocket = importutils.try_import('websocket')


LOG = logging.getLogger(__name__)


class FaultDefinitionsFilter(plugin.DocumentPlugin):
    """Plugin to process the DataCore API WSDL document.

    The document plugin removes fault definitions for callback operations
    from the DataCore API WSDL.
    """

    def parsed(self, context):
        document = context.document
        tns = self._get_tns(document)

        message_qrefs = set()
        for message in self._get_wsdl_messages(document):
            message_qrefs.add((message.get('name'), tns[1]))

        bindings = self._get_wsdl_operation_bindings(document)

        for port_type in self._get_wsdl_port_types(document):
            for operation in self._get_wsdl_operations(port_type):
                self._filter_faults(
                    document, operation, bindings, message_qrefs, tns)

    @staticmethod
    def _get_tns(document):
        target_namespace = document.get('targetNamespace')
        prefix = document.findPrefix(target_namespace) or 'tns'
        return prefix, target_namespace

    @staticmethod
    def _get_wsdl_port_types(document):
        return document.getChildren('portType', wsdl.wsdlns)

    @staticmethod
    def _get_wsdl_operations(port_type):
        return port_type.getChildren('operation', wsdl.wsdlns)

    @staticmethod
    def _get_wsdl_messages(document):
        return document.getChildren('message', wsdl.wsdlns)

    @staticmethod
    def _get_wsdl_operation_bindings(document):
        bindings = []
        for binding in document.getChildren('binding', wsdl.wsdlns):
            operations = {}
            for operation in binding.getChildren('operation', wsdl.wsdlns):
                operations[operation.get('name')] = operation
            bindings.append(operations)
        return bindings

    @staticmethod
    def _filter_faults(document, operation, operation_bindings,
                       message_qrefs, tns):
        filtered_faults = {}
        for fault in operation.getChildren('fault', wsdl.wsdlns):
            fault_message = fault.get('message')
            qref = xsd.qualify(fault_message, document, tns)
            if qref not in message_qrefs:
                filtered_faults[fault.get('name')] = fault
        for fault in filtered_faults.values():
            operation.remove(fault)
        if filtered_faults:
            for binding in operation_bindings:
                filtered_binding_faults = []
                faults = binding[operation.get('name')].getChildren(
                    'fault', wsdl.wsdlns)
                for binding_fault in faults:
                    if binding_fault.get('name') in filtered_faults:
                        filtered_binding_faults.append(binding_fault)
                for binding_fault in filtered_binding_faults:
                    binding[operation.get('name')].remove(binding_fault)


class DataCoreClient(object):
    """DataCore SANsymphony client."""

    API_RETRY_INTERVAL = 10

    DATACORE_EXECUTIVE_PORT = '3794'

    STORAGE_SERVICES = 'IStorageServices'
    STORAGE_SERVICES_BINDING = 'CustomBinding_IStorageServices'

    EXECUTIVE_SERVICE = 'IExecutiveServiceEx'
    EXECUTIVE_SERVICE_BINDING = 'CustomBinding_IExecutiveServiceEx'

    NS_WSA = ('wsa', 'http://www.w3.org/2005/08/addressing')
    WSA_ANONYMOUS = 'http://www.w3.org/2005/08/addressing/anonymous'
    MUST_UNDERSTAND = attribute.Attribute('SOAP-ENV:mustUnderstand', '1')

    # Namespaces that are defined within DataCore API WSDL
    NS_DATACORE_EXECUTIVE = ('http://schemas.datacontract.org/2004/07/'
                             'DataCore.Executive')
    NS_DATACORE_EXECUTIVE_SCSI = ('http://schemas.datacontract.org/2004/07/'
                                  'DataCore.Executive.Scsi')
    NS_DATACORE_EXECUTIVE_ISCSI = ('http://schemas.datacontract.org/2004/07/'
                                   'DataCore.Executive.iSCSI')
    NS_SERIALIZATION_ARRAYS = ('http://schemas.microsoft.com/2003/10/'
                               'Serialization/Arrays')

    # Fully qualified names of objects that are defined within
    # DataCore API WSDL
    O_ACCESS_TOKEN = '{%s}AccessToken' % NS_DATACORE_EXECUTIVE_ISCSI
    O_ARRAY_OF_PERFORMANCE_TYPE = ('{%s}ArrayOfPerformanceType'
                                   % NS_DATACORE_EXECUTIVE)
    O_ARRAY_OF_STRING = '{%s}ArrayOfstring' % NS_SERIALIZATION_ARRAYS
    O_CLIENT_MACHINE_TYPE = '{%s}ClientMachineType' % NS_DATACORE_EXECUTIVE
    O_DATA_SIZE = '{%s}DataSize' % NS_DATACORE_EXECUTIVE
    O_LOGICAL_DISK_ROLE = '{%s}LogicalDiskRole' % NS_DATACORE_EXECUTIVE
    O_LOGICAL_UNIT_TYPE = '{%s}LogicalUnitType' % NS_DATACORE_EXECUTIVE
    O_MIRROR_RECOVERY_PRIORITY = ('{%s}MirrorRecoveryPriority'
                                  % NS_DATACORE_EXECUTIVE)
    O_PATH_POLICY = '{%s}PathPolicy' % NS_DATACORE_EXECUTIVE
    O_PERFORMANCE_TYPE = '{%s}PerformanceType' % NS_DATACORE_EXECUTIVE
    O_POOL_VOLUME_TYPE = '{%s}PoolVolumeType' % NS_DATACORE_EXECUTIVE
    O_SNAPSHOT_TYPE = '{%s}SnapshotType' % NS_DATACORE_EXECUTIVE
    O_SCSI_MODE = '{%s}ScsiMode' % NS_DATACORE_EXECUTIVE_SCSI
    O_SCSI_PORT_DATA = '{%s}ScsiPortData' % NS_DATACORE_EXECUTIVE
    O_SCSI_PORT_NEXUS_DATA = '{%s}ScsiPortNexusData' % NS_DATACORE_EXECUTIVE
    O_SCSI_PORT_TYPE = '{%s}ScsiPortType' % NS_DATACORE_EXECUTIVE_SCSI
    O_VIRTUAL_DISK_DATA = '{%s}VirtualDiskData' % NS_DATACORE_EXECUTIVE
    O_VIRTUAL_DISK_STATUS = '{%s}VirtualDiskStatus' % NS_DATACORE_EXECUTIVE
    O_VIRTUAL_DISK_SUB_TYPE = '{%s}VirtualDiskSubType' % NS_DATACORE_EXECUTIVE
    O_VIRTUAL_DISK_TYPE = '{%s}VirtualDiskType' % NS_DATACORE_EXECUTIVE

    def __init__(self, host, username, password, timeout):
        if websocket is None:
            msg = _("Failed to import websocket-client python module."
                    " Please, ensure the module is installed.")
            raise datacore_exceptions.DataCoreException(msg)

        self.timeout = timeout

        executive_service_net_addr = datacore_utils.build_network_address(
            host, self.DATACORE_EXECUTIVE_PORT)
        executive_service_endpoint = self._build_service_endpoint(
            executive_service_net_addr, self.EXECUTIVE_SERVICE)

        security_options = wsse.Security()
        username_token = wsse.UsernameToken(username, password)
        security_options.tokens.append(username_token)

        self._executive_service_client = suds_client.Client(
            executive_service_endpoint['http_endpoint'] + '?singlewsdl',
            nosend=True,
            timeout=self.timeout,
            wsse=security_options,
            plugins=[FaultDefinitionsFilter()])

        self._update_storage_services_endpoint(executive_service_endpoint)

        storage_services_endpoint = self._get_storage_services_endpoint()

        self._storage_services_client = suds_client.Client(
            storage_services_endpoint['http_endpoint'] + '?singlewsdl',
            nosend=True,
            timeout=self.timeout,
            wsse=security_options,
            plugins=[FaultDefinitionsFilter()])

        self._update_executive_service_endpoints(storage_services_endpoint)

    @staticmethod
    def _get_list_data(obj, attribute_name):
        return getattr(obj, attribute_name, [])

    @staticmethod
    def _build_service_endpoint(network_address, path):
        return {
            'network_address': network_address,
            'http_endpoint': '%s://%s/%s' % ('http', network_address, path),
            'ws_endpoint': '%s://%s/%s' % ('ws', network_address, path),
        }

    @cinder_utils.synchronized('datacore-api-request_context')
    def _get_soap_context(self, service_client, service_binding, method,
                          message_id, *args, **kwargs):
        soap_action = (service_client.wsdl.services[0].port(service_binding)
                       .methods[method].soap.action)

        soap_headers = self._get_soap_headers(soap_action, message_id)

        service_client.set_options(soapheaders=soap_headers)
        context = service_client.service[service_binding][method](
            *args, **kwargs)

        return context

    def _get_soap_headers(self, soap_action, message_id):
        headers = [
            element.Element('Action', ns=self.NS_WSA)
            .setText(soap_action.replace('"', ''))
            .append(self.MUST_UNDERSTAND),

            element.Element('To', ns=self.NS_WSA)
            .setText(self.WSA_ANONYMOUS)
            .append(self.MUST_UNDERSTAND),

            element.Element('MessageID', ns=self.NS_WSA)
            .setText(message_id),

            element.Element('ReplyTo', ns=self.NS_WSA)
            .insert(element.Element('Address', ns=self.NS_WSA)
                    .setText(self.WSA_ANONYMOUS)),
        ]
        return headers

    def _process_request(self, service_client, service_binding,
                         service_endpoint, method, *args, **kwargs):
        message_id = uuid.uuid4().urn

        context = self._get_soap_context(
            service_client, service_binding,
            method, message_id, *args, **kwargs)

        channel = None
        try:
            channel = websocket.create_connection(
                service_endpoint,
                timeout=self.timeout,
                subprotocols=['soap'],
                header=['soap-content-type: text/xml'])
            channel.send(context.envelope)
            response = channel.recv()
            if isinstance(response, six.text_type):
                response = response.encode('utf-8')
            return context.process_reply(response)
        except (socket.error, websocket.WebSocketException) as e:
            traceback = sys.exc_info()[2]
            error = datacore_exceptions.DataCoreConnectionException(reason=e)
            six.reraise(datacore_exceptions.DataCoreConnectionException,
                        error,
                        traceback)
        except suds.WebFault as e:
            traceback = sys.exc_info()[2]
            fault = datacore_exceptions.DataCoreFaultException(reason=e)
            six.reraise(datacore_exceptions.DataCoreFaultException,
                        fault,
                        traceback)
        finally:
            if channel and channel.connected:
                try:
                    channel.close()
                except (socket.error, websocket.WebSocketException) as e:
                    LOG.debug("Closing a connection to "
                              "DataCore server failed. %s", e)

    def _invoke_storage_services(self, method, *args, **kwargs):

        @retrying.retry(
            retry_on_exception=lambda e:
                isinstance(e, datacore_exceptions.DataCoreConnectionException),
            wait_fixed=self.API_RETRY_INTERVAL * 1000,
            stop_max_delay=self.timeout * 1000)
        def retry_call():
            storage_services_endpoint = self._get_storage_services_endpoint()
            try:
                result = self._process_request(
                    self._storage_services_client,
                    self.STORAGE_SERVICES_BINDING,
                    storage_services_endpoint['ws_endpoint'],
                    method, *args, **kwargs)
                return result
            except datacore_exceptions.DataCoreConnectionException:
                with excutils.save_and_reraise_exception():
                    self._update_api_endpoints()

        return retry_call()

    def _update_api_endpoints(self):
        executive_service_endpoints = self._get_executive_service_endpoints()
        for endpoint in executive_service_endpoints:
            try:
                self._update_storage_services_endpoint(endpoint)
                break
            except datacore_exceptions.DataCoreConnectionException as e:
                LOG.warning("Failed to update DataCore Server Group "
                            "endpoints. %s.", e)

        storage_services_endpoint = self._get_storage_services_endpoint()
        try:
            self._update_executive_service_endpoints(
                storage_services_endpoint)
        except datacore_exceptions.DataCoreConnectionException as e:
            LOG.warning("Failed to update DataCore Server Group "
                        "endpoints. %s.", e)

    @cinder_utils.synchronized('datacore-api-storage_services_endpoint')
    def _get_storage_services_endpoint(self):
        if self._storage_services_endpoint:
            return copy.copy(self._storage_services_endpoint)
        return None

    @cinder_utils.synchronized('datacore-api-storage_services_endpoint')
    def _update_storage_services_endpoint(self, executive_service_endpoint):
        controller_address = self._process_request(
            self._executive_service_client,
            self.EXECUTIVE_SERVICE_BINDING,
            executive_service_endpoint['ws_endpoint'],
            'GetControllerAddress')

        if not controller_address:
            msg = _("Could not determine controller node.")
            raise datacore_exceptions.DataCoreConnectionException(reason=msg)

        controller_host = controller_address.rsplit(':', 1)[0].strip('[]')
        controller_net_addr = datacore_utils.build_network_address(
            controller_host,
            self.DATACORE_EXECUTIVE_PORT)

        self._storage_services_endpoint = self._build_service_endpoint(
            controller_net_addr,
            self.STORAGE_SERVICES)

    @cinder_utils.synchronized('datacore-api-executive_service_endpoints')
    def _get_executive_service_endpoints(self):
        if self._executive_service_endpoints:
            return self._executive_service_endpoints[:]
        return []

    @cinder_utils.synchronized('datacore-api-executive_service_endpoints')
    def _update_executive_service_endpoints(self, storage_services_endpoint):
        endpoints = []
        nodes = self._get_list_data(
            self._process_request(self._storage_services_client,
                                  self.STORAGE_SERVICES_BINDING,
                                  storage_services_endpoint['ws_endpoint'],
                                  'GetNodes'),
            'RegionNodeData')

        if not nodes:
            msg = _("Could not determine executive nodes.")
            raise datacore_exceptions.DataCoreConnectionException(reason=msg)

        for node in nodes:
            host = node.HostAddress.rsplit(':', 1)[0].strip('[]')
            endpoint = self._build_service_endpoint(
                datacore_utils.build_network_address(
                    host, self.DATACORE_EXECUTIVE_PORT),
                self.EXECUTIVE_SERVICE)
            endpoints.append(endpoint)

        self._executive_service_endpoints = endpoints

    def get_server_groups(self):
        """Get all the server groups in the configuration.

        :return: A list of server group data.
        """

        return self._get_list_data(
            self._invoke_storage_services('GetServerGroups'),
            'ServerHostGroupData')

    def get_servers(self):
        """Get all the server hosts in the configuration.

        :return: A list of server host data
        """

        return self._get_list_data(
            self._invoke_storage_services('GetServers'),
            'ServerHostData')

    def get_disk_pools(self):
        """Get all the pools in the server group.

        :return: A list of disk pool data
        """

        return self._get_list_data(
            self._invoke_storage_services('GetDiskPools'),
            'DiskPoolData')

    def get_logical_disks(self):
        """Get all the logical disks defined in the system.

        :return: A list of logical disks
        """

        return self._get_list_data(
            self._invoke_storage_services('GetLogicalDisks'),
            'LogicalDiskData')

    def create_pool_logical_disk(self, pool_id, pool_volume_type, size,
                                 min_quota=None, max_quota=None):
        """Create the pool logical disk.

        :param pool_id: Pool id
        :param pool_volume_type: Type, either striped or spanned
        :param size: Size
        :param min_quota: Min quota
        :param max_quota: Max quota
        :return: New logical disk data
        """

        volume_type = getattr(self._storage_services_client.factory
                              .create(self.O_POOL_VOLUME_TYPE),
                              pool_volume_type)

        data_size = (self._storage_services_client.factory
                     .create(self.O_DATA_SIZE))
        data_size.Value = size

        data_size_min_quota = None
        if min_quota:
            data_size_min_quota = (self._storage_services_client.factory
                                   .create(self.O_DATA_SIZE))
            data_size_min_quota.Value = min_quota

        data_size_max_quota = None
        if max_quota:
            data_size_max_quota = (self._storage_services_client.factory
                                   .create(self.O_DATA_SIZE))
            data_size_max_quota.Value = max_quota

        return self._invoke_storage_services('CreatePoolLogicalDisk',
                                             poolId=pool_id,
                                             type=volume_type,
                                             size=data_size,
                                             minQuota=data_size_min_quota,
                                             maxQuota=data_size_max_quota)

    def delete_logical_disk(self, logical_disk_id):
        """Delete the logical disk.

        :param logical_disk_id: Logical disk id
        """

        self._invoke_storage_services('DeleteLogicalDisk',
                                      logicalDiskId=logical_disk_id)

    def get_logical_disk_chunk_allocation_map(self, logical_disk_id):
        """Get the logical disk chunk allocation map.

        The logical disk allocation map details all the physical disk chunks
        that are currently allocated to this logical disk.

        :param logical_disk_id: Logical disk id
        :return: A list of member allocation maps, restricted to chunks
                 allocated on to this logical disk
        """

        return self._get_list_data(
            self._invoke_storage_services('GetLogicalDiskChunkAllocationMap',
                                          logicalDiskId=logical_disk_id),
            'MemberAllocationInfoData')

    def get_next_virtual_disk_alias(self, base_alias):
        """Get the next available (unused) virtual disk alias.

        :param base_alias: Base string of the new alias
        :return: New alias
        """

        return self._invoke_storage_services('GetNextVirtualDiskAlias',
                                             baseAlias=base_alias)

    def get_virtual_disks(self):
        """Get all the virtual disks in the configuration.

        :return: A list of virtual disk's data
        """

        return self._get_list_data(
            self._invoke_storage_services('GetVirtualDisks'),
            'VirtualDiskData')

    def build_virtual_disk_data(self, virtual_disk_alias, virtual_disk_type,
                                size, description, storage_profile_id):
        """Create VirtualDiskData object.

        :param virtual_disk_alias: User-visible alias of the virtual disk,
                                   which must be unique
        :param virtual_disk_type: Virtual disk type
        :param size: Virtual disk size
        :param description: A user-readable description of the virtual disk
        :param storage_profile_id: Virtual disk storage profile
        :return: VirtualDiskData object
        """

        vd_data = (self._storage_services_client.factory
                   .create(self.O_VIRTUAL_DISK_DATA))
        vd_data.Size = (self._storage_services_client.factory
                        .create(self.O_DATA_SIZE))
        vd_data.Size.Value = size
        vd_data.Alias = virtual_disk_alias
        vd_data.Description = description
        vd_data.Type = getattr(self._storage_services_client.factory
                               .create(self.O_VIRTUAL_DISK_TYPE),
                               virtual_disk_type)
        vd_data.SubType = getattr(self._storage_services_client.factory
                                  .create(self.O_VIRTUAL_DISK_SUB_TYPE),
                                  'Standard')
        vd_data.DiskStatus = getattr(self._storage_services_client.factory
                                     .create(self.O_VIRTUAL_DISK_STATUS),
                                     'Online')
        vd_data.RecoveryPriority = getattr(
            self._storage_services_client.factory
            .create(self.O_MIRROR_RECOVERY_PRIORITY),
            'Unset')
        vd_data.StorageProfileId = storage_profile_id

        return vd_data

    def create_virtual_disk_ex2(self, virtual_disk_data, first_logical_disk_id,
                                second_logical_disk_id, add_redundancy):
        """Create a virtual disk specifying the both logical disks.

        :param virtual_disk_data: Virtual disk's properties
        :param first_logical_disk_id: Id of the logical disk to use
        :param second_logical_disk_id: Id of the second logical disk to use
        :param add_redundancy: If True, the mirror has redundant mirror paths
        :return: New virtual disk's data
        """

        return self._invoke_storage_services(
            'CreateVirtualDiskEx2',
            virtualDisk=virtual_disk_data,
            firstLogicalDiskId=first_logical_disk_id,
            secondLogicalDiskId=second_logical_disk_id,
            addRedundancy=add_redundancy)

    def set_virtual_disk_size(self, virtual_disk_id, size):
        """Change the size of a virtual disk.

        :param virtual_disk_id: Id of the virtual disk
        :param size: New size
        :return: Virtual disk's data
        """

        data_size = (self._storage_services_client.factory
                     .create(self.O_DATA_SIZE))
        data_size.Value = size

        return self._invoke_storage_services('SetVirtualDiskSize',
                                             virtualDiskId=virtual_disk_id,
                                             size=data_size)

    def delete_virtual_disk(self, virtual_disk_id, delete_logical_disks):
        """Delete a virtual disk.

        :param virtual_disk_id: Id of the virtual disk
        :param delete_logical_disks: If True, delete the associated
                                     logical disks
        """

        self._invoke_storage_services('DeleteVirtualDisk',
                                      virtualDiskId=virtual_disk_id,
                                      deleteLogicalDisks=delete_logical_disks)

    def serve_virtual_disks_to_host(self, host_id, virtual_disks):
        """Serve multiple virtual disks to a specified host.

        :param host_id: Id of the host machine
        :param virtual_disks: A list of virtual disks to serve
        :return: A list of the virtual disks actually served to the host
        """

        virtual_disk_array = (self._storage_services_client.factory
                              .create(self.O_ARRAY_OF_STRING))
        virtual_disk_array.string = virtual_disks

        return self._get_list_data(
            self._invoke_storage_services('ServeVirtualDisksToHost',
                                          hostId=host_id,
                                          virtualDisks=virtual_disk_array),
            'VirtualLogicalUnitData')

    def unserve_virtual_disks_from_host(self, host_id, virtual_disks):
        """Unserve multiple virtual disks from a specified host.

        :param host_id: Id of the host machine
        :param virtual_disks: A list of virtual disks to unserve
        """

        virtual_disk_array = (self._storage_services_client.factory
                              .create(self.O_ARRAY_OF_STRING))
        virtual_disk_array.string = virtual_disks

        self._invoke_storage_services('UnserveVirtualDisksFromHost',
                                      hostId=host_id,
                                      virtualDisks=virtual_disk_array)

    def unserve_virtual_disks_from_port(self, port_id, virtual_disks):
        """Unserve multiple virtual disks from a specified initiator port.

        :param port_id: Id of the initiator port
        :param virtual_disks: A list of virtual disks to unserve
        """

        virtual_disk_array = (self._storage_services_client.factory
                              .create(self.O_ARRAY_OF_STRING))
        virtual_disk_array.string = virtual_disks

        self._invoke_storage_services('UnserveVirtualDisksFromPort',
                                      portId=port_id,
                                      virtualDisks=virtual_disk_array)

    def bind_logical_disk(self, virtual_disk_id, logical_disk_id, role,
                          create_mirror_mappings, create_client_mappings,
                          add_redundancy):
        """Bind (add) a logical disk to a virtual disk.

        :param virtual_disk_id: Id of the virtual disk to bind to
        :param logical_disk_id: Id of the logical disk being bound
        :param role: logical disk's role
        :param create_mirror_mappings: If True, automatically create the
                                       mirror mappings to this disk, assuming
                                       there is already another logical disk
                                       bound
        :param create_client_mappings: If True, automatically create mappings
                                       from mapped hosts to the new disk
        :param add_redundancy: If True, the mirror has redundant mirror paths
        :return: Updated virtual disk data
        """

        logical_disk_role = getattr(self._storage_services_client.factory
                                    .create(self.O_LOGICAL_DISK_ROLE),
                                    role)

        return self._invoke_storage_services(
            'BindLogicalDisk',
            virtualDiskId=virtual_disk_id,
            logicalDiskId=logical_disk_id,
            role=logical_disk_role,
            createMirrorMappings=create_mirror_mappings,
            createClientMappings=create_client_mappings,
            addRedundancy=add_redundancy)

    def get_snapshots(self):
        """Get all the snapshots on all the servers in the region.

        :return: A list of snapshot data.
        """

        return self._get_list_data(
            self._invoke_storage_services('GetSnapshots'),
            'SnapshotData')

    def create_snapshot(self, virtual_disk_id, name, description,
                        destination_pool_id, snapshot_type,
                        duplicate_disk_id, storage_profile_id):
        """Create a snapshot relationship.

        :param virtual_disk_id: Virtual disk id
        :param name: Name of snapshot
        :param description: Description
        :param destination_pool_id: Destination pool id
        :param snapshot_type: Type of snapshot
        :param duplicate_disk_id: If set to True then the destination virtual
                                  disk's SCSI id will be a duplicate of the
                                  source's
        :param storage_profile_id: Specifies the destination virtual disk's
                                   storage profile
        :return: New snapshot data
        """

        st_type = getattr(self._storage_services_client.factory
                          .create(self.O_SNAPSHOT_TYPE),
                          snapshot_type)

        return self._invoke_storage_services(
            'CreateSnapshot',
            virtualDiskId=virtual_disk_id,
            name=name,
            description=description,
            destinationPoolId=destination_pool_id,
            type=st_type,
            duplicateDiskId=duplicate_disk_id,
            storageProfileId=storage_profile_id)

    def delete_snapshot(self, snapshot_id):
        """Delete the snapshot.

        :param snapshot_id: Snapshot id
        """

        self._invoke_storage_services('DeleteSnapshot', snapshotId=snapshot_id)

    def get_storage_profiles(self):
        """Get all the all the defined storage profiles.

        :return: A list of storage profiles
        """

        return self._get_list_data(
            self._invoke_storage_services('GetStorageProfiles'),
            'StorageProfileData')

    def designate_map_store(self, pool_id):
        """Designate which pool the snapshot mapstore will be allocated from.

        :param pool_id: Pool id
        :return: Updated server host data, which includes the mapstore pool id
        """

        return self._invoke_storage_services('DesignateMapStore',
                                             poolId=pool_id)

    def get_performance_by_type(self, performance_types):
        """Get performance data for specific types of performance counters.

        :param performance_types: A list of performance counter types
        :return: A list of performance data points
        """

        prfm_type_array = (self._storage_services_client.factory
                           .create(self.O_ARRAY_OF_PERFORMANCE_TYPE))
        prfm_type_array.PerformanceType = list(
            getattr(self._storage_services_client.factory
                    .create(self.O_PERFORMANCE_TYPE),
                    performance_type)
            for performance_type in performance_types)

        return self._get_list_data(
            self._invoke_storage_services('GetPerformanceByType',
                                          types=prfm_type_array),
            'CollectionPointData')

    def get_ports(self):
        """Get all ports in the configuration.

        :return: A list of SCSI ports
        """

        return self._get_list_data(
            self._invoke_storage_services('GetPorts'),
            'ScsiPortData')

    def build_scsi_port_data(self, host_id, port_name, port_mode, port_type):
        """Create ScsiPortData object that represents SCSI port, of any type.

        :param host_id: Id of the port's host computer
        :param port_name: Unique name of the port.
        :param port_mode: Mode of port: initiator or target
        :param port_type: Type of port, Fc, iSCSI or loopback
        :return: ScsiPortData object
        """

        scsi_port_data = (self._storage_services_client.factory
                          .create(self.O_SCSI_PORT_DATA))
        scsi_port_data.HostId = host_id
        scsi_port_data.PortName = port_name
        scsi_port_data.PortMode = getattr(self._storage_services_client.factory
                                          .create(self.O_SCSI_MODE),
                                          port_mode)
        scsi_port_data.PortType = getattr(self._storage_services_client.factory
                                          .create(self.O_SCSI_PORT_TYPE),
                                          port_type)

        return scsi_port_data

    def register_port(self, scsi_port_data):
        """Register a port in the configuration.

        :param scsi_port_data: Port data
        :return: Updated port data
        """

        return self._invoke_storage_services('RegisterPort',
                                             port=scsi_port_data)

    def assign_port(self, client_id, port_id):
        """Assign a port to a client.

        :param client_id: Client id
        :param port_id: Port id
        :return: Updated port data,
                 which will now have its host id set to the client id
        """

        return self._invoke_storage_services('AssignPort',
                                             clientId=client_id,
                                             portId=port_id)

    def set_server_port_properties(self, port_id, properties):
        """Set a server port's properties.

        :param port_id: Port id
        :param properties: New properties
        :return: Updated port data
        """

        return self._invoke_storage_services('SetServerPortProperties',
                                             portId=port_id,
                                             properties=properties)

    def build_access_token(self, initiator_node_name, initiator_username,
                           initiator_password, mutual_authentication,
                           target_username, target_password):
        """Create an AccessToken object.

        :param initiator_node_name: Initiator node name
        :param initiator_username: Initiator user name
        :param initiator_password: Initiator password
        :param mutual_authentication: If True the target and the initiator
                                      authenticate each other.
                                      A separate secret is set for each target
                                      and for each initiator in the storage
                                      area network (SAN).
        :param target_username: Target user name
        :param target_password: Target password
        :return: AccessToken object
        """

        access_token = (self._storage_services_client.factory
                        .create(self.O_ACCESS_TOKEN))
        access_token.InitiatorNodeName = initiator_node_name
        access_token.InitiatorUsername = initiator_username
        access_token.InitiatorPassword = initiator_password
        access_token.MutualAuthentication = mutual_authentication
        access_token.TargetUsername = target_username
        access_token.TargetPassword = target_password

        return access_token

    def set_access_token(self, iscsi_port_id, access_token):
        """Set the access token.

        The access token allows access to a specific network node
        from a specific iSCSI port.

        :param iscsi_port_id: Id of the initiator iSCSI port
        :param access_token: Access token to be validated
        :return: Port data
        """

        return self._invoke_storage_services('SetAccessToken',
                                             iScsiPortId=iscsi_port_id,
                                             inputToken=access_token)

    def get_clients(self):
        """Get all the clients in the configuration.

        :return: A list of client data
        """

        return self._get_list_data(
            self._invoke_storage_services('GetClients'),
            'ClientHostData')

    def register_client(self, host_name, description, machine_type,
                        mode, preferred_server_ids):
        """Register the client, creating a client object in the configuration.

        :param host_name: Name of the client
        :param description: Description
        :param machine_type: Type of client
        :param mode: Path policy mode of the client
        :param preferred_server_ids: Preferred server ids
        :return: New client data
        """

        client_machine_type = getattr(self._storage_services_client.factory
                                      .create(self.O_CLIENT_MACHINE_TYPE),
                                      machine_type)
        client_mode = getattr(self._storage_services_client.factory
                              .create(self.O_PATH_POLICY),
                              mode)

        return self._invoke_storage_services(
            'RegisterClient',
            hostName=host_name,
            description=description,
            type=client_machine_type,
            mode=client_mode,
            preferredServerIds=preferred_server_ids)

    def set_client_capabilities(self, client_id, mpio, alua):
        """Set the client capabilities for MPIO and ALUA.

        :param client_id: Client id
        :param mpio: If set to True then MPIO-capable
        :param alua: If set to True then ALUA-capable
        :return: Updated client data
        """

        return self._invoke_storage_services('SetClientCapabilities',
                                             clientId=client_id,
                                             mpio=mpio,
                                             alua=alua)

    def get_target_domains(self):
        """Get all the target domains in the configuration.

        :return: A list of target domains
        """

        return self._get_list_data(
            self._invoke_storage_services('GetTargetDomains'),
            'VirtualTargetDomainData')

    def create_target_domain(self, initiator_host_id, target_host_id):
        """Create a target domain given a pair of hosts, target and initiator.

        :param initiator_host_id: Id of the initiator host machine
        :param target_host_id: Id of the target host server
        :return: New target domain
        """

        return self._invoke_storage_services('CreateTargetDomain',
                                             initiatorHostId=initiator_host_id,
                                             targetHostId=target_host_id)

    def delete_target_domain(self, target_domain_id):
        """Delete a target domain.

        :param target_domain_id: Target domain id
        """

        self._invoke_storage_services('DeleteTargetDomain',
                                      targetDomainId=target_domain_id)

    def get_target_devices(self):
        """Get all the target devices in the configuration.

        :return: A list of target devices
        """

        return self._get_list_data(
            self._invoke_storage_services('GetTargetDevices'),
            'VirtualTargetDeviceData')

    def build_scsi_port_nexus_data(self, initiator_port_id, target_port_id):
        """Create a ScsiPortNexusData object.

        Nexus is a pair of ports that can communicate, one being the initiator,
        the other the target

        :param initiator_port_id: Id of the initiator port
        :param target_port_id: Id of the target port
        :return: ScsiPortNexusData object
        """

        scsi_port_nexus_data = (self._storage_services_client.factory
                                .create(self.O_SCSI_PORT_NEXUS_DATA))
        scsi_port_nexus_data.InitiatorPortId = initiator_port_id
        scsi_port_nexus_data.TargetPortId = target_port_id

        return scsi_port_nexus_data

    def create_target_device(self, target_domain_id, nexus):
        """Create a target device, given a target domain and a nexus.

        :param target_domain_id: Target domain id
        :param nexus: Nexus, or pair of ports
        :return: New target device
        """

        return self._invoke_storage_services('CreateTargetDevice',
                                             targetDomainId=target_domain_id,
                                             nexus=nexus)

    def delete_target_device(self, target_device_id):
        """Delete a target device.

        :param target_device_id: Target device id
        """

        self._invoke_storage_services('DeleteTargetDevice',
                                      targetDeviceId=target_device_id)

    def get_next_free_lun(self, target_device_id):
        """Find the next unused LUN number for a specified target device.

        :param target_device_id: Target device id
        :return: LUN number
        """

        return self._invoke_storage_services('GetNextFreeLun',
                                             targetDeviceId=target_device_id)

    def get_logical_units(self):
        """Get all the mappings configured in the system.

        :return: A list of mappings
        """

        return self._get_list_data(
            self._invoke_storage_services('GetLogicalUnits'),
            'VirtualLogicalUnitData')

    def map_logical_disk(self, logical_disk_id, nexus, lun,
                         initiator_host_id, mapping_type):
        """Map a logical disk to a host.

        :param logical_disk_id: Id of the logical disk
        :param nexus: Nexus, or pair of ports
        :param lun: Logical Unit Number
        :param initiator_host_id: Id of the initiator host machine
        :param mapping_type: Type of mapping
        :return: New mapping
        """

        logical_unit_type = getattr(self._storage_services_client.factory
                                    .create(self.O_LOGICAL_UNIT_TYPE),
                                    mapping_type)

        return self._invoke_storage_services('MapLogicalDisk',
                                             logicalDiskId=logical_disk_id,
                                             nexus=nexus,
                                             lun=lun,
                                             initiatorHostId=initiator_host_id,
                                             mappingType=logical_unit_type)

    def unmap_logical_disk(self, logical_disk_id, nexus):
        """Unmap a logical disk mapped with a specified nexus.

        :param logical_disk_id: Id of the logical disk
        :param nexus: Nexus, or pair of ports
        """

        self._invoke_storage_services('UnmapLogicalDisk',
                                      logicalDiskId=logical_disk_id,
                                      nexusData=nexus)
