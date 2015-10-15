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
    _FAKE_FILE_HANDLE = 'fake_file_handle'
    _FAKE_RET_VAL = 0
    _FAKE_VHD_SIZE = 1024

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
        fake_ctypes.c_ulong = lambda x: x

        mock.patch.multiple(
            'cinder.volume.drivers.windows.vhdutils',
            ctypes=fake_ctypes, kernel32=mock.DEFAULT,
            wintypes=mock.DEFAULT, virtdisk=mock.DEFAULT,
            Win32_GUID=mock.DEFAULT,
            Win32_RESIZE_VIRTUAL_DISK_PARAMETERS=mock.DEFAULT,
            Win32_CREATE_VIRTUAL_DISK_PARAMETERS=mock.DEFAULT,
            Win32_VIRTUAL_STORAGE_TYPE=mock.DEFAULT,
            Win32_OPEN_VIRTUAL_DISK_PARAMETERS_V1=mock.DEFAULT,
            Win32_OPEN_VIRTUAL_DISK_PARAMETERS_V2=mock.DEFAULT,
            Win32_MERGE_VIRTUAL_DISK_PARAMETERS=mock.DEFAULT,
            Win32_GET_VIRTUAL_DISK_INFO_PARAMETERS=mock.DEFAULT,
            Win32_SET_VIRTUAL_DISK_INFO_PARAMETERS=mock.DEFAULT,
            create=True).start()

    def _test_create_vhd(self, src_path=None, max_internal_size=0,
                         parent_path=None, create_failed=False):
        self._vhdutils._get_device_id_by_path = mock.Mock(
            side_effect=(vhdutils.VIRTUAL_STORAGE_TYPE_DEVICE_VHD,
                         vhdutils.VIRTUAL_STORAGE_TYPE_DEVICE_VHDX))
        self._vhdutils._close = mock.Mock()

        fake_params = (
            vhdutils.Win32_CREATE_VIRTUAL_DISK_PARAMETERS.return_value)
        fake_vst = mock.Mock()
        fake_source_vst = mock.Mock()

        vhdutils.Win32_VIRTUAL_STORAGE_TYPE.side_effect = [
            fake_vst, None, fake_source_vst]
        vhdutils.virtdisk.CreateVirtualDisk.return_value = int(
            create_failed)

        if create_failed:
            self.assertRaises(exception.VolumeBackendAPIException,
                              self._vhdutils._create_vhd,
                              self._FAKE_DEST_PATH,
                              constants.VHD_TYPE_DYNAMIC,
                              src_path=src_path,
                              max_internal_size=max_internal_size,
                              parent_path=parent_path)
        else:
            self._vhdutils._create_vhd(self._FAKE_DEST_PATH,
                                       constants.VHD_TYPE_DYNAMIC,
                                       src_path=src_path,
                                       max_internal_size=max_internal_size,
                                       parent_path=parent_path)

        self.assertEqual(vhdutils.VIRTUAL_STORAGE_TYPE_DEVICE_VHD,
                         fake_vst.DeviceId)
        self.assertEqual(parent_path, fake_params.ParentPath)
        self.assertEqual(max_internal_size, fake_params.MaximumSize)

        if src_path:
            self.assertEqual(vhdutils.VIRTUAL_STORAGE_TYPE_DEVICE_VHDX,
                             fake_source_vst.DeviceId)
            self.assertEqual(src_path, fake_params.SourcePath)

        vhdutils.virtdisk.CreateVirtualDisk.assert_called_with(
            vhdutils.ctypes.byref(fake_vst),
            vhdutils.ctypes.c_wchar_p(self._FAKE_DEST_PATH),
            vhdutils.VIRTUAL_DISK_ACCESS_NONE, None,
            vhdutils.CREATE_VIRTUAL_DISK_FLAG_NONE, 0,
            vhdutils.ctypes.byref(fake_params), None,
            vhdutils.ctypes.byref(vhdutils.wintypes.HANDLE()))
        self.assertTrue(self._vhdutils._close.called)

    def test_create_vhd_exception(self):
        self._test_create_vhd(create_failed=True)

    def test_create_dynamic_vhd(self):
        self._test_create_vhd(max_internal_size=1 << 30)

    def test_create_differencing_vhd(self):
        self._test_create_vhd(parent_path=self._FAKE_VHD_PATH)

    def test_convert_vhd(self):
        self._test_create_vhd(src_path=self._FAKE_VHD_PATH)

    def _test_open(self, open_failed=False):
        fake_device_id = vhdutils.VIRTUAL_STORAGE_TYPE_DEVICE_VHD

        vhdutils.virtdisk.OpenVirtualDisk.return_value = int(open_failed)
        self._vhdutils._get_device_id_by_path = mock.Mock(
            return_value=fake_device_id)

        fake_vst = vhdutils.Win32_VIRTUAL_STORAGE_TYPE.return_value
        fake_params = 'fake_params'
        fake_access_mask = vhdutils.VIRTUAL_DISK_ACCESS_NONE
        fake_open_flag = vhdutils.OPEN_VIRTUAL_DISK_FLAG_NO_PARENTS

        if open_failed:
            self.assertRaises(exception.VolumeBackendAPIException,
                              self._vhdutils._open,
                              self._FAKE_VHD_PATH)
        else:
            self._vhdutils._open(self._FAKE_VHD_PATH,
                                 open_flag=fake_open_flag,
                                 open_access_mask=fake_access_mask,
                                 open_params=fake_params)

            vhdutils.virtdisk.OpenVirtualDisk.assert_called_with(
                vhdutils.ctypes.byref(fake_vst),
                vhdutils.ctypes.c_wchar_p(self._FAKE_VHD_PATH),
                fake_access_mask, fake_open_flag, fake_params,
                vhdutils.ctypes.byref(vhdutils.wintypes.HANDLE()))

            self.assertEqual(fake_device_id, fake_vst.DeviceId)

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
            return_value=self._FAKE_FILE_HANDLE)
        self._vhdutils._close = mock.Mock()

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
            self._FAKE_FILE_HANDLE,
            vhdutils.RESIZE_VIRTUAL_DISK_FLAG_NONE,
            vhdutils.ctypes.byref(fake_params),
            None)
        self.assertTrue(self._vhdutils._close.called)

    def test_resize_vhd_success(self):
        self._test_resize_vhd()

    def test_resize_vhd_failed(self):
        self._test_resize_vhd(resize_failed=True)

    def _test_merge_vhd(self, merge_failed=False):
        self._vhdutils._open = mock.Mock(
            return_value=self._FAKE_FILE_HANDLE)
        self._vhdutils._close = mock.Mock()

        fake_open_params = vhdutils.Win32_OPEN_VIRTUAL_DISK_PARAMETERS_V1()
        fake_params = vhdutils.Win32_MERGE_VIRTUAL_DISK_PARAMETERS()

        vhdutils.virtdisk.MergeVirtualDisk.return_value = int(
            merge_failed)
        vhdutils.Win32_RESIZE_VIRTUAL_DISK_PARAMETERS.return_value = (
            fake_params)

        if merge_failed:
            self.assertRaises(exception.VolumeBackendAPIException,
                              self._vhdutils.merge_vhd,
                              self._FAKE_VHD_PATH)
        else:
            self._vhdutils.merge_vhd(self._FAKE_VHD_PATH)

        self._vhdutils._open.assert_called_once_with(
            self._FAKE_VHD_PATH,
            open_params=vhdutils.ctypes.byref(fake_open_params))
        self.assertEqual(vhdutils.OPEN_VIRTUAL_DISK_VERSION_1,
                         fake_open_params.Version)
        self.assertEqual(2, fake_open_params.RWDepth)
        vhdutils.virtdisk.MergeVirtualDisk.assert_called_with(
            self._FAKE_FILE_HANDLE,
            vhdutils.MERGE_VIRTUAL_DISK_FLAG_NONE,
            vhdutils.ctypes.byref(fake_params),
            None)

    def test_merge_vhd_success(self):
        self._test_merge_vhd()

    def test_merge_vhd_failed(self):
        self._test_merge_vhd(merge_failed=True)

    def _test_get_vhd_info_member(self, get_vhd_info_failed=False):
        fake_params = vhdutils.Win32_GET_VIRTUAL_DISK_INFO_PARAMETERS()
        fake_info_size = vhdutils.ctypes.sizeof(fake_params)

        vhdutils.virtdisk.GetVirtualDiskInformation.return_value = (
            get_vhd_info_failed)
        self._vhdutils._close = mock.Mock()

        if get_vhd_info_failed:
            self.assertRaises(exception.VolumeBackendAPIException,
                              self._vhdutils._get_vhd_info_member,
                              self._FAKE_VHD_PATH,
                              vhdutils.GET_VIRTUAL_DISK_INFO_SIZE)
        else:
            self._vhdutils._get_vhd_info_member(
                self._FAKE_VHD_PATH,
                vhdutils.GET_VIRTUAL_DISK_INFO_SIZE)

        vhdutils.virtdisk.GetVirtualDiskInformation.assert_called_with(
            self._FAKE_VHD_PATH,
            vhdutils.ctypes.byref(
                vhdutils.ctypes.c_ulong(fake_info_size)),
            vhdutils.ctypes.byref(fake_params), 0)

    def test_get_vhd_info_member_success(self):
        self._test_get_vhd_info_member()

    def test_get_vhd_info_member_failed(self):
        self._test_get_vhd_info_member(get_vhd_info_failed=True)

    def test_get_vhd_info(self):
        fake_vhd_info = {'VirtualSize': self._FAKE_VHD_SIZE}
        fake_info_member = vhdutils.GET_VIRTUAL_DISK_INFO_SIZE

        self._vhdutils._open = mock.Mock(
            return_value=self._FAKE_FILE_HANDLE)
        self._vhdutils._close = mock.Mock()
        self._vhdutils._get_vhd_info_member = mock.Mock(
            return_value=fake_vhd_info)

        ret_val = self._vhdutils.get_vhd_info(self._FAKE_VHD_PATH,
                                              [fake_info_member])

        self.assertEqual(fake_vhd_info, ret_val)
        self._vhdutils._open.assert_called_once_with(
            self._FAKE_VHD_PATH,
            open_access_mask=vhdutils.VIRTUAL_DISK_ACCESS_GET_INFO)
        self._vhdutils._get_vhd_info_member.assert_called_with(
            self._FAKE_FILE_HANDLE, fake_info_member)
        self._vhdutils._close.assert_called_once_with(self._FAKE_FILE_HANDLE)

    def test_parse_vhd_info(self):
        fake_physical_size = self._FAKE_VHD_SIZE + 1
        fake_info_member = vhdutils.GET_VIRTUAL_DISK_INFO_SIZE
        fake_info = mock.Mock()
        fake_info.VhdInfo.Size._fields_ = [
            ("VirtualSize", vhdutils.wintypes.ULARGE_INTEGER),
            ("PhysicalSize", vhdutils.wintypes.ULARGE_INTEGER)]
        fake_info.VhdInfo.Size.VirtualSize = self._FAKE_VHD_SIZE
        fake_info.VhdInfo.Size.PhysicalSize = fake_physical_size

        ret_val = self._vhdutils._parse_vhd_info(fake_info, fake_info_member)
        expected = {'VirtualSize': self._FAKE_VHD_SIZE,
                    'PhysicalSize': fake_physical_size}

        self.assertEqual(expected, ret_val)

    def _test_reconnect_parent(self, reconnect_failed=False):
        fake_params = vhdutils.Win32_SET_VIRTUAL_DISK_INFO_PARAMETERS()
        fake_open_params = vhdutils.Win32_OPEN_VIRTUAL_DISK_PARAMETERS_V2()

        self._vhdutils._open = mock.Mock(return_value=self._FAKE_FILE_HANDLE)
        self._vhdutils._close = mock.Mock()
        vhdutils.virtdisk.SetVirtualDiskInformation.return_value = int(
            reconnect_failed)

        if reconnect_failed:
            self.assertRaises(exception.VolumeBackendAPIException,
                              self._vhdutils.reconnect_parent,
                              self._FAKE_VHD_PATH, self._FAKE_DEST_PATH)

        else:
            self._vhdutils.reconnect_parent(self._FAKE_VHD_PATH,
                                            self._FAKE_DEST_PATH)

        self._vhdutils._open.assert_called_once_with(
            self._FAKE_VHD_PATH,
            open_flag=vhdutils.OPEN_VIRTUAL_DISK_FLAG_NO_PARENTS,
            open_access_mask=vhdutils.VIRTUAL_DISK_ACCESS_NONE,
            open_params=vhdutils.ctypes.byref(fake_open_params))
        self.assertEqual(vhdutils.OPEN_VIRTUAL_DISK_VERSION_2,
                         fake_open_params.Version)
        self.assertFalse(fake_open_params.GetInfoOnly)
        vhdutils.virtdisk.SetVirtualDiskInformation.assert_called_once_with(
            self._FAKE_FILE_HANDLE, vhdutils.ctypes.byref(fake_params))
        self.assertEqual(self._FAKE_DEST_PATH, fake_params.ParentFilePath)

    def test_reconnect_parent_success(self):
        self._test_reconnect_parent()

    def test_reconnect_parent_failed(self):
        self._test_reconnect_parent(reconnect_failed=True)

    @mock.patch('sys.exc_info')
    @mock.patch.object(vhdutils, 'LOG')
    def test_run_and_check_output_fails_exc_info_set(self, mock_log,
                                                     mock_exc_info):
        # we can't use assertRaises because we're mocking sys.exc_info and
        # that messes up how assertRaises handles the exception
        try:
            self._vhdutils._run_and_check_output(lambda *args, **kwargs: 1)
            self.fail('Expected _run_and_check_output to fail.')
        except exception.VolumeBackendAPIException:
            pass
        mock_log.error.assert_called_once_with(mock.ANY, exc_info=True)

    @mock.patch('sys.exc_info', return_value=None)
    @mock.patch.object(vhdutils, 'LOG')
    def test_run_and_check_output_fails_exc_info_not_set(self, mock_log,
                                                         mock_exc_info):
        # we can't use assertRaises because we're mocking sys.exc_info and
        # that messes up how assertRaises handles the exception
        try:
            self._vhdutils._run_and_check_output(lambda *args, **kwargs: 1)
            self.fail('Expected _run_and_check_output to fail.')
        except exception.VolumeBackendAPIException:
            pass
        mock_log.error.assert_called_once_with(mock.ANY, exc_info=False)
