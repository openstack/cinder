# Copyright (C) 2013 Hewlett-Packard Development Company, L.P.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.
"""
Chance Weigher.  Assign random weights to hosts.

Used to spread volumes randomly across a list of equally suitable hosts.
"""


import random

from cinder.openstack.common.scheduler import weights


class ChanceWeigher(weights.BaseHostWeigher):
    def _weigh_object(self, host_state, weight_properties):
        return random.random()
