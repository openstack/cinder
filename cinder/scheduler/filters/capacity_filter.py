# Copyright (c) 2012 Intel
# Copyright (c) 2012 OpenStack, LLC.
#
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


import math

from cinder.openstack.common import log as logging
from cinder.openstack.common.scheduler import filters


LOG = logging.getLogger(__name__)


class CapacityFilter(filters.BaseHostFilter):
    """CapacityFilter filters based on volume host's capacity utilization."""

    def host_passes(self, host_state, filter_properties):
        """Return True if host has sufficient capacity."""
        volume_size = filter_properties.get('size')

        if not host_state.free_capacity_gb:
            # Fail Safe
            LOG.warning(_("Free capacity not set;"
                          "volume node info collection broken."))
            return False

        reserved = float(host_state.reserved_percentage) / 100
        free = math.floor(host_state.free_capacity_gb * (1 - reserved))

        return free >= volume_size
