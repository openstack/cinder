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
Stochastic weight handler

This weight handler differs from the default weight
handler by giving every pool a chance to be chosen
where the probability is proportional to each pools'
weight.
"""

import random

from cinder.scheduler import base_weight
from cinder.scheduler import weights as wts


class StochasticHostWeightHandler(base_weight.BaseWeightHandler):
    def __init__(self, namespace):
        super(StochasticHostWeightHandler, self).__init__(wts.BaseHostWeigher,
                                                          namespace)

    def get_weighed_objects(self, weigher_classes, obj_list,
                            weighing_properties):
        # The normalization performed in the superclass is nonlinear, which
        # messes up the probabilities, so override it. The probabilistic
        # approach we use here is self-normalizing.
        # Also, the sorting done by the parent implementation is harmless but
        # useless for us.

        # Compute the object weights as the parent would but without sorting
        # or normalization.
        weighed_objs = [wts.WeighedHost(obj, 0.0) for obj in obj_list]
        for weigher_cls in weigher_classes:
            weigher = weigher_cls()
            weights = weigher.weigh_objects(weighed_objs, weighing_properties)
            for i, weight in enumerate(weights):
                obj = weighed_objs[i]
                obj.weight += weigher.weight_multiplier() * weight

        # Avoid processing empty lists
        if not weighed_objs:
            return []

        # First compute the total weight of all the objects and the upper
        # bound for each object to "win" the lottery.
        total_weight = 0
        table = []
        for weighed_obj in weighed_objs:
            total_weight += weighed_obj.weight
            max_value = total_weight
            table.append((max_value, weighed_obj))

        # Now draw a random value with the computed range
        winning_value = random.random() * total_weight

        # Scan the table to find the first object with a maximum higher than
        # the random number. Save the index of the winner.
        winning_index = 0
        for (i, (max_value, weighed_obj)) in enumerate(table):
            if max_value > winning_value:
                # Return a single element array with the winner.
                winning_index = i
                break

        # It's theoretically possible for the above loop to terminate with no
        # winner. This happens when winning_value >= total_weight, which
        # could only occur with very large numbers and floating point
        # rounding. In those cases the actual winner should have been the
        # last element, so return it.
        return weighed_objs[winning_index:] + weighed_objs[0:winning_index]
