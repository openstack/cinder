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
from oslo_serialization import jsonutils
from requests import exceptions as request_exceptions

from cinder.compute import nova
from cinder import context
from cinder import db
from cinder import exception
from cinder.openstack.common.scheduler import filters
from cinder import test
from cinder.tests.unit.scheduler import fakes
from cinder.tests.unit import utils


class HostFiltersTestCase(test.TestCase):
    """Test case for host filters."""

    def setUp(self):
        super(HostFiltersTestCase, self).setUp()
        self.context = context.RequestContext('fake', 'fake')
        # This has a side effect of testing 'get_filter_classes'
        # when specifying a method (in this case, our standard filters)
        filter_handler = filters.HostFilterHandler('cinder.scheduler.filters')
        classes = filter_handler.get_all_classes()
        self.class_map = {}
        for cls in classes:
            self.class_map[cls.__name__] = cls


class CapacityFilterTestCase(HostFiltersTestCase):
    def setUp(self):
        super(CapacityFilterTestCase, self).setUp()
        self.json_query = jsonutils.dumps(
            ['and',
                ['>=', '$free_capacity_gb', 1024],
                ['>=', '$total_capacity_gb', 10 * 1024]])

    @mock.patch('cinder.utils.service_is_up')
    def test_filter_passes(self, _mock_serv_is_up):
        _mock_serv_is_up.return_value = True
        filt_cls = self.class_map['CapacityFilter']()
        filter_properties = {'size': 100}
        service = {'disabled': False}
        host = fakes.FakeHostState('host1',
                                   {'total_capacity_gb': 500,
                                    'free_capacity_gb': 200,
                                    'updated_at': None,
                                    'service': service})
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    @mock.patch('cinder.utils.service_is_up')
    def test_filter_current_host_passes(self, _mock_serv_is_up):
        _mock_serv_is_up.return_value = True
        filt_cls = self.class_map['CapacityFilter']()
        filter_properties = {'size': 100, 'vol_exists_on': 'host1'}
        service = {'disabled': False}
        host = fakes.FakeHostState('host1',
                                   {'total_capacity_gb': 100,
                                    'free_capacity_gb': 10,
                                    'updated_at': None,
                                    'service': service})
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    @mock.patch('cinder.utils.service_is_up')
    def test_filter_fails(self, _mock_serv_is_up):
        _mock_serv_is_up.return_value = True
        filt_cls = self.class_map['CapacityFilter']()
        filter_properties = {'size': 100}
        service = {'disabled': False}
        host = fakes.FakeHostState('host1',
                                   {'total_capacity_gb': 200,
                                    'free_capacity_gb': 120,
                                    'reserved_percentage': 20,
                                    'updated_at': None,
                                    'service': service})
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    @mock.patch('cinder.utils.service_is_up')
    def test_filter_fails_free_capacity_None(self, _mock_serv_is_up):
        _mock_serv_is_up.return_value = True
        filt_cls = self.class_map['CapacityFilter']()
        filter_properties = {'size': 100}
        service = {'disabled': False}
        host = fakes.FakeHostState('host1',
                                   {'free_capacity_gb': None,
                                    'updated_at': None,
                                    'service': service})
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    @mock.patch('cinder.utils.service_is_up')
    def test_filter_passes_infinite(self, _mock_serv_is_up):
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
    def test_filter_passes_unknown(self, _mock_serv_is_up):
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
    def test_filter_passes_total_infinite(self, _mock_serv_is_up):
        _mock_serv_is_up.return_value = True
        filt_cls = self.class_map['CapacityFilter']()
        filter_properties = {'size': 100}
        service = {'disabled': False}
        host = fakes.FakeHostState('host1',
                                   {'free_capacity_gb': 'infinite',
                                    'total_capacity_gb': 'infinite',
                                    'reserved_percentage': 0,
                                    'updated_at': None,
                                    'service': service})
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    @mock.patch('cinder.utils.service_is_up')
    def test_filter_passes_total_unknown(self, _mock_serv_is_up):
        _mock_serv_is_up.return_value = True
        filt_cls = self.class_map['CapacityFilter']()
        filter_properties = {'size': 100}
        service = {'disabled': False}
        host = fakes.FakeHostState('host1',
                                   {'free_capacity_gb': 'unknown',
                                    'total_capacity_gb': 'unknown',
                                    'reserved_percentage': 0,
                                    'updated_at': None,
                                    'service': service})
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    @mock.patch('cinder.utils.service_is_up')
    def test_filter_fails_total_infinite(self, _mock_serv_is_up):
        _mock_serv_is_up.return_value = True
        filt_cls = self.class_map['CapacityFilter']()
        filter_properties = {'size': 100}
        service = {'disabled': False}
        host = fakes.FakeHostState('host1',
                                   {'total_capacity_gb': 'infinite',
                                    'reserved_percentage': 5,
                                    'updated_at': None,
                                    'service': service})
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    @mock.patch('cinder.utils.service_is_up')
    def test_filter_fails_total_unknown(self, _mock_serv_is_up):
        _mock_serv_is_up.return_value = True
        filt_cls = self.class_map['CapacityFilter']()
        filter_properties = {'size': 100}
        service = {'disabled': False}
        host = fakes.FakeHostState('host1',
                                   {'total_capacity_gb': 'unknown',
                                    'reserved_percentage': 5,
                                    'updated_at': None,
                                    'service': service})
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    @mock.patch('cinder.utils.service_is_up')
    def test_filter_fails_total_zero(self, _mock_serv_is_up):
        _mock_serv_is_up.return_value = True
        filt_cls = self.class_map['CapacityFilter']()
        filter_properties = {'size': 100}
        service = {'disabled': False}
        host = fakes.FakeHostState('host1',
                                   {'total_capacity_gb': 0,
                                    'reserved_percentage': 5,
                                    'updated_at': None,
                                    'service': service})
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    @mock.patch('cinder.utils.service_is_up')
    def test_filter_thin_true_passes(self, _mock_serv_is_up):
        _mock_serv_is_up.return_value = True
        filt_cls = self.class_map['CapacityFilter']()
        filter_properties = {'size': 100,
                             'capabilities:thin_provisioning_support':
                                 '<is> True',
                             'capabilities:thick_provisioning_support':
                                 '<is> False'}
        service = {'disabled': False}
        host = fakes.FakeHostState('host1',
                                   {'total_capacity_gb': 500,
                                    'free_capacity_gb': 200,
                                    'provisioned_capacity_gb': 500,
                                    'max_over_subscription_ratio': 2.0,
                                    'reserved_percentage': 5,
                                    'thin_provisioning_support': True,
                                    'thick_provisioning_support': False,
                                    'updated_at': None,
                                    'service': service})
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    @mock.patch('cinder.utils.service_is_up')
    def test_filter_thin_true_passes2(self, _mock_serv_is_up):
        _mock_serv_is_up.return_value = True
        filt_cls = self.class_map['CapacityFilter']()
        filter_properties = {'size': 3000,
                             'capabilities:thin_provisioning_support':
                                 '<is> True',
                             'capabilities:thick_provisioning_support':
                                 '<is> False'}
        service = {'disabled': False}
        host = fakes.FakeHostState('host1',
                                   {'total_capacity_gb': 500,
                                    'free_capacity_gb': 200,
                                    'provisioned_capacity_gb': 7000,
                                    'max_over_subscription_ratio': 20,
                                    'reserved_percentage': 5,
                                    'thin_provisioning_support': True,
                                    'thick_provisioning_support': False,
                                    'updated_at': None,
                                    'service': service})
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    @mock.patch('cinder.utils.service_is_up')
    def test_filter_thin_false_passes(self, _mock_serv_is_up):
        _mock_serv_is_up.return_value = True
        filt_cls = self.class_map['CapacityFilter']()
        filter_properties = {'size': 100,
                             'capabilities:thin_provisioning_support':
                                 '<is> False',
                             'capabilities:thick_provisioning_support':
                                 '<is> True'}
        service = {'disabled': False}
        # If "thin_provisioning_support" is False,
        # "max_over_subscription_ratio" will be ignored.
        host = fakes.FakeHostState('host1',
                                   {'total_capacity_gb': 500,
                                    'free_capacity_gb': 200,
                                    'provisioned_capacity_gb': 300,
                                    'max_over_subscription_ratio': 1.0,
                                    'reserved_percentage': 5,
                                    'thin_provisioning_support': False,
                                    'thick_provisioning_support': True,
                                    'updated_at': None,
                                    'service': service})
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    @mock.patch('cinder.utils.service_is_up')
    def test_filter_over_subscription_less_than_1(self, _mock_serv_is_up):
        _mock_serv_is_up.return_value = True
        filt_cls = self.class_map['CapacityFilter']()
        filter_properties = {'size': 200,
                             'capabilities:thin_provisioning_support':
                                 '<is> True',
                             'capabilities:thick_provisioning_support':
                                 '<is> False'}
        service = {'disabled': False}
        host = fakes.FakeHostState('host1',
                                   {'total_capacity_gb': 500,
                                    'free_capacity_gb': 100,
                                    'provisioned_capacity_gb': 400,
                                    'max_over_subscription_ratio': 0.8,
                                    'reserved_percentage': 0,
                                    'thin_provisioning_support': True,
                                    'thick_provisioning_support': False,
                                    'updated_at': None,
                                    'service': service})
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    @mock.patch('cinder.utils.service_is_up')
    def test_filter_over_subscription_fails(self, _mock_serv_is_up):
        _mock_serv_is_up.return_value = True
        filt_cls = self.class_map['CapacityFilter']()
        filter_properties = {'size': 100,
                             'capabilities:thin_provisioning_support':
                                 '<is> True',
                             'capabilities:thick_provisioning_support':
                                 '<is> False'}
        service = {'disabled': False}
        host = fakes.FakeHostState('host1',
                                   {'total_capacity_gb': 500,
                                    'free_capacity_gb': 200,
                                    'provisioned_capacity_gb': 700,
                                    'max_over_subscription_ratio': 1.5,
                                    'reserved_percentage': 5,
                                    'thin_provisioning_support': True,
                                    'thick_provisioning_support': False,
                                    'updated_at': None,
                                    'service': service})
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    @mock.patch('cinder.utils.service_is_up')
    def test_filter_over_subscription_fails2(self, _mock_serv_is_up):
        _mock_serv_is_up.return_value = True
        filt_cls = self.class_map['CapacityFilter']()
        filter_properties = {'size': 2000,
                             'capabilities:thin_provisioning_support':
                                 '<is> True',
                             'capabilities:thick_provisioning_support':
                                 '<is> False'}
        service = {'disabled': False}
        host = fakes.FakeHostState('host1',
                                   {'total_capacity_gb': 500,
                                    'free_capacity_gb': 30,
                                    'provisioned_capacity_gb': 9000,
                                    'max_over_subscription_ratio': 20,
                                    'reserved_percentage': 0,
                                    'thin_provisioning_support': True,
                                    'thick_provisioning_support': False,
                                    'updated_at': None,
                                    'service': service})
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    @mock.patch('cinder.utils.service_is_up')
    def test_filter_reserved_thin_true_fails(self, _mock_serv_is_up):
        _mock_serv_is_up.return_value = True
        filt_cls = self.class_map['CapacityFilter']()
        filter_properties = {'size': 100,
                             'capabilities:thin_provisioning_support':
                                 '<is> True',
                             'capabilities:thick_provisioning_support':
                                 '<is> False'}
        service = {'disabled': False}
        host = fakes.FakeHostState('host1',
                                   {'total_capacity_gb': 500,
                                    'free_capacity_gb': 100,
                                    'provisioned_capacity_gb': 1000,
                                    'max_over_subscription_ratio': 2.0,
                                    'reserved_percentage': 5,
                                    'thin_provisioning_support': True,
                                    'thick_provisioning_support': False,
                                    'updated_at': None,
                                    'service': service})
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    @mock.patch('cinder.utils.service_is_up')
    def test_filter_reserved_thin_false_fails(self, _mock_serv_is_up):
        _mock_serv_is_up.return_value = True
        filt_cls = self.class_map['CapacityFilter']()
        filter_properties = {'size': 100,
                             'capabilities:thin_provisioning_support':
                                 '<is> False',
                             'capabilities:thick_provisioning_support':
                                 '<is> True'}
        service = {'disabled': False}
        # If "thin_provisioning_support" is False,
        # "max_over_subscription_ratio" will be ignored.
        host = fakes.FakeHostState('host1',
                                   {'total_capacity_gb': 500,
                                    'free_capacity_gb': 100,
                                    'provisioned_capacity_gb': 400,
                                    'max_over_subscription_ratio': 1.0,
                                    'reserved_percentage': 5,
                                    'thin_provisioning_support': False,
                                    'thick_provisioning_support': True,
                                    'updated_at': None,
                                    'service': service})
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    @mock.patch('cinder.utils.service_is_up')
    def test_filter_reserved_thin_thick_true_fails(self, _mock_serv_is_up):
        _mock_serv_is_up.return_value = True
        filt_cls = self.class_map['CapacityFilter']()
        filter_properties = {'size': 100,
                             'capabilities:thin_provisioning_support':
                                 '<is> True',
                             'capabilities:thick_provisioning_support':
                                 '<is> True'}
        service = {'disabled': False}
        host = fakes.FakeHostState('host1',
                                   {'total_capacity_gb': 500,
                                    'free_capacity_gb': 0,
                                    'provisioned_capacity_gb': 800,
                                    'max_over_subscription_ratio': 2.0,
                                    'reserved_percentage': 5,
                                    'thin_provisioning_support': True,
                                    'thick_provisioning_support': True,
                                    'updated_at': None,
                                    'service': service})
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    @mock.patch('cinder.utils.service_is_up')
    def test_filter_reserved_thin_thick_true_passes(self, _mock_serv_is_up):
        _mock_serv_is_up.return_value = True
        filt_cls = self.class_map['CapacityFilter']()
        filter_properties = {'size': 100,
                             'capabilities:thin_provisioning_support':
                                 '<is> True',
                             'capabilities:thick_provisioning_support':
                                 '<is> True'}
        service = {'disabled': False}
        host = fakes.FakeHostState('host1',
                                   {'total_capacity_gb': 500,
                                    'free_capacity_gb': 125,
                                    'provisioned_capacity_gb': 400,
                                    'max_over_subscription_ratio': 2.0,
                                    'reserved_percentage': 5,
                                    'thin_provisioning_support': True,
                                    'thick_provisioning_support': True,
                                    'updated_at': None,
                                    'service': service})
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    @mock.patch('cinder.utils.service_is_up')
    def test_filter_reserved_thin_true_passes(self, _mock_serv_is_up):
        _mock_serv_is_up.return_value = True
        filt_cls = self.class_map['CapacityFilter']()
        filter_properties = {'size': 100,
                             'capabilities:thin_provisioning_support':
                                 '<is> True',
                             'capabilities:thick_provisioning_support':
                                 '<is> False'}
        service = {'disabled': False}
        host = fakes.FakeHostState('host1',
                                   {'total_capacity_gb': 500,
                                    'free_capacity_gb': 80,
                                    'provisioned_capacity_gb': 600,
                                    'max_over_subscription_ratio': 2.0,
                                    'reserved_percentage': 5,
                                    'thin_provisioning_support': True,
                                    'thick_provisioning_support': False,
                                    'updated_at': None,
                                    'service': service})
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    @mock.patch('cinder.utils.service_is_up')
    def test_filter_reserved_thin_thick_true_fails2(self, _mock_serv_is_up):
        _mock_serv_is_up.return_value = True
        filt_cls = self.class_map['CapacityFilter']()
        filter_properties = {'size': 100,
                             'capabilities:thin_provisioning_support':
                                 '<is> True',
                             'capabilities:thick_provisioning_support':
                                 '<is> True'}
        service = {'disabled': False}
        host = fakes.FakeHostState('host1',
                                   {'total_capacity_gb': 500,
                                    'free_capacity_gb': 99,
                                    'provisioned_capacity_gb': 1000,
                                    'max_over_subscription_ratio': 2.0,
                                    'reserved_percentage': 5,
                                    'thin_provisioning_support': True,
                                    'thick_provisioning_support': True,
                                    'updated_at': None,
                                    'service': service})
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    @mock.patch('cinder.utils.service_is_up')
    def test_filter_reserved_thin_thick_true_passes2(self, _mock_serv_is_up):
        _mock_serv_is_up.return_value = True
        filt_cls = self.class_map['CapacityFilter']()
        filter_properties = {'size': 100,
                             'capabilities:thin_provisioning_support':
                                 '<is> True',
                             'capabilities:thick_provisioning_support':
                                 '<is> True'}
        service = {'disabled': False}
        host = fakes.FakeHostState('host1',
                                   {'total_capacity_gb': 500,
                                    'free_capacity_gb': 100,
                                    'provisioned_capacity_gb': 400,
                                    'max_over_subscription_ratio': 2.0,
                                    'reserved_percentage': 0,
                                    'thin_provisioning_support': True,
                                    'thick_provisioning_support': True,
                                    'updated_at': None,
                                    'service': service})
        self.assertTrue(filt_cls.host_passes(host, filter_properties))


