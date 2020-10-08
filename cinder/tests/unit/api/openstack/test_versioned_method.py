# Copyright 2015 Clinton Knight
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

from cinder.api.openstack import versioned_method
from cinder.tests.unit import test


class VersionedMethodTestCase(test.TestCase):

    def test_str(self):
        args = ('fake_name', 'fake_min', 'fake_max')
        method = versioned_method.VersionedMethod(*(args + (False, None)))
        method_string = str(method)

        self.assertEqual('Version Method %s: min: %s, max: %s' % args,
                         method_string)

    def test_cmpkey(self):
        method = versioned_method.VersionedMethod(
            'fake_name', 'fake_start_version', 'fake_end_version', False,
            'fake_func')
        self.assertEqual('fake_start_version', method._cmpkey())
