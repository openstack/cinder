# Copyright (c) 2013 eBay Inc.
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
"""
Weighers that weigh hosts by their capacity, including following two
weighers:

1. Capacity Weigher.  Weigh hosts by their virtual or actual free capacity.

For thin provisioning, weigh hosts by their virtual free capacity calculated
by the total capacity multiplied by the max over subscription ratio and
subtracting the provisioned capacity; Otherwise, weigh hosts by their actual
free capacity, taking into account the reserved space.

The default is to spread volumes across all hosts evenly.  If you prefer
stacking, you can set the 'capacity_weight_multiplier' option to a negative
number and the weighing has the opposite effect of the default.

2. Allocated Capacity Weigher.  Weigh hosts by their allocated capacity.

The default behavior is to place new volume to the host allocated the least
space.  This weigher is intended to simulate the behavior of SimpleScheduler.
If you prefer to place volumes to host allocated the most space, you can
set the 'allocated_capacity_weight_multiplier' option to a positive number
and the weighing has the opposite effect of the default.
"""


import math

from oslo_config import cfg

from cinder.openstack.common.scheduler import weights


capacity_weight_opts = [
    cfg.FloatOpt('capacity_weight_multiplier',
                 default=1.0,
                 help='Multiplier used for weighing volume capacity. '
                      'Negative numbers mean to stack vs spread.'),
    cfg.FloatOpt('allocated_capacity_weight_multiplier',
                 default=-1.0,
                 help='Multiplier used for weighing volume capacity. '
                      'Negative numbers mean to stack vs spread.'),
]

CONF = cfg.CONF
CONF.register_opts(capacity_weight_opts)


class CapacityWeigher(weights.BaseHostWeigher):
    def _weight_multiplier(self):
        """Override the weight multiplier."""
        return CONF.capacity_weight_multiplier

    def _weigh_object(self, host_state, weight_properties):
        """Higher weights win.  We want spreading to be the default."""
        reserved = float(host_state.reserved_percentage) / 100
        free_space = host_state.free_capacity_gb
        total_space = host_state.total_capacity_gb
        if (free_space == 'infinite' or free_space == 'unknown' or
                total_space == 'infinite' or total_space == 'unknown'):
            # (zhiteng) 'infinite' and 'unknown' are treated the same
            # here, for sorting purpose.

            # As a partial fix for bug #1350638, 'infinite' and 'unknown' are
            # given the lowest weight to discourage driver from report such
            # capacity anymore.
            free = -1 if CONF.capacity_weight_multiplier > 0 else float('inf')
        else:
            total = float(total_space)
            if host_state.thin_provisioning_support:
                # Calculate virtual free capacity for thin provisioning.
                free = (total * host_state.max_over_subscription_ratio
                        - host_state.provisioned_capacity_gb -
                        math.floor(total * reserved))
            else:
                # Calculate how much free space is left after taking into
                # account the reserved space.
                free = free_space - math.floor(total * reserved)
        return free


class AllocatedCapacityWeigher(weights.BaseHostWeigher):
    def _weight_multiplier(self):
        """Override the weight multiplier."""
        return CONF.allocated_capacity_weight_multiplier

    def _weigh_object(self, host_state, weight_properties):
        # Higher weights win.  We want spreading (choose host with lowest
        # allocated_capacity first) to be the default.
        allocated_space = host_state.allocated_capacity_gb
        return allocated_space
