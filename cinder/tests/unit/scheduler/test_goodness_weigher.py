# Copyright (C) 2014 Hewlett-Packard Development Company, L.P.
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
Tests For Goodness Weigher.
"""

from cinder.scheduler.weights import goodness
from cinder import test
from cinder.tests.unit.scheduler import fakes


class GoodnessWeigherTestCase(test.TestCase):
    def test_goodness_weigher_with_no_goodness_function(self):
        weigher = goodness.GoodnessWeigher()
        host_state = fakes.FakeBackendState('host1', {
            'host': 'host.example.com',
            'capabilities': {
                'foo': '50'
            }
        })

        weight_properties = {}
        weight = weigher._weigh_object(host_state, weight_properties)
        self.assertEqual(0, weight)

    def test_goodness_weigher_passing_host(self):
        weigher = goodness.GoodnessWeigher()
        host_state = fakes.FakeBackendState('host1', {
            'host': 'host.example.com',
            'capabilities': {
                'goodness_function': '100'
            }
        })
        host_state_2 = fakes.FakeBackendState('host2', {
            'host': 'host2.example.com',
            'capabilities': {
                'goodness_function': '0'
            }
        })
        host_state_3 = fakes.FakeBackendState('host3', {
            'host': 'host3.example.com',
            'capabilities': {
                'goodness_function': '100 / 2'
            }
        })

        weight_properties = {}
        weight = weigher._weigh_object(host_state, weight_properties)
        self.assertEqual(100, weight)
        weight = weigher._weigh_object(host_state_2, weight_properties)
        self.assertEqual(0, weight)
        weight = weigher._weigh_object(host_state_3, weight_properties)
        self.assertEqual(50, weight)

    def test_goodness_weigher_capabilities_substitution(self):
        weigher = goodness.GoodnessWeigher()
        host_state = fakes.FakeBackendState('host1', {
            'host': 'host.example.com',
            'capabilities': {
                'foo': 50,
                'goodness_function': '10 + capabilities.foo'
            }
        })

        weight_properties = {}
        weight = weigher._weigh_object(host_state, weight_properties)
        self.assertEqual(60, weight)

    def test_goodness_weigher_extra_specs_substitution(self):
        weigher = goodness.GoodnessWeigher()
        host_state = fakes.FakeBackendState('host1', {
            'host': 'host.example.com',
            'capabilities': {
                'goodness_function': '10 + extra.foo'
            }
        })

        weight_properties = {
            'volume_type': {
                'extra_specs': {
                    'foo': 50
                }
            }
        }
        weight = weigher._weigh_object(host_state, weight_properties)
        self.assertEqual(60, weight)

    def test_goodness_weigher_volume_substitution(self):
        weigher = goodness.GoodnessWeigher()
        host_state = fakes.FakeBackendState('host1', {
            'host': 'host.example.com',
            'capabilities': {
                'goodness_function': '10 + volume.foo'
            }
        })

        weight_properties = {
            'request_spec': {
                'volume_properties': {
                    'foo': 50
                }
            }
        }
        weight = weigher._weigh_object(host_state, weight_properties)
        self.assertEqual(60, weight)

    def test_goodness_weigher_qos_substitution(self):
        weigher = goodness.GoodnessWeigher()
        host_state = fakes.FakeBackendState('host1', {
            'host': 'host.example.com',
            'capabilities': {
                'goodness_function': '10 + qos.foo'
            }
        })

        weight_properties = {
            'qos_specs': {
                'foo': 50
            }
        }
        weight = weigher._weigh_object(host_state, weight_properties)
        self.assertEqual(60, weight)

    def test_goodness_weigher_stats_substitution(self):
        weigher = goodness.GoodnessWeigher()
        host_state = fakes.FakeBackendState('host1', {
            'host': 'host.example.com',
            'capabilities': {
                'goodness_function': 'stats.free_capacity_gb > 20'
            },
            'free_capacity_gb': 50
        })

        weight_properties = {}
        weight = weigher._weigh_object(host_state, weight_properties)
        self.assertEqual(100, weight)

    def test_goodness_weigher_invalid_substitution(self):
        weigher = goodness.GoodnessWeigher()
        host_state = fakes.FakeBackendState('host1', {
            'host': 'host.example.com',
            'capabilities': {
                'goodness_function': '10 + stats.my_val'
            },
            'foo': 50
        })

        weight_properties = {}
        weight = weigher._weigh_object(host_state, weight_properties)
        self.assertEqual(0, weight)

    def test_goodness_weigher_host_rating_out_of_bounds(self):
        weigher = goodness.GoodnessWeigher()
        host_state = fakes.FakeBackendState('host1', {
            'host': 'host.example.com',
            'capabilities': {
                'goodness_function': '-10'
            }
        })
        host_state_2 = fakes.FakeBackendState('host2', {
            'host': 'host2.example.com',
            'capabilities': {
                'goodness_function': '200'
            }
        })

        weight_properties = {}
        weight = weigher._weigh_object(host_state, weight_properties)
        self.assertEqual(0, weight)
        weight = weigher._weigh_object(host_state_2, weight_properties)
        self.assertEqual(0, weight)

    def test_goodness_weigher_invalid_goodness_function(self):
        weigher = goodness.GoodnessWeigher()
        host_state = fakes.FakeBackendState('host1', {
            'host': 'host.example.com',
            'capabilities': {
                'goodness_function': '50 / 0'
            }
        })

        weight_properties = {}
        weight = weigher._weigh_object(host_state, weight_properties)
        self.assertEqual(0, weight)

    def test_goodness_weigher_untyped_volume(self):
        weigher = goodness.GoodnessWeigher()
        host_state = fakes.FakeBackendState('host1', {
            'host': 'host.example.com',
            'capabilities': {
                'goodness_function': '67'
            }
        })

        weight_properties = {
            'volume_type': None,
        }
        weight = weigher._weigh_object(host_state, weight_properties)
        self.assertEqual(67, weight)
