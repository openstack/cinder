# Copyright 2014 Cloudbase Solutions Srl
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
Utility class for VHD related operations.

Official VHD format specs can be retrieved at:
http://technet.microsoft.com/en-us/library/bb676673.aspx
See "Download the Specifications Without Registering"

Official VHDX format specs can be retrieved at:
http://www.microsoft.com/en-us/download/details.aspx?id=34750
"""
import ctypes
import os

if os.name == 'nt':
    from ctypes import windll
    from ctypes import wintypes

    kernel32 = windll.kernel32
    virtdisk = windll.virtdisk

from cinder import exception
from cinder.i18n import _
from cinder.openstack.common import log as logging
from cinder.volume.drivers.windows import constants

LOG = logging.getLogger(__name__)

if os.name == 'nt':
    class Win32_GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD),
                    ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD),
                    ("Data4", wintypes.BYTE * 8)]

    class Win32_VIRTUAL_STORAGE_TYPE(ctypes.Structure):
        _fields_ = [
            ('DeviceId', wintypes.DWORD),
            ('VendorId', Win32_GUID)
        ]

    class Win32_RESIZE_VIRTUAL_DISK_PARAMETERS(ctypes.Structure):
        _fields_ = [
            ('Version', wintypes.DWORD),
            ('NewSize', ctypes.c_ulonglong)
        ]

    class Win32_CREATE_VIRTUAL_DISK_PARAMETERS(ctypes.Structure):
        _fields_ = [
            ('Version', wintypes.DWORD),
            ('UniqueId', Win32_GUID),
            ('MaximumSize', ctypes.c_ulonglong),
            ('BlockSizeInBytes', wintypes.ULONG),
            ('SectorSizeInBytes', wintypes.ULONG),
            ('PhysicalSectorSizeInBytes', wintypes.ULONG),
            ('ParentPath', wintypes.LPCWSTR),
            ('SourcePath', wintypes.LPCWSTR),
            ('OpenFlags', wintypes.DWORD),
            ('ParentVirtualStorageType', Win32_VIRTUAL_STORAGE_TYPE),
            ('SourceVirtualStorageType', Win32_VIRTUAL_STORAGE_TYPE),
            ('ResiliencyGuid', Win32_GUID)
        ]

VIRTUAL_STORAGE_TYPE_DEVICE_ISO = 1
VIRTUAL_STORAGE_TYPE_DEVICE_VHD = 2
VIRTUAL_STORAGE_TYPE_DEVICE_VHDX = 3
VIRTUAL_DISK_ACCESS_NONE = 0
VIRTUAL_DISK_ACCESS_ALL = 0x003f0000
VIRTUAL_DISK_ACCESS_CREATE = 0x00100000
OPEN_VIRTUAL_DISK_FLAG_NONE = 0
RESIZE_VIRTUAL_DISK_FLAG_NONE = 0
RESIZE_VIRTUAL_DISK_VERSION_1 = 1
CREATE_VIRTUAL_DISK_VERSION_2 = 2
CREATE_VHD_PARAMS_DEFAULT_BLOCK_SIZE = 0
CREATE_VIRTUAL_DISK_FLAG_NONE = 0
CREATE_VIRTUAL_DISK_FLAG_FULL_PHYSICAL_ALLOCATION = 1


class VHDUtils(object):

    def __init__(self):
        self._ext_device_id_map = {
            'vhd': VIRTUAL_STORAGE_TYPE_DEVICE_VHD,
            'vhdx': VIRTUAL_STORAGE_TYPE_DEVICE_VHDX}
        self.create_virtual_disk_flags = {
            constants.VHD_TYPE_FIXED: (
                CREATE_VIRTUAL_DISK_FLAG_FULL_PHYSICAL_ALLOCATION),
            constants.VHD_TYPE_DYNAMIC: CREATE_VIRTUAL_DISK_FLAG_NONE
        }

        if os.name == 'nt':
            self._msft_vendor_id = (
                self.get_WIN32_VIRTUAL_STORAGE_TYPE_VENDOR_MSFT())

    @staticmethod
    def get_WIN32_VIRTUAL_STORAGE_TYPE_VENDOR_MSFT():
        guid = Win32_GUID()
        guid.Data1 = 0xec984aec
        guid.Data2 = 0xa0f9
        guid.Data3 = 0x47e9
        ByteArray8 = wintypes.BYTE * 8
        guid.Data4 = ByteArray8(0x90, 0x1f, 0x71, 0x41, 0x5a, 0x66, 0x34, 0x5b)
        return guid

    def _open(self, device_id, vhd_path):
        vst = Win32_VIRTUAL_STORAGE_TYPE()
        vst.DeviceId = device_id
        vst.VendorId = self._msft_vendor_id

        handle = wintypes.HANDLE()
        ret_val = virtdisk.OpenVirtualDisk(ctypes.byref(vst),
                                           ctypes.c_wchar_p(vhd_path),
                                           VIRTUAL_DISK_ACCESS_ALL,
                                           OPEN_VIRTUAL_DISK_FLAG_NONE,
                                           0, ctypes.byref(handle))
        if ret_val:
            raise exception.VolumeBackendAPIException(
                _("Opening virtual disk failed with error: %s") % ret_val)
        return handle

    def _close(self, handle):
        kernel32.CloseHandle(handle)

    def _get_device_id_by_path(self, vhd_path):
        ext = os.path.splitext(vhd_path)[1][1:].lower()
        device_id = self._ext_device_id_map.get(ext)
        if not device_id:
            raise exception.VolumeBackendAPIException(
                _("Unsupported virtual disk extension: %s") % ext)
        return device_id

    def resize_vhd(self, vhd_path, new_max_size):
        device_id = self._get_device_id_by_path(vhd_path)
        handle = self._open(device_id, vhd_path)

        params = Win32_RESIZE_VIRTUAL_DISK_PARAMETERS()
        params.Version = RESIZE_VIRTUAL_DISK_VERSION_1
        params.NewSize = new_max_size

        ret_val = virtdisk.ResizeVirtualDisk(
            handle,
            RESIZE_VIRTUAL_DISK_FLAG_NONE,
            ctypes.byref(params),
            None)
        self._close(handle)

        if ret_val:
            raise exception.VolumeBackendAPIException(
                _("Virtual disk resize failed with error: %s") % ret_val)

    def convert_vhd(self, src, dest, vhd_type):
        src_device_id = self._get_device_id_by_path(src)
        dest_device_id = self._get_device_id_by_path(dest)

        vst = Win32_VIRTUAL_STORAGE_TYPE()
        vst.DeviceId = dest_device_id
        vst.VendorId = self._msft_vendor_id

        params = Win32_CREATE_VIRTUAL_DISK_PARAMETERS()
        params.Version = CREATE_VIRTUAL_DISK_VERSION_2
        params.UniqueId = Win32_GUID()
        params.MaximumSize = 0
        params.BlockSizeInBytes = CREATE_VHD_PARAMS_DEFAULT_BLOCK_SIZE
        params.SectorSizeInBytes = 0x200
        params.PhysicalSectorSizeInBytes = 0x200
        params.ParentPath = None
        params.SourcePath = src
        params.OpenFlags = OPEN_VIRTUAL_DISK_FLAG_NONE
        params.ParentVirtualStorageType = Win32_VIRTUAL_STORAGE_TYPE()
        params.SourceVirtualStorageType = Win32_VIRTUAL_STORAGE_TYPE()
        params.SourceVirtualStorageType.DeviceId = src_device_id
        params.SourceVirtualStorageType.VendorId = self._msft_vendor_id
        params.ResiliencyGuid = Win32_GUID()

        handle = wintypes.HANDLE()
        create_virtual_disk_flag = self.create_virtual_disk_flags.get(vhd_type)

        ret_val = virtdisk.CreateVirtualDisk(
            ctypes.byref(vst),
            ctypes.c_wchar_p(dest),
            VIRTUAL_DISK_ACCESS_NONE,
            None,
            create_virtual_disk_flag,
            0,
            ctypes.byref(params),
            None,
            ctypes.byref(handle))
        self._close(handle)

        if ret_val:
            raise exception.VolumeBackendAPIException(
                _("Virtual disk conversion failed with error: %s") % ret_val)
