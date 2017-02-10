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

import math

from oslo_config import cfg

from cinder.scheduler import weights
from cinder import utils


capacity_weight_opts = [
    cfg.FloatOpt('capacity_weight_multiplier',
                 default=1.0,
                 help='Multiplier used for weighing free capacity. '
                      'Negative numbers mean to stack vs spread.'),
    cfg.FloatOpt('allocated_capacity_weight_multiplier',
                 default=-1.0,
                 help='Multiplier used for weighing allocated capacity. '
                      'Positive numbers mean to stack vs spread.'),
]

CONF = cfg.CONF
CONF.register_opts(capacity_weight_opts)

OFFSET_MIN = 10000
OFFSET_MULT = 100


class CapacityWeigher(weights.BaseHostWeigher):
    """Capacity Weigher weighs hosts by their virtual or actual free capacity.

    For thin provisioning, weigh hosts by their virtual free capacity
    calculated by the total capacity multiplied by the max over subscription
    ratio and subtracting the provisioned capacity; Otherwise, weigh hosts by
    their actual free capacity, taking into account the reserved space.

    The default is to spread volumes across all hosts evenly. If you prefer
    stacking, you can set the ``capacity_weight_multiplier`` option to a
    negative number and the weighing has the opposite effect of the default.

    """
    def weight_multiplier(self):
        """Override the weight multiplier."""
        return CONF.capacity_weight_multiplier

    def weigh_objects(self, weighed_obj_list, weight_properties):
        """Override the weigh objects.


        This override calls the parent to do the weigh objects and then
        replaces any infinite weights with a value that is a multiple of the
        delta between the min and max values.

        NOTE(jecarey): the infinite weight value is only used when the
        smallest value is being favored (negative multiplier).  When the
        largest weight value is being used a weight of -1 is used instead.
        See _weigh_object method.
        """
        tmp_weights = super(CapacityWeigher, self).weigh_objects(
            weighed_obj_list, weight_properties)

        if math.isinf(self.maxval):
            # NOTE(jecarey): if all weights were infinite then parent
            # method returns 0 for all of the weights.  Thus self.minval
            # cannot be infinite at this point
            copy_weights = [w for w in tmp_weights if not math.isinf(w)]
            self.maxval = max(copy_weights)
            offset = (self.maxval - self.minval) * OFFSET_MULT
            self.maxval += OFFSET_MIN if offset == 0.0 else offset
            tmp_weights = [self.maxval if math.isinf(w) else w
                           for w in tmp_weights]

        return tmp_weights

    def _weigh_object(self, host_state, weight_properties):
        """Higher weights win.  We want spreading to be the default."""
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
            # NOTE(xyang): If 'provisioning:type' is 'thick' in extra_specs,
            # we will not use max_over_subscription_ratio and
            # provisioned_capacity_gb to determine whether a volume can be
            # provisioned. Instead free capacity will be used to evaluate.
            thin = True
            vol_type = weight_properties.get('volume_type', {}) or {}
            provision_type = vol_type.get('extra_specs', {}).get(
                'provisioning:type')
            if provision_type == 'thick':
                thin = False

            free = utils.calculate_virtual_free_capacity(
                total_space,
                free_space,
                host_state.provisioned_capacity_gb,
                host_state.thin_provisioning_support,
                host_state.max_over_subscription_ratio,
                host_state.reserved_percentage,
                thin)

        return free


class AllocatedCapacityWeigher(weights.BaseHostWeigher):
    """Allocated Capacity Weigher weighs hosts by their allocated capacity.

    The default behavior is to place new volume to the host allocated the least
    space. This weigher is intended to simulate the behavior of
    SimpleScheduler. If you prefer to place volumes to host allocated the most
    space, you can set the ``allocated_capacity_weight_multiplier`` option to a
    positive number and the weighing has the opposite effect of the default.
    """

    def weight_multiplier(self):
        """Override the weight multiplier."""
        return CONF.allocated_capacity_weight_multiplier

    def _weigh_object(self, host_state, weight_properties):
        # Higher weights win.  We want spreading (choose host with lowest
        # allocated_capacity first) to be the default.
        allocated_space = host_state.allocated_capacity_gb
        return allocated_space
