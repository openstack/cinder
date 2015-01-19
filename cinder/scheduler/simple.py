# Copyright (c) 2010 OpenStack Foundation
# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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
Chance and Simple Scheduler are DEPRECATED.

Chance and Simple scheduler implementation have been deprecated, as their
functionality can be implemented using the FilterScheduler, here's how:

If one would like to have scheduler randomly picks available back-end
(like ChanceScheduler did), use FilterScheduler with following combination
of filters and weighers.

  scheduler_driver = cinder.scheduler.filter_scheduler.FilterScheduler
  scheduler_default_filters = ['AvailabilityZoneFilter', 'CapacityFilter',
                               'CapabilitiesFilter']
  scheduler_default_weighers = 'ChanceWeigher'

If one prefers the scheduler to pick up the back-end has most available
space that scheduler can see (like SimpleScheduler did), use following
combination of filters and weighers with FilterScheduler.

  scheduler_driver = cinder.scheduler.filter_scheduler.FilterScheduler
  scheduler_default_filters = ['AvailabilityZoneFilter', 'CapacityFilter',
                               'CapabilitiesFilter']
  scheduler_default_weighers = 'AllocatedCapacityWeigher'
  allocated_capacity_weight_multiplier = -1.0

Setting/leaving configure option
'scheduler_driver=cinder.scheduler.chance.ChanceScheduler' or
'scheduler_driver=cinder.scheduler.simple.SimpleScheduler' in cinder.conf
works exactly the same as described above since scheduler manager has been
updated to do the trick internally/transparently for users.

With that, FilterScheduler behaves mostly the same as Chance/SimpleScheduler,
with additional benefits of supporting volume types, volume encryption, QoS.
"""

from oslo_config import cfg

simple_scheduler_opts = [
    cfg.IntOpt("max_gigabytes",
               default=10000,
               help="This configure option has been deprecated along with "
                    "the SimpleScheduler.  New scheduler is able to gather "
                    "capacity information for each host, thus setting the "
                    "maximum number of volume gigabytes for host is no "
                    "longer needed.  It's safe to remove this configure "
                    "from cinder.conf."), ]

CONF = cfg.CONF
CONF.register_opts(simple_scheduler_opts)
