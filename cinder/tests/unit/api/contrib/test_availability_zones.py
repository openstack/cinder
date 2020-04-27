# Copyright (c) 2013 OpenStack Foundation
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

import datetime

from oslo_utils import timeutils

import cinder.api.contrib.availability_zones
import cinder.context
from cinder.tests.unit import test
import cinder.volume.api


created_time = datetime.datetime(2012, 11, 14, 1, 20, 41, 95099)
current_time = timeutils.utcnow()


def list_availability_zones(self):
    return (
        {'name': 'ping', 'available': True},
        {'name': 'pong', 'available': False},
    )


class FakeRequest(object):
    environ = {'cinder.context': cinder.context.get_admin_context()}
    GET = {}


class ControllerTestCase(test.TestCase):

    def setUp(self):
        super(ControllerTestCase, self).setUp()
        self.controller = cinder.api.contrib.availability_zones.Controller()
        self.req = FakeRequest()
        self.mock_object(cinder.volume.api.API,
                         'list_availability_zones',
                         list_availability_zones)

    def test_list_hosts(self):
        """Verify that the volume hosts are returned."""
        actual = self.controller.index(self.req)
        expected = {
            'availabilityZoneInfo': [
                {'zoneName': 'ping', 'zoneState': {'available': True}},
                {'zoneName': 'pong', 'zoneState': {'available': False}},
            ],
        }
        self.assertEqual(expected, actual)
