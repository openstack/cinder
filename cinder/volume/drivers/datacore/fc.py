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

"""Fibre Channel Driver for DataCore SANsymphony storage array."""

from oslo_log import log as logging

from cinder import exception as cinder_exception
from cinder.i18n import _
from cinder import interface
from cinder import utils as cinder_utils
from cinder.volume.drivers.datacore import driver
from cinder.volume.drivers.datacore import exception as datacore_exception


LOG = logging.getLogger(__name__)


@interface.volumedriver
class FibreChannelVolumeDriver(driver.DataCoreVolumeDriver):
    """DataCore SANsymphony Fibre Channel volume driver.

    Version history:

    .. code-block:: none

        1.0.0 - Initial driver

    """

    VERSION = '1.0.0'
    STORAGE_PROTOCOL = 'FC'
    CI_WIKI_NAME = 'DataCore_CI'

    # TODO(jsbryant) Remove driver in Stein if CI is not fixed
    SUPPORTED = False

    def __init__(self, *args, **kwargs):
        super(FibreChannelVolumeDriver, self).__init__(*args, **kwargs)

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

        serve_result = self._serve_virtual_disk(connector, virtual_disk.Id)

        online_servers = [server.Id for server in self._get_online_servers()]
        online_ports = self._get_online_ports(online_servers)
        online_devices = self._get_online_devices(online_ports)
        online_units = [unit for unit in serve_result[1]
                        if unit.VirtualTargetDeviceId in online_devices]

        if not online_units:
            msg = (_("Volume %(volume)s can not be attached "
                     "to connector %(connector)s due to backend state.")
                   % {'volume': volume['id'], 'connector': connector})
            LOG.error(msg)
            try:
                self._api.unserve_virtual_disks_from_host(serve_result[0].Id,
                                                          [virtual_disk.Id])
            except datacore_exception.DataCoreException as e:
                LOG.warning("An error occurred on a cleanup after failed "
                            "attaching of volume %(volume)s to connector "
                            "%(connector)s: %(error)s.",
                            {'volume': volume['id'],
                             'connector': connector,
                             'error': e})
            raise cinder_exception.VolumeDriverException(message=msg)

        target_device = online_devices[online_units[0].VirtualTargetDeviceId]
        target_port = online_ports[target_device.TargetPortId]

        connection_data = {
            'target_discovered': False,
            'target_lun': online_units[0].Lun.Quad,
            'target_wwn': target_port.PortName.replace('-', '').lower(),
            'volume_id': volume['id'],
            'access_mode': 'rw',
        }

        LOG.debug("Connection data: %s", connection_data)

        return {
            'driver_volume_type': 'fibre_channel',
            'data': connection_data,
        }

    def _serve_virtual_disk(self, connector, virtual_disk_id):
        server_group = self._get_our_server_group()

        @cinder_utils.synchronized(
            'datacore-backend-%s' % server_group.Id, external=True)
        def serve_virtual_disk():
            connector_wwpns = list(wwpn.replace('-', '').lower()
                                   for wwpn in connector['wwpns'])

            client = self._get_client(connector['host'], create_new=True)

            available_ports = self._api.get_ports()

            initiators = []
            for port in available_ports:
                port_name = port.PortName.replace('-', '').lower()
                if (port.PortType == 'FibreChannel'
                        and port.PortMode == 'Initiator'
                        and port_name in connector_wwpns):
                    initiators.append(port)
            if not initiators:
                msg = _("Fibre Channel ports not found for "
                        "connector: %s") % connector
                LOG.error(msg)
                raise cinder_exception.VolumeDriverException(message=msg)
            else:
                for initiator in initiators:
                    if initiator.HostId != client.Id:
                        try:
                            self._api.assign_port(client.Id, initiator.Id)
                        except datacore_exception.DataCoreException as e:
                            LOG.info("Assigning initiator port %(initiator)s "
                                     "to client %(client)s failed with "
                                     "error: %(error)s",
                                     {'initiator': initiator.Id,
                                      'client': client.Id,
                                      'error': e})

            virtual_logical_units = self._api.serve_virtual_disks_to_host(
                client.Id, [virtual_disk_id])

            return client, virtual_logical_units

        return serve_virtual_disk()

    def _get_online_ports(self, online_servers):
        ports = self._api.get_ports()
        online_ports = {port.Id: port for port in ports
                        if port.HostId in online_servers}

        return online_ports

    def _get_online_devices(self, online_ports):
        devices = self._api.get_target_devices()
        online_devices = {device.Id: device for device in devices
                          if device.TargetPortId in online_ports}

        return online_devices
