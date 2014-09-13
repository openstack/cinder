# Copyright (c) Clinton Knight
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
Mock unit tests for the NetApp driver utility module
"""

from cinder import test
import cinder.volume.drivers.netapp.utils as na_utils


class NetAppDriverUtilsTestCase(test.TestCase):

    def test_to_bool(self):
        self.assertTrue(na_utils.to_bool(True))
        self.assertTrue(na_utils.to_bool('true'))
        self.assertTrue(na_utils.to_bool('yes'))
        self.assertTrue(na_utils.to_bool('y'))
        self.assertTrue(na_utils.to_bool(1))
        self.assertTrue(na_utils.to_bool('1'))
        self.assertFalse(na_utils.to_bool(False))
        self.assertFalse(na_utils.to_bool('false'))
        self.assertFalse(na_utils.to_bool('asdf'))
        self.assertFalse(na_utils.to_bool('no'))
        self.assertFalse(na_utils.to_bool('n'))
        self.assertFalse(na_utils.to_bool(0))
        self.assertFalse(na_utils.to_bool('0'))
        self.assertFalse(na_utils.to_bool(2))
        self.assertFalse(na_utils.to_bool('2'))

    def test_convert_uuid_to_es_fmt(self):
        value = 'e67e931a-b2ed-4890-938b-3acc6a517fac'
        result = na_utils.convert_uuid_to_es_fmt(value)
        self.assertEqual(result, '4Z7JGGVS5VEJBE4LHLGGUUL7VQ')

    def test_convert_es_fmt_to_uuid(self):
        value = '4Z7JGGVS5VEJBE4LHLGGUUL7VQ'
        result = str(na_utils.convert_es_fmt_to_uuid(value))
        self.assertEqual(result, 'e67e931a-b2ed-4890-938b-3acc6a517fac')

    def test_round_down(self):
        self.assertAlmostEqual(na_utils.round_down(5.567, '0.00'), 5.56)
        self.assertAlmostEqual(na_utils.round_down(5.567, '0.0'), 5.5)
        self.assertAlmostEqual(na_utils.round_down(5.567, '0'), 5)
        self.assertAlmostEqual(na_utils.round_down(0, '0.00'), 0)
        self.assertAlmostEqual(na_utils.round_down(-5.567, '0.00'), -5.56)
        self.assertAlmostEqual(na_utils.round_down(-5.567, '0.0'), -5.5)
        self.assertAlmostEqual(na_utils.round_down(-5.567, '0'), -5)
