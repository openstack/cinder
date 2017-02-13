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
from datetime import datetime

import ddt
import mock

from cinder.common import constants
from cinder import context
from cinder.scheduler import weights
from cinder import test
from cinder.tests.unit.scheduler import fakes
from cinder.volume import utils


@ddt.ddt
class CapacityWeigherTestCase(test.TestCase):
    def setUp(self):
        super(CapacityWeigherTestCase, self).setUp()
        self.host_manager = fakes.FakeHostManager()
        self.weight_handler = weights.OrderedHostWeightHandler(
            'cinder.scheduler.weights')

    def _get_weighed_hosts(self, hosts, weight_properties=None):
        if weight_properties is None:
            weight_properties = {'size': 1}
        return self.weight_handler.get_weighed_objects(
            [weights.capacity.CapacityWeigher],
            hosts,
            weight_properties)

    @mock.patch('cinder.db.sqlalchemy.api.service_get_all')
    def _get_all_backends(self, _mock_service_get_all, disabled=False):
        ctxt = context.get_admin_context()
        fakes.mock_host_manager_db_calls(_mock_service_get_all,
                                         disabled=disabled)
        backend_states = self.host_manager.get_all_backend_states(ctxt)
        _mock_service_get_all.assert_called_once_with(
            ctxt,
            None,  # backend_match_level
            topic=constants.VOLUME_TOPIC, frozen=False, disabled=disabled)
        return backend_states

    # If thin and thin_provisioning_support are True,
    # use the following formula:
    # free = (total * host_state.max_over_subscription_ratio
    #         - host_state.provisioned_capacity_gb
    #         - math.floor(total * reserved))
    # Otherwise, use the following formula:
    # free = free_space - math.floor(total * reserved)

    @ddt.data(
        {'volume_type': {'extra_specs': {'provisioning:type': 'thin'}},
         'winner': 'host2'},
        {'volume_type': {'extra_specs': {'provisioning:type': 'thick'}},
         'winner': 'host1'},
        {'volume_type': {'extra_specs': {}},
         'winner': 'host2'},
        {'volume_type': {},
         'winner': 'host2'},
        {'volume_type': None,
         'winner': 'host2'},
    )
    @ddt.unpack
    def test_default_of_spreading_first(self, volume_type, winner):
        backend_info_list = self._get_all_backends()

        # Results for the 1st test
        # {'provisioning:type': 'thin'}:
        # host1: thin_provisioning_support = False
        #        free_capacity_gb=1024,
        #        free=1024-math.floor(1024*0.1)=922
        #        Norm=0.837837837838
        # host2: thin_provisioning_support = True
        #        free_capacity_gb=300,
        #        free=2048*1.5-1748-math.floor(2048*0.1)=1120
        #        Norm=1.0
        # host3: thin_provisioning_support = False
        #        free_capacity_gb=512, free=256-512*0=256
        #        Norm=0.292383292383
        # host4: thin_provisioning_support = True
        #        free_capacity_gb=200,
        #        free=2048*1.0-2047-math.floor(2048*0.05)=-101
        #        Norm=0.0
        # host5: free_capacity_gb=unknown free=-1
        #        Norm=0.0819000819001

        # so, host2 should win:
        weight_properties = {
            'size': 1,
            'volume_type': volume_type,
        }
        weighed_host = self._get_weighed_hosts(
            backend_info_list,
            weight_properties=weight_properties)[0]
        self.assertEqual(1.0, weighed_host.weight)
        self.assertEqual(winner, utils.extract_host(weighed_host.obj.host))

    @ddt.data(
        {'volume_type': {'extra_specs': {'provisioning:type': 'thin'}},
         'winner': 'host4'},
        {'volume_type': {'extra_specs': {'provisioning:type': 'thick'}},
         'winner': 'host2'},
        {'volume_type': {'extra_specs': {}},
         'winner': 'host4'},
        {'volume_type': {},
         'winner': 'host4'},
        {'volume_type': None,
         'winner': 'host4'},
    )
    @ddt.unpack
    def test_capacity_weight_multiplier1(self, volume_type, winner):
        self.flags(capacity_weight_multiplier=-1.0)
        backend_info_list = self._get_all_backends()

        # Results for the 1st test
        # {'provisioning:type': 'thin'}:
        # host1: thin_provisioning_support = False
        #        free_capacity_gb=1024,
        #        free=-(1024-math.floor(1024*0.1))=-922
        #        Norm=-0.00829542413701
        # host2: thin_provisioning_support = True
        #        free_capacity_gb=300,
        #        free=-(2048*1.5-1748-math.floor(2048*0.1))=-1120
        #        Norm=-0.00990099009901
        # host3: thin_provisioning_support = False
        #        free_capacity_gb=512, free=-(256-512*0)=-256
        #        Norm=--0.002894884083
        # host4: thin_provisioning_support = True
        #        free_capacity_gb=200,
        #        free=-(2048*1.0-2047-math.floor(2048*0.05))=101
        #        Norm=0.0
        # host5: free_capacity_gb=unknown free=-float('inf')
        #        Norm=-1.0

        # so, host4 should win:
        weight_properties = {
            'size': 1,
            'volume_type': volume_type,
        }
        weighed_host = self._get_weighed_hosts(
            backend_info_list,
            weight_properties=weight_properties)[0]
        self.assertEqual(0.0, weighed_host.weight)
        self.assertEqual(winner, utils.extract_host(weighed_host.obj.host))

    @ddt.data(
        {'volume_type': {'extra_specs': {'provisioning:type': 'thin'}},
         'winner': 'host2'},
        {'volume_type': {'extra_specs': {'provisioning:type': 'thick'}},
         'winner': 'host1'},
        {'volume_type': {'extra_specs': {}},
         'winner': 'host2'},
        {'volume_type': {},
         'winner': 'host2'},
        {'volume_type': None,
         'winner': 'host2'},
    )
    @ddt.unpack
    def test_capacity_weight_multiplier2(self, volume_type, winner):
        self.flags(capacity_weight_multiplier=2.0)
        backend_info_list = self._get_all_backends()

        # Results for the 1st test
        # {'provisioning:type': 'thin'}:
        # host1: thin_provisioning_support = False
        #        free_capacity_gb=1024,
        #        free=(1024-math.floor(1024*0.1))*2=1844
        #        Norm=1.67567567568
        # host2: thin_provisioning_support = True
        #        free_capacity_gb=300,
        #        free=(2048*1.5-1748-math.floor(2048*0.1))*2=2240
        #        Norm=2.0
        # host3: thin_provisioning_support = False
        #        free_capacity_gb=512, free=(256-512*0)*2=512
        #        Norm=0.584766584767
        # host4: thin_provisioning_support = True
        #        free_capacity_gb=200,
        #        free=(2048*1.0-2047-math.floor(2048*0.05))*2=-202
        #        Norm=0.0
        # host5: free_capacity_gb=unknown free=-2
        #        Norm=0.1638001638

        # so, host2 should win:
        weight_properties = {
            'size': 1,
            'volume_type': volume_type,
        }
        weighed_host = self._get_weighed_hosts(
            backend_info_list,
            weight_properties=weight_properties)[0]
        self.assertEqual(1.0 * 2, weighed_host.weight)
        self.assertEqual(winner, utils.extract_host(weighed_host.obj.host))

    def test_capacity_weight_no_unknown_or_infinite(self):
        self.flags(capacity_weight_multiplier=-1.0)
        del self.host_manager.service_states['host5']
        backend_info_list = self._get_all_backends()

        # host1: thin_provisioning_support = False
        #        free_capacity_gb=1024,
        #        free=(1024-math.floor(1024*0.1))=-922
        #        Norm=-0.837837837838
        # host2: thin_provisioning_support = True
        #        free_capacity_gb=300,
        #        free=(2048*1.5-1748-math.floor(2048*0.1))=-1120
        #        Norm=-1.0
        # host3: thin_provisioning_support = False
        #        free_capacity_gb=512, free=(256-512*0)=-256
        #        Norm=-0.292383292383
        # host4: thin_provisioning_support = True
        #        free_capacity_gb=200,
        #        free=(2048*1.0-2047-math.floor(2048*0.05))=101
        #        Norm=0.0

        # so, host4 should win:
        weighed_hosts = self._get_weighed_hosts(backend_info_list)
        best_host = weighed_hosts[0]
        self.assertEqual(0.0, best_host.weight)
        self.assertEqual('host4', utils.extract_host(best_host.obj.host))
        # and host2 is the worst:
        worst_host = weighed_hosts[-1]
        self.assertEqual(-1.0, worst_host.weight)
        self.assertEqual('host2', utils.extract_host(worst_host.obj.host))

    def test_capacity_weight_free_unknown(self):
        self.flags(capacity_weight_multiplier=-1.0)
        self.host_manager.service_states['host5'] = {
            'total_capacity_gb': 3000,
            'free_capacity_gb': 'unknown',
            'allocated_capacity_gb': 1548,
            'provisioned_capacity_gb': 1548,
            'max_over_subscription_ratio': 1.0,
            'thin_provisioning_support': True,
            'thick_provisioning_support': False,
            'reserved_percentage': 5,
            'timestamp': datetime.utcnow()}
        backend_info_list = self._get_all_backends()

        # host1: thin_provisioning_support = False
        #        free_capacity_gb=1024,
        #        free=(1024-math.floor(1024*0.1))=-922
        #        Norm= -0.00829542413701
        # host2: thin_provisioning_support = True
        #        free_capacity_gb=300,
        #        free=(2048*1.5-1748-math.floor(2048*0.1))=-1120
        #        Norm=-0.00990099009901
        # host3: thin_provisioning_support = False
        #        free_capacity_gb=512, free=(256-512*0)=-256
        #        Norm=-0.002894884083
        # host4: thin_provisioning_support = True
        #        free_capacity_gb=200,
        #        free=(2048*1.0-2047-math.floor(2048*0.05))=101
        #        Norm=0.0
        # host5: free_capacity_gb=unknown free=3000
        #        Norm=-1.0

        # so, host4 should win:
        weighed_hosts = self._get_weighed_hosts(backend_info_list)
        best_host = weighed_hosts[0]
        self.assertEqual(0.0, best_host.weight)
        self.assertEqual('host4', utils.extract_host(best_host.obj.host))
        # and host5 is the worst:
        worst_host = weighed_hosts[-1]
        self.assertEqual(-1.0, worst_host.weight)
        self.assertEqual('host5', utils.extract_host(worst_host.obj.host))

    def test_capacity_weight_cap_unknown(self):
        self.flags(capacity_weight_multiplier=-1.0)
        self.host_manager.service_states['host5'] = {
            'total_capacity_gb': 'unknown',
            'free_capacity_gb': 3000,
            'allocated_capacity_gb': 1548,
            'provisioned_capacity_gb': 1548,
            'max_over_subscription_ratio': 1.0,
            'thin_provisioning_support': True,
            'thick_provisioning_support': False,
            'reserved_percentage': 5,
            'timestamp': datetime.utcnow()}
        backend_info_list = self._get_all_backends()

        # host1: thin_provisioning_support = False
        #        free_capacity_gb=1024,
        #        free=(1024-math.floor(1024*0.1))=-922
        #        Norm= -0.00829542413701
        # host2: thin_provisioning_support = True
        #        free_capacity_gb=300,
        #        free=(2048*1.5-1748-math.floor(2048*0.1))=-1120
        #        Norm=-0.00990099009901
        # host3: thin_provisioning_support = False
        #        free_capacity_gb=512, free=(256-512*0)=-256
        #        Norm=-0.002894884083
        # host4: thin_provisioning_support = True
        #        free_capacity_gb=200,
        #        free=(2048*1.0-2047-math.floor(2048*0.05))=101
        #        Norm=0.0
        # host5: free_capacity_gb=3000 free=unknown
        #        Norm=-1.0

        # so, host4 should win:
        weighed_hosts = self._get_weighed_hosts(backend_info_list)
        best_host = weighed_hosts[0]
        self.assertEqual(0.0, best_host.weight)
        self.assertEqual('host4', utils.extract_host(best_host.obj.host))
        # and host5 is the worst:
        worst_host = weighed_hosts[-1]
        self.assertEqual(-1.0, worst_host.weight)
        self.assertEqual('host5', utils.extract_host(worst_host.obj.host))

    def test_capacity_weight_free_infinite(self):
        self.flags(capacity_weight_multiplier=-1.0)
        self.host_manager.service_states['host5'] = {
            'total_capacity_gb': 3000,
            'free_capacity_gb': 'infinite',
            'allocated_capacity_gb': 1548,
            'provisioned_capacity_gb': 1548,
            'max_over_subscription_ratio': 1.0,
            'thin_provisioning_support': True,
            'thick_provisioning_support': False,
            'reserved_percentage': 5,
            'timestamp': datetime.utcnow()}
        backend_info_list = self._get_all_backends()

        # host1: thin_provisioning_support = False
        #        free_capacity_gb=1024,
        #        free=(1024-math.floor(1024*0.1))=-922
        #        Norm= -0.00829542413701
        # host2: thin_provisioning_support = True
        #        free_capacity_gb=300,
        #        free=(2048*1.5-1748-math.floor(2048*0.1))=-1120
        #        Norm=-0.00990099009901
        # host3: thin_provisioning_support = False
        #        free_capacity_gb=512, free=(256-512*0)=-256
        #        Norm=-0.002894884083
        # host4: thin_provisioning_support = True
        #        free_capacity_gb=200,
        #        free=(2048*1.0-2047-math.floor(2048*0.05))=101
        #        Norm=0.0
        # host5: free_capacity_gb=infinite free=3000
        #        Norm=-1.0

        # so, host4 should win:
        weighed_hosts = self._get_weighed_hosts(backend_info_list)
        best_host = weighed_hosts[0]
        self.assertEqual(0.0, best_host.weight)
        self.assertEqual('host4', utils.extract_host(best_host.obj.host))
        # and host5 is the worst:
        worst_host = weighed_hosts[-1]
        self.assertEqual(-1.0, worst_host.weight)
        self.assertEqual('host5', utils.extract_host(worst_host.obj.host))

    def test_capacity_weight_cap_infinite(self):
        self.flags(capacity_weight_multiplier=-1.0)
        self.host_manager.service_states['host5'] = {
            'total_capacity_gb': 'infinite',
            'free_capacity_gb': 3000,
            'allocated_capacity_gb': 1548,
            'provisioned_capacity_gb': 1548,
            'max_over_subscription_ratio': 1.0,
            'thin_provisioning_support': True,
            'thick_provisioning_support': False,
            'reserved_percentage': 5,
            'timestamp': datetime.utcnow()}
        backend_info_list = self._get_all_backends()

        # host1: thin_provisioning_support = False
        #        free_capacity_gb=1024,
        #        free=(1024-math.floor(1024*0.1))=-922
        #        Norm= -0.00829542413701
        # host2: thin_provisioning_support = True
        #        free_capacity_gb=300,
        #        free=(2048*1.5-1748-math.floor(2048*0.1))=-1120
        #        Norm=-0.00990099009901
        # host3: thin_provisioning_support = False
        #        free_capacity_gb=512, free=(256-512*0)=-256
        #        Norm=-0.002894884083
        # host4: thin_provisioning_support = True
        #        free_capacity_gb=200,
        #        free=(2048*1.0-2047-math.floor(2048*0.05))=101
        #        Norm=0.0
        # host5: free_capacity_gb=3000 free=infinite
        #        Norm=-1.0

        # so, host4 should win:
        weighed_hosts = self._get_weighed_hosts(backend_info_list)
        best_host = weighed_hosts[0]
        self.assertEqual(0.0, best_host.weight)
        self.assertEqual('host4', utils.extract_host(best_host.obj.host))
        # and host5 is the worst:
        worst_host = weighed_hosts[-1]
        self.assertEqual(-1.0, worst_host.weight)
        self.assertEqual('host5', utils.extract_host(worst_host.obj.host))
