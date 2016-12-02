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

from oslo_log import log as logging

from cinder.interface import fczm_driver
from cinder.zonemanager import fc_common

LOG = logging.getLogger(__name__)


class FCZoneDriver(
        fc_common.FCCommon, fczm_driver.FibreChannelZoneManagerDriver):
    """Interface to manage Connection control during attach/detach."""

    # If a driver hasn't maintained their CI system, this will get set
    # to False, which prevents the driver from starting.
    # Add enable_unsupported_driver = True in cinder.conf to get the
    # unsupported driver started.
    SUPPORTED = True

    def __init__(self, **kwargs):
        super(FCZoneDriver, self).__init__(**kwargs)
        LOG.debug("Initializing FCZoneDriver")

    @property
    def supported(self):
        return self.SUPPORTED
