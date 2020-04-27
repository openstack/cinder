# Copyright 2013 eBay Inc.
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
Tests For Allocated Capacity Weigher.
"""

from unittest import mock

from cinder.common import constants
from cinder import context
from cinder.scheduler import weights
from cinder.tests.unit.scheduler import fakes
from cinder.tests.unit import test
from cinder.volume import volume_utils


class AllocatedCapacityWeigherTestCase(test.TestCase):
    def setUp(self):
        super(AllocatedCapacityWeigherTestCase, self).setUp()
        self.host_manager = fakes.FakeHostManager()
        self.weight_handler = weights.OrderedHostWeightHandler(
            'cinder.scheduler.weights')

    def _get_weighed_host(self, hosts, weight_properties=None):
        if weight_properties is None:
            weight_properties = {}
        return self.weight_handler.get_weighed_objects(
            [weights.capacity.AllocatedCapacityWeigher], hosts,
            weight_properties)[0]

    @mock.patch('cinder.db.sqlalchemy.api.service_get_all')
    def _get_all_backends(self, _mock_service_get_all, disabled=False):
        ctxt = context.get_admin_context()
        fakes.mock_host_manager_db_calls(_mock_service_get_all,
                                         disabled=disabled)
        host_states = self.host_manager.get_all_backend_states(ctxt)
        _mock_service_get_all.assert_called_once_with(
            ctxt,
            None,  # backend_match_level
            topic=constants.VOLUME_TOPIC, frozen=False, disabled=disabled)
        return host_states

    def test_default_of_spreading_first(self):
        hostinfo_list = self._get_all_backends()

        # host1: allocated_capacity_gb=0, weight=0        Norm=0.0
        # host2: allocated_capacity_gb=1748, weight=-1748
        # host3: allocated_capacity_gb=256, weight=-256
        # host4: allocated_capacity_gb=1848, weight=-1848 Norm=-1.0
        # host5: allocated_capacity_gb=1548, weight=-1540

        # so, host1 should win:
        weighed_host = self._get_weighed_host(hostinfo_list)
        self.assertEqual(0.0, weighed_host.weight)
        self.assertEqual(
            'host1', volume_utils.extract_host(weighed_host.obj.host))

    def test_capacity_weight_multiplier1(self):
        self.flags(allocated_capacity_weight_multiplier=1.0)
        hostinfo_list = self._get_all_backends()

        # host1: allocated_capacity_gb=0, weight=0          Norm=0.0
        # host2: allocated_capacity_gb=1748, weight=1748
        # host3: allocated_capacity_gb=256, weight=256
        # host4: allocated_capacity_gb=1848, weight=1848    Norm=1.0
        # host5: allocated_capacity_gb=1548, weight=1540

        # so, host4 should win:
        weighed_host = self._get_weighed_host(hostinfo_list)
        self.assertEqual(1.0, weighed_host.weight)
        self.assertEqual(
            'host4', volume_utils.extract_host(weighed_host.obj.host))

    def test_capacity_weight_multiplier2(self):
        self.flags(allocated_capacity_weight_multiplier=-2.0)
        hostinfo_list = self._get_all_backends()

        # host1: allocated_capacity_gb=0, weight=0        Norm=0.0
        # host2: allocated_capacity_gb=1748, weight=-3496
        # host3: allocated_capacity_gb=256, weight=-512
        # host4: allocated_capacity_gb=1848, weight=-3696 Norm=-2.0
        # host5: allocated_capacity_gb=1548, weight=-3080

        # so, host1 should win:
        weighed_host = self._get_weighed_host(hostinfo_list)
        self.assertEqual(0.0, weighed_host.weight)
        self.assertEqual(
            'host1', volume_utils.extract_host(weighed_host.obj.host))
