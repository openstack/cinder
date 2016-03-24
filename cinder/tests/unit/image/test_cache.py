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
import mock

from oslo_utils import timeutils

from cinder import context as ctxt
from cinder.image import cache as image_cache
from cinder import test


class ImageVolumeCacheTestCase(test.TestCase):

    def setUp(self):
        super(ImageVolumeCacheTestCase, self).setUp()
        self.mock_db = mock.Mock()
        self.mock_volume_api = mock.Mock()
        self.context = ctxt.get_admin_context()

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

    def test_get_entry(self):
        cache = self._build_cache()
        entry = self._build_entry()
        volume_ref = {
            'host': 'foo@bar#whatever'
        }
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
        found_entry = cache.get_entry(self.context,
                                      volume_ref,
                                      entry['image_id'],
                                      image_meta)
        self.assertDictMatch(entry, found_entry)
        (self.mock_db.
         image_volume_cache_get_and_update_last_used.assert_called_once_with)(
            self.context,
            entry['image_id'],
            volume_ref['host']
        )

        msg = self.notifier.notifications[0]
        self.assertEqual('image_volume_cache.hit', msg['event_type'])
        self.assertEqual('INFO', msg['priority'])
        self.assertEqual(entry['host'], msg['payload']['host'])
        self.assertEqual(entry['image_id'], msg['payload']['image_id'])
        self.assertEqual(1, len(self.notifier.notifications))

    def test_get_entry_not_exists(self):
        cache = self._build_cache()
        volume_ref = {
            'host': 'foo@bar#whatever'
        }
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
                                      volume_ref,
                                      image_id,
                                      image_meta)

        self.assertIsNone(found_entry)

        msg = self.notifier.notifications[0]
        self.assertEqual('image_volume_cache.miss', msg['event_type'])
        self.assertEqual('INFO', msg['priority'])
        self.assertEqual(volume_ref['host'], msg['payload']['host'])
        self.assertEqual(image_id, msg['payload']['image_id'])
        self.assertEqual(1, len(self.notifier.notifications))

    def test_get_entry_needs_update(self):
        cache = self._build_cache()
        entry = self._build_entry()
        volume_ref = {
            'host': 'foo@bar#whatever'
        }
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
        mock_volume = mock.Mock()
        self.mock_db.volume_get.return_value = mock_volume

        found_entry = cache.get_entry(self.context,
                                      volume_ref,
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
        self.assertEqual(volume_ref['host'], msg['payload']['host'])
        self.assertEqual(entry['image_id'], msg['payload']['image_id'])
        self.assertEqual(1, len(self.notifier.notifications))

    def test_create_cache_entry(self):
        cache = self._build_cache()
        entry = self._build_entry()
        volume_ref = {
            'id': entry['volume_id'],
            'host': entry['host'],
            'size': entry['size']
        }
        image_meta = {
            'updated_at': entry['image_updated_at']
        }
        self.mock_db.image_volume_cache_create.return_value = entry
        created_entry = cache.create_cache_entry(self.context,
                                                 volume_ref,
                                                 entry['image_id'],
                                                 image_meta)
        self.assertEqual(entry, created_entry)
        self.mock_db.image_volume_cache_create.assert_called_once_with(
            self.context,
            entry['host'],
            entry['image_id'],
            entry['image_updated_at'].replace(tzinfo=None),
            entry['volume_id'],
            entry['size']
        )

    def test_ensure_space_unlimited(self):
        cache = self._build_cache(max_gb=0, max_count=0)
        host = 'foo@bar#whatever'
        has_space = cache.ensure_space(self.context, 0, host)
        self.assertTrue(has_space)

        has_space = cache.ensure_space(self.context, 500, host)
        self.assertTrue(has_space)

    def test_ensure_space_no_entries(self):
        cache = self._build_cache(max_gb=100, max_count=10)
        host = 'foo@bar#whatever'
        self.mock_db.image_volume_cache_get_all_for_host.return_value = []

        has_space = cache.ensure_space(self.context, 5, host)
        self.assertTrue(has_space)

        has_space = cache.ensure_space(self.context, 101, host)
        self.assertFalse(has_space)

    def test_ensure_space_need_gb(self):
        cache = self._build_cache(max_gb=30, max_count=10)
        mock_delete = mock.patch.object(cache, '_delete_image_volume').start()
        host = 'foo@bar#whatever'

        entries = []
        entry1 = self._build_entry(size=12)
        entries.append(entry1)
        entry2 = self._build_entry(size=5)
        entries.append(entry2)
        entry3 = self._build_entry(size=10)
        entries.append(entry3)
        self.mock_db.image_volume_cache_get_all_for_host.return_value = entries

        has_space = cache.ensure_space(self.context, 15, host)
        self.assertTrue(has_space)
        self.assertEqual(2, mock_delete.call_count)
        mock_delete.assert_any_call(self.context, entry2)
        mock_delete.assert_any_call(self.context, entry3)

    def test_ensure_space_need_count(self):
        cache = self._build_cache(max_gb=30, max_count=2)
        mock_delete = mock.patch.object(cache, '_delete_image_volume').start()
        host = 'foo@bar#whatever'

        entries = []
        entry1 = self._build_entry(size=10)
        entries.append(entry1)
        entry2 = self._build_entry(size=5)
        entries.append(entry2)
        self.mock_db.image_volume_cache_get_all_for_host.return_value = entries

        has_space = cache.ensure_space(self.context, 12, host)
        self.assertTrue(has_space)
        self.assertEqual(1, mock_delete.call_count)
        mock_delete.assert_any_call(self.context, entry2)

    def test_ensure_space_need_gb_and_count(self):
        cache = self._build_cache(max_gb=30, max_count=3)
        mock_delete = mock.patch.object(cache, '_delete_image_volume').start()
        host = 'foo@bar#whatever'

        entries = []
        entry1 = self._build_entry(size=10)
        entries.append(entry1)
        entry2 = self._build_entry(size=5)
        entries.append(entry2)
        entry3 = self._build_entry(size=12)
        entries.append(entry3)
        self.mock_db.image_volume_cache_get_all_for_host.return_value = entries

        has_space = cache.ensure_space(self.context, 16, host)
        self.assertTrue(has_space)
        self.assertEqual(2, mock_delete.call_count)
        mock_delete.assert_any_call(self.context, entry2)
        mock_delete.assert_any_call(self.context, entry3)

    def test_ensure_space_cant_free_enough_gb(self):
        cache = self._build_cache(max_gb=30, max_count=10)
        mock_delete = mock.patch.object(cache, '_delete_image_volume').start()
        host = 'foo@bar#whatever'

        entries = list(self._build_entry(size=25))
        self.mock_db.image_volume_cache_get_all_for_host.return_value = entries

        has_space = cache.ensure_space(self.context, 50, host)
        self.assertFalse(has_space)
        mock_delete.assert_not_called()
