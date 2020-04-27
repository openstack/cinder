# Copyright (C) 2015 Pure Storage, Inc.
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

from datetime import timedelta
from unittest import mock

import ddt
from oslo_utils import timeutils

from cinder import context as ctxt
from cinder.db.sqlalchemy import models
from cinder.image import cache as image_cache
from cinder import objects
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import test


@ddt.ddt
class ImageVolumeCacheTestCase(test.TestCase):

    def setUp(self):
        super(ImageVolumeCacheTestCase, self).setUp()
        self.mock_db = mock.Mock()
        self.mock_volume_api = mock.Mock()
        self.context = ctxt.get_admin_context()
        self.volume = models.Volume()
        vol_params = {'id': fake.VOLUME_ID,
                      'host': 'foo@bar#whatever',
                      'cluster_name': 'cluster',
                      'size': 0}
        self.volume.update(vol_params)
        self.volume_ovo = objects.Volume(self.context, **vol_params)

    def _build_cache(self, max_gb=0, max_count=0):
        cache = image_cache.ImageVolumeCache(self.mock_db,
                                             self.mock_volume_api,
                                             max_gb,
                                             max_count)
        cache.notifier = self.notifier
        return cache

    def _build_entry(self, size=10):
        entry = {
            'id': 1,
            'host': 'test@foo#bar',
            'cluster_name': 'cluster@foo#bar',
            'image_id': 'c7a8b8d4-e519-46c7-a0df-ddf1b9b9fff2',
            'image_updated_at': timeutils.utcnow(with_timezone=True),
            'volume_id': '70a599e0-31e7-49b7-b260-868f441e862b',
            'size': size,
            'last_used': timeutils.utcnow(with_timezone=True)
        }
        return entry

    def test_get_by_image_volume(self):
        cache = self._build_cache()
        ret = {'id': 1}
        volume_id = '70a599e0-31e7-49b7-b260-868f441e862b'
        self.mock_db.image_volume_cache_get_by_volume_id.return_value = ret
        entry = cache.get_by_image_volume(self.context, volume_id)
        self.assertEqual(ret, entry)

        self.mock_db.image_volume_cache_get_by_volume_id.return_value = None
        entry = cache.get_by_image_volume(self.context, volume_id)
        self.assertIsNone(entry)

    def test_evict(self):
        cache = self._build_cache()
        entry = self._build_entry()
        cache.evict(self.context, entry)
        self.mock_db.image_volume_cache_delete.assert_called_once_with(
            self.context,
            entry['volume_id']
        )

        msg = self.notifier.notifications[0]
        self.assertEqual('image_volume_cache.evict', msg['event_type'])
        self.assertEqual('INFO', msg['priority'])
        self.assertEqual(entry['host'], msg['payload']['host'])
        self.assertEqual(entry['image_id'], msg['payload']['image_id'])
        self.assertEqual(1, len(self.notifier.notifications))

    @ddt.data(True, False)
    def test_get_entry(self, clustered):
        cache = self._build_cache()
        entry = self._build_entry()
        image_meta = {
            'is_public': True,
            'owner': '70a599e0-31e7-49b7-b260-868f441e862b',
            'properties': {
                'virtual_size': '1.7'
            },
            'updated_at': entry['image_updated_at']
        }
        (self.mock_db.
         image_volume_cache_get_and_update_last_used.return_value) = entry
        if not clustered:
            self.volume_ovo.cluster_name = None
            expect = {'host': self.volume.host}
        else:
            expect = {'cluster_name': self.volume.cluster_name}
        found_entry = cache.get_entry(self.context,
                                      self.volume_ovo,
                                      entry['image_id'],
                                      image_meta)
        self.assertDictEqual(entry, found_entry)
        (self.mock_db.
         image_volume_cache_get_and_update_last_used.assert_called_once_with)(
            self.context,
            entry['image_id'],
            **expect
        )

        msg = self.notifier.notifications[0]
        self.assertEqual('image_volume_cache.hit', msg['event_type'])
        self.assertEqual('INFO', msg['priority'])
        self.assertEqual(entry['host'], msg['payload']['host'])
        self.assertEqual(entry['image_id'], msg['payload']['image_id'])
        self.assertEqual(1, len(self.notifier.notifications))

    def test_get_entry_not_exists(self):
        cache = self._build_cache()
        image_meta = {
            'is_public': True,
            'owner': '70a599e0-31e7-49b7-b260-868f441e862b',
            'properties': {
                'virtual_size': '1.7'
            },
            'updated_at': timeutils.utcnow(with_timezone=True)
        }
        image_id = 'c7a8b8d4-e519-46c7-a0df-ddf1b9b9fff2'
        (self.mock_db.
         image_volume_cache_get_and_update_last_used.return_value) = None

        found_entry = cache.get_entry(self.context,
                                      self.volume_ovo,
                                      image_id,
                                      image_meta)

        self.assertIsNone(found_entry)

        msg = self.notifier.notifications[0]
        self.assertEqual('image_volume_cache.miss', msg['event_type'])
        self.assertEqual('INFO', msg['priority'])
        self.assertEqual(self.volume.host, msg['payload']['host'])
        self.assertEqual(image_id, msg['payload']['image_id'])
        self.assertEqual(1, len(self.notifier.notifications))

    @mock.patch('cinder.objects.Volume.get_by_id')
    def test_get_entry_needs_update(self, mock_volume_by_id):
        cache = self._build_cache()
        entry = self._build_entry()
        image_meta = {
            'is_public': True,
            'owner': '70a599e0-31e7-49b7-b260-868f441e862b',
            'properties': {
                'virtual_size': '1.7'
            },
            'updated_at': entry['image_updated_at'] + timedelta(hours=2)
        }
        (self.mock_db.
         image_volume_cache_get_and_update_last_used.return_value) = entry

        mock_volume = mock.MagicMock()
        mock_volume_by_id.return_value = mock_volume

        found_entry = cache.get_entry(self.context,
                                      self.volume_ovo,
                                      entry['image_id'],
                                      image_meta)

        # Expect that the cache entry is not returned and the image-volume
        # for it is deleted.
        self.assertIsNone(found_entry)
        self.mock_volume_api.delete.assert_called_with(self.context,
                                                       mock_volume)
        msg = self.notifier.notifications[0]
        self.assertEqual('image_volume_cache.miss', msg['event_type'])
        self.assertEqual('INFO', msg['priority'])
        self.assertEqual(self.volume.host, msg['payload']['host'])
        self.assertEqual(entry['image_id'], msg['payload']['image_id'])
        self.assertEqual(1, len(self.notifier.notifications))

    def test_create_cache_entry(self):
        cache = self._build_cache()
        entry = self._build_entry()
        image_meta = {
            'updated_at': entry['image_updated_at']
        }
        self.mock_db.image_volume_cache_create.return_value = entry
        created_entry = cache.create_cache_entry(self.context,
                                                 self.volume_ovo,
                                                 entry['image_id'],
                                                 image_meta)
        self.assertEqual(entry, created_entry)
        self.mock_db.image_volume_cache_create.assert_called_once_with(
            self.context,
            self.volume_ovo.host,
            self.volume_ovo.cluster_name,
            entry['image_id'],
            entry['image_updated_at'].replace(tzinfo=None),
            self.volume_ovo.id,
            self.volume_ovo.size
        )

    def test_ensure_space_unlimited(self):
        cache = self._build_cache(max_gb=0, max_count=0)
        has_space = cache.ensure_space(self.context, self.volume)
        self.assertTrue(has_space)

        self.volume.size = 500
        has_space = cache.ensure_space(self.context, self.volume)
        self.assertTrue(has_space)

    def test_ensure_space_no_entries(self):
        cache = self._build_cache(max_gb=100, max_count=10)
        self.mock_db.image_volume_cache_get_all.return_value = []

        self.volume_ovo.size = 5
        has_space = cache.ensure_space(self.context, self.volume_ovo)
        self.assertTrue(has_space)

        self.volume_ovo.size = 101
        has_space = cache.ensure_space(self.context, self.volume_ovo)
        self.assertFalse(has_space)

    def test_ensure_space_need_gb(self):
        cache = self._build_cache(max_gb=30, max_count=0)
        mock_delete = mock.patch.object(cache, '_delete_image_volume').start()

        entries = []
        entry1 = self._build_entry(size=12)
        entries.append(entry1)
        entry2 = self._build_entry(size=5)
        entries.append(entry2)
        entry3 = self._build_entry(size=10)
        entries.append(entry3)
        self.mock_db.image_volume_cache_get_all.return_value = entries

        self.volume_ovo.size = 15
        has_space = cache.ensure_space(self.context, self.volume_ovo)
        self.assertTrue(has_space)
        self.assertEqual(2, mock_delete.call_count)
        mock_delete.assert_any_call(self.context, entry2)
        mock_delete.assert_any_call(self.context, entry3)
        self.mock_db.image_volume_cache_get_all.assert_called_with(
            self.context, cluster_name=self.volume_ovo.cluster_name)

    def test_ensure_space_need_count(self):
        cache = self._build_cache(max_gb=0, max_count=2)
        mock_delete = mock.patch.object(cache, '_delete_image_volume').start()

        entries = []
        entry1 = self._build_entry(size=10)
        entries.append(entry1)
        entry2 = self._build_entry(size=5)
        entries.append(entry2)
        self.mock_db.image_volume_cache_get_all.return_value = entries

        self.volume_ovo.size = 12
        has_space = cache.ensure_space(self.context, self.volume_ovo)
        self.assertTrue(has_space)
        self.assertEqual(1, mock_delete.call_count)
        mock_delete.assert_any_call(self.context, entry2)

    def test_ensure_space_need_gb_and_count(self):
        cache = self._build_cache(max_gb=30, max_count=3)
        mock_delete = mock.patch.object(cache, '_delete_image_volume').start()

        entries = []
        entry1 = self._build_entry(size=10)
        entries.append(entry1)
        entry2 = self._build_entry(size=5)
        entries.append(entry2)
        entry3 = self._build_entry(size=12)
        entries.append(entry3)
        self.mock_db.image_volume_cache_get_all.return_value = entries

        self.volume_ovo.size = 16
        has_space = cache.ensure_space(self.context, self.volume_ovo)
        self.assertTrue(has_space)
        self.assertEqual(2, mock_delete.call_count)
        mock_delete.assert_any_call(self.context, entry2)
        mock_delete.assert_any_call(self.context, entry3)

    def test_ensure_space_cant_free_enough_gb(self):
        cache = self._build_cache(max_gb=30, max_count=10)
        mock_delete = mock.patch.object(cache, '_delete_image_volume').start()

        entries = list(self._build_entry(size=25))
        self.mock_db.image_volume_cache_get_all.return_value = entries

        self.volume_ovo.size = 50
        has_space = cache.ensure_space(self.context, self.volume_ovo)
        self.assertFalse(has_space)
        mock_delete.assert_not_called()
