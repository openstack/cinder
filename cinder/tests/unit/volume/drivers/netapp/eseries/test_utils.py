# Copyright (c) 2014 Clinton Knight.  All rights reserved.
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
Mock unit tests for the NetApp E-series driver utility module
"""

import six

from cinder import test
from cinder.volume.drivers.netapp.eseries import utils


class NetAppEseriesDriverUtilsTestCase(test.TestCase):

    def test_convert_uuid_to_es_fmt(self):
        value = 'e67e931a-b2ed-4890-938b-3acc6a517fac'
        result = utils.convert_uuid_to_es_fmt(value)
        self.assertEqual(result, '4Z7JGGVS5VEJBE4LHLGGUUL7VQ')

    def test_convert_es_fmt_to_uuid(self):
        value = '4Z7JGGVS5VEJBE4LHLGGUUL7VQ'
        result = six.text_type(utils.convert_es_fmt_to_uuid(value))
        self.assertEqual(result, 'e67e931a-b2ed-4890-938b-3acc6a517fac')
