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

import abc

from oslo_log import log as logging

from cinder import exception
from cinder.volume.targets import driver


LOG = logging.getLogger(__name__)


class NVMeOF(driver.Target):

    """Target object for block storage devices with RDMA transport."""

    protocol = 'nvmeof'
    target_protocol_map = {
        'nvmet_rdma': 'rdma',
    }

    def __init__(self, *args, **kwargs):
        """Reads NVMeOF configurations."""

        super(NVMeOF, self).__init__(*args, **kwargs)
        self.target_ip = self.configuration.target_ip_address
        self.target_port = self.configuration.target_port
        self.nvmet_port_id = self.configuration.nvmet_port_id
        self.nvmet_ns_id = self.configuration.nvmet_ns_id
        self.nvmet_subsystem_name = self.configuration.target_prefix
        target_protocol = self.configuration.target_protocol
        if target_protocol in self.target_protocol_map:
            self.nvme_transport_type = self.target_protocol_map[
                target_protocol]
        else:
            raise exception.UnsupportedNVMETProtocol(
                protocol=target_protocol
            )

    def initialize_connection(self, volume, connector):
        """Returns the connection info.

        In NVMeOF driver, :driver_volume_type: is set to 'nvmeof',
        :data: is the driver data that has the value of
        _get_connection_properties.

        Example return value:

        .. code-block:: json

            {
                "driver_volume_type": "nvmeof",
                "data":
                {
                    "target_portal": "1.1.1.1",
                    "target_port": 4420,
                    "nqn": "nqn.volume-0001",
                    "transport_type": "rdma",
                    "ns_id": 10
                }
            }
        """
        return {
            'driver_volume_type': self.protocol,
            'data': self._get_connection_properties(volume)
        }

    def _get_connection_properties(self, volume):
        """Gets NVMeOF connection configuration.

        :return: dictionary of the following keys:
        :target_portal: NVMe target IP address
        :target_port: NVMe target port
        :nqn: NQN of the NVMe target
        :transport_type: Network fabric being used for an
        NVMe-over-Fabrics network
        :ns_id: namespace id associated with the subsystem
        """

        location = volume['provider_location']
        target_connection, nvme_transport_type, nqn, nvmet_ns_id = (
            location.split(' '))
        target_portal, target_port = target_connection.split(':')

        return {
            'target_portal': target_portal,
            'target_port': target_port,
            'nqn': nqn,
            'transport_type': nvme_transport_type,
            'ns_id': nvmet_ns_id
        }

    def get_nvmeof_location(self, nqn, target_ip, target_port,
                            nvme_transport_type, nvmet_ns_id):
        """Serializes driver data into single line string."""

        return "%(ip)s:%(port)s %(transport)s %(nqn)s %(ns_id)s" % (
            {'ip': target_ip,
             'port': target_port,
             'transport': nvme_transport_type,
             'nqn': nqn,
             'ns_id': nvmet_ns_id})

    def terminate_connection(self, volume, connector, **kwargs):
        pass

    def create_export(self, context, volume, volume_path):
        """Creates export data for a logical volume."""

        return self.create_nvmeof_target(
            volume['id'],
            self.configuration.target_prefix,
            self.target_ip,
            self.target_port,
            self.nvme_transport_type,
            self.nvmet_port_id,
            self.nvmet_ns_id,
            volume_path)

    def ensure_export(self, context, volume, volume_path):
        pass

    def remove_export(self, context, volume):
        return self.delete_nvmeof_target(volume)

    def validate_connector(self, connector):
        if 'initiator' not in connector:
            LOG.error('The volume driver requires the NVMe initiator '
                      'name in the connector.')
            raise exception.InvalidConnectorException(
                missing='initiator')
        return True

    @abc.abstractmethod
    def create_nvmeof_target(self,
                             volume_id,
                             subsystem_name,
                             target_ip,
                             target_port,
                             transport_type,
                             nvmet_port_id,
                             ns_id,
                             volume_path):
        pass

    @abc.abstractmethod
    def delete_nvmeof_target(self, target_name):
        pass
