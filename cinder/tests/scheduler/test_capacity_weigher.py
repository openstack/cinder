# Copyright 2011-2012 OpenStack Foundation
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
Tests For Capacity Weigher.
"""

import mock
from oslo_config import cfg

from cinder import context
from cinder.openstack.common.scheduler import weights
from cinder.scheduler.weights import capacity
from cinder import test
from cinder.tests.scheduler import fakes
from cinder.volume import utils

CONF = cfg.CONF


class CapacityWeigherTestCase(test.TestCase):
    def setUp(self):
        super(CapacityWeigherTestCase, self).setUp()
        self.host_manager = fakes.FakeHostManager()
        self.weight_handler = weights.HostWeightHandler(
            'cinder.scheduler.weights')

    def _get_weighed_host(self, hosts, weight_properties=None):
        if weight_properties is None:
            weight_properties = {'size': 1}
        return self.weight_handler.get_weighed_objects(
            [capacity.CapacityWeigher],
            hosts,
            weight_properties)[0]

    @mock.patch('cinder.db.sqlalchemy.api.service_get_all_by_topic')
    def _get_all_hosts(self, _mock_service_get_all_by_topic, disabled=False):
        ctxt = context.get_admin_context()
        fakes.mock_host_manager_db_calls(_mock_service_get_all_by_topic,
                                         disabled=disabled)
        host_states = self.host_manager.get_all_host_states(ctxt)
        _mock_service_get_all_by_topic.assert_called_once_with(
            ctxt, CONF.volume_topic, disabled=disabled)
        return host_states

    # If thin_provisioning_support = False, use the following formula:
    # free = free_space - math.floor(total * reserved)
    # Otherwise, use the following formula:
    # free = (total * host_state.max_over_subscription_ratio
    #         - host_state.provisioned_capacity_gb
    #         - math.floor(total * reserved))
    def test_default_of_spreading_first(self):
        hostinfo_list = self._get_all_hosts()

        # host1: thin_provisioning_support = False
        #        free_capacity_gb=1024,
        #        free=1024-math.floor(1024*0.1)=922
        # host2: thin_provisioning_support = True
        #        free_capacity_gb=300,
        #        free=2048*1.5-1748-math.floor(2048*0.1)=1120
        # host3: thin_provisioning_support = False
        #        free_capacity_gb=512, free=256-512*0=256
        # host4: thin_provisioning_support = True
        #        free_capacity_gb=200,
        #        free=2048*1.0-2047-math.floor(2048*0.05)=-101
        # host5: free_capacity_gb=unknown free=-1

        # so, host2 should win:
        weighed_host = self._get_weighed_host(hostinfo_list)
        self.assertEqual(weighed_host.weight, 1120.0)
        self.assertEqual(
            utils.extract_host(weighed_host.obj.host), 'host2')

    def test_capacity_weight_multiplier1(self):
        self.flags(capacity_weight_multiplier=-1.0)
        hostinfo_list = self._get_all_hosts()

        # host1: thin_provisioning_support = False
        #        free_capacity_gb=1024,
        #        free=-(1024-math.floor(1024*0.1))=-922
        # host2: thin_provisioning_support = True
        #        free_capacity_gb=300,
        #        free=-(2048*1.5-1748-math.floor(2048*0.1))=-1120
        # host3: thin_provisioning_support = False
        #        free_capacity_gb=512, free=-(256-512*0)=-256
        # host4: thin_provisioning_support = True
        #        free_capacity_gb=200,
        #        free=-(2048*1.0-2047-math.floor(2048*0.05))=101
        # host5: free_capacity_gb=unknown free=-float('inf')

        # so, host4 should win:
        weighed_host = self._get_weighed_host(hostinfo_list)
        self.assertEqual(weighed_host.weight, 101.0)
        self.assertEqual(
            utils.extract_host(weighed_host.obj.host), 'host4')

    def test_capacity_weight_multiplier2(self):
        self.flags(capacity_weight_multiplier=2.0)
        hostinfo_list = self._get_all_hosts()

        # host1: thin_provisioning_support = False
        #        free_capacity_gb=1024,
        #        free=(1024-math.floor(1024*0.1))*2=1844
        # host2: thin_provisioning_support = True
        #        free_capacity_gb=300,
        #        free=(2048*1.5-1748-math.floor(2048*0.1))*2=2240
        # host3: thin_provisioning_support = False
        #        free_capacity_gb=512, free=(256-512*0)*2=512
        # host4: thin_provisioning_support = True
        #        free_capacity_gb=200,
        #        free=(2048*1.0-2047-math.floor(2048*0.05))*2=-202
        # host5: free_capacity_gb=unknown free=-2

        # so, host2 should win:
        weighed_host = self._get_weighed_host(hostinfo_list)
        self.assertEqual(weighed_host.weight, 1120.0 * 2)
        self.assertEqual(
            utils.extract_host(weighed_host.obj.host), 'host2')
