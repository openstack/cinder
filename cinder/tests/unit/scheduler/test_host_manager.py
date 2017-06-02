# Copyright (c) 2011 OpenStack Foundation
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
Tests For HostManager
"""

from datetime import datetime
from datetime import timedelta
import ddt

import mock
from oslo_serialization import jsonutils
from oslo_utils import timeutils

from cinder.common import constants
from cinder import context
from cinder import db
from cinder import exception
from cinder import objects
from cinder.scheduler import filters
from cinder.scheduler import host_manager
from cinder import test
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit.objects import test_service


class FakeFilterClass1(filters.BaseBackendFilter):
    def backend_passes(self, host_state, filter_properties):
        pass


class FakeFilterClass2(filters.BaseBackendFilter):
    def backend_passes(self, host_state, filter_properties):
        pass


class FakeFilterClass3(filters.BaseHostFilter):
    def host_passes(self, host_state, filter_properties):
        return host_state.get('volume_backend_name') == \
            filter_properties.get('volume_type')['volume_backend_name']


@ddt.ddt
class HostManagerTestCase(test.TestCase):
    """Test case for HostManager class."""

    def setUp(self):
        super(HostManagerTestCase, self).setUp()
        self.host_manager = host_manager.HostManager()
        self.fake_backends = [host_manager.BackendState('fake_be%s' % x, None)
                              for x in range(1, 5)]
        # For a second scheduler service.
        self.host_manager_1 = host_manager.HostManager()

    def test_choose_backend_filters_not_found(self):
        self.flags(scheduler_default_filters='FakeFilterClass3')
        self.host_manager.filter_classes = [FakeFilterClass1,
                                            FakeFilterClass2]
        self.assertRaises(exception.SchedulerHostFilterNotFound,
                          self.host_manager._choose_backend_filters, None)

    def test_choose_backend_filters(self):
        self.flags(scheduler_default_filters=['FakeFilterClass2'])
        self.host_manager.filter_classes = [FakeFilterClass1,
                                            FakeFilterClass2]

        # Test 'volume' returns 1 correct function
        filter_classes = self.host_manager._choose_backend_filters(None)
        self.assertEqual(1, len(filter_classes))
        self.assertEqual('FakeFilterClass2', filter_classes[0].__name__)

    @mock.patch('cinder.scheduler.host_manager.HostManager.'
                '_choose_backend_filters')
    def test_get_filtered_backends(self, _mock_choose_backend_filters):
        filter_class = FakeFilterClass1
        mock_func = mock.Mock()
        mock_func.return_value = True
        filter_class._filter_one = mock_func
        _mock_choose_backend_filters.return_value = [filter_class]

        fake_properties = {'moo': 1, 'cow': 2}
        expected = []
        for fake_backend in self.fake_backends:
            expected.append(mock.call(fake_backend, fake_properties))

        result = self.host_manager.get_filtered_backends(self.fake_backends,
                                                         fake_properties)
        self.assertEqual(expected, mock_func.call_args_list)
        self.assertEqual(set(self.fake_backends), set(result))

    @mock.patch('cinder.scheduler.host_manager.HostManager._get_updated_pools')
    @mock.patch('oslo_utils.timeutils.utcnow')
    def test_update_service_capabilities(self, _mock_utcnow,
                                         _mock_get_updated_pools):
        service_states = self.host_manager.service_states
        self.assertDictEqual({}, service_states)
        _mock_utcnow.side_effect = [31338, 31339]

        _mock_get_updated_pools.return_value = []
        timestamp = jsonutils.to_primitive(datetime.utcnow())
        host1_volume_capabs = dict(free_capacity_gb=4321, timestamp=timestamp)
        host1_old_volume_capabs = dict(free_capacity_gb=1, timestamp=timestamp)
        host2_volume_capabs = dict(free_capacity_gb=5432)
        host3_volume_capabs = dict(free_capacity_gb=6543)

        service_name = 'volume'
        # The host manager receives a deserialized timestamp
        timestamp = datetime.strptime(timestamp, timeutils.PERFECT_TIME_FORMAT)
        self.host_manager.update_service_capabilities(service_name, 'host1',
                                                      host1_volume_capabs,
                                                      None, timestamp)
        # It'll ignore older updates
        old_timestamp = timestamp - timedelta(hours=1)
        self.host_manager.update_service_capabilities(service_name, 'host1',
                                                      host1_old_volume_capabs,
                                                      None, old_timestamp)
        self.host_manager.update_service_capabilities(service_name, 'host2',
                                                      host2_volume_capabs,
                                                      None, None)
        self.host_manager.update_service_capabilities(service_name, 'host3',
                                                      host3_volume_capabs,
                                                      None, None)

        # Make sure dictionary isn't re-assigned
        self.assertEqual(service_states, self.host_manager.service_states)

        host1_volume_capabs['timestamp'] = timestamp
        host2_volume_capabs['timestamp'] = 31338
        host3_volume_capabs['timestamp'] = 31339

        expected = {'host1': host1_volume_capabs,
                    'host2': host2_volume_capabs,
                    'host3': host3_volume_capabs}
        self.assertDictEqual(expected, service_states)

    @mock.patch(
        'cinder.scheduler.host_manager.HostManager.get_usage_and_notify')
    @mock.patch('oslo_utils.timeutils.utcnow')
    def test_update_and_notify_service_capabilities_case1(
            self, _mock_utcnow,
            _mock_get_usage_and_notify):

        _mock_utcnow.side_effect = [31337, 31338, 31339]
        service_name = 'volume'

        capab1 = {'pools': [{
                  'pool_name': 'pool1', 'thick_provisioning_support': True,
                  'thin_provisioning_support': False, 'total_capacity_gb': 10,
                  'free_capacity_gb': 10, 'max_over_subscription_ratio': 1,
                  'provisioned_capacity_gb': 0, 'allocated_capacity_gb': 0,
                  'reserved_percentage': 0}]}

        # Run 1:
        # capa: capa1
        # S0: update_service_capabilities()
        # S0: notify_service_capabilities()
        # S1: update_service_capabilities()
        #
        # notify capab1 to ceilometer by S0
        #

        # S0: update_service_capabilities()
        self.host_manager.update_service_capabilities(service_name, 'host1',
                                                      capab1, None, None)
        self.assertDictEqual(dict(dict(timestamp=31337), **capab1),
                             self.host_manager.service_states['host1'])

        # S0: notify_service_capabilities()
        self.host_manager.notify_service_capabilities(service_name, 'host1',
                                                      capab1, None)
        self.assertDictEqual(dict(dict(timestamp=31337), **capab1),
                             self.host_manager.service_states['host1'])
        self.assertDictEqual(
            dict(dict(timestamp=31338), **capab1),
            self.host_manager.service_states_last_update['host1'])

        # notify capab1 to ceilometer by S0
        self.assertTrue(1, _mock_get_usage_and_notify.call_count)

        # S1: update_service_capabilities()
        self.host_manager_1.update_service_capabilities(service_name, 'host1',
                                                        capab1, None, None)

        self.assertDictEqual(dict(dict(timestamp=31339), **capab1),
                             self.host_manager_1.service_states['host1'])

    @mock.patch(
        'cinder.scheduler.host_manager.HostManager.get_usage_and_notify')
    @mock.patch('oslo_utils.timeutils.utcnow')
    def test_update_and_notify_service_capabilities_case2(
            self, _mock_utcnow,
            _mock_get_usage_and_notify):

        _mock_utcnow.side_effect = [31340, 31341, 31342]

        service_name = 'volume'

        capab1 = {'pools': [{
                  'pool_name': 'pool1', 'thick_provisioning_support': True,
                  'thin_provisioning_support': False, 'total_capacity_gb': 10,
                  'free_capacity_gb': 10, 'max_over_subscription_ratio': 1,
                  'provisioned_capacity_gb': 0, 'allocated_capacity_gb': 0,
                  'reserved_percentage': 0}]}

        self.host_manager.service_states['host1'] = (
            dict(dict(timestamp=31337), **capab1))
        self.host_manager.service_states_last_update['host1'] = (
            dict(dict(timestamp=31338), **capab1))
        self.host_manager_1.service_states['host1'] = (
            dict(dict(timestamp=31339), **capab1))

        # Run 2:
        # capa: capa1
        # S0: update_service_capabilities()
        # S1: update_service_capabilities()
        # S1: notify_service_capabilities()
        #
        # Don't notify capab1 to ceilometer.

        # S0: update_service_capabilities()
        self.host_manager.update_service_capabilities(service_name, 'host1',
                                                      capab1, None, None)

        self.assertDictEqual(dict(dict(timestamp=31340), **capab1),
                             self.host_manager.service_states['host1'])

        self.assertDictEqual(
            dict(dict(timestamp=31338), **capab1),
            self.host_manager.service_states_last_update['host1'])

        # S1: update_service_capabilities()
        self.host_manager_1.update_service_capabilities(service_name, 'host1',
                                                        capab1, None, None)

        self.assertDictEqual(dict(dict(timestamp=31341), **capab1),
                             self.host_manager_1.service_states['host1'])

        self.assertDictEqual(
            dict(dict(timestamp=31339), **capab1),
            self.host_manager_1.service_states_last_update['host1'])

        # S1: notify_service_capabilities()
        self.host_manager_1.notify_service_capabilities(service_name, 'host1',
                                                        capab1, None)

        self.assertDictEqual(dict(dict(timestamp=31341), **capab1),
                             self.host_manager_1.service_states['host1'])

        self.assertDictEqual(
            self.host_manager_1.service_states_last_update['host1'],
            dict(dict(timestamp=31339), **capab1))

        # Don't notify capab1 to ceilometer.
        self.assertTrue(1, _mock_get_usage_and_notify.call_count)

    @mock.patch(
        'cinder.scheduler.host_manager.HostManager.get_usage_and_notify')
    @mock.patch('oslo_utils.timeutils.utcnow')
    def test_update_and_notify_service_capabilities_case3(
            self, _mock_utcnow,
            _mock_get_usage_and_notify):

        _mock_utcnow.side_effect = [31343, 31344, 31345]

        service_name = 'volume'

        capab1 = {'pools': [{
                  'pool_name': 'pool1', 'thick_provisioning_support': True,
                  'thin_provisioning_support': False, 'total_capacity_gb': 10,
                  'free_capacity_gb': 10, 'max_over_subscription_ratio': 1,
                  'provisioned_capacity_gb': 0, 'allocated_capacity_gb': 0,
                  'reserved_percentage': 0}]}

        self.host_manager.service_states['host1'] = (
            dict(dict(timestamp=31340), **capab1))
        self.host_manager.service_states_last_update['host1'] = (
            dict(dict(timestamp=31338), **capab1))
        self.host_manager_1.service_states['host1'] = (
            dict(dict(timestamp=31341), **capab1))
        self.host_manager_1.service_states_last_update['host1'] = (
            dict(dict(timestamp=31339), **capab1))

        # Run 3:
        # capa: capab1
        # S0: notify_service_capabilities()
        # S0: update_service_capabilities()
        # S1: update_service_capabilities()
        #
        # Don't notify capab1 to ceilometer.

        # S0: notify_service_capabilities()
        self.host_manager.notify_service_capabilities(service_name, 'host1',
                                                      capab1, None)
        self.assertDictEqual(
            dict(dict(timestamp=31338), **capab1),
            self.host_manager.service_states_last_update['host1'])

        self.assertDictEqual(dict(dict(timestamp=31340), **capab1),
                             self.host_manager.service_states['host1'])

        # Don't notify capab1 to ceilometer.
        self.assertTrue(1, _mock_get_usage_and_notify.call_count)

        # S0: update_service_capabilities()
        self.host_manager.update_service_capabilities(service_name, 'host1',
                                                      capab1, None, None)

        self.assertDictEqual(
            dict(dict(timestamp=31340), **capab1),
            self.host_manager.service_states_last_update['host1'])

        self.assertDictEqual(dict(dict(timestamp=31344), **capab1),
                             self.host_manager.service_states['host1'])

        # S1: update_service_capabilities()
        self.host_manager_1.update_service_capabilities(service_name, 'host1',
                                                        capab1, None, None)
        self.assertDictEqual(dict(dict(timestamp=31345), **capab1),
                             self.host_manager_1.service_states['host1'])

        self.assertDictEqual(
            dict(dict(timestamp=31341), **capab1),
            self.host_manager_1.service_states_last_update['host1'])

    @mock.patch(
        'cinder.scheduler.host_manager.HostManager.get_usage_and_notify')
    @mock.patch('oslo_utils.timeutils.utcnow')
    def test_update_and_notify_service_capabilities_case4(
            self, _mock_utcnow,
            _mock_get_usage_and_notify):

        _mock_utcnow.side_effect = [31346, 31347, 31348]

        service_name = 'volume'

        capab1 = {'pools': [{
                  'pool_name': 'pool1', 'thick_provisioning_support': True,
                  'thin_provisioning_support': False, 'total_capacity_gb': 10,
                  'free_capacity_gb': 10, 'max_over_subscription_ratio': 1,
                  'provisioned_capacity_gb': 0, 'allocated_capacity_gb': 0,
                  'reserved_percentage': 0}]}

        self.host_manager.service_states['host1'] = (
            dict(dict(timestamp=31344), **capab1))
        self.host_manager.service_states_last_update['host1'] = (
            dict(dict(timestamp=31340), **capab1))
        self.host_manager_1.service_states['host1'] = (
            dict(dict(timestamp=31345), **capab1))
        self.host_manager_1.service_states_last_update['host1'] = (
            dict(dict(timestamp=31341), **capab1))

        capab2 = {'pools': [{
                  'pool_name': 'pool1', 'thick_provisioning_support': True,
                  'thin_provisioning_support': False, 'total_capacity_gb': 10,
                  'free_capacity_gb': 9, 'max_over_subscription_ratio': 1,
                  'provisioned_capacity_gb': 1, 'allocated_capacity_gb': 1,
                  'reserved_percentage': 0}]}

        # Run 4:
        # capa: capab2
        # S0: update_service_capabilities()
        # S1: notify_service_capabilities()
        # S1: update_service_capabilities()
        #
        # notify capab2 to ceilometer.

        # S0: update_service_capabilities()
        self.host_manager.update_service_capabilities(service_name, 'host1',
                                                      capab2, None, None)
        self.assertDictEqual(
            dict(dict(timestamp=31340), **capab1),
            self.host_manager.service_states_last_update['host1'])

        self.assertDictEqual(dict(dict(timestamp=31346), **capab2),
                             self.host_manager.service_states['host1'])

        # S1: notify_service_capabilities()
        self.host_manager_1.notify_service_capabilities(service_name, 'host1',
                                                        capab2, None)
        self.assertDictEqual(dict(dict(timestamp=31345), **capab1),
                             self.host_manager_1.service_states['host1'])

        self.assertDictEqual(
            dict(dict(timestamp=31347), **capab2),
            self.host_manager_1.service_states_last_update['host1'])

        # notify capab2 to ceilometer.
        self.assertTrue(2, _mock_get_usage_and_notify.call_count)

        # S1: update_service_capabilities()
        self.host_manager_1.update_service_capabilities(service_name, 'host1',
                                                        capab2, None, None)
        self.assertDictEqual(dict(dict(timestamp=31348), **capab2),
                             self.host_manager_1.service_states['host1'])

        self.assertDictEqual(
            dict(dict(timestamp=31347), **capab2),
            self.host_manager_1.service_states_last_update['host1'])

    @mock.patch(
        'cinder.scheduler.host_manager.HostManager.get_usage_and_notify')
    @mock.patch('oslo_utils.timeutils.utcnow')
    def test_update_and_notify_service_capabilities_case5(
            self, _mock_utcnow,
            _mock_get_usage_and_notify):

        _mock_utcnow.side_effect = [31349, 31350, 31351]

        service_name = 'volume'

        capab1 = {'pools': [{
                  'pool_name': 'pool1', 'thick_provisioning_support': True,
                  'thin_provisioning_support': False, 'total_capacity_gb': 10,
                  'free_capacity_gb': 10, 'max_over_subscription_ratio': 1,
                  'provisioned_capacity_gb': 0, 'allocated_capacity_gb': 0,
                  'reserved_percentage': 0}]}

        capab2 = {'pools': [{
                  'pool_name': 'pool1', 'thick_provisioning_support': True,
                  'thin_provisioning_support': False, 'total_capacity_gb': 10,
                  'free_capacity_gb': 9, 'max_over_subscription_ratio': 1,
                  'provisioned_capacity_gb': 1, 'allocated_capacity_gb': 1,
                  'reserved_percentage': 0}]}

        self.host_manager.service_states['host1'] = (
            dict(dict(timestamp=31346), **capab2))
        self.host_manager.service_states_last_update['host1'] = (
            dict(dict(timestamp=31340), **capab1))
        self.host_manager_1.service_states['host1'] = (
            dict(dict(timestamp=31348), **capab2))
        self.host_manager_1.service_states_last_update['host1'] = (
            dict(dict(timestamp=31347), **capab2))

        # Run 5:
        # capa: capa2
        # S0: notify_service_capabilities()
        # S0: update_service_capabilities()
        # S1: update_service_capabilities()
        #
        # This is the special case not handled.
        # 1) capab is changed (from capab1 to capab2)
        # 2) S1 has already notify the capab2 in Run 4.
        # 3) S0 just got update_service_capabilities() in Run 4.
        # 4) S0 got notify_service_capabilities() immediately in next run,
        #    here is Run 5.
        #    S0 has no ways to know whether other scheduler (here is S1) who
        #    has noitified the changed capab2 or not. S0 just thinks it's his
        #    own turn to notify the changed capab2.
        #    In this case, we have notified the same capabilities twice.
        #
        # S0: notify_service_capabilities()
        self.host_manager.notify_service_capabilities(service_name, 'host1',
                                                      capab2, None)
        self.assertDictEqual(
            dict(dict(timestamp=31349), **capab2),
            self.host_manager.service_states_last_update['host1'])

        self.assertDictEqual(dict(dict(timestamp=31346), **capab2),
                             self.host_manager.service_states['host1'])

        # S0 notify capab2 to ceilometer.
        self.assertTrue(3, _mock_get_usage_and_notify.call_count)

        # S0: update_service_capabilities()
        self.host_manager.update_service_capabilities(service_name, 'host1',
                                                      capab2, None, None)
        self.assertDictEqual(
            dict(dict(timestamp=31349), **capab2),
            self.host_manager.service_states_last_update['host1'])

        self.assertDictEqual(dict(dict(timestamp=31350), **capab2),
                             self.host_manager.service_states['host1'])

        # S1: update_service_capabilities()
        self.host_manager_1.update_service_capabilities(service_name, 'host1',
                                                        capab2, None, None)

        self.assertDictEqual(
            dict(dict(timestamp=31348), **capab2),
            self.host_manager_1.service_states_last_update['host1'])

        self.assertDictEqual(dict(dict(timestamp=31351), **capab2),
                             self.host_manager_1.service_states['host1'])

    @mock.patch('cinder.objects.service.Service.is_up',
                new_callable=mock.PropertyMock)
    @mock.patch('cinder.db.service_get_all')
    def test_has_all_capabilities(self, _mock_service_get_all,
                                  _mock_service_is_up):
        _mock_service_is_up.return_value = True
        services = [
            dict(id=1, host='host1', topic='volume', disabled=False,
                 availability_zone='zone1', updated_at=timeutils.utcnow()),
            dict(id=2, host='host2', topic='volume', disabled=False,
                 availability_zone='zone1', updated_at=timeutils.utcnow()),
            dict(id=3, host='host3', topic='volume', disabled=False,
                 availability_zone='zone1', updated_at=timeutils.utcnow()),
        ]
        _mock_service_get_all.return_value = services
        # Create host_manager again to let db.service_get_all mock run
        self.host_manager = host_manager.HostManager()
        self.assertFalse(self.host_manager.has_all_capabilities())

        timestamp = jsonutils.to_primitive(datetime.utcnow())
        host1_volume_capabs = dict(free_capacity_gb=4321)
        host2_volume_capabs = dict(free_capacity_gb=5432)
        host3_volume_capabs = dict(free_capacity_gb=6543)

        service_name = 'volume'
        self.host_manager.update_service_capabilities(service_name, 'host1',
                                                      host1_volume_capabs,
                                                      None, timestamp)
        self.assertFalse(self.host_manager.has_all_capabilities())
        self.host_manager.update_service_capabilities(service_name, 'host2',
                                                      host2_volume_capabs,
                                                      None, timestamp)
        self.assertFalse(self.host_manager.has_all_capabilities())
        self.host_manager.update_service_capabilities(service_name, 'host3',
                                                      host3_volume_capabs,
                                                      None, timestamp)
        self.assertTrue(self.host_manager.has_all_capabilities())

    @mock.patch('cinder.db.service_get_all')
    @mock.patch('cinder.objects.service.Service.is_up',
                new_callable=mock.PropertyMock)
    @mock.patch('oslo_utils.timeutils.utcnow')
    def test_update_and_get_pools(self, _mock_utcnow,
                                  _mock_service_is_up,
                                  _mock_service_get_all):
        """Test interaction between update and get_pools

        This test verifies that each time that get_pools is called it gets the
        latest copy of service_capabilities, which is timestamped with the
        current date/time.
        """
        context = 'fake_context'
        dates = [datetime.fromtimestamp(400), datetime.fromtimestamp(401),
                 datetime.fromtimestamp(402)]
        _mock_utcnow.side_effect = dates

        services = [
            # This is the first call to utcnow()
            dict(id=1, host='host1', topic='volume', disabled=False,
                 availability_zone='zone1', updated_at=timeutils.utcnow()),
        ]

        mocked_service_states = {
            'host1': dict(volume_backend_name='AAA',
                          total_capacity_gb=512, free_capacity_gb=200,
                          timestamp=dates[1], reserved_percentage=0),
        }

        _mock_service_get_all.return_value = services
        _mock_service_is_up.return_value = True
        _mock_warning = mock.Mock()
        host_manager.LOG.warn = _mock_warning

        host_volume_capabs = dict(free_capacity_gb=4321)

        service_name = 'volume'
        with mock.patch.dict(self.host_manager.service_states,
                             mocked_service_states):
            self.host_manager.update_service_capabilities(service_name,
                                                          'host1',
                                                          host_volume_capabs,
                                                          None, None)
            res = self.host_manager.get_pools(context)
            self.assertEqual(1, len(res))
            self.assertEqual(dates[1], res[0]['capabilities']['timestamp'])

    @mock.patch('cinder.objects.Service.is_up', True)
    def test_get_all_backend_states_cluster(self):
        """Test get_all_backend_states when we have clustered services.

        Confirm that clustered services are grouped and that only the latest
        of the capability reports is relevant.
        """
        ctxt = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, True)

        cluster_name = 'cluster'
        db.cluster_create(ctxt, {'name': cluster_name,
                                 'binary': constants.VOLUME_BINARY})

        services = (
            db.service_create(ctxt,
                              {'host': 'clustered_host_1',
                               'topic': constants.VOLUME_TOPIC,
                               'binary': constants.VOLUME_BINARY,
                               'cluster_name': cluster_name,
                               'created_at': timeutils.utcnow()}),
            # Even if this service is disabled, since it belongs to an enabled
            # cluster, it's not really disabled.
            db.service_create(ctxt,
                              {'host': 'clustered_host_2',
                               'topic': constants.VOLUME_TOPIC,
                               'binary': constants.VOLUME_BINARY,
                               'disabled': True,
                               'cluster_name': cluster_name,
                               'created_at': timeutils.utcnow()}),
            db.service_create(ctxt,
                              {'host': 'clustered_host_3',
                               'topic': constants.VOLUME_TOPIC,
                               'binary': constants.VOLUME_BINARY,
                               'cluster_name': cluster_name,
                               'created_at': timeutils.utcnow()}),
            db.service_create(ctxt,
                              {'host': 'non_clustered_host',
                               'topic': constants.VOLUME_TOPIC,
                               'binary': constants.VOLUME_BINARY,
                               'created_at': timeutils.utcnow()}),
            # This service has no capabilities
            db.service_create(ctxt,
                              {'host': 'no_capabilities_host',
                               'topic': constants.VOLUME_TOPIC,
                               'binary': constants.VOLUME_BINARY,
                               'created_at': timeutils.utcnow()}),
        )

        capabilities = ((1, {'free_capacity_gb': 1000}),
                        # This is the capacity that will be selected for the
                        # cluster because is the one with the latest timestamp.
                        (3, {'free_capacity_gb': 2000}),
                        (2, {'free_capacity_gb': 3000}),
                        (1, {'free_capacity_gb': 4000}))

        for i in range(len(capabilities)):
            self.host_manager.update_service_capabilities(
                'volume', services[i].host, capabilities[i][1],
                services[i].cluster_name, capabilities[i][0])

        res = self.host_manager.get_all_backend_states(ctxt)
        result = {(s.cluster_name or s.host, s.free_capacity_gb) for s in res}
        expected = {(cluster_name + '#_pool0', 2000),
                    ('non_clustered_host#_pool0', 4000)}
        self.assertSetEqual(expected, result)

    @mock.patch('cinder.db.service_get_all')
    @mock.patch('cinder.objects.service.Service.is_up',
                new_callable=mock.PropertyMock)
    def test_get_all_backend_states(self, _mock_service_is_up,
                                    _mock_service_get_all):
        context = 'fake_context'
        timestamp = datetime.utcnow()
        topic = constants.VOLUME_TOPIC

        services = [
            dict(id=1, host='host1', topic='volume', disabled=False,
                 availability_zone='zone1', updated_at=timeutils.utcnow(),
                 binary=None, deleted=False, created_at=None, modified_at=None,
                 report_count=0, deleted_at=None, disabled_reason=None),
            dict(id=2, host='host2', topic='volume', disabled=False,
                 availability_zone='zone1', updated_at=timeutils.utcnow(),
                 binary=None, deleted=False, created_at=None, modified_at=None,
                 report_count=0, deleted_at=None, disabled_reason=None),
            dict(id=3, host='host3', topic='volume', disabled=False,
                 availability_zone='zone2', updated_at=timeutils.utcnow(),
                 binary=None, deleted=False, created_at=None, modified_at=None,
                 report_count=0, deleted_at=None, disabled_reason=None),
            dict(id=4, host='host4', topic='volume', disabled=False,
                 availability_zone='zone3', updated_at=timeutils.utcnow(),
                 binary=None, deleted=False, created_at=None, modified_at=None,
                 report_count=0, deleted_at=None, disabled_reason=None),
        ]

        service_objs = []
        for db_service in services:
            service_obj = objects.Service()
            service_objs.append(objects.Service._from_db_object(context,
                                                                service_obj,
                                                                db_service))

        service_states = {
            'host1': dict(volume_backend_name='AAA',
                          total_capacity_gb=512, free_capacity_gb=200,
                          timestamp=timestamp, reserved_percentage=0,
                          provisioned_capacity_gb=312),
            'host2': dict(volume_backend_name='BBB',
                          total_capacity_gb=256, free_capacity_gb=100,
                          timestamp=timestamp, reserved_percentage=0,
                          provisioned_capacity_gb=156),
            'host3': dict(volume_backend_name='CCC',
                          total_capacity_gb=10000, free_capacity_gb=700,
                          timestamp=timestamp, reserved_percentage=0,
                          provisioned_capacity_gb=9300),
        }
        # First test: service.is_up is always True, host5 is disabled,
        # host4 has no capabilities
        self.host_manager.service_states = service_states
        _mock_service_get_all.return_value = services
        _mock_service_is_up.return_value = True
        _mock_warning = mock.Mock()
        host_manager.LOG.warning = _mock_warning

        # Get all states
        self.host_manager.get_all_backend_states(context)
        _mock_service_get_all.assert_called_with(context,
                                                 disabled=False,
                                                 frozen=False,
                                                 topic=topic)

        # verify that Service.is_up was called for each srv
        expected = [mock.call() for s in service_objs]
        self.assertEqual(expected, _mock_service_is_up.call_args_list)

        # Get backend_state_map and make sure we have the first 3 hosts
        backend_state_map = self.host_manager.backend_state_map
        self.assertEqual(3, len(backend_state_map))
        for i in range(3):
            volume_node = services[i]
            host = volume_node['host']
            test_service.TestService._compare(self, volume_node,
                                              backend_state_map[host].service)

        # Second test: Now service.is_up returns False for host3
        _mock_service_is_up.reset_mock()
        _mock_service_is_up.side_effect = [True, True, False, True]
        _mock_service_get_all.reset_mock()
        _mock_warning.reset_mock()

        # Get all states, make sure host 3 is reported as down
        self.host_manager.get_all_backend_states(context)
        _mock_service_get_all.assert_called_with(context,
                                                 disabled=False,
                                                 frozen=False,
                                                 topic=topic)

        self.assertEqual(expected, _mock_service_is_up.call_args_list)
        self.assertGreater(_mock_warning.call_count, 0)

        # Get backend_state_map and make sure we have the first 2 hosts (host3
        # is down, host4 is missing capabilities)
        backend_state_map = self.host_manager.backend_state_map
        self.assertEqual(2, len(backend_state_map))
        for i in range(2):
            volume_node = services[i]
            host = volume_node['host']
            test_service.TestService._compare(self, volume_node,
                                              backend_state_map[host].service)

    @mock.patch('cinder.db.service_get_all')
    @mock.patch('cinder.objects.service.Service.is_up',
                new_callable=mock.PropertyMock)
    def test_get_pools(self, _mock_service_is_up,
                       _mock_service_get_all):
        context = 'fake_context'
        timestamp = datetime.utcnow()

        services = [
            dict(id=1, host='host1', topic='volume', disabled=False,
                 availability_zone='zone1', updated_at=timeutils.utcnow()),
            dict(id=2, host='host2@back1', topic='volume', disabled=False,
                 availability_zone='zone1', updated_at=timeutils.utcnow()),
            dict(id=3, host='host2@back2', topic='volume', disabled=False,
                 availability_zone='zone2', updated_at=timeutils.utcnow()),
        ]

        mocked_service_states = {
            'host1': dict(volume_backend_name='AAA',
                          total_capacity_gb=512, free_capacity_gb=200,
                          timestamp=timestamp, reserved_percentage=0,
                          provisioned_capacity_gb=312),
            'host2@back1': dict(volume_backend_name='BBB',
                                total_capacity_gb=256, free_capacity_gb=100,
                                timestamp=timestamp, reserved_percentage=0,
                                provisioned_capacity_gb=156),
            'host2@back2': dict(volume_backend_name='CCC',
                                total_capacity_gb=10000, free_capacity_gb=700,
                                timestamp=timestamp, reserved_percentage=0,
                                provisioned_capacity_gb=9300),
        }

        _mock_service_get_all.return_value = services
        _mock_service_is_up.return_value = True
        _mock_warning = mock.Mock()
        host_manager.LOG.warn = _mock_warning

        with mock.patch.dict(self.host_manager.service_states,
                             mocked_service_states):
            res = self.host_manager.get_pools(context)

            # check if get_pools returns all 3 pools
            self.assertEqual(3, len(res))

            expected = [
                {
                    'name': 'host1#AAA',
                    'capabilities': {
                        'timestamp': timestamp,
                        'volume_backend_name': 'AAA',
                        'free_capacity_gb': 200,
                        'driver_version': None,
                        'total_capacity_gb': 512,
                        'reserved_percentage': 0,
                        'vendor_name': None,
                        'storage_protocol': None,
                        'provisioned_capacity_gb': 312},
                },
                {
                    'name': 'host2@back1#BBB',
                    'capabilities': {
                        'timestamp': timestamp,
                        'volume_backend_name': 'BBB',
                        'free_capacity_gb': 100,
                        'driver_version': None,
                        'total_capacity_gb': 256,
                        'reserved_percentage': 0,
                        'vendor_name': None,
                        'storage_protocol': None,
                        'provisioned_capacity_gb': 156},
                },
                {
                    'name': 'host2@back2#CCC',
                    'capabilities': {
                        'timestamp': timestamp,
                        'volume_backend_name': 'CCC',
                        'free_capacity_gb': 700,
                        'driver_version': None,
                        'total_capacity_gb': 10000,
                        'reserved_percentage': 0,
                        'vendor_name': None,
                        'storage_protocol': None,
                        'provisioned_capacity_gb': 9300},
                }
            ]

            def sort_func(data):
                return data['name']

            self.assertEqual(len(expected), len(res))
            self.assertEqual(sorted(expected, key=sort_func),
                             sorted(res, key=sort_func))

    def test_get_usage(self):
        host = "host1@backend1"
        timestamp = 40000
        volume_stats1 = {'pools': [
                         {'pool_name': 'pool1',
                          'total_capacity_gb': 30.01,
                          'free_capacity_gb': 28.01,
                          'allocated_capacity_gb': 2.0,
                          'provisioned_capacity_gb': 2.0,
                          'max_over_subscription_ratio': 1.0,
                          'thin_provisioning_support': False,
                          'thick_provisioning_support': True,
                          'reserved_percentage': 5},
                         {'pool_name': 'pool2',
                          'total_capacity_gb': 20.01,
                          'free_capacity_gb': 18.01,
                          'allocated_capacity_gb': 2.0,
                          'provisioned_capacity_gb': 2.0,
                          'max_over_subscription_ratio': 2.0,
                          'thin_provisioning_support': True,
                          'thick_provisioning_support': False,
                          'reserved_percentage': 5}]}

        updated_pools1 = [{'pool_name': 'pool1',
                           'total_capacity_gb': 30.01,
                           'free_capacity_gb': 28.01,
                           'allocated_capacity_gb': 2.0,
                           'provisioned_capacity_gb': 2.0,
                           'max_over_subscription_ratio': 1.0,
                           'thin_provisioning_support': False,
                           'thick_provisioning_support': True,
                           'reserved_percentage': 5},
                          {'pool_name': 'pool2',
                           'total_capacity_gb': 20.01,
                           'free_capacity_gb': 18.01,
                           'allocated_capacity_gb': 2.0,
                           'provisioned_capacity_gb': 2.0,
                           'max_over_subscription_ratio': 2.0,
                           'thin_provisioning_support': True,
                           'thick_provisioning_support': False,
                           'reserved_percentage': 5}]

        volume_stats2 = {'pools': [
                         {'pool_name': 'pool1',
                          'total_capacity_gb': 30.01,
                          'free_capacity_gb': 28.01,
                          'allocated_capacity_gb': 2.0,
                          'provisioned_capacity_gb': 2.0,
                          'max_over_subscription_ratio': 2.0,
                          'thin_provisioning_support': True,
                          'thick_provisioning_support': False,
                          'reserved_percentage': 0},
                         {'pool_name': 'pool2',
                          'total_capacity_gb': 20.01,
                          'free_capacity_gb': 18.01,
                          'allocated_capacity_gb': 2.0,
                          'provisioned_capacity_gb': 2.0,
                          'max_over_subscription_ratio': 2.0,
                          'thin_provisioning_support': True,
                          'thick_provisioning_support': False,
                          'reserved_percentage': 5}]}

        updated_pools2 = [{'pool_name': 'pool1',
                           'total_capacity_gb': 30.01,
                           'free_capacity_gb': 28.01,
                           'allocated_capacity_gb': 2.0,
                           'provisioned_capacity_gb': 2.0,
                           'max_over_subscription_ratio': 2.0,
                           'thin_provisioning_support': True,
                           'thick_provisioning_support': False,
                           'reserved_percentage': 0}]

        expected1 = [
            {"name_to_id": 'host1@backend1#pool1',
             "type": "pool",
             "total": 30.01,
             "free": 28.01,
             "allocated": 2.0,
             "provisioned": 2.0,
             "virtual_free": 27.01,
             "reported_at": 40000},
            {"name_to_id": 'host1@backend1#pool2',
             "type": "pool",
             "total": 20.01,
             "free": 18.01,
             "allocated": 2.0,
             "provisioned": 2.0,
             "virtual_free": 37.02,
             "reported_at": 40000},
            {"name_to_id": 'host1@backend1',
             "type": "backend",
             "total": 50.02,
             "free": 46.02,
             "allocated": 4.0,
             "provisioned": 4.0,
             "virtual_free": 64.03,
             "reported_at": 40000}]

        expected2 = [
            {"name_to_id": 'host1@backend1#pool1',
             "type": "pool",
             "total": 30.01,
             "free": 28.01,
             "allocated": 2.0,
             "provisioned": 2.0,
             "virtual_free": 58.02,
             "reported_at": 40000},
            {"name_to_id": 'host1@backend1',
             "type": "backend",
             "total": 50.02,
             "free": 46.02,
             "allocated": 4.0,
             "provisioned": 4.0,
             "virtual_free": 95.04,
             "reported_at": 40000}]

        def sort_func(data):
            return data['name_to_id']

        res1 = self.host_manager._get_usage(volume_stats1,
                                            updated_pools1, host, timestamp)
        self.assertEqual(len(expected1), len(res1))
        self.assertEqual(sorted(expected1, key=sort_func),
                         sorted(res1, key=sort_func))

        res2 = self.host_manager._get_usage(volume_stats2,
                                            updated_pools2, host, timestamp)
        self.assertEqual(len(expected2), len(res2))
        self.assertEqual(sorted(expected2, key=sort_func),
                         sorted(res2, key=sort_func))

    @mock.patch('cinder.db.service_get_all')
    @mock.patch('cinder.objects.service.Service.is_up',
                new_callable=mock.PropertyMock)
    def test_get_pools_filter_name(self, _mock_service_is_up,
                                   _mock_service_get_all_by_topic):
        context = 'fake_context'

        services = [
            dict(id=1, host='host1', topic='volume', disabled=False,
                 availability_zone='zone1', updated_at=timeutils.utcnow()),
            dict(id=2, host='host2@back1', topic='volume', disabled=False,
                 availability_zone='zone1', updated_at=timeutils.utcnow())
        ]

        mocked_service_states = {
            'host1': dict(volume_backend_name='AAA',
                          total_capacity_gb=512, free_capacity_gb=200,
                          timestamp=None, reserved_percentage=0,
                          provisioned_capacity_gb=312),
            'host2@back1': dict(volume_backend_name='BBB',
                                total_capacity_gb=256, free_capacity_gb=100,
                                timestamp=None, reserved_percentage=0,
                                provisioned_capacity_gb=156)
        }

        _mock_service_get_all_by_topic.return_value = services
        _mock_service_is_up.return_value = True
        _mock_warning = mock.Mock()
        host_manager.LOG.warn = _mock_warning

        with mock.patch.dict(self.host_manager.service_states,
                             mocked_service_states):
            filters = {'name': 'host1#AAA'}
            res = self.host_manager.get_pools(context, filters=filters)

            expected = [
                {
                    'name': 'host1#AAA',
                    'capabilities': {
                        'timestamp': None,
                        'volume_backend_name': 'AAA',
                        'free_capacity_gb': 200,
                        'driver_version': None,
                        'total_capacity_gb': 512,
                        'reserved_percentage': 0,
                        'vendor_name': None,
                        'storage_protocol': None,
                        'provisioned_capacity_gb': 312},
                }
            ]

            self.assertEqual(expected, res)

    @mock.patch('cinder.scheduler.host_manager.HostManager.'
                '_choose_backend_filters')
    def test_get_pools_filtered_by_volume_type(self,
                                               _mock_choose_backend_filters):
        context = 'fake_context'
        filter_class = FakeFilterClass3
        _mock_choose_backend_filters.return_value = [filter_class]

        hosts = {
            'host1': {'volume_backend_name': 'AAA',
                      'total_capacity_gb': 512,
                      'free_capacity_gb': 200,
                      'timestamp': None,
                      'reserved_percentage': 0,
                      'provisioned_capacity_gb': 312},
            'host2@back1': {'volume_backend_name': 'BBB',
                            'total_capacity_gb': 256,
                            'free_capacity_gb': 100,
                            'timestamp': None,
                            'reserved_percentage': 0,
                            'provisioned_capacity_gb': 156}}
        mock_warning = mock.Mock()
        host_manager.LOG.warn = mock_warning
        mock_volume_type = {
            'volume_backend_name': 'AAA',
            'qos_specs': 'BBB',
        }

        res = self.host_manager._filter_pools_by_volume_type(context,
                                                             mock_volume_type,
                                                             hosts)
        expected = {'host1': {'volume_backend_name': 'AAA',
                              'total_capacity_gb': 512,
                              'free_capacity_gb': 200,
                              'timestamp': None, 'reserved_percentage': 0,
                              'provisioned_capacity_gb': 312}}

        self.assertEqual(expected, res)

    @mock.patch('cinder.db.service_get_all')
    @mock.patch('cinder.objects.service.Service.is_up',
                new_callable=mock.PropertyMock)
    def test_get_pools_filter_mulitattach(self, _mock_service_is_up,
                                          _mock_service_get_all_by_topic):
        context = 'fake_context'

        services = [
            dict(id=1, host='host1', topic='volume', disabled=False,
                 availability_zone='zone1', updated_at=timeutils.utcnow()),
            dict(id=2, host='host2@back1', topic='volume', disabled=False,
                 availability_zone='zone1', updated_at=timeutils.utcnow())
        ]

        mocked_service_states = {
            'host1': dict(volume_backend_name='AAA',
                          total_capacity_gb=512, free_capacity_gb=200,
                          timestamp=None, reserved_percentage=0,
                          multiattach=True),
            'host2@back1': dict(volume_backend_name='BBB',
                                total_capacity_gb=256, free_capacity_gb=100,
                                timestamp=None, reserved_percentage=0,
                                multiattach=False)
        }

        _mock_service_get_all_by_topic.return_value = services
        _mock_service_is_up.return_value = True
        _mock_warning = mock.Mock()
        host_manager.LOG.warn = _mock_warning

        with mock.patch.dict(self.host_manager.service_states,
                             mocked_service_states):
            filters_t = {'multiattach': 'true'}
            filters_f = {'multiattach': False}
            res_t = self.host_manager.get_pools(context, filters=filters_t)
            res_f = self.host_manager.get_pools(context, filters=filters_f)

            expected_t = [
                {
                    'name': 'host1#AAA',
                    'capabilities': {
                        'timestamp': None,
                        'volume_backend_name': 'AAA',
                        'free_capacity_gb': 200,
                        'driver_version': None,
                        'total_capacity_gb': 512,
                        'reserved_percentage': 0,
                        'vendor_name': None,
                        'storage_protocol': None,
                        'multiattach': True},
                }
            ]
            expected_f = [
                {
                    'name': 'host2@back1#BBB',
                    'capabilities': {
                        'timestamp': None,
                        'volume_backend_name': 'BBB',
                        'free_capacity_gb': 100,
                        'driver_version': None,
                        'total_capacity_gb': 256,
                        'reserved_percentage': 0,
                        'vendor_name': None,
                        'storage_protocol': None,
                        'multiattach': False},
                }
            ]

            self.assertEqual(expected_t, res_t)
            self.assertEqual(expected_f, res_f)

    @ddt.data(
        (None, None, True),
        (None, 'value', False),
        ('cap', None, False),
        (False, 'True', False),
        (True, 'True', True),
        (True, True, True),
        (False, 'false', True),
        (1.1, '1.1', True),
        (0, '0', True),
        (1.1, '1.11', False),
        ('str', 'str', True),
        ('str1', 'str2', False),
        ('str', 'StR', False),
        ([], [], True),
        (['hdd', 'ssd'], ['ssd'], False),
        (['hdd', 'ssd'], ['ssd', 'hdd'], False),
        (['hdd', 'ssd'], "['hdd', 'ssd']", True),
        ({}, {}, True),
        ({'a': 'a', 'b': 'b'}, {'b': 'b', 'a': 'a'}, True),
        ({'a': 'a', 'b': 'b'}, {'b': 'b'}, False),
        ({'a': 'a'}, "{'a': 'a'}", True),
    )
    @ddt.unpack
    def test_equal_after_convert(self, cap, value, ret_value):
        self.assertEqual(ret_value,
                         self.host_manager._equal_after_convert(cap, value))


class BackendStateTestCase(test.TestCase):
    """Test case for BackendState class."""

    def test_update_from_volume_capability_nopool(self):
        fake_backend = host_manager.BackendState('be1', None)
        self.assertIsNone(fake_backend.free_capacity_gb)

        volume_capability = {'total_capacity_gb': 1024,
                             'free_capacity_gb': 512,
                             'provisioned_capacity_gb': 512,
                             'reserved_percentage': 0,
                             'timestamp': None}

        fake_backend.update_from_volume_capability(volume_capability)
        # Backend level stats remain uninitialized
        self.assertEqual(0, fake_backend.total_capacity_gb)
        self.assertIsNone(fake_backend.free_capacity_gb)
        # Pool stats has been updated
        self.assertEqual(1024, fake_backend.pools['_pool0'].total_capacity_gb)
        self.assertEqual(512, fake_backend.pools['_pool0'].free_capacity_gb)
        self.assertEqual(512,
                         fake_backend.pools['_pool0'].provisioned_capacity_gb)

        # Test update for existing host state
        volume_capability.update(dict(total_capacity_gb=1000))
        fake_backend.update_from_volume_capability(volume_capability)
        self.assertEqual(1000, fake_backend.pools['_pool0'].total_capacity_gb)

        # Test update for existing host state with different backend name
        volume_capability.update(dict(volume_backend_name='magic'))
        fake_backend.update_from_volume_capability(volume_capability)
        self.assertEqual(1000, fake_backend.pools['magic'].total_capacity_gb)
        self.assertEqual(512, fake_backend.pools['magic'].free_capacity_gb)
        self.assertEqual(512,
                         fake_backend.pools['magic'].provisioned_capacity_gb)
        # 'pool0' becomes nonactive pool, and is deleted
        self.assertRaises(KeyError, lambda: fake_backend.pools['pool0'])

    def test_update_from_volume_capability_with_pools(self):
        fake_backend = host_manager.BackendState('host1', None)
        self.assertIsNone(fake_backend.free_capacity_gb)
        capability = {
            'volume_backend_name': 'Local iSCSI',
            'vendor_name': 'OpenStack',
            'driver_version': '1.0.1',
            'storage_protocol': 'iSCSI',
            'pools': [
                {'pool_name': '1st pool',
                 'total_capacity_gb': 500,
                 'free_capacity_gb': 230,
                 'allocated_capacity_gb': 270,
                 'provisioned_capacity_gb': 270,
                 'QoS_support': 'False',
                 'reserved_percentage': 0,
                 'dying_disks': 100,
                 'super_hero_1': 'spider-man',
                 'super_hero_2': 'flash',
                 'super_hero_3': 'neoncat',
                 },
                {'pool_name': '2nd pool',
                 'total_capacity_gb': 1024,
                 'free_capacity_gb': 1024,
                 'allocated_capacity_gb': 0,
                 'provisioned_capacity_gb': 0,
                 'QoS_support': 'False',
                 'reserved_percentage': 0,
                 'dying_disks': 200,
                 'super_hero_1': 'superman',
                 'super_hero_2': 'Hulk',
                 }
            ],
            'timestamp': None,
        }

        fake_backend.update_from_volume_capability(capability)

        self.assertEqual('Local iSCSI', fake_backend.volume_backend_name)
        self.assertEqual('iSCSI', fake_backend.storage_protocol)
        self.assertEqual('OpenStack', fake_backend.vendor_name)
        self.assertEqual('1.0.1', fake_backend.driver_version)

        # Backend level stats remain uninitialized
        self.assertEqual(0, fake_backend.total_capacity_gb)
        self.assertIsNone(fake_backend.free_capacity_gb)
        # Pool stats has been updated
        self.assertEqual(2, len(fake_backend.pools))

        self.assertEqual(500, fake_backend.pools['1st pool'].total_capacity_gb)
        self.assertEqual(230, fake_backend.pools['1st pool'].free_capacity_gb)
        self.assertEqual(
            270, fake_backend.pools['1st pool'].provisioned_capacity_gb)
        self.assertEqual(
            1024, fake_backend.pools['2nd pool'].total_capacity_gb)
        self.assertEqual(1024, fake_backend.pools['2nd pool'].free_capacity_gb)
        self.assertEqual(
            0, fake_backend.pools['2nd pool'].provisioned_capacity_gb)

        capability = {
            'volume_backend_name': 'Local iSCSI',
            'vendor_name': 'OpenStack',
            'driver_version': '1.0.2',
            'storage_protocol': 'iSCSI',
            'pools': [
                {'pool_name': '3rd pool',
                 'total_capacity_gb': 10000,
                 'free_capacity_gb': 10000,
                 'allocated_capacity_gb': 0,
                 'provisioned_capacity_gb': 0,
                 'QoS_support': 'False',
                 'reserved_percentage': 0,
                 },
            ],
            'timestamp': None,
        }

        # test update BackendState Record
        fake_backend.update_from_volume_capability(capability)

        self.assertEqual('1.0.2', fake_backend.driver_version)

        # Non-active pool stats has been removed
        self.assertEqual(1, len(fake_backend.pools))

        self.assertRaises(KeyError, lambda: fake_backend.pools['1st pool'])
        self.assertRaises(KeyError, lambda: fake_backend.pools['2nd pool'])

        self.assertEqual(10000,
                         fake_backend.pools['3rd pool'].total_capacity_gb)
        self.assertEqual(10000,
                         fake_backend.pools['3rd pool'].free_capacity_gb)
        self.assertEqual(
            0, fake_backend.pools['3rd pool'].provisioned_capacity_gb)

    def test_update_from_volume_infinite_capability(self):
        fake_backend = host_manager.BackendState('host1', None)
        self.assertIsNone(fake_backend.free_capacity_gb)

        volume_capability = {'total_capacity_gb': 'infinite',
                             'free_capacity_gb': 'infinite',
                             'reserved_percentage': 0,
                             'timestamp': None}

        fake_backend.update_from_volume_capability(volume_capability)
        # Backend level stats remain uninitialized
        self.assertEqual(0, fake_backend.total_capacity_gb)
        self.assertIsNone(fake_backend.free_capacity_gb)
        # Pool stats has been updated
        self.assertEqual(
            'infinite',
            fake_backend.pools['_pool0'].total_capacity_gb)
        self.assertEqual(
            'infinite',
            fake_backend.pools['_pool0'].free_capacity_gb)

    def test_update_from_volume_unknown_capability(self):
        fake_backend = host_manager.BackendState('host1', None)
        self.assertIsNone(fake_backend.free_capacity_gb)

        volume_capability = {'total_capacity_gb': 'infinite',
                             'free_capacity_gb': 'unknown',
                             'reserved_percentage': 0,
                             'timestamp': None}

        fake_backend.update_from_volume_capability(volume_capability)
        # Backend level stats remain uninitialized
        self.assertEqual(0, fake_backend.total_capacity_gb)
        self.assertIsNone(fake_backend.free_capacity_gb)
        # Pool stats has been updated
        self.assertEqual(
            'infinite',
            fake_backend.pools['_pool0'].total_capacity_gb)
        self.assertEqual(
            'unknown',
            fake_backend.pools['_pool0'].free_capacity_gb)

    def test_update_from_empty_volume_capability(self):
        fake_backend = host_manager.BackendState('host1', None)

        vol_cap = {'timestamp': None}

        fake_backend.update_from_volume_capability(vol_cap)
        self.assertEqual(0, fake_backend.total_capacity_gb)
        self.assertIsNone(fake_backend.free_capacity_gb)
        # Pool stats has been updated
        self.assertEqual(0,
                         fake_backend.pools['_pool0'].total_capacity_gb)
        self.assertEqual(0,
                         fake_backend.pools['_pool0'].free_capacity_gb)
        self.assertEqual(0,
                         fake_backend.pools['_pool0'].provisioned_capacity_gb)


class PoolStateTestCase(test.TestCase):
    """Test case for BackendState class."""

    def test_update_from_volume_capability(self):
        fake_pool = host_manager.PoolState('host1', None, None, 'pool0')
        self.assertIsNone(fake_pool.free_capacity_gb)

        volume_capability = {'total_capacity_gb': 1024,
                             'free_capacity_gb': 512,
                             'reserved_percentage': 0,
                             'provisioned_capacity_gb': 512,
                             'timestamp': None,
                             'cap1': 'val1',
                             'cap2': 'val2'}

        fake_pool.update_from_volume_capability(volume_capability)
        self.assertEqual('host1#pool0', fake_pool.host)
        self.assertEqual('pool0', fake_pool.pool_name)
        self.assertEqual(1024, fake_pool.total_capacity_gb)
        self.assertEqual(512, fake_pool.free_capacity_gb)
        self.assertEqual(512,
                         fake_pool.provisioned_capacity_gb)

        self.assertDictEqual(volume_capability, dict(fake_pool.capabilities))
