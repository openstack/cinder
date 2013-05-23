# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 eNovance , Inc.
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
"""Unit tests for image utils."""

from cinder.image import image_utils
from cinder import test
from cinder import utils
import mox


class TestUtils(test.TestCase):
    def setUp(self):
        super(TestUtils, self).setUp()
        self._mox = mox.Mox()
        self.addCleanup(self._mox.UnsetStubs)

    def test_resize_image(self):
        mox = self._mox
        mox.StubOutWithMock(utils, 'execute')

        TEST_IMG_SOURCE = 'boobar.img'
        TEST_IMG_SIZE_IN_GB = 1

        utils.execute('qemu-img', 'resize', TEST_IMG_SOURCE,
                      '%sG' % TEST_IMG_SIZE_IN_GB, run_as_root=False)

        mox.ReplayAll()

        image_utils.resize_image(TEST_IMG_SOURCE, TEST_IMG_SIZE_IN_GB)

        mox.VerifyAll()
