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

from unittest import mock

from cinder.common import constants
from cinder import context
from cinder.db.sqlalchemy import api
from cinder.scheduler import weights
from cinder.tests.unit import fake_constants
from cinder.tests.unit.scheduler import fakes
from cinder.tests.unit import test
from cinder.volume import volume_utils


def fake_volume_data_get_for_host(context, host, count_only=False):
    host = volume_utils.extract_host(host)
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
        uid = fake_constants.USER_ID
        pid = fake_constants.PROJECT_ID
        self.context = context.RequestContext(user_id=uid,
                                              project_id=pid,
                                              is_admin=False,
                                              read_deleted="no",
                                              overwrite=False)
        self.host_manager = fakes.FakeHostManager()
        self.weight_handler = weights.OrderedHostWeightHandler(
            'cinder.scheduler.weights')

    def _get_weighed_host(self, hosts, weight_properties=None):
        if weight_properties is None:
            weight_properties = {'context': self.context}
        return self.weight_handler.get_weighed_objects(
            [weights.volume_number.VolumeNumberWeigher],
            hosts,
            weight_properties)[0]

    @mock.patch('cinder.db.sqlalchemy.api.service_get_all')
    def _get_all_backends(self, _mock_service_get_all, disabled=False):
        ctxt = context.get_admin_context()
        fakes.mock_host_manager_db_calls(_mock_service_get_all,
                                         disabled=disabled)
        backend_states = self.host_manager.get_all_backend_states(ctxt)
        _mock_service_get_all.assert_called_once_with(
            ctxt,
            None,  # backend_match_level
            topic=constants.VOLUME_TOPIC,
            frozen=False,
            disabled=disabled)
        return backend_states

    def test_volume_number_weight_multiplier1(self):
        self.flags(volume_number_multiplier=-1.0)
        backend_info_list = self._get_all_backends()

        # host1: 1 volume    Norm=0.0
        # host2: 2 volumes
        # host3: 3 volumes
        # host4: 4 volumes
        # host5: 5 volumes   Norm=-1.0
        # so, host1 should win:
        with mock.patch.object(api, 'volume_data_get_for_host',
                               fake_volume_data_get_for_host):
            weighed_host = self._get_weighed_host(backend_info_list)
            self.assertEqual(0.0, weighed_host.weight)
            self.assertEqual('host1',
                             volume_utils.extract_host(weighed_host.obj.host))

    def test_volume_number_weight_multiplier2(self):
        self.flags(volume_number_multiplier=1.0)
        backend_info_list = self._get_all_backends()

        # host1: 1 volume      Norm=0
        # host2: 2 volumes
        # host3: 3 volumes
        # host4: 4 volumes
        # host5: 5 volumes     Norm=1
        # so, host5 should win:
        with mock.patch.object(api, 'volume_data_get_for_host',
                               fake_volume_data_get_for_host):
            weighed_host = self._get_weighed_host(backend_info_list)
            self.assertEqual(1.0, weighed_host.weight)
            self.assertEqual('host5',
                             volume_utils.extract_host(weighed_host.obj.host))
