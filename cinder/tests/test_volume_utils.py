# Copyright 2011 OpenStack Foundation
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

"""Tests For miscellaneous util methods used with volume."""

import os
import re

from oslo.config import cfg

from cinder import context
from cinder import db
from cinder import exception
from cinder.openstack.common import importutils
from cinder.openstack.common import log as logging
from cinder.openstack.common.notifier import api as notifier_api
from cinder.openstack.common.notifier import test_notifier
from cinder import test
from cinder import utils
from cinder.volume import utils as volume_utils


LOG = logging.getLogger(__name__)

CONF = cfg.CONF


class UsageInfoTestCase(test.TestCase):

    QUEUE_NAME = 'cinder-volume'
    HOSTNAME = 'my-host.com'
    HOSTIP = '10.0.0.1'
    BACKEND = 'test_backend'
    MULTI_AT_BACKEND = 'test_b@ckend'

    def setUp(self):
        super(UsageInfoTestCase, self).setUp()
        self.flags(host='fake',
                   notification_driver=[test_notifier.__name__])
        self.volume = importutils.import_object(CONF.volume_manager)
        self.user_id = 'fake'
        self.project_id = 'fake'
        self.snapshot_id = 'fake'
        self.volume_size = 0
        self.context = context.RequestContext(self.user_id, self.project_id)
        test_notifier.NOTIFICATIONS = []

    def tearDown(self):
        notifier_api._reset_drivers()
        super(UsageInfoTestCase, self).tearDown()

    def _create_volume(self, params={}):
        """Create a test volume."""
        vol = {}
        vol['snapshot_id'] = self.snapshot_id
        vol['user_id'] = self.user_id
        vol['project_id'] = self.project_id
        vol['host'] = CONF.host
        vol['availability_zone'] = CONF.storage_availability_zone
        vol['status'] = "creating"
        vol['attach_status'] = "detached"
        vol['size'] = self.volume_size
        vol.update(params)
        return db.volume_create(self.context, vol)['id']


class LVMVolumeDriverTestCase(test.TestCase):
    def test_convert_blocksize_option(self):
        # Test valid volume_dd_blocksize
        bs, count = volume_utils._calculate_count(1024, '10M')
        self.assertEqual(bs, '10M')
        self.assertEqual(count, 103)

        bs, count = volume_utils._calculate_count(1024, '1xBBB')
        self.assertEqual(bs, '1M')
        self.assertEqual(count, 1024)

        # Test 'volume_dd_blocksize' with fraction
        bs, count = volume_utils._calculate_count(1024, '1.3M')
        self.assertEqual(bs, '1M')
        self.assertEqual(count, 1024)

        # Test zero-size 'volume_dd_blocksize'
        bs, count = volume_utils._calculate_count(1024, '0M')
        self.assertEqual(bs, '1M')
        self.assertEqual(count, 1024)

        # Test negative 'volume_dd_blocksize'
        bs, count = volume_utils._calculate_count(1024, '-1M')
        self.assertEqual(bs, '1M')
        self.assertEqual(count, 1024)

        # Test non-digital 'volume_dd_blocksize'
        bs, count = volume_utils._calculate_count(1024, 'ABM')
        self.assertEqual(bs, '1M')
        self.assertEqual(count, 1024)


class ClearVolumeTestCase(test.TestCase):

    def test_clear_volume(self):
        CONF.volume_clear = 'zero'
        CONF.volume_clear_size = 0
        CONF.volume_dd_blocksize = '1M'
        CONF.volume_clear_ionice = None
        self.mox.StubOutWithMock(volume_utils, 'copy_volume')
        volume_utils.copy_volume("/dev/zero", "volume_path", 1024,
                                 CONF.volume_dd_blocksize, sync=True,
                                 ionice=None, execute=utils.execute)
        self.mox.ReplayAll()
        volume_utils.clear_volume(1024, "volume_path")

    def test_clear_volume_zero(self):
        CONF.volume_clear = 'zero'
        CONF.volume_clear_size = 1
        CONF.volume_clear_ionice = None
        self.mox.StubOutWithMock(volume_utils, 'copy_volume')
        volume_utils.copy_volume("/dev/zero", "volume_path", 1,
                                 CONF.volume_dd_blocksize, sync=True,
                                 ionice=None, execute=utils.execute)
        self.mox.ReplayAll()
        volume_utils.clear_volume(1024, "volume_path")

    def test_clear_volume_ionice(self):
        CONF.volume_clear = 'zero'
        CONF.volume_clear_size = 0
        CONF.volume_dd_blocksize = '1M'
        CONF.volume_clear_ionice = '-c3'
        self.mox.StubOutWithMock(volume_utils, 'copy_volume')
        volume_utils.copy_volume("/dev/zero", "volume_path", 1024,
                                 CONF.volume_dd_blocksize, sync=True,
                                 ionice=CONF.volume_clear_ionice,
                                 execute=utils.execute)
        self.mox.ReplayAll()
        volume_utils.clear_volume(1024, "volume_path")

    def test_clear_volume_zero_ionice(self):
        CONF.volume_clear = 'zero'
        CONF.volume_clear_size = 1
        CONF.volume_clear_ionice = '-c3'
        self.mox.StubOutWithMock(volume_utils, 'copy_volume')
        volume_utils.copy_volume("/dev/zero", "volume_path", 1,
                                 CONF.volume_dd_blocksize, sync=True,
                                 ionice=CONF.volume_clear_ionice,
                                 execute=utils.execute)
        self.mox.ReplayAll()
        volume_utils.clear_volume(1024, "volume_path")

    def test_clear_volume_shred(self):
        CONF.volume_clear = 'shred'
        CONF.volume_clear_size = 1
        clear_cmd = ['shred', '-n3', '-s1MiB', "volume_path"]
        self.mox.StubOutWithMock(utils, "execute")
        utils.execute(*clear_cmd, run_as_root=True)
        self.mox.ReplayAll()
        volume_utils.clear_volume(1024, "volume_path")

    def test_clear_volume_shred_not_clear_size(self):
        CONF.volume_clear = 'shred'
        CONF.volume_clear_size = None
        clear_cmd = ['shred', '-n3', "volume_path"]
        self.mox.StubOutWithMock(utils, "execute")
        utils.execute(*clear_cmd, run_as_root=True)
        self.mox.ReplayAll()
        volume_utils.clear_volume(1024, "volume_path")

    def test_clear_volume_invalid_opt(self):
        CONF.volume_clear = 'non_existent_volume_clearer'
        CONF.volume_clear_size = 0
        self.mox.StubOutWithMock(volume_utils, 'copy_volume')

        self.mox.ReplayAll()

        self.assertRaises(exception.InvalidConfigurationValue,
                          volume_utils.clear_volume,
                          1024, "volume_path")

    def test_clear_volume_lvm_snap(self):
        self.stubs.Set(os.path, 'exists', lambda x: True)
        CONF.volume_clear = 'zero'
        CONF.volume_clear_size = 0

        uuid = '00000000-0000-0000-0000-90ed32cdeed3'
        name = 'snapshot-' + uuid
        mangle_name = '_' + re.sub(r'-', r'--', name)
        vol_path = '/dev/mapper/cinder--volumes-%s-cow' % mangle_name

        def fake_copy_volume(srcstr, deststr, size, blocksize, **kwargs):
            self.assertEqual(deststr, vol_path)
            return True

        self.stubs.Set(volume_utils, 'copy_volume', fake_copy_volume)
        volume_utils.clear_volume(123, vol_path)
