# Copyright (c) 2017-2020 Dell Inc. or its subsidiaries.
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
SimpleCache utility class for Dell EMC PowerFlex (formerly
named Dell EMC VxFlex OS).
"""

import datetime

from oslo_log import log as logging
from oslo_utils import timeutils


LOG = logging.getLogger(__name__)


class SimpleCache(object):

    def __init__(self, name, age_minutes=30):
        self.cache = {}
        self.name = name
        self.age_minutes = age_minutes

    def __contains__(self, key):
        """Checks if a key exists in cache

        :param key: Key for the item being checked.
        :return: True if item exists, otherwise False
        """
        return key in self.cache

    def _remove(self, key):
        """Removes item from the cache

        :param key: Key for the item being removed.
        :return:
        """
        if self.__class__(key):
            del self.cache[key]

    def _validate(self, key):
        """Validate if an item exists and has not expired.

        :param key: Key for the item being requested.
        :return: The value of the related key, or None.
        """
        if key not in self:
            return None
        # make sure the cache has not expired
        entry = self.cache[key]['value']
        now = timeutils.utcnow()
        age = now - self.cache[key]['date']
        if age > datetime.timedelta(minutes=self.age_minutes):
            # if has expired, remove from cache
            LOG.debug("Removing item '%(item)s' from cache '%(name)s' "
                      "due to age",
                      {'item': key,
                       'name': self.name})
            self._remove(key)
            return None

        return entry

    def purge(self, key):
        """Purge an item from the cache, regardless of age

        :param key: Key for the item being removed.
        :return:
        """
        self._remove(key)

    def purge_all(self):
        """Purge all items from the cache, regardless of age

        :return:
        """
        self.cache = {}

    def set_cache_period(self, age_minutes):
        """Define the period of time to cache values for

        :param age_minutes: Number of minutes to cache items for.
        :return:
        """
        self.age_minutes = age_minutes

    def update(self, key, value):
        """Update/Store an item in the cache

        :param key: Key for the item being added.
        :param value: Value to store
        :return:
        """
        LOG.debug("Updating item '%(item)s' in cache '%(name)s'",
                  {'item': key,
                   'name': self.name})
        self.cache[key] = {'date': timeutils.utcnow(),
                           'value': value}

    def get_value(self, key):
        """Returns an item from the cache

        :param key: Key for the item being requested.
        :return: Value of item or None if doesn't exist or expired
        """
        value = self._validate(key)
        if value is None:
            LOG.debug("Item '%(item)s' is not in cache '%(name)s' ",
                      {'item': key,
                       'name': self.name})
        return value
