# Copyright (c) 2012 OpenStack, LLC.
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
Capacity Weigher.  Weigh hosts by their available capacity.

The default is to spread volumes across all hosts evenly.  If you prefer
stacking, you can set the 'capacity_weight_multiplier' option to a negative
number and the weighing has the opposite effect of the default.
"""

import math

from cinder import flags
from cinder.openstack.common import cfg
from cinder.openstack.common.scheduler import weights


capacity_weight_opts = [
        cfg.FloatOpt('capacity_weight_multiplier',
                     default=1.0,
                     help='Multiplier used for weighing volume capacity. '
                          'Negative numbers mean to stack vs spread.'),
]

FLAGS = flags.FLAGS
FLAGS.register_opts(capacity_weight_opts)


class CapacityWeigher(weights.BaseHostWeigher):
    def _weight_multiplier(self):
        """Override the weight multiplier."""
        return FLAGS.capacity_weight_multiplier

    def _weigh_object(self, host_state, weight_properties):
        """Higher weights win.  We want spreading to be the default."""
        reserved = float(host_state.reserved_percentage) / 100
        free = math.floor(host_state.free_capacity_gb * (1 - reserved))
        return free
