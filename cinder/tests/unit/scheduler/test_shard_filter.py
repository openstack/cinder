# Copyright 2020 SAP SE  # All Rights Reserved.
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
import time
from unittest import mock

from cinder import context
from cinder.tests.unit import fake_constants
from cinder.tests.unit.scheduler import fakes
from cinder.tests.unit.scheduler.test_host_filters \
    import BackendFiltersTestCase

VMWARE_VENDOR = 'VMware'


class ShardFilterTestCase(BackendFiltersTestCase):

    def setUp(self):
        super(ShardFilterTestCase, self).setUp()
        self.filt_cls = self.class_map['ShardFilter']()
        self.filt_cls._PROJECT_SHARD_CACHE = {
            'foo': ['vc-a-0', 'vc-b-0'],
            'last_modified': time.time()
        }
        self.props = {
            'request_spec': {
                'volume_properties': {
                    'project_id': 'foo'
                }
            }
        }
        self.context = context.RequestContext(fake_constants.USER_ID,
                                              fake_constants.PROJECT_ID)

    @mock.patch('cinder.scheduler.filters.shard_filter.'
                'ShardFilter._update_cache')
    def test_get_shards_cache_timeout(self, mock_update_cache):
        def set_cache():
            self.filt_cls._PROJECT_SHARD_CACHE = {
                'foo': ['vc-a-1']
            }
        mock_update_cache.side_effect = set_cache

        project_id = 'foo'
        mod = time.time() - self.filt_cls._PROJECT_SHARD_CACHE_RETENTION_TIME

        self.assertEqual(self.filt_cls._get_shards(project_id),
                         ['vc-a-0', 'vc-b-0'])

        self.filt_cls._PROJECT_SHARD_CACHE['last_modified'] = mod
        self.assertEqual(self.filt_cls._get_shards(project_id), ['vc-a-1'])

    @mock.patch('cinder.scheduler.filters.shard_filter.'
                'ShardFilter._update_cache')
    def test_get_shards_project_not_included(self, mock_update_cache):
        def set_cache():
            self.filt_cls._PROJECT_SHARD_CACHE = {
                'bar': ['vc-a-1', 'vc-b-0']
            }
        mock_update_cache.side_effect = set_cache

        self.assertEqual(self.filt_cls._get_shards('bar'),
                         ['vc-a-1', 'vc-b-0'])
        mock_update_cache.assert_called_once()

    @mock.patch('cinder.scheduler.filters.shard_filter.'
                'ShardFilter._update_cache')
    def test_shard_project_not_found(self, mock_update_cache):
        caps = {'vcenter-shard': 'vc-a-1'}
        self.props['request_spec']['volume_properties']['project_id'] = 'bar'
        host = fakes.FakeBackendState('host1',
                                      {'capabilities': caps,
                                       'vendor_name': VMWARE_VENDOR})
        self.backend_no_pass(host, self.props)

    def test_snapshot(self):
        snap_props = {
            'request_spec': {
                'snapshot_id': 'asdf',
                'volume_properties': {'size': 7}
            }
        }
        caps = {'vcenter-shard': 'vc-a-1'}
        host = fakes.FakeBackendState('host1',
                                      {'capabilities': caps,
                                       'vendor_name': VMWARE_VENDOR})
        self.backend_passes(host, snap_props)

    def test_snapshot_None(self):
        snap_props = {
            'request_spec': {
                'snapshot_id': None,
                'volume_properties': {'size': 7}
            }
        }
        caps = {'vcenter-shard': 'vc-a-1'}
        host = fakes.FakeBackendState('host1',
                                      {'capabilities': caps,
                                       'vendor_name': VMWARE_VENDOR})
        self.backend_no_pass(host, snap_props)

    def test_shard_project_no_shards(self):
        caps = {'vcenter-shard': 'vc-a-1'}
        self.filt_cls._PROJECT_SHARD_CACHE['foo'] = []
        host = fakes.FakeBackendState('host1',
                                      {'capabilities': caps,
                                       'vendor_name': VMWARE_VENDOR})
        self.backend_no_pass(host, self.props)

    def test_backend_without_shard(self):
        host = fakes.FakeBackendState('host1', {'vendor_name': VMWARE_VENDOR})
        self.backend_no_pass(host, self.props)

    def test_backend_shards_dont_match(self):
        caps = {'vcenter-shard': 'vc-a-1'}
        host = fakes.FakeBackendState('host1',
                                      {'capabilities': caps,
                                       'vendor_name': VMWARE_VENDOR})
        self.backend_no_pass(host, self.props)

    def test_backend_shards_match(self):
        caps = {'vcenter-shard': 'vc-b-0'}
        host = fakes.FakeBackendState('host1',
                                      {'capabilities': caps,
                                       'vendor_name': VMWARE_VENDOR})
        self.backend_passes(host, self.props)

    def test_shard_override_matches(self):
        caps = {'vcenter-shard': 'vc-a-1'}
        host = fakes.FakeBackendState('host1',
                                      {'capabilities': caps,
                                       'vendor_name': VMWARE_VENDOR})
        self.props['scheduler_hints'] = {'vcenter-shard': 'vc-a-1'}
        self.backend_passes(host, self.props)

    def test_shard_override_no_match(self):
        caps = {'vcenter-shard': 'vc-a-0'}
        host = fakes.FakeBackendState('host1',
                                      {'capabilities': caps,
                                       'vendor_name': VMWARE_VENDOR})
        self.props['scheduler_hints'] = {'vcenter-shard': 'vc-a-1'}
        self.backend_no_pass(host, self.props)

    def test_shard_override_no_data(self):
        caps = {'vcenter-shard': 'vc-a-0'}
        host = fakes.FakeBackendState('host1',
                                      {'capabilities': caps,
                                       'vendor_name': VMWARE_VENDOR})
        self.props['scheduler_hints'] = {'vcenter-shard': None}
        self.backend_no_pass(host, self.props)

    def test_sharding_enabled_any_backend_match(self):
        self.filt_cls._PROJECT_SHARD_CACHE['baz'] = ['sharding_enabled']
        self.props['request_spec']['volume_properties']['project_id'] = 'baz'
        caps = {'vcenter-shard': 'vc-a-0'}
        host = fakes.FakeBackendState('host1',
                                      {'capabilities': caps,
                                       'vendor_name': VMWARE_VENDOR})
        self.backend_passes(host, self.props)

    def test_sharding_enabled_and_single_shard_any_backend_match(self):
        self.filt_cls._PROJECT_SHARD_CACHE['baz'] = ['sharding_enabled',
                                                     'vc-a-1']
        self.props['request_spec']['volume_properties']['project_id'] = 'baz'
        caps = {'vcenter-shard': 'vc-a-0'}
        host = fakes.FakeBackendState('host1',
                                      {'capabilities': caps,
                                       'vendor_name': VMWARE_VENDOR})
        self.backend_passes(host, self.props)

    def test_scheduler_hints_override_sharding_enabled(self):
        self.filt_cls._PROJECT_SHARD_CACHE['baz'] = ['sharding_enabled']
        self.props['scheduler_hints'] = {'vcenter-shard': 'vc-a-1'}
        self.props['request_spec']['volume_properties']['project_id'] = 'baz'
        caps0 = {'vcenter-shard': 'vc-a-0'}
        host = fakes.FakeBackendState('host0',
                                      {'capabilities': caps0,
                                       'vendor_name': VMWARE_VENDOR})
        self.backend_no_pass(host, self.props)
        caps1 = {'vcenter-shard': 'vc-a-1'}
        host = fakes.FakeBackendState('host1',
                                      {'capabilities': caps1,
                                       'vendor_name': VMWARE_VENDOR})
        self.backend_passes(host, self.props)

    def test_noop_for_find_backend_by_connector_with_hint(self):
        """Check if we pass any backend

        If the operation we're scheduling for is find_backend_for_connector,
        we do not look at the shards but pass through every backend, because
        this tries to move a volume towards where a server is during attach and
        we always want that to succeed. Shards are supposed to help decision
        making when we don't know where the volume will be attached.
        """
        caps = {'vcenter-shard': 'vc-a-0'}
        host = fakes.FakeBackendState('host1',
                                      {'capabilities': caps,
                                       'vendor_name': VMWARE_VENDOR})
        self.props['scheduler_hints'] = {'vcenter-shard': 'vc-a-1'}
        self.props['request_spec']['operation'] = 'find_backend_for_connector'
        self.backend_passes(host, self.props)

    def test_noop_for_find_backend_by_connector_without_hint(self):
        """Check if we pass any backend

        If the operation we're scheduling for is find_backend_for_connector,
        we do not look at the shards but pass through every backend, because
        this tries to move a volume towards where a server is during attach and
        we always want that to succeed. Shards are supposed to help decision
        making when we don't know where the volume will be attached.
        """
        self.filt_cls._PROJECT_SHARD_CACHE['baz'] = ['vc-a-1']
        caps = {'vcenter-shard': 'vc-a-0'}
        host = fakes.FakeBackendState('host1',
                                      {'capabilities': caps,
                                       'vendor_name': VMWARE_VENDOR})
        self.props['request_spec']['operation'] = 'find_backend_for_connector'
        self.backend_passes(host, self.props)

    @mock.patch('cinder.context.get_admin_context')
    @mock.patch('cinder.db.get_host_by_volume_metadata')
    def test_same_shard_for_k8s_volumes(self, mock_get_hosts,
                                        mock_get_context):
        CSI_KEY = 'cinder.csi.openstack.org/cluster'
        all_backends = [
            fakes.FakeBackendState(
                'volume-vc-a-0@backend#pool1',
                {'capabilities': {'vcenter-shard': 'vc-a-0'},
                 'vendor_name': VMWARE_VENDOR}),
            fakes.FakeBackendState(
                'volume-vc-a-1@backend#pool2',
                {'capabilities': {'vcenter-shard': 'vc-a-1'},
                 'vendor_name': VMWARE_VENDOR}),
        ]
        mock_get_context.return_value = self.context
        fake_meta = {
            CSI_KEY: 'cluster-1',
        }
        mock_get_hosts.return_value = 'volume-vc-a-1'
        self.filt_cls._PROJECT_SHARD_CACHE['baz'] = ['sharding_enabled',
                                                     'vc-a-1']
        filter_props = dict(self.props)
        filter_props['request_spec']['volume_properties'].update({
            'project_id': 'baz',
            'metadata': fake_meta
        })
        filter_props['request_spec']['resource_properties'] = {
            'availability_zone': 'az-1'
        }

        filtered = self.filt_cls.filter_all(all_backends, filter_props)

        mock_get_hosts.assert_called_once_with(
            key=CSI_KEY, value=fake_meta[CSI_KEY], filters={
                'availability_zone': 'az-1'
            })
        self.assertEqual(len(filtered), 1)
        self.assertEqual('volume-vc-a-1@backend#pool2', filtered[0].host)

    def backend_passes(self, backend, filter_properties):
        filtered = self.filt_cls.filter_all([backend], filter_properties)
        self.assertEqual(backend, filtered[0])

    def backend_no_pass(self, backend, filter_properties):
        filtered = self.filt_cls.filter_all([backend], filter_properties)
        self.assertEqual(0, len(filtered))
