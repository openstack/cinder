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

import mock

from cinder.tests.unit.scheduler import fakes
from cinder.tests.unit.scheduler.test_host_filters \
    import BackendFiltersTestCase


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
        host = fakes.FakeBackendState('host1', {'capabilities': caps})
        self.assertFalse(self.filt_cls.backend_passes(host, self.props))

    def test_shard_project_no_shards(self):
        caps = {'vcenter-shard': 'vc-a-1'}
        self.filt_cls._PROJECT_SHARD_CACHE['foo'] = []
        host = fakes.FakeBackendState('host1', {'capabilities': caps})
        self.assertFalse(self.filt_cls.backend_passes(host, self.props))

    def test_backend_without_shard(self):
        host = fakes.FakeBackendState('host1', {})
        self.assertFalse(self.filt_cls.backend_passes(host, self.props))

    def test_backend_shards_dont_match(self):
        caps = {'vcenter-shard': 'vc-a-1'}
        host = fakes.FakeBackendState('host1', {'capabilities': caps})
        self.assertFalse(self.filt_cls.backend_passes(host, self.props))

    def test_backend_shards_match(self):
        caps = {'vcenter-shard': 'vc-b-0'}
        host = fakes.FakeBackendState('host1', {'capabilities': caps})
        self.assertTrue(self.filt_cls.backend_passes(host, self.props))
