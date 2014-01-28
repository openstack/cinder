# Copyright 2011 OpenStack Foundation  # All Rights Reserved.
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
Tests For Scheduler Host Filters.
"""

import mock

from cinder import context
from cinder import db
from cinder.openstack.common import jsonutils
from cinder.openstack.common.scheduler import filters
from cinder import test
from cinder.tests.scheduler import fakes
from cinder.tests import utils


class HostFiltersTestCase(test.TestCase):
    """Test case for host filters."""

    def setUp(self):
        super(HostFiltersTestCase, self).setUp()
        self.context = context.RequestContext('fake', 'fake')
        self.json_query = jsonutils.dumps(
            ['and',
                ['>=', '$free_capacity_gb', 1024],
                ['>=', '$total_capacity_gb', 10 * 1024]])
        # This has a side effect of testing 'get_filter_classes'
        # when specifying a method (in this case, our standard filters)
        filter_handler = filters.HostFilterHandler('cinder.scheduler.filters')
        classes = filter_handler.get_all_classes()
        self.class_map = {}
        for cls in classes:
            self.class_map[cls.__name__] = cls

    @mock.patch('cinder.utils.service_is_up')
    def test_capacity_filter_passes(self, _mock_serv_is_up):
        _mock_serv_is_up.return_value = True
        filt_cls = self.class_map['CapacityFilter']()
        filter_properties = {'size': 100}
        service = {'disabled': False}
        host = fakes.FakeHostState('host1',
                                   {'free_capacity_gb': 200,
                                    'updated_at': None,
                                    'service': service})
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    @mock.patch('cinder.utils.service_is_up')
    def test_capacity_filter_fails(self, _mock_serv_is_up):
        _mock_serv_is_up.return_value = True
        filt_cls = self.class_map['CapacityFilter']()
        filter_properties = {'size': 100}
        service = {'disabled': False}
        host = fakes.FakeHostState('host1',
                                   {'free_capacity_gb': 120,
                                    'reserved_percentage': 20,
                                    'updated_at': None,
                                    'service': service})
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    @mock.patch('cinder.utils.service_is_up')
    def test_capacity_filter_passes_infinite(self, _mock_serv_is_up):
        _mock_serv_is_up.return_value = True
        filt_cls = self.class_map['CapacityFilter']()
        filter_properties = {'size': 100}
        service = {'disabled': False}
        host = fakes.FakeHostState('host1',
                                   {'free_capacity_gb': 'infinite',
                                    'updated_at': None,
                                    'service': service})
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    @mock.patch('cinder.utils.service_is_up')
    def test_capacity_filter_passes_unknown(self, _mock_serv_is_up):
        _mock_serv_is_up.return_value = True
        filt_cls = self.class_map['CapacityFilter']()
        filter_properties = {'size': 100}
        service = {'disabled': False}
        host = fakes.FakeHostState('host1',
                                   {'free_capacity_gb': 'unknown',
                                    'updated_at': None,
                                    'service': service})
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    @mock.patch('cinder.utils.service_is_up')
    def test_affinity_different_filter_passes(self, _mock_serv_is_up):
        _mock_serv_is_up.return_value = True
        filt_cls = self.class_map['DifferentBackendFilter']()
        service = {'disabled': False}
        host = fakes.FakeHostState('host2',
                                   {'free_capacity_gb': '1000',
                                    'updated_at': None,
                                    'service': service})
        volume = utils.create_volume(self.context, host='host1')
        vol_id = volume.id

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': {
            'different_host': [vol_id], }}

        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_affinity_different_filter_no_list_passes(self):
        filt_cls = self.class_map['DifferentBackendFilter']()
        host = fakes.FakeHostState('host2', {})
        volume = utils.create_volume(self.context, host='host2')
        vol_id = volume.id

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': {
            'different_host': vol_id}}

        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def test_affinity_different_filter_fails(self):
        filt_cls = self.class_map['DifferentBackendFilter']()
        host = fakes.FakeHostState('host1', {})
        volume = utils.create_volume(self.context, host='host1')
        vol_id = volume.id

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': {
            'different_host': [vol_id], }}

        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def test_affinity_different_filter_handles_none(self):
        filt_cls = self.class_map['DifferentBackendFilter']()
        host = fakes.FakeHostState('host1', {})

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': None}

        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_affinity_different_filter_handles_deleted_instance(self):
        filt_cls = self.class_map['DifferentBackendFilter']()
        host = fakes.FakeHostState('host1', {})
        volume = utils.create_volume(self.context, host='host1')
        vol_id = volume.id
        db.volume_destroy(utils.get_test_admin_context(), vol_id)

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': {
            'different_host': [vol_id], }}

        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_affinity_different_filter_fail_nonuuid_hint(self):
        filt_cls = self.class_map['DifferentBackendFilter']()
        host = fakes.FakeHostState('host1', {})

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': {
            'different_host': "NOT-a-valid-UUID", }}

        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def test_affinity_different_filter_handles_multiple_uuids(self):
        filt_cls = self.class_map['DifferentBackendFilter']()
        host = fakes.FakeHostState('host1', {})
        volume1 = utils.create_volume(self.context, host='host2')
        vol_id1 = volume1.id
        volume2 = utils.create_volume(self.context, host='host3')
        vol_id2 = volume2.id

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': {
            'different_host': [vol_id1, vol_id2], }}

        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_affinity_different_filter_handles_invalid_uuids(self):
        filt_cls = self.class_map['DifferentBackendFilter']()
        host = fakes.FakeHostState('host1', {})
        volume = utils.create_volume(self.context, host='host2')
        vol_id = volume.id

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': {
            'different_host': [vol_id, "NOT-a-valid-UUID"], }}

        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def test_affinity_same_filter_no_list_passes(self):
        filt_cls = self.class_map['SameBackendFilter']()
        host = fakes.FakeHostState('host1', {})
        volume = utils.create_volume(self.context, host='host1')
        vol_id = volume.id

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': {
            'same_host': vol_id}}

        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_affinity_same_filter_passes(self):
        filt_cls = self.class_map['SameBackendFilter']()
        host = fakes.FakeHostState('host1', {})
        volume = utils.create_volume(self.context, host='host1')
        vol_id = volume.id

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': {
            'same_host': [vol_id], }}

        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_affinity_same_filter_fails(self):
        filt_cls = self.class_map['SameBackendFilter']()
        host = fakes.FakeHostState('host1', {})
        volume = utils.create_volume(self.context, host='host2')
        vol_id = volume.id

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': {
            'same_host': [vol_id], }}

        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def test_affinity_same_filter_handles_none(self):
        filt_cls = self.class_map['SameBackendFilter']()
        host = fakes.FakeHostState('host1', {})

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': None}

        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_affinity_same_filter_handles_deleted_instance(self):
        filt_cls = self.class_map['SameBackendFilter']()
        host = fakes.FakeHostState('host1', {})
        volume = utils.create_volume(self.context, host='host2')
        vol_id = volume.id
        db.volume_destroy(utils.get_test_admin_context(), vol_id)

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': {
            'same_host': [vol_id], }}

        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def test_affinity_same_filter_fail_nonuuid_hint(self):
        filt_cls = self.class_map['SameBackendFilter']()
        host = fakes.FakeHostState('host1', {})

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': {
            'same_host': "NOT-a-valid-UUID", }}

        self.assertFalse(filt_cls.host_passes(host, filter_properties))
