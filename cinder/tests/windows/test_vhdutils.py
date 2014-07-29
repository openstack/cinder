#  Copyright 2014 Cloudbase Solutions Srl
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

import mock

from cinder import exception
from cinder import test
from cinder.volume.drivers.windows import constants
from cinder.volume.drivers.windows import vhdutils


class VHDUtilsTestCase(test.TestCase):

    _FAKE_FORMAT = 2
    _FAKE_TYPE = constants.VHD_TYPE_DYNAMIC
    _FAKE_JOB_PATH = 'fake_job_path'
    _FAKE_VHD_PATH = r'C:\fake\vhd.vhd'
    _FAKE_DEST_PATH = r'C:\fake\destination.vhdx'
    _FAKE_RET_VAL = 0
    _FAKE_VHD_SIZE = 1024
    _FAKE_DEVICE_ID = 'fake_device_id'

    def setUp(self):
        super(VHDUtilsTestCase, self).setUp()
        self._setup_mocks()
        self._vhdutils = vhdutils.VHDUtils()
        self._vhdutils._msft_vendor_id = 'fake_vendor_id'

        self.addCleanup(mock.patch.stopall)

    def _setup_mocks(self):
        fake_ctypes = mock.Mock()
        # Use this in order to make assertions on the variables parsed by
        # references.
        fake_ctypes.byref = lambda x: x
        fake_ctypes.c_wchar_p = lambda x: x

        mock.patch.multiple(
            'cinder.volume.drivers.windows.vhdutils', ctypes=fake_ctypes,
            windll=mock.DEFAULT, wintypes=mock.DEFAULT, kernel32=mock.DEFAULT,
            virtdisk=mock.DEFAULT, Win32_GUID=mock.DEFAULT,
            Win32_RESIZE_VIRTUAL_DISK_PARAMETERS=mock.DEFAULT,
            Win32_CREATE_VIRTUAL_DISK_PARAMETERS=mock.DEFAULT,
            Win32_VIRTUAL_STORAGE_TYPE=mock.DEFAULT,
            create=True).start()

    def _test_convert_vhd(self, convertion_failed=False):
        self._vhdutils._get_device_id_by_path = mock.Mock(
            side_effect=(vhdutils.VIRTUAL_STORAGE_TYPE_DEVICE_VHD,
                         vhdutils.VIRTUAL_STORAGE_TYPE_DEVICE_VHDX))
        self._vhdutils._close = mock.Mock()

        fake_params = (
            vhdutils.Win32_CREATE_VIRTUAL_DISK_PARAMETERS.return_value)
        fake_vst = mock.Mock()
        fake_source_vst = mock.Mock()

        vhdutils.Win32_VIRTUAL_STORAGE_TYPE = mock.Mock(
            side_effect=[fake_vst, None, fake_source_vst])
        vhdutils.virtdisk.CreateVirtualDisk.return_value = int(
            convertion_failed)

        if convertion_failed:
            self.assertRaises(exception.VolumeBackendAPIException,
                              self._vhdutils.convert_vhd,
                              self._FAKE_VHD_PATH, self._FAKE_DEST_PATH,
                              self._FAKE_TYPE)
        else:
            self._vhdutils.convert_vhd(self._FAKE_VHD_PATH,
                                       self._FAKE_DEST_PATH,
                                       self._FAKE_TYPE)

        self.assertEqual(vhdutils.VIRTUAL_STORAGE_TYPE_DEVICE_VHDX,
                         fake_vst.DeviceId)
        self.assertEqual(vhdutils.VIRTUAL_STORAGE_TYPE_DEVICE_VHD,
                         fake_source_vst.DeviceId)

        vhdutils.virtdisk.CreateVirtualDisk.assert_called_with(
            vhdutils.ctypes.byref(fake_vst),
            vhdutils.ctypes.c_wchar_p(self._FAKE_DEST_PATH),
            vhdutils.VIRTUAL_DISK_ACCESS_NONE, None,
            vhdutils.CREATE_VIRTUAL_DISK_FLAG_NONE, 0,
            vhdutils.ctypes.byref(fake_params), None,
            vhdutils.ctypes.byref(vhdutils.wintypes.HANDLE()))
        self.assertTrue(self._vhdutils._close.called)

    def test_convert_vhd_successfully(self):
        self._test_convert_vhd()

    def test_convert_vhd_exception(self):
        self._test_convert_vhd(True)

    def _test_open(self, open_failed=False):
        vhdutils.virtdisk.OpenVirtualDisk.return_value = int(open_failed)

        fake_vst = vhdutils.Win32_VIRTUAL_STORAGE_TYPE.return_value

        if open_failed:
            self.assertRaises(exception.VolumeBackendAPIException,
                              self._vhdutils._open,
                              self._FAKE_DEVICE_ID, self._FAKE_VHD_PATH)
        else:
            self._vhdutils._open(self._FAKE_DEVICE_ID,
                                 self._FAKE_VHD_PATH)

        vhdutils.virtdisk.OpenVirtualDisk.assert_called_with(
            vhdutils.ctypes.byref(fake_vst),
            vhdutils.ctypes.c_wchar_p(self._FAKE_VHD_PATH),
            vhdutils.VIRTUAL_DISK_ACCESS_ALL,
            vhdutils.CREATE_VIRTUAL_DISK_FLAG_NONE, 0,
            vhdutils.ctypes.byref(vhdutils.wintypes.HANDLE()))
        self.assertEqual(self._FAKE_DEVICE_ID, fake_vst.DeviceId)

    def test_open_success(self):
        self._test_open()

    def test_open_failed(self):
        self._test_open(open_failed=True)

    def _test_get_device_id_by_path(self,
                                    get_device_failed=False):
        if get_device_failed:
            self.assertRaises(exception.VolumeBackendAPIException,
                              self._vhdutils._get_device_id_by_path,
                              self._FAKE_VHD_PATH[:-4])
        else:
            ret_val = self._vhdutils._get_device_id_by_path(
                self._FAKE_VHD_PATH)

            self.assertEqual(
                ret_val,
                vhdutils.VIRTUAL_STORAGE_TYPE_DEVICE_VHD)

    def test_get_device_id_by_path_success(self):
        self._test_get_device_id_by_path()

    def test_get_device_id_by_path_failed(self):
        self._test_get_device_id_by_path(get_device_failed=True)

    def _test_resize_vhd(self, resize_failed=False):
        fake_params = (
            vhdutils.Win32_RESIZE_VIRTUAL_DISK_PARAMETERS.return_value)

        self._vhdutils._open = mock.Mock(
            return_value=vhdutils.ctypes.byref(
                vhdutils.wintypes.HANDLE()))
        self._vhdutils._close = mock.Mock()
        self._vhdutils._get_device_id_by_path = mock.Mock(return_value=2)

        vhdutils.virtdisk.ResizeVirtualDisk.return_value = int(
            resize_failed)

        if resize_failed:
            self.assertRaises(exception.VolumeBackendAPIException,
                              self._vhdutils.resize_vhd,
                              self._FAKE_VHD_PATH,
                              self._FAKE_VHD_SIZE)
        else:
            self._vhdutils.resize_vhd(self._FAKE_VHD_PATH,
                                      self._FAKE_VHD_SIZE)

        vhdutils.virtdisk.ResizeVirtualDisk.assert_called_with(
            vhdutils.ctypes.byref(vhdutils.wintypes.HANDLE()),
            vhdutils.RESIZE_VIRTUAL_DISK_FLAG_NONE,
            vhdutils.ctypes.byref(fake_params),
            None)
        self.assertTrue(self._vhdutils._close.called)

    def test_resize_vhd_success(self):
        self._test_resize_vhd()

    def test_resize_vhd_failed(self):
        self._test_resize_vhd(resize_failed=True)
