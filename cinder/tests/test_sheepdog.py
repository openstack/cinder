
# Copyright (c) 2013 Zelin.io
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


import contextlib
import os
import tempfile

from cinder.image import image_utils
from cinder.openstack.common import processutils
from cinder.openstack.common import units
from cinder import test
from cinder.volume.drivers.sheepdog import SheepdogDriver


COLLIE_NODE_INFO = """
0 107287605248 3623897354 3%
Total 107287605248 3623897354 3% 54760833024
"""

COLLIE_CLUSTER_INFO_0_5 = """
Cluster status: running

Cluster created at Tue Jun 25 19:51:41 2013

Epoch Time           Version
2013-06-25 19:51:41      1 [127.0.0.1:7000, 127.0.0.1:7001, 127.0.0.1:7002]
"""

COLLIE_CLUSTER_INFO_0_6 = """
Cluster status: running, auto-recovery enabled

Cluster created at Tue Jun 25 19:51:41 2013

Epoch Time           Version
2013-06-25 19:51:41      1 [127.0.0.1:7000, 127.0.0.1:7001, 127.0.0.1:7002]
"""


class FakeImageService:
    def download(self, context, image_id, path):
        pass


class SheepdogTestCase(test.TestCase):
    def setUp(self):
        super(SheepdogTestCase, self).setUp()
        self.driver = SheepdogDriver()

    def test_update_volume_stats(self):
        def fake_stats(*args):
            return COLLIE_NODE_INFO, ''
        self.stubs.Set(self.driver, '_execute', fake_stats)
        expected = dict(
            volume_backend_name='sheepdog',
            vendor_name='Open Source',
            dirver_version=self.driver.VERSION,
            storage_protocol='sheepdog',
            total_capacity_gb=float(107287605248) / units.Gi,
            free_capacity_gb=float(107287605248 - 3623897354) / units.Gi,
            reserved_percentage=0,
            QoS_support=False)
        actual = self.driver.get_volume_stats(True)
        self.assertDictMatch(expected, actual)

    def test_update_volume_stats_error(self):
        def fake_stats(*args):
            raise processutils.ProcessExecutionError()
        self.stubs.Set(self.driver, '_execute', fake_stats)
        expected = dict(
            volume_backend_name='sheepdog',
            vendor_name='Open Source',
            dirver_version=self.driver.VERSION,
            storage_protocol='sheepdog',
            total_capacity_gb='unknown',
            free_capacity_gb='unknown',
            reserved_percentage=0,
            QoS_support=False)
        actual = self.driver.get_volume_stats(True)
        self.assertDictMatch(expected, actual)

    def test_check_for_setup_error_0_5(self):
        def fake_stats(*args):
            return COLLIE_CLUSTER_INFO_0_5, ''
        self.stubs.Set(self.driver, '_execute', fake_stats)
        self.driver.check_for_setup_error()

    def test_check_for_setup_error_0_6(self):
        def fake_stats(*args):
            return COLLIE_CLUSTER_INFO_0_6, ''
        self.stubs.Set(self.driver, '_execute', fake_stats)
        self.driver.check_for_setup_error()

    def test_copy_image_to_volume(self):
        @contextlib.contextmanager
        def fake_temp_file(dir):
            class FakeTmp:
                def __init__(self, name):
                    self.name = name
            yield FakeTmp('test')

        def fake_try_execute(obj, *command, **kwargs):
            return True

        self.stubs.Set(tempfile, 'NamedTemporaryFile', fake_temp_file)
        self.stubs.Set(os.path, 'exists', lambda x: True)
        self.stubs.Set(image_utils, 'fetch_verify_image',
                       lambda w, x, y, z: None)
        self.stubs.Set(image_utils, 'convert_image',
                       lambda x, y, z: None)
        self.stubs.Set(SheepdogDriver, '_try_execute', fake_try_execute)
        self.driver.copy_image_to_volume(None, {'name': 'test',
                                                'size': 1},
                                         FakeImageService(), None)

    def test_extend_volume(self):
        fake_name = u'volume-00000001'
        fake_size = '20'
        fake_vol = {'project_id': 'testprjid', 'name': fake_name,
                    'size': fake_size,
                    'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66'}

        self.mox.StubOutWithMock(self.driver, '_resize')
        size = int(fake_size) * units.Gi
        self.driver._resize(fake_vol, size=size)

        self.mox.ReplayAll()
        self.driver.extend_volume(fake_vol, fake_size)

        self.mox.VerifyAll()
