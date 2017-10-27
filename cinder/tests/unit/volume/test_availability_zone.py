# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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
"""Test for volume availability zone."""

import datetime
import mock

from oslo_utils import timeutils

from cinder.tests.unit import volume as base
import cinder.volume


class AvailabilityZoneTestCase(base.BaseVolumeTestCase):
    def setUp(self):
        super(AvailabilityZoneTestCase, self).setUp()
        self.get_all = self.patch(
            'cinder.db.service_get_all', autospec=True,
            return_value=[{'availability_zone': 'a', 'disabled': False,
                           'uuid': 'f838f35c-4035-464f-9792-ce60e390c13d'}])

    def test_list_availability_zones_cached(self):
        azs = self.volume_api.list_availability_zones(enable_cache=True)
        self.assertEqual([{"name": 'a', 'available': True}], list(azs))
        self.assertIsNotNone(self.volume_api.availability_zones_last_fetched)
        self.assertTrue(self.get_all.called)
        self.volume_api.list_availability_zones(enable_cache=True)
        self.assertEqual(1, self.get_all.call_count)

    def test_list_availability_zones_cached_and_refresh_on(self):
        azs = self.volume_api.list_availability_zones(enable_cache=True,
                                                      refresh_cache=True)
        self.assertEqual([{"name": 'a', 'available': True}], list(azs))
        time_before = self.volume_api.availability_zones_last_fetched
        self.assertIsNotNone(time_before)
        self.assertEqual(1, self.get_all.call_count)
        self.volume_api.list_availability_zones(enable_cache=True,
                                                refresh_cache=True)
        self.assertTrue(time_before !=
                        self.volume_api.availability_zones_last_fetched)
        self.assertEqual(2, self.get_all.call_count)

    def test_list_availability_zones_no_cached(self):
        azs = self.volume_api.list_availability_zones(enable_cache=False)
        self.assertEqual([{"name": 'a', 'available': True}], list(azs))
        self.assertIsNone(self.volume_api.availability_zones_last_fetched)

        self.get_all.return_value[0]['disabled'] = True
        azs = self.volume_api.list_availability_zones(enable_cache=False)
        self.assertEqual([{"name": 'a', 'available': False}], list(azs))
        self.assertIsNone(self.volume_api.availability_zones_last_fetched)

    @mock.patch('oslo_utils.timeutils.utcnow')
    def test_list_availability_zones_refetched(self, mock_utcnow):
        mock_utcnow.return_value = datetime.datetime.utcnow()
        azs = self.volume_api.list_availability_zones(enable_cache=True)
        self.assertEqual([{"name": 'a', 'available': True}], list(azs))
        self.assertIsNotNone(self.volume_api.availability_zones_last_fetched)
        last_fetched = self.volume_api.availability_zones_last_fetched
        self.assertTrue(self.get_all.called)
        self.volume_api.list_availability_zones(enable_cache=True)
        self.assertEqual(1, self.get_all.call_count)

        # The default cache time is 3600, push past that...
        mock_utcnow.return_value = (timeutils.utcnow() +
                                    datetime.timedelta(0, 3800))
        self.get_all.return_value = [
            {
                'availability_zone': 'a',
                'disabled': False,
                'uuid': 'a3a593da-7f8d-4bb7-8b4c-f2bc1e0b4824',
            },
            {
                'availability_zone': 'b',
                'disabled': False,
                'uuid': '4200b32b-0bf9-436c-86b2-0675f6ac218e',
            },
        ]
        azs = self.volume_api.list_availability_zones(enable_cache=True)
        azs = sorted([n['name'] for n in azs])
        self.assertEqual(['a', 'b'], azs)
        self.assertEqual(2, self.get_all.call_count)
        self.assertGreater(self.volume_api.availability_zones_last_fetched,
                           last_fetched)
        mock_utcnow.assert_called_with()

    def test_list_availability_zones_enabled_service(self):
        def sort_func(obj):
            return obj['name']

        self.get_all.return_value = [
            {'availability_zone': 'ping', 'disabled': 0,
             'uuid': 'a3a593da-7f8d-4bb7-8b4c-f2bc1e0b4824'},
            {'availability_zone': 'ping', 'disabled': 1,
             'uuid': '4200b32b-0bf9-436c-86b2-0675f6ac218e'},
            {'availability_zone': 'pong', 'disabled': 0,
             'uuid': '6d91e7f5-ca17-4e3b-bf4f-19ca77166dd7'},
            {'availability_zone': 'pung', 'disabled': 1,
             'uuid': '18417850-2ca9-43d1-9619-ae16bfb0f655'},
        ]

        volume_api = cinder.volume.api.API()
        azs = volume_api.list_availability_zones()
        azs = sorted(azs, key=sort_func)

        expected = sorted([
            {'name': 'pung', 'available': False},
            {'name': 'pong', 'available': True},
            {'name': 'ping', 'available': True},
        ], key=sort_func)

        self.assertEqual(expected, azs)