class AffinityFilterTestCase(HostFiltersTestCase):
    @mock.patch('cinder.utils.service_is_up')
    def test_different_filter_passes(self, _mock_serv_is_up):
        _mock_serv_is_up.return_value = True
        filt_cls = self.class_map['DifferentBackendFilter']()
        service = {'disabled': False}
        host = fakes.FakeHostState('host1:pool0',
                                   {'free_capacity_gb': '1000',
                                    'updated_at': None,
                                    'service': service})
        volume = utils.create_volume(self.context, host='host1:pool1')
        vol_id = volume.id

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': {
            'different_host': [vol_id], }}

        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    @mock.patch('cinder.utils.service_is_up')
    def test_different_filter_legacy_volume_hint_passes(
            self, _mock_serv_is_up):
        _mock_serv_is_up.return_value = True
        filt_cls = self.class_map['DifferentBackendFilter']()
        service = {'disabled': False}
        host = fakes.FakeHostState('host1:pool0',
                                   {'free_capacity_gb': '1000',
                                    'updated_at': None,
                                    'service': service})
        volume = utils.create_volume(self.context, host='host1')
        vol_id = volume.id

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': {
            'different_host': [vol_id], }}

        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_different_filter_non_list_fails(self):
        filt_cls = self.class_map['DifferentBackendFilter']()
        host = fakes.FakeHostState('host2', {})
        volume = utils.create_volume(self.context, host='host2')
        vol_id = volume.id

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': {
            'different_host': vol_id}}

        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def test_different_filter_fails(self):
        filt_cls = self.class_map['DifferentBackendFilter']()
        host = fakes.FakeHostState('host1', {})
        volume = utils.create_volume(self.context, host='host1')
        vol_id = volume.id

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': {
            'different_host': [vol_id], }}

        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def test_different_filter_handles_none(self):
        filt_cls = self.class_map['DifferentBackendFilter']()
        host = fakes.FakeHostState('host1', {})

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': None}

        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_different_filter_handles_deleted_instance(self):
        filt_cls = self.class_map['DifferentBackendFilter']()
        host = fakes.FakeHostState('host1', {})
        volume = utils.create_volume(self.context, host='host1')
        vol_id = volume.id
        db.volume_destroy(utils.get_test_admin_context(), vol_id)

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': {
            'different_host': [vol_id], }}

        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_different_filter_fail_nonuuid_hint(self):
        filt_cls = self.class_map['DifferentBackendFilter']()
        host = fakes.FakeHostState('host1', {})

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': {
            'different_host': "NOT-a-valid-UUID", }}

        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def test_different_filter_handles_multiple_uuids(self):
        filt_cls = self.class_map['DifferentBackendFilter']()
        host = fakes.FakeHostState('host1#pool0', {})
        volume1 = utils.create_volume(self.context, host='host1:pool1')
        vol_id1 = volume1.id
        volume2 = utils.create_volume(self.context, host='host1:pool3')
        vol_id2 = volume2.id

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': {
            'different_host': [vol_id1, vol_id2], }}

        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_different_filter_handles_invalid_uuids(self):
        filt_cls = self.class_map['DifferentBackendFilter']()
        host = fakes.FakeHostState('host1', {})
        volume = utils.create_volume(self.context, host='host2')
        vol_id = volume.id

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': {
            'different_host': [vol_id, "NOT-a-valid-UUID"], }}

        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def test_same_filter_no_list_passes(self):
        filt_cls = self.class_map['SameBackendFilter']()
        host = fakes.FakeHostState('host1', {})
        volume = utils.create_volume(self.context, host='host1')
        vol_id = volume.id

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': {
            'same_host': vol_id}}

        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_same_filter_passes(self):
        filt_cls = self.class_map['SameBackendFilter']()
        host = fakes.FakeHostState('host1#pool0', {})
        volume = utils.create_volume(self.context, host='host1#pool0')
        vol_id = volume.id

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': {
            'same_host': [vol_id], }}

        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_same_filter_legacy_vol_fails(self):
        filt_cls = self.class_map['SameBackendFilter']()
        host = fakes.FakeHostState('host1#pool0', {})
        volume = utils.create_volume(self.context, host='host1')
        vol_id = volume.id

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': {
            'same_host': [vol_id], }}

        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def test_same_filter_fails(self):
        filt_cls = self.class_map['SameBackendFilter']()
        host = fakes.FakeHostState('host1#pool0', {})
        volume = utils.create_volume(self.context, host='host1#pool1')
        vol_id = volume.id

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': {
            'same_host': [vol_id], }}

        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def test_same_filter_vol_list_pass(self):
        filt_cls = self.class_map['SameBackendFilter']()
        host = fakes.FakeHostState('host1', {})
        volume1 = utils.create_volume(self.context, host='host1')
        vol_id1 = volume1.id
        volume2 = utils.create_volume(self.context, host='host2')
        vol_id2 = volume2.id

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': {
            'same_host': [vol_id1, vol_id2], }}

        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_same_filter_handles_none(self):
        filt_cls = self.class_map['SameBackendFilter']()
        host = fakes.FakeHostState('host1', {})

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': None}

        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_same_filter_handles_deleted_instance(self):
        filt_cls = self.class_map['SameBackendFilter']()
        host = fakes.FakeHostState('host1', {})
        volume = utils.create_volume(self.context, host='host2')
        vol_id = volume.id
        db.volume_destroy(utils.get_test_admin_context(), vol_id)

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': {
            'same_host': [vol_id], }}

        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def test_same_filter_fail_nonuuid_hint(self):
        filt_cls = self.class_map['SameBackendFilter']()
        host = fakes.FakeHostState('host1', {})

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': {
            'same_host': "NOT-a-valid-UUID", }}

        self.assertFalse(filt_cls.host_passes(host, filter_properties))


