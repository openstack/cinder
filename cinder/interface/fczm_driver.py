# Copyright 2016 Dell Inc.
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
#

"""
Core fibre channel zone manager driver interface.

All fczm drivers should support this interface as a bare minimum.
"""

from cinder.interface import base


class FibreChannelZoneManagerDriver(base.CinderInterface):
    """FCZM driver required interface."""

    def add_connection(self, fabric, initiator_target_map, host_name=None,
                       storage_system=None):
        """Add a new initiator<>target connection.

        All implementing drivers should provide concrete implementation
        for this API.

        :param fabric: Fabric name from cinder.conf file
        :param initiator_target_map: Mapping of initiator to list of targets

        .. code-block:: python

            Example initiator_target_map:

            {
                '10008c7cff523b01': ['20240002ac000a50', '20240002ac000a40']
            }

        Note that WWPN can be in lower or upper case and can be ':'
        separated strings.
        """

    def delete_connection(self, fabric, initiator_target_map, host_name=None,
                          storage_system=None):
        """Delete an initiator<>target connection.

        :param fabric: Fabric name from cinder.conf file
        :param initiator_target_map: Mapping of initiator to list of targets

        .. code-block:: python

            Example initiator_target_map:

            {
                '10008c7cff523b01': ['20240002ac000a50', '20240002ac000a40']
            }

        Note that WWPN can be in lower or upper case and can be ':'
        separated strings.
        """

    def get_san_context(self, target_wwn_list):
        """Get SAN context for end devices.

        :param target_wwn_list: Mapping of initiator to list of targets

        Example initiator_target_map: ['20240002ac000a50', '20240002ac000a40']
        Note that WWPN can be in lower or upper case and can be
        ':' separated strings.
        """
