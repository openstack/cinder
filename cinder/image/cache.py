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

from pytz import timezone
import six

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import timeutils

from cinder import objects
from cinder import rpc
from cinder import utils

CONF = cfg.CONF

LOG = logging.getLogger(__name__)


class ImageVolumeCache(object):
    def __init__(self, db, volume_api, max_cache_size_gb=0,
                 max_cache_size_count=0):
        self.db = db
        self.volume_api = volume_api
        self.max_cache_size_gb = int(max_cache_size_gb)
        self.max_cache_size_count = int(max_cache_size_count)
        self.notifier = rpc.get_notifier('volume', CONF.host)

    def get_by_image_volume(self, context, volume_id):
        return self.db.image_volume_cache_get_by_volume_id(context, volume_id)

    def evict(self, context, cache_entry):
        LOG.debug('Evicting image cache entry: %(entry)s.',
                  {'entry': self._entry_to_str(cache_entry)})
        self.db.image_volume_cache_delete(context, cache_entry['volume_id'])
        self._notify_cache_eviction(context, cache_entry['image_id'],
                                    cache_entry['host'])

    @staticmethod
    def _get_query_filters(volume_ref):
        if volume_ref.is_clustered:
            return {'cluster_name': volume_ref.cluster_name}
        return {'host': volume_ref.host}

    def get_entry(self, context, volume_ref, image_id, image_meta):
        cache_entry = self.db.image_volume_cache_get_and_update_last_used(
            context,
            image_id,
            **self._get_query_filters(volume_ref)
        )

        if cache_entry:
            LOG.debug('Found image-volume cache entry: %(entry)s.',
                      {'entry': self._entry_to_str(cache_entry)})

            if self._should_update_entry(cache_entry, image_meta):
                LOG.debug('Image-volume cache entry is out-dated, evicting: '
                          '%(entry)s.',
                          {'entry': self._entry_to_str(cache_entry)})
                self._delete_image_volume(context, cache_entry)
                cache_entry = None

        if cache_entry:
            self._notify_cache_hit(context, cache_entry['image_id'],
                                   cache_entry['host'])
        else:
            self._notify_cache_miss(context, image_id,
                                    volume_ref['host'])
        return cache_entry

    def create_cache_entry(self, context, volume_ref, image_id, image_meta):
        """Create a new cache entry for an image.

        This assumes that the volume described by volume_ref has already been
        created and is in an available state.
        """
        LOG.debug('Creating new image-volume cache entry for image '
                  '%(image_id)s on %(service)s',
                  {'image_id': image_id,
                   'service': volume_ref.service_topic_queue})

        # When we are creating an image from a volume the updated_at field
        # will be a unicode representation of the datetime. In that case
        # we just need to parse it into one. If it is an actual datetime
        # we want to just grab it as a UTC naive datetime.
        image_updated_at = image_meta['updated_at']
        if isinstance(image_updated_at, six.string_types):
            image_updated_at = timeutils.parse_strtime(image_updated_at)
        else:
            image_updated_at = image_updated_at.astimezone(timezone('UTC'))

        cache_entry = self.db.image_volume_cache_create(
            context,
            volume_ref.host,
            volume_ref.cluster_name,
            image_id,
            image_updated_at.replace(tzinfo=None),
            volume_ref.id,
            volume_ref.size
        )

        LOG.debug('New image-volume cache entry created: %(entry)s.',
                  {'entry': self._entry_to_str(cache_entry)})
        return cache_entry

    def ensure_space(self, context, volume):
        """Makes room for a volume cache entry.

        Returns True if successful, false otherwise.
        """

        # Check to see if the cache is actually limited.
        if self.max_cache_size_gb == 0 and self.max_cache_size_count == 0:
            return True

        # Make sure that we can potentially fit the image in the cache
        # and bail out before evicting everything else to try and make
        # room for it.
        if (self.max_cache_size_gb != 0 and
                volume.size > self.max_cache_size_gb):
            return False

        # Assume the entries are ordered by most recently used to least used.
        entries = self.db.image_volume_cache_get_all(
            context,
            **self._get_query_filters(volume))

        current_count = len(entries)

        current_size = 0
        for entry in entries:
            current_size += entry['size']

        # Add values for the entry we intend to create.
        current_size += volume.size
        current_count += 1

        LOG.debug('Image-volume cache for %(service)s current_size (GB) = '
                  '%(size_gb)s (max = %(max_gb)s), current count = %(count)s '
                  '(max = %(max_count)s).',
                  {'service': volume.service_topic_queue,
                   'size_gb': current_size,
                   'max_gb': self.max_cache_size_gb,
                   'count': current_count,
                   'max_count': self.max_cache_size_count})

        while ((current_size > self.max_cache_size_gb
               or current_count > self.max_cache_size_count)
               and len(entries)):
            entry = entries.pop()
            LOG.debug('Reclaiming image-volume cache space; removing cache '
                      'entry %(entry)s.', {'entry': self._entry_to_str(entry)})
            self._delete_image_volume(context, entry)
            current_size -= entry['size']
            current_count -= 1
            LOG.debug('Image-volume cache for %(service)s new size (GB) = '
                      '%(size_gb)s, new count = %(count)s.',
                      {'service': volume.service_topic_queue,
                       'size_gb': current_size,
                       'count': current_count})

        # It is only possible to not free up enough gb, we will always be able
        # to free enough count. This is because 0 means unlimited which means
        # it is guaranteed to be >0 if limited, and we can always delete down
        # to 0.
        if self.max_cache_size_gb > 0:
            if current_size > self.max_cache_size_gb > 0:
                LOG.warning('Image-volume cache for %(service)s does '
                            'not have enough space (GB).',
                            {'service': volume.service_topic_queue})
                return False

        return True

    @utils.if_notifications_enabled
    def _notify_cache_hit(self, context, image_id, host):
        self._notify_cache_action(context, image_id, host, 'hit')

    @utils.if_notifications_enabled
    def _notify_cache_miss(self, context, image_id, host):
        self._notify_cache_action(context, image_id, host, 'miss')

    @utils.if_notifications_enabled
    def _notify_cache_eviction(self, context, image_id, host):
        self._notify_cache_action(context, image_id, host, 'evict')

    @utils.if_notifications_enabled
    def _notify_cache_action(self, context, image_id, host, action):
        data = {
            'image_id': image_id,
            'host': host,
        }
        LOG.debug('ImageVolumeCache notification: action=%(action)s'
                  ' data=%(data)s.', {'action': action, 'data': data})
        self.notifier.info(context, 'image_volume_cache.%s' % action, data)

    def _delete_image_volume(self, context, cache_entry):
        """Delete a volume and remove cache entry."""
        volume = objects.Volume.get_by_id(context, cache_entry['volume_id'])

        # Delete will evict the cache entry.
        self.volume_api.delete(context, volume)

    def _should_update_entry(self, cache_entry, image_meta):
        """Ensure that the cache entry image data is still valid."""
        image_updated_utc = (image_meta['updated_at']
                             .astimezone(timezone('UTC')))
        cache_updated_utc = (cache_entry['image_updated_at']
                             .replace(tzinfo=timezone('UTC')))

        LOG.debug('Image-volume cache entry image_update_at = %(entry_utc)s, '
                  'requested image updated_at = %(image_utc)s.',
                  {'entry_utc': six.text_type(cache_updated_utc),
                   'image_utc': six.text_type(image_updated_utc)})

        return image_updated_utc != cache_updated_utc

    def _entry_to_str(self, cache_entry):
        return six.text_type({
            'id': cache_entry['id'],
            'image_id': cache_entry['image_id'],
            'volume_id': cache_entry['volume_id'],
            'host': cache_entry['host'],
            'size': cache_entry['size'],
            'image_updated_at': cache_entry['image_updated_at'],
            'last_used': cache_entry['last_used'],
        })