class DriverFilterTestCase(HostFiltersTestCase):
    def test_passing_function(self):
        filt_cls = self.class_map['DriverFilter']()
        host1 = fakes.FakeHostState(
            'host1', {
                'capabilities': {
                    'filter_function': '1 == 1',
                }
            })

        filter_properties = {'volume_type': {}}

        self.assertTrue(filt_cls.host_passes(host1, filter_properties))

    def test_failing_function(self):
        filt_cls = self.class_map['DriverFilter']()
        host1 = fakes.FakeHostState(
            'host1', {
                'capabilities': {
                    'filter_function': '1 == 2',
                }
            })

        filter_properties = {'volume_type': {}}

        self.assertFalse(filt_cls.host_passes(host1, filter_properties))

    def test_no_filter_function(self):
        filt_cls = self.class_map['DriverFilter']()
        host1 = fakes.FakeHostState(
            'host1', {
                'capabilities': {
                    'filter_function': None,
                }
            })

        filter_properties = {'volume_type': {}}

        self.assertTrue(filt_cls.host_passes(host1, filter_properties))

    def test_not_implemented(self):
        filt_cls = self.class_map['DriverFilter']()
        host1 = fakes.FakeHostState(
            'host1', {
                'capabilities': {}
            })

        filter_properties = {'volume_type': {}}

        self.assertTrue(filt_cls.host_passes(host1, filter_properties))

    def test_no_volume_extra_specs(self):
        filt_cls = self.class_map['DriverFilter']()
        host1 = fakes.FakeHostState(
            'host1', {
                'capabilities': {
                    'filter_function': '1 == 1',
                }
            })

        filter_properties = {'volume_type': {}}

        self.assertTrue(filt_cls.host_passes(host1, filter_properties))

    def test_function_extra_spec_replacement(self):
        filt_cls = self.class_map['DriverFilter']()
        host1 = fakes.FakeHostState(
            'host1', {
                'capabilities': {
                    'filter_function': 'extra.var == 1',
                }
            })

        filter_properties = {
            'volume_type': {
                'extra_specs': {
                    'var': 1,
                }
            }
        }

        self.assertTrue(filt_cls.host_passes(host1, filter_properties))

    def test_function_stats_replacement(self):
        filt_cls = self.class_map['DriverFilter']()
        host1 = fakes.FakeHostState(
            'host1', {
                'total_capacity_gb': 100,
                'capabilities': {
                    'filter_function': 'stats.total_capacity_gb < 200',
                }
            })

        filter_properties = {'volume_type': {}}

        self.assertTrue(filt_cls.host_passes(host1, filter_properties))

    def test_function_volume_replacement(self):
        filt_cls = self.class_map['DriverFilter']()
        host1 = fakes.FakeHostState(
            'host1', {
                'capabilities': {
                    'filter_function': 'volume.size < 5',
                }
            })

        filter_properties = {
            'request_spec': {
                'volume_properties': {
                    'size': 1
                }
            }
        }

        self.assertTrue(filt_cls.host_passes(host1, filter_properties))

    def test_function_qos_spec_replacement(self):
        filt_cls = self.class_map['DriverFilter']()
        host1 = fakes.FakeHostState(
            'host1', {
                'capabilities': {
                    'filter_function': 'qos.var == 1',
                }
            })

        filter_properties = {
            'qos_specs': {
                'var': 1
            }
        }

        self.assertTrue(filt_cls.host_passes(host1, filter_properties))

    def test_function_exception_caught(self):
        filt_cls = self.class_map['DriverFilter']()
        host1 = fakes.FakeHostState(
            'host1', {
                'capabilities': {
                    'filter_function': '1 / 0 == 0',
                }
            })

        filter_properties = {}

        self.assertFalse(filt_cls.host_passes(host1, filter_properties))

    def test_function_empty_qos(self):
        filt_cls = self.class_map['DriverFilter']()
        host1 = fakes.FakeHostState(
            'host1', {
                'capabilities': {
                    'filter_function': 'qos.maxiops == 1',
                }
            })

        filter_properties = {
            'qos_specs': None
        }

        self.assertFalse(filt_cls.host_passes(host1, filter_properties))

    def test_capabilities(self):
        filt_cls = self.class_map['DriverFilter']()
        host1 = fakes.FakeHostState(
            'host1', {
                'capabilities': {
                    'foo': 10,
                    'filter_function': 'capabilities.foo == 10',
                },
            })

        filter_properties = {}

        self.assertTrue(filt_cls.host_passes(host1, filter_properties))

    def test_wrong_capabilities(self):
        filt_cls = self.class_map['DriverFilter']()
        host1 = fakes.FakeHostState(
            'host1', {
                'capabilities': {
                    'bar': 10,
                    'filter_function': 'capabilities.foo == 10',
                },
            })

        filter_properties = {}

        self.assertFalse(filt_cls.host_passes(host1, filter_properties))


