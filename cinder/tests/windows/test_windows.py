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

import mox
from oslo_config import cfg

from cinder.image import image_utils
from cinder.openstack.common import fileutils
from cinder import test
from cinder.tests.windows import db_fakes
from cinder.volume import configuration as conf
from cinder.volume.drivers.windows import constants
from cinder.volume.drivers.windows import vhdutils
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
            create_volume_from_snapshot(volume, snapshot['name'])

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

        fake_get_supported_type = lambda x: constants.VHD_TYPE_FIXED
        self.stubs.Set(drv, 'local_path', self.fake_local_path)
        self.stubs.Set(windows_utils.WindowsUtils, 'get_supported_vhd_type',
                       fake_get_supported_type)

        self.mox.StubOutWithMock(os, 'unlink')
        self.mox.StubOutWithMock(image_utils, 'create_temporary_file')
        self.mox.StubOutWithMock(image_utils, 'fetch_to_vhd')
        self.mox.StubOutWithMock(vhdutils.VHDUtils, 'convert_vhd')
        self.mox.StubOutWithMock(vhdutils.VHDUtils, 'resize_vhd')
        self.mox.StubOutWithMock(windows_utils.WindowsUtils,
                                 'change_disk_status')

        fake_temp_path = r'C:\fake\temp\file'
        if (CONF.image_conversion_dir and not
                os.path.exists(CONF.image_conversion_dir)):
            os.makedirs(CONF.image_conversion_dir)
        image_utils.create_temporary_file(suffix='.vhd').AndReturn(
            fake_temp_path)

        fake_volume_path = self.fake_local_path(volume)

        image_utils.fetch_to_vhd(None, None, None,
                                 fake_temp_path,
                                 mox.IgnoreArg())
        windows_utils.WindowsUtils.change_disk_status(volume['name'],
                                                      mox.IsA(bool))
        vhdutils.VHDUtils.convert_vhd(fake_temp_path,
                                      fake_volume_path,
                                      constants.VHD_TYPE_FIXED)
        vhdutils.VHDUtils.resize_vhd(fake_volume_path,
                                     volume['size'] << 30)
        windows_utils.WindowsUtils.change_disk_status(volume['name'],
                                                      mox.IsA(bool))
        os.unlink(mox.IsA(str))

        self.mox.ReplayAll()

        drv.copy_image_to_volume(None, volume, None, None)

    def _test_copy_volume_to_image(self, supported_format):
        drv = self._driver

        vol = db_fakes.get_fake_volume_info()

        image_meta = db_fakes.get_fake_image_meta()

        fake_get_supported_format = lambda x: supported_format

        self.stubs.Set(os.path, 'exists', lambda x: False)
        self.stubs.Set(drv, 'local_path', self.fake_local_path)
        self.stubs.Set(windows_utils.WindowsUtils, 'get_supported_format',
                       fake_get_supported_format)

        self.mox.StubOutWithMock(fileutils, 'ensure_tree')
        self.mox.StubOutWithMock(fileutils, 'delete_if_exists')
        self.mox.StubOutWithMock(image_utils, 'upload_volume')
        self.mox.StubOutWithMock(windows_utils.WindowsUtils, 'copy_vhd_disk')
        self.mox.StubOutWithMock(vhdutils.VHDUtils, 'convert_vhd')

        fileutils.ensure_tree(CONF.image_conversion_dir)
        temp_vhd_path = os.path.join(CONF.image_conversion_dir,
                                     str(image_meta['id']) + "." +
                                     supported_format)
        upload_image = temp_vhd_path

        windows_utils.WindowsUtils.copy_vhd_disk(self.fake_local_path(vol),
                                                 temp_vhd_path)
        if supported_format == 'vhdx':
            upload_image = upload_image[:-1]
            vhdutils.VHDUtils.convert_vhd(temp_vhd_path, upload_image,
                                          constants.VHD_TYPE_DYNAMIC)

        image_utils.upload_volume(None, None, image_meta, upload_image, 'vhd')

        fileutils.delete_if_exists(temp_vhd_path)
        fileutils.delete_if_exists(upload_image)

        self.mox.ReplayAll()

        drv.copy_volume_to_image(None, vol, None, image_meta)

    def test_copy_volume_to_image_using_vhd(self):
        self._test_copy_volume_to_image('vhd')

    def test_copy_volume_to_image_using_vhdx(self):
        self._test_copy_volume_to_image('vhdx')

    def test_create_cloned_volume(self):
        drv = self._driver

        volume = db_fakes.get_fake_volume_info()
        volume_cloned = db_fakes.get_fake_volume_info_cloned()
        new_vhd_path = self.fake_local_path(volume)
        src_vhd_path = self.fake_local_path(volume_cloned)

        self.mox.StubOutWithMock(windows_utils.WindowsUtils,
                                 'copy_vhd_disk')
        self.mox.StubOutWithMock(windows_utils.WindowsUtils,
                                 'import_wt_disk')
        self.mox.StubOutWithMock(vhdutils.VHDUtils,
                                 'resize_vhd')

        self.stubs.Set(drv.utils,
                       'is_resize_needed',
                       lambda vhd_path, new_size, old_size: True)
        self.stubs.Set(drv, 'local_path', self.fake_local_path)

        windows_utils.WindowsUtils.copy_vhd_disk(src_vhd_path,
                                                 new_vhd_path)
        drv.utils.is_resize_needed(new_vhd_path,
                                   volume['size'],
                                   volume_cloned['size'])
        vhdutils.VHDUtils.resize_vhd(new_vhd_path, volume['size'] << 30)
        windows_utils.WindowsUtils.import_wt_disk(new_vhd_path,
                                                  volume['name'])

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
