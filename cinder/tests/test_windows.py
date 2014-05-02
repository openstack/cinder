# Copyright 2012 Pedro Navarro Perez
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
Unit tests for Windows Server 2012 OpenStack Cinder volume driver
"""


import os
import shutil
import tempfile

from oslo.config import cfg

import mox

from cinder import test

from cinder.image import image_utils

from cinder.tests.windows import db_fakes
from cinder.volume import configuration as conf
from cinder.volume.drivers.windows import windows
from cinder.volume.drivers.windows import windows_utils


CONF = cfg.CONF


class TestWindowsDriver(test.TestCase):

    def __init__(self, method):
        super(TestWindowsDriver, self).__init__(method)

    def setUp(self):
        self.lun_path_tempdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.lun_path_tempdir)

        super(TestWindowsDriver, self).setUp()
        self.flags(
            windows_iscsi_lun_path=self.lun_path_tempdir,
        )
        self._setup_stubs()
        configuration = conf.Configuration(None)
        configuration.append_config_values(windows.windows_opts)

        self._driver = windows.WindowsDriver(configuration=configuration)
        self._driver.do_setup({})

    def _setup_stubs(self):

        def fake_wutils__init__(self):
            pass
        windows_utils.WindowsUtils.__init__ = fake_wutils__init__

    def fake_local_path(self, volume):
        return os.path.join(CONF.windows_iscsi_lun_path,
                            str(volume['name']) + ".vhd")

    def test_check_for_setup_errors(self):
        drv = self._driver
        self.mox.StubOutWithMock(windows_utils.WindowsUtils,
                                 'check_for_setup_error')
        windows_utils.WindowsUtils.check_for_setup_error()

        self.mox.ReplayAll()

        drv.check_for_setup_error()

    def test_create_volume(self):
        drv = self._driver
        vol = db_fakes.get_fake_volume_info()

        self.stubs.Set(drv, 'local_path', self.fake_local_path)

        self.mox.StubOutWithMock(windows_utils.WindowsUtils,
                                 'create_volume')

        windows_utils.WindowsUtils.create_volume(self.fake_local_path(vol),
                                                 vol['name'], vol['size'])

        self.mox.ReplayAll()

        drv.create_volume(vol)

    def test_delete_volume(self):
        """delete_volume simple test case."""
        drv = self._driver

        vol = db_fakes.get_fake_volume_info()

        self.mox.StubOutWithMock(drv, 'local_path')
        drv.local_path(vol).AndReturn(self.fake_local_path(vol))

        self.mox.StubOutWithMock(windows_utils.WindowsUtils,
                                 'delete_volume')
        windows_utils.WindowsUtils.delete_volume(vol['name'],
                                                 self.fake_local_path(vol))
        self.mox.ReplayAll()

        drv.delete_volume(vol)

    def test_create_snapshot(self):
        drv = self._driver
        self.mox.StubOutWithMock(windows_utils.WindowsUtils,
                                 'create_snapshot')
        volume = db_fakes.get_fake_volume_info()
        snapshot = db_fakes.get_fake_snapshot_info()

        self.stubs.Set(drv, 'local_path', self.fake_local_path(snapshot))

        windows_utils.WindowsUtils.create_snapshot(volume['name'],
                                                   snapshot['name'])

        self.mox.ReplayAll()

        drv.create_snapshot(snapshot)

    def test_create_volume_from_snapshot(self):
        drv = self._driver

        snapshot = db_fakes.get_fake_snapshot_info()
        volume = db_fakes.get_fake_volume_info()

        self.mox.StubOutWithMock(windows_utils.WindowsUtils,
                                 'create_volume_from_snapshot')
        windows_utils.WindowsUtils.\
            create_volume_from_snapshot(volume['name'], snapshot['name'])

        self.mox.ReplayAll()

        drv.create_volume_from_snapshot(volume, snapshot)

    def test_delete_snapshot(self):
        drv = self._driver

        snapshot = db_fakes.get_fake_snapshot_info()

        self.mox.StubOutWithMock(windows_utils.WindowsUtils,
                                 'delete_snapshot')
        windows_utils.WindowsUtils.delete_snapshot(snapshot['name'])

        self.mox.ReplayAll()

        drv.delete_snapshot(snapshot)

    def test_create_export(self):
        drv = self._driver

        volume = db_fakes.get_fake_volume_info()

        initiator_name = "%s%s" % (CONF.iscsi_target_prefix, volume['name'])

        self.mox.StubOutWithMock(windows_utils.WindowsUtils,
                                 'create_iscsi_target')
        windows_utils.WindowsUtils.create_iscsi_target(initiator_name,
                                                       mox.IgnoreArg())
        self.mox.StubOutWithMock(windows_utils.WindowsUtils,
                                 'add_disk_to_target')
        windows_utils.WindowsUtils.add_disk_to_target(volume['name'],
                                                      initiator_name)

        self.mox.ReplayAll()

        export_info = drv.create_export(None, volume)

        self.assertEqual(export_info['provider_location'], initiator_name)

    def test_initialize_connection(self):
        drv = self._driver

        volume = db_fakes.get_fake_volume_info()
        initiator_name = "%s%s" % (CONF.iscsi_target_prefix, volume['name'])

        connector = db_fakes.get_fake_connector_info()

        self.mox.StubOutWithMock(windows_utils.WindowsUtils,
                                 'associate_initiator_with_iscsi_target')
        windows_utils.WindowsUtils.associate_initiator_with_iscsi_target(
            volume['provider_location'], initiator_name, )

        self.mox.StubOutWithMock(windows_utils.WindowsUtils,
                                 'get_host_information')
        windows_utils.WindowsUtils.get_host_information(
            volume, volume['provider_location'])

        self.mox.ReplayAll()

        drv.initialize_connection(volume, connector)

    def test_terminate_connection(self):
        drv = self._driver

        volume = db_fakes.get_fake_volume_info()
        initiator_name = "%s%s" % (CONF.iscsi_target_prefix, volume['name'])
        connector = db_fakes.get_fake_connector_info()

        self.mox.StubOutWithMock(windows_utils.WindowsUtils,
                                 'delete_iscsi_target')
        windows_utils.WindowsUtils.delete_iscsi_target(
            initiator_name, volume['provider_location'])

        self.mox.ReplayAll()

        drv.terminate_connection(volume, connector)

    def test_ensure_export(self):
        drv = self._driver

        volume = db_fakes.get_fake_volume_info()

        initiator_name = "%s%s" % (CONF.iscsi_target_prefix, volume['name'])

        self.mox.StubOutWithMock(windows_utils.WindowsUtils,
                                 'create_iscsi_target')
        windows_utils.WindowsUtils.create_iscsi_target(initiator_name, True)
        self.mox.StubOutWithMock(windows_utils.WindowsUtils,
                                 'add_disk_to_target')
        windows_utils.WindowsUtils.add_disk_to_target(volume['name'],
                                                      initiator_name)

        self.mox.ReplayAll()

        drv.ensure_export(None, volume)

    def test_remove_export(self):
        drv = self._driver

        volume = db_fakes.get_fake_volume_info()

        target_name = volume['provider_location']

        self.mox.StubOutWithMock(windows_utils.WindowsUtils,
                                 'remove_iscsi_target')
        windows_utils.WindowsUtils.remove_iscsi_target(target_name)

        self.mox.ReplayAll()

        drv.remove_export(None, volume)

    def test_copy_image_to_volume(self):
        """resize_image common case usage."""
        drv = self._driver

        volume = db_fakes.get_fake_volume_info()

        self.stubs.Set(drv, 'local_path', self.fake_local_path)

        self.mox.StubOutWithMock(image_utils, 'fetch_to_vhd')
        image_utils.fetch_to_vhd(None, None, None,
                                 self.fake_local_path(volume),
                                 mox.IgnoreArg())

        self.mox.ReplayAll()

        drv.copy_image_to_volume(None, volume, None, None)

    def test_copy_volume_to_image(self):
        drv = self._driver

        vol = db_fakes.get_fake_volume_info()

        image_meta = db_fakes.get_fake_image_meta()

        self.stubs.Set(drv, 'local_path', self.fake_local_path)

        self.mox.StubOutWithMock(image_utils, 'upload_volume')

        temp_vhd_path = os.path.join(CONF.image_conversion_dir,
                                     str(image_meta['id']) + ".vhd")

        image_utils.upload_volume(None, None, image_meta, temp_vhd_path, 'vpc')

        self.mox.StubOutWithMock(windows_utils.WindowsUtils,
                                 'copy_vhd_disk')

        windows_utils.WindowsUtils.copy_vhd_disk(self.fake_local_path(vol),
                                                 temp_vhd_path)

        self.mox.ReplayAll()

        drv.copy_volume_to_image(None, vol, None, image_meta)

    def test_create_cloned_volume(self):
        drv = self._driver

        volume = db_fakes.get_fake_volume_info()
        volume_cloned = db_fakes.get_fake_volume_info_cloned()

        self.mox.StubOutWithMock(windows_utils.WindowsUtils,
                                 'create_volume')

        windows_utils.WindowsUtils.create_volume(mox.IgnoreArg(),
                                                 mox.IgnoreArg(),
                                                 mox.IgnoreArg())

        self.mox.StubOutWithMock(windows_utils.WindowsUtils,
                                 'copy_vhd_disk')
        windows_utils.WindowsUtils.copy_vhd_disk(self.fake_local_path(
            volume_cloned), self.fake_local_path(volume))

        self.mox.ReplayAll()

        drv.create_cloned_volume(volume, volume_cloned)

    def test_extend_volume(self):
        drv = self._driver

        volume = db_fakes.get_fake_volume_info()

        TEST_VOLUME_ADDITIONAL_SIZE_MB = 1024
        TEST_VOLUME_ADDITIONAL_SIZE_GB = 1

        self.mox.StubOutWithMock(windows_utils.WindowsUtils, 'extend')

        windows_utils.WindowsUtils.extend(volume['name'],
                                          TEST_VOLUME_ADDITIONAL_SIZE_MB)

        new_size = volume['size'] + TEST_VOLUME_ADDITIONAL_SIZE_GB

        self.mox.ReplayAll()

        drv.extend_volume(volume, new_size)