class InstanceLocalityFilterTestCase(HostFiltersTestCase):
    def setUp(self):
        super(InstanceLocalityFilterTestCase, self).setUp()
        self.override_config('nova_endpoint_template',
                             'http://novahost:8774/v2/%(project_id)s')
        self.context.service_catalog = \
            [{'type': 'compute', 'name': 'nova', 'endpoints':
              [{'publicURL': 'http://novahost:8774/v2/e3f0833dc08b4cea'}]},
             {'type': 'identity', 'name': 'keystone', 'endpoints':
              [{'publicURL': 'http://keystonehost:5000/v2.0'}]}]

    @mock.patch('novaclient.client.discover_extensions')
    @mock.patch('cinder.compute.nova.novaclient')
    def test_same_host(self, _mock_novaclient, fake_extensions):
        _mock_novaclient.return_value = fakes.FakeNovaClient()
        fake_extensions.return_value = (
            fakes.FakeNovaClient().discover_extensions.show_all())
        filt_cls = self.class_map['InstanceLocalityFilter']()
        host = fakes.FakeHostState('host1', {})
        uuid = nova.novaclient().servers.create('host1')

        filter_properties = {'context': self.context,
                             'scheduler_hints': {'local_to_instance': uuid}}
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    @mock.patch('novaclient.client.discover_extensions')
    @mock.patch('cinder.compute.nova.novaclient')
    def test_different_host(self, _mock_novaclient, fake_extensions):
        _mock_novaclient.return_value = fakes.FakeNovaClient()
        fake_extensions.return_value = (
            fakes.FakeNovaClient().discover_extensions.show_all())
        filt_cls = self.class_map['InstanceLocalityFilter']()
        host = fakes.FakeHostState('host1', {})
        uuid = nova.novaclient().servers.create('host2')

        filter_properties = {'context': self.context,
                             'scheduler_hints': {'local_to_instance': uuid}}
        self.assertFalse(filt_cls.host_passes(host, filter_properties))

    def test_handles_none(self):
        filt_cls = self.class_map['InstanceLocalityFilter']()
        host = fakes.FakeHostState('host1', {})

        filter_properties = {'context': self.context,
                             'scheduler_hints': None}
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    def test_invalid_uuid(self):
        filt_cls = self.class_map['InstanceLocalityFilter']()
        host = fakes.FakeHostState('host1', {})

        filter_properties = {'context': self.context,
                             'scheduler_hints':
                             {'local_to_instance': 'e29b11d4-not-valid-a716'}}
        self.assertRaises(exception.InvalidUUID,
                          filt_cls.host_passes, host, filter_properties)

    @mock.patch('cinder.compute.nova.novaclient')
    def test_nova_no_extended_server_attributes(self, _mock_novaclient):
        _mock_novaclient.return_value = fakes.FakeNovaClient(
            ext_srv_attr=False)
        filt_cls = self.class_map['InstanceLocalityFilter']()
        host = fakes.FakeHostState('host1', {})
        uuid = nova.novaclient().servers.create('host1')

        filter_properties = {'context': self.context,
                             'scheduler_hints': {'local_to_instance': uuid}}
        self.assertRaises(exception.CinderException,
                          filt_cls.host_passes, host, filter_properties)

    @mock.patch('cinder.compute.nova.novaclient')
    def test_nova_down_does_not_alter_other_filters(self, _mock_novaclient):
        # Simulate Nova API is not available
        _mock_novaclient.side_effect = Exception

        filt_cls = self.class_map['InstanceLocalityFilter']()
        host = fakes.FakeHostState('host1', {})

        filter_properties = {'context': self.context, 'size': 100}
        self.assertTrue(filt_cls.host_passes(host, filter_properties))

    @mock.patch('novaclient.client.discover_extensions')
    @mock.patch('requests.request')
    def test_nova_timeout(self, _mock_request, fake_extensions):
        # Simulate a HTTP timeout
        _mock_request.side_effect = request_exceptions.Timeout
        fake_extensions.return_value = (
            fakes.FakeNovaClient().discover_extensions.show_all())

        filt_cls = self.class_map['InstanceLocalityFilter']()
        host = fakes.FakeHostState('host1', {})

        filter_properties = \
            {'context': self.context, 'scheduler_hints':
                {'local_to_instance': 'e29b11d4-15ef-34a9-a716-598a6f0b5467'}}
        self.assertRaises(exception.APITimeout,
                          filt_cls.host_passes, host, filter_properties)
