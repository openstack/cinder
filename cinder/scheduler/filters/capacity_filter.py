# Copyright (c) 2012 Intel
# Copyright (c) 2012 OpenStack Foundation
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

from cinder.i18n import _
from cinder.openstack.common import log as logging
from cinder.openstack.common.scheduler import filters


LOG = logging.getLogger(__name__)


class CapacityFilter(filters.BaseHostFilter):
    """CapacityFilter filters based on volume host's capacity utilization."""

    def host_passes(self, host_state, filter_properties):
        """Return True if host has sufficient capacity."""

        # If the volume already exists on this host, don't fail it for
        # insufficient capacity (e.g., if we are retyping)
        if host_state.host == filter_properties.get('vol_exists_on'):
            return True

        volume_size = filter_properties.get('size')

        if host_state.free_capacity_gb is None:
            # Fail Safe
            LOG.error(_("Free capacity not set: "
                        "volume node info collection broken."))
            return False

        free_space = host_state.free_capacity_gb
        if free_space == 'infinite' or free_space == 'unknown':
            # NOTE(zhiteng) for those back-ends cannot report actual
            # available capacity, we assume it is able to serve the
            # request.  Even if it was not, the retry mechanism is
            # able to handle the failure by rescheduling
            return True
        reserved = float(host_state.reserved_percentage) / 100
        free = math.floor(free_space * (1 - reserved))
        if free < volume_size:
            LOG.warning(_("Insufficient free space for volume creation "
                          "(requested / avail): "
                          "%(requested)s/%(available)s")
                        % {'requested': volume_size,
                           'available': free})

        return free >= volume_size
