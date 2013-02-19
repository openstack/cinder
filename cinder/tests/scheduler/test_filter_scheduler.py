# Copyright 2011 OpenStack LLC.
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

from cinder import context
from cinder import exception
from cinder import test

from cinder.openstack.common.scheduler import weights
from cinder.scheduler import filter_scheduler
from cinder.scheduler import host_manager
from cinder.tests.scheduler import fakes
from cinder.tests.scheduler import test_scheduler
from cinder.tests import utils as test_utils


def fake_get_filtered_hosts(hosts, filter_properties):
    return list(hosts)


class FilterSchedulerTestCase(test_scheduler.SchedulerTestCase):
    """Test case for Filter Scheduler."""

    driver_cls = filter_scheduler.FilterScheduler

    @test.skip_if(not test_utils.is_cinder_installed(),
                  'Test requires Cinder installed (try setup.py develop')
    def test_create_volume_no_hosts(self):
        """
        Ensure empty hosts & child_zones result in NoValidHosts exception.
        """
        def _fake_empty_call_zone_method(*args, **kwargs):
            return []

        sched = fakes.FakeFilterScheduler()

        fake_context = context.RequestContext('user', 'project')
        request_spec = {'volume_properties': {'project_id': 1,
                                              'size': 1},
                        'volume_type': {'name': 'LVM_iSCSI'},
                        'volume_id': ['fake-id1']}
        self.assertRaises(exception.NoValidHost, sched.schedule_create_volume,
                          fake_context, request_spec, {})

    @test.skip_if(not test_utils.is_cinder_installed(),
                  'Test requires Cinder installed (try setup.py develop')
    def test_create_volume_non_admin(self):
        """Test creating an instance locally using run_instance, passing
        a non-admin context.  DB actions should work."""
        self.was_admin = False

        def fake_get(context, *args, **kwargs):
            # make sure this is called with admin context, even though
            # we're using user context below
            self.was_admin = context.is_admin
            return {}

        sched = fakes.FakeFilterScheduler()
        self.stubs.Set(sched.host_manager, 'get_all_host_states', fake_get)

        fake_context = context.RequestContext('user', 'project')

        request_spec = {'volume_properties': {'project_id': 1,
                                              'size': 1},
                        'volume_type': {'name': 'LVM_iSCSI'},
                        'volume_id': ['fake-id1']}
        self.assertRaises(exception.NoValidHost, sched.schedule_create_volume,
                          fake_context, request_spec, {})
        self.assertTrue(self.was_admin)

    @test.skip_if(not test_utils.is_cinder_installed(),
                  'Test requires Cinder installed (try setup.py develop')
    def test_schedule_happy_day(self):
        """Make sure there's nothing glaringly wrong with _schedule()
        by doing a happy day pass through."""

        self.next_weight = 1.0

        def _fake_weigh_objects(_self, functions, hosts, options):
            self.next_weight += 2.0
            host_state = hosts[0]
            return [weights.WeighedHost(host_state, self.next_weight)]

        sched = fakes.FakeFilterScheduler()
        fake_context = context.RequestContext('user', 'project',
                                              is_admin=True)

        self.stubs.Set(sched.host_manager, 'get_filtered_hosts',
                       fake_get_filtered_hosts)
        self.stubs.Set(weights.HostWeightHandler,
                       'get_weighed_objects', _fake_weigh_objects)
        fakes.mox_host_manager_db_calls(self.mox, fake_context)

        request_spec = {'volume_type': {'name': 'LVM_iSCSI'},
                        'volume_properties': {'project_id': 1,
                                              'size': 1}}
        self.mox.ReplayAll()
        weighed_host = sched._schedule(fake_context, request_spec, {})
        self.assertTrue(weighed_host.obj is not None)

    def test_max_attempts(self):
        self.flags(scheduler_max_attempts=4)

        sched = fakes.FakeFilterScheduler()
        self.assertEqual(4, sched._max_attempts())

    def test_invalid_max_attempts(self):
        self.flags(scheduler_max_attempts=0)

        self.assertRaises(exception.InvalidParameterValue,
                          fakes.FakeFilterScheduler)

    @test.skip_if(not test_utils.is_cinder_installed(),
                  'Test requires Cinder installed (try setup.py develop')
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

        # should not have retry info in the populated filter properties:
        self.assertFalse("retry" in filter_properties)

    @test.skip_if(not test_utils.is_cinder_installed(),
                  'Test requires Cinder installed (try setup.py develop')
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

    @test.skip_if(not test_utils.is_cinder_installed(),
                  'Test requires Cinder installed (try setup.py develop')
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
