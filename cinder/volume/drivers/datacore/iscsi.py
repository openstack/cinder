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

"""iSCSI Driver for DataCore SANsymphony storage array."""

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils

from cinder import exception as cinder_exception
from cinder.i18n import _
from cinder import interface
from cinder import utils as cinder_utils
from cinder.volume.drivers.datacore import driver
from cinder.volume.drivers.datacore import exception as datacore_exception
from cinder.volume.drivers.datacore import passwd
from cinder.volume.drivers.datacore import utils as datacore_utils
from cinder.volume import utils as volume_utils


LOG = logging.getLogger(__name__)

datacore_iscsi_opts = [
    cfg.ListOpt('datacore_iscsi_unallowed_targets',
                default=[],
                help='List of iSCSI targets that cannot be used to attach '
                     'volume. To prevent the DataCore iSCSI volume driver '
                     'from using some front-end targets in volume attachment, '
                     'specify this option and list the iqn and target machine '
                     'for each target as the value, such as '
                     '<iqn:target name>, <iqn:target name>, '
                     '<iqn:target name>.'),
    cfg.BoolOpt('datacore_iscsi_chap_enabled',
                default=False,
                help='Configure CHAP authentication for iSCSI connections.'),
    cfg.StrOpt('datacore_iscsi_chap_storage',
               default=None,
               help='iSCSI CHAP authentication password storage file.'),
]

CONF = cfg.CONF
CONF.register_opts(datacore_iscsi_opts)


