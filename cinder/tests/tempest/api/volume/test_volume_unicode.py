# -*- coding: utf-8 -*-
# Copyright 2016 Red Hat, Inc.
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

from tempest.api.volume import base as volume_base
from tempest.common.utils import data_utils
from tempest.common import waiters
from tempest import config

CONF = config.CONF


class CinderUnicodeTest(volume_base.BaseVolumeTest):

    @classmethod
    def resource_setup(cls):
        super(CinderUnicodeTest, cls).resource_setup()

        # Stick to three-byte unicode here, since four+ byte
        # chars require utf8mb4 database support which may not
        # be configured.
        cls.volume_name = u"CinderUnicodeTest塵㼗‽"
        cls.volume = cls.create_volume_with_args(name=cls.volume_name)

    @classmethod
    def create_volume_with_args(cls, **kwargs):
        name = kwargs['name'] or data_utils.rand_name('Volume')

        name_field = cls.special_fields['name_field']
        kwargs[name_field] = name
        kwargs['size'] = CONF.volume.volume_size

        volume = cls.volumes_client.create_volume(**kwargs)['volume']
        cls.volumes.append(volume)

        waiters.wait_for_volume_status(cls.volumes_client,
                                       volume['id'],
                                       'available')

        return volume

    def test_create_delete_unicode_volume_name(self):
        """Create a volume with a unicode name and view it."""

        result = self.volumes_client.show_volume(self.volumes[0]['id'])
        fetched_volume = result['volume']
        self.assertEqual(fetched_volume[self.special_fields['name_field']],
                         self.volume_name)
