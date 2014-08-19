# Copyright (c) 2014 Hitachi Data Systems, Inc.
# All Rights Reserved.
#
#   Licensed under the Apache License, Version 2.0 (the "License"); you may
#   not use this file except in compliance with the License. You may obtain
#   a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#   WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#   License for the specific language governing permissions and limitations
#   under the License.

import os

import mock
from oslo.rootwrap import wrapper

from cinder import test


class RootwrapFilterTest(test.TestCase):
    """Test cases for etc/cinder/rootwrap.d/volume.filters
    """

    def setUp(self):
        super(RootwrapFilterTest, self).setUp()
        self._filters = wrapper.load_filters(['etc/cinder/rootwrap.d/'])

    @mock.patch.object(os, 'access', return_value=True)
    def _test_match(self, cmd, mock_access):
        filtermatch = wrapper.match_filter(self._filters, cmd,
                                           exec_dirs=['/usr/bin'])
        self.assertIsNotNone(filtermatch)

    def test_ionice_filter(self):
        self._test_match(['ionice', '-c3', 'dd', 'if=/aaa', 'of=/bbb'])
        self._test_match(['ionice', '-c2', '-n7', 'dd', 'if=/aaa', 'of=/bbb',
                          'bs=1M', 'count=1024', 'oflag=direct'])
        self._test_match(['ionice', '-c1', 'dd', 'if=/aaa', 'of=/bbb',
                          'iflag=direct'])
        self._test_match(['ionice', '-c0', 'dd', 'if=/aaa', 'of=/bbb',
                          'convert=datasync'])
