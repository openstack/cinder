# Copyright (c) 2012 Intel
# Copyright (c) 2012 OpenStack Foundation
# Copyright (c) 2015 EMC Corporation
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

from oslo_log import log as logging

from cinder.i18n import _LE, _LW
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
            LOG.error(_LE("Free capacity not set: "
                          "volume node info collection broken."))
            return False

        free_space = host_state.free_capacity_gb
        total_space = host_state.total_capacity_gb
        reserved = float(host_state.reserved_percentage) / 100
        if free_space in ['infinite', 'unknown']:
            # NOTE(zhiteng) for those back-ends cannot report actual
            # available capacity, we assume it is able to serve the
            # request.  Even if it was not, the retry mechanism is
            # able to handle the failure by rescheduling
            return True
        elif total_space in ['infinite', 'unknown']:
            # If total_space is 'infinite' or 'unknown' and reserved
            # is 0, we assume the back-ends can serve the request.
            # If total_space is 'infinite' or 'unknown' and reserved
            # is not 0, we cannot calculate the reserved space.
            # float(total_space) will throw an exception. total*reserved
            # also won't work. So the back-ends cannot serve the request.
            if reserved == 0:
                return True
            return False
        total = float(total_space)
        if total <= 0:
            LOG.warning(_LW("Insufficient free space for volume creation. "
                            "Total capacity is %(total).2f on host %(host)s."),
                        {"total": total,
                         "host": host_state.host})
            return False
        # Calculate how much free space is left after taking into account
        # the reserved space.
        free = free_space - math.floor(total * reserved)

        msg_args = {"host": host_state.host,
                    "requested": volume_size,
                    "available": free}

        # Only evaluate using max_over_subscription_ratio if
        # thin_provisioning_support is True. Check if the ratio of
        # provisioned capacity over total capacity has exceeded over
        # subscription ratio.
        if (host_state.thin_provisioning_support and
                host_state.max_over_subscription_ratio > 1):
            provisioned_ratio = ((host_state.provisioned_capacity_gb +
                                  volume_size) / total)
            if provisioned_ratio > host_state.max_over_subscription_ratio:
                LOG.warning(_LW(
                    "Insufficient free space for thin provisioning. "
                    "The ratio of provisioned capacity over total capacity "
                    "%(provisioned_ratio).2f has exceeded the maximum over "
                    "subscription ratio %(oversub_ratio).2f on host "
                    "%(host)s."),
                    {"provisioned_ratio": provisioned_ratio,
                     "oversub_ratio": host_state.max_over_subscription_ratio,
                     "host": host_state.host})
                return False
            else:
                free_virtual = free * host_state.max_over_subscription_ratio
                return free_virtual >= volume_size

        if free < volume_size:
            LOG.warning(_LW("Insufficient free space for volume creation "
                            "on host %(host)s (requested / avail): "
                            "%(requested)s/%(available)s"), msg_args)
            return False

        LOG.debug("Space information for volume creation "
                  "on host %(host)s (requested / avail): "
                  "%(requested)s/%(available)s", msg_args)

        return True
