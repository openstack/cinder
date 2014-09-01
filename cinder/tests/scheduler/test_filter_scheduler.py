# Copyright 2011 OpenStack Foundation
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
Tests For Filter Scheduler.
"""

import mock

from cinder import context
from cinder import exception
from cinder.scheduler import filter_scheduler
from cinder.scheduler import host_manager
from cinder.tests.scheduler import fakes
from cinder.tests.scheduler import test_scheduler
from cinder.volume import utils


class FilterSchedulerTestCase(test_scheduler.SchedulerTestCase):
    """Test case for Filter Scheduler."""

    driver_cls = filter_scheduler.FilterScheduler

    def test_create_consistencygroup_no_hosts(self):
        # Ensure empty hosts result in NoValidHosts exception.
        sched = fakes.FakeFilterScheduler()

        fake_context = context.RequestContext('user', 'project')
        request_spec = {'volume_properties': {'project_id': 1,
                                              'size': 0},
                        'volume_type': {'name': 'Type1',
                                        'extra_specs': {}}}
        request_spec2 = {'volume_properties': {'project_id': 1,
                                               'size': 0},
                         'volume_type': {'name': 'Type2',
                                         'extra_specs': {}}}
        request_spec_list = [request_spec, request_spec2]
        self.assertRaises(exception.NoValidHost,
                          sched.schedule_create_consistencygroup,
                          fake_context, 'faki-id1', request_spec_list, {})

    @mock.patch('cinder.db.service_get_all_by_topic')
    def test_schedule_consistencygroup(self,
                                       _mock_service_get_all_by_topic):
        # Make sure _schedule_group() can find host successfully.
        sched = fakes.FakeFilterScheduler()
        sched.host_manager = fakes.FakeHostManager()
        fake_context = context.RequestContext('user', 'project',
                                              is_admin=True)

        fakes.mock_host_manager_db_calls(_mock_service_get_all_by_topic)

        specs = {'capabilities:consistencygroup_support': '<is> True'}
        request_spec = {'volume_properties': {'project_id': 1,
                                              'size': 0},
                        'volume_type': {'name': 'Type1',
                                        'extra_specs': specs}}
        request_spec2 = {'volume_properties': {'project_id': 1,
                                               'size': 0},
                         'volume_type': {'name': 'Type2',
                                         'extra_specs': specs}}
        request_spec_list = [request_spec, request_spec2]
        weighed_host = sched._schedule_group(fake_context,
                                             request_spec_list,
                                             {})
        self.assertIsNotNone(weighed_host.obj)
        self.assertTrue(_mock_service_get_all_by_topic.called)

    @mock.patch('cinder.db.service_get_all_by_topic')
    def test_schedule_consistencygroup_no_cg_support_in_extra_specs(
            self,
            _mock_service_get_all_by_topic):
        # Make sure _schedule_group() can find host successfully even
        # when consistencygroup_support is not specified in volume type's
        # extra specs
        sched = fakes.FakeFilterScheduler()
        sched.host_manager = fakes.FakeHostManager()
        fake_context = context.RequestContext('user', 'project',
                                              is_admin=True)

        fakes.mock_host_manager_db_calls(_mock_service_get_all_by_topic)

        request_spec = {'volume_properties': {'project_id': 1,
                                              'size': 0},
                        'volume_type': {'name': 'Type1',
                                        'extra_specs': {}}}
        request_spec2 = {'volume_properties': {'project_id': 1,
                                               'size': 0},
                         'volume_type': {'name': 'Type2',
                                         'extra_specs': {}}}
        request_spec_list = [request_spec, request_spec2]
        weighed_host = sched._schedule_group(fake_context,
                                             request_spec_list,
                                             {})
        self.assertIsNotNone(weighed_host.obj)
        self.assertTrue(_mock_service_get_all_by_topic.called)

    def test_create_volume_no_hosts(self):
        # Ensure empty hosts/child_zones result in NoValidHosts exception.
        sched = fakes.FakeFilterScheduler()

        fake_context = context.RequestContext('user', 'project')
        request_spec = {'volume_properties': {'project_id': 1,
                                              'size': 1},
                        'volume_type': {'name': 'LVM_iSCSI'},
                        'volume_id': ['fake-id1']}
        self.assertRaises(exception.NoValidHost, sched.schedule_create_volume,
                          fake_context, request_spec, {})

    @mock.patch('cinder.scheduler.host_manager.HostManager.'
                'get_all_host_states')
    def test_create_volume_non_admin(self, _mock_get_all_host_states):
        # Test creating a volume locally using create_volume, passing
        # a non-admin context.  DB actions should work.
        self.was_admin = False

        def fake_get(ctxt):
            # Make sure this is called with admin context, even though
            # we're using user context below.
            self.was_admin = ctxt.is_admin
            return {}

        sched = fakes.FakeFilterScheduler()
        _mock_get_all_host_states.side_effect = fake_get

        fake_context = context.RequestContext('user', 'project')

        request_spec = {'volume_properties': {'project_id': 1,
                                              'size': 1},
                        'volume_type': {'name': 'LVM_iSCSI'},
                        'volume_id': ['fake-id1']}
        self.assertRaises(exception.NoValidHost, sched.schedule_create_volume,
                          fake_context, request_spec, {})
        self.assertTrue(self.was_admin)

    @mock.patch('cinder.db.service_get_all_by_topic')
    def test_schedule_happy_day(self, _mock_service_get_all_by_topic):
        # Make sure there's nothing glaringly wrong with _schedule()
        # by doing a happy day pass through.
        sched = fakes.FakeFilterScheduler()
        sched.host_manager = fakes.FakeHostManager()
        fake_context = context.RequestContext('user', 'project',
                                              is_admin=True)

        fakes.mock_host_manager_db_calls(_mock_service_get_all_by_topic)

        request_spec = {'volume_type': {'name': 'LVM_iSCSI'},
                        'volume_properties': {'project_id': 1,
                                              'size': 1}}
        weighed_host = sched._schedule(fake_context, request_spec, {})
        self.assertIsNotNone(weighed_host.obj)
        self.assertTrue(_mock_service_get_all_by_topic.called)

    def test_max_attempts(self):
        self.flags(scheduler_max_attempts=4)

        sched = fakes.FakeFilterScheduler()
        self.assertEqual(4, sched._max_attempts())

    def test_invalid_max_attempts(self):
        self.flags(scheduler_max_attempts=0)

        self.assertRaises(exception.InvalidParameterValue,
                          fakes.FakeFilterScheduler)

    def test_retry_disabled(self):
        # Retry info should not get populated when re-scheduling is off.
        self.flags(scheduler_max_attempts=1)
        sched = fakes.FakeFilterScheduler()

        request_spec = {'volume_type': {'name': 'LVM_iSCSI'},
                        'volume_properties': {'project_id': 1,
                                              'size': 1}}
        filter_properties = {}

        sched._schedule(self.context, request_spec,
                        filter_properties=filter_properties)

        # Should not have retry info in the populated filter properties.
        self.assertNotIn("retry", filter_properties)

    def test_retry_attempt_one(self):
        # Test retry logic on initial scheduling attempt.
        self.flags(scheduler_max_attempts=2)
        sched = fakes.FakeFilterScheduler()

        request_spec = {'volume_type': {'name': 'LVM_iSCSI'},
                        'volume_properties': {'project_id': 1,
                                              'size': 1}}
        filter_properties = {}

        sched._schedule(self.context, request_spec,
                        filter_properties=filter_properties)

        num_attempts = filter_properties['retry']['num_attempts']
        self.assertEqual(1, num_attempts)

    def test_retry_attempt_two(self):
        # Test retry logic when re-scheduling.
        self.flags(scheduler_max_attempts=2)
        sched = fakes.FakeFilterScheduler()

        request_spec = {'volume_type': {'name': 'LVM_iSCSI'},
                        'volume_properties': {'project_id': 1,
                                              'size': 1}}

        retry = dict(num_attempts=1)
        filter_properties = dict(retry=retry)

        sched._schedule(self.context, request_spec,
                        filter_properties=filter_properties)

        num_attempts = filter_properties['retry']['num_attempts']
        self.assertEqual(2, num_attempts)

    def test_retry_exceeded_max_attempts(self):
        # Test for necessary explosion when max retries is exceeded.
        self.flags(scheduler_max_attempts=2)
        sched = fakes.FakeFilterScheduler()

        request_spec = {'volume_type': {'name': 'LVM_iSCSI'},
                        'volume_properties': {'project_id': 1,
                                              'size': 1}}

        retry = dict(num_attempts=2)
        filter_properties = dict(retry=retry)

        self.assertRaises(exception.NoValidHost, sched._schedule, self.context,
                          request_spec, filter_properties=filter_properties)

    def test_add_retry_host(self):
        retry = dict(num_attempts=1, hosts=[])
        filter_properties = dict(retry=retry)
        host = "fakehost"

        sched = fakes.FakeFilterScheduler()
        sched._add_retry_host(filter_properties, host)

        hosts = filter_properties['retry']['hosts']
        self.assertEqual(1, len(hosts))
        self.assertEqual(host, hosts[0])

    def test_post_select_populate(self):
        # Test addition of certain filter props after a node is selected.
        retry = {'hosts': [], 'num_attempts': 1}
        filter_properties = {'retry': retry}
        sched = fakes.FakeFilterScheduler()

        host_state = host_manager.HostState('host')
        host_state.total_capacity_gb = 1024
        sched._post_select_populate_filter_properties(filter_properties,
                                                      host_state)

        self.assertEqual('host',
                         filter_properties['retry']['hosts'][0])

        self.assertEqual(1024, host_state.total_capacity_gb)

    def _host_passes_filters_setup(self, mock_obj):
        sched = fakes.FakeFilterScheduler()
        sched.host_manager = fakes.FakeHostManager()
        fake_context = context.RequestContext('user', 'project',
                                              is_admin=True)

        fakes.mock_host_manager_db_calls(mock_obj)

        return (sched, fake_context)

    @mock.patch('cinder.db.service_get_all_by_topic')
    def test_host_passes_filters_happy_day(self, _mock_service_get_topic):
        """Do a successful pass through of with host_passes_filters()."""
        sched, ctx = self._host_passes_filters_setup(
            _mock_service_get_topic)
        request_spec = {'volume_id': 1,
                        'volume_type': {'name': 'LVM_iSCSI'},
                        'volume_properties': {'project_id': 1,
                                              'size': 1}}
        ret_host = sched.host_passes_filters(ctx, 'host1#lvm1',
                                             request_spec, {})
        self.assertEqual(utils.extract_host(ret_host.host), 'host1')
        self.assertTrue(_mock_service_get_topic.called)

    @mock.patch('cinder.db.service_get_all_by_topic')
    def test_host_passes_filters_default_pool_happy_day(
            self, _mock_service_get_topic):
        """Do a successful pass through of with host_passes_filters()."""
        sched, ctx = self._host_passes_filters_setup(
            _mock_service_get_topic)
        request_spec = {'volume_id': 1,
                        'volume_type': {'name': 'LVM_iSCSI'},
                        'volume_properties': {'project_id': 1,
                                              'size': 1}}
        ret_host = sched.host_passes_filters(ctx, 'host5#_pool0',
                                             request_spec, {})
        self.assertEqual(utils.extract_host(ret_host.host), 'host5')
        self.assertTrue(_mock_service_get_topic.called)

    @mock.patch('cinder.db.service_get_all_by_topic')
    def test_host_passes_filters_no_capacity(self, _mock_service_get_topic):
        """Fail the host due to insufficient capacity."""
        sched, ctx = self._host_passes_filters_setup(
            _mock_service_get_topic)
        request_spec = {'volume_id': 1,
                        'volume_type': {'name': 'LVM_iSCSI'},
                        'volume_properties': {'project_id': 1,
                                              'size': 1024}}
        self.assertRaises(exception.NoValidHost,
                          sched.host_passes_filters,
                          ctx, 'host1#lvm1', request_spec, {})
        self.assertTrue(_mock_service_get_topic.called)

    @mock.patch('cinder.db.service_get_all_by_topic')
    def test_retype_policy_never_migrate_pass(self, _mock_service_get_topic):
        # Retype should pass if current host passes filters and
        # policy=never. host4 doesn't have enough space to hold an additional
        # 200GB, but it is already the host of this volume and should not be
        # counted twice.
        sched, ctx = self._host_passes_filters_setup(
            _mock_service_get_topic)
        extra_specs = {'volume_backend_name': 'lvm4'}
        request_spec = {'volume_id': 1,
                        'volume_type': {'name': 'LVM_iSCSI',
                                        'extra_specs': extra_specs},
                        'volume_properties': {'project_id': 1,
                                              'size': 200,
                                              'host': 'host4#lvm4'}}
        host_state = sched.find_retype_host(ctx, request_spec,
                                            filter_properties={},
                                            migration_policy='never')
        self.assertEqual(utils.extract_host(host_state.host), 'host4')

    @mock.patch('cinder.db.service_get_all_by_topic')
    def test_retype_with_pool_policy_never_migrate_pass(
            self, _mock_service_get_topic):
        # Retype should pass if current host passes filters and
        # policy=never. host4 doesn't have enough space to hold an additional
        # 200GB, but it is already the host of this volume and should not be
        # counted twice.
        sched, ctx = self._host_passes_filters_setup(
            _mock_service_get_topic)
        extra_specs = {'volume_backend_name': 'lvm3'}
        request_spec = {'volume_id': 1,
                        'volume_type': {'name': 'LVM_iSCSI',
                                        'extra_specs': extra_specs},
                        'volume_properties': {'project_id': 1,
                                              'size': 200,
                                              'host': 'host3#lvm3'}}
        host_state = sched.find_retype_host(ctx, request_spec,
                                            filter_properties={},
                                            migration_policy='never')
        self.assertEqual(host_state.host, 'host3#lvm3')

    @mock.patch('cinder.db.service_get_all_by_topic')
    def test_retype_policy_never_migrate_fail(self, _mock_service_get_topic):
        # Retype should fail if current host doesn't pass filters and
        # policy=never.
        sched, ctx = self._host_passes_filters_setup(
            _mock_service_get_topic)
        extra_specs = {'volume_backend_name': 'lvm1'}
        request_spec = {'volume_id': 1,
                        'volume_type': {'name': 'LVM_iSCSI',
                                        'extra_specs': extra_specs},
                        'volume_properties': {'project_id': 1,
                                              'size': 200,
                                              'host': 'host4'}}
        self.assertRaises(exception.NoValidHost, sched.find_retype_host, ctx,
                          request_spec, filter_properties={},
                          migration_policy='never')

    @mock.patch('cinder.db.service_get_all_by_topic')
    def test_retype_policy_demand_migrate_pass(self, _mock_service_get_topic):
        # Retype should pass if current host fails filters but another host
        # is suitable when policy=on-demand.
        sched, ctx = self._host_passes_filters_setup(
            _mock_service_get_topic)
        extra_specs = {'volume_backend_name': 'lvm1'}
        request_spec = {'volume_id': 1,
                        'volume_type': {'name': 'LVM_iSCSI',
                                        'extra_specs': extra_specs},
                        'volume_properties': {'project_id': 1,
                                              'size': 200,
                                              'host': 'host4'}}
        host_state = sched.find_retype_host(ctx, request_spec,
                                            filter_properties={},
                                            migration_policy='on-demand')
        self.assertEqual(utils.extract_host(host_state.host), 'host1')

    @mock.patch('cinder.db.service_get_all_by_topic')
    def test_retype_policy_demand_migrate_fail(self, _mock_service_get_topic):
        # Retype should fail if current host doesn't pass filters and
        # no other suitable candidates exist even if policy=on-demand.
        sched, ctx = self._host_passes_filters_setup(
            _mock_service_get_topic)
        extra_specs = {'volume_backend_name': 'lvm1'}
        request_spec = {'volume_id': 1,
                        'volume_type': {'name': 'LVM_iSCSI',
                                        'extra_specs': extra_specs},
                        'volume_properties': {'project_id': 1,
                                              'size': 2048,
                                              'host': 'host4'}}
        self.assertRaises(exception.NoValidHost, sched.find_retype_host, ctx,
                          request_spec, filter_properties={},
                          migration_policy='on-demand')
