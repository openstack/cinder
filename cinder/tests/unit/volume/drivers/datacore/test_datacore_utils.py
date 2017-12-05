# Copyright (c) 2017 DataCore Software Corp. All Rights Reserved.
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

"""Unit tests for utilities and helper functions."""

from cinder import test
from cinder.volume.drivers.datacore import utils


class GenericUtilsTestCase(test.TestCase):
    """Tests for the generic utilities and helper functions."""

    def test_build_network_address(self):
        ipv4_address = '127.0.0.1'
        ipv6_address = '::1'
        host_name = 'localhost'
        port = 3498
        self.assertEqual('%s:%s' % (ipv4_address, port),
                         utils.build_network_address(ipv4_address, port))
        self.assertEqual('[%s]:%s' % (ipv6_address, port),
                         utils.build_network_address(ipv6_address, port))
        self.assertEqual('%s:%s' % (host_name, port),
                         utils.build_network_address(host_name, port))

    def test_get_first(self):
        disk_a = {'id': 'disk-a', 'type': 'Single', 'size': 5}
        disk_b = {'id': 'disk-b', 'type': 'Single', 'size': 1}
        disk_c = {'id': 'disk-c', 'type': 'Mirrored', 'size': 5}
        disk_d = {'id': 'disk-d', 'type': 'Single', 'size': 10}
        test_source = [disk_a, disk_b, disk_c, disk_d]

        first = utils.get_first(lambda item: item['id'] == 'disk-c',
                                test_source)
        self.assertEqual(disk_c, first)

        self.assertRaises(StopIteration,
                          utils.get_first,
                          lambda item: item['type'] == 'Dual',
                          test_source)

    def test_get_first_or_default(self):
        disk_a = {'id': 'disk-a', 'type': 'Single', 'size': 5}
        disk_b = {'id': 'disk-b', 'type': 'Single', 'size': 1}
        disk_c = {'id': 'disk-c', 'type': 'Mirrored', 'size': 5}
        disk_d = {'id': 'disk-d', 'type': 'Single', 'size': 10}
        test_source = [disk_a, disk_b, disk_c, disk_d]

        first = utils.get_first_or_default(lambda item: item['size'] == 1,
                                           test_source,
                                           None)
        self.assertEqual(disk_b, first)

        default = utils.get_first_or_default(lambda item: item['size'] == 15,
                                             test_source,
                                             None)
        self.assertIsNone(default)

    def test_get_distinct_by(self):
        disk_a = {'id': 'disk-a', 'type': 'Single', 'size': 5}
        disk_b = {'id': 'disk-b', 'type': 'Single', 'size': 1}
        disk_c = {'id': 'disk-c', 'type': 'Mirrored', 'size': 5}
        disk_d = {'id': 'disk-d', 'type': 'Single', 'size': 10}
        test_source = [disk_a, disk_b, disk_c, disk_d]

        distinct_values = utils.get_distinct_by(lambda item: item['type'],
                                                test_source)
        self.assertEqual([disk_a, disk_c], distinct_values)
