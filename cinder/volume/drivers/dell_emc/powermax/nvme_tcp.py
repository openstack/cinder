# Copyright (c) 2020 Dell Inc. or its subsidiaries.
# All Rights Reserved.
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
from os_brick.initiator.connectors.nvmeof import NVMeOFConnector
from oslo_log import log as logging

from cinder.common import constants as cinder_constants
from cinder import coordination
from cinder import exception
from cinder.utils import get_root_helper
from cinder.volume.drivers.dell_emc.powermax import common
from cinder.volume.drivers.dell_emc.powermax import nvme
from cinder.volume.drivers.dell_emc.powermax import utils

LOG = logging.getLogger(__name__)

U4P_100_VERSION = 100


class PowerMaxNVMETCPDriver(nvme.PowerMaxNVMEBaseDriver):
    """NVMe/TCP Drivers for PowerMax using Rest.

        Version history:

        .. code-block:: none

            1.0.0 - Initial driver
    """

    VERSION = "1.0.0"
    SUPPORTS_ACTIVE_ACTIVE = True
    # ThirdPartySystems wiki
    CI_WIKI_NAME = "DellEMC_PowerMAX_CI"

    driver_prefix = 'powermax'

    def __init__(self, *args, **kwargs):
        super(PowerMaxNVMETCPDriver, self).__init__(*args, **kwargs)
        self.active_backend_id = kwargs.get('active_backend_id', None)
        self.common = common.PowerMaxCommon(
            cinder_constants.NVMEOF_TCP,
            self.VERSION,
            configuration=self.configuration,
            active_backend_id=self.active_backend_id)
        self.performance = self.common.performance
        self.rest = self.common.rest
        self.nvme_connector = NVMeOFConnector(root_helper=get_root_helper())

    @classmethod
    def get_driver_options(cls):
        additional_opts = cls._get_oslo_driver_opts(
            'san_ip', 'san_login', 'san_password',
            'driver_ssl_cert_verify',
            'max_over_subscription_ratio', 'reserved_percentage',
            'replication_device')
        return common.powermax_opts + additional_opts

    def check_for_setup_error(self):
        """Validate the Unisphere version.

        This function checks the running and major versions of Unisphere
        retrieved from the REST API. If the versions are invalid or do not meet
        the minimum supported requirements, it logs appropriate warnings or
        errors and raises an exception.

        :raises InvalidConfigurationValue: If the Unisphere version does not
            meet the minimum requirements.
        """
        running_version, major_version = self.rest.get_uni_version()
        array = self.configuration.safe_get('powermax_array')
        powermax_version = self.rest.get_vmax_model(array)
        LOG.info("Unisphere running version %(running_version)s and "
                 "major version %(major_version)s",
                 {'running_version': running_version,
                  'major_version': major_version})
        LOG.info("PowerMax version %(version)s",
                 {'version': powermax_version})
        if not running_version or not major_version or not powermax_version:
            msg = ("Unable to validate Unisphere instance "
                   "or PowerMax version.")
            LOG.error(msg)
            raise exception.InvalidConfigurationValue(message=msg)
        else:
            if (int(major_version) < int(U4P_100_VERSION) or
                (powermax_version.lower() != "powermax_2500" and
                 powermax_version.lower() != "powermax_8500")):
                msg = (("Unisphere version %(running_version)s or "
                        "PowerMax version %(version)s "
                       "is not supported.") %
                       {'running_version': running_version,
                        'version': powermax_version})
                LOG.error(msg)
                raise exception.InvalidConfigurationValue(message=msg)

    @coordination.synchronized('{self.driver_prefix}-{volume.id}')
    def initialize_connection(self, volume, connector):
        """Initializes the connection and returns connection info.

        The nvme driver returns a driver_volume_type of 'nvmeof'.
        The target_nqn can be a single entry correspond to the one
        powermax array.
        Example return value:

        .. code-block:: default

            {
                'driver_volume_type': 'nvmeof',
                'data': {
                    "portals": target_portals,
                    "target_nqn": device_info['target_nqn'],
                    "volume_nguid": device_nguid,
                    "discard": True
                }
            }

        :param volume: the cinder volume object
        :param connector: the connector object
        :returns: dict -- the nvmeof dict
        """
        device_info = self.common.initialize_connection(
            volume, connector)
        if device_info:
            return self._populate_data(device_info)
        return {}

    def _populate_data(self, device_info):
        """Populate NVMe over Fabrics (NVMe-oF) connection data for a device.

        This function retrieves the necessary NVMe-oF connection
        details for the specified device, including the target NQN,
        portals, and volume NGUID.If load balancing is enabled in
        the configuration, it attempts to select the optimal port
        based on performance metrics. If an error occurs during
        this process, it falls back to default target selection.

        :param device_info: Dictionary containing device information,
         including:
            - array: The storage array ID.
            - device_id: The device identifier.
            - ips: List of IP addresses.
            - maskingview: The masking view associated with the device.
        :return: A dictionary containing NVMe-oF connection details:
            - driver_volume_type: Always "nvmeof".
            - data: A dictionary with keys:
                - portals: List of target portals as tuples
                (IP, port, protocol).
                - target_nqn: The NVMe Qualified Name for the target.
                - volume_nguid: The globally unique identifier for the volume.
                - discard: Boolean indicating discard support.
        :raises VolumeBackendAPIException: If an error occurs during port
            performance analysis or target selection.
        """
        device_nguid = self.rest.get_device_nguid(device_info['array'],
                                                  device_info['device_id'])
        target_portals = []
        ips = device_info['ips']
        if self.performance.config.get('load_balance'):
            try:
                masking_view = device_info.get('maskingview')
                array_id = device_info.get('array')
                # Get PG from MV
                port_group = self.rest.get_element_from_masking_view(
                    array_id, masking_view, portgroup=True)
                port_list = self.rest.get_port_ids(array_id, port_group)
                load, metric, port = self.performance.process_port_load(
                    array_id, port_list)
                LOG.info("Lowest %(met)s load port for NVMe"
                         " is %(port)s: %(load)s",
                         {'met': metric, 'port': port, 'load': load})
                port_details = self.rest.get_port(array_id, port)
                port_info = port_details.get('symmetrixPort')
                ips = port_info.get('ip_addresses')
                for ip in ips:
                    (target_portals.
                     append((ip, utils.POWERMAX_NVME_TCP_PORT,
                             utils.POWERMAX_NVME_TRANSPORT_PROTOCOL_TCP)))
            except exception.VolumeBackendAPIException:
                LOG.error("There was an error calculating port load, "
                          "reverting to default target selection.")
                for ip in ips:
                    (target_portals.
                     append((ip, utils.POWERMAX_NVME_TCP_PORT,
                             utils.POWERMAX_NVME_TRANSPORT_PROTOCOL_TCP)))
        else:
            for ip in ips:
                (target_portals.
                 append((ip, utils.POWERMAX_NVME_TCP_PORT,
                         utils.POWERMAX_NVME_TRANSPORT_PROTOCOL_TCP)))
        target_nqn = (self.common.get_target_nqn(target_portals,
                                                 self.nvme_connector))
        return {
            "driver_volume_type": "nvmeof",
            "data": {
                "portals": target_portals,
                "target_nqn": target_nqn,
                "volume_nguid": device_nguid,
                "discard": True
            },
        }

    def _update_volume_stats(self):
        """Retrieve stats info from volume group."""
        LOG.debug("Updating volume stats")
        data = self.common.update_volume_stats()
        data['storage_protocol'] = cinder_constants.NVMEOF_TCP
        data['driver_version'] = self.VERSION
        self._stats = data
