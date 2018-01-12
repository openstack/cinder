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

from tempest.common import waiters
from tempest import config
from tempest.lib.common.utils import data_utils
from tempest.lib.common.utils import test_utils

from cinder.tests.tempest.api.volume import base

CONF = config.CONF


class CinderUnicodeTest(base.BaseVolumeTest):

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
        if 'name' not in kwargs:
            kwargs['name'] = data_utils.rand_name('Volume')

        kwargs['size'] = CONF.volume.volume_size

        volume = cls.volumes_client.create_volume(**kwargs)['volume']
        cls.addClassResourceCleanup(
            cls.volumes_client.wait_for_resource_deletion, volume['id'])
        cls.addClassResourceCleanup(test_utils.call_and_ignore_notfound_exc,
                                    cls.volumes_client.delete_volume,
                                    volume['id'])
        waiters.wait_for_volume_resource_status(cls.volumes_client,
                                                volume['id'],
                                                'available')

        return volume

    def test_create_delete_unicode_volume_name(self):
        """Create a volume with a unicode name and view it."""

        result = self.volumes_client.show_volume(self.volume['id'])
        fetched_volume = result['volume']
        self.assertEqual(fetched_volume['name'],
                         self.volume_name)
