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
Tests For Chance Weigher.
"""

from unittest import mock

from cinder.scheduler import host_manager
from cinder.scheduler.weights import chance
from cinder.tests.unit import test


class ChanceWeigherTestCase(test.TestCase):
    def fake_random(self, reset=False):
        if reset:
            self.not_random_float = 0.0
        else:
            self.not_random_float += 1.0
        return self.not_random_float

    @mock.patch('random.random')
    def test_chance_weigher(self, _mock_random):
        # stub random.random() to verify the ChanceWeigher
        # is using random.random() (repeated calls to weigh should
        # return incrementing weights)
        weigher = chance.ChanceWeigher()
        _mock_random.side_effect = self.fake_random
        self.fake_random(reset=True)
        host_state = {'host': 'host.example.com', 'free_capacity_gb': 99999}
        weight = weigher._weigh_object(host_state, None)
        self.assertEqual(1.0, weight)
        weight = weigher._weigh_object(host_state, None)
        self.assertEqual(2.0, weight)
        weight = weigher._weigh_object(host_state, None)
        self.assertEqual(3.0, weight)

    def test_host_manager_choosing_chance_weigher(self):
        # ensure HostManager can load the ChanceWeigher
        # via the entry points mechanism
        hm = host_manager.HostManager()
        weighers = hm._choose_backend_weighers('ChanceWeigher')
        self.assertEqual(1, len(weighers))
        self.assertEqual(weighers[0], chance.ChanceWeigher)

    def test_use_of_chance_weigher_via_host_manager(self):
        # ensure we don't lose any hosts when weighing with
        # the ChanceWeigher
        hm = host_manager.HostManager()
        fake_backends = [host_manager.BackendState('fake_be%s' % x, None)
                         for x in range(1, 5)]
        weighed_backends = hm.get_weighed_backends(fake_backends, {},
                                                   'ChanceWeigher')
        self.assertEqual(4, len(weighed_backends))
