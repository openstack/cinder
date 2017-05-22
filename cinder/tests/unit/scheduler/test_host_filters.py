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

import ddt
import mock
from oslo_serialization import jsonutils
from requests import exceptions as request_exceptions

from cinder.compute import nova
from cinder import context
from cinder import db
from cinder import exception
from cinder.scheduler import filters
from cinder.scheduler.filters import extra_specs_ops
from cinder import test
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit.scheduler import fakes
from cinder.tests.unit import utils


class BackendFiltersTestCase(test.TestCase):
    """Test case for backend filters."""

    def setUp(self):
        super(BackendFiltersTestCase, self).setUp()
        self.context = context.RequestContext(fake.USER_ID, fake.PROJECT_ID)
        # This has a side effect of testing 'get_filter_classes'
        # when specifying a method (in this case, our standard filters)
        filter_handler = filters.BackendFilterHandler(
            'cinder.scheduler.filters')
        classes = filter_handler.get_all_classes()
        self.class_map = {}
        for cls in classes:
            self.class_map[cls.__name__] = cls


@ddt.ddt
@mock.patch('cinder.objects.service.Service.is_up',
            new_callable=mock.PropertyMock)
class CapacityFilterTestCase(BackendFiltersTestCase):
    def setUp(self):
        super(CapacityFilterTestCase, self).setUp()
        self.json_query = jsonutils.dumps(
            ['and',
                ['>=', '$free_capacity_gb', 1024],
                ['>=', '$total_capacity_gb', 10 * 1024]])

    def test_filter_passes(self, _mock_serv_is_up):
        _mock_serv_is_up.return_value = True
        filt_cls = self.class_map['CapacityFilter']()
        filter_properties = {'size': 100,
                             'request_spec': {'volume_id': fake.VOLUME_ID}}
        service = {'disabled': False}
        host = fakes.FakeBackendState('host1',
                                      {'total_capacity_gb': 500,
                                       'free_capacity_gb': 200,
                                       'updated_at': None,
                                       'service': service})
        self.assertTrue(filt_cls.backend_passes(host, filter_properties))

    def test_filter_passes_without_volume_id(self, _mock_serv_is_up):
        _mock_serv_is_up.return_value = True
        filter_cls = self.class_map['CapacityFilter']()
        filter_properties = {'size': 100}
        service = {'disabled': False}
        host = fakes.FakeBackendState('host1',
                                      {'total_capacity_gb': 500,
                                       'free_capacity_gb': 200,
                                       'updated_at': None,
                                       'service': service})
        self.assertTrue(filter_cls.backend_passes(host, filter_properties))

    def test_filter_current_backend_passes(self, _mock_serv_is_up):
        _mock_serv_is_up.return_value = True
        filt_cls = self.class_map['CapacityFilter']()
        filter_properties = {'size': 100, 'vol_exists_on': 'host1',
                             'request_spec': {'volume_id': fake.VOLUME_ID}}
        service = {'disabled': False}
        host = fakes.FakeBackendState('host1',
                                      {'total_capacity_gb': 100,
                                       'free_capacity_gb': 10,
                                       'updated_at': None,
                                       'service': service})
        self.assertTrue(filt_cls.backend_passes(host, filter_properties))

    def test_filter_fails(self, _mock_serv_is_up):
        _mock_serv_is_up.return_value = True
        filt_cls = self.class_map['CapacityFilter']()
        filter_properties = {'size': 100,
                             'request_spec': {'volume_id': fake.VOLUME_ID}}
        service = {'disabled': False}
        host = fakes.FakeBackendState('host1',
                                      {'total_capacity_gb': 200,
                                       'free_capacity_gb': 120,
                                       'reserved_percentage': 20,
                                       'updated_at': None,
                                       'service': service})
        self.assertFalse(filt_cls.backend_passes(host, filter_properties))

    def test_filter_fails_free_capacity_None(self, _mock_serv_is_up):
        _mock_serv_is_up.return_value = True
        filt_cls = self.class_map['CapacityFilter']()
        filter_properties = {'size': 100,
                             'request_spec': {'volume_id': fake.VOLUME_ID}}
        service = {'disabled': False}
        host = fakes.FakeBackendState('host1',
                                      {'free_capacity_gb': None,
                                       'updated_at': None,
                                       'service': service})
        self.assertFalse(filt_cls.backend_passes(host, filter_properties))

    def test_filter_with_size_0(self, _mock_serv_is_up):
        _mock_serv_is_up.return_value = True
        filt_cls = self.class_map['CapacityFilter']()
        filter_properties = {'size': 0,
                             'request_spec': {'volume_id': fake.VOLUME_ID}}
        service = {'disabled': False}
        host = fakes.FakeBackendState('host1',
                                      {'total_capacity_gb': 500,
                                       'free_capacity_gb': 200,
                                       'provisioned_capacity_gb': 1500,
                                       'max_over_subscription_ratio': 2.0,
                                       'reserved_percentage': 5,
                                       'thin_provisioning_support': True,
                                       'thick_provisioning_support': False,
                                       'updated_at': None,
                                       'service': service})
        self.assertTrue(filt_cls.backend_passes(host, filter_properties))

    def test_filter_passes_infinite(self, _mock_serv_is_up):
        _mock_serv_is_up.return_value = True
        filt_cls = self.class_map['CapacityFilter']()
        filter_properties = {'size': 100,
                             'request_spec': {'volume_id': fake.VOLUME_ID}}
        service = {'disabled': False}
        host = fakes.FakeBackendState('host1',
                                      {'free_capacity_gb': 'infinite',
                                       'updated_at': None,
                                       'service': service})
        self.assertTrue(filt_cls.backend_passes(host, filter_properties))

    def test_filter_extend_request(self, _mock_serv_is_up):
        _mock_serv_is_up.return_value = True
        filt_cls = self.class_map['CapacityFilter']()
        filter_properties = {'new_size': 100, 'size': 50,
                             'request_spec': {'volume_id': fake.VOLUME_ID}}
        service = {'disabled': False}
        host = fakes.FakeBackendState('host1',
                                      {'free_capacity_gb': 200,
                                       'updated_at': None,
                                       'total_capacity_gb': 500,
                                       'service': service})
        self.assertTrue(filt_cls.backend_passes(host, filter_properties))

    def test_filter_extend_request_negative(self, _mock_serv_is_up):
        _mock_serv_is_up.return_value = True
        filt_cls = self.class_map['CapacityFilter']()
        filter_properties = {'size': 50,
                             'request_spec': {'volume_id': fake.VOLUME_ID}}
        service = {'disabled': False}
        host = fakes.FakeBackendState('host1',
                                      {'free_capacity_gb': 49,
                                       'updated_at': None,
                                       'total_capacity_gb': 500,
                                       'service': service})
        self.assertFalse(filt_cls.backend_passes(host, filter_properties))

    def test_filter_passes_unknown(self, _mock_serv_is_up):
        _mock_serv_is_up.return_value = True
        filt_cls = self.class_map['CapacityFilter']()
        filter_properties = {'size': 100,
                             'request_spec': {'volume_id': fake.VOLUME_ID}}
        service = {'disabled': False}
        host = fakes.FakeBackendState('host1',
                                      {'free_capacity_gb': 'unknown',
                                       'updated_at': None,
                                       'service': service})
        self.assertTrue(filt_cls.backend_passes(host, filter_properties))

    def test_filter_passes_total_infinite(self, _mock_serv_is_up):
        _mock_serv_is_up.return_value = True
        filt_cls = self.class_map['CapacityFilter']()
        filter_properties = {'size': 100,
                             'request_spec': {'volume_id': fake.VOLUME_ID}}
        service = {'disabled': False}
        host = fakes.FakeBackendState('host1',
                                      {'free_capacity_gb': 'infinite',
                                       'total_capacity_gb': 'infinite',
                                       'reserved_percentage': 0,
                                       'updated_at': None,
                                       'service': service})
        self.assertTrue(filt_cls.backend_passes(host, filter_properties))

    def test_filter_passes_total_unknown(self, _mock_serv_is_up):
        _mock_serv_is_up.return_value = True
        filt_cls = self.class_map['CapacityFilter']()
        filter_properties = {'size': 100,
                             'request_spec': {'volume_id': fake.VOLUME_ID}}
        service = {'disabled': False}
        host = fakes.FakeBackendState('host1',
                                      {'free_capacity_gb': 'unknown',
                                       'total_capacity_gb': 'unknown',
                                       'reserved_percentage': 0,
                                       'updated_at': None,
                                       'service': service})
        self.assertTrue(filt_cls.backend_passes(host, filter_properties))

    def test_filter_fails_total_infinite(self, _mock_serv_is_up):
        _mock_serv_is_up.return_value = True
        filt_cls = self.class_map['CapacityFilter']()
        filter_properties = {'size': 100,
                             'request_spec': {'volume_id': fake.VOLUME_ID}}
        service = {'disabled': False}
        host = fakes.FakeBackendState('host1',
                                      {'total_capacity_gb': 'infinite',
                                       'reserved_percentage': 5,
                                       'updated_at': None,
                                       'service': service})
        self.assertFalse(filt_cls.backend_passes(host, filter_properties))

    def test_filter_fails_total_unknown(self, _mock_serv_is_up):
        _mock_serv_is_up.return_value = True
        filt_cls = self.class_map['CapacityFilter']()
        filter_properties = {'size': 100,
                             'request_spec': {'volume_id': fake.VOLUME_ID}}
        service = {'disabled': False}
        host = fakes.FakeBackendState('host1',
                                      {'total_capacity_gb': 'unknown',
                                       'reserved_percentage': 5,
                                       'updated_at': None,
                                       'service': service})
        self.assertFalse(filt_cls.backend_passes(host, filter_properties))

    def test_filter_fails_total_zero(self, _mock_serv_is_up):
        _mock_serv_is_up.return_value = True
        filt_cls = self.class_map['CapacityFilter']()
        filter_properties = {'size': 100,
                             'request_spec': {'volume_id': fake.VOLUME_ID}}
        service = {'disabled': False}
        host = fakes.FakeBackendState('host1',
                                      {'total_capacity_gb': 0,
                                       'reserved_percentage': 5,
                                       'updated_at': None,
                                       'service': service})
        self.assertFalse(filt_cls.backend_passes(host, filter_properties))

    def test_filter_thin_true_passes(self, _mock_serv_is_up):
        _mock_serv_is_up.return_value = True
        filt_cls = self.class_map['CapacityFilter']()
        filter_properties = {'size': 100,
                             'capabilities:thin_provisioning_support':
                                 '<is> True',
                             'capabilities:thick_provisioning_support':
                                 '<is> False',
                             'request_spec': {'volume_id': fake.VOLUME_ID}}
        service = {'disabled': False}
        host = fakes.FakeBackendState('host1',
                                      {'total_capacity_gb': 500,
                                       'free_capacity_gb': 200,
                                       'provisioned_capacity_gb': 500,
                                       'max_over_subscription_ratio': 2.0,
                                       'reserved_percentage': 5,
                                       'thin_provisioning_support': True,
                                       'thick_provisioning_support': False,
                                       'updated_at': None,
                                       'service': service})
        self.assertTrue(filt_cls.backend_passes(host, filter_properties))

    def test_filter_thin_true_passes2(self, _mock_serv_is_up):
        _mock_serv_is_up.return_value = True
        filt_cls = self.class_map['CapacityFilter']()
        filter_properties = {'size': 3000,
                             'capabilities:thin_provisioning_support':
                                 '<is> True',
                             'capabilities:thick_provisioning_support':
                                 '<is> False',
                             'request_spec': {'volume_id': fake.VOLUME_ID}}
        service = {'disabled': False}
        host = fakes.FakeBackendState('host1',
                                      {'total_capacity_gb': 500,
                                       'free_capacity_gb': 200,
                                       'provisioned_capacity_gb': 7000,
                                       'max_over_subscription_ratio': 20,
                                       'reserved_percentage': 5,
                                       'thin_provisioning_support': True,
                                       'thick_provisioning_support': False,
                                       'updated_at': None,
                                       'service': service})
        self.assertTrue(filt_cls.backend_passes(host, filter_properties))

    def test_filter_thin_false_passes(self, _mock_serv_is_up):
        _mock_serv_is_up.return_value = True
        filt_cls = self.class_map['CapacityFilter']()
        filter_properties = {'size': 100,
                             'capabilities:thin_provisioning_support':
                                 '<is> False',
                             'capabilities:thick_provisioning_support':
                                 '<is> True',
                             'request_spec': {'volume_id': fake.VOLUME_ID}}
        service = {'disabled': False}
        # If "thin_provisioning_support" is False,
        # "max_over_subscription_ratio" will be ignored.
        host = fakes.FakeBackendState('host1',
                                      {'total_capacity_gb': 500,
                                       'free_capacity_gb': 200,
                                       'provisioned_capacity_gb': 300,
                                       'max_over_subscription_ratio': 1.0,
                                       'reserved_percentage': 5,
                                       'thin_provisioning_support': False,
                                       'thick_provisioning_support': True,
                                       'updated_at': None,
                                       'service': service})
        self.assertTrue(filt_cls.backend_passes(host, filter_properties))

    def test_filter_over_subscription_less_than_1(self, _mock_serv_is_up):
        _mock_serv_is_up.return_value = True
        filt_cls = self.class_map['CapacityFilter']()
        filter_properties = {'size': 200,
                             'capabilities:thin_provisioning_support':
                                 '<is> True',
                             'capabilities:thick_provisioning_support':
                                 '<is> False',
                             'request_spec': {'volume_id': fake.VOLUME_ID}}
        service = {'disabled': False}
        host = fakes.FakeBackendState('host1',
                                      {'total_capacity_gb': 500,
                                       'free_capacity_gb': 100,
                                       'provisioned_capacity_gb': 400,
                                       'max_over_subscription_ratio': 0.8,
                                       'reserved_percentage': 0,
                                       'thin_provisioning_support': True,
                                       'thick_provisioning_support': False,
                                       'updated_at': None,
                                       'service': service})
        self.assertFalse(filt_cls.backend_passes(host, filter_properties))

    def test_filter_over_subscription_equal_to_1(self, _mock_serv_is_up):
        _mock_serv_is_up.return_value = True
        filt_cls = self.class_map['CapacityFilter']()
        filter_properties = {'size': 150,
                             'capabilities:thin_provisioning_support':
                                 '<is> True',
                             'capabilities:thick_provisioning_support':
                                 '<is> False',
                             'request_spec': {'volume_id': fake.VOLUME_ID}}
        service = {'disabled': False}
        host = fakes.FakeBackendState('host1',
                                      {'total_capacity_gb': 500,
                                       'free_capacity_gb': 200,
                                       'provisioned_capacity_gb': 400,
                                       'max_over_subscription_ratio': 1.0,
                                       'reserved_percentage': 0,
                                       'thin_provisioning_support': True,
                                       'thick_provisioning_support': False,
                                       'updated_at': None,
                                       'service': service})
        self.assertFalse(filt_cls.backend_passes(host, filter_properties))

    def test_filter_over_subscription_fails(self, _mock_serv_is_up):
        _mock_serv_is_up.return_value = True
        filt_cls = self.class_map['CapacityFilter']()
        filter_properties = {'size': 100,
                             'capabilities:thin_provisioning_support':
                                 '<is> True',
                             'capabilities:thick_provisioning_support':
                                 '<is> False',
                             'request_spec': {'volume_id': fake.VOLUME_ID}}
        service = {'disabled': False}
        host = fakes.FakeBackendState('host1',
                                      {'total_capacity_gb': 500,
                                       'free_capacity_gb': 200,
                                       'provisioned_capacity_gb': 700,
                                       'max_over_subscription_ratio': 1.5,
                                       'reserved_percentage': 5,
                                       'thin_provisioning_support': True,
                                       'thick_provisioning_support': False,
                                       'updated_at': None,
                                       'service': service})
        self.assertFalse(filt_cls.backend_passes(host, filter_properties))

    def test_filter_over_subscription_fails2(self, _mock_serv_is_up):
        _mock_serv_is_up.return_value = True
        filt_cls = self.class_map['CapacityFilter']()
        filter_properties = {'size': 2000,
                             'capabilities:thin_provisioning_support':
                                 '<is> True',
                             'capabilities:thick_provisioning_support':
                                 '<is> False',
                             'request_spec': {'volume_id': fake.VOLUME_ID}}
        service = {'disabled': False}
        host = fakes.FakeBackendState('host1',
                                      {'total_capacity_gb': 500,
                                       'free_capacity_gb': 30,
                                       'provisioned_capacity_gb': 9000,
                                       'max_over_subscription_ratio': 20,
                                       'reserved_percentage': 0,
                                       'thin_provisioning_support': True,
                                       'thick_provisioning_support': False,
                                       'updated_at': None,
                                       'service': service})
        self.assertFalse(filt_cls.backend_passes(host, filter_properties))

    def test_filter_reserved_thin_true_fails(self, _mock_serv_is_up):
        _mock_serv_is_up.return_value = True
        filt_cls = self.class_map['CapacityFilter']()
        filter_properties = {'size': 100,
                             'capabilities:thin_provisioning_support':
                                 '<is> True',
                             'capabilities:thick_provisioning_support':
                                 '<is> False',
                             'request_spec': {'volume_id': fake.VOLUME_ID}}
        service = {'disabled': False}
        host = fakes.FakeBackendState('host1',
                                      {'total_capacity_gb': 500,
                                       'free_capacity_gb': 100,
                                       'provisioned_capacity_gb': 1000,
                                       'max_over_subscription_ratio': 2.0,
                                       'reserved_percentage': 5,
                                       'thin_provisioning_support': True,
                                       'thick_provisioning_support': False,
                                       'updated_at': None,
                                       'service': service})
        self.assertFalse(filt_cls.backend_passes(host, filter_properties))

    def test_filter_reserved_thin_false_fails(self, _mock_serv_is_up):
        _mock_serv_is_up.return_value = True
        filt_cls = self.class_map['CapacityFilter']()
        filter_properties = {'size': 100,
                             'capabilities:thin_provisioning_support':
                                 '<is> False',
                             'capabilities:thick_provisioning_support':
                                 '<is> True',
                             'request_spec': {'volume_id': fake.VOLUME_ID}}
        service = {'disabled': False}
        # If "thin_provisioning_support" is False,
        # "max_over_subscription_ratio" will be ignored.
        host = fakes.FakeBackendState('host1',
                                      {'total_capacity_gb': 500,
                                       'free_capacity_gb': 100,
                                       'provisioned_capacity_gb': 400,
                                       'max_over_subscription_ratio': 1.0,
                                       'reserved_percentage': 5,
                                       'thin_provisioning_support': False,
                                       'thick_provisioning_support': True,
                                       'updated_at': None,
                                       'service': service})
        self.assertFalse(filt_cls.backend_passes(host, filter_properties))

    def test_filter_reserved_thin_thick_true_fails(self, _mock_serv_is_up):
        _mock_serv_is_up.return_value = True
        filt_cls = self.class_map['CapacityFilter']()
        filter_properties = {'size': 100,
                             'capabilities:thin_provisioning_support':
                                 '<is> True',
                             'capabilities:thick_provisioning_support':
                                 '<is> True',
                             'request_spec': {'volume_id': fake.VOLUME_ID}}
        service = {'disabled': False}
        host = fakes.FakeBackendState('host1',
                                      {'total_capacity_gb': 500,
                                       'free_capacity_gb': 0,
                                       'provisioned_capacity_gb': 800,
                                       'max_over_subscription_ratio': 2.0,
                                       'reserved_percentage': 5,
                                       'thin_provisioning_support': True,
                                       'thick_provisioning_support': True,
                                       'updated_at': None,
                                       'service': service})
        self.assertFalse(filt_cls.backend_passes(host, filter_properties))

    def test_filter_reserved_thin_thick_true_passes(self, _mock_serv_is_up):
        _mock_serv_is_up.return_value = True
        filt_cls = self.class_map['CapacityFilter']()
        filter_properties = {'size': 100,
                             'capabilities:thin_provisioning_support':
                                 '<is> True',
                             'capabilities:thick_provisioning_support':
                                 '<is> True',
                             'request_spec': {'volume_id': fake.VOLUME_ID}}
        service = {'disabled': False}
        host = fakes.FakeBackendState('host1',
                                      {'total_capacity_gb': 500,
                                       'free_capacity_gb': 125,
                                       'provisioned_capacity_gb': 400,
                                       'max_over_subscription_ratio': 2.0,
                                       'reserved_percentage': 5,
                                       'thin_provisioning_support': True,
                                       'thick_provisioning_support': True,
                                       'updated_at': None,
                                       'service': service})
        self.assertTrue(filt_cls.backend_passes(host, filter_properties))

    def test_filter_reserved_thin_true_passes(self, _mock_serv_is_up):
        _mock_serv_is_up.return_value = True
        filt_cls = self.class_map['CapacityFilter']()
        filter_properties = {'size': 100,
                             'capabilities:thin_provisioning_support':
                                 '<is> True',
                             'capabilities:thick_provisioning_support':
                                 '<is> False',
                             'request_spec': {'volume_id': fake.VOLUME_ID}}
        service = {'disabled': False}
        host = fakes.FakeBackendState('host1',
                                      {'total_capacity_gb': 500,
                                       'free_capacity_gb': 80,
                                       'provisioned_capacity_gb': 600,
                                       'max_over_subscription_ratio': 2.0,
                                       'reserved_percentage': 5,
                                       'thin_provisioning_support': True,
                                       'thick_provisioning_support': False,
                                       'updated_at': None,
                                       'service': service})
        self.assertTrue(filt_cls.backend_passes(host, filter_properties))

    def test_filter_reserved_thin_thick_true_fails2(self, _mock_serv_is_up):
        _mock_serv_is_up.return_value = True
        filt_cls = self.class_map['CapacityFilter']()
        filter_properties = {'size': 100,
                             'capabilities:thin_provisioning_support':
                                 '<is> True',
                             'capabilities:thick_provisioning_support':
                                 '<is> True',
                             'request_spec': {'volume_id': fake.VOLUME_ID}}
        service = {'disabled': False}
        host = fakes.FakeBackendState('host1',
                                      {'total_capacity_gb': 500,
                                       'free_capacity_gb': 99,
                                       'provisioned_capacity_gb': 1000,
                                       'max_over_subscription_ratio': 2.0,
                                       'reserved_percentage': 5,
                                       'thin_provisioning_support': True,
                                       'thick_provisioning_support': True,
                                       'updated_at': None,
                                       'service': service})
        self.assertFalse(filt_cls.backend_passes(host, filter_properties))

    def test_filter_reserved_thin_thick_true_passes2(self, _mock_serv_is_up):
        _mock_serv_is_up.return_value = True
        filt_cls = self.class_map['CapacityFilter']()
        filter_properties = {'size': 100,
                             'capabilities:thin_provisioning_support':
                                 '<is> True',
                             'capabilities:thick_provisioning_support':
                                 '<is> True',
                             'request_spec': {'volume_id': fake.VOLUME_ID}}
        service = {'disabled': False}
        host = fakes.FakeBackendState('host1',
                                      {'total_capacity_gb': 500,
                                       'free_capacity_gb': 100,
                                       'provisioned_capacity_gb': 400,
                                       'max_over_subscription_ratio': 2.0,
                                       'reserved_percentage': 0,
                                       'thin_provisioning_support': True,
                                       'thick_provisioning_support': True,
                                       'updated_at': None,
                                       'service': service})
        self.assertTrue(filt_cls.backend_passes(host, filter_properties))

    @ddt.data(
        {'volume_type': {'extra_specs': {'provisioning:type': 'thick'}}},
        {'volume_type': {'extra_specs': {'provisioning:type': 'thin'}}},
        {'volume_type': {'extra_specs': {}}},
        {'volume_type': {}},
        {'volume_type': None},
    )
    @ddt.unpack
    def test_filter_provisioning_type(self, _mock_serv_is_up, volume_type):
        _mock_serv_is_up.return_value = True
        filt_cls = self.class_map['CapacityFilter']()
        filter_properties = {'size': 100,
                             'volume_type': volume_type,
                             'request_spec': {'volume_id': fake.VOLUME_ID}}
        service = {'disabled': False}
        host = fakes.FakeBackendState('host1',
                                      {'total_capacity_gb': 500,
                                       'free_capacity_gb': 100,
                                       'provisioned_capacity_gb': 400,
                                       'max_over_subscription_ratio': 2.0,
                                       'reserved_percentage': 0,
                                       'thin_provisioning_support': True,
                                       'thick_provisioning_support': True,
                                       'updated_at': None,
                                       'service': service})
        self.assertTrue(filt_cls.backend_passes(host, filter_properties))


