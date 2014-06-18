#    (c) Copyright 2014 Brocade Communications Systems Inc.
#    All Rights Reserved.
#
#    Copyright 2014 OpenStack Foundation
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
Base Zone Driver is responsible to manage access control using FC zoning
Vendor specific implementations should extend this class to provide
concrete implementation for add_connection and delete_connection
interfaces.

**Related Flags**

:zoning_policy: Used by: class: 'FCZoneDriver'. Defaults to 'none'
:zone_driver: Used by: class: 'FCZoneDriver'. Defaults to 'none'

"""


from cinder.openstack.common import log as logging
from cinder.zonemanager import fc_common

LOG = logging.getLogger(__name__)


class FCZoneDriver(fc_common.FCCommon):
    """Interface to manage Connection control during attach/detach."""

    def __init__(self, **kwargs):
        super(FCZoneDriver, self).__init__(**kwargs)
        LOG.debug("Initializing FCZoneDriver")

    def add_connection(self, fabric, initiator_target_map):
        """Add connection control.

        Abstract method to add connection control.
        All implementing drivers should provide concrete implementation
        for this API.
        :param fabric: Fabric name from cinder.conf file
        :param initiator_target_map: Mapping of initiator to list of targets
        Example initiator_target_map:
            {
                '10008c7cff523b01': ['20240002ac000a50', '20240002ac000a40']
            }
        Note that WWPN can be in lower or upper case and can be
        ':' separated strings
        """
        raise NotImplementedError()

    def delete_connection(self, fabric, initiator_target_map):
        """Delete connection control.

        Abstract method to remove connection control.
        All implementing drivers should provide concrete implementation
        for this API.
        :param fabric: Fabric name from cinder.conf file
        :param initiator_target_map: Mapping of initiator to list of targets
        Example initiator_target_map:
            {
                '10008c7cff523b01': ['20240002ac000a50', '20240002ac000a40']
            }
        Note that WWPN can be in lower or upper case and can be
        ':' separated strings
        """
        raise NotImplementedError()

    def get_san_context(self, target_wwn_list):
        """Get SAN context for end devices.

        Abstract method to get SAN contexts for given list of end devices
        All implementing drivers should provide concrete implementation
        for this API.
        :param fabric: Fabric name from cinder.conf file
        :param initiator_target_map: Mapping of initiator to list of targets
        Example initiator_target_map: ['20240002ac000a50', '20240002ac000a40']
        Note that WWPN can be in lower or upper case and can be
        ':' separated strings
        """
        raise NotImplementedError()
