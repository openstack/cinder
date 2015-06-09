# Copyright (c) 2013 The Johns Hopkins University/Applied Physics Laboratory
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
Test cases for the key manager.
"""

from cinder import test


class KeyManagerTestCase(test.TestCase):
    def __init__(self, *args, **kwargs):
        super(KeyManagerTestCase, self).__init__(*args, **kwargs)

    def _create_key_manager(self):
        raise NotImplementedError()

    def setUp(self):
        super(KeyManagerTestCase, self).setUp()

        self.key_mgr = self._create_key_manager()