class AffinityFilterTestCase(BackendFiltersTestCase):
    @mock.patch('cinder.objects.service.Service.is_up',
                new_callable=mock.PropertyMock)
    def test_different_filter_passes(self, _mock_serv_is_up):
        _mock_serv_is_up.return_value = True
        filt_cls = self.class_map['DifferentBackendFilter']()
        service = {'disabled': False}
        host = fakes.FakeBackendState('host1:pool0',
                                      {'free_capacity_gb': '1000',
                                       'updated_at': None,
                                       'service': service})
        volume = utils.create_volume(self.context, host='host1:pool1')
        vol_id = volume.id

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': {'different_host': [vol_id], },
                             'request_spec': {'volume_id': fake.VOLUME_ID}}

        self.assertTrue(filt_cls.backend_passes(host, filter_properties))

    @mock.patch('cinder.objects.service.Service.is_up',
                new_callable=mock.PropertyMock)
    def test_different_filter_legacy_volume_hint_passes(
            self, _mock_serv_is_up):
        _mock_serv_is_up.return_value = True
        filt_cls = self.class_map['DifferentBackendFilter']()
        service = {'disabled': False}
        host = fakes.FakeBackendState('host1:pool0',
                                      {'free_capacity_gb': '1000',
                                       'updated_at': None,
                                       'service': service})
        volume = utils.create_volume(self.context, host='host1')
        vol_id = volume.id

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': {'different_host': [vol_id], },
                             'request_spec': {'volume_id': fake.VOLUME_ID}}

        self.assertTrue(filt_cls.backend_passes(host, filter_properties))

    def test_different_filter_non_list_fails(self):
        filt_cls = self.class_map['DifferentBackendFilter']()
        host = fakes.FakeBackendState('host2', {})
        volume = utils.create_volume(self.context, host='host2')
        vol_id = volume.id

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': {
            'different_host': vol_id}}

        self.assertFalse(filt_cls.backend_passes(host, filter_properties))

    def test_different_filter_fails(self):
        filt_cls = self.class_map['DifferentBackendFilter']()
        host = fakes.FakeBackendState('host1', {})
        volume = utils.create_volume(self.context, host='host1')
        vol_id = volume.id

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': {'different_host': [vol_id], },
                             'request_spec': {'volume_id': fake.VOLUME_ID}}

        self.assertFalse(filt_cls.backend_passes(host, filter_properties))

    def test_different_filter_handles_none(self):
        filt_cls = self.class_map['DifferentBackendFilter']()
        host = fakes.FakeBackendState('host1', {})

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': None,
                             'request_spec': {'volume_id': fake.VOLUME_ID}}

        self.assertTrue(filt_cls.backend_passes(host, filter_properties))

    def test_different_filter_handles_deleted_instance(self):
        filt_cls = self.class_map['DifferentBackendFilter']()
        host = fakes.FakeBackendState('host1', {})
        volume = utils.create_volume(self.context, host='host1')
        vol_id = volume.id
        db.volume_destroy(utils.get_test_admin_context(), vol_id)

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': {
            'different_host': [vol_id], }}

        self.assertTrue(filt_cls.backend_passes(host, filter_properties))

    def test_different_filter_fail_nonuuid_hint(self):
        filt_cls = self.class_map['DifferentBackendFilter']()
        host = fakes.FakeBackendState('host1', {})

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': {
            'different_host': "NOT-a-valid-UUID", }}

        self.assertFalse(filt_cls.backend_passes(host, filter_properties))

    def test_different_filter_handles_multiple_uuids(self):
        filt_cls = self.class_map['DifferentBackendFilter']()
        host = fakes.FakeBackendState('host1#pool0', {})
        volume1 = utils.create_volume(self.context, host='host1:pool1')
        vol_id1 = volume1.id
        volume2 = utils.create_volume(self.context, host='host1:pool3')
        vol_id2 = volume2.id

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': {
            'different_host': [vol_id1, vol_id2], }}

        self.assertTrue(filt_cls.backend_passes(host, filter_properties))

    def test_different_filter_handles_invalid_uuids(self):
        filt_cls = self.class_map['DifferentBackendFilter']()
        host = fakes.FakeBackendState('host1', {})
        volume = utils.create_volume(self.context, host='host2')
        vol_id = volume.id

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': {
            'different_host': [vol_id, "NOT-a-valid-UUID"], }}

        self.assertFalse(filt_cls.backend_passes(host, filter_properties))

    def test_same_filter_no_list_passes(self):
        filt_cls = self.class_map['SameBackendFilter']()
        host = fakes.FakeBackendState('host1', {})
        volume = utils.create_volume(self.context, host='host1')
        vol_id = volume.id

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': {
            'same_host': vol_id}}

        self.assertTrue(filt_cls.backend_passes(host, filter_properties))

    def test_same_filter_passes(self):
        filt_cls = self.class_map['SameBackendFilter']()
        host = fakes.FakeBackendState('host1#pool0', {})
        volume = utils.create_volume(self.context, host='host1#pool0')
        vol_id = volume.id

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': {
            'same_host': [vol_id], }}

        self.assertTrue(filt_cls.backend_passes(host, filter_properties))

    def test_same_filter_legacy_vol_fails(self):
        filt_cls = self.class_map['SameBackendFilter']()
        host = fakes.FakeBackendState('host1#pool0', {})
        volume = utils.create_volume(self.context, host='host1')
        vol_id = volume.id

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': {
            'same_host': [vol_id], }}

        self.assertFalse(filt_cls.backend_passes(host, filter_properties))

    def test_same_filter_fails(self):
        filt_cls = self.class_map['SameBackendFilter']()
        host = fakes.FakeBackendState('host1#pool0', {})
        volume = utils.create_volume(self.context, host='host1#pool1')
        vol_id = volume.id

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': {
            'same_host': [vol_id], }}

        self.assertFalse(filt_cls.backend_passes(host, filter_properties))

    def test_same_filter_vol_list_pass(self):
        filt_cls = self.class_map['SameBackendFilter']()
        host = fakes.FakeBackendState('host1', {})
        volume1 = utils.create_volume(self.context, host='host1')
        vol_id1 = volume1.id
        volume2 = utils.create_volume(self.context, host='host2')
        vol_id2 = volume2.id

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': {
            'same_host': [vol_id1, vol_id2], }}

        self.assertTrue(filt_cls.backend_passes(host, filter_properties))

    def test_same_filter_handles_none(self):
        filt_cls = self.class_map['SameBackendFilter']()
        host = fakes.FakeBackendState('host1', {})

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': None}

        self.assertTrue(filt_cls.backend_passes(host, filter_properties))

    def test_same_filter_handles_deleted_instance(self):
        filt_cls = self.class_map['SameBackendFilter']()
        host = fakes.FakeBackendState('host1', {})
        volume = utils.create_volume(self.context, host='host2')
        vol_id = volume.id
        db.volume_destroy(utils.get_test_admin_context(), vol_id)

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': {
            'same_host': [vol_id], }}

        self.assertFalse(filt_cls.backend_passes(host, filter_properties))

    def test_same_filter_fail_nonuuid_hint(self):
        filt_cls = self.class_map['SameBackendFilter']()
        host = fakes.FakeBackendState('host1', {})

        filter_properties = {'context': self.context.elevated(),
                             'scheduler_hints': {
            'same_host': "NOT-a-valid-UUID", }}

        self.assertFalse(filt_cls.backend_passes(host, filter_properties))


