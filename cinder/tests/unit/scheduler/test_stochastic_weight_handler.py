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
"""Tests for stochastic weight handler."""

import random

import ddt

from cinder.scheduler import base_weight
from cinder.scheduler.weights.stochastic import StochasticHostWeightHandler
from cinder.tests.unit import test


@ddt.ddt
class StochasticWeightHandlerTestCase(test.TestCase):
    """Test case for StochasticHostWeightHandler."""

    @ddt.data(
        (0.0, 'A'),
        (0.1, 'A'),
        (0.2, 'B'),
        (0.3, 'B'),
        (0.4, 'B'),
        (0.5, 'B'),
        (0.6, 'B'),
        (0.7, 'C'),
        (0.8, 'C'),
        (0.9, 'C'),
    )
    @ddt.unpack
    def test_get_weighed_objects_correct(self, rand_value, expected_obj):
        self.mock_object(random,
                         'random',
                         return_value=rand_value)

        class MapWeigher(base_weight.BaseWeigher):
            minval = 0
            maxval = 100

            def _weigh_object(self, obj, weight_map):
                return weight_map[obj]

        weight_map = {'A': 1, 'B': 3, 'C': 2}
        objs = sorted(weight_map.keys())

        weigher_classes = [MapWeigher]
        handler = StochasticHostWeightHandler('fake_namespace')
        weighted_objs = handler.get_weighed_objects(weigher_classes,
                                                    objs,
                                                    weight_map)
        winner = weighted_objs[0].obj
        self.assertEqual(expected_obj, winner)
