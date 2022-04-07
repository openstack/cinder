# Copyright (c) 2022 DataCore Software Corp. All Rights Reserved.
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

"""Fibre Channel Driver for DataCore SANsymphony storage array."""

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils

from cinder.common import constants
from cinder import exception as cinder_exception
from cinder.i18n import _
from cinder import interface
from cinder import utils as cinder_utils
from cinder.volume import configuration
from cinder.volume.drivers.datacore import driver
from cinder.volume.drivers.datacore import exception as datacore_exception
from cinder.volume.drivers.datacore import utils as datacore_utils
from cinder.zonemanager import utils as fczm_utils

LOG = logging.getLogger(__name__)

datacore_fc_opts = [
    cfg.ListOpt('datacore_fc_unallowed_targets',
                default=[],
                help='List of FC targets that cannot be used to attach '
                     'volume. To prevent the DataCore FibreChannel '
                     'volume driver from using some front-end targets '
                     'in volume attachment, specify this option and list '
                     'the iqn and target machine for each target as '
                     'the value, such as '
                     '<wwpns:target name>, <wwpns:target name>, '
                     '<wwpns:target name>.'),
]

CONF = cfg.CONF
CONF.register_opts(datacore_fc_opts, group=configuration.SHARED_CONF_GROUP)


