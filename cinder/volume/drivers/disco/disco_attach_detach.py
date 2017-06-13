#    copyright (c) 2016 Industrial Technology Research Institute.
#    All Rights Reserved.
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

"""Class for DISCO to attach and detach volume."""

from os_brick.initiator import connector
from oslo_log import log as logging

from cinder import utils


LOG = logging.getLogger(__name__)


class AttachDetachDiscoVolume(object):
    """Class for attach and detach a DISCO volume."""

    def __init__(self, configuration):
        """Init volume attachment class."""
        self.configuration = configuration
        self.connector = connector.InitiatorConnector.factory(
            self._get_connector_identifier(), utils.get_root_helper(),
            device_scan_attempts=(
                self.configuration.num_volume_device_scan_tries)
        )
        self.connection_conf = {}
        self.connection_conf['server_ip'] = self.configuration.disco_client
        self.connection_conf['server_port'] = (
            self.configuration.disco_client_port)

        self.connection_properties = {}
        self.connection_properties['name'] = None
        self.connection_properties['disco_id'] = None
        self.connection_properties['conf'] = self.connection_conf

    def _get_connection_properties(self, volume):
        """Return a dictionnary with the connection properties."""
        connection_properties = dict(self.connection_properties)
        connection_properties['name'] = volume['name']
        connection_properties['disco_id'] = volume['provider_location']
        return connection_properties

    def _get_connector_identifier(self):
        """Return connector identifier, put here to mock it in unit tests."""
        return connector.DISCO

    def _attach_volume(self, volume):
        """Call the connector.connect_volume()."""
        connection_properties = self._get_connection_properties(volume)
        device_info = self.connector.connect_volume(connection_properties)
        return device_info

    def _detach_volume(self, volume):
        """Call the connector.disconnect_volume()."""
        connection_properties = self._get_connection_properties(volume)
        self.connector.disconnect_volume(connection_properties, volume)
