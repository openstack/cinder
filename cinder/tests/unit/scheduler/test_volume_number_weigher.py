# Copyright 2014 OpenStack Foundation
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
Tests For Volume Number Weigher.
"""

import mock
from oslo_config import cfg

from cinder import context
from cinder.db.sqlalchemy import api
from cinder.openstack.common.scheduler import weights
from cinder.scheduler.weights import volume_number
from cinder import test
from cinder.tests.unit.scheduler import fakes
from cinder.volume import utils

CONF = cfg.CONF


def fake_volume_data_get_for_host(context, host, count_only=False):
    host = utils.extract_host(host)
    if host == 'host1':
        return 1
    elif host == 'host2':
        return 2
    elif host == 'host3':
        return 3
    elif host == 'host4':
        return 4
    elif host == 'host5':
        return 5
    else:
        return 6


class VolumeNumberWeigherTestCase(test.TestCase):
    def setUp(self):
        super(VolumeNumberWeigherTestCase, self).setUp()
        self.context = context.get_admin_context()
        self.host_manager = fakes.FakeHostManager()
        self.weight_handler = weights.HostWeightHandler(
            'cinder.scheduler.weights')

    def _get_weighed_host(self, hosts, weight_properties=None):
        if weight_properties is None:
            weight_properties = {'context': self.context}
        return self.weight_handler.get_weighed_objects(
            [volume_number.VolumeNumberWeigher],
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

    def test_volume_number_weight_multiplier1(self):
        self.flags(volume_number_multiplier=-1.0)
        hostinfo_list = self._get_all_hosts()

        # host1: 1 volume    Norm=0.0
        # host2: 2 volumes
        # host3: 3 volumes
        # host4: 4 volumes
        # host5: 5 volumes   Norm=-1.0
        # so, host1 should win:
        with mock.patch.object(api, 'volume_data_get_for_host',
                               fake_volume_data_get_for_host):
            weighed_host = self._get_weighed_host(hostinfo_list)
            self.assertEqual(0.0, weighed_host.weight)
            self.assertEqual('host1',
                             utils.extract_host(weighed_host.obj.host))

    def test_volume_number_weight_multiplier2(self):
        self.flags(volume_number_multiplier=1.0)
        hostinfo_list = self._get_all_hosts()

        # host1: 1 volume      Norm=0
        # host2: 2 volumes
        # host3: 3 volumes
        # host4: 4 volumes
        # host5: 5 volumes     Norm=1
        # so, host5 should win:
        with mock.patch.object(api, 'volume_data_get_for_host',
                               fake_volume_data_get_for_host):
            weighed_host = self._get_weighed_host(hostinfo_list)
            self.assertEqual(1.0, weighed_host.weight)
            self.assertEqual('host5',
                             utils.extract_host(weighed_host.obj.host))