@interface.volumedriver
class FibreChannelVolumeDriver(driver.DataCoreVolumeDriver):
    """DataCore SANsymphony Fibre Channel volume driver.

    Version history:

    .. code-block:: none

        1.0.0 - Initial driver
        2.0.0 - Reintroduce the driver

    """

    VERSION = '2.0.0'
    STORAGE_PROTOCOL = constants.FC
    CI_WIKI_NAME = 'DataCore_CI'

    def __init__(self, *args, **kwargs):
        super(FibreChannelVolumeDriver, self).__init__(*args, **kwargs)
        self.configuration = kwargs.get('configuration', None)
        if self.configuration:
            self.configuration.append_config_values(datacore_fc_opts)

    @classmethod
    def get_driver_options(cls):
        additional_opts = cls._get_oslo_driver_opts(
            'san_ip', 'san_login', 'san_password')
        return driver.datacore_opts + datacore_fc_opts + additional_opts

    def validate_connector(self, connector):
        """Fail if connector doesn't contain all the data needed by the driver.

        :param connector: Connector information
        """

        required_data = ['host', 'wwpns']
        for required in required_data:
            if required not in connector:
                LOG.error("The volume driver requires %(data)s "
                          "in the connector.", {'data': required})
                raise cinder_exception.InvalidConnectorException(
                    missing=required)

    def _build_initiator_target_map(self, connector):
        target_wwns = []
        init_targ_map = {}
        initiator_wwns = []

        if connector:
            initiator_wwns = connector['wwpns']
        fc_target_ports = self._get_frontend_fc_target_ports(
            self._api.get_ports())
        for target_port in fc_target_ports:
            target_wwns.append(
                target_port.PortName.replace('-', '').lower())
        for initiator in initiator_wwns:
            init_targ_map[initiator] = target_wwns

        return init_targ_map, target_wwns

    def initialize_connection(self, volume, connector):
        """Allow connection to connector and return connection info.

        :param volume: Volume object
        :param connector: Connector information
        :return: Connection information
        """

        LOG.debug("Initialize connection for volume %(volume)s for "
                  "connector %(connector)s.",
                  {'volume': volume.id, 'connector': connector})

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

            connector_wwpns = list(wwpn.replace('-', '').lower()
                                   for wwpn in connector['wwpns'])

            fc_initiator = self._get_initiator(connector['host'],
                                               connector_wwpns,
                                               available_ports)
            if not fc_initiator:
                msg = (_("Suitable initiator not found for "
                         "virtual disk %(disk)s for volume %(volume)s.")
                       % {'disk': virtual_disk.Id, 'volume': volume.id})
                LOG.error(msg)
                raise cinder_exception.VolumeDriverException(message=msg)

            fc_targets = self._get_targets(virtual_disk, available_ports)
            if not fc_targets:
                msg = (_("Suitable targets not found for "
                         "virtual disk %(disk)s for volume %(volume)s.")
                       % {'disk': virtual_disk.Id, 'volume': volume.id})
                LOG.error(msg)
                raise cinder_exception.VolumeDriverException(message=msg)

            virtual_logical_units = self._map_virtual_disk(
                virtual_disk, fc_targets, fc_initiator)
            return fc_targets, virtual_logical_units

        targets, logical_units = serve_virtual_disk()

        init_targ_map, target_wwns = self._build_initiator_target_map(
            connector)
        info_backend = {'driver_volume_type': 'fibre_channel',
                        'data': {
                            'target_discovered': False,
                            'target_lun': logical_units[targets[0]].Lun.Quad,
                            'target_wwn': target_wwns,
                            'volume_id': volume.id,
                            'access_mode': 'rw',
                            'initiator_target_map': init_targ_map}}

        fczm_utils.add_fc_zone(info_backend)

        LOG.debug("Connection data: %s", info_backend)

        return info_backend

    def terminate_connection(self, volume, connector, **kwargs):

        init_targ_map, target_wwns = self._build_initiator_target_map(
            connector)
        info = {'driver_volume_type': 'fibre_channel', 'data': {}}
        info['data'] = {'target_wwn': target_wwns,
                        'initiator_target_map': init_targ_map}

        # First unserve the virtual disk from Host
        super().unserve_virtual_disks_from_host(volume, connector)

        fczm_utils.remove_fc_zone(info)

        return info

    def _get_initiator(self, host, connector_wwpns, available_ports):
        wwpn_list = []
        for wwp in connector_wwpns:
            wwpn_list.append('-'.join(
                a + b for a, b in zip(*[iter(wwp.upper())] * 2)))

        client = self._get_client(host, create_new=True)
        valid_initiator = self._valid_fc_initiator(wwpn_list, available_ports)
        if not valid_initiator:
            return []

        fc_initiator_ports = self._get_host_fc_initiator_ports(
            client, available_ports)
        fc_initiator = datacore_utils.get_first_or_default(
            lambda port: True if (port.PortName in wwpn_list) else False,
            fc_initiator_ports,
            None)

        if not fc_initiator:
            for wwn in wwpn_list:
                for port in available_ports:
                    if (port.PortName == wwn and
                            port.PortType == 'FibreChannel' and
                            port.PortMode == 'Initiator' and
                            port.Connected):
                        scsi_port_data = self._api.build_scsi_port_data(
                            client.Id, wwn, 'Initiator', 'FibreChannel')
                        fc_initiator = self._api.register_port(scsi_port_data)
                        return fc_initiator
        return fc_initiator

    @staticmethod
    def _get_host_fc_initiator_ports(host, ports):
        return [port for port in ports if
                port.PortType == 'FibreChannel' and port.PortMode ==
                'Initiator' and port.HostId == host.Id]

    def _get_targets(self, virtual_disk, available_ports):
        unallowed_targets = self.configuration.datacore_fc_unallowed_targets
        fc_target_ports = self._get_frontend_fc_target_ports(
            available_ports)
        server_port_map = {}

        for target_port in fc_target_ports:
            if target_port.HostId in server_port_map:
                server_port_map[target_port.HostId].append(target_port)
            else:
                server_port_map[target_port.HostId] = [target_port]
        fc_targets = []
        if virtual_disk.FirstHostId in server_port_map:
            fc_targets += server_port_map[virtual_disk.FirstHostId]
        if virtual_disk.SecondHostId in server_port_map:
            fc_targets += server_port_map[virtual_disk.SecondHostId]

        return [target for target in fc_targets
                if target.PortName not in unallowed_targets]

    @staticmethod
    def _is_fc_frontend_port(port):
        if (port.PortType == 'FibreChannel' and
                port.PortMode == 'Target' and
                port.HostId):
            if port.PresenceStatus == 'Present':
                port_roles = port.ServerPortProperties.Role.split()
                port_state = port.StateInfo.State
                if 'Frontend' in port_roles and port_state == 'LoopLinkUp':
                    return True
        return False

    def _get_frontend_fc_target_ports(self, ports):
        return [target_port for target_port in ports
                if self._is_fc_frontend_port(target_port)]

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
            lambda domain: (domain.InitiatorHostId == initiator.HostId and
                            domain.TargetHostId == target.HostId),
            target_domains, None)
        return target_domain

    def _get_target_device(self, target_domain, target, initiator):
        target_devices = self._api.get_target_devices()
        target_device = datacore_utils.get_first_or_default(
            lambda device: (device.TargetDomainId == target_domain.Id and
                            device.InitiatorPortId == initiator.Id and
                            device.TargetPortId == target.Id),
            target_devices, None)
        return target_device

    def _get_logical_unit(self, logical_disk, target_device):
        logical_units = self._api.get_logical_units()
        logical_unit = datacore_utils.get_first_or_default(
            lambda unit: (unit.LogicalDiskId == logical_disk.Id and
                          unit.VirtualTargetDeviceId == target_device.Id),
            logical_units, None)
        return logical_unit

    def _create_logical_unit(self, logical_disk, nexus, target_device):
        free_lun = self._api.get_next_free_lun(target_device.Id)
        logical_unit = self._api.map_logical_disk(logical_disk.Id,
                                                  nexus,
                                                  free_lun,
                                                  logical_disk.ServerHostId,
                                                  'Client')
        return logical_unit

    @staticmethod
    def _get_logical_disk_on_host(virtual_disk_id,
                                  host_id, logical_disks):
        logical_disk = datacore_utils.get_first(
            lambda disk: (disk.ServerHostId == host_id and
                          disk.VirtualDiskId == virtual_disk_id),
            logical_disks)
        return logical_disk

    @staticmethod
    def _valid_fc_initiator(wwpn_list, available_ports):
        for port in available_ports:
            if (port.PortType == 'FibreChannel' and
                    port.PortMode == 'Initiator'):
                if (port.PortName in wwpn_list):
                    return True
        return False
