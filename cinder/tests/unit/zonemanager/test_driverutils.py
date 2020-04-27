#    (c) Copyright 2015 Brocade Communications Systems Inc.
#    All Rights Reserved.
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
#

"""Unit tests for friendly zone name."""
import string

import ddt

from cinder.tests.unit import test
from cinder.zonemanager.drivers import driver_utils

TEST_CHAR_SET = string.ascii_letters + string.digits


@ddt.ddt
class TestDriverUtils(test.TestCase):

    @ddt.data('OSHost10010008c7cff523b01AMCEArray20240002ac000a50')
    def test_get_friendly_zone_name_valid_hostname_storagesystem(self, value):
        self.assertEqual(value,
                         driver_utils.get_friendly_zone_name(
                             'initiator-target', "10:00:8c:7c:ff:52:3b:01",
                             "20:24:00:02:ac:00:0a:50", "OS_Host100", 'AMCE'
                             '_Array', "openstack", TEST_CHAR_SET))

    @ddt.data('openstack10008c7cff523b0120240002ac000a50')
    def test_get_friendly_zone_name_hostname_storagesystem_none(self, value):
        self.assertEqual(value,
                         driver_utils.get_friendly_zone_name(
                             'initiator-target', "10:00:8c:7c:ff:52:3b:01",
                             "20:24:00:02:ac:00:0a:50", None, None,
                             "openstack", TEST_CHAR_SET))

    @ddt.data('openstack10008c7cff523b0120240002ac000a50')
    def test_get_friendly_zone_name_storagesystem_none(self, value):
        self.assertEqual(value,
                         driver_utils.get_friendly_zone_name(
                             'initiator-target', "10:00:8c:7c:ff:52:3b:01",
                             "20:24:00:02:ac:00:0a:50", "OS_Host100", None,
                             "openstack", TEST_CHAR_SET))

    @ddt.data('openstack10008c7cff523b0120240002ac000a50')
    def test_get_friendly_zone_name_hostname_none(self, value):
        self.assertEqual(value,
                         driver_utils.get_friendly_zone_name(
                             'initiator-target', "10:00:8c:7c:ff:52:3b:01",
                             "20:24:00:02:ac:00:0a:50", None, "AMCE_Array",
                             "openstack", TEST_CHAR_SET))

    @ddt.data('OSHost10010008c7cff523b01')
    def test_get_friendly_zone_name_initiator_mode(self, value):
        self.assertEqual(value,
                         driver_utils.get_friendly_zone_name(
                             'initiator', "10:00:8c:7c:ff:52:3b:01", None,
                             "OS_Host100", None, "openstack", TEST_CHAR_SET))

    @ddt.data('openstack10008c7cff523b01')
    def test_get_friendly_zone_name_initiator_mode_hostname_none(self, value):
        self.assertEqual(value,
                         driver_utils.get_friendly_zone_name(
                             'initiator', "10:00:8c:7c:ff:52:3b:01", None,
                             None, None, "openstack", TEST_CHAR_SET))

    @ddt.data('OSHost100XXXX10008c7cff523b01AMCEArrayYYYY20240002ac000a50')
    def test_get_friendly_zone_name_storagename_length_too_long(self, value):
        self.assertEqual(value,
                         driver_utils.get_friendly_zone_name(
                             'initiator-target', "10:00:8c:7c:ff:52:3b:01",
                             "20:24:00:02:ac:00:0a:50",
                             "OS_Host100XXXXXXXXXX",
                             "AMCE_ArrayYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYY"
                             "YYYY", "openstack", TEST_CHAR_SET))

    @ddt.data('OSHost100XXXX10008c7cff523b01AMCEArrayYYYY20240002ac000a50')
    def test_get_friendly_zone_name_max_length(self, value):
        self.assertEqual(value,
                         driver_utils.get_friendly_zone_name(
                             'initiator-target', "10:00:8c:7c:ff:52:3b:01",
                             "20:24:00:02:ac:00:0a:50",
                             "OS_Host100XXXXXXXXXX",
                             "AMCE_ArrayYYYYYYYYYY",
                             "openstack", TEST_CHAR_SET))

    @ddt.data('OSHost100XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX10008c7cff523b01')
    def test_get_friendly_zone_name_initiator_mode_hostname_max_length(self,
                                                                       value):
        self.assertEqual(value,
                         driver_utils.get_friendly_zone_name(
                             'initiator', "10:00:8c:7c:ff:52:3b:01", None,
                             'OS_Host100XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX'
                             'XXXXX',
                             None, "openstack", TEST_CHAR_SET))

    @ddt.data('openstack110008c7cff523b0120240002ac000a50')
    def test_get_friendly_zone_name_invalid_characters(self, value):
        self.assertEqual(value,
                         driver_utils.get_friendly_zone_name(
                             'initiator-target', "10:00:8c:7c:ff:52:3b:01",
                             "20:24:00:02:ac:00:0a:50", None, "AMCE_Array",
                             "open-stack*1_", TEST_CHAR_SET))
