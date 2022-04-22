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

from oslo_log import log as logging

from cinder.common import constants
from cinder import exception
from cinder.i18n import _
from cinder.volume.targets import driver


LOG = logging.getLogger(__name__)


class UnsupportedNVMETProtocol(exception.Invalid):
    message = _("An invalid 'target_protocol' "
                "value was provided: %(protocol)s")


class NVMeOF(driver.Target):

    """Target object for block storage devices with RDMA transport."""

    protocol = constants.NVMEOF_VARIANT_2
    target_protocol_map = {
        'nvmet_rdma': 'rdma',
        'nvmet_tcp': 'tcp',
    }

    def __init__(self, *args, **kwargs):
        """Reads NVMeOF configurations."""

        super(NVMeOF, self).__init__(*args, **kwargs)
        self.target_ips = ([self.configuration.target_ip_address] +
                           self.configuration.target_secondary_ip_addresses)
        self.target_port = self.configuration.target_port
        self.nvmet_port_id = self.configuration.nvmet_port_id
        self.nvmet_ns_id = self.configuration.nvmet_ns_id
        self.nvmet_subsystem_name = self.configuration.target_prefix
        # Compatibility with non lvm drivers
        self.share_targets = getattr(self.configuration,
                                     'lvm_share_target', False)
        target_protocol = self.configuration.target_protocol
        if target_protocol in self.target_protocol_map:
            self.nvme_transport_type = self.target_protocol_map[
                target_protocol]
        else:
            raise UnsupportedNVMETProtocol(
                protocol=target_protocol
            )

        # Secondary ip addresses only work with new connection info
        if (self.configuration.target_secondary_ip_addresses
                and self.configuration.nvmeof_conn_info_version == 1):
            raise exception.InvalidConfigurationValue(
                'Secondary addresses need to use NVMe-oF connection properties'
                ' format version 2 or greater (nvmeof_conn_info_version).')

    def initialize_connection(self, volume, connector):
        """Returns the connection info.

        In NVMeOF driver, :driver_volume_type: is set to 'nvmeof',
        :data: is the driver data that has the value of
        _get_connection_properties_from_vol.

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
            'data': self._get_connection_properties_from_vol(volume)
        }

    def _get_connection_properties_from_vol(self, volume):
        """Gets NVMeOF connection configuration.

        Returns the connection info based on the volume's provider_location and
        the _get_nvme_uuid method for the volume.

        For the specific data returned check the _get_connection_properties
        method.

        :return: dictionary with the connection properties using one of the 2
                 existing formats depending on the nvmeof_conn_info_version
                 configuration option.
        """
        location = volume['provider_location']
        target_connection, nvme_transport_type, nqn, nvmet_ns_id = (
            location.split(' '))
        target_portals, target_port = target_connection.split(':')
        target_portals = target_portals.split(',')

        uuid = self._get_nvme_uuid(volume)
        return self._get_connection_properties(nqn,
                                               target_portals, target_port,
                                               nvme_transport_type,
                                               nvmet_ns_id, uuid)

    def _get_connection_properties(self, nqn, portals, port, transport, ns_id,
                                   uuid):
        """Get connection properties dictionary.

        For nvmeof_conn_info_version set to 1 (default) the old format will
        be sent:
        {
         'target_portal': NVMe target IP address
         'target_port': NVMe target port
         'nqn': NQN of the NVMe target
         'transport_type': Network fabric being used for an NVMe-oF network
                           One of: tcp, rdma
         'ns_id': namespace id associated with the subsystem
        }


        For nvmeof_conn_info_version set to 2 the new format will be sent:
        {
          'target_nqn': NQN of the NVMe target
          'vol_uuid': NVMe-oF UUID of the volume. May be different than Cinder
                      volume id and may be None if ns_id is provided.
          'portals': [(target_address, target_port, transport_type) ... ]
          'ns_id': namespace id associated with the subsystem, in case target
                   doesn't provide the volume_uuid.
        }
        Unlike the old format the transport_type can be one of RoCEv2 and tcp

        :return: dictionary with the connection properties using one of the 2
                 existing formats depending on the nvmeof_conn_info_version
                 configuration option.
        """
        # NVMe-oF Connection Information Version 2
        if self.configuration.nvmeof_conn_info_version == 2:
            if transport == 'rdma':
                transport = 'RoCEv2'

            if transport == 'rdma':
                transport = 'RoCEv2'

            return {
                'target_nqn': nqn,
                'vol_uuid': uuid,
                'portals': [(portal, port, transport) for portal in portals],
                'ns_id': ns_id,
            }

        # NVMe-oF Connection Information Version 1
        result = {
            'target_portal': portals[0],
            'target_port': port,
            'nqn': nqn,
            'transport_type': transport,
            'ns_id': ns_id,
        }

        return result

    def _get_nvme_uuid(self, volume):
        """Return the NVMe uuid of a given volume.

        Targets that want to support the nvmeof_conn_info_version=2 option need
        to override this method and return the NVMe uuid of the given volume.
        """
        return None

    def get_nvmeof_location(self, nqn, target_ips, target_port,
                            nvme_transport_type, nvmet_ns_id):
        """Serializes driver data into single line string."""

        return "%(ip)s:%(port)s %(transport)s %(nqn)s %(ns_id)s" % (
            {'ip': ','.join(target_ips),
             'port': target_port,
             'transport': nvme_transport_type,
             'nqn': nqn,
             'ns_id': nvmet_ns_id})

    def terminate_connection(self, volume, connector, **kwargs):
        pass

    @staticmethod
    def are_same_connector(A, B):
        a_nqn = A.get('nqn')
        return a_nqn and (a_nqn == B.get('nqn'))

    def create_export(self, context, volume, volume_path):
        """Creates export data for a logical volume."""

        return self.create_nvmeof_target(
            volume['id'],
            self.configuration.target_prefix,
            self.target_ips,
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

    def create_nvmeof_target(self,
                             volume_id,
                             subsystem_name,
                             target_ips,
                             target_port,
                             transport_type,
                             nvmet_port_id,
                             ns_id,
                             volume_path):
        """Targets that don't override create_export must implement this."""
        pass

    def delete_nvmeof_target(self, target_name):
        """Targets that don't override remove_export must implement this."""
        pass