class DriverFilterTestCase(BackendFiltersTestCase):
    def test_passing_function(self):
        filt_cls = self.class_map['DriverFilter']()
        host1 = fakes.FakeBackendState(
            'host1', {
                'capabilities': {
                    'filter_function': '1 == 1',
                }
            })

        filter_properties = {'volume_type': {}}

        self.assertTrue(filt_cls.backend_passes(host1, filter_properties))

    def test_failing_function(self):
        filt_cls = self.class_map['DriverFilter']()
        host1 = fakes.FakeBackendState(
            'host1', {
                'capabilities': {
                    'filter_function': '1 == 2',
                }
            })

        filter_properties = {'volume_type': {}}

        self.assertFalse(filt_cls.backend_passes(host1, filter_properties))

    def test_no_filter_function(self):
        filt_cls = self.class_map['DriverFilter']()
        host1 = fakes.FakeBackendState(
            'host1', {
                'capabilities': {
                    'filter_function': None,
                }
            })

        filter_properties = {'volume_type': {}}

        self.assertTrue(filt_cls.backend_passes(host1, filter_properties))

    def test_not_implemented(self):
        filt_cls = self.class_map['DriverFilter']()
        host1 = fakes.FakeBackendState(
            'host1', {
                'capabilities': {}
            })

        filter_properties = {'volume_type': {}}

        self.assertTrue(filt_cls.backend_passes(host1, filter_properties))

    def test_no_volume_extra_specs(self):
        filt_cls = self.class_map['DriverFilter']()
        host1 = fakes.FakeBackendState(
            'host1', {
                'capabilities': {
                    'filter_function': '1 == 1',
                }
            })

        filter_properties = {'volume_type': {}}

        self.assertTrue(filt_cls.backend_passes(host1, filter_properties))

    def test_function_extra_spec_replacement(self):
        filt_cls = self.class_map['DriverFilter']()
        host1 = fakes.FakeBackendState(
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

        self.assertTrue(filt_cls.backend_passes(host1, filter_properties))

    def test_function_stats_replacement(self):
        filt_cls = self.class_map['DriverFilter']()
        host1 = fakes.FakeBackendState(
            'host1', {
                'total_capacity_gb': 100,
                'capabilities': {
                    'filter_function': 'stats.total_capacity_gb < 200',
                }
            })

        filter_properties = {'volume_type': {}}

        self.assertTrue(filt_cls.backend_passes(host1, filter_properties))

    def test_function_volume_replacement(self):
        filt_cls = self.class_map['DriverFilter']()
        host1 = fakes.FakeBackendState(
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

        self.assertTrue(filt_cls.backend_passes(host1, filter_properties))

    def test_function_qos_spec_replacement(self):
        filt_cls = self.class_map['DriverFilter']()
        host1 = fakes.FakeBackendState(
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

        self.assertTrue(filt_cls.backend_passes(host1, filter_properties))

    def test_function_exception_caught(self):
        filt_cls = self.class_map['DriverFilter']()
        host1 = fakes.FakeBackendState(
            'host1', {
                'capabilities': {
                    'filter_function': '1 / 0 == 0',
                }
            })

        filter_properties = {}

        self.assertFalse(filt_cls.backend_passes(host1, filter_properties))

    def test_function_empty_qos(self):
        filt_cls = self.class_map['DriverFilter']()
        host1 = fakes.FakeBackendState(
            'host1', {
                'capabilities': {
                    'filter_function': 'qos.maxiops == 1',
                }
            })

        filter_properties = {
            'qos_specs': None
        }

        self.assertFalse(filt_cls.backend_passes(host1, filter_properties))

    def test_capabilities(self):
        filt_cls = self.class_map['DriverFilter']()
        host1 = fakes.FakeBackendState(
            'host1', {
                'capabilities': {
                    'foo': 10,
                    'filter_function': 'capabilities.foo == 10',
                },
            })

        filter_properties = {}

        self.assertTrue(filt_cls.backend_passes(host1, filter_properties))

    def test_wrong_capabilities(self):
        filt_cls = self.class_map['DriverFilter']()
        host1 = fakes.FakeBackendState(
            'host1', {
                'capabilities': {
                    'bar': 10,
                    'filter_function': 'capabilities.foo == 10',
                },
            })

        filter_properties = {}

        self.assertFalse(filt_cls.backend_passes(host1, filter_properties))


class InstanceLocalityFilterTestCase(BackendFiltersTestCase):
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
            fakes.FakeNovaClient().list_extensions.show_all())
        filt_cls = self.class_map['InstanceLocalityFilter']()
        host = fakes.FakeBackendState('host1', {})
        uuid = nova.novaclient().servers.create('host1')

        filter_properties = {'context': self.context,
                             'scheduler_hints': {'local_to_instance': uuid},
                             'request_spec': {'volume_id': fake.VOLUME_ID}}
        self.assertTrue(filt_cls.backend_passes(host, filter_properties))

    @mock.patch('novaclient.client.discover_extensions')
    @mock.patch('cinder.compute.nova.novaclient')
    def test_different_host(self, _mock_novaclient, fake_extensions):
        _mock_novaclient.return_value = fakes.FakeNovaClient()
        fake_extensions.return_value = (
            fakes.FakeNovaClient().list_extensions.show_all())
        filt_cls = self.class_map['InstanceLocalityFilter']()
        host = fakes.FakeBackendState('host1', {})
        uuid = nova.novaclient().servers.create('host2')

        filter_properties = {'context': self.context,
                             'scheduler_hints': {'local_to_instance': uuid},
                             'request_spec': {'volume_id': fake.VOLUME_ID}}
        self.assertFalse(filt_cls.backend_passes(host, filter_properties))

    def test_handles_none(self):
        filt_cls = self.class_map['InstanceLocalityFilter']()
        host = fakes.FakeBackendState('host1', {})

        filter_properties = {'context': self.context,
                             'scheduler_hints': None,
                             'request_spec': {'volume_id': fake.VOLUME_ID}}
        self.assertTrue(filt_cls.backend_passes(host, filter_properties))

    def test_invalid_uuid(self):
        filt_cls = self.class_map['InstanceLocalityFilter']()
        host = fakes.FakeBackendState('host1', {})

        filter_properties = {'context': self.context,
                             'scheduler_hints':
                             {'local_to_instance': 'e29b11d4-not-valid-a716'},
                             'request_spec': {'volume_id': fake.VOLUME_ID}}
        self.assertRaises(exception.InvalidUUID,
                          filt_cls.backend_passes, host, filter_properties)

    @mock.patch('cinder.compute.nova.novaclient')
    def test_nova_no_extended_server_attributes(self, _mock_novaclient):
        _mock_novaclient.return_value = fakes.FakeNovaClient(
            ext_srv_attr=False)
        filt_cls = self.class_map['InstanceLocalityFilter']()
        host = fakes.FakeBackendState('host1', {})
        uuid = nova.novaclient().servers.create('host1')

        filter_properties = {'context': self.context,
                             'scheduler_hints': {'local_to_instance': uuid},
                             'request_spec': {'volume_id': fake.VOLUME_ID}}
        self.assertRaises(exception.CinderException,
                          filt_cls.backend_passes, host, filter_properties)

    @mock.patch('cinder.compute.nova.novaclient')
    def test_nova_down_does_not_alter_other_filters(self, _mock_novaclient):
        # Simulate Nova API is not available
        _mock_novaclient.side_effect = Exception

        filt_cls = self.class_map['InstanceLocalityFilter']()
        host = fakes.FakeBackendState('host1', {})

        filter_properties = {'context': self.context, 'size': 100,
                             'request_spec': {'volume_id': fake.VOLUME_ID}}
        self.assertTrue(filt_cls.backend_passes(host, filter_properties))

    @mock.patch('cinder.compute.nova.novaclient')
    def test_nova_timeout(self, mock_novaclient):
        # Simulate a HTTP timeout
        mock_show_all = mock_novaclient.return_value.list_extensions.show_all
        mock_show_all.side_effect = request_exceptions.Timeout

        filt_cls = self.class_map['InstanceLocalityFilter']()
        host = fakes.FakeBackendState('host1', {})

        filter_properties = \
            {'context': self.context, 'scheduler_hints':
                {'local_to_instance': 'e29b11d4-15ef-34a9-a716-598a6f0b5467'},
             'request_spec': {'volume_id': fake.VOLUME_ID}}
        self.assertRaises(exception.APITimeout,
                          filt_cls.backend_passes, host, filter_properties)


class TestFilter(filters.BaseBackendFilter):
    pass


class TestBogusFilter(object):
    """Class that doesn't inherit from BaseBackendFilter."""
    pass


@ddt.ddt
class ExtraSpecsOpsTestCase(test.TestCase):
    def _do_extra_specs_ops_test(self, value, req, matches):
        assertion = self.assertTrue if matches else self.assertFalse
        assertion(extra_specs_ops.match(value, req))

    def test_extra_specs_fails_with_bogus_ops(self):
        self._do_extra_specs_ops_test(
            value='4',
            req='> 2',
            matches=False)

    @ddt.data({'value': '1', 'req': '1', 'matches': True},
              {'value': '', 'req': '1', 'matches': False},
              {'value': '3', 'req': '1', 'matches': False},
              {'value': '222', 'req': '2', 'matches': False})
    @ddt.unpack
    def test_extra_specs_matches_simple(self, value, req, matches):
        self._do_extra_specs_ops_test(
            value=value,
            req=req,
            matches=matches)

    @ddt.data({'value': '123', 'req': '= 123', 'matches': True},
              {'value': '124', 'req': '= 123', 'matches': True},
              {'value': '34', 'req': '= 234', 'matches': False},
              {'value': '34', 'req': '=', 'matches': False})
    @ddt.unpack
    def test_extra_specs_matches_with_op_eq(self, value, req, matches):
        self._do_extra_specs_ops_test(
            value=value,
            req=req,
            matches=matches)

    @ddt.data({'value': '2', 'req': '<= 10', 'matches': True},
              {'value': '3', 'req': '<= 2', 'matches': False},
              {'value': '3', 'req': '>= 1', 'matches': True},
              {'value': '2', 'req': '>= 3', 'matches': False})
    @ddt.unpack
    def test_extra_specs_matches_with_op_not_eq(self, value, req, matches):
        self._do_extra_specs_ops_test(
            value=value,
            req=req,
            matches=matches)

    @ddt.data({'value': '123', 'req': 's== 123', 'matches': True},
              {'value': '1234', 'req': 's== 123', 'matches': False},
              {'value': '1234', 'req': 's!= 123', 'matches': True},
              {'value': '123', 'req': 's!= 123', 'matches': False})
    @ddt.unpack
    def test_extra_specs_matches_with_op_seq(self, value, req, matches):
        self._do_extra_specs_ops_test(
            value=value,
            req=req,
            matches=matches)

    @ddt.data({'value': '1000', 'req': 's>= 234', 'matches': False},
              {'value': '1234', 'req': 's<= 1000', 'matches': False},
              {'value': '2', 'req': 's< 12', 'matches': False},
              {'value': '12', 'req': 's> 2', 'matches': False})
    @ddt.unpack
    def test_extra_specs_fails_with_op_not_seq(self, value, req, matches):
        self._do_extra_specs_ops_test(
            value=value,
            req=req,
            matches=matches)

    @ddt.data({'value': '12311321', 'req': '<in> 11', 'matches': True},
              {'value': '12311321', 'req': '<in> 12311321', 'matches': True},
              {'value': '12311321', 'req':
                  '<in> 12311321 <in>', 'matches': True},
              {'value': '12310321', 'req': '<in> 11', 'matches': False},
              {'value': '12310321', 'req': '<in> 11 <in>', 'matches': False})
    @ddt.unpack
    def test_extra_specs_matches_with_op_in(self, value, req, matches):
        self._do_extra_specs_ops_test(
            value=value,
            req=req,
            matches=matches)

    @ddt.data({'value': True, 'req': '<is> True', 'matches': True},
              {'value': False, 'req': '<is> False', 'matches': True},
              {'value': False, 'req': '<is> Nonsense', 'matches': True},
              {'value': True, 'req': '<is> False', 'matches': False},
              {'value': False, 'req': '<is> True', 'matches': False})
    @ddt.unpack
    def test_extra_specs_matches_with_op_is(self, value, req, matches):
        self._do_extra_specs_ops_test(
            value=value,
            req=req,
            matches=matches)

    @ddt.data({'value': '12', 'req': '<or> 11 <or> 12', 'matches': True},
              {'value': '12', 'req': '<or> 11 <or> 12 <or>', 'matches': True},
              {'value': '13', 'req': '<or> 11 <or> 12', 'matches': False},
              {'value': '13', 'req': '<or> 11 <or> 12 <or>', 'matches': False})
    @ddt.unpack
    def test_extra_specs_matches_with_op_or(self, value, req, matches):
        self._do_extra_specs_ops_test(
            value=value,
            req=req,
            matches=matches)

    @ddt.data({'value': None, 'req': None, 'matches': True},
              {'value': 'foo', 'req': None, 'matches': False})
    @ddt.unpack
    def test_extra_specs_matches_none_req(self, value, req, matches):
        self._do_extra_specs_ops_test(
            value=value,
            req=req,
            matches=matches)


@ddt.ddt
class BasicFiltersTestCase(BackendFiltersTestCase):
    """Test case for host filters."""

    def setUp(self):
        super(BasicFiltersTestCase, self).setUp()
        self.json_query = jsonutils.dumps(
            ['and', ['>=', '$free_ram_mb', 1024],
             ['>=', '$free_disk_mb', 200 * 1024]])

    def test_all_filters(self):
        # Double check at least a couple of known filters exist
        self.assertIn('JsonFilter', self.class_map)
        self.assertIn('CapabilitiesFilter', self.class_map)
        self.assertIn('AvailabilityZoneFilter', self.class_map)
        self.assertIn('IgnoreAttemptedHostsFilter', self.class_map)

    def _do_test_type_filter_extra_specs(self, ecaps, especs, passes):
        filt_cls = self.class_map['CapabilitiesFilter']()
        capabilities = {'enabled': True}
        capabilities.update(ecaps)
        service = {'disabled': False}
        filter_properties = {'resource_type': {'name': 'fake_type',
                                               'extra_specs': especs},
                             'request_spec': {'volume_id': fake.VOLUME_ID}}
        host = fakes.FakeBackendState('host1',
                                      {'free_capacity_gb': 1024,
                                       'capabilities': capabilities,
                                       'service': service})
        assertion = self.assertTrue if passes else self.assertFalse
        assertion(filt_cls.backend_passes(host, filter_properties))

    def test_capability_filter_passes_extra_specs_simple(self):
        self._do_test_type_filter_extra_specs(
            ecaps={'opt1': '1', 'opt2': '2'},
            especs={'opt1': '1', 'opt2': '2'},
            passes=True)

    def test_capability_filter_fails_extra_specs_simple(self):
        self._do_test_type_filter_extra_specs(
            ecaps={'opt1': '1', 'opt2': '2'},
            especs={'opt1': '1', 'opt2': '222'},
            passes=False)

    def test_capability_filter_passes_extra_specs_complex(self):
        self._do_test_type_filter_extra_specs(
            ecaps={'opt1': 10, 'opt2': 5},
            especs={'opt1': '>= 2', 'opt2': '<= 8'},
            passes=True)

    def test_capability_filter_fails_extra_specs_complex(self):
        self._do_test_type_filter_extra_specs(
            ecaps={'opt1': 10, 'opt2': 5},
            especs={'opt1': '>= 2', 'opt2': '>= 8'},
            passes=False)

    def test_capability_filter_passes_extra_specs_list_simple(self):
        self._do_test_type_filter_extra_specs(
            ecaps={'opt1': ['1', '2'], 'opt2': '2'},
            especs={'opt1': '1', 'opt2': '2'},
            passes=True)

    @ddt.data('<is> True', '<is> False')
    def test_capability_filter_passes_extra_specs_list_complex(self, opt1):
        self._do_test_type_filter_extra_specs(
            ecaps={'opt1': [True, False], 'opt2': ['1', '2']},
            especs={'opt1': opt1, 'opt2': '<= 8'},
            passes=True)

    def test_capability_filter_fails_extra_specs_list_simple(self):
        self._do_test_type_filter_extra_specs(
            ecaps={'opt1': ['1', '2'], 'opt2': ['2']},
            especs={'opt1': '3', 'opt2': '2'},
            passes=False)

    def test_capability_filter_fails_extra_specs_list_complex(self):
        self._do_test_type_filter_extra_specs(
            ecaps={'opt1': [True, False], 'opt2': ['1', '2']},
            especs={'opt1': 'fake', 'opt2': '<= 8'},
            passes=False)

    def test_capability_filter_passes_scope_extra_specs(self):
        self._do_test_type_filter_extra_specs(
            ecaps={'scope_lv1': {'opt1': 10}},
            especs={'capabilities:scope_lv1:opt1': '>= 2'},
            passes=True)

    def test_capability_filter_passes_fakescope_extra_specs(self):
        self._do_test_type_filter_extra_specs(
            ecaps={'scope_lv1': {'opt1': 10}, 'opt2': 5},
            especs={'scope_lv1:opt1': '= 2', 'opt2': '>= 3'},
            passes=True)

    def test_capability_filter_fails_scope_extra_specs(self):
        self._do_test_type_filter_extra_specs(
            ecaps={'scope_lv1': {'opt1': 10}},
            especs={'capabilities:scope_lv1:opt1': '<= 2'},
            passes=False)

    def test_capability_filter_passes_multi_level_scope_extra_specs(self):
        self._do_test_type_filter_extra_specs(
            ecaps={'scope_lv0': {'scope_lv1':
                                 {'scope_lv2': {'opt1': 10}}}},
            especs={'capabilities:scope_lv0:scope_lv1:scope_lv2:opt1': '>= 2'},
            passes=True)

    def test_capability_filter_fails_unenough_level_scope_extra_specs(self):
        self._do_test_type_filter_extra_specs(
            ecaps={'scope_lv0': {'scope_lv1': None}},
            especs={'capabilities:scope_lv0:scope_lv1:scope_lv2:opt1': '>= 2'},
            passes=False)

    def test_capability_filter_fails_wrong_scope_extra_specs(self):
        self._do_test_type_filter_extra_specs(
            ecaps={'scope_lv0': {'opt1': 10}},
            especs={'capabilities:scope_lv1:opt1': '>= 2'},
            passes=False)

    def test_capability_filter_passes_none_extra_specs(self):
        self._do_test_type_filter_extra_specs(
            ecaps={'scope_lv0': {'opt1': None}},
            especs={'capabilities:scope_lv0:opt1': None},
            passes=True)

    def test_capability_filter_fails_none_extra_specs(self):
        self._do_test_type_filter_extra_specs(
            ecaps={'scope_lv0': {'opt1': 10}},
            especs={'capabilities:scope_lv0:opt1': None},
            passes=False)

    def test_capability_filter_fails_none_caps(self):
        self._do_test_type_filter_extra_specs(
            ecaps={'scope_lv0': {'opt1': None}},
            especs={'capabilities:scope_lv0:opt1': 'foo'},
            passes=False)

    def test_capability_filter_passes_multi_level_scope_extra_specs_list(self):
        self._do_test_type_filter_extra_specs(
            ecaps={
                'scope_lv0': {
                    'scope_lv1': {
                        'scope_lv2': {
                            'opt1': [True, False],
                        },
                    },
                },
            },
            especs={
                'capabilities:scope_lv0:scope_lv1:scope_lv2:opt1': '<is> True',
            },
            passes=True)

    def test_capability_filter_fails_multi_level_scope_extra_specs_list(self):
        self._do_test_type_filter_extra_specs(
            ecaps={
                'scope_lv0': {
                    'scope_lv1': {
                        'scope_lv2': {
                            'opt1': [True, False],
                            'opt2': ['1', '2'],
                        },
                    },
                },
            },
            especs={
                'capabilities:scope_lv0:scope_lv1:scope_lv2:opt1': '<is> True',
                'capabilities:scope_lv0:scope_lv1:scope_lv2:opt2': '3',
            },
            passes=False)

    def test_capability_filter_fails_wrong_scope_extra_specs_list(self):
        self._do_test_type_filter_extra_specs(
            ecaps={'scope_lv0': {'opt1': [True, False]}},
            especs={'capabilities:scope_lv1:opt1': '<is> True'},
            passes=False)

    def test_json_filter_passes(self):
        filt_cls = self.class_map['JsonFilter']()
        filter_properties = {'resource_type': {'memory_mb': 1024,
                                               'root_gb': 200,
                                               'ephemeral_gb': 0},
                             'scheduler_hints': {'query': self.json_query},
                             'request_spec': {'volume_id': fake.VOLUME_ID}}
        capabilities = {'enabled': True}
        host = fakes.FakeBackendState('host1',
                                      {'free_ram_mb': 1024,
                                       'free_disk_mb': 200 * 1024,
                                       'capabilities': capabilities})
        self.assertTrue(filt_cls.backend_passes(host, filter_properties))

    def test_json_filter_passes_with_no_query(self):
        filt_cls = self.class_map['JsonFilter']()
        filter_properties = {'resource_type': {'memory_mb': 1024,
                                               'root_gb': 200,
                                               'ephemeral_gb': 0},
                             'request_spec': {'volume_id': fake.VOLUME_ID}}
        capabilities = {'enabled': True}
        host = fakes.FakeBackendState('host1',
                                      {'free_ram_mb': 0,
                                       'free_disk_mb': 0,
                                       'capabilities': capabilities})
        self.assertTrue(filt_cls.backend_passes(host, filter_properties))

    def test_json_filter_fails_on_memory(self):
        filt_cls = self.class_map['JsonFilter']()
        filter_properties = {'resource_type': {'memory_mb': 1024,
                                               'root_gb': 200,
                                               'ephemeral_gb': 0},
                             'scheduler_hints': {'query': self.json_query},
                             'request_spec': {'volume_id': fake.VOLUME_ID}}
        capabilities = {'enabled': True}
        host = fakes.FakeBackendState('host1',
                                      {'free_ram_mb': 1023,
                                       'free_disk_mb': 200 * 1024,
                                       'capabilities': capabilities})
        self.assertFalse(filt_cls.backend_passes(host, filter_properties))

    def test_json_filter_fails_on_disk(self):
        filt_cls = self.class_map['JsonFilter']()
        filter_properties = {'resource_type': {'memory_mb': 1024,
                                               'root_gb': 200,
                                               'ephemeral_gb': 0},
                             'scheduler_hints': {'query': self.json_query},
                             'request_spec': {'volume_id': fake.VOLUME_ID}}
        capabilities = {'enabled': True}
        host = fakes.FakeBackendState('host1',
                                      {'free_ram_mb': 1024,
                                       'free_disk_mb': (200 * 1024) - 1,
                                       'capabilities': capabilities})
        self.assertFalse(filt_cls.backend_passes(host, filter_properties))

    def test_json_filter_fails_on_caps_disabled(self):
        filt_cls = self.class_map['JsonFilter']()
        json_query = jsonutils.dumps(
            ['and', ['>=', '$free_ram_mb', 1024],
             ['>=', '$free_disk_mb', 200 * 1024],
             '$capabilities.enabled'])
        filter_properties = {'resource_type': {'memory_mb': 1024,
                                               'root_gb': 200,
                                               'ephemeral_gb': 0},
                             'scheduler_hints': {'query': json_query},
                             'request_spec': {'volume_id': fake.VOLUME_ID}}
        capabilities = {'enabled': False}
        host = fakes.FakeBackendState('host1',
                                      {'free_ram_mb': 1024,
                                       'free_disk_mb': 200 * 1024,
                                       'capabilities': capabilities})
        self.assertFalse(filt_cls.backend_passes(host, filter_properties))

    def test_json_filter_fails_on_service_disabled(self):
        filt_cls = self.class_map['JsonFilter']()
        json_query = jsonutils.dumps(
            ['and', ['>=', '$free_ram_mb', 1024],
             ['>=', '$free_disk_mb', 200 * 1024],
             ['not', '$service.disabled']])
        filter_properties = {'resource_type': {'memory_mb': 1024,
                                               'local_gb': 200},
                             'scheduler_hints': {'query': json_query},
                             'request_spec': {'volume_id': fake.VOLUME_ID}}
        capabilities = {'enabled': True}
        host = fakes.FakeBackendState('host1',
                                      {'free_ram_mb': 1024,
                                       'free_disk_mb': 200 * 1024,
                                       'capabilities': capabilities})
        self.assertFalse(filt_cls.backend_passes(host, filter_properties))

    def test_json_filter_happy_day(self):
        """Test json filter more thoroughly."""
        filt_cls = self.class_map['JsonFilter']()
        raw = ['and',
               '$capabilities.enabled',
               ['=', '$capabilities.opt1', 'match'],
               ['or',
                ['and',
                 ['<', '$free_ram_mb', 30],
                 ['<', '$free_disk_mb', 300]],
                ['and',
                 ['>', '$free_ram_mb', 30],
                 ['>', '$free_disk_mb', 300]]]]
        filter_properties = {
            'scheduler_hints': {
                'query': jsonutils.dumps(raw),
            },
            'request_spec': {'volume_id': fake.VOLUME_ID}
        }

        # Passes
        capabilities = {'enabled': True, 'opt1': 'match'}
        service = {'disabled': False}
        host = fakes.FakeBackendState('host1',
                                      {'free_ram_mb': 10,
                                       'free_disk_mb': 200,
                                       'capabilities': capabilities,
                                       'service': service})
        self.assertTrue(filt_cls.backend_passes(host, filter_properties))

        # Passes
        capabilities = {'enabled': True, 'opt1': 'match'}
        service = {'disabled': False}
        host = fakes.FakeBackendState('host1',
                                      {'free_ram_mb': 40,
                                       'free_disk_mb': 400,
                                       'capabilities': capabilities,
                                       'service': service})
        self.assertTrue(filt_cls.backend_passes(host, filter_properties))

        # Fails due to capabilities being disabled
        capabilities = {'enabled': False, 'opt1': 'match'}
        service = {'disabled': False}
        host = fakes.FakeBackendState('host1',
                                      {'free_ram_mb': 40,
                                       'free_disk_mb': 400,
                                       'capabilities': capabilities,
                                       'service': service})
        self.assertFalse(filt_cls.backend_passes(host, filter_properties))

        # Fails due to being exact memory/disk we don't want
        capabilities = {'enabled': True, 'opt1': 'match'}
        service = {'disabled': False}
        host = fakes.FakeBackendState('host1',
                                      {'free_ram_mb': 30,
                                       'free_disk_mb': 300,
                                       'capabilities': capabilities,
                                       'service': service})
        self.assertFalse(filt_cls.backend_passes(host, filter_properties))

        # Fails due to memory lower but disk higher
        capabilities = {'enabled': True, 'opt1': 'match'}
        service = {'disabled': False}
        host = fakes.FakeBackendState('host1',
                                      {'free_ram_mb': 20,
                                       'free_disk_mb': 400,
                                       'capabilities': capabilities,
                                       'service': service})
        self.assertFalse(filt_cls.backend_passes(host, filter_properties))

        # Fails due to capabilities 'opt1' not equal
        capabilities = {'enabled': True, 'opt1': 'no-match'}
        service = {'enabled': True}
        host = fakes.FakeBackendState('host1',
                                      {'free_ram_mb': 20,
                                       'free_disk_mb': 400,
                                       'capabilities': capabilities,
                                       'service': service})
        self.assertFalse(filt_cls.backend_passes(host, filter_properties))

    def test_json_filter_basic_operators(self):
        filt_cls = self.class_map['JsonFilter']()
        host = fakes.FakeBackendState('host1',
                                      {'capabilities': {'enabled': True}})
        # (operator, arguments, expected_result)
        ops_to_test = [
            ['=', [1, 1], True],
            ['=', [1, 2], False],
            ['<', [1, 2], True],
            ['<', [1, 1], False],
            ['<', [2, 1], False],
            ['>', [2, 1], True],
            ['>', [2, 2], False],
            ['>', [2, 3], False],
            ['<=', [1, 2], True],
            ['<=', [1, 1], True],
            ['<=', [2, 1], False],
            ['>=', [2, 1], True],
            ['>=', [2, 2], True],
            ['>=', [2, 3], False],
            ['in', [1, 1], True],
            ['in', [1, 1, 2, 3], True],
            ['in', [4, 1, 2, 3], False],
            ['not', [True], False],
            ['not', [False], True],
            ['or', [True, False], True],
            ['or', [False, False], False],
            ['and', [True, True], True],
            ['and', [False, False], False],
            ['and', [True, False], False],
            # Nested ((True or False) and (2 > 1)) == Passes
            ['and', [['or', True, False], ['>', 2, 1]], True]]

        for (op, args, expected) in ops_to_test:
            raw = [op] + args
            filter_properties = {
                'scheduler_hints': {
                    'query': jsonutils.dumps(raw),
                },
                'request_spec': {'volume_id': fake.VOLUME_ID}
            }
            self.assertEqual(expected,
                             filt_cls.backend_passes(host, filter_properties))

        # This results in [False, True, False, True] and if any are True
        # then it passes...
        raw = ['not', True, False, True, False]
        filter_properties = {
            'scheduler_hints': {
                'query': jsonutils.dumps(raw),
            },
        }
        self.assertTrue(filt_cls.backend_passes(host, filter_properties))

        # This results in [False, False, False] and if any are True
        # then it passes...which this doesn't
        raw = ['not', True, True, True]
        filter_properties = {
            'scheduler_hints': {
                'query': jsonutils.dumps(raw),
            },
        }
        self.assertFalse(filt_cls.backend_passes(host, filter_properties))

    def test_json_filter_unknown_operator_raises(self):
        filt_cls = self.class_map['JsonFilter']()
        raw = ['!=', 1, 2]
        filter_properties = {
            'scheduler_hints': {
                'query': jsonutils.dumps(raw),
            },
        }
        host = fakes.FakeBackendState('host1',
                                      {'capabilities': {'enabled': True}})
        self.assertRaises(KeyError,
                          filt_cls.backend_passes, host, filter_properties)

    def test_json_filter_empty_filters_pass(self):
        filt_cls = self.class_map['JsonFilter']()
        host = fakes.FakeBackendState('host1',
                                      {'capabilities': {'enabled': True}})

        raw = []
        filter_properties = {
            'scheduler_hints': {
                'query': jsonutils.dumps(raw),
            },
        }
        self.assertTrue(filt_cls.backend_passes(host, filter_properties))
        raw = {}
        filter_properties = {
            'scheduler_hints': {
                'query': jsonutils.dumps(raw),
            },
        }
        self.assertTrue(filt_cls.backend_passes(host, filter_properties))

    def test_json_filter_invalid_num_arguments_fails(self):
        filt_cls = self.class_map['JsonFilter']()
        host = fakes.FakeBackendState('host1',
                                      {'capabilities': {'enabled': True}})

        raw = ['>', ['and', ['or', ['not', ['<', ['>=', ['<=', ['in', ]]]]]]]]
        filter_properties = {
            'scheduler_hints': {
                'query': jsonutils.dumps(raw),
            },
        }
        self.assertFalse(filt_cls.backend_passes(host, filter_properties))

        raw = ['>', 1]
        filter_properties = {
            'scheduler_hints': {
                'query': jsonutils.dumps(raw),
            },
        }
        self.assertFalse(filt_cls.backend_passes(host, filter_properties))

    def test_json_filter_unknown_variable_ignored(self):
        filt_cls = self.class_map['JsonFilter']()
        host = fakes.FakeBackendState('host1',
                                      {'capabilities': {'enabled': True}})

        raw = ['=', '$........', 1, 1]
        filter_properties = {
            'scheduler_hints': {
                'query': jsonutils.dumps(raw),
            },
        }
        self.assertTrue(filt_cls.backend_passes(host, filter_properties))

        raw = ['=', '$foo', 2, 2]
        filter_properties = {
            'scheduler_hints': {
                'query': jsonutils.dumps(raw),
            },
        }
        self.assertTrue(filt_cls.backend_passes(host, filter_properties))

    @staticmethod
    def _make_zone_request(zone, is_admin=False):
        ctxt = context.RequestContext('fake', 'fake', is_admin=is_admin)
        return {
            'context': ctxt,
            'request_spec': {
                'resource_properties': {
                    'availability_zone': zone
                }
            }
        }

    def test_availability_zone_filter_same(self):
        filt_cls = self.class_map['AvailabilityZoneFilter']()
        service = {'availability_zone': 'nova'}
        request = self._make_zone_request('nova')
        host = fakes.FakeBackendState('host1', {'service': service})
        self.assertTrue(filt_cls.backend_passes(host, request))

    def test_availability_zone_filter_different(self):
        filt_cls = self.class_map['AvailabilityZoneFilter']()
        service = {'availability_zone': 'nova'}
        request = self._make_zone_request('bad')
        host = fakes.FakeBackendState('host1', {'service': service})
        self.assertFalse(filt_cls.backend_passes(host, request))

    def test_availability_zone_filter_empty(self):
        filt_cls = self.class_map['AvailabilityZoneFilter']()
        service = {'availability_zone': 'nova'}
        request = {}
        host = fakes.FakeBackendState('host1', {'service': service})
        self.assertTrue(filt_cls.backend_passes(host, request))

    def test_ignore_attempted_hosts_filter_disabled(self):
        # Test case where re-scheduling is disabled.
        filt_cls = self.class_map['IgnoreAttemptedHostsFilter']()
        host = fakes.FakeBackendState('host1', {})
        filter_properties = {}
        self.assertTrue(filt_cls.backend_passes(host, filter_properties))

    def test_ignore_attempted_hosts_filter_pass(self):
        # Node not previously tried.
        filt_cls = self.class_map['IgnoreAttemptedHostsFilter']()
        host = fakes.FakeBackendState('host1', {})
        attempted = dict(num_attempts=2, hosts=['host2'])
        filter_properties = dict(retry=attempted)
        self.assertTrue(filt_cls.backend_passes(host, filter_properties))

    def test_ignore_attempted_hosts_filter_fail(self):
        # Node was already tried.
        filt_cls = self.class_map['IgnoreAttemptedHostsFilter']()
        host = fakes.FakeBackendState('host1', {})
        attempted = dict(num_attempts=2, backends=['host1'])
        filter_properties = dict(retry=attempted)
        self.assertFalse(filt_cls.backend_passes(host, filter_properties))