@interface.volumedriver
class ISCSIVolumeDriver(driver.DataCoreVolumeDriver):
    """DataCore SANsymphony iSCSI volume driver.

    Version history:

    .. code-block:: none

        1.0.0 - Initial driver

    """

    VERSION = '1.0.0'
    STORAGE_PROTOCOL = 'iSCSI'
    CI_WIKI_NAME = 'DataCore_CI'

    # TODO(jsbryant) Remove driver in Stein if CI is not fixed
    SUPPORTED = False

    def __init__(self, *args, **kwargs):
        super(ISCSIVolumeDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(datacore_iscsi_opts)
        self._password_storage = None

    def do_setup(self, context):
        """Perform validations and establish connection to server.

        :param context: Context information
        """

        super(ISCSIVolumeDriver, self).do_setup(context)

        password_storage_path = getattr(self.configuration,
                                        'datacore_iscsi_chap_storage', None)
        if (self.configuration.datacore_iscsi_chap_enabled
                and not password_storage_path):
            raise cinder_exception.InvalidInput(
                _("datacore_iscsi_chap_storage not set."))
        elif password_storage_path:
            self._password_storage = passwd.PasswordFileStorage(
                self.configuration.datacore_iscsi_chap_storage)

    def validate_connector(self, connector):
        """Fail if connector doesn't contain all the data needed by the driver.

        :param connector: Connector information
        """

        required_data = ['host', 'initiator']
        for required in required_data:
            if required not in connector:
                LOG.error("The volume driver requires %(data)s "
                          "in the connector.", {'data': required})
                raise cinder_exception.InvalidConnectorException(
                    missing=required)

    def initialize_connection(self, volume, connector):
        """Allow connection to connector and return connection info.

        :param volume: Volume object
        :param connector: Connector information
        :return: Connection information
        """

        LOG.debug("Initialize connection for volume %(volume)s for "
                  "connector %(connector)s.",
                  {'volume': volume['id'], 'connector': connector})

        virtual_disk = self._get_virtual_disk_for(volume, raise_not_found=True)

        if virtual_disk.DiskStatus != 'Online':
            LOG.warning("Attempting to attach virtual disk %(disk)s "
                        "that is in %(state)s state.",
                        {'disk': virtual_disk.Id,
                         'state': virtual_disk.DiskStatus})

        server_group = self._get_our_server_group()

        @cinder_utils.synchronized(
            'datacore-backend-%s' % server_group.Id, external=True)
        def serve_virtual_disk():
            available_ports = self._api.get_ports()

            iscsi_initiator = self._get_initiator(connector['host'],
                                                  connector['initiator'],
                                                  available_ports)

            iscsi_targets = self._get_targets(virtual_disk, available_ports)

            if not iscsi_targets:
                msg = (_("Suitable targets not found for "
                         "virtual disk %(disk)s for volume %(volume)s.")
                       % {'disk': virtual_disk.Id, 'volume': volume['id']})
                LOG.error(msg)
                raise cinder_exception.VolumeDriverException(message=msg)

            auth_params = self._setup_iscsi_chap_authentication(
                iscsi_targets, iscsi_initiator)

            virtual_logical_units = self._map_virtual_disk(
                virtual_disk, iscsi_targets, iscsi_initiator)

            return iscsi_targets, virtual_logical_units, auth_params

        targets, logical_units, chap_params = serve_virtual_disk()

        target_portal = datacore_utils.build_network_address(
            targets[0].PortConfigInfo.PortalsConfig.iScsiPortalConfigInfo[0]
            .Address.Address,
            targets[0].PortConfigInfo.PortalsConfig.iScsiPortalConfigInfo[0]
            .TcpPort)

        connection_data = {}

        if chap_params:
            connection_data['auth_method'] = 'CHAP'
            connection_data['auth_username'] = chap_params[0]
            connection_data['auth_password'] = chap_params[1]

        connection_data['target_discovered'] = False
        connection_data['target_iqn'] = targets[0].PortName
        connection_data['target_portal'] = target_portal
        connection_data['target_lun'] = logical_units[targets[0]].Lun.Quad
        connection_data['volume_id'] = volume['id']
        connection_data['access_mode'] = 'rw'

        LOG.debug("Connection data: %s", connection_data)

        return {
            'driver_volume_type': 'iscsi',
            'data': connection_data,
        }

    def _map_virtual_disk(self, virtual_disk, targets, initiator):
        logical_disks = self._api.get_logical_disks()

        logical_units = {}
        created_mapping = {}
        created_devices = []
        created_domains = []
        try:
            for target in targets:
                target_domain = self._get_target_domain(target, initiator)
                if not target_domain:
                    target_domain = self._api.create_target_domain(
                        initiator.HostId, target.HostId)
                    created_domains.append(target_domain)

                nexus = self._api.build_scsi_port_nexus_data(
                    initiator.Id, target.Id)

                target_device = self._get_target_device(
                    target_domain, target, initiator)
                if not target_device:
                    target_device = self._api.create_target_device(
                        target_domain.Id, nexus)
                    created_devices.append(target_device)

                logical_disk = self._get_logical_disk_on_host(
                    virtual_disk.Id, target.HostId, logical_disks)

                logical_unit = self._get_logical_unit(
                    logical_disk, target_device)
                if not logical_unit:
                    logical_unit = self._create_logical_unit(
                        logical_disk, nexus, target_device)
                    created_mapping[logical_unit] = target_device
                logical_units[target] = logical_unit
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception("Mapping operation for virtual disk %(disk)s "
                              "failed with error.",
                              {'disk': virtual_disk.Id})
                try:
                    for logical_unit in created_mapping:
                        nexus = self._api.build_scsi_port_nexus_data(
                            created_mapping[logical_unit].InitiatorPortId,
                            created_mapping[logical_unit].TargetPortId)
                        self._api.unmap_logical_disk(
                            logical_unit.LogicalDiskId, nexus)
                    for target_device in created_devices:
                        self._api.delete_target_device(target_device.Id)
                    for target_domain in created_domains:
                        self._api.delete_target_domain(target_domain.Id)
                except datacore_exception.DataCoreException as e:
                    LOG.warning("An error occurred on a cleanup after "
                                "failed mapping operation: %s.", e)

        return logical_units

    def _get_target_domain(self, target, initiator):
        target_domains = self._api.get_target_domains()
        target_domain = datacore_utils.get_first_or_default(
            lambda domain: (domain.InitiatorHostId == initiator.HostId
                            and domain.TargetHostId == target.HostId),
            target_domains,
            None)
        return target_domain

    def _get_target_device(self, target_domain, target, initiator):
        target_devices = self._api.get_target_devices()
        target_device = datacore_utils.get_first_or_default(
            lambda device: (device.TargetDomainId == target_domain.Id
                            and device.InitiatorPortId == initiator.Id
                            and device.TargetPortId == target.Id),
            target_devices,
            None)
        return target_device

    def _get_logical_unit(self, logical_disk, target_device):
        logical_units = self._api.get_logical_units()
        logical_unit = datacore_utils.get_first_or_default(
            lambda unit: (unit.LogicalDiskId == logical_disk.Id
                          and unit.VirtualTargetDeviceId == target_device.Id),
            logical_units,
            None)
        return logical_unit

    def _create_logical_unit(self, logical_disk, nexus, target_device):
        free_lun = self._api.get_next_free_lun(target_device.Id)
        logical_unit = self._api.map_logical_disk(logical_disk.Id,
                                                  nexus,
                                                  free_lun,
                                                  logical_disk.ServerHostId,
                                                  'Client')
        return logical_unit

    def _check_iscsi_chap_configuration(self, iscsi_chap_enabled, targets):
        logical_units = self._api.get_logical_units()
        target_devices = self._api.get_target_devices()

        for logical_unit in logical_units:
            target_device_id = logical_unit.VirtualTargetDeviceId
            target_device = datacore_utils.get_first(
                lambda device, key=target_device_id: device.Id == key,
                target_devices)
            target_port_id = target_device.TargetPortId
            target = datacore_utils.get_first_or_default(
                lambda target_port, key=target_port_id: target_port.Id == key,
                targets,
                None)
            if (target and iscsi_chap_enabled ==
                    (target.ServerPortProperties.Authentication == 'None')):
                msg = _("iSCSI CHAP authentication can't be configured for "
                        "target %s. Device exists that served through "
                        "this target.") % target.PortName
                LOG.error(msg)
                raise cinder_exception.VolumeDriverException(message=msg)

    def _setup_iscsi_chap_authentication(self, targets, initiator):
        iscsi_chap_enabled = self.configuration.datacore_iscsi_chap_enabled

        self._check_iscsi_chap_configuration(iscsi_chap_enabled, targets)

        server_group = self._get_our_server_group()
        update_access_token = False
        access_token = None
        chap_secret = None
        if iscsi_chap_enabled:
            authentication = 'CHAP'
            chap_secret = self._password_storage.get_password(
                server_group.Id, initiator.PortName)
            update_access_token = False
            if not chap_secret:
                chap_secret = volume_utils.generate_password(length=15)
                self._password_storage.set_password(
                    server_group.Id, initiator.PortName, chap_secret)
                update_access_token = True
            access_token = self._api.build_access_token(
                initiator.PortName,
                None,
                None,
                False,
                initiator.PortName,
                chap_secret)
        else:
            authentication = 'None'
            if self._password_storage:
                self._password_storage.delete_password(server_group.Id,
                                                       initiator.PortName)
        changed_targets = {}
        try:
            for target in targets:
                if iscsi_chap_enabled:
                    target_iscsi_nodes = getattr(target.iSCSINodes, 'Node', [])
                    iscsi_node = datacore_utils.get_first_or_default(
                        lambda node: node.Name == initiator.PortName,
                        target_iscsi_nodes,
                        None)
                    if (not iscsi_node
                            or not iscsi_node.AccessToken.TargetUsername
                            or update_access_token):
                        self._api.set_access_token(target.Id, access_token)
                properties = target.ServerPortProperties
                if properties.Authentication != authentication:
                    changed_targets[target] = properties.Authentication
                    properties.Authentication = authentication
                    self._api.set_server_port_properties(
                        target.Id, properties)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception("Configuring of iSCSI CHAP authentication for "
                              "initiator %(initiator)s failed.",
                              {'initiator': initiator.PortName})
                try:
                    for target in changed_targets:
                        properties = target.ServerPortProperties
                        properties.Authentication = changed_targets[target]
                        self._api.set_server_port_properties(
                            target.Id, properties)
                except datacore_exception.DataCoreException as e:
                    LOG.warning("An error occurred on a cleanup after  failed "
                                "configuration of iSCSI CHAP authentication "
                                "on initiator %(initiator)s: %(error)s.",
                                {'initiator': initiator.PortName, 'error': e})
        if iscsi_chap_enabled:
            return initiator.PortName, chap_secret

    def _get_initiator(self, host, iqn, available_ports):
        client = self._get_client(host, create_new=True)

        iscsi_initiator_ports = self._get_host_iscsi_initiator_ports(
            client, available_ports)

        iscsi_initiator = datacore_utils.get_first_or_default(
            lambda port: port.PortName == iqn,
            iscsi_initiator_ports,
            None)

        if not iscsi_initiator:
            scsi_port_data = self._api.build_scsi_port_data(
                client.Id, iqn, 'Initiator', 'iSCSI')
            iscsi_initiator = self._api.register_port(scsi_port_data)
        return iscsi_initiator

    def _get_targets(self, virtual_disk, available_ports):
        unallowed_targets = self.configuration.datacore_iscsi_unallowed_targets
        iscsi_target_ports = self._get_frontend_iscsi_target_ports(
            available_ports)
        server_port_map = {}
        for target_port in iscsi_target_ports:
            if target_port.HostId in server_port_map:
                server_port_map[target_port.HostId].append(target_port)
            else:
                server_port_map[target_port.HostId] = [target_port]
        iscsi_targets = []
        if virtual_disk.FirstHostId in server_port_map:
            iscsi_targets += server_port_map[virtual_disk.FirstHostId]
        if virtual_disk.SecondHostId in server_port_map:
            iscsi_targets += server_port_map[virtual_disk.SecondHostId]
        iscsi_targets = [target for target in iscsi_targets
                         if target.PortName not in unallowed_targets]
        return iscsi_targets

    @staticmethod
    def _get_logical_disk_on_host(virtual_disk_id,
                                  host_id, logical_disks):
        logical_disk = datacore_utils.get_first(
            lambda disk: (disk.ServerHostId == host_id
                          and disk.VirtualDiskId == virtual_disk_id),
            logical_disks)
        return logical_disk

    @staticmethod
    def _is_iscsi_frontend_port(port):
        if (port.PortType == 'iSCSI'
                and port.PortMode == 'Target'
                and port.HostId
                and port.PresenceStatus == 'Present'
                and hasattr(port, 'IScsiPortStateInfo')):
            port_roles = port.ServerPortProperties.Role.split()
            port_state = (port.IScsiPortStateInfo.PortalsState
                          .PortalStateInfo[0].State)
            if 'Frontend' in port_roles and port_state == 'Ready':
                return True
        return False

    @staticmethod
    def _get_frontend_iscsi_target_ports(ports):
        return [target_port for target_port in ports
                if ISCSIVolumeDriver._is_iscsi_frontend_port(target_port)]

    @staticmethod
    def _get_host_iscsi_initiator_ports(host, ports):
        return [port for port in ports
                if port.PortType == 'iSCSI'
                and port.PortMode == 'Initiator'
                and port.HostId == host.Id]
