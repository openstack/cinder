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
"""Tests For Filter Scheduler."""

from unittest import mock

import ddt

from cinder import context
from cinder import exception
from cinder import objects
from cinder.scheduler import filter_scheduler
from cinder.scheduler import host_manager
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit.scheduler import fakes
from cinder.tests.unit.scheduler import test_scheduler
from cinder.volume import volume_utils


@ddt.ddt
class FilterSchedulerTestCase(test_scheduler.SchedulerTestCase):
    """Test case for Filter Scheduler."""

    driver_cls = filter_scheduler.FilterScheduler

    def test_create_group_no_hosts(self):
        # Ensure empty hosts result in NoValidBackend exception.
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
        group_spec = {'group_type': {'name': 'GrpType'},
                      'volume_properties': {'project_id': 1,
                                            'size': 0}}
        self.assertRaises(exception.NoValidBackend,
                          sched.schedule_create_group,
                          fake_context, 'faki-id1', group_spec,
                          request_spec_list, {}, [])

    @ddt.data(
        {'capabilities:consistent_group_snapshot_enabled': '<is> True'},
        {'consistent_group_snapshot_enabled': '<is> True'}
    )
    @mock.patch('cinder.db.service_get_all')
    def test_schedule_group(self, specs, _mock_service_get_all):
        # Make sure _schedule_group() can find host successfully.
        sched = fakes.FakeFilterScheduler()
        sched.host_manager = fakes.FakeHostManager()
        fake_context = context.RequestContext('user', 'project',
                                              is_admin=True)

        fakes.mock_host_manager_db_calls(_mock_service_get_all)

        request_spec = {'volume_properties': {'project_id': 1,
                                              'size': 0},
                        'volume_type': {'name': 'Type1',
                                        'extra_specs': specs}}
        request_spec2 = {'volume_properties': {'project_id': 1,
                                               'size': 0},
                         'volume_type': {'name': 'Type2',
                                         'extra_specs': specs}}
        request_spec_list = [request_spec, request_spec2]
        group_spec = {'group_type': {'name': 'GrpType'},
                      'volume_properties': {'project_id': 1,
                                            'size': 0}}
        weighed_host = sched._schedule_generic_group(fake_context,
                                                     group_spec,
                                                     request_spec_list,
                                                     {}, [])
        self.assertIsNotNone(weighed_host.obj)
        self.assertTrue(_mock_service_get_all.called)

    def test_create_volume_no_hosts(self):
        # Ensure empty hosts/child_zones result in NoValidBackend exception.
        sched = fakes.FakeFilterScheduler()

        fake_context = context.RequestContext('user', 'project')
        request_spec = {'volume_properties': {'project_id': 1,
                                              'size': 1},
                        'volume_type': {'name': 'LVM_iSCSI'},
                        'volume_id': fake.VOLUME_ID}
        request_spec = objects.RequestSpec.from_primitives(request_spec)
        self.assertRaises(exception.NoValidBackend,
                          sched.schedule_create_volume, fake_context,
                          request_spec, {})

    def test_create_volume_no_hosts_invalid_req(self):
        sched = fakes.FakeFilterScheduler()

        fake_context = context.RequestContext('user', 'project')

        # request_spec is missing 'volume_id'
        request_spec = {'volume_properties': {'project_id': 1,
                                              'size': 1},
                        'volume_type': {'name': 'LVM_iSCSI'}}
        request_spec = objects.RequestSpec.from_primitives(request_spec)
        self.assertRaises(exception.NoValidBackend,
                          sched.schedule_create_volume,
                          fake_context,
                          request_spec,
                          {})

    def test_create_volume_no_volume_type(self):
        sched = fakes.FakeFilterScheduler()

        fake_context = context.RequestContext('user', 'project')

        # request_spec is missing 'volume_type'
        request_spec = {'volume_properties': {'project_id': 1,
                                              'size': 1},
                        'volume_id': fake.VOLUME_ID}
        request_spec = objects.RequestSpec.from_primitives(request_spec)
        self.assertRaises(exception.NoValidBackend,
                          sched.schedule_create_volume,
                          fake_context,
                          request_spec,
                          {})

    @mock.patch('cinder.scheduler.host_manager.HostManager.'
                'get_all_backend_states')
    def test_create_volume_non_admin(self, _mock_get_all_backend_states):
        # Test creating a volume locally using create_volume, passing
        # a non-admin context.  DB actions should work.
        self.was_admin = False

        def fake_get(ctxt):
            # Make sure this is called with admin context, even though
            # we're using user context below.
            self.was_admin = ctxt.is_admin
            return {}

        sched = fakes.FakeFilterScheduler()
        _mock_get_all_backend_states.side_effect = fake_get

        fake_context = context.RequestContext('user', 'project')

        request_spec = {'volume_properties': {'project_id': 1,
                                              'size': 1},
                        'volume_type': {'name': 'LVM_iSCSI'},
                        'volume_id': fake.VOLUME_ID}
        request_spec = objects.RequestSpec.from_primitives(request_spec)
        self.assertRaises(exception.NoValidBackend,
                          sched.schedule_create_volume, fake_context,
                          request_spec, {})
        self.assertTrue(self.was_admin)

    @mock.patch('cinder.db.service_get_all')
    def test_schedule_happy_day(self, _mock_service_get_all):
        # Make sure there's nothing glaringly wrong with _schedule()
        # by doing a happy day pass through.
        sched = fakes.FakeFilterScheduler()
        sched.host_manager = fakes.FakeHostManager()
        fake_context = context.RequestContext('user', 'project',
                                              is_admin=True)

        fakes.mock_host_manager_db_calls(_mock_service_get_all)

        request_spec = {'volume_type': {'name': 'LVM_iSCSI'},
                        'volume_properties': {'project_id': 1,
                                              'size': 1}}
        request_spec = objects.RequestSpec.from_primitives(request_spec)
        weighed_host = sched._schedule(fake_context, request_spec, {})
        self.assertIsNotNone(weighed_host.obj)
        self.assertTrue(_mock_service_get_all.called)

    @ddt.data(('host10@BackendA', True),
              ('host10@BackendB#openstack_nfs_1', True),
              ('host10', False))
    @ddt.unpack
    @mock.patch('cinder.db.service_get_all')
    def test_create_volume_host_different_with_resource_backend(
            self, resource_backend, multibackend_with_pools,
            _mock_service_get_all):
        sched = fakes.FakeFilterScheduler()
        sched.host_manager = fakes.FakeHostManager(
            multibackend_with_pools=multibackend_with_pools)
        fakes.mock_host_manager_db_calls(
            _mock_service_get_all, backends_with_pools=multibackend_with_pools)
        fake_context = context.RequestContext('user', 'project')
        request_spec = {'volume_properties': {'project_id': 1,
                                              'size': 1},
                        'volume_type': {'name': 'LVM_iSCSI'},
                        'resource_backend': resource_backend}
        weighed_host = sched._schedule(fake_context, request_spec, {})
        self.assertIsNone(weighed_host)

    @ddt.data(('host1@BackendA', True),
              ('host1@BackendB#openstack_nfs_1', True),
              ('host1', False))
    @ddt.unpack
    @mock.patch('cinder.db.service_get_all')
    def test_create_volume_host_same_as_resource(self, resource_backend,
                                                 multibackend_with_pools,
                                                 _mock_service_get_all):
        # Ensure we don't clear the host whose backend is same as
        # requested backend (ex: create from source-volume/snapshot,
        # or create within a group)
        sched = fakes.FakeFilterScheduler()
        sched.host_manager = fakes.FakeHostManager(
            multibackend_with_pools=multibackend_with_pools)
        fakes.mock_host_manager_db_calls(
            _mock_service_get_all, backends_with_pools=multibackend_with_pools)
        fake_context = context.RequestContext('user', 'project')
        request_spec = {'volume_properties': {'project_id': 1,
                                              'size': 1},
                        'volume_type': {'name': 'LVM_iSCSI'},
                        'resource_backend': resource_backend}
        weighed_host = sched._schedule(fake_context, request_spec, {})
        self.assertIn(resource_backend, weighed_host.obj.host)

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
        request_spec = objects.RequestSpec.from_primitives(request_spec)
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
        request_spec = objects.RequestSpec.from_primitives(request_spec)
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
        request_spec = objects.RequestSpec.from_primitives(request_spec)

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
        request_spec = objects.RequestSpec.from_primitives(request_spec)

        retry = dict(num_attempts=2)
        filter_properties = dict(retry=retry)

        self.assertRaises(exception.NoValidBackend, sched._schedule,
                          self.context, request_spec,
                          filter_properties=filter_properties)

    def test_retry_revert_consumed_capacity(self):
        sched = fakes.FakeFilterScheduler()
        request_spec = {'volume_type': {'name': 'LVM_iSCSI'},
                        'volume_properties': {'project_id': 1,
                                              'size': 2}}
        request_spec = objects.RequestSpec.from_primitives(request_spec)
        retry = dict(num_attempts=1, backends=['fake_backend_name'])
        filter_properties = dict(retry=retry)

        with mock.patch.object(
                sched.host_manager,
                'revert_volume_consumed_capacity') as mock_revert:
            sched._schedule(self.context, request_spec,
                            filter_properties=filter_properties)
            mock_revert.assert_called_once_with('fake_backend_name', 2)

    def test_add_retry_backend(self):
        retry = dict(num_attempts=1, backends=[])
        filter_properties = dict(retry=retry)
        backend = "fakehost"

        sched = fakes.FakeFilterScheduler()
        sched._add_retry_backend(filter_properties, backend)

        backends = filter_properties['retry']['backends']
        self.assertListEqual([backend], backends)

    def test_post_select_populate(self):
        # Test addition of certain filter props after a node is selected.
        retry = {'backends': [], 'num_attempts': 1}
        filter_properties = {'retry': retry}
        sched = fakes.FakeFilterScheduler()

        backend_state = host_manager.BackendState('host', None)
        backend_state.total_capacity_gb = 1024
        sched._post_select_populate_filter_properties(filter_properties,
                                                      backend_state)

        self.assertEqual('host',
                         filter_properties['retry']['backends'][0])

        self.assertEqual(1024, backend_state.total_capacity_gb)

    def _backend_passes_filters_setup(self, mock_obj):
        sched = fakes.FakeFilterScheduler()
        sched.host_manager = fakes.FakeHostManager()
        fake_context = context.RequestContext('user', 'project',
                                              is_admin=True)

        fakes.mock_host_manager_db_calls(mock_obj)

        return (sched, fake_context)

    @ddt.data(None, {'name': 'LVM_iSCSI'})
    @mock.patch('cinder.db.service_get_all')
    def test_backend_passes_filters_happy_day(self, volume_type,
                                              _mock_service_get_topic):
        """Do a successful pass through of with backend_passes_filters()."""
        sched, ctx = self._backend_passes_filters_setup(
            _mock_service_get_topic)
        request_spec = {'volume_id': fake.VOLUME_ID,
                        'volume_type': volume_type,
                        'volume_properties': {'project_id': 1,
                                              'size': 1,
                                              'multiattach': True}}
        request_spec = objects.RequestSpec.from_primitives(request_spec)
        ret_host = sched.backend_passes_filters(ctx, 'host1#lvm1',
                                                request_spec, {})
        self.assertEqual('host1', volume_utils.extract_host(ret_host.host))
        self.assertTrue(_mock_service_get_topic.called)

    @mock.patch('cinder.db.service_get_all')
    def test_backend_passes_filters_default_pool_happy_day(
            self, _mock_service_get_topic):
        """Do a successful pass through of with backend_passes_filters()."""
        sched, ctx = self._backend_passes_filters_setup(
            _mock_service_get_topic)
        request_spec = {'volume_id': fake.VOLUME_ID,
                        'volume_type': {'name': 'LVM_iSCSI'},
                        'volume_properties': {'project_id': 1,
                                              'size': 1}}
        request_spec = objects.RequestSpec.from_primitives(request_spec)
        ret_host = sched.backend_passes_filters(ctx, 'host5#_pool0',
                                                request_spec, {})
        self.assertEqual('host5', volume_utils.extract_host(ret_host.host))
        self.assertTrue(_mock_service_get_topic.called)

    @mock.patch('cinder.db.service_get_all')
    def test_backend_passes_filters_without_pool(self, mock_service_get_all):
        """Do a successful pass through of with backend_passes_filters()."""
        sched, ctx = self._backend_passes_filters_setup(mock_service_get_all)
        request_spec = {'volume_id': fake.VOLUME_ID,
                        'volume_type': {'name': 'LVM_iSCSI'},
                        'volume_properties': {'project_id': 1,
                                              'size': 1}}
        request_spec = objects.RequestSpec.from_primitives(request_spec)
        ret_host = sched.backend_passes_filters(ctx, 'host1', request_spec, {})
        self.assertEqual('host1', volume_utils.extract_host(ret_host.host))
        self.assertTrue(mock_service_get_all.called)

    @mock.patch('cinder.db.service_get_all')
    def test_backend_passes_filters_no_capacity(self, _mock_service_get_topic):
        """Fail the host due to insufficient capacity."""
        sched, ctx = self._backend_passes_filters_setup(
            _mock_service_get_topic)
        request_spec = {'volume_id': fake.VOLUME_ID,
                        'volume_type': {'name': 'LVM_iSCSI'},
                        'volume_properties': {'project_id': 1,
                                              'size': 1024}}
        request_spec = objects.RequestSpec.from_primitives(request_spec)
        self.assertRaises(exception.NoValidBackend,
                          sched.backend_passes_filters,
                          ctx, 'host1#lvm1', request_spec, {})
        self.assertTrue(_mock_service_get_topic.called)

    @mock.patch('cinder.db.service_get_all')
    def test_backend_passes_filters_online_extend_support_happy_day(
            self, _mock_service_get_topic):
        """Do a successful online extend with backend_passes_filters()."""
        sched, ctx = self._backend_passes_filters_setup(
            _mock_service_get_topic)
        request_spec = {'volume_id': fake.VOLUME_ID,
                        'volume_type': {'name': 'LVM_iSCSI'},
                        'volume_properties': {'project_id': 1,
                                              'size': 1,
                                              'attach_status': 'attached'},
                        'operation': 'extend_volume'}
        request_spec = objects.RequestSpec.from_primitives(request_spec)
        # host1#lvm1 has online_extend_support = True
        sched.backend_passes_filters(ctx, 'host1#lvm1', request_spec, {})
        self.assertTrue(_mock_service_get_topic.called)

    @mock.patch('cinder.db.service_get_all')
    def test_backend_passes_filters_no_online_extend_support(
            self, _mock_service_get_topic):
        """Fail the host due to lack of online extend support."""
        sched, ctx = self._backend_passes_filters_setup(
            _mock_service_get_topic)
        request_spec = {'volume_id': fake.VOLUME_ID,
                        'volume_type': {'name': 'LVM_iSCSI'},
                        'volume_properties': {'project_id': 1,
                                              'size': 1,
                                              'attach_status': 'attached'},
                        'operation': 'extend_volume'}
        request_spec = objects.RequestSpec.from_primitives(request_spec)
        # host2#lvm2 has online_extend_support = False
        self.assertRaises(exception.NoValidBackend,
                          sched.backend_passes_filters,
                          ctx, 'host2#lvm2', request_spec, {})
        self.assertTrue(_mock_service_get_topic.called)

    @mock.patch('cinder.db.service_get_all')
    def test_retype_policy_never_migrate_pass(self, _mock_service_get_topic):
        # Retype should pass if current host passes filters and
        # policy=never. host4 doesn't have enough space to hold an additional
        # 200GB, but it is already the host of this volume and should not be
        # counted twice.
        sched, ctx = self._backend_passes_filters_setup(
            _mock_service_get_topic)
        extra_specs = {'volume_backend_name': 'lvm4'}
        request_spec = {'volume_id': fake.VOLUME_ID,
                        'volume_type': {'name': 'LVM_iSCSI',
                                        'extra_specs': extra_specs},
                        'volume_properties': {'project_id': 1,
                                              'size': 200,
                                              'host': 'host4#lvm4'}}
        request_spec = objects.RequestSpec.from_primitives(request_spec)
        host_state = sched.find_retype_backend(ctx, request_spec,
                                               filter_properties={},
                                               migration_policy='never')
        self.assertEqual('host4', volume_utils.extract_host(host_state.host))

    @mock.patch('cinder.db.service_get_all')
    def test_retype_with_pool_policy_never_migrate_pass(
            self, _mock_service_get_topic):
        # Retype should pass if current host passes filters and
        # policy=never. host4 doesn't have enough space to hold an additional
        # 200GB, but it is already the host of this volume and should not be
        # counted twice.
        sched, ctx = self._backend_passes_filters_setup(
            _mock_service_get_topic)
        extra_specs = {'volume_backend_name': 'lvm3'}
        request_spec = {'volume_id': fake.VOLUME_ID,
                        'volume_type': {'name': 'LVM_iSCSI',
                                        'extra_specs': extra_specs},
                        'volume_properties': {'project_id': 1,
                                              'size': 200,
                                              'host': 'host3#lvm3'}}
        request_spec = objects.RequestSpec.from_primitives(request_spec)
        host_state = sched.find_retype_backend(ctx, request_spec,
                                               filter_properties={},
                                               migration_policy='never')
        self.assertEqual('host3#lvm3', host_state.host)

    @mock.patch('cinder.db.service_get_all')
    def test_retype_policy_never_migrate_fail(self, _mock_service_get_topic):
        # Retype should fail if current host doesn't pass filters and
        # policy=never.
        sched, ctx = self._backend_passes_filters_setup(
            _mock_service_get_topic)
        extra_specs = {'volume_backend_name': 'lvm1'}
        request_spec = {'volume_id': fake.VOLUME_ID,
                        'volume_type': {'name': 'LVM_iSCSI',
                                        'extra_specs': extra_specs},
                        'volume_properties': {'project_id': 1,
                                              'size': 200,
                                              'host': 'host4'}}
        request_spec = objects.RequestSpec.from_primitives(request_spec)
        self.assertRaises(exception.NoValidBackend, sched.find_retype_backend,
                          ctx, request_spec, filter_properties={},
                          migration_policy='never')

    @mock.patch('cinder.db.service_get_all')
    def test_retype_policy_demand_migrate_pass(self, _mock_service_get_topic):
        # Retype should pass if current host fails filters but another host
        # is suitable when policy=on-demand.
        sched, ctx = self._backend_passes_filters_setup(
            _mock_service_get_topic)
        extra_specs = {'volume_backend_name': 'lvm1'}
        request_spec = {'volume_id': fake.VOLUME_ID,
                        'volume_type': {'name': 'LVM_iSCSI',
                                        'extra_specs': extra_specs},
                        'volume_properties': {'project_id': 1,
                                              'size': 200,
                                              'host': 'host4'}}
        request_spec = objects.RequestSpec.from_primitives(request_spec)
        host_state = sched.find_retype_backend(ctx, request_spec,
                                               filter_properties={},
                                               migration_policy='on-demand')
        self.assertEqual('host1', volume_utils.extract_host(host_state.host))

    @mock.patch('cinder.db.service_get_all')
    def test_retype_policy_demand_migrate_fail(self, _mock_service_get_topic):
        # Retype should fail if current host doesn't pass filters and
        # no other suitable candidates exist even if policy=on-demand.
        sched, ctx = self._backend_passes_filters_setup(
            _mock_service_get_topic)
        extra_specs = {'volume_backend_name': 'lvm1'}
        request_spec = {'volume_id': fake.VOLUME_ID,
                        'volume_type': {'name': 'LVM_iSCSI',
                                        'extra_specs': extra_specs},
                        'volume_properties': {'project_id': 1,
                                              'size': 2048,
                                              'host': 'host4'}}
        request_spec = objects.RequestSpec.from_primitives(request_spec)
        self.assertRaises(exception.NoValidBackend, sched.find_retype_backend,
                          ctx, request_spec, filter_properties={},
                          migration_policy='on-demand')
