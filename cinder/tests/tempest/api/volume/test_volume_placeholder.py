# Copyright 2015
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

from tempest.tests import base


class CinderPlaceholderTest(base.TestCase):
    """Placeholder test for adding in-tree Cinder tempest tests."""
    # TODO(smcginnis) Remove once real tests are added

    def test_placeholder(self):
        expected = 'This test is temporary and should be removed!'
        self.assertEqual(expected, expected)
